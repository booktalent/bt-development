"""
Outstation Analytics — Admin report (Iter 35).

Aggregates the booking snapshots captured in Iter 32:
  • is_outstation, artist_city, event_city on every booking

Endpoint: GET /admin/reports/outstation
  ?days=90           limit to bookings in the last N days (default all-time)

Returns:
  {
    "totals": {
        "total_bookings": int,
        "outstation_bookings": int,
        "outstation_pct": float,
        "avg_performance_fee": float,          # across all outstation
        "total_gmv_outstation": float,         # sum of artist_fee for outstation
    },
    "top_routes": [
        {"artist_city": "Mumbai", "event_city": "Delhi",
         "count": 12, "avg_fee": 65000, "total_fee": 780000}, ...
    ],
    "top_artist_cities": [...],
    "top_event_cities": [...],
    "generated_at": iso,
  }
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query


def make_router(*, db, admin_only, clean, **_extra) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/reports/outstation")
    async def outstation_report(
        _: dict = Depends(admin_only),
        days: Optional[int] = Query(None, ge=1, le=730),
        limit_routes: int = Query(15, ge=1, le=50),
    ):
        # Optional time filter — created_at is stored as ISO string, so we
        # compare ISO strings for Mongo range queries.
        match: dict = {}
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            match["created_at"] = {"$gte": cutoff}

        total = await db.bookings.count_documents(match)
        out_match = dict(match, is_outstation=True)
        outstation = await db.bookings.count_documents(out_match)

        # Sum + avg artist_fee for outstation bookings only
        pipeline = [
            {"$match": out_match},
            {"$group": {
                "_id": None,
                "total_gmv": {"$sum": "$pricing.artist_fee"},
                "avg_fee":   {"$avg": "$pricing.artist_fee"},
            }},
        ]
        total_row = None
        async for row in db.bookings.aggregate(pipeline):
            total_row = row
        total_gmv = round((total_row or {}).get("total_gmv") or 0, 2)
        avg_fee = round((total_row or {}).get("avg_fee") or 0, 2)

        # Top artist→event city routes
        routes_pipe = [
            {"$match": out_match},
            {"$group": {
                "_id": {"a": "$artist_city", "e": "$event_city"},
                "count":     {"$sum": 1},
                "avg_fee":   {"$avg": "$pricing.artist_fee"},
                "total_fee": {"$sum": "$pricing.artist_fee"},
            }},
            {"$sort": {"count": -1, "total_fee": -1}},
            {"$limit": limit_routes},
        ]
        top_routes = []
        async for row in db.bookings.aggregate(routes_pipe):
            top_routes.append({
                "artist_city": row["_id"].get("a") or "Unknown",
                "event_city":  row["_id"].get("e") or "Unknown",
                "count":       row["count"],
                "avg_fee":     round(row["avg_fee"] or 0, 2),
                "total_fee":   round(row["total_fee"] or 0, 2),
            })

        # Top source (artist) cities + destination (event) cities
        async def _top_by(field: str, k: int = 10) -> list:
            out = []
            pipe = [
                {"$match": out_match},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1},
                            "total_fee": {"$sum": "$pricing.artist_fee"}}},
                {"$sort": {"count": -1}},
                {"$limit": k},
            ]
            async for row in db.bookings.aggregate(pipe):
                out.append({
                    "city": row["_id"] or "Unknown",
                    "count": row["count"],
                    "total_fee": round(row["total_fee"] or 0, 2),
                })
            return out

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "totals": {
                "total_bookings": total,
                "outstation_bookings": outstation,
                "outstation_pct": round((outstation / total) * 100, 1) if total else 0.0,
                "total_gmv_outstation": total_gmv,
                "avg_performance_fee": avg_fee,
            },
            "top_routes": top_routes,
            "top_artist_cities": await _top_by("artist_city"),
            "top_event_cities": await _top_by("event_city"),
        }

    return r
