"""
Sprint 5 — Premium Subscription Plans (Free / Silver / Gold / Platinum / Elite).

An artist's active plan drives:
  • search-ranking boost (higher tier → higher `plan_rank`)
  • badge on artist cards ("💎 GOLD", "👑 ELITE")
  • per-tier feature caps (media, add-ons, response-time SLA, boost multiplier)
  • eligibility for Elite-only homepage rail

Plans are seeded on module import; artists subscribe via a mock payment (until
Razorpay recurring is wired). Downgrade to Free is free & immediate.

Endpoints:
  GET  /subscriptions/plans                  — public catalog
  GET  /subscriptions/me                     — current artist subscription
  POST /subscriptions/subscribe              — start / upgrade (mock payment)
  POST /subscriptions/cancel                 — cancel (falls back to Free at period end)
  GET  /admin/subscriptions                  — admin list
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


# ── Pydantic bodies (module scope so FastAPI can resolve annotations) ──────
class AdminSubEditBody(BaseModel):
    plan: Optional[str] = None
    status: Optional[str] = None
    auto_renew: Optional[bool] = None
    extend_days: Optional[int] = None
    expires_at: Optional[str] = None
    transaction_id: Optional[str] = None


class AdminSubCreateBody(BaseModel):
    artist_id: str
    plan: str
    billing_cycle: str = "monthly"
    duration_days: Optional[int] = None
    transaction_id: Optional[str] = None
    note: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Plan catalog — single source of truth for pricing + feature gates.
# ─────────────────────────────────────────────────────────────────────────────
PLANS = {
    "free": {
        "code": "free", "name": "Free", "price_monthly": 0, "price_yearly": 0,
        "badge": None, "rank": 0, "featured": False,
        "features": {
            "max_media": 6, "max_addons": 3, "priority_support": False,
            "verified_badge": False, "boost_multiplier": 1.0,
            "response_sla_hours": 48, "elite_rail": False,
            "commission_discount_pct": 0,
        },
    },
    "silver": {
        "code": "silver", "name": "Silver", "price_monthly": 499, "price_yearly": 4990,
        "badge": "SILVER", "rank": 1, "featured": False,
        "features": {
            "max_media": 15, "max_addons": 6, "priority_support": False,
            "verified_badge": True, "boost_multiplier": 1.2,
            "response_sla_hours": 24, "elite_rail": False,
            "commission_discount_pct": 0,
        },
    },
    "gold": {
        "code": "gold", "name": "Gold", "price_monthly": 999, "price_yearly": 9990,
        "badge": "GOLD", "rank": 2, "featured": True,
        "features": {
            "max_media": 40, "max_addons": 12, "priority_support": True,
            "verified_badge": True, "boost_multiplier": 1.5,
            "response_sla_hours": 12, "elite_rail": False,
            "commission_discount_pct": 10,
        },
    },
    "platinum": {
        "code": "platinum", "name": "Platinum", "price_monthly": 2499, "price_yearly": 24990,
        "badge": "PLATINUM", "rank": 3, "featured": True,
        "features": {
            "max_media": 100, "max_addons": 25, "priority_support": True,
            "verified_badge": True, "boost_multiplier": 2.0,
            "response_sla_hours": 6, "elite_rail": False,
            "commission_discount_pct": 20,
        },
    },
    "elite": {
        "code": "elite", "name": "Elite", "price_monthly": 4999, "price_yearly": 49990,
        "badge": "ELITE", "rank": 4, "featured": True,
        "features": {
            "max_media": 500, "max_addons": 100, "priority_support": True,
            "verified_badge": True, "boost_multiplier": 3.0,
            "response_sla_hours": 2, "elite_rail": True,
            "commission_discount_pct": 30,
        },
    },
}


class SubscribeBody(BaseModel):
    plan: Literal["free", "silver", "gold", "platinum", "elite"]
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    payment_method: str = "mock"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plan_from_doc(doc: Optional[dict]) -> dict:
    """Resolve the artist's currently active plan document to a full PLAN dict."""
    if not doc or doc.get("status") != "active":
        return PLANS["free"]
    # expired?
    try:
        exp = doc.get("expires_at")
        if exp and datetime.fromisoformat(exp.replace("Z", "+00:00")) < _now():
            return PLANS["free"]
    except Exception:
        pass
    return PLANS.get(doc.get("plan", "free"), PLANS["free"])


