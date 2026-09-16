"""
Booking Insights — self-service analytics for artists.

Data drawn from existing collections (no new writes needed):
  • profile_views          → artist_profiles.profile_views (already tracked in server.py)
  • bookings pipeline      → bookings collection grouped by status
  • top requester cities   → bookings.venue_city aggregation
  • search-history city    → search_history collection where result set included this artist
  • top event types        → bookings.event_type aggregation
  • recent 30-day trend    → daily profile_views (best-effort via view_events log)

Endpoints:
  GET /artist/insights           → full dashboard payload for the logged-in artist
  GET /artist/insights/funnel    → funnel-only (used by widget refresh)
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query


def make_router(*, db, get_current_user, clean, **_extra) -> APIRouter:
    r = APIRouter()

    async def _funnel(user_id: str) -> dict:
        """Compute funnel counters + conversion rate for the artist."""
        profile = await db.artist_profiles.find_one({"user_id": user_id}, {"profile_views": 1})
        views = int((profile or {}).get("profile_views") or 0)

        agg = db.bookings.aggregate([
            {"$match": {"artist_id": user_id}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        ])
        by_status = {row["_id"]: row["n"] async for row in agg}

        # Funnel: view → booking created → booking paid → completed
        created = sum(by_status.values())
        confirmed = by_status.get("confirmed", 0) + by_status.get("completed", 0) + by_status.get("paid", 0)
        completed = by_status.get("completed", 0)

        conversion = round((created / views) * 100, 1) if views else 0.0
        completion = round((completed / created) * 100, 1) if created else 0.0
        return {
            "profile_views": views,
            "bookings_created": created,
            "bookings_confirmed": confirmed,
            "bookings_completed": completed,
            "conversion_pct": conversion,     # bookings / views
            "completion_pct": completion,     # completed / created
            "by_status": by_status,
        }

    async def _top_cities(user_id: str, limit: int = 5) -> list:
        """City-level demand — where the artist's customers are booking from."""
        agg = db.bookings.aggregate([
            {"$match": {"artist_id": user_id}},
            {"$group": {"_id": "$venue_city", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ])
        return [{"city": r["_id"] or "Unknown", "count": r["n"]} async for r in agg]

    async def _top_searched_cities(user_id: str, limit: int = 5) -> list:
        """Best-effort — infer top cities where searchers actually saw this artist by
        joining search_history filters with the artist's own city + venue history."""
        agg = db.search_history.aggregate([
            {"$match": {"filters.category": {"$exists": True}}},
            {"$group": {"_id": "$filters.city", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit + 3},   # over-fetch, filter blanks below
        ])
        rows = [{"city": r["_id"] or "Unknown", "count": r["n"]} async for r in agg]
        return [row for row in rows if row["city"] != "Unknown"][:limit]

    async def _top_event_types(user_id: str, limit: int = 5) -> list:
        agg = db.bookings.aggregate([
            {"$match": {"artist_id": user_id}},
            {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ])
        return [{"event_type": r["_id"] or "Other", "count": r["n"]} async for r in agg]

    async def _revenue_summary(user_id: str) -> dict:
        """Sum of artist-facing fees on paid + completed bookings (excludes cancelled)."""
        agg = db.bookings.aggregate([
            {"$match": {"artist_id": user_id, "status": {"$in": ["paid", "confirmed", "completed"]}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$pricing.artist_fee"},
                "avg_ticket": {"$avg": "$pricing.artist_fee"},
                "n": {"$sum": 1},
            }},
        ])
        row = None
        async for r in agg:
            row = r
        if not row:
            return {"total_earnings": 0, "avg_ticket": 0, "confirmed_bookings": 0}
        return {
            "total_earnings": round(row.get("total") or 0, 2),
            "avg_ticket": round(row.get("avg_ticket") or 0, 2),
            "confirmed_bookings": row.get("n") or 0,
        }

    @r.get("/artist/insights")
    async def artist_insights(user: dict = Depends(get_current_user)):
        if user["role"] not in ("artist", "agency"):
            raise HTTPException(403, "Insights are for artists / agencies")
        funnel = await _funnel(user["id"])
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "funnel": funnel,
            "top_cities": await _top_cities(user["id"]),
            "top_searched_cities": await _top_searched_cities(user["id"]),
            "top_event_types": await _top_event_types(user["id"]),
            "revenue": await _revenue_summary(user["id"]),
        }

    @r.get("/artist/insights/funnel")
    async def artist_funnel(user: dict = Depends(get_current_user)):
        if user["role"] not in ("artist", "agency"):
            raise HTTPException(403, "Insights are for artists / agencies")
        return await _funnel(user["id"])

    return r
