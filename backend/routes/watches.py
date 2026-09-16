"""
Iter 50 — Save-a-Watch
----------------------
Lets a visitor save a filter combo (city + category + date) and be pinged
when a new matching artist joins BookTalent or opens up on that date.

Notification delivery is intentionally minimal (in-app notification row +
optional email) so we keep the surface area small and the DB clean.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


class WatchBody(BaseModel):
    city: Optional[str] = None
    category: Optional[str] = None
    event_date: Optional[str] = None
    label: Optional[str] = Field(None, max_length=120)


def make_router(*, get_current_user: Callable, db: Any, utcnow: Callable) -> APIRouter:
    r = APIRouter()

    @r.post("/watches")
    async def create_watch(body: WatchBody, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        """Save a filter combo. Any of city/category/event_date may be empty
        — but at least one must be present to make the watch meaningful."""
        if not (body.city or body.category or body.event_date):
            raise HTTPException(400, "Set at least one of city / category / event_date")
        doc = {
            "id": str(uuid4()),
            "user_id": user["id"],
            "city": (body.city or "").strip() or None,
            "category": (body.category or "").strip() or None,
            "event_date": body.event_date or None,
            "label": (body.label or "").strip() or None,
            "created_at": utcnow(),
            "last_pinged_at": None,
            "match_count": 0,
        }
        await db.watches.insert_one(doc)
        doc.pop("_id", None)  # never leak Mongo's ObjectId back to JSON
        return {"ok": True, "watch": doc}

    @r.get("/watches")
    async def list_watches(user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
        docs = await db.watches.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
        for d in docs:
            d.pop("_id", None)
        return docs

    @r.delete("/watches/{watch_id}")
    async def delete_watch(watch_id: str, user: dict = Depends(get_current_user)) -> Dict[str, bool]:
        res = await db.watches.delete_one({"id": watch_id, "user_id": user["id"]})
        if res.deleted_count == 0:
            raise HTTPException(404, "Watch not found")
        return {"ok": True}

    @r.post("/watches/_recheck")
    async def recheck_watches(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
        """Manually re-scan every one of the caller's watches for new matches
        and insert a notification row when the match count grew since last check.
        In production, a cron would call this periodically for every user."""
        watches = await db.watches.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
        pinged = 0
        for w in watches:
            q: Dict[str, Any] = {}
            if w.get("city"):
                q["city"] = {"$regex": f"^{w['city']}", "$options": "i"}
            if w.get("category"):
                q["category"] = {"$regex": w["category"], "$options": "i"}
            # Skip artists booked on the requested date if one is set
            excluded_ids: set = set()
            if w.get("event_date"):
                booked = await db.bookings.find(
                    {"event_date": w["event_date"],
                     "status": {"$in": ["pending_artist", "confirmed", "started", "completed"]}},
                    {"artist_id": 1},
                ).to_list(500)
                excluded_ids = {b["artist_id"] for b in booked}
            profiles = await db.artist_profiles.find(q).to_list(200)
            fresh = [p for p in profiles if p.get("user_id") not in excluded_ids]
            new_count = len(fresh)
            if new_count > int(w.get("match_count", 0) or 0):
                # Fire an in-app notification
                await db.notifications.insert_one({
                    "id": str(uuid4()),
                    "user_id": user["id"],
                    "type": "watch_match",
                    "title": "New artist matches your watch",
                    "body": f"{new_count} artist{'s' if new_count > 1 else ''} now match "
                            f"{w.get('label') or (w.get('category') or 'your saved search')}"
                            f"{' in ' + w['city'] if w.get('city') else ''}",
                    "read": False,
                    "created_at": utcnow(),
                    "link": _watch_deep_link(w),
                })
                pinged += 1
            await db.watches.update_one(
                {"id": w["id"]},
                {"$set": {"match_count": new_count, "last_pinged_at": utcnow()}},
            )
        return {"ok": True, "pinged": pinged, "watches_checked": len(watches)}

    return r


def _watch_deep_link(w: Dict[str, Any]) -> str:
    from urllib.parse import urlencode
    params: Dict[str, str] = {}
    if w.get("city"): params["city"] = w["city"]
    if w.get("category"): params["category"] = w["category"]
    if w.get("event_date"): params["date"] = w["event_date"]
    return f"/discover?{urlencode(params)}" if params else "/discover"
