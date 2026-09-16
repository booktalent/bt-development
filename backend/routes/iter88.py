"""
Iter 88 — Payout auto-retry + Report scheduling + Manager scorecard.

Three thin verticals bundled into one router for reviewability:

1. Payout Retry Queue (Sec 42, complements Iter 84 manual payouts)
   -------------------------------------------------------------
   * Whenever an auto-payout attempt fails (Easebuzz 5xx, network,
     validation), we enqueue a row in `payout_retry_queue`.
   * Background loop `payout_retry_loop` picks up due rows every N min
     with exponential backoff (5m, 15m, 45m, 2h, 6h) up to 5 attempts.
   * Admin can inspect / manually retry / cancel entries.

2. Report Schedules
   -----------------
   * Admin picks a report (artist-bookings, manager-leads, waivers), a
     cadence (daily/weekly/monthly) and a day+hour (IST). We regenerate
     the CSV, attach it to an email, and send via the existing SMTP path.
   * Loop scans every 15 min → next-due schedules → dispatches → stamps
     `last_sent_at` so we never double-send.

3. Manager Scorecard
   ------------------
   * `GET /admin/reports/manager-scorecard?month=YYYY-MM` returns each
     manager with won/lost/in_pipeline counts + total revenue driven
     (bookings assigned via those leads) versus a `monthly_target` per
     manager (stored on the user doc — admin can PATCH it).
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("iter88")


# SEC-002 — CSV formula-injection guard; use the shared helper (csv_safe.py).
from csv_safe import safe_row  # noqa: E402


def _safe_row(r: Dict[str, Any], columns: List[str]) -> List[Any]:
    return safe_row([r.get(c, "") for c in columns])


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


# Retry backoff schedule (in seconds) — index = attempt number
RETRY_BACKOFF = [5 * 60, 15 * 60, 45 * 60, 2 * 3600, 6 * 3600]
MAX_ATTEMPTS = len(RETRY_BACKOFF)


# ═══════════════════════════════════════════════════════════════════════
# Helpers — payout retry
# ═══════════════════════════════════════════════════════════════════════
async def enqueue_payout_retry(db, *, booking_id: str, amount: float, reason: str,
                                triggered_by: Optional[str] = None) -> Dict[str, Any]:
    """Public entry point — call this from any failed auto-payout attempt."""
    doc = {
        "id": str(uuid.uuid4()),
        "booking_id": booking_id,
        "amount": float(amount),
        "attempts": 0,
        "max_attempts": MAX_ATTEMPTS,
        "next_attempt_at": (utcnow_dt() + timedelta(seconds=RETRY_BACKOFF[0])).isoformat(),
        "last_error": reason,
        "status": "queued",  # queued | in_progress | succeeded | failed | cancelled
        "triggered_by": triggered_by,
        "created_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
        "history": [{"at": utcnow_iso(), "event": "enqueued", "reason": reason}],
    }
    await db.payout_retry_queue.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _attempt_payout(db, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt one auto-payout. Returns dict with 'ok' bool and 'reason'.
    The actual Easebuzz call is behind the same stub as Iter 84 — until
    real payout creds are added, this deliberately fails so ops can see
    the queue working end-to-end with a live retry cycle."""
    booking = await db.bookings.find_one({"id": entry["booking_id"]}) or {}
    if not booking:
        return {"ok": False, "reason": "booking not found — will not retry", "terminal": True}
    if booking.get("artist_payout_status") == "paid":
        return {"ok": True, "reason": "already paid (out of band)"}
    payout_key = os.environ.get("EASEBUZZ_PAYOUT_KEY", "").strip()
    payout_salt = os.environ.get("EASEBUZZ_PAYOUT_SALT", "").strip()
    if not (payout_key and payout_salt):
        return {"ok": False, "reason": "EASEBUZZ_PAYOUT_KEY/SALT not configured"}
    # TODO: real Easebuzz Payouts API call goes here.
    return {"ok": False, "reason": "auto payout implementation pending"}


async def payout_retry_loop(db: AsyncIOMotorDatabase) -> None:
    """Started as a background task on server boot."""
    interval = int(os.environ.get("PAYOUT_RETRY_MINUTES", "5"))
    log.info("Payout retry loop starting (every %d min)", interval)
    while True:
        try:
            await _payout_retry_tick(db)
        except Exception as e:
            log.error("payout retry tick failed: %s", e)
        await asyncio.sleep(interval * 60)


