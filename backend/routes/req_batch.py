"""
BookTalent Requirement Batch — Feb 2026.

Additions in one small router (kept focused so it's easy to move later):

  1. Tech Rider upload / download / delete for artists (req #5).
  2. Manager "Add Customer" + "Create Booking on Behalf" (req #10).
  3. Persistent Advance-Payment reminder broadcast (req #17) — fan-out
     helper the pending payout loop already runs will now push to admin +
     subadmin + relevant agency in-app notifications every 24h until the
     payout is marked paid.

All file storage stays local to `/app/uploads/tech_riders` per VPS rule.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr, Field

log = logging.getLogger("req_batch")

TECH_RIDER_DIR = Path(os.environ.get("TECH_RIDER_DIR", "/app/uploads/tech_riders"))
TECH_RIDER_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Manager helper models
# ═══════════════════════════════════════════════════════════════════════
class AddCustomerBody(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=20)
    city: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=500)


class ManagerBookingBody(BaseModel):
    customer_id: str
    artist_id: str
    package_id: Optional[str] = None
    package_fee: float = 0.0
    event_type: str = Field(min_length=1, max_length=80)
    event_type_other: Optional[str] = None
    event_date: str
    number_of_days: int = 1
    venue: str = Field(min_length=1, max_length=160)
    venue_address: str = Field(min_length=1, max_length=400)
    city: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=1000)


# ═══════════════════════════════════════════════════════════════════════
# Advance-payment reminder broadcast
# ═══════════════════════════════════════════════════════════════════════
async def broadcast_advance_pending(db: AsyncIOMotorDatabase, *, booking: Dict[str, Any]) -> int:
    """Notify admin + subadmin + relevant agency that an artist advance is
    pending. In-app only — Slack/email cover the wider audit trail.
    Returns count of notifications inserted.
    """
    targets: List[str] = []
    admins = await db.users.find(
        {"role": {"$in": ["admin", "subadmin"]}}, {"id": 1, "_id": 0},
    ).to_list(200)
    targets.extend([u["id"] for u in admins if u.get("id")])

    # Relevant agency: booking's assigned agency (if any) or the artist's roster.
    agency_id = booking.get("agency_id")
    if not agency_id:
        prof = await db.artist_profiles.find_one(
            {"user_id": booking.get("artist_id")}, {"managed_by_agency_id": 1, "_id": 0},
        ) or {}
        agency_id = prof.get("managed_by_agency_id")
    if agency_id:
        targets.append(agency_id)

    amount = float((booking.get("pricing") or {}).get("artist_payable_advance") or 0)
    ref = booking.get("ref") or booking.get("id")
    msg = f"⚠️ Artist advance pending — ₹{amount:,.0f} · Booking {ref}"

    inserted = 0
    for uid in set(targets):
        try:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "kind": "advance_pending",
                "title": "Artist Advance Pending",
                "body": msg,
                "booking_id": booking.get("id"),
                "read": False,
                "created_at": utcnow(),
            })
            inserted += 1
        except Exception as e:  # noqa: BLE001
            log.warning("advance_pending notify insert failed: %s", e)
    return inserted


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ─── 1. Tech Rider (artist) ─────────────────────────────────────
    @r.get("/artist/tech-rider/mine")
    async def my_tech_rider(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        prof = await db.artist_profiles.find_one(
            {"user_id": user["id"]},
            {"_id": 0, "tech_rider_file": 1, "tech_rider_text": 1},
        ) or {}
        return {
            "text": prof.get("tech_rider_text") or "",
            "file": prof.get("tech_rider_file") or None,
        }

    @r.post("/artist/tech-rider/upload")
    async def upload_tech_rider(file: UploadFile = File(...),
                                 user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        if file.content_type not in ALLOWED_MIME:
            raise HTTPException(400, f"Unsupported file type: {file.content_type}")

        # Read & size-check
        data = await file.read()
        if len(data) > MAX_SIZE:
            raise HTTPException(413, "File exceeds 10 MB limit")

        # Save under /app/uploads/tech_riders/<user_id>/<uuid><ext>
        ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
        artist_dir = TECH_RIDER_DIR / user["id"]
        artist_dir.mkdir(parents=True, exist_ok=True)
        # Remove previous files so each artist keeps only the latest.
        for p in artist_dir.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        fname = f"{uuid.uuid4().hex}{ext}"
        (artist_dir / fname).write_bytes(data)

        meta = {
            "filename": file.filename,
            "size": len(data),
            "mime": file.content_type,
            "path": str(artist_dir / fname),
            "url": f"/api/artist/tech-rider/{user['id']}/download",
            "uploaded_at": utcnow(),
        }
        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$set": {"tech_rider_file": meta}},
        )
        return {"ok": True, "file": meta}

    @r.get("/artist/tech-rider/{artist_id}/download")
    async def download_tech_rider(artist_id: str, user: dict = Depends(get_current_user)):
        prof = await db.artist_profiles.find_one(
            {"user_id": artist_id}, {"tech_rider_file": 1, "_id": 0},
        ) or {}
        meta = prof.get("tech_rider_file")
        if not meta or not meta.get("path"):
            raise HTTPException(404, "Tech rider not uploaded")
        # Access: artist themselves, or admin / manager / assigned agency.
        role = user.get("role")
        if not (user.get("id") == artist_id
                or role in ("admin", "subadmin", "manager", "agency")):
            raise HTTPException(403, "Not allowed")
        p = Path(meta["path"])
        if not p.exists():
            raise HTTPException(410, "File missing on disk")
        return FileResponse(
            str(p),
            media_type=meta.get("mime") or "application/octet-stream",
            filename=meta.get("filename") or p.name,
        )

    @r.delete("/artist/tech-rider/mine")
    async def delete_tech_rider(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        prof = await db.artist_profiles.find_one(
            {"user_id": user["id"]}, {"tech_rider_file": 1, "_id": 0},
        ) or {}
        meta = prof.get("tech_rider_file") or {}
        if meta.get("path"):
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$unset": {"tech_rider_file": ""}},
        )
        return {"ok": True}

    # ─── 2. Manager: add customer + create booking on behalf ────────
    async def _require_manager(user: dict) -> None:
        if user.get("role") not in ("manager", "admin", "subadmin"):
            raise HTTPException(403, "Manager or admin only")

    @r.post("/manager/customers")
    async def manager_add_customer(body: AddCustomerBody, request: Request,
                                    user: dict = Depends(get_current_user)):
        await _require_manager(user)
        existing = await db.users.find_one({"email": body.email.lower()})
        if existing:
            return {"ok": True, "existing": True, "user": {
                "id": existing["id"], "email": existing["email"],
                "first_name": existing.get("first_name", ""),
                "last_name": existing.get("last_name", ""),
                "role": existing.get("role"),
            }}
        new_id = str(uuid.uuid4())
        # No password — customer will complete signup via magic link later.
        doc = {
            "id": new_id,
            "email": body.email.lower(),
            "first_name": body.first_name,
            "last_name": body.last_name,
            "phone": body.phone,
            "city": body.city,
            "role": "customer",
            "created_at": utcnow(),
            "created_by_manager_id": user["id"],
            "notes": body.notes,
            "password_hash": None,           # inactive until customer sets password
            "email_verified": False,
        }
        await db.users.insert_one(doc)
        # Audit
        try:
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "actor_id": user["id"], "actor_role": user.get("role"),
                "action": "manager.add_customer",
                "entity": "user", "entity_id": new_id,
                "metadata": {"email": body.email, "notes": body.notes},
                "created_at": utcnow(),
            })
        except Exception:
            pass
        return {"ok": True, "existing": False, "user": {
            "id": new_id, "email": doc["email"],
            "first_name": doc["first_name"], "last_name": doc["last_name"],
            "role": "customer",
        }}

    @r.get("/manager/customers")
    async def manager_list_customers(q: Optional[str] = None, limit: int = 50,
                                      user: dict = Depends(get_current_user)):
        await _require_manager(user)
        filt: Dict[str, Any] = {"role": "customer"}
        if q:
            filt["$or"] = [
                {"email": {"$regex": q, "$options": "i"}},
                {"first_name": {"$regex": q, "$options": "i"}},
                {"last_name": {"$regex": q, "$options": "i"}},
                {"phone": {"$regex": q, "$options": "i"}},
            ]
        rows = await db.users.find(
            filt,
            {"id": 1, "email": 1, "first_name": 1, "last_name": 1,
             "phone": 1, "city": 1, "created_at": 1,
             "created_by_manager_id": 1, "_id": 0},
        ).sort("created_at", -1).to_list(max(1, min(limit, 200)))
        return {"items": rows, "count": len(rows)}

    @r.post("/manager/bookings")
    async def manager_create_booking(body: ManagerBookingBody, request: Request,
                                      user: dict = Depends(get_current_user)):
        await _require_manager(user)

        cust = await db.users.find_one({"id": body.customer_id, "role": "customer"})
        if not cust:
            raise HTTPException(404, "Customer not found")
        artist = await db.users.find_one({"id": body.artist_id, "role": "artist"})
        if not artist:
            raise HTTPException(404, "Artist not found")

        # Central price using the same engine as customer checkout.
        from financial_engine import compute_price
        pkg_fee = body.package_fee
        if not pkg_fee and body.package_id:
            pkg = await db.packages.find_one({"id": body.package_id})
            if pkg:
                pkg_fee = float(pkg.get("price") or 0)
        pricing = await compute_price(db, artist_id=body.artist_id, package_fee=pkg_fee)

        bid = str(uuid.uuid4())
        booking = {
            "id": bid,
            "ref": f"BT-{bid[:8].upper()}",
            "customer_id": body.customer_id,
            "artist_id": body.artist_id,
            "package_id": body.package_id,
            "event_type": body.event_type,
            "event_type_other": body.event_type_other,
            "event_date": body.event_date,
            "number_of_days": body.number_of_days,
            "venue": body.venue,
            "venue_address": body.venue_address,
            "city": body.city,
            "notes": body.notes,
            "status": "pending_artist",
            "payment_status": "pending",
            "pricing": pricing,
            "assigned_manager_id": user["id"] if user.get("role") == "manager" else None,
            "created_by_role": user.get("role"),
            "created_on_behalf": True,
            "created_at": utcnow(),
        }
        await db.bookings.insert_one(booking)
        # Iter 99 — Deal snapshot so future rate changes don't break payouts.
        try:
            from routes.req_batch_6 import stamp_deal_snapshot_on_booking
            await stamp_deal_snapshot_on_booking(db, bid, body.artist_id)
        except Exception:
            pass
        # Emit first-class timeline events so BookingTimeline shows real dates.
        try:
            from routes.req_batch_2 import emit_booking_event
            await emit_booking_event(db, booking_id=bid, kind="lead_created",
                                      label="Booking Created (on behalf)",
                                      actor_id=user["id"], actor_role=user.get("role"))
            if booking.get("assigned_manager_id"):
                await emit_booking_event(db, booking_id=bid, kind="manager_assigned",
                                          label="Manager Assigned",
                                          actor_id=user["id"], actor_role=user.get("role"))
            await emit_booking_event(db, booking_id=bid, kind="artist_selected",
                                      label="Artist Selected",
                                      actor_id=user["id"], actor_role=user.get("role"))
        except Exception as e:  # noqa: BLE001
            log.warning("timeline events for %s failed: %s", bid, e)
        try:
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "actor_id": user["id"], "actor_role": user.get("role"),
                "action": "manager.create_booking",
                "entity": "booking", "entity_id": bid,
                "metadata": {"customer_id": body.customer_id, "artist_id": body.artist_id},
                "created_at": utcnow(),
            })
        except Exception:
            pass
        booking.pop("_id", None)
        return {"ok": True, "booking": booking}

    # ─── 3. Advance-pending broadcast (admin trigger + list) ────────
    @r.post("/admin/advance-pending/broadcast")
    async def admin_broadcast_advance_pending(_: dict = Depends(require_admin)):
        """Manual trigger — walks every booking with payment received
        but artist_payout_status != paid and pushes fresh in-app
        notifications to admin/subadmin/agency."""
        pushed = 0
        touched = 0
        async for bk in db.bookings.find(
            {
                "payment_status": {"$in": ["partial", "paid", "fully_paid"]},
                "$or": [
                    {"artist_payout_status": {"$ne": "paid"}},
                    {"artist_payout_status": {"$exists": False}},
                ],
            },
            {"_id": 0, "id": 1, "ref": 1, "artist_id": 1, "agency_id": 1, "pricing": 1},
        ):
            touched += 1
            pushed += await broadcast_advance_pending(db, booking=bk)
        return {"ok": True, "bookings_touched": touched, "notifications_pushed": pushed}

    return r
