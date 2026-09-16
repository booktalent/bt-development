"""
Feb-2026 Requirement Batch 5.

Adds:
  1. CSV Bank Presets — save/reuse column mappings per bank (HDFC/ICICI/…).
  2. SLA Escalation Tiers — 48 h / 72 h / 96 h ladder for stale mutual
     refund requests, each tier louder than the last.
  3. Preset Recommendations — surface top-3 most-used team presets.
  4. Timeline Badge — cheap "current stage" summary per booking.
  5. Auditor Watchlists — flag specific bookings; any refund activity
     pings Slack immediately regardless of amount.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

log = logging.getLogger("req_batch_5")


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Escalation ladder
# ═══════════════════════════════════════════════════════════════════════
# Tier 0 (48 h) — already handled by routes/req_batch_4.py::refund_sla_loop.
# Tier 1 (72 h) — Slack with a channel-mention prefix so on-call sees it.
# Tier 2 (96 h) — CEO ping via internal email digest + Slack @here.
ESCALATION_TIERS = [
    {"tier": 1, "hours": 72, "prefix": "<!channel> ", "kind": "sla_72h"},
    {"tier": 2, "hours": 96, "prefix": "<!here> ", "kind": "sla_96h_ceo"},
]
ESCALATION_INTERVAL_SEC = 60 * 60 * 6  # every 6 h — same cadence as base loop


async def _fire_escalation_for_tier(db: AsyncIOMotorDatabase, tier_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Sweep pending refund requests past this tier's threshold that we
    haven't alerted at this tier yet."""
    from routes.iter89 import notify_slack

    cutoff = (utcnow_dt() - timedelta(hours=tier_meta["hours"])).isoformat()
    filt = {
        "status": "pending_counter_ack",
        "created_at": {"$lt": cutoff},
        f"escalation_alerts.{tier_meta['kind']}": {"$exists": False},
    }
    stale = await db.refund_requests.find(filt).to_list(200)
    if not stale:
        return {"tier": tier_meta["tier"], "alerted": 0}

    lines = []
    for r in stale[:12]:
        bk = await db.bookings.find_one({"id": r["booking_id"]},
                                        {"_id": 0, "ref": 1}) or {}
        hours = round(
            (utcnow_dt() - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600,
            1,
        )
        lines.append(
            f"• *{bk.get('ref') or r['booking_id']}* — ₹{r['amount']:,.0f} "
            f"idle {hours} h ({r.get('requested_by_role')})"
        )
    ceo = " · CC founders / CEO" if tier_meta["tier"] >= 2 else ""
    text = (
        f"{tier_meta['prefix']}:rotating_light: *Refund SLA — Tier {tier_meta['tier']} "
        f"({tier_meta['hours']} h)* — {len(stale)} request(s) still ignored{ceo}:\n"
        + "\n".join(lines)
        + (f"\n…and {len(stale) - 12} more." if len(stale) > 12 else "")
        + "\n→ Admin → Refund Auditor"
    )
    await notify_slack(db, text=text)

    # Tier 2 additionally fanouts an in-app "founder ping" notification.
    if tier_meta["tier"] >= 2:
        founders = await db.users.find(
            {"role": {"$in": ["admin", "subadmin"]}}, {"_id": 0, "id": 1},
        ).to_list(50)
        for f in founders:
            try:
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": f["id"],
                    "kind": "refund_ceo_ping",
                    "title": "Refunds SLA — 96 h escalation",
                    "body": f"{len(stale)} mutual-refund request(s) unresolved for > 96 h. Immediate review needed.",
                    "read": False,
                    "created_at": utcnow(),
                })
            except Exception:
                pass

    # Mark this tier as fired on each of the stale rows.
    ids = [r["id"] for r in stale]
    await db.refund_requests.update_many(
        {"id": {"$in": ids}},
        {"$set": {f"escalation_alerts.{tier_meta['kind']}": utcnow()}},
    )
    return {"tier": tier_meta["tier"], "alerted": len(ids), "request_ids": ids}