async def _payout_retry_tick(db: AsyncIOMotorDatabase) -> None:
    now_iso = utcnow_iso()
    cursor = db.payout_retry_queue.find({
        "status": "queued",
        "next_attempt_at": {"$lte": now_iso},
    }).sort("next_attempt_at", 1).limit(20)
    async for entry in cursor:
        entry_id = entry["id"]
        # Move to in_progress to prevent double-pickup
        await db.payout_retry_queue.update_one(
            {"id": entry_id, "status": "queued"},
            {"$set": {"status": "in_progress", "updated_at": utcnow_iso()}},
        )
        result = await _attempt_payout(db, entry)
        new_attempts = int(entry.get("attempts", 0)) + 1
        history_entry = {"at": utcnow_iso(), "event": "attempt",
                          "attempt": new_attempts, "result": result}
        if result.get("ok"):
            # Mark booking + queue as succeeded
            await db.bookings.update_one(
                {"id": entry["booking_id"]},
                {"$set": {"artist_payout_status": "paid",
                          "artist_payout_paid_at": utcnow_iso()}},
            )
            await db.payout_retry_queue.update_one(
                {"id": entry_id},
                {"$set": {"status": "succeeded", "attempts": new_attempts,
                          "updated_at": utcnow_iso()},
                 "$push": {"history": history_entry}},
            )
            continue
        # Failed — schedule next attempt or give up
        terminal = result.get("terminal") or new_attempts >= MAX_ATTEMPTS
        if terminal:
            await db.payout_retry_queue.update_one(
                {"id": entry_id},
                {"$set": {"status": "failed", "attempts": new_attempts,
                          "last_error": result.get("reason", "unknown"),
                          "updated_at": utcnow_iso()},
                 "$push": {"history": history_entry}},
            )
            # Iter 89 — Slack alert on final failure so ops can jump in.
            try:
                from routes.iter89 import slack_alert_max_retries as _sl
                final_entry = await db.payout_retry_queue.find_one({"id": entry_id}) or entry
                await _sl(db, entry=final_entry)
            except Exception as e:  # noqa: BLE001
                log.warning("slack alert for max_retries failed: %s", e)
        else:
            backoff = RETRY_BACKOFF[min(new_attempts, MAX_ATTEMPTS - 1)]
            next_at = (utcnow_dt() + timedelta(seconds=backoff)).isoformat()
            await db.payout_retry_queue.update_one(
                {"id": entry_id},
                {"$set": {"status": "queued", "attempts": new_attempts,
                          "next_attempt_at": next_at,
                          "last_error": result.get("reason", "unknown"),
                          "updated_at": utcnow_iso()},
                 "$push": {"history": history_entry}},
            )


# ═══════════════════════════════════════════════════════════════════════
# Helpers — report scheduling
# ═══════════════════════════════════════════════════════════════════════
REPORT_KINDS = {"artist_bookings", "manager_leads", "platform_waivers"}
FREQUENCIES = {"daily", "weekly", "monthly"}


def _next_due(freq: str, day_of_week: Optional[int], hour_ist: int, from_dt: datetime) -> datetime:
    """Compute the next-run datetime (UTC) for a schedule.

    day_of_week is 0-6 with Monday=0 (matches Python weekday()).
    hour_ist is 0-23 in Indian Standard Time.
    """
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = from_dt + ist_offset
    if freq == "daily":
        candidate = now_ist.replace(hour=hour_ist, minute=0, second=0, microsecond=0)
        if candidate <= now_ist:
            candidate += timedelta(days=1)
    elif freq == "weekly":
        dow = day_of_week if day_of_week is not None else 0
        days_ahead = (dow - now_ist.weekday()) % 7
        candidate = (now_ist + timedelta(days=days_ahead)).replace(
            hour=hour_ist, minute=0, second=0, microsecond=0)
        if candidate <= now_ist:
            candidate += timedelta(days=7)
    else:  # monthly — run on the 1st of every month
        year = now_ist.year
        month = now_ist.month
        candidate = now_ist.replace(day=1, hour=hour_ist, minute=0, second=0, microsecond=0)
        if candidate <= now_ist:
            month = month + 1 if month < 12 else 1
            year = year + 1 if month == 1 else year
            candidate = candidate.replace(year=year, month=month)
    # Convert back to UTC
    return candidate - ist_offset


