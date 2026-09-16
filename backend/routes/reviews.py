"""Reviews — create, moderate, list, reply, report."""
from __future__ import annotations
from typing import Callable, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


class ReviewBody(BaseModel):
    booking_id: str
    rating: int = Field(ge=1, le=5)
    text: str
    photos: List[str] = []   # data urls — images
    videos: List[str] = []   # data urls — short clips (≤ 30 MB)


class ReviewReplyBody(BaseModel):
    reply: str


class ReviewModerateBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason: Optional[str] = None


def make_router(
    *,
    db,
    get_current_user: Callable,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
    notify_dispatch: Callable,
) -> APIRouter:
    r = APIRouter()

    @r.post("/reviews")
    async def create_review(body: ReviewBody, user: dict = Depends(get_current_user)):
        booking = await db.bookings.find_one({"id": body.booking_id})
        if not booking or booking["customer_id"] != user["id"]:
            raise HTTPException(404, "Booking not found")
        if booking["status"] not in ("completed", "confirmed"):
            raise HTTPException(400, "Can only review completed/confirmed bookings")
        if await db.reviews.find_one({"booking_id": body.booking_id}):
            raise HTTPException(400, "Already reviewed")

        rid = new_id()
        photo_ids, video_ids = [], []

        # photos (≤ 5 MB each, ≤ 5 photos)
        for du in body.photos[:5]:
            try:
                header, b64 = du.split(",", 1)
                mime = header.split(";")[0].replace("data:", "")
                if not mime.startswith("image/"):
                    continue
                if (len(b64) * 3) // 4 > 5 * 1024 * 1024:
                    continue
                mid = new_id()
                await db.media.insert_one({
                    "id": mid, "user_id": user["id"], "type": "review",
                    "mime": mime, "data": b64, "created_at": utcnow(),
                })
                photo_ids.append(mid)
            except Exception:
                continue

        # videos (≤ 30 MB each, ≤ 2 videos)
        for du in body.videos[:2]:
            try:
                header, b64 = du.split(",", 1)
                mime = header.split(";")[0].replace("data:", "")
                if not mime.startswith("video/"):
                    continue
                if (len(b64) * 3) // 4 > 30 * 1024 * 1024:
                    continue
                mid = new_id()
                await db.media.insert_one({
                    "id": mid, "user_id": user["id"], "type": "review",
                    "mime": mime, "data": b64, "created_at": utcnow(),
                })
                video_ids.append(mid)
            except Exception:
                continue

        # Smart moderation: reviews with media go to admin queue;
        # text-only reviews are auto-approved.
        auto_approve = not (photo_ids or video_ids)
        initial_status = "approved" if auto_approve else "pending"

        await db.reviews.insert_one({
            "id": rid, "booking_id": body.booking_id, "customer_id": user["id"],
            "customer_name": booking.get("customer_name"),
            "artist_id": booking["artist_id"], "rating": body.rating, "text": body.text,
            "photos": photo_ids, "videos": video_ids,
            "event_type": booking.get("event_type"),
            "moderated": initial_status, "reply": None, "created_at": utcnow(),
        })

        # Rebuild aggregate against approved reviews only
        all_reviews = await db.reviews.find({"artist_id": booking["artist_id"], "moderated": "approved"}).to_list(10000)
        avg = sum(r["rating"] for r in all_reviews) / len(all_reviews) if all_reviews else 0
        await db.artist_profiles.update_one(
            {"user_id": booking["artist_id"]},
            {"$set": {"rating_avg": round(avg, 2), "review_count": len(all_reviews)}},
        )
        await db.bookings.update_one({"id": body.booking_id}, {"$set": {"status": "reviewed"}})

        # Notify admins on pending-moderation reviews
        if not auto_approve:
            async for adm in db.users.find({"role": "admin"}, {"id": 1}):
                await notify_dispatch(
                    db, user_id=adm["id"], event="review.pending_moderation",
                    channels=["in_app"],
                    ctx={"title": "Review awaiting moderation",
                         "body": f"{booking.get('customer_name', 'A customer')} attached media to a {body.rating}★ review."},
                )

        return {"ok": True, "review_id": rid, "status": initial_status}

    @r.get("/admin/reviews")
    async def admin_reviews(status: str = "pending", _: dict = Depends(admin_only)):
        q = {} if status == "all" else {"moderated": status}
        docs = await db.reviews.find(q).sort("created_at", -1).to_list(500)
        out = []
        for d in docs:
            d = clean(d)
            a = await db.artist_profiles.find_one({"user_id": d["artist_id"]}, {"stage_name": 1, "_id": 0})
            d["artist_stage_name"] = a.get("stage_name") if a else None
            out.append(d)
        return out

    @r.post("/admin/reviews/{rid}/moderate")
    async def admin_moderate_review(rid: str, body: ReviewModerateBody, admin: dict = Depends(admin_only)):
        rev = await db.reviews.find_one({"id": rid})
        if not rev:
            raise HTTPException(404, "Review not found")
        new_status = "approved" if body.decision == "approve" else "rejected"
        await db.reviews.update_one(
            {"id": rid},
            {"$set": {
                "moderated": new_status,
                "moderation_reason": body.reason,
                "moderated_by": admin["id"],
                "moderated_at": utcnow(),
            }},
        )
        # Recompute aggregate
        all_reviews = await db.reviews.find({"artist_id": rev["artist_id"], "moderated": "approved"}).to_list(10000)
        avg = sum(x["rating"] for x in all_reviews) / len(all_reviews) if all_reviews else 0
        await db.artist_profiles.update_one(
            {"user_id": rev["artist_id"]},
            {"$set": {"rating_avg": round(avg, 2), "review_count": len(all_reviews)}},
        )
        # Audit + notify customer
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "actor_id": admin["id"], "actor_email": admin.get("email"),
                "actor_role": "admin", "action": f"review.{body.decision}",
                "target_type": "review", "target_id": rid,
                "payload": {"reason": body.reason}, "created_at": utcnow(),
            })
        except Exception:
            pass
        await notify_dispatch(
            db, user_id=rev["customer_id"], event=f"review.{new_status}",
            channels=["in_app"],
            ctx={
                "title": "Review approved" if new_status == "approved" else "Review removed",
                "body": body.reason or ("Your review is now live." if new_status == "approved" else "Your review violated our guidelines."),
            },
        )
        return {"ok": True, "status": new_status}

    @r.get("/reviews/artist/{user_id}")
    async def reviews_for_artist(user_id: str):
        docs = await db.reviews.find({"artist_id": user_id, "moderated": "approved"}).sort("created_at", -1).to_list(200)
        return [clean(d) for d in docs]

    @r.post("/reviews/{rid}/reply")
    async def reply_review(rid: str, body: ReviewReplyBody, user: dict = Depends(get_current_user)):
        rev = await db.reviews.find_one({"id": rid})
        if not rev or rev["artist_id"] != user["id"]:
            raise HTTPException(404, "Not found")
        await db.reviews.update_one({"id": rid}, {"$set": {"reply": body.reply, "replied_at": utcnow()}})
        return {"ok": True}

    @r.post("/reviews/{rid}/report")
    async def report_review(rid: str, user: dict = Depends(get_current_user)):
        await db.review_reports.insert_one({
            "id": new_id(), "review_id": rid, "reporter_id": user["id"], "created_at": utcnow(),
        })
        return {"ok": True}

    return r
