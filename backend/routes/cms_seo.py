"""
Iter 39 — CMS pages, Dynamic Menus, FAQs (public/featured), Broadcast
Announcements (banner/popup/dashboard), Sitemap.xml, Robots.txt.

Ties the previously admin-only CMS/FAQ/Broadcast modules to the live public
site, plus SEO-friendly discovery endpoints for category / city landing pages
and artist slug lookups.
"""
from __future__ import annotations
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Response
from pydantic import BaseModel


# ─── Slug helper ─────────────────────────────────────────────────────────────
_SLUG_RX = re.compile(r"[^a-z0-9]+")


def slugify(txt: str) -> str:
    s = _SLUG_RX.sub("-", (txt or "").strip().lower()).strip("-")
    return s or "item"


def artist_slug(profile: Dict[str, Any]) -> str:
    """Deterministic SEO slug for an artist: stage-name-category-city-<id6>."""
    parts = [profile.get("stage_name") or "", profile.get("category") or "", profile.get("city") or ""]
    base = "-".join(slugify(p) for p in parts if p)
    uid_tail = (profile.get("user_id") or "")[:6]
    return f"{base}-{uid_tail}".strip("-")


# ─── Payload models ──────────────────────────────────────────────────────────
class CMSPageBody(BaseModel):
    model_config = {"protected_namespaces": ()}
    slug: str
    title: str
    body_html: str
    meta_description: str = ""
    published: bool = True
    # Iter 39 additions
    header_menu: bool = False
    footer_menu: bool = True
    menu_order: int = 100
    seo_title: str = ""
    seo_keywords: str = ""
    og_image: str = ""
    canonical: str = ""
    schema_json: str = ""       # optional JSON-LD blob (raw string)
    # Iter 40 — Featured banner (renders as a hero on /page/<slug>)
    hero_image: str = ""        # URL — recommended 1600x600
    hero_title: str = ""        # Overrides page.title in the hero if set
    hero_subtitle: str = ""
    hero_cta_label: str = ""
    hero_cta_url: str = ""


class FAQItemBody(BaseModel):
    question: str
    answer: str
    category: str = "general"
    sort_order: int = 0
    active: bool = True
    is_featured: bool = False


class AnnouncementBody(BaseModel):
    title: str
    body: str = ""
    audience: Literal["all", "artist", "customer", "agency", "corporate", "admin"] = "all"
    channels: List[Literal["banner", "popup", "dashboard"]] = ["dashboard"]
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    cta_label: str = ""
    cta_url: str = ""
    starts_at: Optional[str] = None      # ISO strings
    expires_at: Optional[str] = None
    active: bool = True


