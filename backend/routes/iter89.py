"""
Iter 89 — 4 focused additions on top of Iter 88:

  1. WA Templates admin-editable persistence (platform_settings.wa_templates)
  2. Team Leaderboard endpoint for managers (auto-scoped to caller)
  3. Slack alerting helper + hook fired when a payout retry hits max_attempts
  4. Report Snapshot History — every scheduled CSV persisted to disk with
     a downloadable listing endpoint.

All snapshots go to /app/uploads/report_snapshots which is the same disk
BookTalent uses for VPS-compatible local storage (Iter 77).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("iter89")


SNAPSHOTS_DIR = Path(os.environ.get("REPORT_SNAPSHOTS_DIR", "/app/uploads/report_snapshots"))
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Slack helper
# ═══════════════════════════════════════════════════════════════════════
async def notify_slack(db: AsyncIOMotorDatabase, *, text: str,
                        channel: Optional[str] = None,
                        blocks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Post a message to Slack via incoming webhook. Persists every
    attempt to `slack_logs` for audit — never raises so business flows
    keep going."""
    webhook = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    result: Dict[str, Any] = {"sent": False, "provider": "slack"}
    if not webhook:
        result["mock"] = True
        result["sent"] = True  # mock success so callers don't retry
        log.info("[MOCK Slack] %s", text)
    else:
        payload: Dict[str, Any] = {"text": text}
        if channel:
            payload["channel"] = channel
        if blocks:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(webhook, json=payload)
            result["status"] = r.status_code
            result["response"] = r.text[:500]
            result["sent"] = r.status_code < 400
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
    try:
        await db.slack_logs.insert_one({
            "id": str(uuid.uuid4()),
            "text": text, "channel": channel,
            **result, "at": utcnow_iso(),
        })
    except Exception:
        pass
    return result


async def slack_alert_max_retries(db: AsyncIOMotorDatabase, *, entry: Dict[str, Any]) -> None:
    """Called by the payout retry loop when an entry exhausts max_attempts.

    Kept as a public function so `routes/iter88.py::_payout_retry_tick`
    can call it after marking status=failed.
    """
    booking = await db.bookings.find_one(
        {"id": entry.get("booking_id")},
        {"ref": 1, "artist_id": 1, "customer_name": 1, "event_date": 1, "_id": 0},
    ) or {}
    artist_u = await db.users.find_one(
        {"id": booking.get("artist_id")},
        {"first_name": 1, "last_name": 1, "email": 1, "phone": 1, "_id": 0},
    ) or {}
    artist_p = await db.artist_profiles.find_one(
        {"user_id": booking.get("artist_id")}, {"stage_name": 1, "_id": 0},
    ) or {}
    artist_name = artist_p.get("stage_name") or f"{artist_u.get('first_name', '')} {artist_u.get('last_name', '')}".strip() or "Unknown"
    text = (
        f":rotating_light: *Payout retry FAILED after {entry.get('attempts', 0)} attempts*\n"
        f"Booking: `{booking.get('ref') or entry.get('booking_id')}` · Event: {booking.get('event_date', '—')}\n"
        f"Artist: *{artist_name}* ({artist_u.get('email', '—')})\n"
        f"Amount: ₹{entry.get('amount', 0):,.0f}\n"
        f"Last error: `{entry.get('last_error', 'unknown')}`\n"
        f"→ Manual intervention required in Admin → Payout Retry Queue."
    )
    await notify_slack(db, text=text)


