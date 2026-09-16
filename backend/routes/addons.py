"""
Sprint 3 — Artist Add-ons.

Artists define reusable add-ons (Extra Time, Sound System, Travel, etc.) that
customers can pick during booking. The booking captures a *snapshot* of the
add-ons (name + price at booking time) so later edits to the add-on don't
retroactively change historical bookings.

Endpoints:
  POST   /artist/addons                — create (artist)
  GET    /artist/addons                — list mine (artist)
  PATCH  /artist/addons/{id}           — update (artist owner)
  DELETE /artist/addons/{id}           — soft delete (artist owner)
  GET    /artists/{user_id}/addons     — public list for customer (only active)
"""
from __future__ import annotations
from typing import Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


class AddonBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    price: float = Field(ge=0, le=10_000_000)
    is_mandatory: bool = False
    max_quantity: int = Field(default=1, ge=1, le=100)
    gst_pct: float = Field(default=0, ge=0, le=100)
    active: bool = True


class AddonPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    price: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    is_mandatory: Optional[bool] = None
    max_quantity: Optional[int] = Field(default=None, ge=1, le=100)
    gst_pct: Optional[float] = Field(default=None, ge=0, le=100)
    active: Optional[bool] = None


def make_router(*, db, get_current_user: Callable, utcnow, new_id, clean) -> APIRouter:
    r = APIRouter()

    @r.post("/artist/addons")
    async def create_addon(body: AddonBody, user: dict = Depends(get_current_user)):
        if user["role"] not in ("artist", "agency"):
            raise HTTPException(403, "Only artists / agencies can create add-ons")
        # Iter 76.8 — Enforce the plan's `max_addons` cap. Agencies act on
        # behalf of one artist; check the acting user's plan.
        try:
            from routes.subscriptions import resolve_plan
            plan = await resolve_plan(db, user["id"])
            limit = int(plan.get("max_addons") or 3)
            current = await db.artist_addons.count_documents({
                "artist_id": user["id"], "deleted": {"$ne": True},
            })
            if current >= limit:
                raise HTTPException(
                    402,
                    f"Your {plan.get('name','Free')} plan allows up to {limit} add-ons "
                    f"(you have {current}). Upgrade your plan or remove an existing add-on to add more.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # plan lookup failure ≠ hard block

        aid = new_id()
        doc = body.model_dump()
        doc.update({
            "id": aid, "artist_id": user["id"], "created_at": utcnow(),
            "deleted": False,
        })
        await db.artist_addons.insert_one(doc)
        return clean(doc)

    @r.get("/artist/addons")
    async def list_my_addons(user: dict = Depends(get_current_user)):
        cur = db.artist_addons.find({"artist_id": user["id"], "deleted": {"$ne": True}}).sort("created_at", -1)
        return [clean(d) async for d in cur]

    @r.patch("/artist/addons/{aid}")
    async def update_addon(aid: str, body: AddonPatch, user: dict = Depends(get_current_user)):
        doc = await db.artist_addons.find_one({"id": aid})
        if not doc or doc.get("deleted"):
            raise HTTPException(404, "Add-on not found")
        if doc["artist_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "Not your add-on")
        patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if patch:
            patch["updated_at"] = utcnow()
            await db.artist_addons.update_one({"id": aid}, {"$set": patch})
        return clean(await db.artist_addons.find_one({"id": aid}))

    @r.delete("/artist/addons/{aid}")
    async def delete_addon(aid: str, user: dict = Depends(get_current_user)):
        doc = await db.artist_addons.find_one({"id": aid})
        if not doc:
            raise HTTPException(404, "Add-on not found")
        if doc["artist_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "Not your add-on")
        # Soft delete so historic bookings still resolve the snapshot names
        await db.artist_addons.update_one({"id": aid}, {"$set": {"deleted": True, "deleted_at": utcnow()}})
        return {"ok": True}

    @r.get("/artists/{user_id}/addons")
    async def public_addons(user_id: str):
        cur = db.artist_addons.find({
            "artist_id": user_id, "deleted": {"$ne": True}, "active": True,
        }).sort([("is_mandatory", -1), ("price", 1)])
        return [clean(d) async for d in cur]

    return r


# ─────────────────────────────────────────────────────────────────────────────
# Helper used by /bookings when the customer picks add-ons.
# Returns:
#   snapshots:  [{addon_id, name, description, unit_price, gst_pct, quantity,
#                 subtotal, gst_amount, total}]
#   grand_total: sum of add-on totals (price*qty + gst)
# ─────────────────────────────────────────────────────────────────────────────
async def snapshot_addons(db, artist_id: str, selections: List[dict]) -> tuple[list, float]:
    """`selections` is the raw customer payload: [{addon_id, quantity}].
    Rejects invalid IDs, unknown artists, quantity > max, or inactive add-ons.
    Also enforces that ALL mandatory add-ons for the artist are selected — even
    when the customer submits an empty selection list."""
    selections = selections or []
    ids = [s.get("addon_id") for s in selections if s.get("addon_id")]

    docs = {
        d["id"]: d
        async for d in db.artist_addons.find({
            "id": {"$in": ids},
            "artist_id": artist_id,
            "deleted": {"$ne": True},
            "active": True,
        })
    } if ids else {}

    snapshots, grand = [], 0.0
    seen = set()
    for s in selections:
        aid = s.get("addon_id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        doc = docs.get(aid)
        if not doc:
            raise HTTPException(400, f"Add-on {aid} not available")
        qty = int(s.get("quantity") or 1)
        if qty < 1 or qty > doc.get("max_quantity", 1):
            raise HTTPException(400, f"Invalid quantity for {doc['name']}")
        unit = float(doc["price"])
        subtotal = round(unit * qty, 2)
        gst_pct = float(doc.get("gst_pct") or 0)
        gst_amt = round(subtotal * gst_pct / 100, 2)
        total = round(subtotal + gst_amt, 2)
        snapshots.append({
            "addon_id": aid,
            "name": doc["name"],
            "description": doc.get("description", ""),
            "unit_price": unit,
            "gst_pct": gst_pct,
            "quantity": qty,
            "subtotal": subtotal,
            "gst_amount": gst_amt,
            "total": total,
        })
        grand += total

    # Enforce mandatory add-ons — if any active mandatory add-on wasn't selected, reject
    async for md in db.artist_addons.find({
        "artist_id": artist_id, "deleted": {"$ne": True},
        "active": True, "is_mandatory": True,
    }):
        if md["id"] not in seen:
            raise HTTPException(
                400,
                f"Mandatory add-on '{md['name']}' must be selected",
            )

    return snapshots, round(grand, 2)