def make_router(
    *,
    db,
    get_current_user: Callable,
    get_current_user_optional: Callable,
    admin_only: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
) -> APIRouter:
    r = APIRouter()

    # ═══════════════════════════════════════════════════════════════════════
    # CMS Pages — extended fields
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/cms")
    async def cms_list_public():
        """Every published page, lightweight (used by sitemaps / footer)."""
        items = await db.cms_pages.find(
            {"published": True},
            {"slug": 1, "title": 1, "menu_order": 1, "header_menu": 1, "footer_menu": 1, "updated_at": 1, "created_at": 1},
        ).sort("menu_order", 1).to_list(500)
        return [clean(d) for d in items]

    @r.get("/cms/pages/{slug}")
    async def cms_page(slug: str):
        page = await db.cms_pages.find_one({"slug": slug, "published": True})
        if not page:
            raise HTTPException(404, "Page not found")
        return clean(page)

    @r.get("/admin/cms-v2")
    async def admin_cms_list(_: dict = Depends(admin_only)):
        items = await db.cms_pages.find({}).sort("menu_order", 1).to_list(500)
        return [clean(d) for d in items]

    @r.post("/admin/cms-v2")
    async def admin_cms_create(body: CMSPageBody, _: dict = Depends(admin_only)):
        body.slug = slugify(body.slug)
        if await db.cms_pages.find_one({"slug": body.slug}):
            raise HTTPException(400, "Slug already exists")
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow(), "updated_at": utcnow()}
        await db.cms_pages.insert_one(doc)
        return clean(doc)

    @r.put("/admin/cms-v2/{pid}")
    async def admin_cms_update(pid: str, body: CMSPageBody, _: dict = Depends(admin_only)):
        body.slug = slugify(body.slug)
        await db.cms_pages.update_one({"id": pid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        doc = await db.cms_pages.find_one({"id": pid})
        if not doc:
            raise HTTPException(404, "Page not found")
        return clean(doc)

    @r.delete("/admin/cms-v2/{pid}")
    async def admin_cms_delete(pid: str, _: dict = Depends(admin_only)):
        await db.cms_pages.delete_one({"id": pid})
        return {"ok": True}

    # ═══════════════════════════════════════════════════════════════════════
    # Dynamic Menus — built from published CMS pages
    # ═══════════════════════════════════════════════════════════════════════
    async def _menu(where: str):
        q = {"published": True, where: True}
        items = await db.cms_pages.find(
            q, {"slug": 1, "title": 1, "menu_order": 1}
        ).sort("menu_order", 1).to_list(200)
        return [
            {"label": it.get("title") or it["slug"], "href": f"/page/{it['slug']}", "order": it.get("menu_order", 100)}
            for it in items
        ]

    @r.get("/menu/header")
    async def menu_header():
        return {"items": await _menu("header_menu")}

    @r.get("/menu/footer")
    async def menu_footer():
        return {"items": await _menu("footer_menu")}

    # ═══════════════════════════════════════════════════════════════════════
    # FAQs — featured / category-filtered / search
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/faqs/search")
    async def faqs_search(
        q: Optional[str] = None,
        category: Optional[str] = None,
        featured: Optional[bool] = None,
        limit: int = 200,
    ):
        query: Dict[str, Any] = {"active": True}
        if category and category != "all":
            query["category"] = category
        if featured is not None:
            query["is_featured"] = featured
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = [{"question": rx}, {"answer": rx}]
        items = await db.faqs.find(query).sort([("is_featured", -1), ("sort_order", 1)]).to_list(limit)
        return [clean(d) for d in items]

    @r.get("/faqs/categories")
    async def faqs_categories():
        cats = await db.faqs.distinct("category", {"active": True})
        return sorted(cats)

    # Admin CRUD v2 (keeps original iter7 endpoints alive too, but with
    # `is_featured` field so admin can flag home-page hero FAQs).
    @r.get("/admin/faqs-v2")
    async def admin_faqs_list(_: dict = Depends(admin_only)):
        items = await db.faqs.find({}).sort([("is_featured", -1), ("sort_order", 1)]).to_list(2000)
        return [clean(d) for d in items]

    @r.post("/admin/faqs-v2")
    async def admin_faq_create(body: FAQItemBody, _: dict = Depends(admin_only)):
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
        await db.faqs.insert_one(doc)
        return clean(doc)

    @r.put("/admin/faqs-v2/{fid}")
    async def admin_faq_update(fid: str, body: FAQItemBody, _: dict = Depends(admin_only)):
        await db.faqs.update_one({"id": fid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        return clean(await db.faqs.find_one({"id": fid}))

    @r.delete("/admin/faqs-v2/{fid}")
    async def admin_faq_delete(fid: str, _: dict = Depends(admin_only)):
        await db.faqs.delete_one({"id": fid})
        return {"ok": True}

    # ═══════════════════════════════════════════════════════════════════════
    # Broadcast Announcements (banner / popup / dashboard) — per-user read
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/announcements/active")
    async def announcements_active(authorization: Optional[str] = Header(None)):
        """Returns currently-live announcements for the caller (audience match
        + within schedule window). Anonymous callers see `all` audience only."""
        user = None
        if authorization:
            user = await get_current_user_optional(authorization)
        now = datetime.now(timezone.utc).isoformat()
        role = (user or {}).get("role") if user else None
        audience_ok = ["all"] + ([role] if role else [])
        q: Dict[str, Any] = {
            "active": True,
            "audience": {"$in": audience_ok},
            "$and": [
                {"$or": [{"starts_at": None}, {"starts_at": {"$lte": now}}, {"starts_at": ""}]},
                {"$or": [{"expires_at": None}, {"expires_at": {"$gte": now}}, {"expires_at": ""}]},
            ],
        }
        items = await db.announcements.find(q).sort([("priority", -1), ("created_at", -1)]).to_list(50)
        # attach `read` flag when the user is logged in
        read_ids: set = set()
        if user:
            reads = await db.announcement_reads.find({"user_id": user["id"]}).to_list(1000)
            read_ids = {r["announcement_id"] for r in reads}
        out = []
        for it in items:
            row = clean(it)
            row["read"] = row["id"] in read_ids if user else False
            out.append(row)
        return out

    @r.post("/announcements/{aid}/read")
    async def announcement_read(aid: str, user: dict = Depends(get_current_user)):
        await db.announcement_reads.update_one(
            {"user_id": user["id"], "announcement_id": aid},
            {"$set": {"read_at": utcnow()}},
            upsert=True,
        )
        return {"ok": True}

    @r.get("/admin/announcements")
    async def admin_ann_list(_: dict = Depends(admin_only)):
        items = await db.announcements.find({}).sort("created_at", -1).to_list(500)
        return [clean(d) for d in items]

    @r.post("/admin/announcements")
    async def admin_ann_create(body: AnnouncementBody, _: dict = Depends(admin_only)):
        doc = {"id": new_id(), **body.dict(), "created_at": utcnow()}
        await db.announcements.insert_one(doc)
        return clean(doc)

    @r.put("/admin/announcements/{aid}")
    async def admin_ann_update(aid: str, body: AnnouncementBody, _: dict = Depends(admin_only)):
        await db.announcements.update_one({"id": aid}, {"$set": {**body.dict(), "updated_at": utcnow()}})
        return clean(await db.announcements.find_one({"id": aid}))

    @r.delete("/admin/announcements/{aid}")
    async def admin_ann_delete(aid: str, _: dict = Depends(admin_only)):
        await db.announcements.delete_one({"id": aid})
        await db.announcement_reads.delete_many({"announcement_id": aid})
        return {"ok": True}

    # ═══════════════════════════════════════════════════════════════════════
    # Artist slug lookup (SEO-friendly URLs)
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/artists/slug/{slug}")
    async def artist_by_slug(slug: str):
        profile = await db.artist_profiles.find_one({"slug": slug, "suspended": {"$ne": True}})
        if not profile:
            # Fallback: some legacy profiles don't have a slug yet — try
            # matching by uid-tail (last 6 chars of slug should be user_id[:6]).
            tail = slug.split("-")[-1]
            if len(tail) == 6:
                async for p in db.artist_profiles.find({"user_id": {"$regex": f"^{re.escape(tail)}"}, "suspended": {"$ne": True}}, {"user_id": 1, "stage_name": 1, "category": 1, "city": 1}):
                    if artist_slug(p) == slug:
                        profile = await db.artist_profiles.find_one({"user_id": p["user_id"], "suspended": {"$ne": True}})
                        break
        if not profile:
            raise HTTPException(404, "Artist not found")
        user = await db.users.find_one({"id": profile["user_id"]}) or {}
        return {"profile": clean(profile), "user": clean(user), "user_id": profile["user_id"]}

    # ═══════════════════════════════════════════════════════════════════════
    # Category / City SEO landing pages
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/seo/category/{slug}")
    async def seo_category(slug: str, limit: int = 30):
        cat = await db.categories_master.find_one({"slug": slug, "active": True})
        if not cat:
            raise HTTPException(404, "Category not found")
        # Category values on artist profiles vary — accept either the category
        # display name ("Singers & Vocalists") or a sub-category alias
        # ("Bollywood Vocalist") that contains the slug root.
        root = slug.rstrip("s")  # e.g. "singer" → matches "Singers", "Singer"
        rx = {"$regex": re.escape(root), "$options": "i"}
        query = {"$or": [{"category": cat["name"]}, {"category": rx}], "suspended": {"$ne": True}}
        artists = await db.artist_profiles.find(
            query,
            {"user_id": 1, "stage_name": 1, "category": 1, "city": 1, "rating_avg": 1, "review_count": 1, "starting_price": 1, "photos": 1, "emoji": 1, "slug": 1},
        ).sort([("rating_avg", -1)]).limit(limit).to_list(limit)
        return {
            "category": clean(cat),
            "artists": [clean(a) for a in artists],
            "total": await db.artist_profiles.count_documents(query),
        }

    @r.get("/seo/city/{slug}")
    async def seo_city(slug: str, limit: int = 30):
        city = await db.cities_master.find_one({"slug": slug, "active": True})
        if not city:
            raise HTTPException(404, "City not found")
        query = {"city": city["name"], "suspended": {"$ne": True}}
        artists = await db.artist_profiles.find(
            query,
            {"user_id": 1, "stage_name": 1, "category": 1, "city": 1, "rating_avg": 1, "review_count": 1, "starting_price": 1, "photos": 1, "emoji": 1, "slug": 1},
        ).sort([("rating_avg", -1)]).limit(limit).to_list(limit)
        return {
            "city": clean(city),
            "artists": [clean(a) for a in artists],
            "total": await db.artist_profiles.count_documents(query),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Sitemap.xml + Robots.txt (public site index for search engines)
    # ═══════════════════════════════════════════════════════════════════════
    @r.get("/sitemap.xml")
    async def sitemap_xml(request_base: Optional[str] = None):
        # Build absolute URLs relative to the live public site. We accept an
        # override via ?request_base=https://…, otherwise we use FRONTEND_URL
        # from the backend env (production canonical origin).
        default_base = (os.environ.get("FRONTEND_URL") or "https://booktalent.in").rstrip("/")
        base = (request_base or default_base).rstrip("/")
        urls: List[Dict[str, Any]] = [
            {"loc": f"{base}/", "priority": "1.0", "changefreq": "daily"},
            {"loc": f"{base}/search", "priority": "0.9", "changefreq": "daily"},
            {"loc": f"{base}/help", "priority": "0.6", "changefreq": "weekly"},
            {"loc": f"{base}/blog", "priority": "0.7", "changefreq": "weekly"},
        ]
        # CMS pages
        async for p in db.cms_pages.find({"published": True}, {"slug": 1, "updated_at": 1, "created_at": 1}):
            urls.append({
                "loc": f"{base}/page/{p['slug']}",
                "lastmod": (p.get("updated_at") or p.get("created_at") or "")[:10],
                "priority": "0.7", "changefreq": "monthly",
            })
        # Categories
        async for c in db.categories_master.find({"active": True}, {"slug": 1}):
            urls.append({"loc": f"{base}/artists/{c['slug']}", "priority": "0.8", "changefreq": "daily"})
        # Cities
        async for c in db.cities_master.find({"active": True}, {"slug": 1}):
            urls.append({"loc": f"{base}/artists/city/{c['slug']}", "priority": "0.8", "changefreq": "daily"})
        # Artist profiles — include everyone with a slug (no profile_completed
        # gate; the slug itself is a sign the profile is discoverable).
        async for a in db.artist_profiles.find(
            {"slug": {"$exists": True, "$ne": ""}, "suspended": {"$ne": True}},
            {"user_id": 1, "stage_name": 1, "category": 1, "city": 1, "slug": 1, "updated_at": 1},
        ).limit(5000):
            slug = a.get("slug") or artist_slug(a)
            urls.append({
                "loc": f"{base}/artist/{slug}",
                "lastmod": (a.get("updated_at") or "")[:10],
                "priority": "0.7", "changefreq": "weekly",
            })
        # Blogs
        async for b in db.blogs.find({"published": True}, {"slug": 1, "updated_at": 1, "created_at": 1}):
            urls.append({
                "loc": f"{base}/blog/{b['slug']}",
                "lastmod": (b.get("updated_at") or b.get("created_at") or "")[:10],
                "priority": "0.6", "changefreq": "monthly",
            })

        xml = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls:
            xml.append("  <url>")
            xml.append(f"    <loc>{u['loc']}</loc>")
            if u.get("lastmod"):
                xml.append(f"    <lastmod>{u['lastmod']}</lastmod>")
            xml.append(f"    <changefreq>{u.get('changefreq', 'weekly')}</changefreq>")
            xml.append(f"    <priority>{u.get('priority', '0.5')}</priority>")
            xml.append("  </url>")
        xml.append("</urlset>")
        return Response(content="\n".join(xml), media_type="application/xml")

    @r.get("/robots.txt")
    async def robots_txt():
        base = (os.environ.get("FRONTEND_URL") or "https://booktalent.in").rstrip("/")
        txt = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /api/admin\n"
            "Disallow: /customer\n"
            "Disallow: /artist/edit\n"
            f"\nSitemap: {base}/sitemap.xml\n"
        )
        return Response(content=txt, media_type="text/plain")

    # ═══════════════════════════════════════════════════════════════════════
    # Seeder
    # ═══════════════════════════════════════════════════════════════════════
    async def seed():
        # Backfill: mark existing CMS pages as footer_menu=True so they show
        # up in the footer automatically. Also seed a wider set of legal /
        # informational pages that most marketplaces expect.
        defaults = [
            ("about", "About Us", "<h2>About BookTalent</h2><p>BookTalent is India's premium marketplace for booking live performers. From weddings and corporate events to private parties and festivals — we connect you with verified artists across the country.</p>", 10, True, True),
            ("contact", "Contact Us", "<h2>Contact Us</h2><p>Email: <a href='mailto:support@booktalent.com'>support@booktalent.com</a></p><p>Phone: +91 80000 00000</p>", 20, True, True),
            ("privacy", "Privacy Policy", "<h2>Privacy Policy</h2><p>We respect your privacy and only collect what we need to deliver bookings. Read the full policy here.</p>", 30, False, True),
            ("terms", "Terms &amp; Conditions", "<h2>Terms of Service</h2><p>By using BookTalent you agree to our terms — BookTalent is a lead-generation marketplace only. See the full terms here.</p>", 40, False, True),
            ("refund-policy", "Refund Policy", "<h2>Refund Policy</h2><p>The Platform Service Fee (5% + 18% GST) is refundable if the artist rejects or the booking is cancelled per our timelines. Artist Performance Fee is settled directly between customer and artist.</p>", 50, False, True),
            ("cancellation-policy", "Cancellation Policy", "<h2>Cancellation Policy</h2><p>Cancellations 7+ days before the event: 90% refund. 3–7 days: 50%. Within 72 hours: no refund on Platform Fee.</p>", 60, False, True),
            ("artist-guidelines", "Artist Guidelines", "<h2>Artist Guidelines</h2><p>Complete your profile, submit KYC, respond within 24 hours, uphold professional standards on-stage and off.</p>", 70, False, True),
            ("customer-guidelines", "Customer Guidelines", "<h2>Customer Guidelines</h2><p>Be clear about your event brief, respect artist timings, settle the Artist Performance Fee directly and promptly.</p>", 80, False, True),
            ("agency-guidelines", "Agency Guidelines", "<h2>Agency Guidelines</h2><p>Agencies onboarding rosters must ensure each artist has completed KYC and consented to platform terms.</p>", 90, False, True),
            ("careers", "Careers", "<h2>Careers</h2><p>We're always hiring music-loving product, design, engineering and ops folks. Reach out at <a href='mailto:careers@booktalent.com'>careers@booktalent.com</a>.</p>", 100, False, True),
            ("press", "Press &amp; Media", "<h2>Press &amp; Media</h2><p>For interviews, features and media assets, write to <a href='mailto:press@booktalent.com'>press@booktalent.com</a>.</p>", 110, False, True),
        ]
        for slug, title, html, order, header, footer in defaults:
            existing = await db.cms_pages.find_one({"slug": slug})
            if existing:
                # Backfill new fields on legacy rows without overwriting
                # admin-edited body / title.
                await db.cms_pages.update_one(
                    {"id": existing["id"]},
                    {"$set": {
                        "header_menu": existing.get("header_menu", header),
                        "footer_menu": existing.get("footer_menu", footer),
                        "menu_order": existing.get("menu_order", order),
                        "seo_title": existing.get("seo_title", ""),
                        "seo_keywords": existing.get("seo_keywords", ""),
                        "og_image": existing.get("og_image", ""),
                        "canonical": existing.get("canonical", ""),
                        "schema_json": existing.get("schema_json", ""),
                    }},
                )
            else:
                await db.cms_pages.insert_one({
                    "id": new_id(), "slug": slug, "title": title, "body_html": html,
                    "meta_description": title, "published": True,
                    "header_menu": header, "footer_menu": footer, "menu_order": order,
                    "seo_title": "", "seo_keywords": "", "og_image": "",
                    "canonical": "", "schema_json": "",
                    "created_at": utcnow(), "updated_at": utcnow(),
                })

        # Backfill artist slugs on all completed profiles that don't have one
        async for p in db.artist_profiles.find({"slug": {"$in": [None, ""]}}, {"user_id": 1, "stage_name": 1, "category": 1, "city": 1}):
            if p.get("stage_name"):
                await db.artist_profiles.update_one(
                    {"user_id": p["user_id"]},
                    {"$set": {"slug": artist_slug(p)}},
                )

        # FAQ backfill: is_featured=False on legacy rows
        await db.faqs.update_many(
            {"is_featured": {"$exists": False}},
            {"$set": {"is_featured": False}},
        )
        # Ensure a few featured FAQs exist for the homepage
        featured_seed = [
            ("How does BookTalent make money?", "We charge only a 5% Platform Service Fee (plus 18% GST on that fee) when a booking is confirmed. The Artist Performance Fee is settled directly between you and the artist.", "payment", True),
            ("Are artists verified?", "Every artist completes KYC and profile review before going live. Look for the ✓ verified badge on their profile.", "trust", True),
            ("Can I book for an outstation event?", "Yes! Travel, stay and hospitality are arranged directly by you with the artist as per our outstation clause — see the notice on the booking screen.", "booking", True),
        ]
        for q, a, cat, feat in featured_seed:
            if not await db.faqs.find_one({"question": q}):
                await db.faqs.insert_one({
                    "id": new_id(), "question": q, "answer": a, "category": cat,
                    "sort_order": 0, "active": True, "is_featured": feat,
                    "created_at": utcnow(),
                })

    r.seed = seed  # type: ignore[attr-defined]
    return r