async def resolve_plan(db, user_id: str) -> dict:
    """Public helper — used by search/homepage to grade an artist's tier."""
    doc = await db.artist_subscriptions.find_one({"artist_id": user_id, "status": "active"})
    return _plan_from_doc(doc)


def make_router(*, db, get_current_user: Callable, admin_only: Callable, utcnow, new_id, clean) -> APIRouter:
    r = APIRouter()

    async def _activate_plan(user_id: str, plan_code: str, billing_cycle: str,
                             price: float, payment_method: str = "easebuzz",
                             days_override: Optional[int] = None) -> dict:
        """Activate (or renew) a plan for a user. Idempotent — cancels any
        existing active subscription first. Called by both the direct
        `/subscribe` endpoint (free plan) and by the Easebuzz callback
        finaliser after a paid checkout completes."""
        plan = PLANS[plan_code]
        await db.artist_subscriptions.update_many(
            {"artist_id": user_id, "status": "active"},
            {"$set": {"status": "cancelled", "cancelled_at": utcnow()}},
        )
        days = days_override if days_override is not None else (365 if billing_cycle == "yearly" else 30)
        expires = (_now() + timedelta(days=days)).isoformat()
        sub = {
            "id": new_id(),
            "artist_id": user_id,
            "plan": plan_code,
            "billing_cycle": billing_cycle,
            "price": price,
            "status": "active",
            "payment_method": payment_method,
            "started_at": utcnow(),
            "expires_at": expires,
            "auto_renew": payment_method != "trial",
            "is_trial": payment_method == "trial",
        }
        await db.artist_subscriptions.insert_one(sub)
        await db.artist_profiles.update_one(
            {"user_id": user_id},
            {"$set": {
                "premium_badge": plan["rank"] >= 2,
                "plan_code": plan["code"],
                "plan_rank": plan["rank"],
            }},
        )
        await db.notifications.insert_one({
            "id": new_id(), "user_id": user_id, "type": "subscription",
            "title": f"Welcome to {plan['name']}!" if payment_method != "trial"
                     else f"Elite trial activated — 7 days on us 🎩",
            "body": f"Your {plan['name']} plan is active until {expires[:10]}.",
            "read": False, "created_at": utcnow(),
        })
        return sub

    @r.get("/subscriptions/plans")
    async def list_plans():
        return list(PLANS.values())

    @r.get("/subscriptions/me")
    async def my_subscription(user: dict = Depends(get_current_user)):
        doc = await db.artist_subscriptions.find_one({"artist_id": user["id"], "status": "active"})
        plan = _plan_from_doc(doc)
        me = await db.users.find_one({"id": user["id"]}, {"elite_trial_used_at": 1})
        return {
            "subscription": clean(doc) if doc else None,
            "plan": plan,
            "elite_trial_used": bool(me and me.get("elite_trial_used_at")),
        }

    @r.post("/subscriptions/subscribe")
    async def subscribe(body: SubscribeBody, user: dict = Depends(get_current_user)):
        if user["role"] not in ("artist", "agency"):
            raise HTTPException(403, "Only artists / agencies can subscribe")
        plan = PLANS.get(body.plan)
        if not plan:
            raise HTTPException(400, "Invalid plan")

        # For Free plan just cancel any active sub and bounce cached badge.
        if body.plan == "free":
            await db.artist_subscriptions.update_many(
                {"artist_id": user["id"], "status": "active"},
                {"$set": {"status": "cancelled", "cancelled_at": utcnow()}},
            )
            await db.artist_profiles.update_one(
                {"user_id": user["id"]},
                {"$set": {"premium_badge": False, "plan_code": "free", "plan_rank": 0}},
            )
            return {"ok": True, "plan": plan, "downgraded": True}

        # Iter 63.3 — Paid plans must go through Easebuzz. Reject direct
        # activation to prevent bypass. Frontend calls /subscriptions/easebuzz/init.
        raise HTTPException(
            402,
            "Paid plans require a completed payment. Use POST /api/subscriptions/easebuzz/init.",
        )

    # Iter 63.4 — trial endpoint removed per product decision. Free plan
    # remains the only zero-cost tier; artists must pay for Platinum/Elite.

    # Expose the activator on the router so the Easebuzz callback can call it.
    r._activate_plan = _activate_plan  # type: ignore[attr-defined]

    @r.post("/subscriptions/cancel")
    async def cancel(user: dict = Depends(get_current_user)):
        doc = await db.artist_subscriptions.find_one({"artist_id": user["id"], "status": "active"})
        if not doc:
            raise HTTPException(404, "No active subscription")
        await db.artist_subscriptions.update_one(
            {"id": doc["id"]},
            {"$set": {"status": "cancelled", "auto_renew": False, "cancelled_at": utcnow()}},
        )
        # Do NOT downgrade cached profile yet — customer keeps benefits until
        # expires_at. A daily cron would flip premium_badge=False; here we
        # rely on `resolve_plan` runtime expiry check.
        return {"ok": True, "expires_at": doc.get("expires_at")}

    # ─────────────────────────────────────────────────────────────────────
    # Admin: Subscription Management (Iter 52.9)
    # ─────────────────────────────────────────────────────────────────────
    def _serialize(doc: dict, users_by_id: dict, plans: dict) -> dict:
        out = clean(doc) if doc else {}
        subscriber = users_by_id.get(doc.get("artist_id"), {}) if doc else {}
        out["subscriber"] = {
            "id": subscriber.get("id"),
            "name": f"{subscriber.get('first_name') or ''} {subscriber.get('last_name') or ''}".strip() or subscriber.get("email"),
            "email": subscriber.get("email"),
            "phone": subscriber.get("phone"),
            "role": subscriber.get("role"),
            "company_name": subscriber.get("company_name"),
        }
        pl = plans.get(out.get("plan") or "free", {})
        out["plan_name"] = pl.get("name") or out.get("plan")
        # Days-left calc — negative if already past expiry.
        try:
            exp = out.get("expires_at")
            if exp:
                dt_exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                out["days_left"] = int((dt_exp - _now()).total_seconds() // 86400)
        except Exception:
            out["days_left"] = None
        return out

    @r.get("/admin/subscriptions")
    async def admin_subs_list(
        _: dict = Depends(admin_only),
        status: Optional[str] = None,      # active | expired | cancelled | pending
        plan: Optional[str] = None,        # plan code
        role: Optional[str] = None,        # artist | agency
        q: Optional[str] = None,           # search name/email/phone
        page: int = 1,
        limit: int = 50,
    ):
        query: dict = {}
        if status:
            query["status"] = status
        if plan:
            query["plan"] = plan

        # If searching by user or filtering by role, first find matching users.
        if q or role:
            uq: dict = {}
            if role:
                uq["role"] = role
            if q:
                rx = {"$regex": q.strip(), "$options": "i"}
                uq["$or"] = [
                    {"first_name": rx}, {"last_name": rx}, {"email": rx},
                    {"phone": rx}, {"company_name": rx},
                ]
            uids = [u["id"] async for u in db.users.find(uq, {"id": 1})]
            query["artist_id"] = {"$in": uids or ["__none__"]}

        total = await db.artist_subscriptions.count_documents(query)
        docs = await db.artist_subscriptions.find(query).sort("started_at", -1).skip((page - 1) * limit).limit(limit).to_list(limit)

        uids = list({d.get("artist_id") for d in docs if d.get("artist_id")})
        users = {}
        async for u in db.users.find({"id": {"$in": uids}}, {"id": 1, "first_name": 1, "last_name": 1, "email": 1, "phone": 1, "role": 1, "company_name": 1}):
            users[u["id"]] = u

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [_serialize(d, users, PLANS) for d in docs],
        }

    @r.get("/admin/subscriptions/summary")
    async def admin_subs_summary(_: dict = Depends(admin_only)):
        pipeline = [
            {"$group": {"_id": {"status": "$status", "plan": "$plan"}, "count": {"$sum": 1}, "revenue": {"$sum": "$price"}}},
        ]
        rows: list = []
        async for row in db.artist_subscriptions.aggregate(pipeline):
            rows.append({"status": row["_id"].get("status"), "plan": row["_id"].get("plan"), "count": row["count"], "revenue": row.get("revenue", 0)})
        # Also expiring-soon count (next 7 days)
        soon = (_now() + timedelta(days=7)).isoformat()
        expiring = await db.artist_subscriptions.count_documents({
            "status": "active",
            "expires_at": {"$lte": soon, "$gte": _now().isoformat()},
        })
        return {"breakdown": rows, "expiring_soon_7d": expiring}

    @r.get("/admin/subscriptions/{sid}")
    async def admin_subs_get(sid: str, _: dict = Depends(admin_only)):
        doc = await db.artist_subscriptions.find_one({"id": sid})
        if not doc:
            raise HTTPException(404, "Subscription not found")
        user = await db.users.find_one({"id": doc["artist_id"]}) or {}
        history = await db.artist_subscriptions.find({"artist_id": doc["artist_id"]}).sort("started_at", -1).to_list(50)
        return {
            "subscription": _serialize(doc, {doc["artist_id"]: user}, PLANS),
            "history": [_serialize(h, {doc["artist_id"]: user}, PLANS) for h in history],
        }

    @r.patch("/admin/subscriptions/{sid}")
    async def admin_subs_edit(sid: str, body: AdminSubEditBody, _: dict = Depends(admin_only)):
        doc = await db.artist_subscriptions.find_one({"id": sid})
        if not doc:
            raise HTTPException(404, "Subscription not found")
        upd: dict = {}
        if body.plan and body.plan in PLANS:
            upd["plan"] = body.plan
            upd["plan_upgraded_at"] = utcnow()
        if body.status:
            upd["status"] = body.status
            if body.status == "cancelled":
                upd["cancelled_at"] = utcnow()
                upd["auto_renew"] = False
            elif body.status == "expired":
                upd["expired_at"] = utcnow()
        if body.auto_renew is not None:
            upd["auto_renew"] = body.auto_renew
        if body.transaction_id:
            upd["transaction_id"] = body.transaction_id
        # Explicit expiry wins; else extend/reduce by days.
        if body.expires_at:
            upd["expires_at"] = body.expires_at
        elif body.extend_days:
            try:
                cur = datetime.fromisoformat((doc.get("expires_at") or utcnow()).replace("Z", "+00:00"))
            except Exception:
                cur = _now()
            upd["expires_at"] = (cur + timedelta(days=int(body.extend_days))).isoformat()

        if not upd:
            raise HTTPException(400, "Nothing to update")

        await db.artist_subscriptions.update_one({"id": sid}, {"$set": upd})

        # Re-sync artist_profiles denorm when plan / status changes.
        if "plan" in upd or "status" in upd:
            active = await db.artist_subscriptions.find_one({"artist_id": doc["artist_id"], "status": "active"})
            plan_code = (active or {}).get("plan", "free")
            pl = PLANS.get(plan_code, PLANS["free"])
            await db.artist_profiles.update_one(
                {"user_id": doc["artist_id"]},
                {"$set": {"premium_badge": pl["rank"] >= 2, "plan_code": pl["code"], "plan_rank": pl["rank"]}},
            )
        return {"ok": True}

    @r.post("/admin/subscriptions")
    async def admin_subs_create(body: AdminSubCreateBody, _: dict = Depends(admin_only)):
        u = await db.users.find_one({"id": body.artist_id})
        if not u:
            raise HTTPException(404, "User not found")
        if u.get("role") not in ("artist", "agency"):
            raise HTTPException(400, "Target user must be an artist or agency")
        plan = PLANS.get(body.plan)
        if not plan:
            raise HTTPException(400, "Invalid plan")
        # Deactivate any current active row.
        await db.artist_subscriptions.update_many(
            {"artist_id": body.artist_id, "status": "active"},
            {"$set": {"status": "cancelled", "cancelled_at": utcnow(), "auto_renew": False}},
        )
        days = body.duration_days or (365 if body.billing_cycle == "yearly" else 30)
        expires = (_now() + timedelta(days=days)).isoformat()
        price = plan["price_yearly"] if body.billing_cycle == "yearly" else plan["price_monthly"]
        sub = {
            "id": new_id(),
            "artist_id": body.artist_id,
            "plan": body.plan,
            "billing_cycle": body.billing_cycle,
            "price": price,
            "status": "active",
            "payment_method": "admin_grant",
            "transaction_id": body.transaction_id or f"ADMIN-{new_id()[:8].upper()}",
            "started_at": utcnow(),
            "expires_at": expires,
            "auto_renew": False,
            "note": body.note,
            "granted_by_admin": True,
        }
        await db.artist_subscriptions.insert_one(sub)
        await db.artist_profiles.update_one(
            {"user_id": body.artist_id},
            {"$set": {"premium_badge": plan["rank"] >= 2, "plan_code": plan["code"], "plan_rank": plan["rank"]}},
        )
        await db.notifications.insert_one({
            "id": new_id(), "user_id": body.artist_id, "type": "subscription",
            "title": f"{plan['name']} granted by admin",
            "body": f"Your {plan['name']} plan is active until {expires[:10]}.",
            "read": False, "created_at": utcnow(),
        })
        return {"ok": True, "subscription": clean(sub)}

    @r.delete("/admin/subscriptions/{sid}")
    async def admin_subs_delete(sid: str, _: dict = Depends(admin_only)):
        doc = await db.artist_subscriptions.find_one({"id": sid})
        if not doc:
            raise HTTPException(404, "Not found")
        await db.artist_subscriptions.update_one(
            {"id": sid},
            {"$set": {"status": "cancelled", "cancelled_at": utcnow(), "auto_renew": False}},
        )
        # Rebuild profile denorm.
        active = await db.artist_subscriptions.find_one({"artist_id": doc["artist_id"], "status": "active"})
        plan_code = (active or {}).get("plan", "free")
        pl = PLANS.get(plan_code, PLANS["free"])
        await db.artist_profiles.update_one(
            {"user_id": doc["artist_id"]},
            {"$set": {"premium_badge": pl["rank"] >= 2, "plan_code": pl["code"], "plan_rank": pl["rank"]}},
        )
        return {"ok": True}

    @r.post("/admin/subscriptions/sweep-expired")
    async def admin_subs_sweep_expired(_: dict = Depends(admin_only)):
        """
        Idempotent sweep — marks any active subscription past its expiry as
        expired and downgrades the artist_profiles denorm. Safe to run any
        time; the background loop also calls this every 15 min but the admin
        can force a run from the UI.
        """
        now_iso = _now().isoformat()
        flipped = 0
        soon_iso = (_now() + timedelta(days=7)).isoformat()
        async for s in db.artist_subscriptions.find({"status": "active", "expires_at": {"$lt": now_iso}}):
            await db.artist_subscriptions.update_one(
                {"_id": s["_id"]},
                {"$set": {"status": "expired", "expired_at": utcnow()}},
            )
            await db.artist_profiles.update_one(
                {"user_id": s["artist_id"]},
                {"$set": {"premium_badge": False, "plan_code": "free", "plan_rank": 0}},
            )
            await db.notifications.insert_one({
                "id": new_id(), "user_id": s["artist_id"], "type": "subscription",
                "title": "Subscription expired",
                "body": "Your subscription has expired. Renew to keep premium benefits.",
                "read": False, "created_at": utcnow(),
            })
            flipped += 1
        # Also send expiry-warning notifications to anyone in the 7-day and 1-day windows
        warnings = 0
        async for s in db.artist_subscriptions.find({"status": "active", "expires_at": {"$lte": soon_iso, "$gte": now_iso}}):
            try:
                dt_exp = datetime.fromisoformat(s["expires_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            days = int((dt_exp - _now()).total_seconds() // 86400)
            marker_key = f"expiry_warn_{days}d_sent"
            if days in (7, 1) and not s.get(marker_key):
                await db.artist_subscriptions.update_one({"_id": s["_id"]}, {"$set": {marker_key: True}})
                await db.notifications.insert_one({
                    "id": new_id(), "user_id": s["artist_id"], "type": "subscription",
                    "title": f"Subscription expires in {days} day{'s' if days != 1 else ''}",
                    "body": "Renew now to avoid losing premium benefits.",
                    "read": False, "created_at": utcnow(),
                })
                warnings += 1
        return {"ok": True, "expired": flipped, "warnings": warnings}

    return r

