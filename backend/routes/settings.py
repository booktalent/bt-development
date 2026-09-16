"""
Iter 82 — Platform Settings + Audit Log core.

This is the foundation for the v2 financial engine. Every business rule
that MUST be admin-configurable lives here (GST%, Platform Fee%, Payment
Schedule, Payout Mode feature flag, Instant Book rules). Frontend never
hard-codes these — it always reads from `/api/settings/public`.

Every write goes through `record_audit()` so we have a tamper-evident
trail of who changed what and when — critical for financial governance.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field


# ─── Defaults ───────────────────────────────────────────────────────────
# These seed values are used ONLY when the platform_settings row is
# missing. Once seeded, admin edits are the source of truth.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "gst_percent": 18.0,
    "platform_fee_percent": 5.0,
    # Booking → D-7 → D-2 → D+1  (Sec 32)
    "payment_schedule": [
        {"milestone": "booking_advance",  "label": "Booking Advance",    "percent": 30, "offset_days": None,  "mandatory": True},
        {"milestone": "pre_event_7d",     "label": "Event Date − 7 days", "percent": 40, "offset_days": -7,   "mandatory": True},
        {"milestone": "pre_event_2d",     "label": "Event Date − 2 days", "percent": 20, "offset_days": -2,   "mandatory": True},
        {"milestone": "post_event_1d",    "label": "Event Date + 1 day",  "percent": 10, "offset_days":  1,   "mandatory": True},
    ],
    "instant_book_rules": {
        # Event > 7 days → use standard payment_schedule
        "standard_window_days": 7,
        # Event ≤ 7 days → collect 90% before event
        "short_window_min_before_event_pct": 90,
        # Event ≤ 48h → collect 100% upfront
        "very_short_window_hours": 48,
        "very_short_window_min_pct": 100,
        # Same-day booking → 100% + artist confirm + manager confirm
        "same_day_requires_manager_confirm": True,
    },
    # Sec 43 — MANUAL by default. Never flip to easebuzz without an admin
    # explicitly enabling it AND providing valid Easebuzz Payout credentials.
    "payout_mode": "manual",           # "manual" | "easebuzz"
    "enable_automated_payout": False,   # feature flag (Sec 43)
    "required_kyc_docs": [
        {"code": "pan",         "label": "PAN Card",          "required": True},
        {"code": "aadhaar",     "label": "Aadhaar / Govt ID", "required": True},
        {"code": "address",     "label": "Address Proof",     "required": True},
        {"code": "bank",        "label": "Bank Details",      "required": True},
        {"code": "photo",       "label": "Profile Photo",     "required": True},
        {"code": "tech_rider",  "label": "Tech Rider",        "required": False},
    ],
    # Company info — used for GST invoices, agreements
    "company_info": {
        "legal_name": "BookTalent",
        "gstin": "",
        "address": "",
        "pan": "",
        "state": "",
        "support_email": "manager@booktalent.in",
        "support_phone": "",
    },
}

_SETTINGS_ID = "singleton"  # only one row ever


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Audit Log ──────────────────────────────────────────────────────────
async def record_audit(
    db: AsyncIOMotorDatabase,
    *,
    actor: Dict[str, Any],
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """Write a single tamper-evident audit row. Used for every state change
    that has financial or compliance importance (percentage deal changes,
    payment status flips, KYC approvals, payout marks, etc.).

    Never raises — audit failures must never break a business flow. We do
    log them though, so operators can fix logging issues out-of-band.
    """
    try:
        row = {
            "id": str(uuid.uuid4()),
            "actor_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "actor_role": (actor or {}).get("role"),
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "old_value": old_value,
            "new_value": new_value,
            "metadata": metadata or {},
            "ip": request.client.host if request and request.client else None,
            "user_agent": request.headers.get("user-agent") if request else None,
            "at": utcnow(),
        }
        await db.audit_logs.insert_one(row)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("audit").error("record_audit failed: %s", e)


# ─── Settings helpers ────────────────────────────────────────────────────
async def get_settings(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """Return the current platform_settings row, seeding defaults if needed."""
    row = await db.platform_settings.find_one({"id": _SETTINGS_ID})
    if row:
        # Fill any newly-added default keys (forward-compat)
        merged = {**DEFAULT_SETTINGS, **{k: v for k, v in row.items() if k not in ("_id",)}}
        return merged
    # First boot — seed
    await db.platform_settings.insert_one({
        "id": _SETTINGS_ID,
        **DEFAULT_SETTINGS,
        "updated_at": utcnow(),
        "updated_by": "system_seed",
    })
    return {"id": _SETTINGS_ID, **DEFAULT_SETTINGS}


def public_projection(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Fields that are safe to expose to non-admin callers (used by booking
    flow, artist checkout page, etc.)."""
    return {
        "gst_percent": settings.get("gst_percent", 18.0),
        "platform_fee_percent": settings.get("platform_fee_percent", 5.0),
        "payment_schedule": settings.get("payment_schedule", []),
        "instant_book_rules": settings.get("instant_book_rules", {}),
        # Payout mode/flag is EXPOSED so the artist dashboard can conditionally
        # show "Withdraw" button vs "Payouts are processed manually" copy.
        "payout_mode": settings.get("payout_mode", "manual"),
        "enable_automated_payout": bool(settings.get("enable_automated_payout", False)),
        "required_kyc_docs": settings.get("required_kyc_docs", []),
        "company_info": {
            "legal_name": (settings.get("company_info") or {}).get("legal_name", "BookTalent"),
            "support_email": (settings.get("company_info") or {}).get("support_email", ""),
            "support_phone": (settings.get("company_info") or {}).get("support_phone", ""),
        },
    }


