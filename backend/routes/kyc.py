"""KYC — artist identity verification (submit + admin decide)."""
from __future__ import annotations
import re
from typing import Callable, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


# Validation
KYC_ALLOWED_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"}
KYC_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per doc

_AADHAAR_RX = re.compile(r"^\d{12}$")
_PAN_RX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _validate_data_url(label: str, dataurl: str) -> tuple[str, str]:
    """Returns (mime, base64) or raises 400."""
    if not dataurl.startswith("data:"):
        raise HTTPException(400, f"{label}: not a data url")
    try:
        header, b64 = dataurl.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").lower()
    except Exception:
        raise HTTPException(400, f"{label}: malformed data url")
    if mime not in KYC_ALLOWED_MIMES:
        raise HTTPException(400, f"{label}: only JPG / PNG / WEBP / PDF allowed (got {mime})")
    approx = (len(b64) * 3) // 4
    if approx > KYC_MAX_BYTES:
        raise HTTPException(400, f"{label}: file too large ({approx // 1024} KB > 5120 KB limit)")
    return mime, b64


class KYCSubmitBody(BaseModel):
    aadhaar_number: Optional[str] = None       # raw 12-digit Aadhaar number
    pan_number: Optional[str] = None           # raw PAN like ABCDE1234F
    full_name: Optional[str] = None
    dob: Optional[str] = None                  # YYYY-MM-DD
    aadhaar: Optional[str] = None              # data url — Aadhaar doc image/pdf
    pan: Optional[str] = None                  # data url — PAN doc image/pdf
    bank_proof: Optional[str] = None           # data url — cancelled cheque / passbook
    selfie: Optional[str] = None               # data url — live selfie for face-match


class KYCDecideBody(BaseModel):
    artist_id: str
    decision: Literal["approve", "reject", "request_resubmission"]
    reason: Optional[str] = None
    # Iter 98 — Admin can set the commercial deal at approval time so
    # a new artist is either "Normal" (5% platform fee applied to customer)
    # or "BookTalent Service" (fee waived, artist owes a % commission).
    artist_type: Optional[Literal["normal", "service"]] = None
    percentage_deal: Optional[float] = Field(None, ge=0, le=50)


