"""
Iteration 7 — Enterprise routes for BookTalent.

Adds:
- Master Data CRUD (categories, cities, event_types, languages, FAQs, CMS pages)
- Notification Templates (email/sms/whatsapp) — admin editable
- Audit Logs (every admin write is logged)
- System Settings (key-value store)
- Boost / Promotion System (admin packages + artist subscriptions)
- Advanced Search (filters, suggestions, popular, saved searches, history)
- Reports / Analytics aggregations
- Broadcast notifications
"""
from __future__ import annotations

import os
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from notification_service import dispatch as notify_dispatch, broadcast as notify_broadcast


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def clean(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


# ─────────────────────────────────────────────────────────────────
# Pydantic models (must be module-level for FastAPI body detection)
# ─────────────────────────────────────────────────────────────────
class MasterItem(BaseModel):
    name: str
    slug: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    active: bool = True
    # Iter 41 — Featured banner on category / city SEO landing pages
    hero_image: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    hero_cta_label: Optional[str] = None
    hero_cta_url: Optional[str] = None


class FAQItem(BaseModel):
    question: str
    answer: str
    category: str = "general"
    sort_order: int = 0
    active: bool = True


class CMSPage(BaseModel):
    slug: str
    title: str
    body_html: str
    meta_description: str = ""
    published: bool = True


class SettingBody(BaseModel):
    value: Any


class TemplateBody(BaseModel):
    channel: Literal["email", "sms", "whatsapp", "push", "in_app"]
    code: str
    subject: str = ""
    body: str
    active: bool = True


class BroadcastBody(BaseModel):
    audience: Literal["all", "artist", "customer", "agency", "corporate", "admin"]
    event: str
    channels: List[Literal["email", "sms", "whatsapp", "push", "in_app"]] = ["in_app"]
    title: str
    body: str


class BoostPackageBody(BaseModel):
    name: str
    type: Literal["featured_artist", "homepage_banner", "category_top", "search_priority", "premium_badge", "verified_badge", "city_featured", "trending", "recommended"]
    duration_days: int = Field(ge=1, le=400)
    price: float
    gst_pct: float = 18.0
    commission_pct: float = 0.0
    description: str = ""
    active: bool = True


class BoostPurchaseBody(BaseModel):
    package_id: str
    payment_method: Literal["easebuzz", "mock"] = "mock"
    payment_ref: Optional[str] = None


class SavedSearchBody(BaseModel):
    name: str
    query: str = ""
    filters: Dict[str, Any] = {}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")



def make_router(db, get_current_user, admin_only) -> APIRouter:
    r = APIRouter()

    # ─────────────────────────────────────────────────────────────────
    # Audit Logs (shared helper)
    # ─────────────────────────────────────────────────────────────────
    async def audit(actor: dict, action: str, target_type: str, target_id: Optional[str] = None, payload: Optional[dict] = None):
        await db.audit_logs.insert_one({
            "id": new_id(),
            "actor_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "actor_role": actor.get("role"),
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "payload": payload or {},
            "created_at": utcnow(),
        })

    @r.get("/admin/audit-logs")
    async def list_audit(limit: int = 200, action: Optional[str] = None, _: dict = Depends(admin_only)):
        q: Dict[str, Any] = {}
        if action:
            q["action"] = action
        docs = await db.audit_logs.find(q).sort("created_at", -1).to_list(limit)
        return [clean(d) for d in docs]

    # ─────────────────────────────────────────────────────────────────
    # Generic Master Data — categories, cities, event_types, languages
    # Schema: {id, slug, name, icon?, sort_order, active}
    # ─────────────────────────────────────────────────────────────────
    MASTER_COLLECTIONS = {
        "categories": "categories_master",
        "cities": "cities_master",
        "event-types": "event_types_master",
        "languages": "languages_master",
    }

    @r.get("/catalog/{entity}")
    async def catalog_public(entity: str):
        col = MASTER_COLLECTIONS.get(entity)
        if not col:
            raise HTTPException(404, "Unknown catalog")
        items = await db[col].find({"active": True}).sort("sort_order", 1).to_list(2000)
        return [clean(d) for d in items]

    @r.get("/admin/master/{entity}")
    async def admin_master_list(entity: str, _: dict = Depends(admin_only)):
        col = MASTER_COLLECTIONS.get(entity)
        if not col:
            raise HTTPException(404, "Unknown master entity")
        items = await db[col].find({}).sort("sort_order", 1).to_list(5000)
        return [clean(d) for d in items]

    @r.post("/admin/master/{entity}")
    async def admin_master_create(entity: str, body: MasterItem, user: dict = Depends(admin_only)):
        col = MASTER_COLLECTIONS.get(entity)
        if not col:
            raise HTTPException(404, "Unknown master entity")
        slug = body.slug or slugify(body.name)
        if await db[col].find_one({"slug": slug}):
            raise HTTPException(400, "Slug already exists")
        doc = {
            "id": new_id(),
            "slug": slug,
            "name": body.name,
            "icon": body.icon,
            "sort_order": body.sort_order,
            "active": body.active,
            "hero_image": body.hero_image or "",
            "hero_title": body.hero_title or "",
            "hero_subtitle": body.hero_subtitle or "",
            "hero_cta_label": body.hero_cta_label or "",
            "hero_cta_url": body.hero_cta_url or "",
            "created_at": utcnow(),
        }
        await db[col].insert_one(doc)
        await audit(user, "master.create", entity, doc["id"], body.dict())
        return clean(doc)

    @r.put("/admin/master/{entity}/{item_id}")
    async def admin_master_update(entity: str, item_id: str, body: MasterItem, user: dict = Depends(admin_only)):
        col = MASTER_COLLECTIONS.get(entity)
        if not col:
            raise HTTPException(404, "Unknown master entity")
        updates = {k: v for k, v in body.dict().items() if v is not None}
        updates["updated_at"] = utcnow()
        # Only regenerate the slug when the admin explicitly passes a new
        # slug — do NOT auto-derive from name on update or we'd silently
        # break every existing public URL for this row.
        if not body.slug:
            updates.pop("slug", None)
        await db[col].update_one({"id": item_id}, {"$set": updates})
        await audit(user, "master.update", entity, item_id, updates)
        doc = await db[col].find_one({"id": item_id})
        return clean(doc)

    @r.delete("/admin/master/{entity}/{item_id}")
    async def admin_master_delete(entity: str, item_id: str, user: dict = Depends(admin_only)):
        col = MASTER_COLLECTIONS.get(entity)
        if not col:
            raise HTTPException(404, "Unknown master entity")
        await db[col].delete_one({"id": item_id})
        await audit(user, "master.delete", entity, item_id)
        return {"ok": True}

    # ─────────────────────────────────────────────────────────────────
    # FAQ Master
    # ─────────────────────────────────────────────────────────────────
    @r.get("/faqs")
    async def faqs_public(category: Optional[str] = None):
        q: Dict[str, Any] = {"active": True}
        if category:
            q["category"] = category
        items = await db.faqs.find(q).sort("sort_order", 1).to_list(500)
        return [clean(d) for d in items]

    @r.get("/admin/faqs")
    async def admin_faqs_list(_: dict = Depends(admin_only)):
        items = await db.faqs.find({}).sort("sort_order", 1).to_list(2000)
        return [clean(d) for d in items]

    @r.post("/admin/faqs")
    async def admin_faq_create(body: FAQItem, user: dict = Depends(admin_only)):
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
        await db.faqs.insert_one(doc)
        await audit(user, "faq.create", "faq", doc["id"], body.dict())
        return clean(doc)

    @r.put("/admin/faqs/{fid}")
    async def admin_faq_update(fid: str, body: FAQItem, user: dict = Depends(admin_only)):
        await db.faqs.update_one({"id": fid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        await audit(user, "faq.update", "faq", fid, body.dict())
        return clean(await db.faqs.find_one({"id": fid}))

    @r.delete("/admin/faqs/{fid}")
    async def admin_faq_delete(fid: str, user: dict = Depends(admin_only)):
        await db.faqs.delete_one({"id": fid})
        await audit(user, "faq.delete", "faq", fid)
        return {"ok": True}

    # ─────────────────────────────────────────────────────────────────
    # CMS Pages (About, Terms, Privacy, etc.)
    # ─────────────────────────────────────────────────────────────────
    @r.get("/cms/{slug}")
    async def cms_get(slug: str):
        page = await db.cms_pages.find_one({"slug": slug, "published": True})
        if not page:
            raise HTTPException(404, "Page not found")
        return clean(page)

    @r.get("/admin/cms")
    async def admin_cms_list(_: dict = Depends(admin_only)):
        items = await db.cms_pages.find({}).sort("slug", 1).to_list(500)
        return [clean(d) for d in items]

    @r.post("/admin/cms")
    async def admin_cms_create(body: CMSPage, user: dict = Depends(admin_only)):
        if await db.cms_pages.find_one({"slug": body.slug}):
            raise HTTPException(400, "Slug already exists")
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
        await db.cms_pages.insert_one(doc)
        await audit(user, "cms.create", "cms_page", doc["id"], body.dict())
        return clean(doc)

    @r.put("/admin/cms/{pid}")
    async def admin_cms_update(pid: str, body: CMSPage, user: dict = Depends(admin_only)):
        await db.cms_pages.update_one({"id": pid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        await audit(user, "cms.update", "cms_page", pid, body.dict())
        return clean(await db.cms_pages.find_one({"id": pid}))

    @r.delete("/admin/cms/{pid}")
    async def admin_cms_delete(pid: str, user: dict = Depends(admin_only)):
        await db.cms_pages.delete_one({"id": pid})
        await audit(user, "cms.delete", "cms_page", pid)
        return {"ok": True}

    # ─────────────────────────────────────────────────────────────────
    # System Settings (key-value, e.g. platform_fee_pct, gst_pct)
    # ─────────────────────────────────────────────────────────────────
    # Whitelist of settings safe to expose to unauthenticated callers
    # (only display strings, no secrets).
    PUBLIC_SETTING_KEYS = {
        "outstation_notice",
        "booking_fee_note",
        "outstation_clause",
        "city_aliases",
        "platform_fee_pct",
        "gst_pct",
        "support_email",
        "support_phone",
        # Iter 40 — Featured banner for the /blog list page
        "blog_hero_image",
        "blog_hero_title",
        "blog_hero_subtitle",
        "blog_hero_cta_label",
        "blog_hero_cta_url",
    }

    @r.get("/settings/public")
    async def public_settings():
        """Public read-only settings map. Used by the customer-facing UI
        (BookingFlow, contract preview) so admins can tune copy without
        redeploying."""
        docs = await db.system_settings.find({"key": {"$in": list(PUBLIC_SETTING_KEYS)}}).to_list(50)
        return {d["key"]: d.get("value") for d in docs}

    @r.get("/admin/settings")
    async def admin_settings_list(_: dict = Depends(admin_only)):
        items = await db.system_settings.find({}).sort("key", 1).to_list(500)
        return [clean(d) for d in items]

    @r.put("/admin/settings/{key}")
    async def admin_settings_set(key: str, body: SettingBody, user: dict = Depends(admin_only)):
        await db.system_settings.update_one(
            {"key": key},
            {"$set": {"key": key, "value": body.value, "updated_at": utcnow()}},
            upsert=True,
        )
        await audit(user, "settings.update", "system_settings", key, {"value": body.value})
        doc = await db.system_settings.find_one({"key": key})
        return clean(doc)

    # ─────────────────────────────────────────────────────────────────
    # Notification Templates (email / sms / whatsapp / push / in_app)
    # ─────────────────────────────────────────────────────────────────
    @r.get("/admin/templates")
    async def admin_templates_list(channel: Optional[str] = None, _: dict = Depends(admin_only)):
        q: Dict[str, Any] = {}
        if channel:
            q["channel"] = channel
        items = await db.notification_templates.find(q).sort([("channel", 1), ("code", 1)]).to_list(2000)
        return [clean(d) for d in items]

    @r.post("/admin/templates")
    async def admin_template_upsert(body: TemplateBody, user: dict = Depends(admin_only)):
        existing = await db.notification_templates.find_one({"channel": body.channel, "code": body.code})
        if existing:
            await db.notification_templates.update_one(
                {"id": existing["id"]},
                {"$set": {**body.dict(), "updated_at": utcnow()}},
            )
            doc = await db.notification_templates.find_one({"id": existing["id"]})
            await audit(user, "template.update", "template", existing["id"], body.dict())
        else:
            doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
            await db.notification_templates.insert_one(doc)
            await audit(user, "template.create", "template", doc["id"], body.dict())
        return clean(doc)

    @r.delete("/admin/templates/{tid}")
    async def admin_template_delete(tid: str, user: dict = Depends(admin_only)):
        await db.notification_templates.delete_one({"id": tid})
        await audit(user, "template.delete", "template", tid)
        return {"ok": True}

    # ─────────────────────────────────────────────────────────────────
    # Broadcast Notifications
    # ─────────────────────────────────────────────────────────────────
    @r.post("/admin/notifications/broadcast")
    async def admin_broadcast(body: BroadcastBody, user: dict = Depends(admin_only)):
        result = await notify_broadcast(
            db,
            audience=body.audience,
            event=body.event,
            channels=body.channels,
            ctx={"title": body.title, "body": body.body},
        )
        await audit(user, "notification.broadcast", "broadcast", None, body.dict())
        return {"ok": True, **result}

    @r.get("/admin/notifications/log")
    async def admin_notification_log(limit: int = 200, event: Optional[str] = None, _: dict = Depends(admin_only)):
        q: Dict[str, Any] = {}
        if event:
            q["event"] = event
        items = await db.notifications_log.find(q).sort("created_at", -1).to_list(limit)
        return [clean(d) for d in items]

    # ─────────────────────────────────────────────────────────────────
    # BOOST / Promotion System
    # ─────────────────────────────────────────────────────────────────
    @r.get("/boost/packages")
    async def boost_packages_public():
        items = await db.boost_packages.find({"active": True}).sort([("type", 1), ("duration_days", 1)]).to_list(500)
        return [clean(d) for d in items]

    @r.get("/admin/boost/packages")
    async def admin_boost_packages(_: dict = Depends(admin_only)):
        items = await db.boost_packages.find({}).sort([("type", 1), ("duration_days", 1)]).to_list(500)
        return [clean(d) for d in items]

    @r.post("/admin/boost/packages")
    async def admin_boost_pkg_create(body: BoostPackageBody, user: dict = Depends(admin_only)):
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
        await db.boost_packages.insert_one(doc)
        await audit(user, "boost_package.create", "boost_package", doc["id"], body.dict())
        return clean(doc)

    @r.put("/admin/boost/packages/{pid}")
    async def admin_boost_pkg_update(pid: str, body: BoostPackageBody, user: dict = Depends(admin_only)):
        await db.boost_packages.update_one({"id": pid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        await audit(user, "boost_package.update", "boost_package", pid, body.dict())
        return clean(await db.boost_packages.find_one({"id": pid}))

    @r.delete("/admin/boost/packages/{pid}")
    async def admin_boost_pkg_delete(pid: str, user: dict = Depends(admin_only)):
        await db.boost_packages.delete_one({"id": pid})
        await audit(user, "boost_package.delete", "boost_package", pid)
        return {"ok": True}

    async def _activate_boost(user_id: str, pkg: dict, price: float,
                              payment_method: str = "easebuzz",
                              payment_ref: Optional[str] = None) -> dict:
        """Activate a boost package for a user. Called by /boost/purchase (mock)
        AND by the Easebuzz callback finaliser after paid checkout completes."""
        gst_amount = round(pkg["price"] * pkg.get("gst_pct", 18) / 100, 2)
        commission = round(pkg["price"] * pkg.get("commission_pct", 0) / 100, 2)
        total = round(pkg["price"] + gst_amount, 2)
        starts_at = datetime.now(timezone.utc)
        expires_at = starts_at + timedelta(days=pkg["duration_days"])
        sub = {
            "id": new_id(),
            "artist_id": user_id,
            "package_id": pkg["id"],
            "package_snapshot": {"name": pkg["name"], "type": pkg["type"], "duration_days": pkg["duration_days"]},
            "type": pkg["type"], "price": pkg["price"],
            "gst_amount": gst_amount, "commission": commission, "total": total,
            "payment_method": payment_method,
            "payment_ref": payment_ref or f"AUTO-{new_id()[:8]}",
            "status": "active",
            "starts_at": starts_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "created_at": utcnow(),
        }
        await db.boost_subscriptions.insert_one(sub)
        profile_updates: Dict[str, Any] = {"updated_at": utcnow()}
        t = pkg["type"]
        if t in ("featured_artist", "city_featured", "homepage_banner"):
            profile_updates["is_featured"] = True
        if t == "premium_badge": profile_updates["premium_badge"] = True
        if t == "verified_badge": profile_updates["verified_badge"] = True
        if t == "trending": profile_updates["is_trending"] = True
        if t == "recommended": profile_updates["is_recommended"] = True
        profile_updates["boost_rank"] = max(
            (await db.artist_profiles.find_one({"user_id": user_id}) or {}).get("boost_rank", 0),
            {"search_priority": 100, "category_top": 90, "homepage_banner": 80,
             "featured_artist": 70, "trending": 60, "recommended": 50,
             "city_featured": 40, "premium_badge": 20, "verified_badge": 10}.get(t, 5),
        )
        profile_updates["boost_expires_at"] = expires_at.isoformat()
        await db.artist_profiles.update_one({"user_id": user_id}, {"$set": profile_updates})
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1, "first_name": 1})
        await notify_dispatch(
            db, user_id=user_id, event="boost.activated",
            channels=["in_app", "email"],
            ctx={"title": f"Boost activated: {pkg['name']}",
                 "body": f"Your {pkg['name']} package is now active for {pkg['duration_days']} days.",
                 "package": pkg["name"]},
            email=(u or {}).get("email"),
        )
        return sub

    r._activate_boost = _activate_boost  # type: ignore[attr-defined]

    @r.post("/boost/purchase")
    async def boost_purchase(body: BoostPurchaseBody, user: dict = Depends(get_current_user)):
        if user["role"] != "artist":
            raise HTTPException(403, "Only artists can purchase boost packages")
        pkg = await db.boost_packages.find_one({"id": body.package_id, "active": True})
        if not pkg:
            raise HTTPException(404, "Package not found or inactive")
        # Paid boosts must go through Easebuzz — reject direct activation to
        # prevent bypass. Frontend should call POST /api/boost/easebuzz/init.
        if body.payment_method != "mock" and not body.payment_ref:
            raise HTTPException(
                402,
                "Paid boosts require a completed payment. Use POST /api/boost/easebuzz/init.",
            )
        sub = await _activate_boost(user["id"], pkg, pkg["price"],
                                    payment_method=body.payment_method,
                                    payment_ref=body.payment_ref)
        gst_amount = sub["gst_amount"]; commission = sub["commission"]; total = sub["total"]
        expires_at = datetime.fromisoformat(sub["expires_at"])

        return {"ok": True, "subscription": clean(sub), "mock": body.payment_method == "mock"}

    @r.get("/boost/mine")
    async def boost_mine(user: dict = Depends(get_current_user)):
        subs = await db.boost_subscriptions.find({"artist_id": user["id"]}).sort("created_at", -1).to_list(200)
        # Auto-expire
        now = datetime.now(timezone.utc)
        any_expired = False
        for s in subs:
            try:
                exp = datetime.fromisoformat(s["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if s["status"] == "active" and exp < now:
                    await db.boost_subscriptions.update_one({"id": s["id"]}, {"$set": {"status": "expired"}})
                    s["status"] = "expired"
                    any_expired = True
            except Exception:
                pass
        # If we expired some, recompute the artist's profile flags & boost_rank
        if any_expired:
            active = [s for s in subs if s["status"] == "active"]
            rank_map = {"search_priority": 100, "category_top": 90, "homepage_banner": 80, "featured_artist": 70, "trending": 60, "recommended": 50, "city_featured": 40, "premium_badge": 20, "verified_badge": 10}
            new_rank = max((rank_map.get(s["type"], 0) for s in active), default=0)
            updates = {
                "boost_rank": new_rank,
                "is_featured": any(s["type"] in ("featured_artist", "city_featured", "homepage_banner") for s in active),
                "is_trending": any(s["type"] == "trending" for s in active),
                "is_recommended": any(s["type"] == "recommended" for s in active),
                "premium_badge": any(s["type"] == "premium_badge" for s in active),
                "verified_badge": any(s["type"] == "verified_badge" for s in active),
            }
            await db.artist_profiles.update_one({"user_id": user["id"]}, {"$set": updates})
        return [clean(s) for s in subs]

    @r.get("/admin/boost/subscriptions")
    async def admin_boost_subs(status: Optional[str] = None, _: dict = Depends(admin_only)):
        q: Dict[str, Any] = {}
        if status:
            q["status"] = status
        subs = await db.boost_subscriptions.find(q).sort("created_at", -1).to_list(1000)
        out = []
        for s in subs:
            s = clean(s)
            u = await db.users.find_one({"id": s["artist_id"]})
            s["artist"] = {"id": u["id"], "email": u.get("email"), "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()} if u else None
            out.append(s)
        return out

    @r.post("/admin/boost/{sub_id}/cancel")
    async def admin_boost_cancel(sub_id: str, user: dict = Depends(admin_only)):
        sub = await db.boost_subscriptions.find_one({"id": sub_id})
        if not sub:
            raise HTTPException(404, "Subscription not found")
        await db.boost_subscriptions.update_one({"id": sub_id}, {"$set": {"status": "cancelled", "cancelled_at": utcnow()}})
        # Revert flags only if no other active sub
        active_count = await db.boost_subscriptions.count_documents({"artist_id": sub["artist_id"], "status": "active", "id": {"$ne": sub_id}})
        if active_count == 0:
            await db.artist_profiles.update_one(
                {"user_id": sub["artist_id"]},
                {"$set": {"is_featured": False, "is_trending": False, "is_recommended": False, "boost_rank": 0}},
            )
        await audit(user, "boost.cancel", "boost_subscription", sub_id)
        await notify_dispatch(db, user_id=sub["artist_id"], event="boost.cancelled", channels=["in_app", "email"], ctx={
            "title": "Boost cancelled by admin",
            "body": f"Your boost subscription ({sub['package_snapshot']['name']}) has been cancelled.",
        })
        return {"ok": True}

    @r.post("/admin/boost/manual-assign")
    async def admin_boost_manual(body: BoostPurchaseBody, target_artist_id: str = Query(...), user: dict = Depends(admin_only)):
        pkg = await db.boost_packages.find_one({"id": body.package_id})
        if not pkg:
            raise HTTPException(404, "Package not found")
        starts_at = datetime.now(timezone.utc)
        expires_at = starts_at + timedelta(days=pkg["duration_days"])
        sub = {
            "id": new_id(),
            "artist_id": target_artist_id,
            "package_id": pkg["id"],
            "package_snapshot": {"name": pkg["name"], "type": pkg["type"], "duration_days": pkg["duration_days"]},
            "type": pkg["type"],
            "price": 0,
            "gst_amount": 0,
            "commission": 0,
            "total": 0,
            "payment_method": "manual",
            "payment_ref": f"ADMIN-{new_id()[:8]}",
            "status": "active",
            "starts_at": starts_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "created_at": utcnow(),
            "assigned_by": user["id"],
        }
        await db.boost_subscriptions.insert_one(sub)
        await db.artist_profiles.update_one({"user_id": target_artist_id}, {"$set": {
            "is_featured": pkg["type"] in ("featured_artist", "city_featured", "homepage_banner"),
            "boost_expires_at": expires_at.isoformat(),
        }})
        await audit(user, "boost.manual_assign", "boost_subscription", sub["id"], {"target": target_artist_id})
        return clean(sub)

    # ─────────────────────────────────────────────────────────────────
    # ADVANCED SEARCH
    # ─────────────────────────────────────────────────────────────────
    @r.get("/search/artists")
    async def search_artists(
        q: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        language: Optional[str] = None,
        gender: Optional[str] = None,
        min_rating: Optional[float] = None,
        event_type: Optional[str] = None,
        featured_only: bool = False,
        verified_only: bool = False,
        premium_only: bool = False,
        instant_available: bool = False,
        min_experience: Optional[int] = None,
        sort: str = "relevance",  # relevance | price_asc | price_desc | rating | newest
        page: int = 1,
        limit: int = 24,
        request: Request = None,
    ):
        # Iter 99 — LIVE-only public gate. Only artists who completed
        # KYC → T&C acceptance → Agreement generation → went live are
        # discoverable. Suspended profiles also hidden.
        filt: Dict[str, Any] = {
            "suspended": {"$ne": True},
            "kyc_status": "live",
        }
        if category:
            # Iter 62.6 — Dropdown sends catalog labels like "Singers & Vocalists"
            # or slugs like "singer" but profiles store free-text ("Bollywood
            # Vocalist", "Ghazal Singer", "DJ / Music Producer"). Map the
            # incoming label/slug to a set of keywords and match ANY of them.
            _KEYWORDS = {
                "singer": ["singer", "vocalist"],
                "singers": ["singer", "vocalist"],
                "vocalist": ["singer", "vocalist"],
                "singers & vocalists": ["singer", "vocalist"],
                "dj": ["dj", "music producer"],
                "djs": ["dj", "music producer"],
                "djs & music": ["dj", "music producer"],
                "comedian": ["comed"],
                "comedians": ["comed"],
                "stand-up": ["comed", "stand-up"],
                "anchor": ["anchor", "emcee", "mc"],
                "anchor / mc": ["anchor", "emcee", "mc"],
                "band": ["band"],
                "dancer": ["dance", "choreograph"],
                "instrumentalist": ["instrument", "guitarist", "flutist", "tabla", "sitar"],
                "magician": ["magic", "illusion"],
                "speaker": ["speaker", "motivational"],
            }
            key = (category or "").strip().lower()
            words = _KEYWORDS.get(key)
            if not words:
                # Fallback: split on non-word chars and drop common connectors.
                raw = re.split(r"[^\w]+", key)
                words = [w for w in raw if w and w not in ("and", "or", "the", "of", "a", "an", "&")]
                if not words:
                    words = [key]
            regex = "|".join(re.escape(w) for w in words)
            filt["category"] = {"$regex": regex, "$options": "i"}
        if city:
            filt["city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}
        if language:
            filt["languages"] = language
        if gender:
            filt["gender"] = gender
        if event_type:
            filt["event_types"] = event_type
        if min_rating is not None:
            filt["rating_avg"] = {"$gte": min_rating}
        if min_price is not None or max_price is not None:
            # Iter 62.6 — Prices live in the `packages` collection, not on
            # artist_profiles. Query package prices first and restrict to the
            # matching artist_ids so pagination + total stay correct.
            pkg_q: Dict[str, Any] = {}
            if min_price is not None:
                pkg_q["price"] = {"$gte": float(min_price)}
            if max_price is not None:
                pkg_q.setdefault("price", {})["$lte"] = float(max_price)
            matching_ids = await db.packages.distinct("artist_id", pkg_q)
            filt["user_id"] = {"$in": matching_ids or ["__none__"]}
        if featured_only:
            filt["is_featured"] = True
        if verified_only:
            # Iter 99 — "verified" now means fully live (KYC + T&C + agreement).
            # Since the base filter already enforces kyc_status=="live", this is
            # effectively a no-op but kept for API compatibility.
            filt["kyc_status"] = "live"
        if premium_only:
            filt["premium_badge"] = True
        if instant_available:
            filt["available_for_booking"] = True
        if min_experience is not None:
            filt["experience_years"] = {"$gte": min_experience}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            filt["$or"] = [{"stage_name": rx}, {"bio": rx}, {"tagline": rx}, {"category": rx}, {"city": rx}]

        # Save search history (anonymous if no token)
        try:
            uid = None
            if request is not None:
                from jwt import decode as jwt_decode
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    try:
                        payload = jwt_decode(auth[7:], os.environ["JWT_SECRET"], algorithms=["HS256"])
                        uid = payload.get("sub")
                    except Exception:
                        pass
            if q:
                await db.search_history.insert_one({
                    "id": new_id(),
                    "user_id": uid,
                    "query": q,
                    "filters": {k: v for k, v in filt.items() if k != "$or"},
                    "created_at": utcnow(),
                })
        except Exception:
            pass

        sort_spec: List[tuple] = []
        if sort == "price_asc":
            sort_spec = [("plan_rank", -1), ("boost_rank", -1), ("base_price", 1)]
        elif sort == "price_desc":
            sort_spec = [("plan_rank", -1), ("boost_rank", -1), ("base_price", -1)]
        elif sort == "rating":
            sort_spec = [("plan_rank", -1), ("boost_rank", -1), ("rating_avg", -1)]
        elif sort == "newest":
            sort_spec = [("plan_rank", -1), ("boost_rank", -1), ("created_at", -1)]
        else:
            sort_spec = [("plan_rank", -1), ("boost_rank", -1), ("is_featured", -1), ("rating_avg", -1)]

        skip = max(0, (page - 1) * limit)
        cur = db.artist_profiles.find(filt).sort(sort_spec).skip(skip).limit(limit)
        total = await db.artist_profiles.count_documents(filt)
        items = await cur.to_list(limit)
        # Enrich with starting_price + gallery_thumbs for the rotating card
        out_items = []
        for p in items:
            p = clean(p)
            pkgs = await db.packages.find({"artist_id": p["user_id"]}).to_list(20)
            p["starting_price"] = min((float(pp.get("price", 0)) for pp in pkgs), default=None)
            gallery = await db.media.find(
                {"user_id": p["user_id"], "type": "gallery"},
                {"data": 0, "thumb": 0},
            ).sort([("is_featured", -1), ("order", 1)]).limit(8).to_list(8)
            p["gallery_thumbs"] = [{"id": g["id"], "is_featured": g.get("is_featured", False)} for g in gallery]
            out_items.append(p)
        return {"items": out_items, "total": total, "page": page, "limit": limit, "pages": (total + limit - 1) // limit if limit else 1}

    @r.get("/search/suggestions")
    async def search_suggestions(q: str = Query(min_length=1)):
        if not q:
            return []
        rx = {"$regex": re.escape(q), "$options": "i"}
        names = await db.artist_profiles.find({"stage_name": rx}, {"stage_name": 1, "category": 1, "city": 1, "user_id": 1}).limit(8).to_list(8)
        cats = await db.categories_master.find({"name": rx}, {"name": 1, "slug": 1}).limit(4).to_list(4)
        cities = await db.cities_master.find({"name": rx}, {"name": 1, "slug": 1}).limit(4).to_list(4)
        return {
            "artists": [{"id": n.get("user_id"), "label": n.get("stage_name"), "sub": f"{n.get('category', '')} · {n.get('city', '')}"} for n in names],
            "categories": [{"slug": c.get("slug"), "label": c.get("name")} for c in cats],
            "cities": [{"slug": c.get("slug"), "label": c.get("name")} for c in cities],
        }

    @r.get("/search/popular")
    async def search_popular(limit: int = 10):
        # Aggregate top queries from last 30 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pipe = [
            {"$match": {"created_at": {"$gte": cutoff}, "query": {"$ne": None}}},
            {"$group": {"_id": "$query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        rows = await db.search_history.aggregate(pipe).to_list(limit)
        return [{"query": r["_id"], "count": r["count"]} for r in rows]

    # ─────────────────────────────────────────────────────────────────
    # Saved Searches
    # ─────────────────────────────────────────────────────────────────
    @r.post("/search/saved")
    async def saved_search_create(body: SavedSearchBody, user: dict = Depends(get_current_user)):
        doc = {"id": new_id(), "user_id": user["id"], **body.dict(), "created_at": utcnow()}
        await db.saved_searches.insert_one(doc)
        return clean(doc)

    @r.get("/search/saved")
    async def saved_search_list(user: dict = Depends(get_current_user)):
        items = await db.saved_searches.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
        return [clean(d) for d in items]

    @r.delete("/search/saved/{sid}")
    async def saved_search_delete(sid: str, user: dict = Depends(get_current_user)):
        await db.saved_searches.delete_one({"id": sid, "user_id": user["id"]})
        return {"ok": True}

    @r.get("/search/history")
    async def search_history_mine(user: dict = Depends(get_current_user), limit: int = 30):
        items = await db.search_history.find({"user_id": user["id"]}).sort("created_at", -1).limit(limit).to_list(limit)
        return [clean(d) for d in items]

    # ─────────────────────────────────────────────────────────────────
    # Reports & Analytics
    # ─────────────────────────────────────────────────────────────────
    @r.get("/admin/reports/revenue")
    async def revenue_report(days: int = 30, _: dict = Depends(admin_only)):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        total_gmv = 0.0        # Marketplace volume (artist fees flowing through bookings)
        platform_rev = 0.0     # Net BookTalent revenue (platform_fee only)
        gst_collected = 0.0    # 18% GST on platform_fee
        booking_count = 0
        async for b in db.bookings.find({"created_at": {"$gte": cutoff}, "status": {"$in": ["confirmed", "completed", "reviewed"]}}):
            p = b.get("pricing", {}) or {}
            total_gmv += float(p.get("artist_fee", p.get("package_fee", 0) + p.get("addons_total", 0)))
            platform_rev += float(p.get("platform_fee", 0))
            gst_collected += float(p.get("gst", 0))
            booking_count += 1
        boost_rev = 0.0
        async for s in db.boost_subscriptions.find({"created_at": {"$gte": cutoff}, "status": {"$ne": "manual"}}):
            boost_rev += float(s.get("total", 0))
        return {
            "period_days": days,
            "gmv": round(total_gmv, 2),                              # informational — NOT BookTalent revenue
            "platform_revenue": round(platform_rev, 2),              # net platform fees earned
            "gst_collected": round(gst_collected, 2),                # GST collected on behalf of govt
            "boost_revenue": round(boost_rev, 2),
            "net_revenue": round(platform_rev + boost_rev, 2),        # BookTalent's actual revenue ex-GST
            "total_collected": round(platform_rev + gst_collected + boost_rev, 2),
            "bookings": booking_count,
        }

    @r.get("/admin/reports/top-artists")
    async def top_artists(limit: int = 10, _: dict = Depends(admin_only)):
        # Python-side aggregate so we can fall back to (package_fee + addons_total)
        # for legacy bookings that have no `artist_fee` field.
        agg: Dict[str, Dict[str, float]] = {}
        async for b in db.bookings.find({"status": {"$in": ["confirmed", "completed", "reviewed"]}}, {"artist_id": 1, "pricing": 1, "_id": 0}):
            p = b.get("pricing", {}) or {}
            fee = float(p.get("artist_fee", p.get("package_fee", 0) + p.get("addons_total", 0)))
            row = agg.setdefault(b["artist_id"], {"bookings": 0, "revenue": 0.0})
            row["bookings"] += 1
            row["revenue"] += fee
        rows = sorted(agg.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:limit]
        out = []
        for aid, row in rows:
            prof = await db.artist_profiles.find_one({"user_id": aid}, {"stage_name": 1, "category": 1, "city": 1, "user_id": 1})
            if prof:
                out.append({
                    "artist_id": aid,
                    "stage_name": prof.get("stage_name"),
                    "category": prof.get("category"),
                    "city": prof.get("city"),
                    "bookings": row["bookings"],
                    "revenue": row["revenue"],
                })
        return out

    # ─────────────────────────────────────────────────────────────────
    # Seeder (idempotent) — creates default master data on startup
    # ─────────────────────────────────────────────────────────────────
    async def seed_iter7():
        # Categories
        cats = [
            ("singer", "Singers & Vocalists", "🎤", 1),
            ("dj", "DJs & Music", "🎧", 2),
            ("comedian", "Comedians", "🎭", 3),
            ("dancer", "Dancers", "💃", 4),
            ("anchor", "Anchors / Emcees", "🎙️", 5),
            ("band", "Live Bands", "🎸", 6),
            ("magician", "Magicians", "🎩", 7),
            ("folk", "Folk Artists", "🪕", 8),
        ]
        for slug, name, icon, order in cats:
            if not await db.categories_master.find_one({"slug": slug}):
                await db.categories_master.insert_one({"id": new_id(), "slug": slug, "name": name, "icon": icon, "sort_order": order, "active": True, "created_at": utcnow()})

        # Cities
        for i, c in enumerate(["Mumbai", "Delhi NCR", "Bangalore", "Chennai", "Hyderabad", "Kolkata", "Pune", "Jaipur", "Ahmedabad", "Goa"]):
            slug = slugify(c)
            if not await db.cities_master.find_one({"slug": slug}):
                await db.cities_master.insert_one({"id": new_id(), "slug": slug, "name": c, "sort_order": i, "active": True, "created_at": utcnow()})

        # Event types
        for i, e in enumerate(["Wedding", "Corporate", "Birthday", "Private Party", "Engagement", "Anniversary", "Concert", "Festival"]):
            slug = slugify(e)
            if not await db.event_types_master.find_one({"slug": slug}):
                await db.event_types_master.insert_one({"id": new_id(), "slug": slug, "name": e, "sort_order": i, "active": True, "created_at": utcnow()})

        # Languages
        for i, l in enumerate(["Hindi", "English", "Punjabi", "Tamil", "Telugu", "Marathi", "Bengali", "Gujarati", "Kannada", "Malayalam"]):
            slug = slugify(l)
            if not await db.languages_master.find_one({"slug": slug}):
                await db.languages_master.insert_one({"id": new_id(), "slug": slug, "name": l, "sort_order": i, "active": True, "created_at": utcnow()})

        # Default Boost packages
        boost_seed = [
            ("Featured Artist · 7 days", "featured_artist", 7, 1499),
            ("Featured Artist · 30 days", "featured_artist", 30, 4999),
            ("Homepage Banner · 7 days", "homepage_banner", 7, 2999),
            ("Homepage Banner · 30 days", "homepage_banner", 30, 9999),
            ("Category Top · 15 days", "category_top", 15, 2499),
            ("Search Priority · 30 days", "search_priority", 30, 5999),
            ("Premium Badge · 90 days", "premium_badge", 90, 1999),
            ("Verified Badge · 365 days", "verified_badge", 365, 999),
            ("City Featured · 30 days", "city_featured", 30, 3499),
            ("Trending · 7 days", "trending", 7, 1299),
            ("Recommended · 15 days", "recommended", 15, 1799),
        ]
        for name, t, days, price in boost_seed:
            if not await db.boost_packages.find_one({"name": name}):
                await db.boost_packages.insert_one({
                    "id": new_id(), "name": name, "type": t,
                    "duration_days": days, "price": price,
                    "gst_pct": 18.0, "commission_pct": 0.0,
                    "description": f"Boost your profile with {name}",
                    "active": True, "created_at": utcnow(),
                })

        # Default FAQs
        faq_seed = [
            ("How do I book an artist?", "Search for the artist, pick a package, choose your event date, complete the payment and the artist will confirm within 24 hours.", "booking"),
            ("How does payment work?", "BookTalent is a lead-generation marketplace. On booking, you pay only the Platform Service Fee (5% of the artist fee) plus 18% GST to BookTalent. The Artist Performance Fee is paid directly by you to the artist as per the signed agreement.", "payment"),
            ("What is the cancellation policy?", "Cancellations 7 days before the event are refunded 90%. 3-7 days = 50%. Within 72 hours = no refund.", "cancellation"),
            ("How do I become an artist on BookTalent?", "Sign up as 'Artist', complete onboarding, upload your portfolio and submit KYC. Approval takes 24-48 hours.", "artist"),
        ]
        for q, a, cat in faq_seed:
            existing = await db.faqs.find_one({"question": q})
            if not existing:
                await db.faqs.insert_one({"id": new_id(), "question": q, "answer": a, "category": cat, "sort_order": 0, "active": True, "created_at": utcnow()})
            elif "escrow" in (existing.get("answer") or "").lower():
                # Iter 38 pivot: silently correct any legacy escrow copy.
                await db.faqs.update_one({"id": existing["id"]}, {"$set": {"answer": a}})

        # Default CMS pages
        cms_seed = [
            ("about", "About BookTalent", "<p>BookTalent is India's premium marketplace for booking live performers.</p>"),
            ("terms", "Terms of Service", "<p>By using BookTalent you agree to our terms.</p>"),
            ("privacy", "Privacy Policy", "<p>We respect your privacy. Read our policy.</p>"),
        ]
        for slug, title, html in cms_seed:
            if not await db.cms_pages.find_one({"slug": slug}):
                await db.cms_pages.insert_one({"id": new_id(), "slug": slug, "title": title, "body_html": html, "meta_description": title, "published": True, "created_at": utcnow()})

        # Default notification templates
        tpl_seed = [
            ("email", "booking.created", "New booking request", "You have received a new booking request from {customer_name} for {event_date}. Review and respond on your dashboard."),
            ("email", "booking.confirmed", "Your booking is confirmed!", "Your booking with {artist_name} for {event_date} is confirmed. Reference: {ref}."),
            ("email", "booking.rejected", "Booking declined", "Unfortunately {artist_name} could not accept your booking for {event_date}. You can search for similar artists."),
            ("email", "payment.success", "Payment received", "We've received your payment of ₹{amount}. Your booking is being processed."),
            ("email", "boost.activated", "Boost package activated", "Your {package} boost is now live and expires on {expires_at}."),
            ("in_app", "booking.created", "New booking request", "Booking from {customer_name} for {event_date}"),
            ("in_app", "booking.confirmed", "Booking confirmed", "Your booking with {artist_name} is confirmed"),
        ]
        for ch, code, sub, body in tpl_seed:
            if not await db.notification_templates.find_one({"channel": ch, "code": code}):
                await db.notification_templates.insert_one({"id": new_id(), "channel": ch, "code": code, "subject": sub, "body": body, "active": True, "created_at": utcnow()})

        # Default system settings
        defaults = {
            "platform_fee_pct": 5.0,
            "gst_pct": 18.0,
            "token_pct": 5.0,
            "support_email": "support@booktalent.com",
            "support_phone": "+91 80000 00000",
            # Outstation Business Rule (Iter 32, refined Iter 37) — Admin-editable
            "outstation_notice": (
                "Travel, accommodation, local transportation, meals, hospitality, "
                "and any other outstation expenses are NOT included in the Artist "
                "Package Fee.\n\n"
                "By proceeding with this booking, you acknowledge and agree that "
                "all such additional expenses must be paid directly by the Customer "
                "to the Artist. This applies regardless of whether the Artist is "
                "travelling alone or with any accompanying team members, musicians, "
                "assistants, technicians, or other add-on members."
            ),
            "booking_fee_note": (
                "Travel, accommodation, local transportation, meals, hospitality, "
                "and any other outstation expenses are NOT included in the Artist "
                "Package Fee. These expenses must be paid directly by the Customer "
                "to the Artist — this applies to the Artist and any accompanying "
                "team members, musicians, assistants or technicians."
            ),
            "outstation_clause": (
                "OUTSTATION LOGISTICS CLAUSE\n"
                "Travel, accommodation, local transportation, meals, hospitality, "
                "and any other outstation expenses are NOT included in the Artist "
                "Performance Fee or the Platform Service Fee. All such additional "
                "expenses shall be arranged and paid separately and directly by the "
                "Customer to the Artist. This applies regardless of whether the "
                "Artist is travelling alone or with any accompanying team members, "
                "musicians, assistants, technicians, or other add-on members."
            ),
        }
        for k, v in defaults.items():
            if not await db.system_settings.find_one({"key": k}):
                await db.system_settings.insert_one({"key": k, "value": v, "created_at": utcnow()})

    # Public seed trigger so server.py calls on startup
    r.seed = seed_iter7  # type: ignore[attr-defined]

    return r
