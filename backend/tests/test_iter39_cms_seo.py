"""
Iter 39 — CMS pages, Dynamic Menus, FAQ v2, Broadcast Announcements,
Sitemap/Robots, Artist slug + Category/City SEO landing endpoints.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
API = f"{BASE_URL}/api"


def _admin_token():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@booktalent.com", "password": "Admin@123"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestCMSPublic:
    def test_cms_list(self):
        r = requests.get(f"{API}/cms", timeout=10)
        assert r.status_code == 200
        pages = r.json()
        assert len(pages) >= 5
        slugs = {p["slug"] for p in pages}
        for expected in ("about", "privacy", "terms", "refund-policy", "cancellation-policy"):
            assert expected in slugs

    def test_cms_page(self):
        r = requests.get(f"{API}/cms/pages/about", timeout=10)
        assert r.status_code == 200
        p = r.json()
        assert p["title"]
        assert p["body_html"]
        assert p["published"] is True

    def test_cms_404(self):
        r = requests.get(f"{API}/cms/pages/does-not-exist", timeout=10)
        assert r.status_code == 404

    def test_menu_footer_contains_pages(self):
        r = requests.get(f"{API}/menu/footer", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 5
        assert all("/page/" in it["href"] for it in items)

    def test_menu_header(self):
        r = requests.get(f"{API}/menu/header", timeout=10)
        assert r.status_code == 200
        # header items may be 0-2, but at minimum "about" and "contact" are
        # seeded as header_menu=True
        items = r.json()["items"]
        assert isinstance(items, list)

    def test_admin_cms_v2_crud(self):
        tok = _admin_token()
        # Create
        r = requests.post(f"{API}/admin/cms-v2", headers=_h(tok), timeout=10, json={
            "slug": "iter39-test", "title": "Iter39 Test", "body_html": "<p>x</p>",
            "meta_description": "test", "published": True,
            "header_menu": True, "footer_menu": False, "menu_order": 999,
            "seo_title": "T", "seo_keywords": "k1,k2",
            "og_image": "", "canonical": "", "schema_json": "",
        })
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        # Public sees it
        pub = requests.get(f"{API}/cms/pages/iter39-test", timeout=10)
        assert pub.status_code == 200

        # Update — unpublish
        r = requests.put(f"{API}/admin/cms-v2/{pid}", headers=_h(tok), timeout=10, json={
            "slug": "iter39-test", "title": "Iter39 Test", "body_html": "<p>x</p>",
            "meta_description": "test", "published": False,
            "header_menu": True, "footer_menu": False, "menu_order": 999,
            "seo_title": "", "seo_keywords": "", "og_image": "",
            "canonical": "", "schema_json": "",
        })
        assert r.status_code == 200
        # Public 404s
        pub2 = requests.get(f"{API}/cms/pages/iter39-test", timeout=10)
        assert pub2.status_code == 404

        # Delete
        r = requests.delete(f"{API}/admin/cms-v2/{pid}", headers=_h(tok), timeout=10)
        assert r.status_code == 200


class TestFAQ:
    def test_faqs_search_featured(self):
        r = requests.get(f"{API}/faqs/search?featured=true", timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2
        assert all(f.get("is_featured") for f in items)

    def test_faqs_categories(self):
        r = requests.get(f"{API}/faqs/categories", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_faqs_search_q(self):
        r = requests.get(f"{API}/faqs/search?q=payment", timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert any("payment" in (f["question"] + f["answer"]).lower() for f in items)


class TestAnnouncements:
    def test_active_endpoint_public(self):
        r = requests.get(f"{API}/announcements/active", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_ann_crud(self):
        tok = _admin_token()
        r = requests.post(f"{API}/admin/announcements", headers=_h(tok), timeout=10, json={
            "title": "Iter39 Test Ann", "body": "Test body", "audience": "all",
            "channels": ["banner", "dashboard"], "priority": "high",
            "cta_label": "Try it", "cta_url": "/help",
            "active": True,
        })
        assert r.status_code == 200, r.text
        aid = r.json()["id"]
        # Public sees it
        pub = requests.get(f"{API}/announcements/active", timeout=10)
        titles = [x["title"] for x in pub.json()]
        assert "Iter39 Test Ann" in titles
        # Delete
        requests.delete(f"{API}/admin/announcements/{aid}", headers=_h(tok), timeout=10)


class TestSitemapAndRobots:
    def test_sitemap_xml(self):
        r = requests.get(f"{API}/sitemap.xml", timeout=15)
        assert r.status_code == 200
        assert "application/xml" in r.headers.get("content-type", "")
        body = r.text
        assert "<?xml" in body
        assert "<urlset" in body
        assert "/page/about" in body
        assert "/artists/singer" in body or "/artists/dj" in body

    def test_robots(self):
        r = requests.get(f"{API}/robots.txt", timeout=10)
        assert r.status_code == 200
        assert "User-agent" in r.text
        assert "Sitemap:" in r.text


class TestSEOEndpoints:
    def test_category_landing(self):
        r = requests.get(f"{API}/seo/category/singer", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["category"]["slug"] == "singer"
        assert isinstance(d["artists"], list)

    def test_city_landing(self):
        r = requests.get(f"{API}/seo/city/mumbai", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["city"]["slug"] == "mumbai"

    def test_artist_slug_lookup(self):
        # Seed data guarantees a Mumbai artist exists
        city = requests.get(f"{API}/seo/city/mumbai", timeout=10).json()
        assert city["artists"], "expected at least one Mumbai artist in seed"
        slug = city["artists"][0]["slug"]
        assert slug
        r = requests.get(f"{API}/artists/slug/{slug}", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["user_id"]
        assert d["profile"]["stage_name"]
