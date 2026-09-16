"""
Iter 67 — Artist City Requests (mirror of category_requests)
────────────────────────────────────────────────────────────
Workflow for artists whose primary city isn't in the cities master yet.

Endpoints:
  POST   /api/artist/city-requests               — artist submits
  GET    /api/artist/city-requests/mine          — artist's own history
  GET    /api/admin/city-requests                — admin queue
  GET    /api/admin/city-requests/similar        — dupe-check helper
  POST   /api/admin/city-requests/{id}/approve   — admin approves
  POST   /api/admin/city-requests/{id}/reject    — admin rejects

Approval logic:
  * If admin passes `existing_slug`, we reuse that master row.
  * Otherwise we create a new cities_master doc (slug auto-derived).
  * The requesting artist's profile.city is updated to the final name and
    `city_pending` flag is cleared. Artist is notified.

Reject logic:
  * `rejection_reason` stored on the request. Artist is notified.
  * No changes to cities_master.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "custom"


def _now():
    return datetime.now(timezone.utc).isoformat()


class SubmitCityRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    state: Optional[str] = None
    country: Optional[str] = "India"
    description: str = Field("", max_length=1000)
    reason: Optional[str] = None      # Why this city — e.g. venue types


class ApproveBody(BaseModel):
    existing_slug: Optional[str] = None
    new_name: Optional[str] = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=400)


def make_city_requests_router(*, db, get_current_user, admin_only, new_id):
    r = APIRouter()

    @r.post("/artist/city-requests")
    async def submit_request(body: SubmitCityRequest, user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        pending = await db.city_requests.find_one({
            "artist_id": user["id"], "status": "pending",
        })
        if pending:
            raise HTTPException(400, "You already have a pending city request. Wait for admin review.")
        prof = await db.artist_profiles.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
        doc = {
            "id": new_id(),
            "artist_id": user["id"],
            "artist_name": f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user.get("email"),
            "artist_email": user.get("email"),
            "stage_name": prof.get("stage_name"),
            "category": prof.get("category"),
            "requested_name": body.name.strip(),
            "requested_slug": _slugify(body.name),
            "state": (body.state or "").strip(),
            "country": (body.country or "India").strip(),
            "description": body.description.strip(),
            "reason": (body.reason or "").strip(),
            "status": "pending",
            "created_at": _now(),
        }
        await db.city_requests.insert_one(doc)

        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$set": {
                "city_pending": True,
                "pending_city_id": doc["id"],
                "pending_city_name": body.name.strip(),
            }},
        )
        try:
            async for adm in db.users.find({"role": "admin"}, {"_id": 0, "id": 1}):
                await db.notifications.insert_one({
                    "id": new_id(), "user_id": adm["id"],
                    "type": "city.request",
                    "title": "New Artist City request",
                    "body": f"{doc['artist_name']} requested '{doc['requested_name']}'.",
                    "link": f"/admin?tab=city-requests&highlight={doc['id']}",
                    "read": False, "created_at": _now(),
                })
        except Exception:
            pass
        doc.pop("_id", None)
        return doc

    @r.get("/artist/city-requests/mine")
    async def my_requests(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        docs = await db.city_requests.find(
            {"artist_id": user["id"]}, {"_id": 0},
        ).sort("created_at", -1).to_list(50)
        return docs

    @r.get("/admin/city-requests")
    async def admin_list(status: Optional[str] = None, _: dict = Depends(admin_only)):
        q = {}
        if status:
            q["status"] = status
        docs = await db.city_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
        return docs

    @r.get("/admin/city-requests/similar")
    async def admin_similar(name: str, _: dict = Depends(admin_only)):
        if not name:
            return []
        tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name.lower()) if len(t) >= 3]
        if not tokens:
            tokens = [name.lower()]
        rxs = [{"$regex": re.escape(t), "$options": "i"} for t in tokens]
        or_filters = []
        for rx in rxs:
            or_filters.append({"name": rx})
            or_filters.append({"slug": rx})
        rows = await db.cities_master.find({"$or": or_filters}, {"_id": 0}).limit(15).to_list(15)
        return rows

    async def _finalise_artist(req: dict, canonical_name: str, new_id_fn):
        await db.artist_profiles.update_one(
            {"user_id": req["artist_id"]},
            {"$set": {"city": canonical_name, "city_pending": False},
             "$unset": {"pending_city_id": "", "pending_city_name": ""}},
        )
        await db.notifications.insert_one({
            "id": new_id_fn(), "user_id": req["artist_id"],
            "type": "city.approved",
            "title": "Your city request was approved 🎉",
            "body": f"'{canonical_name}' is now live. Customers in that area can now discover you.",
            "link": "/artist?tab=profile",
            "read": False, "created_at": _now(),
        })

    @r.post("/admin/city-requests/{req_id}/approve")
    async def admin_approve(req_id: str, body: ApproveBody, admin: dict = Depends(admin_only)):
        req = await db.city_requests.find_one({"id": req_id})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] != "pending":
            raise HTTPException(400, f"Request is already {req['status']}")

        if body.existing_slug:
            existing = await db.cities_master.find_one({"slug": body.existing_slug})
            if not existing:
                raise HTTPException(404, "existing_slug not found in cities_master")
            canonical_name = existing["name"]
            canonical_slug = existing["slug"]
            await db.city_requests.update_one({"id": req_id}, {"$set": {
                "status": "approved",
                "decision": "reused_existing",
                "assigned_slug": canonical_slug,
                "assigned_name": canonical_name,
                "decided_at": _now(),
                "decided_by": admin["id"],
            }})
        else:
            new_name = (body.new_name or req["requested_name"]).strip()
            new_slug = _slugify(new_name)
            if await db.cities_master.find_one({"slug": new_slug}):
                raise HTTPException(
                    400,
                    f"City slug '{new_slug}' already exists. Pass existing_slug='{new_slug}' to reuse it.",
                )
            existing_ct = await db.cities_master.count_documents({})
            master_doc = {
                "id": new_id(),
                "slug": new_slug,
                "name": new_name,
                "sort_order": existing_ct + 1,
                "active": True,
                "created_at": _now(),
                "created_from_request": req_id,
            }
            await db.cities_master.insert_one(master_doc)
            canonical_name = new_name
            canonical_slug = new_slug
            await db.city_requests.update_one({"id": req_id}, {"$set": {
                "status": "approved",
                "decision": "created_new",
                "assigned_slug": new_slug,
                "assigned_name": new_name,
                "decided_at": _now(),
                "decided_by": admin["id"],
            }})

        await _finalise_artist(req, canonical_name, new_id)
        return {"ok": True, "assigned_name": canonical_name, "assigned_slug": canonical_slug}

    @r.post("/admin/city-requests/{req_id}/reject")
    async def admin_reject(req_id: str, body: RejectBody, admin: dict = Depends(admin_only)):
        req = await db.city_requests.find_one({"id": req_id})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] != "pending":
            raise HTTPException(400, f"Request is already {req['status']}")
        await db.city_requests.update_one({"id": req_id}, {"$set": {
            "status": "rejected",
            "rejection_reason": body.reason.strip(),
            "decided_at": _now(),
            "decided_by": admin["id"],
        }})
        await db.artist_profiles.update_one(
            {"user_id": req["artist_id"]},
            {"$set": {"city_pending": False},
             "$unset": {"pending_city_id": "", "pending_city_name": ""}},
        )
        await db.notifications.insert_one({
            "id": new_id(), "user_id": req["artist_id"],
            "type": "city.rejected",
            "title": "City request not approved",
            "body": f"Reason: {body.reason.strip()[:200]}",
            "link": "/artist?tab=profile",
            "read": False, "created_at": _now(),
        })
        return {"ok": True}

    return r
