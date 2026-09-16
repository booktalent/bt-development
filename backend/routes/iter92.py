"""
Iter 92 — 3 features in one focused router:
  1. Admin Analytics KPIs (/admin/analytics/*)
  2. Public Trust Page stats (/public/trust-stats)
  3. Per-user Notification Preferences (/user/notification-preferences)

The notification_service also imports `is_channel_muted` from here to
respect per-user opt-outs at dispatch time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("iter92")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Notification preference helper (imported by notification_service)
# ═══════════════════════════════════════════════════════════════════════
# Sane defaults — all channels ON for critical events, OFF for marketing.
DEFAULT_PREFS: Dict[str, Dict[str, bool]] = {
    # Booking / payment lifecycle — mandatory transactional (all ON, non-mutable).
    "booking.confirmed":   {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    "payment.received":    {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    "payout.released":     {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    "kyc.approved":        {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    "kyc.rejected":        {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    "kyc.needs_resubmission": {"in_app": True, "email": True, "whatsapp": True, "sms": True},
    # Reminders — mutable.
    "event.reminder":      {"in_app": True, "email": True, "whatsapp": True, "sms": False},
    "payment.reminder":    {"in_app": True, "email": True, "whatsapp": True, "sms": False},
    # Marketing / nudges — mutable (default whatsapp off, email on).
    "marketing.digest":    {"in_app": True, "email": True, "whatsapp": False, "sms": False},
    "profile.nudge":       {"in_app": True, "email": False, "whatsapp": False, "sms": False},
}
# Events users cannot opt out of (regulatory / transactional).
FORCE_ON_EVENTS = {
    "booking.confirmed", "payment.received", "payout.released",
    "kyc.approved", "kyc.rejected", "kyc.needs_resubmission",
}


async def is_channel_muted(db: AsyncIOMotorDatabase, *, user_id: str,
                            event: str, channel: str) -> bool:
    """Return True when the user has explicitly opted out of `channel`
    for `event`. Force-on events always return False."""
    if event in FORCE_ON_EVENTS:
        return False
    u = await db.users.find_one({"id": user_id}, {"notification_preferences": 1, "_id": 0}) or {}
    prefs = (u.get("notification_preferences") or {}).get(event)
    if not prefs:
        # No override → use defaults
        return not DEFAULT_PREFS.get(event, {}).get(channel, True)
    return not prefs.get(channel, DEFAULT_PREFS.get(event, {}).get(channel, True))


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
class NotifPrefsBody(BaseModel):
    preferences: Dict[str, Dict[str, bool]] = Field(default_factory=dict)


def make_iter92_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ─── 1. Admin Analytics KPIs ─────────────────────────────────
    @r.get("/admin/analytics/kpis")
    async def admin_kpis(days: int = Query(30, ge=1, le=365),
                         _: dict = Depends(require_admin)):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days))
        cutoff_iso = cutoff.isoformat()
        cutoff_date = cutoff.strftime("%Y-%m-%d")

        # Confirmed/completed bookings in period
        gmv = 0.0
        net_platform_revenue = 0.0
        gst = 0.0
        booking_count = 0
        artist_ids = set()
        completed_events = 0

        async for b in db.bookings.find(
            {"status": {"$in": ["confirmed", "completed", "reviewed"]},
             "event_date": {"$gte": cutoff_date}},
            {"_id": 0, "pricing": 1, "artist_id": 1, "status": 1},
        ):
            booking_count += 1
            if b.get("artist_id"):
                artist_ids.add(b["artist_id"])
            if b.get("status") in ("completed", "reviewed"):
                completed_events += 1
            p = b.get("pricing") or {}
            gmv += float(p.get("total", 0) or 0)
            net_platform_revenue += float(p.get("platform_fee", 0) or 0)
            gst += float(p.get("gst", 0) or 0)

        # New signups
        new_customers = await db.users.count_documents({
            "role": "customer", "created_at": {"$gte": cutoff_iso},
        })
        new_artists = await db.users.count_documents({
            "role": "artist", "created_at": {"$gte": cutoff_iso},
        })

        # Verified artists total (KYC live)
        verified_artists = await db.artist_profiles.count_documents({
            "kyc_status": {"$in": ["kyc_approved", "tnc_pending", "agreement_generated", "live"]},
        })

        # Pipeline volume — leads created in period
        leads_new = await db.leads.count_documents({"created_at": {"$gte": cutoff_iso}})
        leads_won = await db.leads.count_documents({
            "stage": "closed",
            "updated_at": {"$gte": cutoff_iso},
        })

        return {
            "period_days": days,
            "gmv": round(gmv, 2),
            "net_platform_revenue": round(net_platform_revenue, 2),
            "gst_collected": round(gst, 2),
            "bookings": booking_count,
            "completed_events": completed_events,
            "avg_booking_value": round(gmv / booking_count, 2) if booking_count else 0,
            "active_artists": len(artist_ids),
            "verified_artists_total": verified_artists,
            "new_customers": new_customers,
            "new_artists": new_artists,
            "leads_new": leads_new,
            "leads_won": leads_won,
            "conversion_pct": round((leads_won / leads_new) * 100, 1) if leads_new else 0,
        }

    @r.get("/admin/analytics/funnel")
    async def admin_funnel(days: int = Query(30, ge=1, le=365),
                            _: dict = Depends(require_admin)):
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cutoff_date = cutoff_iso[:10]

        # Count each stage
        leads = await db.leads.count_documents({"created_at": {"$gte": cutoff_iso}})
        quoted = await db.leads.count_documents({
            "stage": {"$in": ["quotation_sent", "negotiation", "booking_pending",
                              "booking_confirmed", "payment_pending", "event_upcoming",
                              "event_completed", "closed"]},
            "created_at": {"$gte": cutoff_iso},
        })
        bookings = await db.bookings.count_documents({"created_at": {"$gte": cutoff_iso}})
        confirmed = await db.bookings.count_documents({
            "status": {"$in": ["confirmed", "started", "completed", "reviewed"]},
            "created_at": {"$gte": cutoff_iso},
        })
        paid = await db.bookings.count_documents({
            "payment_status": {"$in": ["partial", "paid", "fully_paid"]},
            "created_at": {"$gte": cutoff_iso},
        })
        completed = await db.bookings.count_documents({
            "status": {"$in": ["completed", "reviewed"]},
            "event_date": {"$gte": cutoff_date},
        })

        return {
            "period_days": days,
            "stages": [
                {"label": "Leads", "count": leads, "conversion_from_prev": None},
                {"label": "Quoted", "count": quoted,
                 "conversion_from_prev": round((quoted / leads) * 100, 1) if leads else 0},
                {"label": "Bookings Created", "count": bookings,
                 "conversion_from_prev": round((bookings / quoted) * 100, 1) if quoted else 0},
                {"label": "Confirmed", "count": confirmed,
                 "conversion_from_prev": round((confirmed / bookings) * 100, 1) if bookings else 0},
                {"label": "Paid", "count": paid,
                 "conversion_from_prev": round((paid / confirmed) * 100, 1) if confirmed else 0},
                {"label": "Completed Events", "count": completed,
                 "conversion_from_prev": round((completed / paid) * 100, 1) if paid else 0},
            ],
        }

    @r.get("/admin/analytics/churn")
    async def admin_churn(_: dict = Depends(require_admin)):
        """Artists who had bookings LAST month but ZERO this month."""
        now = datetime.now(timezone.utc)
        this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if this_start.month == 1:
            last_start = this_start.replace(year=this_start.year - 1, month=12)
        else:
            last_start = this_start.replace(month=this_start.month - 1)

        # Artist IDs booked in last full month
        last_month_ids = set()
        async for b in db.bookings.find({
            "status": {"$in": ["confirmed", "completed", "reviewed"]},
            "event_date": {
                "$gte": last_start.strftime("%Y-%m-%d"),
                "$lt": this_start.strftime("%Y-%m-%d"),
            },
        }, {"_id": 0, "artist_id": 1}):
            if b.get("artist_id"):
                last_month_ids.add(b["artist_id"])

        # Artist IDs booked this month
        this_month_ids = set()
        async for b in db.bookings.find({
            "status": {"$in": ["confirmed", "completed", "reviewed"]},
            "event_date": {"$gte": this_start.strftime("%Y-%m-%d")},
        }, {"_id": 0, "artist_id": 1}):
            if b.get("artist_id"):
                this_month_ids.add(b["artist_id"])

        churned = last_month_ids - this_month_ids
        retained = last_month_ids & this_month_ids

        return {
            "last_month": last_start.strftime("%Y-%m"),
            "this_month": this_start.strftime("%Y-%m"),
            "last_month_active": len(last_month_ids),
            "this_month_active": len(this_month_ids),
            "retained": len(retained),
            "churned": len(churned),
            "churn_pct": round((len(churned) / len(last_month_ids)) * 100, 1) if last_month_ids else 0,
        }

    @r.get("/admin/analytics/daily")
    async def admin_daily(days: int = Query(30, ge=1, le=90),
                           _: dict = Depends(require_admin)):
        """Daily GMV + booking count for the line chart."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_date = cutoff.strftime("%Y-%m-%d")
        by_date: Dict[str, Dict[str, float]] = {}
        async for b in db.bookings.find({
            "status": {"$in": ["confirmed", "completed", "reviewed"]},
            "event_date": {"$gte": cutoff_date},
        }, {"_id": 0, "event_date": 1, "pricing": 1}):
            date = b.get("event_date", "")[:10]
            row = by_date.setdefault(date, {"date": date, "gmv": 0, "bookings": 0})
            row["gmv"] += float((b.get("pricing") or {}).get("total", 0) or 0)
            row["bookings"] += 1
        # Fill missing days for a smooth chart
        series = []
        for i in range(days, -1, -1):
            d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            series.append(by_date.get(d, {"date": d, "gmv": 0, "bookings": 0}))
        return {"series": series, "period_days": days}

    # ─── 2. Public Trust Page stats ──────────────────────────────
    @r.get("/public/trust-stats")
    async def public_trust_stats():
        """No-auth endpoint powering the /trust marketing page."""
        # Verified artists (KYC live)
        verified = await db.artist_profiles.count_documents({
            "kyc_status": {"$in": ["kyc_approved", "tnc_pending", "agreement_generated", "live"]},
        })
        # Completed events all-time
        completed = await db.bookings.count_documents({
            "status": {"$in": ["completed", "reviewed"]},
        })
        # Cities served (distinct cities in artist_profiles + bookings)
        cities_set = set()
        async for a in db.artist_profiles.find(
            {"city": {"$exists": True, "$ne": ""}}, {"_id": 0, "city": 1},
        ):
            if a.get("city"):
                cities_set.add(a["city"].strip().title())
        async for b in db.bookings.find(
            {"city": {"$exists": True, "$ne": ""}}, {"_id": 0, "city": 1},
        ):
            if b.get("city"):
                cities_set.add(b["city"].strip().title())
        # Average rating
        pipeline = [{"$group": {"_id": None,
                                 "avg": {"$avg": "$rating"},
                                 "count": {"$sum": 1}}}]
        cur = db.reviews.aggregate(pipeline)
        agg = None
        async for row in cur:
            agg = row
        # Total bookings all-time
        total_bookings = await db.bookings.count_documents({})
        return {
            "verified_artists": verified,
            "completed_events": completed,
            "cities_served": len(cities_set),
            "top_cities": sorted(cities_set)[:10],
            "avg_rating": round(agg.get("avg", 0), 1) if agg else 0,
            "total_reviews": (agg or {}).get("count", 0),
            "total_bookings": total_bookings,
        }

    # ─── 3. Notification preferences (per-user) ──────────────────
    @r.get("/user/notification-preferences")
    async def get_prefs(user: dict = Depends(get_current_user)):
        u = await db.users.find_one({"id": user["id"]}, {"notification_preferences": 1, "_id": 0}) or {}
        overrides = u.get("notification_preferences") or {}
        # Build a full response merging defaults + overrides so the UI has
        # a stable shape regardless of what's been saved.
        merged: Dict[str, Dict[str, Any]] = {}
        for ev, defaults in DEFAULT_PREFS.items():
            saved = overrides.get(ev, {})
            merged[ev] = {
                "email":    saved.get("email",    defaults.get("email", True)),
                "whatsapp": saved.get("whatsapp", defaults.get("whatsapp", True)),
                "in_app":   saved.get("in_app",   defaults.get("in_app", True)),
                "sms":      saved.get("sms",      defaults.get("sms", False)),
                "force_on": ev in FORCE_ON_EVENTS,
            }
        return {
            "preferences": merged,
            "force_on_events": sorted(FORCE_ON_EVENTS),
        }

    @r.patch("/user/notification-preferences")
    async def set_prefs(body: NotifPrefsBody, user: dict = Depends(get_current_user)):
        # Sanitise — only accept known events and known channels; force-on
        # events silently ignored (server-side enforcement).
        clean_map: Dict[str, Dict[str, bool]] = {}
        for ev, chans in (body.preferences or {}).items():
            if ev not in DEFAULT_PREFS or ev in FORCE_ON_EVENTS:
                continue
            row: Dict[str, bool] = {}
            for c in ("email", "whatsapp", "in_app", "sms"):
                if c in chans:
                    row[c] = bool(chans[c])
            if row:
                clean_map[ev] = row
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"notification_preferences": clean_map, "notification_prefs_updated_at": utcnow_iso()}},
        )
        return {"ok": True, "saved_events": list(clean_map.keys())}

    return r
