"""Dispute creation & admin resolution.

BookTalent is a lead-generation marketplace — there are no internal wallets.
Refunds are actioned by the admin via /payments/{id}/refund (Razorpay). This
router only records the dispute + the admin's decision so a paper trail
survives; any money movement is handled elsewhere.
"""
from __future__ import annotations
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class DisputeBody(BaseModel):
    booking_id: str
    reason: str
    description: str = ""


class DisputeResolveBody(BaseModel):
    decision: Literal["refund", "release", "partial"]
    amount: Optional[float] = None
    note: Optional[str] = None


def make_router(
    *,
    db,
    get_current_user: Callable,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
) -> APIRouter:
    r = APIRouter()

    @r.post("/disputes")
    async def create_dispute(body: DisputeBody, user: dict = Depends(get_current_user)):
        b = await db.bookings.find_one({"id": body.booking_id})
        if not b or user["id"] not in (b["customer_id"], b["artist_id"]):
            raise HTTPException(403, "Not allowed")
        did = new_id()
        await db.disputes.insert_one({
            "id": did, "booking_id": body.booking_id, "raised_by": user["id"],
            "reason": body.reason, "description": body.description,
            "status": "open", "created_at": utcnow(),
        })
        return {"id": did}

    @r.get("/admin/disputes")
    async def admin_disputes(_: dict = Depends(admin_only)):
        docs = await db.disputes.find().sort("created_at", -1).to_list(500)
        return [clean(d) for d in docs]

    @r.post("/admin/disputes/{did}/resolve")
    async def resolve_dispute(did: str, body: DisputeResolveBody, _: dict = Depends(admin_only)):
        d = await db.disputes.find_one({"id": did})
        if not d:
            raise HTTPException(404, "Not found")
        booking = await db.bookings.find_one({"id": d["booking_id"]})
        # Flag related payment for refund when admin decides in customer favour.
        # Actual money-back is processed through /payments/{id}/refund.
        if body.decision in ("refund", "partial") and booking:
            note = (
                f"Dispute {body.decision} for booking {booking.get('ref', '')}"
                + (f" — amount ₹{body.amount}" if body.amount else "")
            )
            await db.payments.update_many(
                {"booking_id": booking["id"], "status": "completed"},
                {"$set": {"refund_pending": True, "refund_note": note, "refund_flagged_at": utcnow()}},
            )
        await db.disputes.update_one(
            {"id": did},
            {"$set": {
                "status": "resolved", "decision": body.decision,
                "amount": body.amount, "note": body.note, "resolved_at": utcnow(),
            }},
        )
        return {"ok": True}

    return r