def make_router(
    *,
    db,
    get_current_user: Callable,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
    notify_dispatch: Callable,
    log,
) -> APIRouter:
    r = APIRouter()

    @r.post("/kyc/submit")
    async def kyc_submit(body: KYCSubmitBody, user: dict = Depends(get_current_user)):
        payload = body.model_dump(exclude_unset=True)

        # Iter 90 — Guard against regressive transitions. Only for artists.
        # A `live` / `tnc_pending` / `agreement_generated` / `kyc_approved`
        # artist cannot re-submit — admin must first request changes.
        if user.get("role") == "artist":
            prof = await db.artist_profiles.find_one(
                {"user_id": user["id"]}, {"kyc_status": 1, "_id": 0},
            ) or {}
            current = prof.get("kyc_status")
            BLOCKED = {"kyc_approved", "tnc_pending", "agreement_generated", "live"}
            if current in BLOCKED:
                raise HTTPException(
                    409,
                    f"Cannot re-submit KYC — current state '{current}' is post-approval. "
                    "Ask an admin to request changes first."
                )

        aadhaar_no = (payload.get("aadhaar_number") or "").strip().replace(" ", "")
        pan_no = (payload.get("pan_number") or "").strip().upper()
        if aadhaar_no and not _AADHAAR_RX.match(aadhaar_no):
            raise HTTPException(400, "Aadhaar number must be exactly 12 digits")
        if pan_no and not _PAN_RX.match(pan_no):
            raise HTTPException(400, "PAN must follow the format ABCDE1234F")

        if not (payload.get("aadhaar") or payload.get("pan")):
            raise HTTPException(400, "Upload at least one identity document (Aadhaar or PAN)")
        if payload.get("aadhaar") and not aadhaar_no:
            raise HTTPException(400, "Aadhaar number is required when uploading the Aadhaar document")
        if payload.get("pan") and not pan_no:
            raise HTTPException(400, "PAN number is required when uploading the PAN document")

        docs: Dict[str, str] = {}
        for key in ("aadhaar", "pan", "bank_proof", "selfie"):
            v = payload.get(key)
            if not v:
                continue
            mime, b64 = _validate_data_url(key, v)
            mid = new_id()
            await db.media.insert_one({
                "id": mid, "user_id": user["id"], "type": "kyc",
                "mime": mime, "data": b64, "created_at": utcnow(), "kyc_field": key,
            })
            docs[key] = mid

        sub_doc = {
            "user_id": user["id"],
            "documents": docs,
            "aadhaar_number_masked": ("XXXX-XXXX-" + aadhaar_no[-4:]) if aadhaar_no else None,
            "pan_number": pan_no or None,
            "full_name": payload.get("full_name"),
            "dob": payload.get("dob"),
            "status": "pending",
            "submitted_at": utcnow(),
            "decided_at": None,
            "reason": None,
        }
        await db.kyc_submissions.update_one(
            {"user_id": user["id"]},
            {"$set": sub_doc},
            upsert=True,
        )
        # Iter 90 — Use sync helper so all 3 collections stay aligned.
        if user["role"] == "artist":
            from kyc_sync import sync_kyc_status
            await sync_kyc_status(db, user_id=user["id"], legacy_status="pending")
        else:
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {"kyc_status": "kyc_under_review", "kyc_legacy_status": "pending"}},
            )

        # Notify admins so they can act fast
        try:
            u_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("email", "")
            async for adm in db.users.find({"role": "admin"}, {"id": 1, "email": 1}):
                await notify_dispatch(
                    db, user_id=adm["id"], event="kyc.submitted",
                    channels=["in_app"],
                    ctx={"title": "New KYC submission",
                         "body": f"{u_name} submitted KYC documents — review pending."},
                )
        except Exception:
            pass

        return {"ok": True}

    @r.get("/kyc/mine")
    async def kyc_mine(user: dict = Depends(get_current_user)):
        doc = await db.kyc_submissions.find_one({"user_id": user["id"]})
        return clean(doc) if doc else None

    @r.get("/admin/kyc")
    async def admin_kyc(status: Optional[str] = None, _: dict = Depends(admin_only)):
        q: dict = {}
        if status in ("pending", "approved", "rejected", "needs_resubmission"):
            q["status"] = status
        docs = await db.kyc_submissions.find(q).sort("submitted_at", -1).to_list(500)
        out = []
        for d in docs:
            d = clean(d)
            u = await db.users.find_one({"id": d["user_id"]}, {"password_hash": 0})
            d["user"] = clean(u) if u else None
            if u and u.get("role") == "artist":
                ap = await db.artist_profiles.find_one(
                    {"user_id": u["id"]},
                    {"stage_name": 1, "category": 1, "city": 1, "kyc_status": 1, "_id": 0},
                )
                d["artist_profile"] = ap
                # Iter 90 — expose the v2 pipeline state so the admin UI
                # can show post-approval progress (tnc_pending →
                # agreement_generated → live).
                d["v2_status"] = (ap or {}).get("kyc_status")
            out.append(d)
        return out

    @r.post("/admin/kyc/decide")
    async def admin_kyc_decide(body: KYCDecideBody, admin: dict = Depends(admin_only)):
        sub = await db.kyc_submissions.find_one({"user_id": body.artist_id})
        if not sub:
            # Iter 90 — Backfill a submission row for artists whose docs
            # were captured via the old v2_flow /kyc/submit path (before
            # the duplicate-route fix). This lets admin decide from the
            # legacy admin queue even for pre-fix submissions.
            prof = await db.artist_profiles.find_one(
                {"user_id": body.artist_id},
                {"kyc_documents": 1, "kyc_submitted_at": 1, "kyc_status": 1, "_id": 0},
            ) or {}
            if not prof or not prof.get("kyc_documents"):
                raise HTTPException(404, "No KYC submission found for this user")
            sub = {
                "user_id": body.artist_id,
                "documents": prof.get("kyc_documents") or {},
                "status": "pending",
                "v2_status": prof.get("kyc_status", "kyc_under_review"),
                "submitted_at": prof.get("kyc_submitted_at") or utcnow(),
            }
            await db.kyc_submissions.insert_one({**sub, "id": new_id()})

        decision_to_status = {
            "approve": "approved",
            "reject": "rejected",
            "request_resubmission": "needs_resubmission",
        }
        new_status = decision_to_status[body.decision]

        await db.kyc_submissions.update_one(
            {"user_id": body.artist_id},
            {"$set": {
                "status": new_status,
                "decided_at": utcnow(),
                "decided_by": admin["id"],
                "reason": body.reason,
            }},
        )
        # Iter 90 — Single source of truth via kyc_sync helper.
        # This atomically updates artist_profiles (canonical) + users
        # (cache) + kyc_submissions (audit) with matching v2 status.
        from kyc_sync import sync_kyc_status
        synced = await sync_kyc_status(
            db, user_id=body.artist_id,
            legacy_status=new_status,
            reason=body.reason,
            decided_by=admin.get("email"),
        )
        # For downstream notification templates
        v2_status = synced["v2"]

        # Iter 98 — Commercial deal is set at approval time. Admin picks
        # "normal" (default, 5% platform fee applied to customer) or
        # "service" (BookTalent Service Artist, fee waived, artist pays
        # a % commission). These flags feed `financial_engine._artist_commercial`
        # so the waiver shows up on every subsequent /finance/quote.
        if body.decision == "approve":
            is_service = (body.artist_type == "service")
            pct = float(body.percentage_deal or 0)
            await db.artist_profiles.update_one(
                {"user_id": body.artist_id},
                {"$set": {
                    "artist_type": body.artist_type or "normal",
                    "is_service_artist": bool(is_service and pct > 0),
                    "percentage_deal": pct if is_service else 0.0,
                    "commercial_deal_set_at": utcnow(),
                    "commercial_deal_set_by": admin.get("email"),
                }},
                upsert=False,
            )

        target_user = await db.users.find_one({"id": body.artist_id})
        # Iter 99 — R3 fix: KYC approval message MUST explicitly prompt the
        # artist to complete Terms & Conditions on their dashboard so they can
        # progress to the "live" state (agreement generation + go-live).
        # Both email and WhatsApp use the same T&C prompt copy.
        _tnc_prompt = (
            "Congratulations! Your KYC has been approved and your Verified "
            "Badge is now active. Please log in to your Artist Dashboard and "
            "accept the Terms & Conditions to receive your Agreement and go "
            "LIVE on BookTalent."
        )
        titles = {
            "approved": "✓ KYC Approved — Accept T&C to Go LIVE",
            "rejected": "✗ KYC Rejected",
            "needs_resubmission": "↻ KYC — Resubmission Requested",
        }
        bodies = {
            "approved": _tnc_prompt,
            "rejected": f"Your KYC was rejected. Reason: {body.reason or 'documents did not meet our standards'}.",
            "needs_resubmission": f"Please resubmit your KYC. Reason: {body.reason or 'we need a clearer copy of your documents'}.",
        }
        try:
            await notify_dispatch(
                db, user_id=body.artist_id, event=f"kyc.{new_status}",
                channels=["in_app", "email", "whatsapp"],
                ctx={"title": titles[new_status], "body": bodies[new_status], "reason": body.reason or ""},
                email=target_user.get("email") if target_user else None,
                phone=target_user.get("phone") if target_user else None,
            )
        except Exception as _e:
            log.warning("KYC notification failed: %s", _e)

        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "actor_id": admin.get("id"),
                "actor_email": admin.get("email"),
                "actor_role": "admin",
                "action": f"kyc.{body.decision}",
                "target_type": "kyc_submission",
                "target_id": body.artist_id,
                "payload": {"reason": body.reason, "new_status": new_status},
                "created_at": utcnow(),
            })
        except Exception:
            pass

        return {"ok": True, "status": new_status}

    return r