# ═══════════════════════════════════════════════════════════════════════
# Report snapshot helpers
# ═══════════════════════════════════════════════════════════════════════
async def save_snapshot(db: AsyncIOMotorDatabase, *, kind: str, csv_bytes: bytes,
                         schedule_id: Optional[str] = None,
                         trigger: str = "scheduled",
                         actor_email: Optional[str] = None,
                         to_email: Optional[str] = None,
                         status: str = "sent",
                         error: str = "") -> Dict[str, Any]:
    """Persist a CSV report to disk + Mongo row.

    File layout: /app/uploads/report_snapshots/<yyyy>/<mm>/<uuid>.csv
    """
    now = datetime.now(timezone.utc)
    subdir = SNAPSHOTS_DIR / f"{now.year:04d}" / f"{now.month:02d}"
    subdir.mkdir(parents=True, exist_ok=True)
    snap_id = str(uuid.uuid4())
    filename = f"{kind}_{now.strftime('%Y%m%d_%H%M%S')}_{snap_id[:8]}.csv"
    path = subdir / filename
    path.write_bytes(csv_bytes)
    doc = {
        "id": snap_id,
        "kind": kind,
        "filename": filename,
        "rel_path": str(path.relative_to(SNAPSHOTS_DIR)),
        "size": len(csv_bytes),
        "schedule_id": schedule_id,
        "trigger": trigger,  # scheduled | run-now | manual
        "actor_email": actor_email,
        "to_email": to_email,
        "status": status,
        "error": error,
        "created_at": utcnow_iso(),
    }
    await db.report_snapshots.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
class WATemplatesBody(BaseModel):
    """Free-form mapping event.name → template_name."""
    templates: Dict[str, str] = Field(default_factory=dict)


