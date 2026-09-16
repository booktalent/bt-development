"""Coupons — admin CRUD + analytics + validation."""
from __future__ import annotations
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class CouponBody(BaseModel):
    code: str
    description: str = ""
    discount_type: Literal["percent", "flat"]
    discount_value: float
    max_uses: int = 1000
    per_user_limit: int = 1
    expires_at: str          # YYYY-MM-DD
    min_order: float = 0
    applies_to: str = "all"  # all/wedding/corporate/category-slug
    active: bool = True


def make_router(
    *,
    db,
    get_current_user: Callable,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
    validate_coupon: Callable,
) -> APIRouter:
    r = APIRouter()

    @r.post("/admin/coupons")
    async def admin_create_coupon(body: CouponBody, admin: dict = Depends(admin_only)):
        if await db.coupons.find_one({"code": body.code.upper()}):
            raise HTTPException(400, "Coupon code already exists")
        doc = body.model_dump()
        doc["code"] = doc["code"].upper()
        doc["id"] = new_id()
        doc["created_at"] = utcnow()
        doc["usage_count"] = 0
        doc["total_discount"] = 0.0
        await db.coupons.insert_one(doc)
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "actor_id": admin["id"], "actor_email": admin.get("email"),
                "actor_role": "admin", "action": "coupon.create", "target_type": "coupon",
                "target_id": doc["id"], "payload": {"code": doc["code"]}, "created_at": utcnow(),
            })
        except Exception:
            pass
        return clean(doc)

    @r.get("/admin/coupons")
    async def admin_list_coupons(_: dict = Depends(admin_only)):
        docs = await db.coupons.find().sort("created_at", -1).to_list(500)
        return [clean(d) for d in docs]

    @r.delete("/admin/coupons/{cid}")
    async def admin_delete_coupon(cid: str, admin: dict = Depends(admin_only)):
        await db.coupons.delete_one({"id": cid})
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "actor_id": admin["id"], "actor_email": admin.get("email"),
                "actor_role": "admin", "action": "coupon.delete", "target_type": "coupon",
                "target_id": cid, "payload": {}, "created_at": utcnow(),
            })
        except Exception:
            pass
        return {"ok": True}

    @r.get("/admin/coupons/{cid}/redemptions")
    async def admin_coupon_redemptions(cid: str, _: dict = Depends(admin_only)):
        """Per-coupon redemption ledger with user + booking details."""
        rows = await db.coupon_redemptions.find({"coupon_id": cid}).sort("created_at", -1).to_list(500)
        out = []
        for row in rows:
            row = clean(row)
            u = await db.users.find_one({"id": row["user_id"]}, {"password_hash": 0})
            b = await db.bookings.find_one({"id": row.get("booking_id")}, {"ref": 1, "status": 1, "pricing": 1, "_id": 0})
            row["user"] = clean(u) if u else None
            row["booking"] = b
            out.append(row)
        return out

    @r.get("/admin/coupons/analytics")
    async def admin_coupon_analytics(_: dict = Depends(admin_only)):
        """Aggregate per-coupon usage + revenue impact."""
        coupons = await db.coupons.find({}).sort("created_at", -1).to_list(500)
        out = []
        for c in coupons:
            c = clean(c)
            pipe = [
                {"$match": {"coupon_id": c["id"]}},
                {"$group": {
                    "_id": None,
                    "uses": {"$sum": 1},
                    "total_discount": {"$sum": "$discount_amount"},
                    "total_gmv": {"$sum": "$booking_total"},
                }},
            ]
            agg = await db.coupon_redemptions.aggregate(pipe).to_list(1)
            a = agg[0] if agg else {"uses": 0, "total_discount": 0, "total_gmv": 0}
            out.append({
                "id": c["id"], "code": c["code"], "discount_type": c["discount_type"],
                "discount_value": c["discount_value"], "active": c["active"], "expires_at": c.get("expires_at"),
                "max_uses": c.get("max_uses"), "per_user_limit": c.get("per_user_limit", 1),
                "uses": a["uses"], "remaining": max(0, c.get("max_uses", 0) - a["uses"]),
                "total_discount": round(a["total_discount"], 2),
                "total_gmv": round(a["total_gmv"], 2),
                "net_revenue": round(a["total_gmv"] - a["total_discount"], 2),
            })
        # Sort by uses desc so highest-impact coupons surface first
        out.sort(key=lambda x: x["uses"], reverse=True)
        return out

    @r.get("/coupons/validate")
    async def coupon_validate(
        code: str,
        base_amount: float = 0,
        event_type: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        c, discount = await validate_coupon(
            code, user_id=user["id"], base_amount=base_amount, event_type=event_type,
        )
        return {
            "code": c["code"], "description": c.get("description", ""),
            "discount_type": c["discount_type"], "discount_value": c["discount_value"],
            "discount_amount": discount, "min_order": c.get("min_order", 0),
            "applies_to": c.get("applies_to", "all"),
        }

    return r
