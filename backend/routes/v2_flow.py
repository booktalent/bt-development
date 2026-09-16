"""
Iter 83 — Public Quote endpoint + KYC v2 state machine + T&C + Agreement.

Bundle: keeps the v2 vertical slice in one small router so we don't
scatter Phase-2/3 code across server.py. Server.py mounts this router.

Endpoints (all under /api):

Financial
    GET  /finance/quote                        — canonical price breakdown

KYC v2 (Sec 7-14)
    GET  /kyc/me                               — artist reads own KYC state
    POST /kyc/submit                           — artist submits KYC docs
    GET  /admin/kyc/queue                      — admin queue (newest first)
    POST /admin/kyc/{artist_id}/review         — admin approves/rejects/requests changes,
                                                 and sets artist commercial deal.

T&C + Agreement (Sec 12-14)
    POST /kyc/accept-terms                     — artist checks the T&C tick
    GET  /agreements/mine                      — artist downloads latest agreement PDF
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from financial_engine import compute_price
from routes.settings import get_settings, record_audit


# ─── KYC state machine ─────────────────────────────────────────────────
# 9 states per Sec 7. Transitions are explicit — any illegal move rejected.
KYC_STATUSES = [
    "registration_pending",   # user registered but hasn't opened KYC yet
    "kyc_pending",            # artist has profile but hasn't submitted docs
    "kyc_under_review",       # docs submitted, awaiting admin
    "kyc_changes_required",   # admin sent it back
    "kyc_rejected",           # admin rejected outright
    "kyc_approved",           # admin approved, but T&C not yet accepted
    "tnc_pending",            # alias of kyc_approved before T&C tick
    "agreement_generated",    # T&C accepted + PDF generated
    "live",                   # artist appears on public site
    "suspended",              # admin can suspend a live artist
]

# Which transitions the ADMIN may perform (Sec 9)
_ADMIN_TRANSITIONS: Dict[str, List[str]] = {
    "kyc_under_review":   ["kyc_approved", "kyc_rejected", "kyc_changes_required"],
    "kyc_changes_required": ["kyc_under_review", "kyc_rejected"],
    "kyc_approved":       ["kyc_rejected", "suspended"],
    "tnc_pending":        ["kyc_rejected", "suspended"],
    "agreement_generated": ["live", "suspended"],
    "live":               ["suspended"],
    "suspended":          ["live"],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flip_kyc(db, artist_id: str, new_status: str, extra: Optional[Dict[str, Any]] = None):
    """Persist a KYC status change on the artist profile. Returns the coroutine."""
    doc = {"kyc_status": new_status, "kyc_updated_at": utcnow()}
    if extra:
        doc.update(extra)
    return db.artist_profiles.update_one(
        {"user_id": artist_id}, {"$set": doc}, upsert=True,
    )


# ─── Router ────────────────────────────────────────────────────────────
class KycSubmitBody(BaseModel):
    documents: Dict[str, str]  # {"pan": "<url|base64>", "aadhaar": "...", ...}
    tech_rider_text: Optional[str] = Field(None, max_length=5000)
    bank: Optional[Dict[str, str]] = None


class KycReviewBody(BaseModel):
    action: Literal["approve", "reject", "request_changes"]
    reason: Optional[str] = Field(None, max_length=1000)
    # Only used with "approve" — sets the commercial deal (Sec 10)
    artist_type: Optional[Literal["normal", "service"]] = None
    percentage_deal: Optional[float] = Field(None, ge=0, le=50)


class AcceptTermsBody(BaseModel):
    accepted: bool


def make_v2_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ─── Finance ────────────────────────────────────────────────────
    @r.get("/finance/quote")
    async def quote(
        artist_id: Optional[str] = None,
        package_fee: float = 0.0,
        addons_total: float = 0.0,
        coupon_discount: float = 0.0,
    ):
        """Canonical price breakdown. Called by the booking flow whenever
        any input changes so the on-screen total stays perfectly in sync
        with what the server will actually charge."""
        return await compute_price(
            db,
            artist_id=artist_id,
            package_fee=package_fee,
            addons_total=addons_total,
            coupon_discount=coupon_discount,
        )

    # ─── KYC: artist side ────────────────────────────────────────────
    @r.get("/kyc/me")
    async def my_kyc(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        prof = await db.artist_profiles.find_one(
            {"user_id": user["id"]},
            {"_id": 0, "kyc_status": 1, "kyc_documents": 1, "kyc_updated_at": 1,
             "kyc_review_reason": 1, "is_service_artist": 1, "percentage_deal": 1,
             "tnc_accepted_at": 1, "agreement_url": 1, "agreement_generated_at": 1},
        ) or {}
        status = prof.get("kyc_status") or "kyc_pending"
        return {
            "kyc_status": status,
            "kyc_documents": prof.get("kyc_documents") or {},
            "kyc_review_reason": prof.get("kyc_review_reason") or "",
            "is_service_artist": bool(prof.get("is_service_artist")),
            "percentage_deal": float(prof.get("percentage_deal") or 0),
            "tnc_accepted_at": prof.get("tnc_accepted_at"),
            "agreement_url": prof.get("agreement_url"),
            "agreement_generated_at": prof.get("agreement_generated_at"),
            "next_step": _next_step(status, prof),
        }

    # Iter 90 — /kyc/submit lives ONLY in routes/kyc.py (richer schema:
    # media upload IDs, PAN/Aadhaar regex validation, masked storage).
    # Kept here as a `_flip_kyc` seam only; the HTTP surface is
    # de-duplicated.

    # ─── KYC: admin side ─────────────────────────────────────────────
    @r.get("/admin/kyc/queue")
    async def kyc_queue(
        status: Optional[str] = Query(None),
        limit: int = 100,
        _admin: dict = Depends(require_admin),
    ):
        q: Dict[str, Any] = {}
        if status:
            if status not in KYC_STATUSES:
                raise HTTPException(400, "Invalid status")
            q["kyc_status"] = status
        else:
            # Default queue = actively-actionable states
            q["kyc_status"] = {"$in": ["kyc_under_review", "kyc_changes_required"]}
        limit = max(1, min(int(limit), 500))
        rows = await db.artist_profiles.find(
            q, {"_id": 0, "user_id": 1, "stage_name": 1, "kyc_status": 1,
                "kyc_documents": 1, "kyc_updated_at": 1, "kyc_submitted_at": 1,
                "percentage_deal": 1, "is_service_artist": 1,
                "tech_rider_text": 1, "bank": 1, "kyc_review_reason": 1},
        ).sort("kyc_updated_at", -1).to_list(limit)
        return {"items": rows, "count": len(rows)}

    @r.post("/admin/kyc/{artist_id}/review")
    async def review_kyc(artist_id: str, body: KycReviewBody, request: Request,
                         admin: dict = Depends(require_admin)):
        prof = await db.artist_profiles.find_one({"user_id": artist_id})
        if not prof:
            raise HTTPException(404, "Artist not found")

        current_status = prof.get("kyc_status") or "kyc_pending"
        target = {
            "approve": "kyc_approved",
            "reject": "kyc_rejected",
            "request_changes": "kyc_changes_required",
        }[body.action]

        allowed = _ADMIN_TRANSITIONS.get(current_status, [])
        if target not in allowed and current_status != target:
            raise HTTPException(
                400,
                f"Illegal KYC transition {current_status} → {target} (allowed: {allowed})",
            )

        extra: Dict[str, Any] = {"kyc_review_reason": body.reason or ""}
        if body.action == "approve":
            # Sec 10 — set commercial deal at approval time
            is_service = (body.artist_type == "service")
            pct = float(body.percentage_deal or 0)
            if is_service and pct <= 0:
                raise HTTPException(400, "Service artist requires percentage_deal > 0")
            extra["is_service_artist"] = is_service
            extra["percentage_deal"] = pct if is_service else 0.0
            extra["kyc_approved_at"] = utcnow()

        await _flip_kyc(db, artist_id, target, extra=extra)
        await record_audit(
            db, actor=admin, action=f"kyc.{body.action}", entity="artist",
            entity_id=artist_id, old_value=current_status, new_value=target,
            metadata={"reason": body.reason,
                      "artist_type": body.artist_type,
                      "percentage_deal": body.percentage_deal},
            request=request,
        )

        # Sec 11 — fire approval email (best-effort). We don't wait.
        if body.action == "approve":
            import asyncio
            asyncio.create_task(_notify_kyc_approved(db, artist_id))

        return {"ok": True, "kyc_status": target}

    # ─── T&C + Agreement ─────────────────────────────────────────────
    @r.post("/kyc/accept-terms")
    async def accept_terms(body: AcceptTermsBody, request: Request,
                            user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        if not body.accepted:
            raise HTTPException(400, "You must accept the Terms & Conditions to continue")

        prof = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
        current = prof.get("kyc_status") or "kyc_pending"
        if current not in ("kyc_approved", "tnc_pending"):
            raise HTTPException(400, "Terms can only be accepted after KYC is approved")

        # Generate agreement (see _generate_agreement below)
        agreement = await _generate_agreement(db, user, prof)
        await _flip_kyc(db, user["id"], "agreement_generated", extra={
            "tnc_accepted_at": utcnow(),
            "agreement_url": agreement["url"],
            "agreement_generated_at": utcnow(),
            "agreement_id": agreement["id"],
        })
        # Auto-flip to live — the artist is now bookable.
        await _flip_kyc(db, user["id"], "live", extra={"went_live_at": utcnow()})

        await record_audit(db, actor=user, action="kyc.tnc_accept", entity="artist",
                           entity_id=user["id"], new_value="live", request=request)
        return {
            "ok": True,
            "kyc_status": "live",
            "agreement_url": agreement["url"],
        }

    @r.get("/agreements/mine")
    async def my_agreement(user: dict = Depends(get_current_user)):
        if user.get("role") != "artist":
            raise HTTPException(403, "Artists only")
        prof = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
        if not prof.get("agreement_id"):
            raise HTTPException(404, "Agreement not generated yet")
        rec = await db.agreements.find_one({"id": prof["agreement_id"]})
        if not rec:
            raise HTTPException(404, "Agreement missing")
        return StreamingResponse(
            io.BytesIO(bytes.fromhex(rec["pdf_hex"])),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="agreement-{rec["ref"]}.pdf"'},
        )

    return r


# ─── helpers ───────────────────────────────────────────────────────────
def _next_step(status: str, prof: Dict[str, Any]) -> str:
    """Copy shown in the artist dashboard nudging them to the next action."""
    if status in ("registration_pending", "kyc_pending"):
        return "Upload your KYC documents to activate your artist profile."
    if status == "kyc_under_review":
        return "Your KYC is under review. We'll email you within 48 hours."
    if status == "kyc_changes_required":
        return f"Please re-submit KYC — reviewer note: {prof.get('kyc_review_reason') or 'see email'}"
    if status == "kyc_rejected":
        return "Your KYC was rejected. Contact support to re-apply."
    if status in ("kyc_approved", "tnc_pending"):
        return "Please review and accept the BookTalent Terms & Conditions to go live."
    if status == "agreement_generated":
        return "Finalising your listing — you'll be live in a few seconds."
    if status == "live":
        return "You're live on BookTalent. Keep your calendar up to date."
    if status == "suspended":
        return "Your listing is currently suspended. Contact support."
    return ""


async def _notify_kyc_approved(db: AsyncIOMotorDatabase, artist_id: str) -> None:
    """Fire Sec 11 approval email. WhatsApp channel is queued for Phase 7."""
    from email_service import _send_sync  # local import to avoid circulars
    import asyncio
    try:
        u = await db.users.find_one({"id": artist_id}) or {}
        if not u.get("email"):
            return
        name = (u.get("first_name") or "").strip() or "there"
        subject = "Your BookTalent KYC has been approved ✅"
        html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,sans-serif;color:#F0EEFF;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;"><tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;">
          <tr><td style="padding:36px;">
            <div style="font-family:'Times New Roman',serif;font-size:22px;font-weight:700;margin-bottom:18px;">Book<span style="color:#D4AF37;">Talent</span></div>
            <h2 style="font-family:'Times New Roman',serif;font-size:28px;margin:0 0 8px;">KYC <span style="color:#D4AF37;">Approved</span></h2>
            <p style="color:rgba(240,238,255,0.7);font-size:14px;line-height:1.6;">Hi {name}, your KYC is approved. Log in to your dashboard, review the Terms & Conditions, and your listing will go live automatically.</p>
          </td></tr>
        </table></td></tr></table></body></html>"""
        await asyncio.to_thread(_send_sync, u["email"], subject, html,
                                 f"Hi {name}, your KYC is approved. Log in to accept the T&C and go live.")
    except Exception:
        pass


