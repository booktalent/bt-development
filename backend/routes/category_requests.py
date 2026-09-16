"""
Iter 66 — Artist Category Requests
──────────────────────────────────
Workflow for artists whose desired category isn't in the master list yet.

Endpoints:
  POST   /api/artist/category-requests               — artist submits
  GET    /api/artist/category-requests/mine          — artist's own history
  GET    /api/admin/category-requests                — admin queue
  GET    /api/admin/category-requests/similar        — dupe-check helper
  POST   /api/admin/category-requests/{id}/approve   — admin approves
  POST   /api/admin/category-requests/{id}/reject    — admin rejects

Approval logic:
  * If admin passes `existing_slug`, we reuse that master row.
  * Otherwise we create a new categories_master doc (slug auto-derived).
  * The requesting artist's profile.category is updated to the final name and
    `category_pending` flag is cleared. Artist is notified.

Reject logic:
  * `rejection_reason` stored on the request. Artist is notified.
  * No changes to categories_master.

Idempotency: Once approved/rejected, further approve/reject calls 400 out.
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


class SubmitCategoryRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=1000)
    example_artists: Optional[str] = None       # free text
    portfolio_link: Optional[str] = None


class ApproveBody(BaseModel):
    # If set, we assign that existing master row to the artist instead of
    # creating a new one (dupe-avoidance). If empty, we create a new row.
    existing_slug: Optional[str] = None
    # Optional override for the display name we create in the master list.
    new_name: Optional[str] = None
    icon: Optional[str] = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=400)


def make_category_requests_router(*, db, get_current_user, admin_only, new_id):
    r = APIRouter()

    # ── Artist side ──────────────────────────────────────────────────
    @r.post("/artist/category-requests")
    async def submit_request(body: SubmitCategoryRequest, user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        # Prevent multiple simultaneous pending requests per artist so the
        # admin queue doesn't get spammed.
        pending = await db.category_requests.find_one({
            "artist_id": user["id"], "status": "pending",
        })
        if pending:
            raise HTTPException(400, "You already have a pending category request. Wait for admin review.")
        prof = await db.artist_profiles.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
        doc = {
            "id": new_id(),
            "artist_id": user["id"],
            "artist_name": f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user.get("email"),
            "artist_email": user.get("email"),
            "stage_name": prof.get("stage_name"),
            "city": prof.get("city"),
            "requested_name": body.name.strip(),
            "requested_slug": _slugify(body.name),
            "description": body.description.strip(),
            "example_artists": (body.example_artists or "").strip(),
            "portfolio_link": (body.portfolio_link or "").strip(),
            "status": "pending",
            "created_at": _now(),
        }
        await db.category_requests.insert_one(doc)

        # Flag the artist profile so downstream UI can show
        # "Pending category approval" pill and skip the listing.
        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$set": {
                "category_pending": True,
                "pending_category_id": doc["id"],
                "pending_category_name": body.name.strip(),
            }},
        )
        # Notify admins.
        try:
            async for adm in db.users.find({"role": "admin"}, {"_id": 0, "id": 1}):
                await db.notifications.insert_one({
                    "id": new_id(), "user_id": adm["id"],
                    "type": "category.request",
                    "title": "New Artist Category request",
                    "body": f"{doc['artist_name']} requested '{doc['requested_name']}'.",
                    "link": f"/admin?tab=category-requests&highlight={doc['id']}",
                    "read": False, "created_at": _now(),
                })
        except Exception:
            pass
        doc.pop("_id", None)
        return doc

    @r.get("/artist/category-requests/mine")
    async def my_requests(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artist only")
        docs = await db.category_requests.find(
            {"artist_id": user["id"]}, {"_id": 0},
        ).sort("created_at", -1).to_list(50)
        return docs

    # ── Admin side ───────────────────────────────────────────────────
    @r.get("/admin/category-requests")
    async def admin_list(status: Optional[str] = None, _: dict = Depends(admin_only)):
        q = {}
        if status:
            q["status"] = status
        docs = await db.category_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
        return docs

    @r.get("/admin/category-requests/similar")
    async def admin_similar(name: str, _: dict = Depends(admin_only)):
        """Dupe-avoidance helper. Returns categories_master rows whose name
        or slug loosely match the request text so admin can quickly assign
        an existing category instead of creating a new one."""
        if not name:
            return []
        tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name.lower()) if len(t) >= 3]
        if not tokens:
            tokens = [name.lower()]
        rxs = [{"$regex": re.escape(t), "$options": "i"} for t in tokens]
        # Match if ANY token appears in name OR slug.
        or_filters = []
        for rx in rxs:
            or_filters.append({"name": rx})
            or_filters.append({"slug": rx})
        rows = await db.categories_master.find({"$or": or_filters}, {"_id": 0}).limit(15).to_list(15)
        return rows

    async def _finalise_artist(req: dict, canonical_name: str, canonical_slug: str, new_id_fn):
        # Update artist profile: replace category, clear pending flag.
        await db.artist_profiles.update_one(
            {"user_id": req["artist_id"]},
            {"$set": {
                "category": canonical_name,
                "category_pending": False,
            }, "$unset": {"pending_category_id": "", "pending_category_name": ""}},
        )
        await db.notifications.insert_one({
            "id": new_id_fn(), "user_id": req["artist_id"],
            "type": "category.approved",
            "title": "Your category request was approved 🎉",
            "body": f"'{canonical_name}' is now live. You can finish listing your artist profile.",
            "link": "/artist?tab=profile",
            "read": False, "created_at": _now(),
        })

    @r.post("/admin/category-requests/{req_id}/approve")
    async def admin_approve(req_id: str, body: ApproveBody, admin: dict = Depends(admin_only)):
        req = await db.category_requests.find_one({"id": req_id})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] != "pending":
            raise HTTPException(400, f"Request is already {req['status']}")

        # Route 1 — reuse an existing category (dupe avoidance).
        if body.existing_slug:
            existing = await db.categories_master.find_one({"slug": body.existing_slug})
            if not existing:
                raise HTTPException(404, "existing_slug not found in master list")
            canonical_name = existing["name"]
            canonical_slug = existing["slug"]
            await db.category_requests.update_one({"id": req_id}, {"$set": {
                "status": "approved",
                "decision": "reused_existing",
                "assigned_slug": canonical_slug,
                "assigned_name": canonical_name,
                "decided_at": _now(),
                "decided_by": admin["id"],
            }})
        else:
            # Route 2 — create new master row. Slug conflict → 400.
            new_name = (body.new_name or req["requested_name"]).strip()
            new_slug = _slugify(new_name)
            if await db.categories_master.find_one({"slug": new_slug}):
                raise HTTPException(
                    400,
                    f"Category slug '{new_slug}' already exists. Pass existing_slug='{new_slug}' to reuse it.",
                )
            # Sort order = end of list.
            existing_ct = await db.categories_master.count_documents({})
            master_doc = {
                "id": new_id(),
                "slug": new_slug,
                "name": new_name,
                "icon": body.icon or "🎼",
                "sort_order": existing_ct + 1,
                "active": True,
                "created_at": _now(),
                "created_from_request": req_id,
            }
            await db.categories_master.insert_one(master_doc)
            canonical_name = new_name
            canonical_slug = new_slug
            await db.category_requests.update_one({"id": req_id}, {"$set": {
                "status": "approved",
                "decision": "created_new",
                "assigned_slug": new_slug,
                "assigned_name": new_name,
                "decided_at": _now(),
                "decided_by": admin["id"],
            }})

        await _finalise_artist(req, canonical_name, canonical_slug, new_id)
        return {"ok": True, "assigned_name": canonical_name, "assigned_slug": canonical_slug}

    @r.post("/admin/category-requests/{req_id}/reject")
    async def admin_reject(req_id: str, body: RejectBody, admin: dict = Depends(admin_only)):
        req = await db.category_requests.find_one({"id": req_id})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] != "pending":
            raise HTTPException(400, f"Request is already {req['status']}")
        await db.category_requests.update_one({"id": req_id}, {"$set": {
            "status": "rejected",
            "rejection_reason": body.reason.strip(),
            "decided_at": _now(),
            "decided_by": admin["id"],
        }})
        # Clear the pending flag on the artist profile so their existing
        # placeholder category (from signup) remains active. The rejection
        # reason is shown in the artist dashboard so they can try again.
        await db.artist_profiles.update_one(
            {"user_id": req["artist_id"]},
            {"$set": {"category_pending": False},
             "$unset": {"pending_category_id": "", "pending_category_name": ""}},
        )
        await db.notifications.insert_one({
            "id": new_id(), "user_id": req["artist_id"],
            "type": "category.rejected",
            "title": "Category request not approved",
            "body": f"Reason: {body.reason.strip()[:200]}",
            "link": "/artist?tab=profile",
            "read": False, "created_at": _now(),
        })
        return {"ok": True}

    return r
