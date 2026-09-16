"""
Iter 40 — Admin user CRUD (edit/delete/suspend), CMS featured banner,
Blog page banner via public settings.
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


class TestAdminUserCrud:
    def _make_user(self, tok):
        # Register a test customer through the signup endpoint (bypasses email
        # OTP for test env in this build).
        r = requests.post(f"{API}/admin/register-direct", headers=_h(tok), timeout=15,
                          json={"email": f"iter40-{uuid.uuid4().hex[:8]}@example.com",
                                "password": "TestPass@123", "first_name": "Iter40",
                                "last_name": "Test", "role": "customer"}) if False else None
        # Fallback: create via /auth/register — some builds need OTP; catch and
        # use an existing seeded user instead.
        email = f"iter40-{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", timeout=15, json={
            "email": email, "password": "TestPass@123",
            "first_name": "Iter40", "last_name": "Test",
            "phone": "+919999000000", "role": "customer",
        })
        if r.status_code != 200:
            # Fallback — mutate an existing user
            users = requests.get(f"{API}/admin/users?role=customer", headers=_h(tok), timeout=15).json()
            assert users, "No customers available for edit/delete test"
            return users[0]["id"], users[0]["email"]
        return r.json()["user"]["id"], email

    def test_edit_user(self):
        tok = _admin()
        uid, email = self._make_user(tok)
        r = requests.put(f"{API}/admin/users/{uid}", headers=_h(tok), timeout=15, json={
            "first_name": "Renamed", "phone": "+911111111111",
        })
        assert r.status_code == 200, r.text
        # Confirm via /admin/users
        u = next(x for x in requests.get(f"{API}/admin/users?role=customer", headers=_h(tok), timeout=15).json() if x["id"] == uid)
        assert u["first_name"] == "Renamed"
        assert u["phone"] == "+911111111111"

    def test_suspend_toggle(self):
        tok = _admin()
        uid, _ = self._make_user(tok)
        r = requests.post(f"{API}/admin/artists/{uid}/suspend", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["suspended"] is True
        r = requests.post(f"{API}/admin/artists/{uid}/suspend", headers=_h(tok), timeout=15)
        assert r.json()["suspended"] is False

    def test_soft_delete(self):
        tok = _admin()
        uid, _ = self._make_user(tok)
        r = requests.delete(f"{API}/admin/users/{uid}", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["mode"] == "soft"
        # Not in default listing
        users = requests.get(f"{API}/admin/users?role=customer", headers=_h(tok), timeout=15).json()
        assert not any(x["id"] == uid for x in users)
        # Visible when include_deleted=true
        users2 = requests.get(f"{API}/admin/users?role=customer&include_deleted=true", headers=_h(tok), timeout=15).json()
        assert any(x["id"] == uid for x in users2)

    def test_hard_delete(self):
        tok = _admin()
        uid, _ = self._make_user(tok)
        r = requests.delete(f"{API}/admin/users/{uid}?hard=true", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["mode"] == "hard"
        users = requests.get(f"{API}/admin/users?include_deleted=true", headers=_h(tok), timeout=15).json()
        assert not any(x["id"] == uid for x in users)

    def test_admin_cant_delete_self(self):
        tok = _admin()
        me = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=15).json()
        r = requests.delete(f"{API}/admin/users/{me['id']}", headers=_h(tok), timeout=15)
        assert r.status_code == 400


class TestFeaturedBanners:
    def test_cms_page_hero_fields(self):
        tok = _admin()
        pages = requests.get(f"{API}/admin/cms-v2", headers=_h(tok), timeout=15).json()
        about = next(p for p in pages if p["slug"] == "about")
        r = requests.put(f"{API}/admin/cms-v2/{about['id']}", headers=_h(tok), timeout=15, json={
            **{k: about.get(k, "") for k in ("slug", "title", "body_html", "meta_description",
                                             "seo_title", "seo_keywords", "og_image", "canonical", "schema_json")},
            "published": True, "header_menu": about.get("header_menu", True),
            "footer_menu": about.get("footer_menu", True), "menu_order": about.get("menu_order", 10),
            "hero_image": "https://example.com/h.jpg",
            "hero_title": "Iter40 Hero", "hero_subtitle": "Sub", "hero_cta_label": "Go", "hero_cta_url": "/search",
        })
        assert r.status_code == 200
        pub = requests.get(f"{API}/cms/pages/about", timeout=15).json()
        assert pub["hero_title"] == "Iter40 Hero"
        assert pub["hero_image"].endswith("h.jpg")
        assert pub["hero_cta_url"] == "/search"

    def test_blog_hero_via_settings(self):
        tok = _admin()
        payload = {"value": "Iter40 blog hero"}
        r = requests.put(f"{API}/admin/settings/blog_hero_title", headers=_h(tok), timeout=15, json=payload)
        assert r.status_code == 200
        pub = requests.get(f"{API}/settings/public", timeout=15).json()
        assert pub.get("blog_hero_title") == "Iter40 blog hero"