def make_iter89_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ── 1. WA templates persistence ─────────────────────────────
    @r.patch("/admin/whatsapp/templates")
    async def save_wa_templates(body: WATemplatesBody, admin: dict = Depends(require_admin)):
        """Persist admin-approved template names to platform_settings so
        the send_whatsapp() call resolves them without env-var edits.

        Mongo treats `.` in field names as a nested-path selector, so we
        store the mapping under a `mapping` sub-document (dots inside a
        dict value are literal). Read path in _wa_template_from_db mirrors this.
        """
        clean = {k: (v or "").strip() for k, v in (body.templates or {}).items() if isinstance(v, str)}
        await db.platform_settings.update_one(
            {"id": "wa_templates"},
            {"$set": {"id": "wa_templates", "updated_at": utcnow_iso(),
                      "updated_by": admin.get("email"), "mapping": clean}},
            upsert=True,
        )
        return {"ok": True, "count": len(clean)}

    # ── 2. Manager team leaderboard (manager or admin) ──────────
    @r.get("/manager/leaderboard")
    async def manager_leaderboard(
        month: Optional[str] = Query(None, description="YYYY-MM (default = current)"),
        user: dict = Depends(get_current_user),
    ):
        if user.get("role") not in ("admin", "manager"):
            raise HTTPException(403, "Manager or admin only")
        # Reuse the scorecard logic — call it directly so ranking stays
        # in one place. Import lazily to avoid a circular reference.
        from routes.iter88 import make_iter88_router  # noqa: F401  (side-effect free)
        # We re-compute here instead of doing an HTTP call to keep it cheap.
        from datetime import datetime as _dt
        now = _dt.now(timezone.utc)
        if month:
            try:
                y, m = [int(x) for x in month.split("-")]
            except Exception:
                raise HTTPException(400, "month must be YYYY-MM")
        else:
            y, m = now.year, now.month
        start = _dt(y, m, 1, tzinfo=timezone.utc).isoformat()
        if m == 12:
            next_month = _dt(y + 1, 1, 1, tzinfo=timezone.utc).isoformat()
        else:
            next_month = _dt(y, m + 1, 1, tzinfo=timezone.utc).isoformat()

        managers = await db.users.find(
            {"role": "manager"},
            {"id": 1, "email": 1, "first_name": 1, "last_name": 1,
             "monthly_lead_target": 1, "monthly_revenue_target": 1},
        ).to_list(500)

        rows: List[Dict[str, Any]] = []
        for mgr in managers:
            mid = mgr["id"]
            leads_won = await db.leads.count_documents({
                "assigned_manager_id": mid, "stage": "closed",
                "updated_at": {"$gte": start, "$lt": next_month},
            })
            leads_lost = await db.leads.count_documents({
                "assigned_manager_id": mid, "stage": "lost_cancelled",
                "updated_at": {"$gte": start, "$lt": next_month},
            })
            revenue = 0.0
            async for b in db.bookings.find({
                "assigned_manager_id": mid,
                "status": {"$in": ["confirmed", "completed", "reviewed"]},
                "event_date": {"$gte": start[:10], "$lt": next_month[:10]},
            }, {"_id": 0, "pricing": 1}):
                revenue += float((b.get("pricing") or {}).get("total", 0) or 0)
            conv = round((leads_won / (leads_won + leads_lost)) * 100, 1) if (leads_won + leads_lost) else 0
            rows.append({
                "manager_id": mid,
                "manager_name": f"{mgr.get('first_name', '')} {mgr.get('last_name', '')}".strip() or (mgr.get("email") or "").split("@")[0],
                "leads_won": leads_won,
                "leads_lost": leads_lost,
                "conversion_pct": conv,
                "revenue": round(revenue, 2),
                "monthly_lead_target": int(mgr.get("monthly_lead_target") or 0),
                "monthly_revenue_target": float(mgr.get("monthly_revenue_target") or 0),
                "is_me": mid == user.get("id"),
            })

        # Rank by revenue desc, then leads_won desc as tie-breaker
        rows.sort(key=lambda x: (-x["revenue"], -x["leads_won"]))
        for i, row in enumerate(rows):
            row["rank"] = i + 1
            row["rank_medal"] = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else ""

        my_rank = None
        for row in rows:
            if row["is_me"]:
                my_rank = row["rank"]
                break
        return {
            "items": rows, "count": len(rows), "month": f"{y:04d}-{m:02d}",
            "my_rank": my_rank,
            "totals": {
                "revenue": sum(r["revenue"] for r in rows),
                "leads_won": sum(r["leads_won"] for r in rows),
            },
        }

    # ── 3. Report Snapshot History ───────────────────────────────
    @r.get("/admin/report-snapshots")
    async def list_snapshots(
        kind: Optional[str] = None,
        schedule_id: Optional[str] = None,
        limit: int = Query(100, ge=1, le=500),
        _: dict = Depends(require_admin),
    ):
        q: Dict[str, Any] = {}
        if kind:
            q["kind"] = kind
        if schedule_id:
            q["schedule_id"] = schedule_id
        rows = await db.report_snapshots.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
        return {"items": rows, "count": len(rows)}

    @r.get("/admin/report-snapshots/{snapshot_id}/download")
    async def download_snapshot(snapshot_id: str, _: dict = Depends(require_admin)):
        snap = await db.report_snapshots.find_one({"id": snapshot_id})
        if not snap:
            raise HTTPException(404, "Snapshot not found")
        path = SNAPSHOTS_DIR / snap["rel_path"]
        if not path.exists():
            raise HTTPException(410, "Snapshot file has been deleted from disk")
        return FileResponse(
            str(path),
            media_type="text/csv",
            filename=snap["filename"],
        )

    @r.delete("/admin/report-snapshots/{snapshot_id}")
    async def delete_snapshot(snapshot_id: str, _: dict = Depends(require_admin)):
        snap = await db.report_snapshots.find_one({"id": snapshot_id})
        if not snap:
            raise HTTPException(404, "Snapshot not found")
        path = SNAPSHOTS_DIR / snap["rel_path"]
        if path.exists():
            path.unlink(missing_ok=True)
        await db.report_snapshots.delete_one({"id": snapshot_id})
        return {"ok": True}

    # ── 4. Slack test-send (admin diagnostic) ────────────────────
    @r.post("/admin/slack/test")
    async def slack_test(text: str = "BookTalent Slack integration test", _: dict = Depends(require_admin)):
        result = await notify_slack(db, text=text)
        return result

    return r
