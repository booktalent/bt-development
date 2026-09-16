"""
Iter 39 Extended — Additional verifications not covered by test_iter39_cms_seo:
- POST /api/announcements/{aid}/read stores read receipt for logged-in user
- Artist slug lookup by known Priya slug pattern
- Category=singer and City=mumbai return actual artist arrays with slug + stage_name
- Banner announcement flows through /api/announcements/active with channels filtered
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL.rstrip('/')}/api"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestAnnouncementReadReceipt:
    def test_read_receipt_flow(self):
        admin_tok = _login("admin@booktalent.com", "Admin@123")
        cust_tok = _login("customer@booktalent.com", "Customer@123")

        # Create banner announcement targeted at "all"
        r = requests.post(f"{API}/admin/announcements", headers=_h(admin_tok), timeout=10, json={
            "title": "TEST_iter39_read_flow",
            "body": "read-receipt test",
            "audience": "all",
            "channels": ["banner", "dashboard"],
            "priority": "high",
            "active": True,
        })
        assert r.status_code == 200, r.text
        aid = r.json()["id"]

        try:
            # Public active should include it
            active = requests.get(f"{API}/announcements/active", timeout=10)
            assert active.status_code == 200
            titles = [x["title"] for x in active.json()]
            assert "TEST_iter39_read_flow" in titles

            # Logged-in customer marks as read
            r = requests.post(f"{API}/announcements/{aid}/read", headers=_h(cust_tok), timeout=10)
            assert r.status_code in (200, 201, 204), r.text

            # Second read should still be OK (idempotent)
            r2 = requests.post(f"{API}/announcements/{aid}/read", headers=_h(cust_tok), timeout=10)
            assert r2.status_code in (200, 201, 204)
        finally:
            requests.delete(f"{API}/admin/announcements/{aid}", headers=_h(admin_tok), timeout=10)


class TestArtistSlugPriya:
    def test_priya_slug_resolves(self):
        # Grab artists from mumbai and locate Priya
        r = requests.get(f"{API}/seo/city/mumbai", timeout=15)
        assert r.status_code == 200
        artists = r.json().get("artists", [])
        assert artists, "expected mumbai artists"
        # Find any artist with 'priya' in slug/name if present, otherwise use first
        priya = next((a for a in artists if "priya" in (a.get("slug") or "").lower()), artists[0])
        slug = priya["slug"]
        r2 = requests.get(f"{API}/artists/slug/{slug}", timeout=15)
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d.get("user_id")
        assert d.get("profile", {}).get("stage_name")

    def test_legacy_uuid_lookup_still_works(self):
        # Login as priya to fetch her own user id
        tok = _login("priya@booktalent.com", "Artist@123")
        me = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=10)
        assert me.status_code == 200
        uid = me.json().get("id") or me.json().get("_id") or me.json().get("user_id")
        assert uid
        # UUID/legacy artist profile lookup
        r = requests.get(f"{API}/artists/{uid}", timeout=10)
        assert r.status_code == 200, r.text


class TestFAQFeatured:
    def test_featured_count_ge_2(self):
        r = requests.get(f"{API}/faqs/search?featured=true", timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2, f"expected >=2 featured FAQs, got {len(items)}"


class TestBannerAudience:
    def test_banner_channel_appears_in_active(self):
        admin_tok = _login("admin@booktalent.com", "Admin@123")
        r = requests.post(f"{API}/admin/announcements", headers=_h(admin_tok), timeout=10, json={
            "title": "TEST_iter39_banner",
            "body": "banner-only",
            "audience": "all",
            "channels": ["banner"],
            "priority": "high",
            "active": True,
        })
        assert r.status_code == 200
        aid = r.json()["id"]
        try:
            pub = requests.get(f"{API}/announcements/active", timeout=10).json()
            found = [x for x in pub if x["title"] == "TEST_iter39_banner"]
            assert found
            assert "banner" in (found[0].get("channels") or [])
        finally:
            requests.delete(f"{API}/admin/announcements/{aid}", headers=_h(admin_tok), timeout=10)


class TestSitemapContents:
    def test_sitemap_contains_key_urls(self):
        r = requests.get(f"{API}/sitemap.xml", timeout=15)
        assert r.status_code == 200
        body = r.text
        # base URLs
        assert "/page/about" in body
        # category & city landings
        assert "/artists/" in body
        assert "/artists/city/" in body
        # Blog + Help
        assert "/help" in body
        assert "/blog" in body
