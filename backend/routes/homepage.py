"""
Sprint 5 — Dynamic Homepage Sections.

Ten curated rails computed on-the-fly from artist_profiles + bookings + reviews.
Each rail returns up to `limit` artists in a compact card shape.

Rails:
  1. featured           — hand-picked featured / boosted artists
  2. trending           — most booked in the last 30 days
  3. elite              — Elite-plan artists only (💎)
  4. new_talent         — profiles created in the last 60 days
  5. top_rated          — rating_avg >= 4.5, sorted by review_count
  6. fastest_response   — response_sla_hours ascending (Elite/Platinum priority)
  7. best_value         — lowest starting_price among rating >= 4
  8. by_city_{city}     — top artists in the user's city (client passes ?city=)
  9. by_category_singers, by_category_djs, by_category_dancers — top of each

Endpoint: GET /homepage/sections?city=Mumbai&limit=8
Returns:  [{ "code": "...", "title": "...", "subtitle": "...", "items": [...] }]
"""
from __future__ import annotations
import re
from typing import Callable, Optional

from fastapi import APIRouter, Depends, Header, Query
from datetime import datetime, timedelta, timezone


def _slug(s: str) -> str:
    """Sanitize a string to a safe slug for use in URLs / data-testid."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


async def _enrich(db, docs: list, clean) -> list:
    """Attach starting_price, gallery_thumbs, plan_code to each artist."""
    out = []
    for p in docs:
        p = clean(p)
        pkgs = await db.packages.find({"artist_id": p["user_id"]}).to_list(20)
        p["starting_price"] = min((float(pp.get("price", 0)) for pp in pkgs), default=None)
        gallery = await db.media.find(
            {"user_id": p["user_id"], "type": "gallery"},
            {"data": 0, "thumb": 0},
        ).sort([("is_featured", -1), ("order", 1)]).limit(6).to_list(6)
        p["gallery_thumbs"] = [{"id": g["id"], "is_featured": g.get("is_featured", False)} for g in gallery]
        out.append(p)
    return out


def make_router(*, db, clean, get_current_user_optional=None, **_extra) -> APIRouter:
    r = APIRouter()

    async def _personal_rails(user_id: str, limit: int) -> list:
        """Sprint 5+ Smart Homepage — computed from user's search + booking history.

        Emits up to 3 personalized rails placed FIRST when a user is logged in:
          • recent_category      — "Because you searched <category>"
          • continue_in_city     — "Continue browsing in <city>"
          • rebook               — "You've booked <artist> before"
        """
        out = []

        # ── Continue browsing in your favourite city ──────────────
        hist = await db.search_history.find({"user_id": user_id}).sort("created_at", -1).limit(20).to_list(20)
        cities = [(h.get("filters") or {}).get("city") for h in hist]
        cities = [c for c in cities if c]
        top_city = None
        if cities:
            # pick the most common recent city
            from collections import Counter
            top_city = Counter(cities).most_common(1)[0][0]
        if top_city:
            docs = await db.artist_profiles.find({"city": {"$regex": f"^{top_city}$", "$options": "i"}}).sort([("plan_rank", -1), ("rating_avg", -1)]).limit(limit).to_list(limit)
            items = await _enrich(db, docs, clean)
            if items:
                out.append({"code": "continue_in_city", "title": f"📍 Continue Browsing in {top_city}",
                            "subtitle": "Picking up where you left off", "items": items,
                            "personalised": True})

        # ── Because you searched <category> ──────────────────────
        categories = [(h.get("filters") or {}).get("category") for h in hist]
        categories = [c for c in categories if c]
        top_cat = None
        if categories:
            from collections import Counter
            top_cat = Counter(categories).most_common(1)[0][0]
        if top_cat:
            docs = await db.artist_profiles.find({"category": top_cat}).sort([("plan_rank", -1), ("rating_avg", -1)]).limit(limit).to_list(limit)
            items = await _enrich(db, docs, clean)
            if items:
                out.append({"code": "because_you_searched", "title": f"🎯 Because you searched {top_cat}",
                            "subtitle": "More artists you might love", "items": items,
                            "personalised": True})

        # ── Book them again ──────────────────────────────────────
        bookings = await db.bookings.find({"customer_id": user_id}).sort("created_at", -1).limit(10).to_list(10)
        artist_ids = list({b.get("artist_id") for b in bookings if b.get("artist_id")})
        if artist_ids:
            docs = await db.artist_profiles.find({"user_id": {"$in": artist_ids}}).limit(limit).to_list(limit)
            items = await _enrich(db, docs, clean)
            if items:
                out.append({"code": "rebook", "title": "🔁 Book Them Again",
                            "subtitle": "Artists you've booked before", "items": items,
                            "personalised": True})
        return out

    @r.get("/homepage/sections")
    async def homepage_sections(
        city: Optional[str] = Query(None),
        limit: int = Query(8, ge=1, le=20),
        authorization: Optional[str] = Header(None),
    ):
        # Try to resolve the caller (optional — this endpoint is public)
        user = None
        if authorization and get_current_user_optional:
            user = await get_current_user_optional(authorization)

        rails = []
        # Prepend personalized rails when we can identify the user
        if user and user.get("role") == "customer":
            personal = await _personal_rails(user["id"], limit)
            rails.extend(personal)

        # 1. Featured
        cur = db.artist_profiles.find({"$or": [{"is_featured": True}, {"is_boosted": True}]}).sort("rating_avg", -1).limit(limit)
        items = await _enrich(db, await cur.to_list(limit), clean)
        rails.append({"code": "featured", "title": "✨ Featured Artists", "subtitle": "Hand-picked by BookTalent", "items": items})

        # 2. Trending — most booked in last 30 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pipe = [
            {"$match": {"created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$artist_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        rows = await db.bookings.aggregate(pipe).to_list(limit)
        artist_ids = [r["_id"] for r in rows if r.get("_id")]
        if artist_ids:
            docs = await db.artist_profiles.find({"user_id": {"$in": artist_ids}}).to_list(limit)
            # preserve trending order
            by_id = {d["user_id"]: d for d in docs}
            ordered = [by_id[a] for a in artist_ids if a in by_id]
            items = await _enrich(db, ordered, clean)
        else:
            items = []
        rails.append({"code": "trending", "title": "🔥 Trending This Month", "subtitle": "Most booked in the last 30 days", "items": items})

        # 3. Elite plan artists
        cur = db.artist_profiles.find({"plan_code": "elite"}).sort("rating_avg", -1).limit(limit)
        items = await _enrich(db, await cur.to_list(limit), clean)
        if items:
            rails.append({"code": "elite", "title": "💎 Elite Artists", "subtitle": "Our top-tier performers", "items": items})

        # 4. New Talent — created in last 60 days
        cutoff2 = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        cur = db.artist_profiles.find({"created_at": {"$gte": cutoff2}}).sort("created_at", -1).limit(limit)
        items = await _enrich(db, await cur.to_list(limit), clean)
        if items:
            rails.append({"code": "new_talent", "title": "🌟 New Talent", "subtitle": "Fresh faces just joined", "items": items})

        # 5. Top Rated
        cur = db.artist_profiles.find({"rating_avg": {"$gte": 4.5}}).sort([("rating_avg", -1), ("review_count", -1)]).limit(limit)
        items = await _enrich(db, await cur.to_list(limit), clean)
        rails.append({"code": "top_rated", "title": "⭐ Top Rated", "subtitle": "Rated 4.5+ by real customers", "items": items})

        # 6. Fastest Response
        cur = db.artist_profiles.find({"plan_code": {"$in": ["platinum", "elite"]}}).sort("plan_rank", -1).limit(limit)
        items = await _enrich(db, await cur.to_list(limit), clean)
        if items:
            rails.append({"code": "fastest_response", "title": "⚡ Fastest Response", "subtitle": "Reply within 2-6 hours", "items": items})

        # 7. Best Value — good rating + lower price
        docs = await db.artist_profiles.find({"rating_avg": {"$gte": 4.0}}).sort("rating_avg", -1).limit(50).to_list(50)
        enriched = await _enrich(db, docs, clean)
        enriched.sort(key=lambda x: x.get("starting_price") or 1e9)
        items = enriched[:limit]
        rails.append({"code": "best_value", "title": "💰 Best Value", "subtitle": "Great artists, honest prices", "items": items})

        # 8. Best in your city
        if city:
            cur = db.artist_profiles.find({"city": {"$regex": f"^{city}$", "$options": "i"}}).sort("rating_avg", -1).limit(limit)
            items = await _enrich(db, await cur.to_list(limit), clean)
            if items:
                rails.append({"code": f"city_{city.lower()}", "title": f"📍 Best in {city}", "subtitle": f"Top-rated artists near you", "items": items})

        # 9-11. By Category — Singers / DJs / Dancers
        for slug, title, icon in [
            ("Bollywood Vocalist", "Singers", "🎤"),
            ("DJ / Music Producer", "DJs", "🎧"),
            ("Dancer", "Dancers", "💃"),
        ]:
            cur = db.artist_profiles.find({"category": slug}).sort([("plan_rank", -1), ("rating_avg", -1)]).limit(limit)
            items = await _enrich(db, await cur.to_list(limit), clean)
            if items:
                rails.append({"code": f"cat_{_slug(slug)}", "title": f"{icon} Top {title}", "subtitle": f"India's leading {title.lower()}", "items": items})

        return rails

    @r.get("/homepage/spotlight")
    async def homepage_spotlight():
        """Iter 42 — powers the floating artist cards + booking pulse on the
        landing hero. Priority order for the 3 cards:

          1. Artists holding an active `homepage_banner` boost (recency-sorted).
          2. Admin-featured artists (`is_featured=true`) to fill any gaps.

        Also returns the most recent confirmed booking so we can render the
        "New booking confirmed · <venue> · <date>" toast for social proof.
        """
        cards, seen = [], set()

        # 1. Active homepage_banner boost buyers
        now = datetime.now(timezone.utc).isoformat()
        subs = await db.boost_subscriptions.find({
            "type": "homepage_banner", "status": "active",
            "expires_at": {"$gt": now},
        }).sort("created_at", -1).limit(6).to_list(6)
        boost_ids = [s["artist_id"] for s in subs if s.get("artist_id")]
        if boost_ids:
            docs = await db.artist_profiles.find({"user_id": {"$in": boost_ids}}).to_list(len(boost_ids))
            by_id = {d["user_id"]: d for d in docs}
            for aid in boost_ids:
                if aid in by_id and aid not in seen:
                    cards.append(by_id[aid]); seen.add(aid)
                if len(cards) >= 3:
                    break

        # 2. Fill with featured artists if fewer than 3 spotlight buyers.
        if len(cards) < 3:
            fill = await db.artist_profiles.find({
                "is_featured": True, "user_id": {"$nin": list(seen) or [""]}
            }).sort("rating_avg", -1).limit(3 - len(cards)).to_list(3)
            for d in fill:
                if d["user_id"] not in seen:
                    cards.append(d); seen.add(d["user_id"])
                if len(cards) >= 3:
                    break

        # 3. Fallback: top-rated overall
        if len(cards) < 3:
            fill = await db.artist_profiles.find({
                "user_id": {"$nin": list(seen) or [""]}
            }).sort([("rating_avg", -1), ("review_count", -1)]).limit(3 - len(cards)).to_list(3)
            for d in fill:
                if d["user_id"] not in seen:
                    cards.append(d); seen.add(d["user_id"])
                if len(cards) >= 3:
                    break

        enriched = await _enrich(db, cards, clean)

        # Social-proof toast — the most recent confirmed booking.
        latest_toast = None
        recent = await db.bookings.find({
            "status": {"$in": ["confirmed", "completed"]}
        }).sort("created_at", -1).limit(1).to_list(1)
        if recent:
            b = recent[0]
            latest_toast = {
                "venue": b.get("venue") or b.get("event_venue") or b.get("event_city") or "Private Event",
                "event_date": (b.get("event_date") or b.get("created_at") or "")[:10],
            }

        return {
            "cards": enriched,
            "spotlight_active": len(boost_ids) > 0,
            "latest_booking": latest_toast,
        }

    # ── Impression tracking (Iter 45) ────────────────────────────────────
    @r.post("/homepage/spotlight/impression")
    async def spotlight_impression(payload: dict):
        """
        Records one impression per artist per session per day so a rotating
        card doesn't inflate the count on the same browser. Payload:
          { "user_id": "<artist user_id>", "session": "<random client id>" }
        """
        aid = (payload or {}).get("user_id")
        sess = (payload or {}).get("session") or "anon"
        if not aid:
            return {"ok": False}
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{aid}|{sess}|{day}"
        try:
            # Idempotent — the unique key stops the same session from double-counting.
            await db.spotlight_impressions.insert_one({
                "artist_id": aid, "session": sess, "day": day,
                "key": key, "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            # Duplicate key means we already counted this session today.
            return {"ok": True, "deduped": True}
        return {"ok": True}

    @r.get("/artist/analytics/spotlight/{artist_id}")
    async def artist_spotlight_stats(artist_id: str):
        """Returns total impressions + last-7-day impressions for the artist's
        Homepage Banner boost so it can be surfaced in the Artist dashboard."""
        from collections import Counter
        docs = await db.spotlight_impressions.find({"artist_id": artist_id}).to_list(20000)
        total = len(docs)
        # last 7 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        last7 = sum(1 for d in docs if (d.get("day") or "") >= cutoff)
        # daily breakdown for spark line
        by_day = Counter(d.get("day") for d in docs if d.get("day") and d["day"] >= cutoff)
        return {
            "total_impressions": total,
            "last_7d": last7,
            "series": [{"day": k, "count": by_day[k]} for k in sorted(by_day.keys())],
        }

    # ── Localised category counts (Iter 45) ──────────────────────────────
    @r.get("/homepage/category-stats")
    async def category_stats(city: Optional[str] = None):
        """Returns artist counts per category, optionally scoped to a city.
        The frontend uses this to highlight categories that are strongest in
        the visitor's city so the Categories grid feels local."""
        query = {}
        if city:
            query["city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}
        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        ]
        cur = db.artist_profiles.aggregate(pipeline)
        out = {}
        async for doc in cur:
            if doc.get("_id"):
                out[doc["_id"].lower()] = doc["count"]
        return {"city": city or "", "counts": out}

    return r