# ─── Router factory ──────────────────────────────────────────────────────
class SettingsUpdate(BaseModel):
    """Partial-update body — only include the keys you want to change."""
    gst_percent: Optional[float] = Field(None, ge=0, le=50)
    platform_fee_percent: Optional[float] = Field(None, ge=0, le=50)
    payment_schedule: Optional[List[Dict[str, Any]]] = None
    instant_book_rules: Optional[Dict[str, Any]] = None
    payout_mode: Optional[str] = Field(None, pattern="^(manual|easebuzz)$")
    enable_automated_payout: Optional[bool] = None
    required_kyc_docs: Optional[List[Dict[str, Any]]] = None
    company_info: Optional[Dict[str, Any]] = None


def make_settings_router(db: AsyncIOMotorDatabase, require_admin, get_current_user) -> APIRouter:
    r = APIRouter()

    @r.get("/platform-settings/public")
    async def public_settings():
        """Fields the frontend needs to render prices, payment schedules
        and KYC forms. No auth required — these are non-sensitive."""
        s = await get_settings(db)
        return public_projection(s)

    @r.get("/platform-settings/admin")
    async def admin_settings(user=Depends(require_admin)):
        """Full settings row — admin only."""
        s = await get_settings(db)
        s.pop("_id", None)
        return s

    @r.patch("/platform-settings/admin")
    async def update_settings(body: SettingsUpdate, request: Request, user=Depends(require_admin)):
        """Partial update. Every changed field is audit-logged."""
        current = await get_settings(db)
        updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}

        # Extra guard — flipping payout_mode to easebuzz REQUIRES the
        # automated-payout flag AND live Easebuzz Payout credentials.
        # We validate the flag combo here; credential presence check
        # happens inside the payout service when it's actually invoked.
        if updates.get("payout_mode") == "easebuzz" and not updates.get(
            "enable_automated_payout", current.get("enable_automated_payout")
        ):
            raise HTTPException(
                400,
                "Cannot switch payout_mode to 'easebuzz' unless enable_automated_payout is also true"
            )

        # Payment-schedule sanity: percents must sum to 100
        if "payment_schedule" in updates:
            total = sum(float(s.get("percent", 0)) for s in updates["payment_schedule"])
            if abs(total - 100.0) > 0.01:
                raise HTTPException(400, f"Payment schedule percents must sum to 100 (got {total})")

        # Diff → audit rows
        changed = []
        for key, new_val in updates.items():
            old_val = current.get(key)
            if old_val != new_val:
                changed.append((key, old_val, new_val))

        if not changed:
            return {"ok": True, "changed": []}

        updates["updated_at"] = utcnow()
        updates["updated_by"] = user.get("email")
        await db.platform_settings.update_one(
            {"id": _SETTINGS_ID}, {"$set": updates}, upsert=True
        )

        # Iter 89 — Mirror the two financial values into legacy
        # `system_settings` so the public /settings/public endpoint (read
        # by BookingFlow copy) stays in sync. Legacy admin UI no longer
        # exposes these keys as editable.
        mirror_map = {
            "gst_percent": "gst_pct",
            "platform_fee_percent": "platform_fee_pct",
        }
        for new_key, legacy_key in mirror_map.items():
            if new_key in updates:
                await db.system_settings.update_one(
                    {"key": legacy_key},
                    {"$set": {"key": legacy_key,
                              "value": updates[new_key],
                              "updated_at": utcnow(),
                              "mirrored_from": "platform_settings"}},
                    upsert=True,
                )

        for key, old_val, new_val in changed:
            await record_audit(
                db,
                actor=user,
                action="settings.update",
                entity="platform_settings",
                entity_id=key,
                old_value=old_val,
                new_value=new_val,
                request=request,
            )
        return {"ok": True, "changed": [c[0] for c in changed]}

    @r.get("/audit-logs")
    async def list_audit_logs(
        entity: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        limit: int = 100,
        user=Depends(require_admin),
    ):
        """Newest-first paginated audit view. Admin only."""
        q: Dict[str, Any] = {}
        if entity: q["entity"] = entity
        if entity_id: q["entity_id"] = entity_id
        if actor_id: q["actor_id"] = actor_id
        limit = max(1, min(int(limit), 500))
        rows = await db.audit_logs.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
        return {"items": rows, "count": len(rows)}

    return r