async def _generate_agreement(db: AsyncIOMotorDatabase, user: Dict[str, Any],
                              prof: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the artist agreement PDF, store it (bytes-in-Mongo for now
    since agreements are tiny), and email it. Returns ``{id, url, ref}``.

    Kept intentionally simple — text-only PDF via reportlab if available,
    plain-text fallback otherwise. Legally binding form of consent is the
    T&C tick, not a wet/e-signature.
    """
    from routes.settings import get_settings as _get_settings
    settings = await _get_settings(db)
    company = settings.get("company_info") or {}

    ref = f"AG-{datetime.now(timezone.utc).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    artist_name = prof.get("stage_name") or f"{user.get('first_name','')} {user.get('last_name','')}".strip()
    pct = float(prof.get("percentage_deal") or 0)
    is_service = bool(prof.get("is_service_artist"))
    lines = [
        f"BOOKTALENT ARTIST AGREEMENT · {ref}",
        f"Date: {datetime.now(timezone.utc).strftime('%d %b %Y')}",
        "",
        f"Between: {company.get('legal_name', 'BookTalent')}",
        f"And:     {artist_name}  (Email: {user.get('email','-')})",
        "",
        "1. Engagement",
        "   BookTalent will list the Artist on its platform and route",
        "   customer enquiries and bookings to the Artist per the platform's",
        "   standard operating rules.",
        "",
        "2. Commercial",
        (
            f"   Artist Type: BookTalent Service Artist. BookTalent share = {pct:g}% "
            "of the artist performance fee on all applicable bookings. "
            "The customer-side 5% Platform Fee is WAIVED for this artist."
            if is_service else
            "   Artist Type: Platform (Normal) Artist. BookTalent charges the "
            "customer a 5% Platform Fee. No revenue share is deducted from "
            "the Artist's fee."
        ),
        "",
        "3. Payments",
        "   Customer payments follow the BookTalent Payment Schedule",
        "   (currently 30/40/20/10). At least 90% of the booking value is",
        "   collected before the event. Artist settlements are processed",
        "   after the booking is confirmed and per BookTalent settlement",
        "   rules.",
        "",
        "4. Conduct & Cancellations",
        "   The Artist agrees to BookTalent's Cancellation & Refund Policy",
        "   as published on the platform, and to industry-standard conduct",
        "   at all events.",
        "",
        "5. Data & Privacy",
        "   For BookTalent Service Artists, direct customer contact is not",
        "   shared with the customer; all pre-booking communication is",
        "   routed through the BookTalent manager.",
        "",
        "6. Governing Law",
        "   This agreement is governed by the laws of India. Jurisdiction:",
        "   the courts of the Artist's state of residence or BookTalent's",
        "   principal office as applicable.",
        "",
        f"Accepted by the Artist on: {utcnow()}  (electronic T&C consent)",
    ]

    pdf_bytes: bytes
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, h - 60, lines[0])
        c.setFont("Helvetica", 10)
        y = h - 90
        for ln in lines[1:]:
            if y < 60:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = h - 60
            c.drawString(50, y, ln)
            y -= 14
        c.showPage()
        c.save()
        pdf_bytes = buf.getvalue()
    except Exception:
        pdf_bytes = "\n".join(lines).encode("utf-8")

    agreement_id = str(uuid.uuid4())
    await db.agreements.insert_one({
        "id": agreement_id,
        "ref": ref,
        "artist_id": user["id"],
        "pdf_hex": pdf_bytes.hex(),
        "generated_at": utcnow(),
        "commercial": {"is_service": is_service, "percentage_deal": pct},
    })

    # Email it (best effort)
    try:
        from email_service import _send_sync
        import asyncio as _a
        html = f"""<p>Hi {user.get('first_name','')}, your BookTalent artist agreement is attached / available in your dashboard.
        Reference: <b>{ref}</b>.</p>"""
        await _a.to_thread(_send_sync, user.get("email"),
                            f"Your BookTalent Artist Agreement — {ref}", html,
                            "\n".join(lines))
    except Exception:
        pass

    frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
    return {"id": agreement_id, "ref": ref,
            "url": f"{frontend_url}/api/agreements/mine" if frontend_url else "/api/agreements/mine"}
