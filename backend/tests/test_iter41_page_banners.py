"""
Iter 41 — Home hero, per-category/city banners, per-blog banners, admin blog CRUD.
"""
import os, uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
API = f"{BASE}/api"


def _admin():
    r = requests.post(f"{API}/auth/login", json={"email": "admin@booktalent.com", "password": "Admin@123"}, timeout=15)
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestHomeHero:
    def test_home_hero_settings_public(self):
        tok = _admin()
        requests.put(f"{API}/admin/settings/home_hero_title", headers=_h(tok), json={"value": "Iter41 Home"}, timeout=10)
        pub = requests.get(f"{API}/settings/public", timeout=10).json()
        assert pub.get("home_hero_title") == "Iter41 Home"


class TestCategoryBanner:
    def test_category_hero_persists_and_public(self):
        tok = _admin()
        cats = requests.get(f"{API}/admin/master/categories", headers=_h(tok), timeout=10).json()
        cat = next(c for c in cats if c["slug"] == "dj")
        requests.put(f"{API}/admin/master/categories/{cat['id']}", headers=_h(tok), timeout=10, json={
            "name": cat["name"], "slug": "dj", "icon": cat.get("icon", "🎧"),
            "sort_order": cat.get("sort_order", 2), "active": True,
            "hero_image": "https://example.com/dj.jpg",
            "hero_title": "Book DJs", "hero_subtitle": "Sub", "hero_cta_label": "Go", "hero_cta_url": "/artists/dj",
        })
        pub = requests.get(f"{API}/seo/category/dj", timeout=10).json()
        assert pub["category"]["hero_title"] == "Book DJs"
        assert pub["category"]["hero_image"].endswith("dj.jpg")
        # Slug must be preserved (regression from Iter41 bug)
        assert pub["category"]["slug"] == "dj"

    def test_update_without_slug_does_not_regenerate(self):
        """Regression: updating with only hero fields must NOT rewrite the
        slug from name, or every public /artists/<slug> URL breaks."""
        tok = _admin()
        cats = requests.get(f"{API}/admin/master/categories", headers=_h(tok), timeout=10).json()
        cat = next(c for c in cats if c["slug"] == "comedian")
        before_slug = cat["slug"]
        # PUT without slug field
        requests.put(f"{API}/admin/master/categories/{cat['id']}", headers=_h(tok), timeout=10, json={
            "name": cat["name"], "icon": cat.get("icon"),
            "sort_order": cat.get("sort_order", 3), "active": True,
            "hero_title": "Comedians of India",
        })
        after = requests.get(f"{API}/seo/category/{before_slug}", timeout=10)
        assert after.status_code == 200, f"Slug got rewritten: /seo/category/{before_slug} -> {after.status_code}"


class TestBlogAdminCrud:
    def test_blog_full_lifecycle_with_banner(self):
        tok = _admin()
        slug = f"iter41-{uuid.uuid4().hex[:6]}"
        payload = {
            "title": "Iter41 Test", "slug": slug, "content": "<p>Hello</p>",
            "cover_image": "", "excerpt": "excerpt", "tags": ["test"], "published": True,
            "author": "Iter41",
            "hero_image": "https://example.com/h.jpg",
            "hero_title": "Iter41 Banner", "hero_subtitle": "Sub",
            "hero_cta_label": "Read", "hero_cta_url": "/help",
        }
        r = requests.post(f"{API}/admin/blogs", headers=_h(tok), json=payload, timeout=10)
        assert r.status_code == 200, r.text
        bid = r.json()["id"]

        pub = requests.get(f"{API}/blogs/{slug}", timeout=10).json()
        assert pub["hero_title"] == "Iter41 Banner"
        assert pub["author"] == "Iter41"

        # Update
        payload["hero_title"] = "Updated"
        r = requests.put(f"{API}/admin/blogs/{bid}", headers=_h(tok), json=payload, timeout=10)
        assert r.status_code == 200
        assert requests.get(f"{API}/blogs/{slug}", timeout=10).json()["hero_title"] == "Updated"

        # Delete
        r = requests.delete(f"{API}/admin/blogs/{bid}", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        assert requests.get(f"{API}/blogs/{slug}", timeout=10).status_code == 404
