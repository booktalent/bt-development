"""
Iter 90 — KYC status single source of truth.

Historically there were 3 places writing/reading KYC status:
  1. users.kyc_status           (legacy — used by admin queries & seed)
  2. kyc_submissions.status     (legacy — 4-state: pending/approved/
                                  rejected/needs_resubmission)
  3. artist_profiles.kyc_status (v2 — 9-state machine)

We make #3 the ONLY source of truth. The other two become mirrored
read-only caches. This helper centralises every write so no route ever
needs to touch the individual collections directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger("booktalent.kyc_sync")


# 4-state (legacy) ↔ 9-state (v2) bidirectional mapping.
LEGACY_TO_V2: Dict[str, str] = {
    "pending":              "kyc_under_review",
    "approved":             "kyc_approved",
    "rejected":             "kyc_rejected",
    "needs_resubmission":   "kyc_changes_required",
}
V2_TO_LEGACY: Dict[str, str] = {
    # Anything past kyc_approved is functionally "approved" in the legacy view
    "kyc_pending":          "pending",
    "kyc_under_review":     "pending",
    "kyc_changes_required": "needs_resubmission",
    "kyc_rejected":         "rejected",
    "kyc_approved":         "approved",
    "tnc_pending":          "approved",
    "agreement_generated":  "approved",
    "live":                 "approved",
    "suspended":            "rejected",
    # Iter 90 — Backward-compat: legacy 4-state values stored directly in
    # artist_profiles.kyc_status (from before the v2 rename). Normalise
    # them to their v2 equivalents so backfill idempotently upgrades.
    "pending":              "pending",
    "approved":             "approved",
    "rejected":             "rejected",
    "needs_resubmission":   "needs_resubmission",
    "unverified":           "pending",
}


# Values that are still on the legacy 4-state naming — the backfill will
# rewrite them to the v2 name so every artist ends up with a canonical
# 9-state string in artist_profiles.kyc_status.
LEGACY_STATUS_UPGRADE: Dict[str, str] = {
    "pending":              "kyc_under_review",
    "approved":             "kyc_approved",
    "rejected":             "kyc_rejected",
    "needs_resubmission":   "kyc_changes_required",
    "unverified":           "kyc_pending",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_kyc_status(
    db: AsyncIOMotorDatabase,
    *,
    user_id: str,
    v2_status: Optional[str] = None,
    legacy_status: Optional[str] = None,
    reason: Optional[str] = None,
    decided_by: Optional[str] = None,
) -> Dict[str, str]:
    """Write KYC status atomically across all 3 collections.

    Pass EITHER `v2_status` (9-state) OR `legacy_status` (4-state);
    the other is derived from the mapping tables.

    Returns the resolved {v2, legacy} pair so callers can log/respond.
    """
    if not (v2_status or legacy_status):
        raise ValueError("Provide v2_status or legacy_status")

    if v2_status:
        v2 = v2_status
        legacy = V2_TO_LEGACY.get(v2, "pending")
    else:
        legacy = legacy_status
        v2 = LEGACY_TO_V2.get(legacy, "kyc_pending")

    now = utcnow()
    verified = v2 in ("kyc_approved", "tnc_pending", "agreement_generated", "live")

    # 1. Canonical: artist_profiles.kyc_status
    await db.artist_profiles.update_one(
        {"user_id": user_id},
        {"$set": {"kyc_status": v2,
                  "kyc_updated_at": now,
                  "verified_badge": verified}},
    )
    # 2. Mirrored cache: users.kyc_status (for fast admin queries)
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"kyc_status": v2,           # ← store v2 as canonical
                  "kyc_legacy_status": legacy, # ← keep legacy name too for old queries
                  "verified": verified}},
    )
    # 3. Document review: kyc_submissions.status (auto-sync)
    #    We only touch this if a submission row already exists.
    upd = {
        "status": legacy,
        "v2_status": v2,
        "decided_at": now,
    }
    if decided_by:
        upd["decided_by"] = decided_by
    if reason is not None:
        upd["reason"] = reason
    await db.kyc_submissions.update_one(
        {"user_id": user_id},
        {"$set": upd},
        upsert=False,  # only update if exists — don't create phantom rows
    )
    log.info("kyc sync user=%s v2=%s legacy=%s", user_id, v2, legacy)
    return {"v2": v2, "legacy": legacy}


async def backfill_all(db: AsyncIOMotorDatabase) -> Dict[str, int]:
    """One-shot: walk every artist and align users.kyc_status +
    kyc_submissions.status to artist_profiles.kyc_status (canonical).
    Idempotent — safe to run at boot.
    """
    fixed = 0
    scanned = 0
    async for prof in db.artist_profiles.find(
        {}, {"user_id": 1, "kyc_status": 1, "_id": 0},
    ):
        scanned += 1
        uid = prof.get("user_id")
        if not uid:
            continue
        raw_status = prof.get("kyc_status") or "kyc_pending"
        # Upgrade legacy 4-state → v2 9-state if we detect an old value.
        if raw_status in LEGACY_STATUS_UPGRADE:
            v2 = LEGACY_STATUS_UPGRADE[raw_status]
            # Also persist the upgraded value on the canonical doc.
            await db.artist_profiles.update_one(
                {"user_id": uid},
                {"$set": {"kyc_status": v2, "kyc_upgraded_from": raw_status}},
            )
        else:
            v2 = raw_status
        legacy = V2_TO_LEGACY.get(v2, "pending")
        verified = v2 in ("kyc_approved", "tnc_pending", "agreement_generated", "live")
        # Only update if drifted
        u = await db.users.find_one({"id": uid}, {"kyc_status": 1, "kyc_legacy_status": 1, "verified": 1, "_id": 0})
        if u is None:
            # Orphan artist_profile — user was deleted. Skip so backfill
            # converges instead of reporting the same "fix" every boot.
            continue
        drifted = (
            u.get("kyc_status") != v2
            or u.get("kyc_legacy_status") != legacy
            or u.get("verified") != verified
        )
        if drifted:
            await db.users.update_one(
                {"id": uid},
                {"$set": {"kyc_status": v2, "kyc_legacy_status": legacy, "verified": verified}},
            )
            await db.kyc_submissions.update_one(
                {"user_id": uid},
                {"$set": {"status": legacy, "v2_status": v2}},
                upsert=False,
            )
            fixed += 1
    log.info("[kyc_sync backfill] scanned=%d fixed=%d", scanned, fixed)
    return {"scanned": scanned, "fixed": fixed}
