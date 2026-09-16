"""
Event umbrella endpoints — Multi-Artist Event recap + summary.

Extracted from server.py (iter 48) to keep the mega-file honest. Every
endpoint here operates on `bookings.event_id` — the umbrella UUID shared by
every artist a customer hires for the same event.

The batch booking + batch payment endpoints (POST /bookings/batch,
POST /payments/batch/*) stay in server.py for now because they depend on the
tightly-coupled create_booking + calc_booking_pricing helpers; extracting
them cleanly is tracked separately in the backlog.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException


def make_router(
    *,
    db: Any,
    get_current_user: Callable,
    clean: Callable,
) -> APIRouter:
    """Wire up event endpoints with the collaborators from server.py."""
    r = APIRouter()

    @r.get("/events/{event_id}/recap")
    async def event_recap(event_id: str) -> Dict[str, Any]:
        """Public shareable recap for an event. No auth — returns only
        artist-side and event-side info, never customer contact or payment
        details. Used by the /recap/:event_id share page."""
        active_statuses: List[str] = [
            "pending_artist", "confirmed", "started", "completed", "reviewed",
        ]
        docs = await db.bookings.find(
            {"event_id": event_id, "status": {"$in": active_statuses}},
        ).to_list(20)

        if not docs:
            # Backward-compat: any legacy single-artist booking is shareable
            # via its own booking id (before the event_id column was introduced).
            legacy = await db.bookings.find_one({"id": event_id})
            if legacy and legacy.get("status") in active_statuses:
                docs = [legacy]
        if not docs:
            raise HTTPException(404, "Event not found")

        docs.sort(key=lambda d: (d.get("event_date", ""), d.get("artist_id", "")))
        artists: List[Dict[str, Any]] = []
        seen: set = set()
        for d in docs:
            aid = d["artist_id"]
            if aid in seen:
                continue
            seen.add(aid)
            artist_user = await db.users.find_one({"id": aid}) or {}
            profile = await db.artist_profiles.find_one({"user_id": aid}) or {}
            display_name = (
                profile.get("stage_name")
                or f"{artist_user.get('first_name', '')} {artist_user.get('last_name', '')}".strip()
                or "Artist"
            )
            artists.append({
                "user_id": aid,
                "stage_name": display_name,
                "category": profile.get("category"),
                "city": profile.get("city"),
                "emoji": profile.get("emoji") or "🎤",
                "featured_media_id": profile.get("featured_media_id"),
                "rating_avg": profile.get("rating_avg", 0),
                "profile_url": f"/artist/{aid}",
                "booking_ref": d["ref"],
                "booking_status": d["status"],
            })

        head = docs[0]
        host_user = await db.users.find_one({"id": head["customer_id"]}) or {}
        host_name = (
            (head.get("customer_name") or host_user.get("first_name") or "")
            .split(" ")[0]
            or "The Host"
        )

        return {
            "event_id": event_id,
            "event_date": head.get("event_date"),
            "event_time": head.get("event_time"),
            "event_type": head.get("event_type"),
            "venue": head.get("venue"),
            "city": head.get("city"),
            "host_first_name": host_name,
            "artist_count": len(artists),
            "artists": artists,
            "booked_via": "BookTalent",
        }

    @r.get("/events/{event_id}/summary")
    async def event_summary(event_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        """Authenticated event summary for the customer — includes payment
        aggregates and per-booking status. Used by the Customer Dashboard
        event view + the Share button."""
        docs = await db.bookings.find({"event_id": event_id}).to_list(20)
        if not docs:
            raise HTTPException(404, "Event not found")
        if user["role"] != "admin" and docs[0]["customer_id"] != user["id"]:
            raise HTTPException(403, "Not your event")

        total_platform_fee = sum(float(d.get("pricing", {}).get("platform_fee", 0)) for d in docs)
        total_gst = sum(float(d.get("pricing", {}).get("gst", 0)) for d in docs)
        total_paid = sum(float(d.get("amount_paid", 0)) for d in docs)
        return {
            "event_id": event_id,
            "bookings": [clean(d) for d in docs],
            "aggregate": {
                "platform_fee": round(total_platform_fee, 2),
                "gst": round(total_gst, 2),
                "amount_paid": round(total_paid, 2),
                "count": len(docs),
            },
        }

    return r
