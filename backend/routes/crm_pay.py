"""
Iter 84 — Phases 4-7 backend vertical slice.

Bundled into one router to keep the surface area easy to review. Each
section is separated with its own comment header. All endpoints live
under /api/.

Sections
--------
1. CRM      (Sec 26-30)   Lead lifecycle (12 stages) + Manager assignment
2. Payments (Sec 32-37)   Milestone tracking + reminders + 90/10 rule
3. Payouts  (Sec 40-44)   Manual payout + Easebuzz-ready abstraction
4. Chat     (Sec 23-24)   Manager-mediated chat + contact-privacy filter
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from routes.settings import get_settings, record_audit
from financial_engine import build_payment_milestones, compute_price
from notification_service import dispatch as notify_dispatch

log = logging.getLogger("v2.crm_pay")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# 1. CRM  ─  Leads + Manager Assignment (Sec 26-30)
# ═══════════════════════════════════════════════════════════════════════
LEAD_STAGES = [
    "new_lead", "contacted", "requirement_received", "artist_suggested",
    "quotation_sent", "negotiation", "booking_pending", "booking_confirmed",
    "payment_pending", "event_upcoming", "event_completed",
    "closed", "lost_cancelled",
]


class LeadCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    company: Optional[str] = Field(None, max_length=200)
    phone: str = Field(min_length=10, max_length=20)
    email: Optional[str] = None
    city: Optional[str] = None
    event_type: Optional[str] = None
    event_date: Optional[str] = None
    number_of_days: int = 1
    venue: Optional[str] = None
    venue_address: Optional[str] = None
    budget: Optional[float] = None
    requirements: Optional[str] = None
    lead_source: Optional[str] = "manual"
    assigned_manager_id: Optional[str] = None
    notes: Optional[str] = None


class LeadStageUpdate(BaseModel):
    stage: Literal[
        "new_lead", "contacted", "requirement_received", "artist_suggested",
        "quotation_sent", "negotiation", "booking_pending", "booking_confirmed",
        "payment_pending", "event_upcoming", "event_completed",
        "closed", "lost_cancelled",
    ]
    note: Optional[str] = None


class AssignManagerBody(BaseModel):
    manager_id: str
    note: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# 2. PAYMENTS  ─  Milestones + Reminders (Sec 32-37)
# ═══════════════════════════════════════════════════════════════════════
class MilestoneMarkPaidBody(BaseModel):
    milestone_index: int = Field(ge=0)
    amount_received: float = Field(gt=0)
    paid_on: Optional[str] = None
    method: Optional[str] = "manual"
    reference: Optional[str] = None


async def _create_or_get_schedule(db, booking: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent: create the payment schedule doc for a booking, using
    the current admin-configured schedule + Instant-Book rules."""
    existing = await db.payment_schedules.find_one({"booking_id": booking["id"]})
    if existing:
        existing.pop("_id", None)
        return existing

    settings = await get_settings(db)
    total = float(booking.get("pricing", {}).get("total", 0) or booking.get("total", 0))
    event_iso = booking.get("event_date")

    # Instant-Book adjustment (Sec 34): compress schedule when event is close
    schedule = list(settings.get("payment_schedule", []))
    rules = settings.get("instant_book_rules", {})
    try:
        base = datetime.fromisoformat((event_iso or "").replace("Z", "+00:00"))
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        hours_to_event = (base - datetime.now(timezone.utc)).total_seconds() / 3600
    except Exception:
        hours_to_event = 24 * 365  # far future — use default schedule

    if hours_to_event <= float(rules.get("very_short_window_hours", 48)):
        # 100% upfront — single milestone
        schedule = [{
            "milestone": "instant_full", "label": "Full Payment (Instant Book)",
            "percent": float(rules.get("very_short_window_min_pct", 100)),
            "offset_days": None, "mandatory": True,
        }]
    elif hours_to_event <= float(rules.get("standard_window_days", 7)) * 24:
        # Short window — collapse pre-event milestones so ≥ min_pct is
        # collected upfront. Post-event tail keeps its share.
        min_pre = float(rules.get("short_window_min_before_event_pct", 90))
        post = [s for s in schedule if (s.get("offset_days") or 0) > 0]
        post_pct = sum(float(s.get("percent", 0)) for s in post)
        upfront_pct = 100.0 - post_pct
        upfront_pct = max(upfront_pct, min_pre)  # never less than the floor
        schedule = [
            {"milestone": "short_window_upfront",
             "label": "Upfront (Short Window)",
             "percent": upfront_pct, "offset_days": None, "mandatory": True},
        ] + post

    milestones = build_payment_milestones(total, event_iso, schedule)
    doc = {
        "id": str(uuid.uuid4()),
        "booking_id": booking["id"],
        "artist_id": booking.get("artist_id"),
        "customer_id": booking.get("customer_id"),
        "event_date": event_iso,
        "total": total,
        "amount_received": 0.0,
        "milestones": milestones,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    await db.payment_schedules.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _milestone_reminder_tick(db: AsyncIOMotorDatabase) -> None:
    """Sec 35 — Runs periodically. Sends payment_due / reminder / overdue
    notifications based on how far the milestone's due_date is from today.
    Idempotent per (schedule_id, milestone_index, reminder_kind).
    """
    from email_service import _send_sync
    now = datetime.now(timezone.utc).date()

    async for sched in db.payment_schedules.find({"amount_received": {"$lt": 1e15}}):
        booking = await db.bookings.find_one({"id": sched["booking_id"]}) or {}
        cust_email = booking.get("customer_email")
        if not cust_email:
            continue
        for idx, m in enumerate(sched.get("milestones", [])):
            if m.get("status") == "paid" or not m.get("due_date"):
                continue
            try:
                due = datetime.fromisoformat(m["due_date"]).date()
            except Exception:
                continue
            delta = (due - now).days
            kind = None
            if delta == 7: kind = "reminder_7d"
            elif delta == 2: kind = "reminder_2d"
            elif delta == 0: kind = "due"
            elif delta < 0: kind = "overdue"
            if not kind:
                continue
            already = await db.payment_reminders.find_one({
                "schedule_id": sched["id"], "milestone_index": idx, "kind": kind,
            })
            if already:
                continue
            subject = {
                "reminder_7d": f"Reminder — ₹{m['amount']:,.0f} due on {m['due_date']}",
                "reminder_2d": f"Payment due in 2 days — ₹{m['amount']:,.0f}",
                "due":         f"Payment due today — ₹{m['amount']:,.0f}",
                "overdue":     f"⚠ Overdue payment — ₹{m['amount']:,.0f}",
            }[kind]
            # Build the compact timeline snippet so every reminder email
            # carries booking context (Sec 20 / Iter 96).
            try:
                from routes.req_batch_3 import build_email_timeline_html, fetch_booking_events
                _events = await fetch_booking_events(db, booking.get("id") or "")
                timeline_html = build_email_timeline_html(booking, _events)
            except Exception:
                timeline_html = ""
            html = f"""<p>Hi {booking.get('customer_name','')},</p>
            <p>Your booking <b>{booking.get('ref','')}</b> has a milestone due:</p>
            <ul><li><b>{m['label']}</b>: ₹{m['amount']:,.0f}</li>
            <li>Due: <b>{m['due_date']}</b></li></ul>
            <p>Please log in to BookTalent to complete payment.</p>
            {timeline_html or ""}"""
            try:
                await asyncio.to_thread(_send_sync, cust_email, subject, html, subject)
            except Exception as e:
                log.error("Reminder send failed: %s", e)
                continue
            await db.payment_reminders.insert_one({
                "id": str(uuid.uuid4()),
                "schedule_id": sched["id"], "milestone_index": idx,
                "kind": kind, "sent_at": utcnow(),
            })
            if kind == "overdue" and m.get("status") != "overdue":
                await db.payment_schedules.update_one(
                    {"id": sched["id"], "milestones.status": {"$ne": "paid"}},
                    {"$set": {f"milestones.{idx}.status": "overdue"}},
                )


async def payment_reminder_loop(db: AsyncIOMotorDatabase) -> None:
    """Started as a background task on server boot."""
    interval = int(os.environ.get("PAYMENT_REMINDER_MINUTES", "180"))
    log.info("Payment reminder loop starting (every %d min)", interval)
    while True:
        try:
            await _milestone_reminder_tick(db)
        except Exception as e:
            log.error("Payment reminder tick failed: %s", e)
        await asyncio.sleep(interval * 60)


# ═══════════════════════════════════════════════════════════════════════
# 3. PAYOUTS  ─  Manual now, Easebuzz-ready (Sec 40-44, 64)
# ═══════════════════════════════════════════════════════════════════════
class ManualPayoutBody(BaseModel):
    amount: float = Field(gt=0)
    paid_on: str
    method: Literal["neft", "imps", "upi", "cash", "cheque", "other"]
    utr: str = Field(min_length=3, max_length=50)
    bank_reference: Optional[str] = None
    notes: Optional[str] = None


async def _record_payout(db, booking: Dict[str, Any], user: Dict[str, Any], body: ManualPayoutBody) -> Dict[str, Any]:
    """Persist a manual payout. Sec 40-41."""
    payout = {
        "id": str(uuid.uuid4()),
        "booking_id": booking["id"],
        "artist_id": booking.get("artist_id"),
        "amount": float(body.amount),
        "method": body.method,
        "utr": body.utr,
        "bank_reference": body.bank_reference or "",
        "notes": body.notes or "",
        "paid_on": body.paid_on,
        "paid_by_id": user.get("id"),
        "paid_by_email": user.get("email"),
        "mode": "manual",
        "status": "paid",
        "created_at": utcnow(),
    }
    await db.artist_payouts.insert_one(payout)
    payout.pop("_id", None)
    await db.bookings.update_one(
        {"id": booking["id"]},
        {"$set": {"artist_payout_status": "paid",
                  "artist_payout_id": payout["id"],
                  "artist_payout_paid_at": utcnow()}}
    )
    return payout


async def _easebuzz_payout_stub(db, booking, user, amount):
    """Sec 42-43 — Automated payout is behind a feature flag. This is the
    integration seam; when live Easebuzz Payouts credentials are provided
    and `enable_automated_payout=true`, wire the actual API call here."""
    raise HTTPException(
        503,
        "Automated Easebuzz Payout is not yet configured. Add EASEBUZZ_PAYOUT_KEY/SALT "
        "in .env and implement the API call in _easebuzz_payout_stub()."
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. CHAT  ─  Manager-mediated with contact privacy (Sec 23-24)
# ═══════════════════════════════════════════════════════════════════════
class ChatSend(BaseModel):
    thread_id: str
    body: str = Field(min_length=1, max_length=4000)
    # Sender is derived from the authenticated user.


PHONE_RE = None  # compiled below (regex)
EMAIL_RE = None


def _init_regexes():
    global PHONE_RE, EMAIL_RE
    import re
    # Redact 10-digit runs (with optional spaces / dashes) — customer-visible messages only
    PHONE_RE = re.compile(r"(?:\+?\d[\s\-]?){10,13}")
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


_init_regexes()


def _redact_contact_info(text: str) -> str:
    """Sec 24 — For Service Artists, redact phone/email from any message
    that reaches the customer, so private artist contact info never
    leaks. Preserves message meaning while masking digits."""
    if not text:
        return text
    text = PHONE_RE.sub("[contact hidden]", text)
    text = EMAIL_RE.sub("[email hidden]", text)
    return text


# ═══════════════════════════════════════════════════════════════════════
# ROUTER FACTORY
# ═══════════════════════════════════════════════════════════════════════
def make_crm_pay_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ── CRM ──────────────────────────────────────────────────────────
    @r.post("/leads")
    async def create_lead(body: LeadCreate, request: Request,
                          user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "manager"):
            raise HTTPException(403, "Only admins/managers can create leads")
        doc = {
            "id": str(uuid.uuid4()),
            "stage": "new_lead",
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "created_by_id": user["id"],
            "history": [{"at": utcnow(), "stage": "new_lead",
                         "actor": user.get("email"), "note": "Lead created"}],
            **body.model_dump(),
        }
        await db.leads.insert_one(doc)
        doc.pop("_id", None)
        await record_audit(db, actor=user, action="lead.create",
                           entity="lead", entity_id=doc["id"],
                           new_value=doc["stage"], request=request)
        return doc

    @r.get("/leads")
    async def list_leads(
        stage: Optional[str] = None,
        assigned_manager_id: Optional[str] = None,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        q: Dict[str, Any] = {}
        if user.get("role") == "manager":
            q["assigned_manager_id"] = user["id"]  # managers see only own
        elif user.get("role") != "admin":
            raise HTTPException(403, "Access denied")
        if stage:
            if stage not in LEAD_STAGES:
                raise HTTPException(400, "Invalid stage")
            q["stage"] = stage
        if assigned_manager_id and user.get("role") == "admin":
            q["assigned_manager_id"] = assigned_manager_id
        rows = await db.leads.find(q, {"_id": 0}).sort("updated_at", -1).to_list(max(1, min(int(limit), 500)))
        return {"items": rows, "count": len(rows)}

    @r.patch("/leads/{lead_id}/stage")
    async def update_stage(lead_id: str, body: LeadStageUpdate, request: Request,
                            user: dict = Depends(get_current_user)):
        lead = await db.leads.find_one({"id": lead_id})
        if not lead: raise HTTPException(404, "Lead not found")
        if user.get("role") == "manager" and lead.get("assigned_manager_id") != user["id"]:
            raise HTTPException(403, "This lead is not assigned to you")
        if user.get("role") not in ("admin", "manager"):
            raise HTTPException(403, "Access denied")
        old = lead.get("stage")
        await db.leads.update_one(
            {"id": lead_id},
            {"$set": {"stage": body.stage, "updated_at": utcnow()},
             "$push": {"history": {"at": utcnow(), "stage": body.stage,
                                    "actor": user.get("email"), "note": body.note or ""}}},
        )
        await record_audit(db, actor=user, action="lead.stage",
                           entity="lead", entity_id=lead_id,
                           old_value=old, new_value=body.stage,
                           metadata={"note": body.note}, request=request)
        return {"ok": True, "stage": body.stage}

    @r.post("/leads/{lead_id}/assign")
    async def assign_manager(lead_id: str, body: AssignManagerBody, request: Request,
                              admin: dict = Depends(require_admin)):
        mgr = await db.users.find_one({"id": body.manager_id, "role": "manager"})
        if not mgr:
            raise HTTPException(400, "Not a valid manager user")
        lead = await db.leads.find_one({"id": lead_id})
        if not lead:
            raise HTTPException(404, "Lead not found")
        old = lead.get("assigned_manager_id")
        await db.leads.update_one(
            {"id": lead_id},
            {"$set": {"assigned_manager_id": body.manager_id,
                       "assigned_manager_email": mgr.get("email"),
                       "assigned_at": utcnow(),
                       "updated_at": utcnow()},
             "$push": {"history": {"at": utcnow(), "stage": lead.get("stage"),
                                    "actor": admin.get("email"),
                                    "note": f"Manager assigned: {mgr.get('email')} — {body.note or ''}"}}}
        )
        await record_audit(db, actor=admin, action="lead.assign",
                           entity="lead", entity_id=lead_id,
                           old_value=old, new_value=body.manager_id,
                           request=request)
        return {"ok": True, "assigned_to": mgr.get("email")}

    @r.get("/manager/dashboard")
    async def manager_dashboard(user: dict = Depends(get_current_user)):
        if user.get("role") != "manager":
            raise HTTPException(403, "Manager only")
        mid = user["id"]
        # Fan-out counts for the top-row cards (Sec 28)
        pipeline_counts = {
            stage: await db.leads.count_documents({"assigned_manager_id": mid, "stage": stage})
            for stage in LEAD_STAGES
        }
        active_bookings = await db.bookings.count_documents({
            "assigned_manager_id": mid, "status": {"$in": ["confirmed", "started", "pending_artist"]},
        })
        return {
            "counts": pipeline_counts,
            "active_bookings": active_bookings,
            "manager_id": mid,
        }

    # ── PAYMENTS ────────────────────────────────────────────────────
    @r.post("/bookings/{booking_id}/schedule")
    async def ensure_schedule(booking_id: str, user: dict = Depends(get_current_user)):
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            raise HTTPException(404, "Booking not found")
        if user.get("role") not in ("admin", "manager") and booking.get("customer_id") != user.get("id") and booking.get("artist_id") != user.get("id"):
            raise HTTPException(403, "Access denied")
        return await _create_or_get_schedule(db, booking)

    @r.get("/bookings/{booking_id}/schedule")
    async def read_schedule(booking_id: str, user: dict = Depends(get_current_user)):
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            raise HTTPException(404, "Booking not found")
        sched = await db.payment_schedules.find_one({"booking_id": booking_id}, {"_id": 0})
        if not sched:
            sched = await _create_or_get_schedule(db, booking)
        return sched

    @r.post("/bookings/{booking_id}/schedule/mark-paid")
    async def mark_paid(booking_id: str, body: MilestoneMarkPaidBody, request: Request,
                        user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "manager"):
            raise HTTPException(403, "Admin/Manager only")
        sched = await db.payment_schedules.find_one({"booking_id": booking_id})
        if not sched:
            raise HTTPException(404, "Schedule not found — create it first")
        idx = body.milestone_index
        milestones = sched.get("milestones", [])
        if idx >= len(milestones):
            raise HTTPException(400, "Invalid milestone index")
        old_status = milestones[idx].get("status")
        milestones[idx].update({
            "status": "paid",
            "amount_received": float(body.amount_received),
            "paid_on": body.paid_on or utcnow(),
            "method": body.method,
            "reference": body.reference or "",
        })
        new_received = sum(float(m.get("amount_received", 0)) for m in milestones if m.get("status") == "paid")
        await db.payment_schedules.update_one(
            {"id": sched["id"]},
            {"$set": {"milestones": milestones,
                       "amount_received": new_received,
                       "updated_at": utcnow()}}
        )
        await record_audit(db, actor=user, action="milestone.paid",
                           entity="payment_schedule", entity_id=sched["id"],
                           old_value=old_status, new_value="paid",
                           metadata={"milestone": idx, "amount": body.amount_received},
                           request=request)
        # Notify customer + artist (email + whatsapp + in-app) — Sec 32/37/51
        try:
            booking = await db.bookings.find_one({"id": booking_id}) or {}
            m_label = milestones[idx].get("label") or f"Milestone {idx + 1}"
            body_msg = (f"Payment of ₹{int(body.amount_received):,} received against "
                        f"'{m_label}' for booking {booking.get('ref', booking_id)}. "
                        f"Total received: ₹{int(new_received):,} of ₹{int(sched.get('total', 0)):,}.")
            if booking.get("customer_id"):
                await notify_dispatch(
                    db, user_id=booking["customer_id"], event="payment.received",
                    channels=["in_app", "email", "whatsapp"],
                    ctx={"title": "Payment received", "body": body_msg,
                         "amount": body.amount_received, "ref": booking.get("ref", "")},
                    email=booking.get("customer_email"),
                    phone=booking.get("customer_phone"),
                )
            if booking.get("artist_id"):
                artist_u = await db.users.find_one({"id": booking["artist_id"]}) or {}
                await notify_dispatch(
                    db, user_id=booking["artist_id"], event="payment.received",
                    channels=["in_app", "email", "whatsapp"],
                    ctx={"title": "Customer payment received",
                         "body": f"Customer paid ₹{int(body.amount_received):,} for booking {booking.get('ref', '')}. Milestone: {m_label}."},
                    email=artist_u.get("email"),
                    phone=artist_u.get("phone"),
                )
        except Exception as _e:
            log.warning("payment.received notification failed: %s", _e)
        return {"ok": True, "amount_received": new_received, "total": sched["total"]}

    # ── PAYOUTS ─────────────────────────────────────────────────────
    @r.post("/bookings/{booking_id}/payout/manual")
    async def record_manual_payout(booking_id: str, body: ManualPayoutBody, request: Request,
                                    user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "manager", "agency"):
            raise HTTPException(403, "Admin/Manager/Agency only")
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            raise HTTPException(404, "Booking not found")
        payout = await _record_payout(db, booking, user, body)
        await record_audit(db, actor=user, action="payout.manual",
                           entity="booking", entity_id=booking_id,
                           new_value="paid",
                           metadata={"amount": body.amount, "utr": body.utr},
                           request=request)
        # Notify the artist that the payout has been released — Sec 41/51
        try:
            if booking.get("artist_id"):
                artist_u = await db.users.find_one({"id": booking["artist_id"]}) or {}
                await notify_dispatch(
                    db, user_id=booking["artist_id"], event="payout.released",
                    channels=["in_app", "email", "whatsapp"],
                    ctx={
                        "title": "Payout released",
                        "body": (f"Your payout of ₹{int(body.amount):,} for booking "
                                 f"{booking.get('ref', '')} has been released via "
                                 f"{body.method.upper()}. UTR: {body.utr}."),
                        "amount": body.amount, "utr": body.utr, "method": body.method,
                    },
                    email=artist_u.get("email"),
                    phone=artist_u.get("phone"),
                )
        except Exception as _e:
            log.warning("payout.released notification failed: %s", _e)
        return payout

    @r.post("/bookings/{booking_id}/payout/auto")
    async def trigger_auto_payout(booking_id: str, request: Request,
                                   admin: dict = Depends(require_admin)):
        settings = await get_settings(db)
        if not (settings.get("enable_automated_payout") and settings.get("payout_mode") == "easebuzz"):
            raise HTTPException(400, "Automated payout is disabled. Enable it in Platform Settings.")
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            raise HTTPException(404, "Booking not found")
        # Compute payable via financial engine to be safe
        pricing = booking.get("pricing", {})
        quote = await compute_price(
            db, artist_id=booking.get("artist_id"),
            package_fee=float(pricing.get("package_fee", 0)),
            addons_total=float(pricing.get("addons_total", 0)),
            coupon_discount=float(pricing.get("coupon_discount", 0)),
        )
        # Iter 88 — instead of hard-failing when the Easebuzz Payouts stub
        # isn't ready, enqueue for background retry so ops sees the
        # attempt in the retry queue.
        try:
            return await _easebuzz_payout_stub(db, booking, admin, quote["artist_payable"])
        except HTTPException as he:
            from routes.iter88 import enqueue_payout_retry as _enq
            entry = await _enq(
                db, booking_id=booking_id, amount=float(quote["artist_payable"]),
                reason=str(he.detail), triggered_by=admin.get("email"),
            )
            return {"queued": True, "retry_entry": entry,
                    "message": "Auto payout unavailable — queued for retry"}

    @r.get("/bookings/{booking_id}/payouts")
    async def list_payouts(booking_id: str, user: dict = Depends(get_current_user)):
        rows = await db.artist_payouts.find({"booking_id": booking_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
        return {"items": rows, "count": len(rows)}

    # ── CHAT ────────────────────────────────────────────────────────
    @r.post("/chat/threads")
    async def create_thread(artist_id: str, user: dict = Depends(get_current_user)):
        """Sec 23 — Customer opens a thread to enquire about an artist.
        For Service Artists, the thread is auto-routed via a BookTalent
        manager (assigned round-robin if none set yet). For normal
        artists, the customer talks directly with the artist.
        """
        artist_prof = await db.artist_profiles.find_one({"user_id": artist_id}) or {}
        is_service = bool(artist_prof.get("is_service_artist"))
        thread_id = str(uuid.uuid4())
        thread = {
            "id": thread_id,
            "artist_id": artist_id,
            "customer_id": user["id"],
            "is_managed": is_service,
            "manager_id": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if is_service:
            # Assign a random active manager for now — round-robin can
            # replace this once the CRM has enough leads to load-balance.
            mgr = await db.users.find_one({"role": "manager"})
            if mgr:
                thread["manager_id"] = mgr["id"]
        await db.chat_v2_threads.insert_one(thread)
        thread.pop("_id", None)
        return {"id": thread_id, "is_managed": is_service, "manager_id": thread["manager_id"]}

    @r.post("/chat/messages")
    async def send_message(body: ChatSend, user: dict = Depends(get_current_user)):
        thread = await db.chat_v2_threads.find_one({"id": body.thread_id})
        if not thread:
            raise HTTPException(404, "Thread not found")
        # SEC-002 — Participant authorization. Only the thread's customer,
        # artist, or assigned manager may write. Admins are always allowed
        # for moderation. Previously ANY authenticated user with the thread
        # UUID could inject / impersonate messages.
        participants = {thread.get("customer_id"), thread.get("artist_id"), thread.get("manager_id")}
        if user.get("role") != "admin" and user["id"] not in participants:
            raise HTTPException(403, "You are not a participant of this conversation.")
        # Iter 99.5 SEC-002 — Contact-masking enforcer.
        # For every managed thread (Service-artist booking chat) OR any
        # thread whose linked artist has is_service_artist=true, mask
        # phone/email/URL from EVERY sender. Previously the gate required a
        # booking_id on the thread which was never populated → masking
        # never ran. `redact_for_thread` now enforces from the thread
        # itself and looks up the artist profile if is_managed is unset.
        visible_body = body.body
        raw_body = body.body
        try:
            from routes.req_batch_6 import redact_for_thread
            visible_body, _hits = await redact_for_thread(
                db, thread=thread,
                sender_id=user["id"], sender_role=user.get("role"),
                body_original=body.body,
            )
        except Exception:  # noqa: BLE001
            # Legacy fallback — never fail a chat write on masker error.
            if user["id"] == thread.get("artist_id"):
                visible_body = _redact_contact_info(body.body)
        msg = {
            "id": str(uuid.uuid4()),
            "thread_id": body.thread_id,
            "sender_id": user["id"],
            "sender_role": user.get("role"),
            "body_original": raw_body,          # kept for admin/audit
            "body": visible_body,               # what customers see
            "at": utcnow(),
        }
        await db.chat_v2_messages.insert_one(msg)
        await db.chat_v2_threads.update_one(
            {"id": body.thread_id},
            {"$set": {"updated_at": utcnow()}},
        )
        return {"id": msg["id"], "body": msg["body"], "at": msg["at"]}

    @r.get("/chat/threads/{thread_id}/messages")
    async def list_messages(thread_id: str, user: dict = Depends(get_current_user)):
        thread = await db.chat_v2_threads.find_one({"id": thread_id})
        if not thread:
            raise HTTPException(404, "Thread not found")
        allowed = {thread.get("customer_id"), thread.get("artist_id"), thread.get("manager_id")}
        if user["id"] not in allowed and user.get("role") not in ("admin",):
            raise HTTPException(403, "Access denied")
        # Chat scrollback = oldest first (natural conversation flow — one
        # of the intentional ascending sorts, distinct from our list convention).
        rows = await db.chat_v2_messages.find({"thread_id": thread_id}, {"_id": 0}).sort("at", 1).to_list(500)
        # Non-admin viewers see the redacted body only
        if user.get("role") != "admin":
            for m in rows:
                m.pop("body_original", None)
        return {"items": rows, "count": len(rows), "thread": {
            "is_managed": thread.get("is_managed"),
            "manager_id": thread.get("manager_id"),
        }}

    return r