async def _generate_report_csv(db, kind: str) -> bytes:
    """Regenerate the CSV bytes for a given report kind by calling the
    same aggregation logic used by the live endpoints (imported here
    to keep behaviour identical)."""
    from routes.reports import make_reports_router  # circular-safe at call time
    # We don't need the router — we call the underlying aggregations directly.
    if kind == "artist_bookings":
        return await _csv_artist_bookings(db)
    if kind == "manager_leads":
        return await _csv_manager_leads(db)
    if kind == "platform_waivers":
        return await _csv_waivers(db)
    raise ValueError(f"Unknown report kind: {kind}")


async def _csv_artist_bookings(db) -> bytes:
    """Duplicates routes/reports.py logic — intentional to avoid coupling
    the HTTP layer to background jobs."""
    from collections import defaultdict
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "artist_id": "", "artist_name": "", "artist_email": "",
        "bookings_count": 0, "gross_revenue": 0.0, "artist_payable": 0.0,
        "platform_fee": 0.0, "gst": 0.0, "paid_count": 0, "pending_payout_count": 0,
    })
    async for b in db.bookings.find(
        {"status": {"$in": ["confirmed", "started", "completed", "reviewed"]}},
        {"_id": 0},
    ):
        aid = b.get("artist_id") or "unknown"
        row = agg[aid]
        row["artist_id"] = aid
        p = b.get("pricing") or {}
        row["bookings_count"] += 1
        row["gross_revenue"] += float(p.get("total", 0) or 0)
        row["artist_payable"] += float(p.get("artist_payable", p.get("artist_fee", 0)) or 0)
        row["platform_fee"] += float(p.get("platform_fee", 0) or 0)
        row["gst"] += float(p.get("gst", 0) or 0)
        if b.get("artist_payout_status") == "paid":
            row["paid_count"] += 1
        else:
            row["pending_payout_count"] += 1
    for aid, row in agg.items():
        u = await db.users.find_one({"id": aid}, {"first_name": 1, "last_name": 1, "email": 1}) or {}
        p = await db.artist_profiles.find_one({"user_id": aid}, {"stage_name": 1}) or {}
        row["artist_name"] = p.get("stage_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Unknown"
        row["artist_email"] = u.get("email", "")
    rows = sorted(agg.values(), key=lambda x: x["gross_revenue"], reverse=True)
    columns = ["artist_id", "artist_name", "artist_email", "bookings_count",
               "gross_revenue", "artist_payable", "platform_fee", "gst",
               "paid_count", "pending_payout_count"]
    buf = io.StringIO()
    w = csv.writer(buf); w.writerow(columns)
    for r in rows:
        w.writerow(_safe_row(r, columns))
    return buf.getvalue().encode("utf-8")


async def _csv_manager_leads(db) -> bytes:
    STAGES = ["new_lead", "contacted", "requirement_received", "artist_suggested",
              "quotation_sent", "negotiation", "booking_pending", "booking_confirmed",
              "payment_pending", "event_upcoming", "event_completed",
              "closed", "lost_cancelled"]
    managers = await db.users.find({"role": "manager"},
        {"id": 1, "email": 1, "first_name": 1, "last_name": 1}).to_list(500)
    rows = []
    for m in managers:
        row = {
            "manager_id": m["id"], "manager_email": m.get("email", ""),
            "manager_name": f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
            "total_leads": 0, "won": 0, "lost": 0, "in_pipeline": 0,
        }
        for s in STAGES:
            cnt = await db.leads.count_documents({"assigned_manager_id": m["id"], "stage": s})
            row[f"stage_{s}"] = cnt
            row["total_leads"] += cnt
            if s == "closed": row["won"] += cnt
            elif s == "lost_cancelled": row["lost"] += cnt
            else: row["in_pipeline"] += cnt
        denom = row["won"] + row["lost"]
        row["conversion_pct"] = round((row["won"] / denom) * 100, 1) if denom else 0
        rows.append(row)
    rows.sort(key=lambda x: x["total_leads"], reverse=True)
    columns = ["manager_id", "manager_email", "manager_name", "total_leads",
               "won", "lost", "in_pipeline", "conversion_pct"] + [f"stage_{s}" for s in STAGES]
    buf = io.StringIO()
    w = csv.writer(buf); w.writerow(columns)
    for r in rows:
        w.writerow(_safe_row(r, columns))
    return buf.getvalue().encode("utf-8")


async def _csv_waivers(db) -> bytes:
    rows = []
    async for b in db.bookings.find({
        "$or": [
            {"pricing.platform_fee_waived": True},
            {"pricing.platform_fee": 0, "pricing.total": {"$gt": 0}},
        ]
    }, {"_id": 0}):
        pricing = b.get("pricing") or {}
        settings = await db.platform_settings.find_one({"id": "platform"}) or {}
        pct = float(settings.get("platform_fee_percent", 5))
        base = float(pricing.get("package_fee", 0) or 0) + float(pricing.get("addons_total", 0) or 0)
        wb = round(base * pct / 100, 2)
        actual = float(pricing.get("platform_fee", 0) or 0)
        rows.append({
            "ref": b.get("ref"), "event_date": b.get("event_date"),
            "artist_id": b.get("artist_id"), "customer_name": b.get("customer_name", ""),
            "gross_total": float(pricing.get("total", 0) or 0),
            "actual_platform_fee": actual, "would_be_platform_fee": wb,
            "waived_amount": max(0, round(wb - actual, 2)),
        })
    columns = ["ref", "event_date", "artist_id", "customer_name", "gross_total",
               "actual_platform_fee", "would_be_platform_fee", "waived_amount"]
    buf = io.StringIO()
    w = csv.writer(buf); w.writerow(columns)
    for r in rows:
        w.writerow(_safe_row(r, columns))
    return buf.getvalue().encode("utf-8")


async def _email_report_csv(*, to_email: str, kind: str, csv_bytes: bytes) -> Dict[str, Any]:
    """Send the CSV as an attachment via existing SMTP. Uses smtplib
    directly to leverage the same manager@booktalent.in credentials."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("SMTP_FROM_EMAIL", user)
    from_name = os.environ.get("SMTP_FROM_NAME", "BookTalent")
    if not (user and pwd):
        return {"sent": False, "reason": "SMTP not configured"}

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_email
    label = kind.replace("_", " ").title()
    today = utcnow_dt().strftime("%Y-%m-%d")
    msg["Subject"] = f"[BookTalent] Scheduled Report — {label} ({today})"
    body = (f"Hi,\n\nAttached is your scheduled {label} report for {today}.\n\n"
             f"You can manage report schedules from Admin → Settings → Scheduled Reports.\n\n"
             f"— BookTalent Ops")
    msg.attach(MIMEText(body, "plain"))

    part = MIMEApplication(csv_bytes, Name=f"{kind}_{today}.csv")
    part["Content-Disposition"] = f'attachment; filename="{kind}_{today}.csv"'
    msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.sendmail(from_addr, [to_email], msg.as_string())
        return {"sent": True}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "reason": str(e)}


async def report_schedule_loop(db: AsyncIOMotorDatabase) -> None:
    """Every 15 min, find schedules whose `next_run_at` has arrived and
    fire them."""
    interval = int(os.environ.get("REPORT_SCHEDULE_MINUTES", "15"))
    log.info("Report schedule loop starting (every %d min)", interval)
    while True:
        try:
            await _report_schedule_tick(db)
        except Exception as e:
            log.error("report schedule tick failed: %s", e)
        await asyncio.sleep(interval * 60)


async def _report_schedule_tick(db: AsyncIOMotorDatabase) -> None:
    now_iso = utcnow_iso()
    cursor = db.report_schedules.find({
        "enabled": True,
        "next_run_at": {"$lte": now_iso},
    }).limit(50)
    async for sched in cursor:
        try:
            csv_bytes = await _generate_report_csv(db, sched["kind"])
            result = await _email_report_csv(
                to_email=sched["email"], kind=sched["kind"], csv_bytes=csv_bytes,
            )
            # Iter 89 — persist snapshot for later download.
            try:
                from routes.iter89 import save_snapshot as _snap
                await _snap(
                    db, kind=sched["kind"], csv_bytes=csv_bytes,
                    schedule_id=sched["id"], trigger="scheduled",
                    to_email=sched["email"],
                    status="sent" if result.get("sent") else "failed",
                    error=result.get("reason", ""),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("snapshot save failed for schedule %s: %s", sched.get("id"), e)
            next_dt = _next_due(sched["frequency"],
                                sched.get("day_of_week"),
                                int(sched.get("hour_ist", 8)),
                                utcnow_dt())
            await db.report_schedules.update_one(
                {"id": sched["id"]},
                {"$set": {
                    "last_run_at": utcnow_iso(),
                    "last_run_status": "sent" if result.get("sent") else "failed",
                    "last_run_error": result.get("reason", ""),
                    "next_run_at": next_dt.isoformat(),
                    "updated_at": utcnow_iso(),
                }},
            )
        except Exception as e:
            log.error("failed to run schedule %s: %s", sched.get("id"), e)


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
class ScheduleBody(BaseModel):
    kind: Literal["artist_bookings", "manager_leads", "platform_waivers"]
    email: str = Field(min_length=3, max_length=200)
    frequency: Literal["daily", "weekly", "monthly"]
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    hour_ist: int = Field(8, ge=0, le=23)
    enabled: bool = True


class ManagerTargetBody(BaseModel):
    monthly_lead_target: int = Field(ge=0)
    monthly_revenue_target: float = Field(ge=0)


def make_iter88_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ─── 1. Payout retry queue admin endpoints ─────────────────────
    @r.get("/admin/payouts/retry-queue")
    async def list_retry_queue(
        status: Optional[str] = Query(None, regex="^(queued|in_progress|succeeded|failed|cancelled)$"),
        _: dict = Depends(require_admin),
    ):
        q: Dict[str, Any] = {}
        if status:
            q["status"] = status
        rows = await db.payout_retry_queue.find(q, {"_id": 0}).sort("updated_at", -1).to_list(300)
        # Summary counts (all statuses)
        summary: Dict[str, int] = {}
        for s in ("queued", "in_progress", "succeeded", "failed", "cancelled"):
            summary[s] = await db.payout_retry_queue.count_documents({"status": s})
        return {"items": rows, "count": len(rows), "summary": summary}

    @r.post("/admin/payouts/retry-queue/{entry_id}/retry")
    async def force_retry(entry_id: str, _: dict = Depends(require_admin)):
        """Move a failed/cancelled entry back to queued for immediate pickup."""
        entry = await db.payout_retry_queue.find_one({"id": entry_id})
        if not entry:
            raise HTTPException(404, "Retry entry not found")
        await db.payout_retry_queue.update_one(
            {"id": entry_id},
            {"$set": {"status": "queued",
                       "next_attempt_at": utcnow_iso(),
                       "updated_at": utcnow_iso()},
             "$push": {"history": {"at": utcnow_iso(), "event": "force_retry"}}},
        )
        return {"ok": True}

    @r.post("/admin/payouts/retry-queue/{entry_id}/cancel")
    async def cancel_retry(entry_id: str, _: dict = Depends(require_admin)):
        entry = await db.payout_retry_queue.find_one({"id": entry_id})
        if not entry:
            raise HTTPException(404, "Retry entry not found")
        if entry.get("status") == "succeeded":
            raise HTTPException(400, "Cannot cancel — already succeeded")
        await db.payout_retry_queue.update_one(
            {"id": entry_id},
            {"$set": {"status": "cancelled", "updated_at": utcnow_iso()},
             "$push": {"history": {"at": utcnow_iso(), "event": "cancelled"}}},
        )
        return {"ok": True}

    @r.post("/admin/payouts/retry-queue/enqueue")
    async def admin_enqueue(booking_id: str, amount: float, reason: str = "manual",
                             admin: dict = Depends(require_admin)):
        """Admin can manually enqueue a booking for auto-payout retries."""
        row = await enqueue_payout_retry(
            db, booking_id=booking_id, amount=amount, reason=reason,
            triggered_by=admin.get("email"),
        )
        return row

    # ─── 2. Report schedules CRUD ─────────────────────────────────
    @r.get("/admin/report-schedules")
    async def list_schedules(_: dict = Depends(require_admin)):
        rows = await db.report_schedules.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
        return {"items": rows, "count": len(rows)}

    @r.post("/admin/report-schedules")
    async def create_schedule(body: ScheduleBody, admin: dict = Depends(require_admin)):
        if body.frequency == "weekly" and body.day_of_week is None:
            raise HTTPException(400, "day_of_week is required for weekly schedules")
        doc = {
            "id": str(uuid.uuid4()),
            "kind": body.kind, "email": body.email,
            "frequency": body.frequency,
            "day_of_week": body.day_of_week,
            "hour_ist": body.hour_ist,
            "enabled": body.enabled,
            "created_by": admin.get("email"),
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "next_run_at": _next_due(body.frequency, body.day_of_week,
                                       body.hour_ist, utcnow_dt()).isoformat(),
            "last_run_at": None, "last_run_status": None, "last_run_error": "",
        }
        await db.report_schedules.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @r.patch("/admin/report-schedules/{schedule_id}")
    async def update_schedule(schedule_id: str, body: ScheduleBody, _: dict = Depends(require_admin)):
        cur = await db.report_schedules.find_one({"id": schedule_id})
        if not cur:
            raise HTTPException(404, "Schedule not found")
        upd = body.model_dump()
        upd["updated_at"] = utcnow_iso()
        upd["next_run_at"] = _next_due(body.frequency, body.day_of_week,
                                        body.hour_ist, utcnow_dt()).isoformat()
        await db.report_schedules.update_one({"id": schedule_id}, {"$set": upd})
        return {"ok": True}

    @r.delete("/admin/report-schedules/{schedule_id}")
    async def delete_schedule(schedule_id: str, _: dict = Depends(require_admin)):
        r_ = await db.report_schedules.delete_one({"id": schedule_id})
        return {"ok": True, "deleted": r_.deleted_count}

    @r.post("/admin/report-schedules/{schedule_id}/run-now")
    async def run_now(schedule_id: str, admin: dict = Depends(require_admin)):
        sched = await db.report_schedules.find_one({"id": schedule_id})
        if not sched:
            raise HTTPException(404, "Schedule not found")
        csv_bytes = await _generate_report_csv(db, sched["kind"])
        result = await _email_report_csv(to_email=sched["email"],
                                          kind=sched["kind"],
                                          csv_bytes=csv_bytes)
        # Iter 89 — persist a snapshot for run-now dispatches too.
        try:
            from routes.iter89 import save_snapshot as _snap
            await _snap(
                db, kind=sched["kind"], csv_bytes=csv_bytes,
                schedule_id=schedule_id, trigger="run-now",
                actor_email=admin.get("email"),
                to_email=sched["email"],
                status="sent" if result.get("sent") else "failed",
                error=result.get("reason", ""),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot save (run-now) failed: %s", e)
        await db.report_schedules.update_one(
            {"id": schedule_id},
            {"$set": {"last_run_at": utcnow_iso(),
                       "last_run_status": "sent" if result.get("sent") else "failed",
                       "last_run_error": result.get("reason", "")}},
        )
        return result

    # ─── 3. Manager Scorecard ─────────────────────────────────────
    @r.get("/admin/reports/manager-scorecard")
    async def manager_scorecard(
        month: Optional[str] = Query(None, description="YYYY-MM (default = current)"),
        _: dict = Depends(require_admin),
    ):
        # Resolve month range
        now = utcnow_dt()
        if month:
            try:
                y, m = month.split("-")
                y, m = int(y), int(m)
            except Exception:
                raise HTTPException(400, "month must be YYYY-MM")
        else:
            y, m = now.year, now.month
        start = datetime(y, m, 1, tzinfo=timezone.utc).isoformat()
        next_month = (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)).replace(tzinfo=timezone.utc).isoformat()

        managers = await db.users.find(
            {"role": "manager"},
            {"id": 1, "email": 1, "first_name": 1, "last_name": 1,
             "monthly_lead_target": 1, "monthly_revenue_target": 1},
        ).to_list(500)

        cards: List[Dict[str, Any]] = []
        for mgr in managers:
            mid = mgr["id"]
            leads_total = await db.leads.count_documents({
                "assigned_manager_id": mid,
                "created_at": {"$gte": start, "$lt": next_month},
            })
            leads_won = await db.leads.count_documents({
                "assigned_manager_id": mid, "stage": "closed",
                "updated_at": {"$gte": start, "$lt": next_month},
            })
            leads_lost = await db.leads.count_documents({
                "assigned_manager_id": mid, "stage": "lost_cancelled",
                "updated_at": {"$gte": start, "$lt": next_month},
            })
            # Revenue driven — bookings assigned to this manager confirmed in month
            revenue = 0.0
            async for b in db.bookings.find({
                "assigned_manager_id": mid,
                "status": {"$in": ["confirmed", "completed", "reviewed"]},
                "event_date": {"$gte": start[:10], "$lt": next_month[:10]},
            }, {"_id": 0, "pricing": 1}):
                revenue += float((b.get("pricing") or {}).get("total", 0) or 0)

            lead_target = int(mgr.get("monthly_lead_target") or 0)
            rev_target = float(mgr.get("monthly_revenue_target") or 0)
            lead_pct = round((leads_won / lead_target) * 100, 1) if lead_target else 0
            rev_pct = round((revenue / rev_target) * 100, 1) if rev_target else 0
            conv_pct = round((leads_won / (leads_won + leads_lost)) * 100, 1) if (leads_won + leads_lost) else 0

            cards.append({
                "manager_id": mid,
                "manager_email": mgr.get("email", ""),
                "manager_name": f"{mgr.get('first_name', '')} {mgr.get('last_name', '')}".strip(),
                "month": f"{y:04d}-{m:02d}",
                "leads_total": leads_total,
                "leads_won": leads_won,
                "leads_lost": leads_lost,
                "conversion_pct": conv_pct,
                "revenue_driven": round(revenue, 2),
                "monthly_lead_target": lead_target,
                "monthly_revenue_target": rev_target,
                "lead_progress_pct": min(200, lead_pct),   # clamp for UI (allow up to 200 to show over-perf)
                "revenue_progress_pct": min(200, rev_pct),
            })

        cards.sort(key=lambda c: c["revenue_driven"], reverse=True)
        return {"items": cards, "count": len(cards), "month": f"{y:04d}-{m:02d}"}

    @r.patch("/admin/managers/{manager_id}/targets")
    async def set_manager_targets(manager_id: str, body: ManagerTargetBody,
                                    admin: dict = Depends(require_admin)):
        mgr = await db.users.find_one({"id": manager_id, "role": "manager"})
        if not mgr:
            raise HTTPException(404, "Manager not found")
        await db.users.update_one(
            {"id": manager_id},
            {"$set": {"monthly_lead_target": body.monthly_lead_target,
                       "monthly_revenue_target": body.monthly_revenue_target,
                       "targets_updated_at": utcnow_iso(),
                       "targets_updated_by": admin.get("email")}},
        )
        return {"ok": True}

    # ─── 4. WhatsApp templates status (informational) ─────────────
    @r.get("/admin/whatsapp/templates-status")
    async def whatsapp_templates_status(_: dict = Depends(require_admin)):
        """Show which templates are configured (env or DB) so admins can
        see at a glance which notification events are running in template
        mode vs plain-text fall-back."""
        events = [
            "booking.confirmed", "payment.received", "payout.released",
            "kyc.approved", "kyc.rejected", "kyc.needs_resubmission",
        ]
        # Iter 89 — DB overrides + source labelling.
        db_doc = await db.platform_settings.find_one({"id": "wa_templates"}) or {}
        db_mapping = db_doc.get("mapping") or {}
        rows = []
        for ev in events:
            env_var = "WA_TEMPLATE_" + ev.upper().replace(".", "_").replace("-", "_")
            env_val = (os.environ.get(env_var) or "").strip()
            db_val = (db_mapping.get(ev) or "").strip()
            resolved = env_val or db_val
            rows.append({
                "event": ev,
                "env_var": env_var,
                "template_name": resolved or None,
                "source": "env" if env_val else ("db" if db_val else None),
            })
        return {
            "provider": (os.environ.get("WHATSAPP_PROVIDER") or "mock").strip(),
            "templates": rows,
        }

    return r