async def _escalation_sweep(db: AsyncIOMotorDatabase) -> List[Dict[str, Any]]:
    """Run every tier once in order; higher tiers naturally fire only for
    older rows because of their bigger `cutoff` window."""
    out = []
    for tier_meta in ESCALATION_TIERS:
        try:
            out.append(await _fire_escalation_for_tier(db, tier_meta))
        except Exception as e:  # noqa: BLE001
            log.warning("escalation tier %s failed: %s", tier_meta["tier"], e)
    return out


async def escalation_loop(db: AsyncIOMotorDatabase) -> None:
    await asyncio.sleep(180)  # let boot settle
    while True:
        try:
            await _escalation_sweep(db)
        except Exception as e:  # noqa: BLE001
            log.warning("escalation_loop: %s", e)
        await asyncio.sleep(ESCALATION_INTERVAL_SEC)


# ═══════════════════════════════════════════════════════════════════════
# Bodies
# ═══════════════════════════════════════════════════════════════════════
class BankPresetBody(BaseModel):
    bank_name: str = Field(min_length=1, max_length=50)
    mapping: Dict[str, List[str]] = Field(default_factory=dict)


class WatchlistBody(BaseModel):
    booking_id: str
    note: str = Field(default="", max_length=200)


class CommercialDealBody(BaseModel):
    """Admin can update an artist's commercial deal *after* KYC approval —
    e.g. Normal → Service upgrade, or bumping % from 10 → 12."""
    artist_type: str = Field(pattern="^(normal|service)$")
    percentage_deal: float = Field(ge=0, le=50)


