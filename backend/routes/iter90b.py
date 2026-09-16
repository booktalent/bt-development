"""
Iter 90b — Endpoints for the 3 outstanding UI features:

  1. Artist KYC pipeline status (already exposed via /kyc/me → this file
     just enriches it with a canonical `stages[]` payload so the wizard
     UI doesn't have to duplicate the state list).

  2. Admin Agreement Viewer — download / list / re-issue.

  3. Manager Chat threads — list all booking chats a manager should
     moderate (bookings assigned to them, or all bookings for admins),
     with last-message preview + unread count.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger("iter90b")


# Canonical KYC stage list — matches routes/v2_flow.py state machine.
# Split into (a) the linear "happy path" shown as a progress bar, and
# (b) terminal error states shown as alerts. Order is significant.
KYC_STAGES = [
    {"id": "kyc_pending",         "label": "Upload KYC",              "action": "Fill your KYC form and upload the required documents."},
    {"id": "kyc_under_review",    "label": "Under Review",            "action": "Our team is reviewing your documents (usually 24-48 hrs)."},
    {"id": "kyc_approved",        "label": "KYC Approved",            "action": "Your identity is verified. Next: accept the Terms & Conditions."},
    {"id": "tnc_pending",         "label": "Accept T&C",              "action": "Read and accept the BookTalent Terms & Conditions to go live."},
    {"id": "agreement_generated", "label": "Agreement Signed",        "action": "Your artist agreement is generated. Listing goes live in seconds."},
    {"id": "live",                "label": "Live on BookTalent",      "action": "You're live! Keep your calendar and packages up to date."},
]
KYC_ERROR_STATES = {"kyc_changes_required", "kyc_rejected", "suspended"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_iter90b_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ═══════════════════════════════════════════════════════════════
    # 1. Artist KYC pipeline snapshot (for the progress-bar UI)
    # ═══════════════════════════════════════════════════════════════
    @r.get("/kyc/pipeline")
    async def kyc_pipeline(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        prof = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
        current = prof.get("kyc_status") or "kyc_pending"

        # Compute step index. Error states pin to the step just before
        # them so the UI can render "you're stuck here" indicator.
        step_index = 0
        for i, s in enumerate(KYC_STAGES):
            if s["id"] == current:
                step_index = i
                break
        else:
            # Handle error states — pin to the review stage for stuck flows
            if current == "kyc_changes_required":
                step_index = 1  # under review row
            elif current == "kyc_rejected":
                step_index = 1
            elif current == "suspended":
                step_index = 5  # live row (was live, now suspended)

        stages_out = []
        for i, s in enumerate(KYC_STAGES):
            status = ("done" if i < step_index
                       else "current" if i == step_index
                       else "pending")
            stages_out.append({**s, "status": status})

        is_error = current in KYC_ERROR_STATES
        error_reason = None
        if current == "kyc_changes_required":
            error_reason = prof.get("kyc_review_reason") or "Reviewer asked for updated documents."
        elif current == "kyc_rejected":
            error_reason = prof.get("kyc_review_reason") or "Contact support to re-apply."
        elif current == "suspended":
            error_reason = prof.get("suspend_reason") or "Contact support for reinstatement."

        return {
            "current_status": current,
            "step_index": step_index,
            "stages": stages_out,
            "is_error": is_error,
            "error_reason": error_reason,
            "verified_badge": prof.get("verified_badge", False),
            "agreement_id": prof.get("agreement_id"),
            "agreement_url": f"/api/agreements/mine" if prof.get("agreement_id") else None,
            "kyc_submitted_at": prof.get("kyc_submitted_at"),
            "kyc_updated_at": prof.get("kyc_updated_at"),
        }

    # ═══════════════════════════════════════════════════════════════
    # 2. Admin Agreement Viewer
    # ═══════════════════════════════════════════════════════════════
    @r.get("/admin/agreements/{artist_id}")
    async def admin_get_agreement_meta(artist_id: str, _: dict = Depends(require_admin)):
        prof = await db.artist_profiles.find_one({"user_id": artist_id}, {"agreement_id": 1, "kyc_status": 1, "_id": 0})
        if not prof:
            raise HTTPException(404, "Artist not found")
        if not prof.get("agreement_id"):
            raise HTTPException(404, "No agreement generated yet — artist hasn't accepted T&C")
        agr = await db.agreements.find_one({"id": prof["agreement_id"]}, {"pdf_hex": 0, "_id": 0})
        if not agr:
            raise HTTPException(410, "Agreement metadata missing")
        return {
            "agreement": agr,
            "kyc_status": prof.get("kyc_status"),
            "download_url": f"/api/admin/agreements/{artist_id}/download",
        }

    @r.get("/admin/agreements/{artist_id}/download")
    async def admin_download_agreement(artist_id: str, _: dict = Depends(require_admin)):
        prof = await db.artist_profiles.find_one({"user_id": artist_id}, {"agreement_id": 1, "_id": 0})
        if not prof or not prof.get("agreement_id"):
            raise HTTPException(404, "No agreement for this artist")
        rec = await db.agreements.find_one({"id": prof["agreement_id"]})
        if not rec:
            raise HTTPException(410, "Agreement file missing")
        return StreamingResponse(
            io.BytesIO(bytes.fromhex(rec["pdf_hex"])),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="agreement-{rec["ref"]}.pdf"'},
        )

    @r.post("/admin/agreements/{artist_id}/reissue")
    async def admin_reissue_agreement(artist_id: str, admin: dict = Depends(require_admin)):
        """Regenerate the agreement PDF (e.g. after commission % change).
        Keeps the old agreement archived in agreements collection with
        `superseded_by` back-pointer for audit trail.
        """
        user = await db.users.find_one({"id": artist_id})
        if not user:
            raise HTTPException(404, "Artist not found")
        prof = await db.artist_profiles.find_one({"user_id": artist_id}) or {}
        if prof.get("kyc_status") not in ("agreement_generated", "live"):
            raise HTTPException(409, f"Cannot re-issue — artist is in state '{prof.get('kyc_status')}'. Only artists past T&C acceptance can have their agreement re-issued.")

        # Import the same generator used at T&C acceptance so both paths
        # produce identical PDFs.
        from routes.v2_flow import _generate_agreement
        old_id = prof.get("agreement_id")

        new_agr = await _generate_agreement(db, user, prof)

        # Archive old agreement with pointer to new one for audit trail
        if old_id and old_id != new_agr["id"]:
            await db.agreements.update_one(
                {"id": old_id},
                {"$set": {"superseded_by": new_agr["id"],
                           "superseded_at": utcnow(),
                           "superseded_by_admin": admin.get("email")}},
            )
            await db.artist_profiles.update_one(
                {"user_id": artist_id},
                {"$set": {"agreement_id": new_agr["id"],
                           "agreement_reissued_at": utcnow(),
                           "agreement_reissued_by": admin.get("email")}},
            )
        return {"ok": True, "new_agreement": new_agr, "previous_id": old_id}

    # ═══════════════════════════════════════════════════════════════
    # 3. Manager Chat Threads
    # ═══════════════════════════════════════════════════════════════
    @r.get("/manager/chats/threads")
    async def manager_chat_threads(user: dict = Depends(get_current_user)):
        """List all booking chat threads relevant to the caller.

        * Manager  → threads where the booking is assigned to them.
        * Admin    → all threads (moderation view).
        * Others   → 403.
        """
        role = user.get("role")
        if role not in ("manager", "admin"):
            raise HTTPException(403, "Manager or admin only")

        q: Dict[str, Any] = {}
        if role == "manager":
            q["assigned_manager_id"] = user["id"]

        # Get bookings assigned to this manager (or all for admin)
        threads: List[Dict[str, Any]] = []
        async for b in db.bookings.find(q, {
            "_id": 0, "id": 1, "ref": 1, "status": 1, "customer_id": 1,
            "customer_name": 1, "customer_email": 1, "artist_id": 1,
            "event_date": 1, "pricing": 1,
        }).sort("event_date", -1).limit(200):
            # Skip bookings without chat activity to keep the list snappy
            last = await db.chat_messages.find_one(
                {"booking_id": b["id"]},
                sort=[("created_at", -1)],
            )
            unread = 0
            if last:
                unread = await db.chat_messages.count_documents({
                    "booking_id": b["id"],
                    "read_by": {"$ne": user["id"]},
                })
            # Only include if there's any activity OR unread notifications
            if not last and role == "manager":
                continue
            # Fetch artist stage_name for display
            artist_prof = await db.artist_profiles.find_one(
                {"user_id": b.get("artist_id")},
                {"stage_name": 1, "_id": 0},
            ) or {}
            threads.append({
                "booking_id": b["id"],
                "ref": b.get("ref"),
                "status": b.get("status"),
                "event_date": b.get("event_date"),
                "customer_name": b.get("customer_name"),
                "artist_name": artist_prof.get("stage_name") or "Unknown",
                "last_message": {
                    "content": last.get("content") if last else None,
                    "sender_role": last.get("sender_role") if last else None,
                    "sender_name": last.get("sender_name") if last else None,
                    "created_at": last.get("created_at") if last else None,
                } if last else None,
                "unread_count": unread,
            })
        # Order by last-message-desc (unread first)
        threads.sort(
            key=lambda t: (
                -t["unread_count"],
                t["last_message"]["created_at"] if t.get("last_message") else "",
            ),
            reverse=False,
        )
        return {"items": threads, "count": len(threads)}

    return r
