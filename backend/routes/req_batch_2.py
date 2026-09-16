"""
Feb-2026 Requirement Batch 2 — mutual refunds, booking presets,
booking timeline persistence, demo service-artist seeder.

Kept in one focused module so the additions are easy to locate.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("req_batch_2")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# 1. Booking Timeline persistence — `booking_events` collection
# ═══════════════════════════════════════════════════════════════════════
async def emit_booking_event(
    db: AsyncIOMotorDatabase,
    *,
    booking_id: str,
    kind: str,
    label: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a first-class timeline entry. Called anywhere the booking
    lifecycle materially changes. Idempotent per (booking_id, kind)
    when kind is a one-shot milestone."""
    try:
        one_shot = {"lead_created", "manager_assigned", "artist_selected",
                    "booking_confirmed", "event_completed", "final_settled"}
        if kind in one_shot:
            existing = await db.booking_events.find_one(
                {"booking_id": booking_id, "kind": kind}, {"_id": 1}
            )
            if existing:
                return
        await db.booking_events.insert_one({
            "id": str(uuid.uuid4()),
            "booking_id": booking_id,
            "kind": kind,
            "label": label,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "metadata": metadata or {},
            "at": utcnow(),
        })
    except Exception as e:  # noqa: BLE001
        log.warning("emit_booking_event failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# 2. Mutual-agreement refunds
# ═══════════════════════════════════════════════════════════════════════
class RefundRequestBody(BaseModel):
    reason: str = Field(default="", max_length=500)
    amount: Optional[float] = None  # None = full refund


class ManagerPresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    event_type_other: Optional[str] = None
    number_of_days: int = 1
    city: str = Field(default="", max_length=80)
    default_package_fee: float = 0.0
    notes_template: str = Field(default="", max_length=1000)
    shared: bool = False


class ManagerPresetSharePatch(BaseModel):
    shared: bool


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_2_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ─── Helper: fetch + role check ────────────────────────────────
    async def _booking_for_party(booking_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        bk = await db.bookings.find_one({"id": booking_id})
        if not bk:
            raise HTTPException(404, "Booking not found")
        role = user.get("role")
        uid = user.get("id")
        if role == "admin" or role == "subadmin":
            return bk
        if uid in (bk.get("customer_id"), bk.get("artist_id")):
            return bk
        raise HTTPException(403, "Not a party to this booking")

    # ═══════════════════════════════════════════════════════════════
    # (2) Refund automation for mutual agreements
    # ═══════════════════════════════════════════════════════════════
    @r.post("/bookings/{booking_id}/refund-request")
    async def refund_request(booking_id: str, body: RefundRequestBody,
                              user: dict = Depends(get_current_user)):
        bk = await _booking_for_party(booking_id, user)
        role = user.get("role")
        if role not in ("customer", "artist"):
            raise HTTPException(403, "Only customer or artist may request a mutual refund")

        total = float((bk.get("pricing") or {}).get("total") or 0)
        paid = float(bk.get("paid_amount") or 0)
        amt = float(body.amount) if body.amount is not None else paid
        if amt <= 0:
            raise HTTPException(400, "Refund amount must be positive")
        if amt > paid:
            raise HTTPException(400, f"Refund cannot exceed paid amount ₹{paid}")

        # If a live request already exists, return it (idempotent per booking).
        existing = await db.refund_requests.find_one({
            "booking_id": booking_id,
            "status": {"$in": ["pending_counter_ack", "accepted", "rejected"]},
        })
        if existing and existing.get("status") == "pending_counter_ack":
            existing.pop("_id", None)
            return {"ok": True, "already_pending": True, "request": existing}

        rid = str(uuid.uuid4())
        doc = {
            "id": rid,
            "booking_id": booking_id,
            "amount": amt,
            "reason": body.reason,
            "requested_by_id": user["id"],
            "requested_by_role": role,
            "counter_role": "artist" if role == "customer" else "customer",
            "counter_id": bk["artist_id"] if role == "customer" else bk["customer_id"],
            "status": "pending_counter_ack",
            "created_at": utcnow(),
        }
        await db.refund_requests.insert_one(doc)

        # Notify the counter party
        try:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": doc["counter_id"],
                "kind": "refund_request",
                "title": "Refund request awaiting your acknowledgement",
                "body": f"₹{amt:,.0f} refund requested for booking {bk.get('ref') or booking_id}. Open the booking to accept or reject.",
                "booking_id": booking_id,
                "read": False,
                "created_at": utcnow(),
            })
        except Exception:
            pass

        # Persist a timeline event
        await emit_booking_event(
            db,
            booking_id=booking_id,
            kind="refund_requested",
            label=f"Refund requested by {role} · ₹{amt:,.0f}",
            actor_id=user["id"], actor_role=role,
            metadata={"amount": amt, "reason": body.reason, "request_id": rid},
        )
        # Watchlist Slack ping — fires only if an admin flagged this booking.
        try:
            from routes.req_batch_5 import maybe_ping_watchlist
            await maybe_ping_watchlist(db, booking_id=booking_id,
                                        action="refund_requested",
                                        actor_role=role, amount=amt)
        except Exception:
            pass
        doc.pop("_id", None)
        return {"ok": True, "request": doc}

    @r.post("/bookings/{booking_id}/refund-accept")
    async def refund_accept(booking_id: str, user: dict = Depends(get_current_user)):
        bk = await _booking_for_party(booking_id, user)
        role = user.get("role")
        req = await db.refund_requests.find_one({
            "booking_id": booking_id, "status": "pending_counter_ack",
        })
        if not req:
            raise HTTPException(404, "No pending refund request")
        if req.get("counter_role") != role or req.get("counter_id") != user.get("id"):
            raise HTTPException(403, "Only the counter party may accept this request")

        await db.refund_requests.update_one(
            {"id": req["id"]},
            {"$set": {
                "status": "accepted",
                "counter_accepted_at": utcnow(),
                "counter_accepted_by": user["id"],
            }},
        )
        # Flag the booking as mutually-agreed refundable.
        await db.bookings.update_one(
            {"id": booking_id},
            {"$set": {
                "mutual_refund_status": "agreed",
                "mutual_refund_amount": req["amount"],
                "mutual_refund_agreed_at": utcnow(),
                "refund_flag": True,
                "refund_reason": req.get("reason") or "mutual_agreement",
            }, "$push": {"history": {
                "at": utcnow(),
                "action": "mutual_refund_agreed",
                "by": user["id"],
                "amount": req["amount"],
            }}},
        )

        # Best-effort: trigger the existing auto-refund pipeline if enabled.
        auto_dispatched = False
        try:
            from routes.easebuzz import auto_refund_bookings  # type: ignore
            r_out = await auto_refund_bookings(db, booking_ids=[booking_id])
            auto_dispatched = bool(r_out)
        except Exception as e:  # noqa: BLE001
            log.warning("auto_refund_bookings not invoked: %s", e)

        # Notify requester
        try:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": req["requested_by_id"],
                "kind": "refund_accepted",
                "title": "Refund request accepted",
                "body": f"Your ₹{req['amount']:,.0f} refund on booking {bk.get('ref') or booking_id} was accepted. Payout in progress.",
                "booking_id": booking_id,
                "read": False,
                "created_at": utcnow(),
            })
        except Exception:
            pass

        await emit_booking_event(
            db,
            booking_id=booking_id,
            kind="refund_accepted",
            label=f"Refund accepted · ₹{req['amount']:,.0f}",
            actor_id=user["id"], actor_role=role,
            metadata={"amount": req["amount"], "auto_dispatched": auto_dispatched},
        )
        try:
            from routes.req_batch_5 import maybe_ping_watchlist
            await maybe_ping_watchlist(db, booking_id=booking_id,
                                        action="refund_accepted",
                                        actor_role=role, amount=req["amount"])
        except Exception:
            pass
        try:
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "actor_id": user["id"], "actor_role": role,
                "action": "refund.mutual_accepted",
                "entity": "booking", "entity_id": booking_id,
                "metadata": {"amount": req["amount"], "request_id": req["id"]},
                "created_at": utcnow(),
            })
        except Exception:
            pass
        return {"ok": True, "auto_dispatched": auto_dispatched, "amount": req["amount"]}

    @r.post("/bookings/{booking_id}/refund-reject")
    async def refund_reject(booking_id: str, user: dict = Depends(get_current_user)):
        bk = await _booking_for_party(booking_id, user)
        req = await db.refund_requests.find_one({
            "booking_id": booking_id, "status": "pending_counter_ack",
        })
        if not req:
            raise HTTPException(404, "No pending refund request")
        if req.get("counter_id") != user.get("id"):
            raise HTTPException(403, "Only the counter party may reject this request")
        await db.refund_requests.update_one(
            {"id": req["id"]},
            {"$set": {"status": "rejected", "counter_rejected_at": utcnow()}},
        )
        await emit_booking_event(
            db, booking_id=booking_id, kind="refund_rejected",
            label=f"Refund rejected by {user.get('role')}",
            actor_id=user["id"], actor_role=user.get("role"),
        )
        try:
            from routes.req_batch_5 import maybe_ping_watchlist
            await maybe_ping_watchlist(db, booking_id=booking_id,
                                        action="refund_rejected",
                                        actor_role=user.get("role"),
                                        amount=req.get("amount"))
        except Exception:
            pass
        return {"ok": True}

    @r.get("/bookings/{booking_id}/refund-status")
    async def refund_status(booking_id: str, user: dict = Depends(get_current_user)):
        await _booking_for_party(booking_id, user)
        req = await db.refund_requests.find_one(
            {"booking_id": booking_id},
            {"_id": 0}, sort=[("created_at", -1)],
        )
        return {"request": req}

    # ═══════════════════════════════════════════════════════════════
    # (3) Manager booking presets
    # ═══════════════════════════════════════════════════════════════
    async def _require_manager(user: dict) -> None:
        if user.get("role") not in ("manager", "admin", "subadmin"):
            raise HTTPException(403, "Manager or admin only")

    @r.get("/manager/booking-presets")
    async def list_presets(user: dict = Depends(get_current_user)):
        await _require_manager(user)
        # Return the manager's own presets + team-shared presets from others.
        rows = await db.manager_booking_presets.find(
            {"$or": [{"manager_id": user["id"]}, {"shared": True}]},
            {"_id": 0},
        ).sort("created_at", -1).to_list(500)
        # Annotate `owned` and lookup owner names for shared rows.
        owner_ids = {r.get("manager_id") for r in rows if r.get("manager_id") != user["id"]}
        owners: Dict[str, str] = {}
        if owner_ids:
            async for u in db.users.find(
                {"id": {"$in": list(owner_ids)}},
                {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1},
            ):
                owners[u["id"]] = (
                    f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("email") or u["id"]
                )
        for row in rows:
            row["owned"] = row.get("manager_id") == user["id"]
            if not row["owned"]:
                row["owner_name"] = owners.get(row.get("manager_id"), "Team")
        return {"items": rows, "count": len(rows)}

    @r.post("/manager/booking-presets")
    async def create_preset(body: ManagerPresetBody, user: dict = Depends(get_current_user)):
        await _require_manager(user)
        doc = {
            "id": str(uuid.uuid4()),
            "manager_id": user["id"],
            "name": body.name,
            "event_type": body.event_type,
            "event_type_other": body.event_type_other,
            "number_of_days": body.number_of_days,
            "city": body.city,
            "default_package_fee": body.default_package_fee,
            "notes_template": body.notes_template,
            "shared": bool(body.shared),
            "created_at": utcnow(),
        }
        await db.manager_booking_presets.insert_one(doc)
        doc.pop("_id", None)
        doc["owned"] = True
        return {"ok": True, "preset": doc}

    @r.patch("/manager/booking-presets/{preset_id}/share")
    async def toggle_share(preset_id: str, body: ManagerPresetSharePatch,
                            user: dict = Depends(get_current_user)):
        await _require_manager(user)
        # Only the preset owner (or admin) can flip the shared flag.
        row = await db.manager_booking_presets.find_one({"id": preset_id})
        if not row:
            raise HTTPException(404, "Preset not found")
        if row.get("manager_id") != user["id"] and user.get("role") not in ("admin", "subadmin"):
            raise HTTPException(403, "Only the preset owner can share/unshare it")
        await db.manager_booking_presets.update_one(
            {"id": preset_id}, {"$set": {"shared": bool(body.shared)}},
        )
        return {"ok": True, "shared": bool(body.shared)}

    @r.delete("/manager/booking-presets/{preset_id}")
    async def delete_preset(preset_id: str, user: dict = Depends(get_current_user)):
        await _require_manager(user)
        # Manager can delete only their own; admin can delete any.
        filt = {"id": preset_id}
        if user.get("role") == "manager":
            filt["manager_id"] = user["id"]
        r_out = await db.manager_booking_presets.delete_one(filt)
        if r_out.deleted_count == 0:
            raise HTTPException(404, "Preset not found or not yours")
        return {"ok": True}

    # ═══════════════════════════════════════════════════════════════
    # (4) Booking Timeline endpoint — merges booking_events + history
    # ═══════════════════════════════════════════════════════════════
    @r.get("/bookings/{booking_id}/timeline")
    async def booking_timeline(booking_id: str, user: dict = Depends(get_current_user)):
        bk = await _booking_for_party(booking_id, user)
        events = await db.booking_events.find(
            {"booking_id": booking_id}, {"_id": 0},
        ).sort("at", 1).to_list(500)

        # Backfill from the `history` array so bookings created before this
        # collection existed still show a timeline.
        hist = bk.get("history") or []
        seen = {(e.get("kind"), e.get("at")) for e in events}
        for h in hist:
            key = (h.get("action"), h.get("at"))
            if key in seen:
                continue
            events.append({
                "id": str(uuid.uuid4()),
                "booking_id": booking_id,
                "kind": h.get("action") or "history",
                "label": (h.get("action") or "").replace("_", " ").title(),
                "actor_id": h.get("by"),
                "actor_role": None,
                "metadata": {k: v for k, v in h.items() if k not in ("at", "action", "by")},
                "at": h.get("at"),
            })
        events.sort(key=lambda x: x.get("at") or "")
        return {"items": events, "count": len(events)}

    # ═══════════════════════════════════════════════════════════════
    # (5) Seed demo service artist  (admin-only)
    # ═══════════════════════════════════════════════════════════════
    @r.post("/admin/seed/service-artist")
    async def seed_service_artist(_: dict = Depends(require_admin)):
        """Idempotent — creates a demo BookTalent-Service artist with a
        10% deal so the fee-waiver flow is visible without extra setup.
        """
        email = "service-artist@booktalent.com"
        existing = await db.users.find_one({"email": email})
        if existing:
            prof = await db.artist_profiles.find_one({"user_id": existing["id"]})
            # Ensure flags are set even if the row pre-existed.
            await db.artist_profiles.update_one(
                {"user_id": existing["id"]},
                {"$set": {
                    "is_service_artist": True,
                    "percentage_deal": 10.0,
                    "kyc_status": "live",
                    "artist_type": "service",
                }},
            )
            return {"ok": True, "existed": True, "user_id": existing["id"], "profile": bool(prof)}

        # bcrypt from server-side helper — same as normal user signup.
        try:
            from server import _hash_password  # type: ignore
            pwd_hash = _hash_password("Service@123")
        except Exception:
            import bcrypt
            pwd_hash = bcrypt.hashpw(b"Service@123", bcrypt.gensalt()).decode()

        uid = str(uuid.uuid4())
        await db.users.insert_one({
            "id": uid,
            "email": email,
            "password_hash": pwd_hash,
            "role": "artist",
            "first_name": "Aarav",
            "last_name": "Menon",
            "phone": "+91 90000 00099",
            "city": "Mumbai",
            "email_verified": True,
            "created_at": utcnow(),
        })
        await db.artist_profiles.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "stage_name": "Aarav Menon (BookTalent Service)",
            "category": "Live Band",
            "bio": "Demo BookTalent-Service artist. Bookings via this artist showcase the 5% platform-fee waiver at checkout.",
            "city": "Mumbai",
            "cities_served": ["Mumbai", "Pune", "Bengaluru"],
            "genres": ["Pop", "Fusion", "Bollywood"],
            "languages": ["English", "Hindi"],
            "starting_fee": 150000,
            "verified": True,
            "is_service_artist": True,
            "artist_type": "service",
            "percentage_deal": 10.0,
            "kyc_status": "live",
            "tnc_accepted_at": utcnow(),
            "rating_avg": 4.9,
            "rating_count": 42,
            "created_at": utcnow(),
        })
        return {"ok": True, "existed": False, "user_id": uid, "credentials": {
            "email": email, "password": "Service@123",
        }}

    return r