# ═══════════════════════════════════════════════════════════════════════
# Timeline stage helper (used by /bookings/mine/badges)
# ═══════════════════════════════════════════════════════════════════════
def _current_stage(booking: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a compact ({stage, label, tint}) badge for a booking."""
    kinds = {e.get("kind") for e in events or []}
    total = float((booking.get("pricing") or {}).get("total") or 0)
    paid = float(booking.get("paid_amount") or 0)
    status = (booking.get("status") or "").lower()
    payout = (booking.get("artist_payout_status") or "").lower()

    if status == "completed" or status == "reviewed" or "final_settled" in kinds:
        return {"stage": "completed", "label": "Completed", "tint": "emerald"}
    if payout == "paid" or "artist_payout" in kinds:
        return {"stage": "settled", "label": "Payout Settled", "tint": "emerald"}
    if paid >= total > 0:
        return {"stage": "fully_paid", "label": "Fully Paid", "tint": "gold"}
    if paid > 0 or "payment_received" in kinds:
        return {"stage": "partial_paid", "label": "Partly Paid", "tint": "amber"}
    if status in ("confirmed", "started") or "booking_confirmed" in kinds:
        return {"stage": "confirmed", "label": "Confirmed · Awaiting Payment", "tint": "gold"}
    if status == "pending_artist":
        return {"stage": "awaiting_artist", "label": "Awaiting Artist", "tint": "violet"}
    return {"stage": "new", "label": "Booking Created", "tint": "blue"}


# ═══════════════════════════════════════════════════════════════════════
# Watchlist Slack helper (called from refund actions)
# ═══════════════════════════════════════════════════════════════════════
async def maybe_ping_watchlist(db: AsyncIOMotorDatabase, *, booking_id: str,
                                action: str, actor_role: Optional[str] = None,
                                amount: Optional[float] = None) -> None:
    """If this booking is on any watchlist, ping Slack immediately."""
    try:
        watchers = await db.refund_watchlist.find({"booking_id": booking_id}).to_list(20)
        if not watchers:
            return
        from routes.iter89 import notify_slack
        bk = await db.bookings.find_one({"id": booking_id}, {"_id": 0, "ref": 1}) or {}
        amt_str = f" · ₹{amount:,.0f}" if amount else ""
        watch_names: List[str] = []
        for w in watchers:
            u = await db.users.find_one({"id": w.get("admin_id")},
                                         {"_id": 0, "email": 1}) or {}
            watch_names.append(u.get("email") or w.get("admin_id"))
        text = (
            f":eye: *Watchlist alert* — Refund activity on watched booking "
            f"*{bk.get('ref') or booking_id}*: `{action}`{amt_str} by {actor_role or 'unknown'}.\n"
            f"Watchers: {', '.join(watch_names)}"
        )
        await notify_slack(db, text=text)
        await db.refund_watchlist.update_many(
            {"booking_id": booking_id},
            {"$inc": {"trigger_count": 1},
             "$set": {"last_triggered_at": utcnow()}},
        )
    except Exception as e:  # noqa: BLE001
        log.warning("watchlist ping for %s failed: %s", booking_id, e)


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_5_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ───────────────────────────────────────────────────────────────
    # (1) CSV Bank Presets — CRUD
    # ───────────────────────────────────────────────────────────────
    @r.get("/admin/payouts/bank-presets")
    async def list_bank_presets(_: dict = Depends(require_admin)):
        rows = await db.csv_bank_presets.find({}, {"_id": 0}).sort("last_used_at", -1).to_list(50)
        return {"items": rows, "count": len(rows)}

    @r.post("/admin/payouts/bank-presets")
    async def create_bank_preset(body: BankPresetBody, user: dict = Depends(require_admin)):
        doc = {
            "id": str(uuid.uuid4()),
            "bank_name": body.bank_name.strip(),
            "mapping": body.mapping,
            "created_by": user.get("id"),
            "created_at": utcnow(),
            "usage_count": 0,
        }
        await db.csv_bank_presets.insert_one(doc)
        doc.pop("_id", None)
        return {"ok": True, "preset": doc}

    @r.patch("/admin/payouts/bank-presets/{preset_id}")
    async def update_bank_preset(preset_id: str, body: BankPresetBody,
                                  _: dict = Depends(require_admin)):
        r_out = await db.csv_bank_presets.update_one(
            {"id": preset_id},
            {"$set": {"bank_name": body.bank_name.strip(),
                      "mapping": body.mapping,
                      "updated_at": utcnow()}},
        )
        if r_out.matched_count == 0:
            raise HTTPException(404, "Bank preset not found")
        return {"ok": True}

    @r.delete("/admin/payouts/bank-presets/{preset_id}")
    async def delete_bank_preset(preset_id: str, _: dict = Depends(require_admin)):
        r_out = await db.csv_bank_presets.delete_one({"id": preset_id})
        if r_out.deleted_count == 0:
            raise HTTPException(404, "Bank preset not found")
        return {"ok": True}

    # ───────────────────────────────────────────────────────────────
    # (2) Escalation trigger (idempotent — tier stamp gates it)
    # ───────────────────────────────────────────────────────────────
    @r.post("/admin/refunds/escalate")
    async def refund_escalate(_: dict = Depends(require_admin)):
        return {"results": await _escalation_sweep(db)}

    # ───────────────────────────────────────────────────────────────
    # (3) Preset Recommendations
    # ───────────────────────────────────────────────────────────────
    @r.get("/manager/booking-presets/recommendations")
    async def preset_recommendations(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("manager", "admin", "subadmin"):
            raise HTTPException(403, "Manager or admin only")
        rows = await db.manager_booking_presets.find(
            {"shared": True, "usage_count": {"$gt": 0}},
            {"_id": 0},
        ).sort("usage_count", -1).limit(3).to_list(3)
        return {"items": rows, "count": len(rows)}

    # ───────────────────────────────────────────────────────────────
    # (4) Timeline badges for the current customer's bookings
    # ───────────────────────────────────────────────────────────────
    @r.get("/bookings/mine/badges")
    async def my_booking_badges(user: dict = Depends(get_current_user)):
        role = user.get("role")
        if role not in ("customer", "artist"):
            raise HTTPException(403, "Customer or artist only")
        key = "customer_id" if role == "customer" else "artist_id"
        cur = db.bookings.find(
            {key: user["id"]},
            {"_id": 0, "id": 1, "status": 1, "paid_amount": 1,
             "artist_payout_status": 1, "pricing": 1},
        ).sort("created_at", -1).limit(200)
        badges: Dict[str, Dict[str, Any]] = {}
        async for bk in cur:
            evs = await db.booking_events.find(
                {"booking_id": bk["id"]}, {"_id": 0, "kind": 1},
            ).to_list(50)
            badges[bk["id"]] = _current_stage(bk, evs)
        return {"items": badges, "count": len(badges)}

    # ───────────────────────────────────────────────────────────────
    # (5) Auditor Watchlists
    # ───────────────────────────────────────────────────────────────
    @r.get("/admin/refunds/watchlist")
    async def list_watchlist(_: dict = Depends(require_admin)):
        rows = await db.refund_watchlist.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
        # Hydrate booking ref for the UI table.
        for row in rows:
            bk = await db.bookings.find_one({"id": row.get("booking_id")},
                                             {"_id": 0, "ref": 1}) or {}
            row["booking_ref"] = bk.get("ref") or row.get("booking_id")
        return {"items": rows, "count": len(rows)}

    @r.post("/admin/refunds/watchlist")
    async def add_to_watchlist(body: WatchlistBody, user: dict = Depends(require_admin)):
        bk = await db.bookings.find_one({"id": body.booking_id}, {"_id": 0, "id": 1})
        if not bk:
            raise HTTPException(404, "Booking not found")
        # Idempotent per (admin, booking).
        existing = await db.refund_watchlist.find_one(
            {"admin_id": user["id"], "booking_id": body.booking_id},
        )
        if existing:
            existing.pop("_id", None)
            return {"ok": True, "existing": True, "row": existing}
        doc = {
            "id": str(uuid.uuid4()),
            "admin_id": user["id"],
            "booking_id": body.booking_id,
            "note": body.note,
            "created_at": utcnow(),
            "trigger_count": 0,
        }
        await db.refund_watchlist.insert_one(doc)
        doc.pop("_id", None)
        return {"ok": True, "existing": False, "row": doc}

    @r.delete("/admin/refunds/watchlist/{watch_id}")
    async def remove_watchlist(watch_id: str, user: dict = Depends(require_admin)):
        r_out = await db.refund_watchlist.delete_one(
            {"id": watch_id, "admin_id": user["id"]},
        )
        if r_out.deleted_count == 0:
            raise HTTPException(404, "Watch row not found")
        return {"ok": True}

    # ───────────────────────────────────────────────────────────────
    # Admin: view/edit an artist's commercial deal any time after KYC.
    # (Iter 98 companion to /admin/kyc/decide which sets it at approval.)
    # ───────────────────────────────────────────────────────────────
    @r.get("/admin/artists/{artist_id}/commercial-deal")
    async def get_commercial_deal(artist_id: str, _: dict = Depends(require_admin)):
        u = await db.users.find_one({"id": artist_id, "role": "artist"},
                                     {"_id": 0, "email": 1, "first_name": 1, "last_name": 1})
        if not u:
            raise HTTPException(404, "Artist not found")
        p = await db.artist_profiles.find_one(
            {"user_id": artist_id},
            {"_id": 0, "stage_name": 1, "is_service_artist": 1,
             "artist_type": 1, "percentage_deal": 1,
             "commercial_deal_set_at": 1, "commercial_deal_set_by": 1,
             "kyc_status": 1},
        ) or {}
        return {"artist": u, "profile": p}

    @r.patch("/admin/artists/{artist_id}/commercial-deal")
    async def set_commercial_deal(artist_id: str, body: CommercialDealBody,
                                    user: dict = Depends(require_admin)):
        prof = await db.artist_profiles.find_one({"user_id": artist_id}, {"_id": 0, "kyc_status": 1})
        if not prof:
            raise HTTPException(404, "Artist profile not found")
        is_service = (body.artist_type == "service") and (body.percentage_deal > 0)
        await db.artist_profiles.update_one(
            {"user_id": artist_id},
            {"$set": {
                "artist_type": body.artist_type,
                "is_service_artist": is_service,
                "percentage_deal": body.percentage_deal if is_service else 0.0,
                "commercial_deal_set_at": utcnow(),
                "commercial_deal_set_by": user.get("email"),
            }},
        )
        try:
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "actor_id": user.get("id"), "actor_role": user.get("role"),
                "action": "artist.commercial_deal_updated",
                "entity": "artist_profile", "entity_id": artist_id,
                "metadata": {"artist_type": body.artist_type,
                             "percentage_deal": body.percentage_deal,
                             "is_service_artist": is_service},
                "created_at": utcnow(),
            })
        except Exception:
            pass
        return {"ok": True, "is_service_artist": is_service,
                "percentage_deal": body.percentage_deal if is_service else 0.0}

    return r
