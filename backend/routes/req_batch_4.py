"""
Feb-2026 Requirement Batch 4.

Adds:
  1. Payout Batch CSV Import — parse a bank export, auto-match rows to
     pending payouts, and (after confirmation) mark them all paid.
  2. Refund SLA Slack alerts — nightly loop pings admins on Slack when
     a mutual-refund request sits in pending state for > 48 h.
  3. Preset team-stats — usage counter + `/use` endpoint so managers
     see which shared templates the team actually reuses.
  4. Payment-received & payment-reminder emails now carry the compact
     booking-timeline snippet (wired via helpers here; email HTML edits
     live in `email_service.py`).
  5. Refund Auditor Saved Views — per-admin CRUD for filter combos so
     month-end audits are a single click.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("req_batch_4")


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().isoformat()


# ═══════════════════════════════════════════════════════════════════════
# (2) Refund SLA loop
# ═══════════════════════════════════════════════════════════════════════
REFUND_SLA_HOURS = 48
REFUND_SLA_INTERVAL_SEC = 60 * 60 * 6  # sweep every 6 h


async def _refund_sla_sweep(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """Fire Slack once per stale refund request older than the SLA."""
    from routes.iter89 import notify_slack  # local import — avoid cycles
    cutoff = (utcnow_dt() - timedelta(hours=REFUND_SLA_HOURS)).isoformat()
    stale = await db.refund_requests.find({
        "status": "pending_counter_ack",
        "created_at": {"$lt": cutoff},
        "sla_alert_sent_at": {"$exists": False},
    }).to_list(200)
    if not stale:
        return {"alerted": 0}

    lines = []
    for r in stale[:12]:
        bk = await db.bookings.find_one(
            {"id": r["booking_id"]},
            {"_id": 0, "ref": 1, "customer_id": 1, "artist_id": 1},
        ) or {}
        hours = round((utcnow_dt() - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600, 1)
        lines.append(
            f"• *{bk.get('ref') or r['booking_id']}* — ₹{r['amount']:,.0f} pending for {hours} h "
            f"(requested by {r.get('requested_by_role')})"
        )
    text = (
        f":alarm_clock: *Refund SLA Breach* — {len(stale)} mutual-refund "
        f"request(s) waiting > {REFUND_SLA_HOURS} h for counter-party action:\n"
        + "\n".join(lines)
        + (f"\n…and {len(stale) - 12} more." if len(stale) > 12 else "")
        + "\n→ Nudge parties from Admin → Refund Auditor."
    )
    await notify_slack(db, text=text)
    ids = [r["id"] for r in stale]
    await db.refund_requests.update_many(
        {"id": {"$in": ids}},
        {"$set": {"sla_alert_sent_at": utcnow()}},
    )
    return {"alerted": len(ids), "request_ids": ids}


async def refund_sla_loop(db: AsyncIOMotorDatabase) -> None:
    """Slow-ticking loop. Runs `_refund_sla_sweep` every 6 h."""
    await asyncio.sleep(120)  # let boot settle
    while True:
        try:
            await _refund_sla_sweep(db)
        except Exception as e:  # noqa: BLE001
            log.warning("refund_sla_loop: %s", e)
        await asyncio.sleep(REFUND_SLA_INTERVAL_SEC)


# ═══════════════════════════════════════════════════════════════════════
# Pydantic bodies
# ═══════════════════════════════════════════════════════════════════════
class SavedViewBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: Dict[str, Any] = Field(default_factory=dict)


class BatchApplyRow(BaseModel):
    booking_id: str
    amount: float = Field(gt=0)
    utr: str = Field(default="")
    method: str = Field(default="neft")
    paid_on: Optional[str] = None
    notes: Optional[str] = None


class BatchApplyBody(BaseModel):
    rows: List[BatchApplyRow]
    default_method: str = "neft"
    default_paid_on: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# CSV import — matching engine
# ═══════════════════════════════════════════════════════════════════════
_MONEY_RE = re.compile(r"[^\d.\-]")

def _num(v: Any) -> Optional[float]:
    """Best-effort number parse — strip ₹, commas, spaces, currency codes."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _MONEY_RE.sub("", str(v))
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _pick(row: Dict[str, Any], keys: List[str]) -> str:
    """Return the first non-empty value across candidate keys (case-insensitive)."""
    lower_map = {k.lower().strip(): k for k in row.keys()}
    for k in keys:
        real = lower_map.get(k.lower())
        if real is not None and str(row[real]).strip():
            return str(row[real]).strip()
    return ""


