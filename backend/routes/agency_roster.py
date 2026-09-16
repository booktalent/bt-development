"""
Agency ↔ Artist roster — Iter 63 additions.

The full invite / accept / decline / release / commission flow already
existed in `iter9_routes.py` on the `agency_roster` collection. This
module adds only what was missing per the user's spec:

  GET  /api/agency/referral                (agency) stable referral URL
  POST /api/auth/roster/consume-ref        (public artist) auto-join by ref
  GET  /api/roster/my-agency               (artist) who currently manages me

Business rules (per user):
  - Referral link auto-joins on signup — no accept step.
  - Artist can't leave; only agency can release (already enforced by
    /agency/remove which flips status to 'removed').
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class ConsumeRefBody(BaseModel):
    referral_code: str


def make_roster_router(db: AsyncIOMotorDatabase, get_current_user):
    r = APIRouter(tags=["agency-roster"])

    @r.get("/agency/referral")
    async def get_referral_link(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        code = user["id"].replace("-", "")[:12].upper()
        await db.agency_referral_codes.update_one(
            {"code": code},
            {"$set": {"code": code, "agency_id": user["id"], "updated_at": _now()},
             "$setOnInsert": {"created_at": _now()}},
            upsert=True,
        )
        base = os.environ.get("FRONTEND_URL", "").rstrip("/")
        return {
            "code": code,
            "link": f"{base}/signup?role=artist&ref={code}",
            "note": "Artists who sign up via this link auto-join your roster (no accept step).",
        }

    @r.get("/roster/my-agency")
    async def my_agency(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        rel = await db.agency_roster.find_one(
            {"artist_id": user["id"], "status": "active"}, {"_id": 0},
        )
        if not rel:
            return {"active": False}
        u = await db.users.find_one(
            {"id": rel["agency_id"]},
            {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "company_name": 1},
        )
        return {
            "active": True,
            "agency": u or {},
            "commission_pct": rel.get("commission_pct", 15),
            "since": rel.get("decided_at") or rel.get("created_at"),
        }

    # Iter 63.4 — Agency views full boost + subscription payment history for
    # every managed artist. Bookings excluded here (those are on the CRM tab).
    @r.get("/agency/artist/{artist_id}/payments")
    async def agency_artist_payments(artist_id: str, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        # Ensure the artist is actually in this agency's active roster.
        rel = await db.agency_roster.find_one(
            {"agency_id": user["id"], "artist_id": artist_id, "status": "active"},
        )
        if not rel and user.get("role") != "admin":
            raise HTTPException(404, "Not an active artist in your roster")
        rows = await db.payments.find(
            {"user_id": artist_id, "payment_kind": {"$in": ["subscription", "boost"]}},
            {"_id": 0, "id": 1, "gateway": 1, "environment": 1, "amount": 1,
             "status": 1, "txnid": 1, "easepayid": 1, "created_at": 1,
             "verified_at": 1, "payment_kind": 1, "subscription_plan": 1,
             "subscription_cycle": 1, "boost_package_id": 1, "failure_reason": 1},
        ).sort("created_at", -1).to_list(500)
        # Enrich boost rows with package name for readability.
        boost_pkg_ids = [r["boost_package_id"] for r in rows if r.get("boost_package_id")]
        pkg_map: Dict[str, str] = {}
        if boost_pkg_ids:
            async for p in db.boost_packages.find(
                {"id": {"$in": boost_pkg_ids}}, {"_id": 0, "id": 1, "name": 1},
            ):
                pkg_map[p["id"]] = p.get("name", "")
        for r in rows:
            if r.get("boost_package_id"):
                r["boost_package_name"] = pkg_map.get(r["boost_package_id"], "")
            if r.get("payment_kind") == "subscription":
                r["label"] = f"{(r.get('subscription_plan') or '').title()} · {r.get('subscription_cycle') or 'monthly'}"
            elif r.get("payment_kind") == "boost":
                r["label"] = r.get("boost_package_name") or "Boost package"
        return rows

    @r.post("/auth/roster/consume-ref")
    async def consume_ref(body: ConsumeRefBody, user: dict = Depends(get_current_user)):
        """Called right after signup when a ?ref=CODE was present.
        Auto-attaches the artist to the referring agency with status='active'."""
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        code = (body.referral_code or "").strip().upper()
        if not code:
            raise HTTPException(400, "referral_code required")
        row = await db.agency_referral_codes.find_one({"code": code})
        if not row:
            raise HTTPException(404, "Invalid referral code")
        agency_id = row["agency_id"]
        # If artist is already managed anywhere, don't override.
        existing = await db.agency_roster.find_one({
            "artist_id": user["id"], "status": {"$in": ["pending", "active"]},
        })
        if existing:
            return {"ok": False, "reason": "already_linked", "status": existing["status"]}
        await db.agency_roster.insert_one({
            "id": _new_id(),
            "agency_id": agency_id,
            "artist_id": user["id"],
            "artist_email": user["email"],
            "commission_pct": 15,
            "status": "active",
            "source": "referral_link",
            "referral_code": code,
            "created_at": _now(),
            "decided_at": _now(),
        })
        await db.notifications.insert_one({
            "id": _new_id(), "user_id": agency_id, "type": "agency_referral_joined",
            "title": "New artist joined via your referral",
            "body": f"{user.get('first_name') or 'An artist'} signed up using your referral link.",
            "link": "/agency/artists", "read": False, "created_at": _now(),
        })
        return {"ok": True, "agency_id": agency_id}

    # Iter 64 — Agency Artist Earnings.
    # The Agency portal shows COMPLETE earnings history for every roster
    # artist — including bookings that existed BEFORE the artist joined the
    # agency, per user spec. No date-window filter on bookings.
    @r.get("/agency/artist/{artist_id}/earnings")
    async def agency_artist_earnings(artist_id: str, user: dict = Depends(get_current_user)):
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        if user.get("role") == "agency":
            rel = await db.agency_roster.find_one({
                "agency_id": user["id"], "artist_id": artist_id, "status": "active",
            })
            if not rel:
                raise HTTPException(404, "Not an active artist in your roster")
            commission_pct = float(rel.get("commission_pct", 15))
        else:
            rel = await db.agency_roster.find_one({"artist_id": artist_id, "status": "active"})
            commission_pct = float((rel or {}).get("commission_pct", 15))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bookings: list = []
        # Iter 68 — batch-lookup all payments once instead of per-booking round-trip.
        booking_ids: list = []
        async for b in db.bookings.find({"artist_id": artist_id}).sort("event_date", -1):
            booking_ids.append(b.get("id"))
            p = b.get("pricing") or {}
            artist_fee = float(p.get("artist_fee",
                (p.get("package_fee", 0) or 0)
                + (p.get("addons_total", 0) or 0)
                - (p.get("coupon_discount", 0) or 0),
            ))
            platform_charges = float(p.get("platform_fee", 0) or 0) + float(p.get("gst", 0) or 0)
            commission_amount = round(artist_fee * commission_pct / 100.0, 2)
            bookings.append({
                "id": b.get("id"),
                "ref": b.get("ref"),
                "customer_id": b.get("customer_id"),
                "customer_name": b.get("customer_name"),
                "customer_email": b.get("customer_email"),
                "customer_phone": b.get("customer_phone"),
                "event_date": b.get("event_date"),
                "event_time": b.get("event_time"),
                "event_type": b.get("event_type"),
                "package_name": b.get("package_name"),
                "guests": b.get("guests"),
                "venue": b.get("venue"),
                "city": b.get("city"),
                "status": b.get("status"),
                "payment_status": b.get("payment_status"),
                "amount_paid": float(b.get("amount_paid") or 0),
                "artist_fee": artist_fee,
                "platform_charges": round(platform_charges, 2),
                "agency_commission": commission_amount,
                "artist_net": round(artist_fee - commission_amount, 2),
                # refund fields filled in below via batch lookup
                "refund_status": None,
                "refund_amount": None,
                "refund_reason": None,
                "created_at": b.get("created_at"),
            })
        # Batch pull payment refund info for the whole booking set.
        if booking_ids:
            payment_map: dict = {}
            async for pay in db.payments.find(
                {"$or": [{"booking_id": {"$in": booking_ids}},
                         {"booking_ids": {"$in": booking_ids}}],
                 "status": {"$in": ["completed", "refunded"]}},
                {"_id": 0, "booking_id": 1, "booking_ids": 1, "refund_status": 1,
                 "refund_amount": 1, "refund_reason": 1},
            ):
                for bid in ([pay["booking_id"]] if pay.get("booking_id") else []) + (pay.get("booking_ids") or []):
                    payment_map[bid] = pay
            for row in bookings:
                p = payment_map.get(row["id"])
                if p:
                    row["refund_status"] = p.get("refund_status")
                    row["refund_amount"] = p.get("refund_amount")
                    row["refund_reason"] = p.get("refund_reason")

        # Iter 68 — extended status buckets used by the Agency Schedule page.
        COMPLETED = {"completed", "reviewed"}
        UPCOMING = {"confirmed", "pending_artist", "pending_payment", "started"}
        PENDING = {"pending_artist", "pending_payment"}
        CANCELLED = {"cancelled", "rejected", "auto_expired"}

        completed_bookings = [x for x in bookings if x["status"] in COMPLETED]
        upcoming_bookings = [x for x in bookings if x["status"] in UPCOMING and (x.get("event_date") or "") >= today]
        confirmed_bookings = [x for x in bookings if x["status"] == "confirmed"]
        pending_bookings = [x for x in bookings if x["status"] in PENDING]
        cancelled_bookings = [x for x in bookings if x["status"] in CANCELLED]
        refunded_bookings = [x for x in bookings if x.get("refund_status") == "successful"]

        totals = {
            "total_bookings": len(bookings),
            "total_earnings": round(sum(x["artist_fee"] for x in bookings if x["status"] not in CANCELLED), 2),
            "completed_earnings": round(sum(x["artist_fee"] for x in completed_bookings), 2),
            "upcoming_earnings": round(sum(x["artist_fee"] for x in upcoming_bookings), 2),
            "confirmed_booking_value": round(sum(x["artist_fee"] for x in confirmed_bookings), 2),
            "agency_commission_earned": round(sum(x["agency_commission"] for x in completed_bookings), 2),
            "completed_events": len(completed_bookings),
            "upcoming_events": len(upcoming_bookings),
            "confirmed_events": len(confirmed_bookings),
            "pending_events": len(pending_bookings),
            "cancelled_events": len(cancelled_bookings),
            "refunded_events": len(refunded_bookings),
            "commission_pct": commission_pct,
        }

        prof = await db.artist_profiles.find_one({"user_id": artist_id}) or {}
        u = await db.users.find_one({"id": artist_id}) or {}
        artist = {
            "id": artist_id,
            "stage_name": prof.get("stage_name"),
            "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or u.get("email"),
            "category": prof.get("category"),
            "city": prof.get("city"),
            "email": u.get("email"),
        }
        return {"artist": artist, "totals": totals, "bookings": bookings}

    # Iter 68 — Schedule range endpoint (for calendar month/week/day queries).
    # Uses the compound `artist_id + event_date` index so the calendar loads
    # only the visible slice, not the artist's entire history.
    @r.get("/agency/artist/{artist_id}/schedule")
    async def agency_artist_schedule(
        artist_id: str,
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        """Return bookings in `[from, to]` inclusive (YYYY-MM-DD)."""
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        if user.get("role") == "agency":
            rel = await db.agency_roster.find_one({
                "agency_id": user["id"], "artist_id": artist_id, "status": "active",
            })
            if not rel:
                raise HTTPException(404, "Not an active artist in your roster")

        q: dict = {"artist_id": artist_id}
        if from_ and to:
            q["event_date"] = {"$gte": from_, "$lte": to}
        elif from_:
            q["event_date"] = {"$gte": from_}
        elif to:
            q["event_date"] = {"$lte": to}

        out = []
        async for b in db.bookings.find(q, {
            "_id": 0, "id": 1, "ref": 1, "event_date": 1, "event_time": 1,
            "event_type": 1, "venue": 1, "city": 1, "status": 1,
            "customer_name": 1, "package_name": 1, "amount_paid": 1, "pricing": 1,
            "payment_status": 1,
        }).sort("event_date", 1):
            p = b.get("pricing") or {}
            artist_fee = float(p.get("artist_fee",
                (p.get("package_fee", 0) or 0)
                + (p.get("addons_total", 0) or 0)
                - (p.get("coupon_discount", 0) or 0),
            ))
            out.append({**b, "artist_fee": artist_fee})
        return out

    # Iter 68 — Availability check for a proposed slot. The agency uses this
    # BEFORE creating a booking to prevent overlaps.
    @r.get("/agency/artist/{artist_id}/availability")
    async def agency_artist_availability(
        artist_id: str,
        date: str,
        event_time: Optional[str] = None,
        duration_hours: float = 4.0,
        user: dict = Depends(get_current_user),
    ):
        """Returns `{available: bool, conflicts: [...], reason?: str}`.

        Rule: a booking conflicts if it is `confirmed` / `started` AND its
        `event_date` matches AND its `event_time` overlaps the proposed
        window (default 4-hour block). Pending/cancelled bookings are
        treated as free so agencies can double-book pending requests.
        """
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        if user.get("role") == "agency":
            rel = await db.agency_roster.find_one({
                "agency_id": user["id"], "artist_id": artist_id, "status": "active",
            })
            if not rel:
                raise HTTPException(404, "Not an active artist in your roster")

        BUSY_STATUSES = {"confirmed", "started", "completed_by_artist", "completed"}

        def _to_min(hhmm):
            try:
                h, m = str(hhmm).split(":")[:2]
                return int(h) * 60 + int(m)
            except Exception:
                return None

        proposed_start = _to_min(event_time) if event_time else None
        proposed_end = (proposed_start + int(duration_hours * 60)) if proposed_start is not None else None

        conflicts = []
        async for b in db.bookings.find({
            "artist_id": artist_id,
            "event_date": date,
            "status": {"$in": list(BUSY_STATUSES)},
        }, {"_id": 0, "id": 1, "ref": 1, "event_time": 1, "status": 1,
             "event_type": 1, "venue": 1, "customer_name": 1}):
            other_start = _to_min(b.get("event_time"))
            # If either side has no explicit time, treat the whole day as busy.
            if proposed_start is None or other_start is None:
                conflicts.append(b)
                continue
            other_end = other_start + int(duration_hours * 60)
            if proposed_start < other_end and other_start < proposed_end:
                conflicts.append(b)

        return {
            "available": len(conflicts) == 0,
            "conflicts": conflicts,
            "reason": ("Artist is already booked during this time." if conflicts else None),
        }

    return r