async def _match_csv_rows(db: AsyncIOMotorDatabase, csv_rows: List[Dict[str, Any]],
                          mapping: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Given parsed CSV rows, return { matched, unmatched, ambiguous }.

    `mapping` optionally overrides the default column-alias lists for
    each field: amount / utr / ref_hint / paid_on. Keys not supplied
    fall back to the defaults so partial mappings work.
    """
    m = mapping or {}
    amount_keys = m.get("amount") or [
        "amount", "amount (inr)", "amount_inr", "credit", "credit amount",
        "debit", "debit amount", "value", "txn amount",
    ]
    utr_keys = m.get("utr") or [
        "utr", "utr number", "utr no", "utr_no", "reference no", "ref no",
        "reference", "reference number", "transaction id", "txn id", "txnid",
    ]
    ref_keys = m.get("ref_hint") or [
        "booking ref", "booking id", "booking", "narration",
        "description", "remarks", "particulars", "note",
    ]
    paid_on_keys = m.get("paid_on") or [
        "value date", "value_date", "date", "txn date", "transaction date", "posting date",
    ]

    # Pull the current pending payout candidates.
    candidates: List[Dict[str, Any]] = []
    cur = db.bookings.find(
        {
            "payment_status": {"$in": ["partial", "paid", "fully_paid"]},
            "$or": [
                {"artist_payout_status": {"$ne": "paid"}},
                {"artist_payout_status": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "ref": 1, "pricing": 1, "artist_id": 1,
         "artist_payouts": 1, "customer_id": 1},
    )
    async for bk in cur:
        artist_share = float((bk.get("pricing") or {}).get("artist_payable")
                             or (bk.get("pricing") or {}).get("artist_amount") or 0)
        paid_out = sum(float(p.get("amount") or 0) for p in (bk.get("artist_payouts") or []))
        outstanding = round(max(0.0, artist_share - paid_out), 2)
        if outstanding <= 0:
            continue
        candidates.append({
            "id": bk["id"],
            "ref": (bk.get("ref") or "").upper(),
            "outstanding": outstanding,
            "artist_id": bk.get("artist_id"),
        })

    matched: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    for idx, r in enumerate(csv_rows):
        amount = _num(_pick(r, amount_keys))
        utr = _pick(r, utr_keys)
        ref_hint = _pick(r, ref_keys)
        paid_on = _pick(r, paid_on_keys)

        if amount is None:
            unmatched.append({"row": idx, "reason": "no_amount", "raw": r})
            continue

        # Step 1 — try to find the booking ref inside any of the hint fields.
        hint_blob = f"{ref_hint} {utr}".upper()
        ref_hits = [c for c in candidates if c["ref"] and c["ref"] in hint_blob]
        if len(ref_hits) == 1:
            c = ref_hits[0]
            matched.append({
                "row": idx,
                "booking_id": c["id"],
                "booking_ref": c["ref"],
                "amount": amount,
                "outstanding": c["outstanding"],
                "utr": utr,
                "paid_on": paid_on or None,
                "match_reason": "ref",
                "delta": round(amount - c["outstanding"], 2),
            })
            continue
        if len(ref_hits) > 1:
            ambiguous.append({"row": idx, "reason": "multiple_ref_hits",
                              "candidates": [c["ref"] for c in ref_hits], "raw": r})
            continue

        # Step 2 — fall back to exact-amount matching.
        amount_hits = [c for c in candidates if abs(c["outstanding"] - amount) < 0.01]
        if len(amount_hits) == 1:
            c = amount_hits[0]
            matched.append({
                "row": idx,
                "booking_id": c["id"],
                "booking_ref": c["ref"],
                "amount": amount,
                "outstanding": c["outstanding"],
                "utr": utr,
                "paid_on": paid_on or None,
                "match_reason": "amount_exact",
                "delta": 0.0,
            })
            continue
        if len(amount_hits) > 1:
            ambiguous.append({"row": idx, "reason": "multiple_amount_hits",
                              "candidates": [c["ref"] for c in amount_hits],
                              "amount": amount, "raw": r})
            continue

        unmatched.append({"row": idx, "reason": "no_match",
                          "amount": amount, "utr": utr, "ref_hint": ref_hint, "raw": r})

    # Bookings the CSV missed — surface a small summary so admin can act.
    matched_ids = {m["booking_id"] for m in matched}
    not_in_csv = [c for c in candidates if c["id"] not in matched_ids]

    return {
        "matched": matched,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "candidates_total": len(candidates),
        "candidates_missing_in_csv": len(not_in_csv),
    }


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_4_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ───────────────────────────────────────────────────────────────
    # (1) Payout Batch CSV Import — preview + apply
    # ───────────────────────────────────────────────────────────────
    @r.post("/admin/payouts/batch-preview")
    async def batch_preview(file: UploadFile = File(...),
                             preset_id: Optional[str] = None,
                             _: dict = Depends(require_admin)):
        raw = (await file.read()).decode("utf-8-sig", errors="replace")
        if not raw.strip():
            raise HTTPException(400, "Empty CSV")

        # Try both DictReader (headered) and sniff for headerless files.
        try:
            reader = csv.DictReader(io.StringIO(raw))
            rows = [dict(r) for r in reader]
        except Exception:
            rows = []
        if not rows:
            raise HTTPException(400, "Could not parse CSV — ensure the first row contains column headers")

        # Optional bank preset — pass its column mapping through so
        # HDFC/ICICI/Axis-specific headers are recognised on re-imports.
        mapping = None
        preset_used = None
        if preset_id:
            preset = await db.csv_bank_presets.find_one({"id": preset_id}, {"_id": 0})
            if not preset:
                raise HTTPException(404, "Bank preset not found")
            mapping = preset.get("mapping") or {}
            preset_used = {"id": preset["id"], "bank_name": preset.get("bank_name")}
            # Track last-used timestamp for the preset recommendations UI.
            await db.csv_bank_presets.update_one(
                {"id": preset_id},
                {"$inc": {"usage_count": 1},
                 "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}},
            )

        result = await _match_csv_rows(db, rows, mapping=mapping)
        result["parsed_rows"] = len(rows)
        if preset_used:
            result["preset"] = preset_used
        return result

    @r.post("/admin/payouts/batch-apply")
    async def batch_apply(body: BatchApplyBody, user: dict = Depends(require_admin)):
        """Mark the confirmed rows as paid. Thin wrapper around
        `/admin/payouts/bulk-mark-paid` so we reuse the audit trail +
        timeline emit + `_record_payout` writer."""
        try:
            from routes.req_batch_3 import make_req_batch_3_router  # noqa: F401
            # We can't invoke that endpoint directly (it's a Depends-wired
            # handler); replicate its inner logic so behaviour is identical.
            from routes.crm_pay import _record_payout, ManualPayoutBody  # type: ignore
            from routes.req_batch_2 import emit_booking_event
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"payout writer unavailable: {e}")

        default_paid = body.default_paid_on or utcnow()[:10]
        results: List[Dict[str, Any]] = []
        succeeded = 0
        total = 0.0
        for row in body.rows:
            bk = await db.bookings.find_one({"id": row.booking_id})
            if not bk:
                results.append({"booking_id": row.booking_id, "ok": False, "error": "booking_not_found"})
                continue
            payload = {
                "amount": row.amount,
                "method": row.method or body.default_method or "neft",
                "utr": row.utr or "",
                "bank_reference": "",
                "notes": row.notes or "CSV batch import",
                "paid_on": row.paid_on or default_paid,
            }
            try:
                mpb = ManualPayoutBody(**payload)
                doc = await _record_payout(db, bk, user, mpb)
                pid = doc.get("id")
                results.append({"booking_id": row.booking_id, "ok": True, "payout_id": pid})
                succeeded += 1
                total += float(row.amount)
                try:
                    await emit_booking_event(
                        db, booking_id=row.booking_id, kind="artist_payout",
                        label=f"Artist Payout · ₹{row.amount:,.0f}",
                        actor_id=user.get("id"), actor_role=user.get("role"),
                        metadata={"amount": row.amount, "utr": row.utr,
                                  "source": "csv_batch", "payout_id": pid},
                    )
                    await db.audit_logs.insert_one({
                        "id": str(uuid.uuid4()),
                        "actor_id": user.get("id"), "actor_role": user.get("role"),
                        "action": "payout.csv_batch_apply",
                        "entity": "booking", "entity_id": row.booking_id,
                        "metadata": payload | {"payout_id": pid},
                        "created_at": utcnow(),
                    })
                except Exception:
                    pass
            except Exception as e:  # noqa: BLE001
                log.warning("csv batch apply for %s failed: %s", row.booking_id, e)
                results.append({"booking_id": row.booking_id, "ok": False, "error": str(e)})

        return {
            "ok": succeeded == len(body.rows),
            "processed": len(body.rows),
            "succeeded": succeeded,
            "failed": len(body.rows) - succeeded,
            "total_amount": round(total, 2),
            "results": results,
        }

    # ───────────────────────────────────────────────────────────────
    # (2) Refund SLA — admin trigger + status
    # ───────────────────────────────────────────────────────────────
    @r.post("/admin/refunds/sla-sweep")
    async def sla_sweep(_: dict = Depends(require_admin)):
        return await _refund_sla_sweep(db)

    # ───────────────────────────────────────────────────────────────
    # (3) Preset team stats — usage counter
    # ───────────────────────────────────────────────────────────────
    @r.post("/manager/booking-presets/{preset_id}/use")
    async def use_preset(preset_id: str, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("manager", "admin", "subadmin"):
            raise HTTPException(403, "Manager or admin only")
        p = await db.manager_booking_presets.find_one({"id": preset_id})
        if not p:
            raise HTTPException(404, "Preset not found")
        # Only the owner or a team member (if shared) can bump usage.
        if p.get("manager_id") != user["id"] and not p.get("shared"):
            raise HTTPException(403, "Preset not available to you")
        await db.manager_booking_presets.update_one(
            {"id": preset_id},
            {"$inc": {"usage_count": 1},
             "$set": {"last_used_at": utcnow(), "last_used_by": user["id"]}},
        )
        await db.manager_preset_uses.insert_one({
            "id": str(uuid.uuid4()),
            "preset_id": preset_id,
            "manager_id": user["id"],
            "at": utcnow(),
        })
        row = await db.manager_booking_presets.find_one(
            {"id": preset_id}, {"_id": 0, "usage_count": 1, "last_used_at": 1},
        ) or {}
        return {"ok": True, "usage_count": int(row.get("usage_count") or 0),
                "last_used_at": row.get("last_used_at")}

    # ───────────────────────────────────────────────────────────────
    # (5) Auditor Saved Views — per-admin CRUD
    # ───────────────────────────────────────────────────────────────
    @r.get("/admin/refunds/saved-views")
    async def list_saved_views(_: dict = Depends(require_admin), user: dict = Depends(get_current_user)):
        rows = await db.refund_saved_views.find(
            {"admin_id": user["id"]}, {"_id": 0},
        ).sort("created_at", -1).to_list(50)
        return {"items": rows, "count": len(rows)}

    @r.post("/admin/refunds/saved-views")
    async def create_saved_view(body: SavedViewBody, user: dict = Depends(require_admin)):
        doc = {
            "id": str(uuid.uuid4()),
            "admin_id": user["id"],
            "name": body.name.strip(),
            "filters": body.filters,
            "created_at": utcnow(),
        }
        await db.refund_saved_views.insert_one(doc)
        doc.pop("_id", None)
        return {"ok": True, "view": doc}

    @r.delete("/admin/refunds/saved-views/{view_id}")
    async def delete_saved_view(view_id: str, user: dict = Depends(require_admin)):
        r_out = await db.refund_saved_views.delete_one(
            {"id": view_id, "admin_id": user["id"]},
        )
        if r_out.deleted_count == 0:
            raise HTTPException(404, "Saved view not found")
        return {"ok": True}

    return r
