"""Iter 72 — media list ordering + Iter 71 security regressions."""
import base64
import io
import os
import re
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"

CREDS = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")


def cred(email):
    m = re.search(r"\|\s*`" + re.escape(email) + r"`\s*\|\s*`([^`]+)`", CREDS)
    if not m:
        pytest.skip(f"no credentials for {email} in test_credentials.md")
    return m.group(1)


ADMIN_EMAIL = "admin@booktalent.com"
ARTIST_EMAIL = "priya@booktalent.com"


def login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return s, r


@pytest.fixture(scope="module")
def artist_session():
    s, r = login(ARTIST_EMAIL, cred(ARTIST_EMAIL))
    if r.status_code != 200:
        pytest.fail(f"artist login failed {r.status_code}: {r.text[:300]}")
    return s


def tiny_png_data_url():
    # 1x1 png
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode()


# ── Media list ordering (order asc, created_at desc) ─────────────────────────
class TestMediaOrdering:
    def test_upload_new_media_appears_first(self, artist_session):
        created = []
        try:
            before = artist_session.get(f"{API}/media", timeout=30)
            assert before.status_code == 200, before.text[:300]
            assert isinstance(before.json(), list)

            up = artist_session.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": tiny_png_data_url(), "title": "TEST_iter72_a.png"},
                timeout=60,
            )
            assert up.status_code == 200, up.text[:300]
            mid_a = up.json()["id"]
            created.append(mid_a)

            time.sleep(1.2)
            up2 = artist_session.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": tiny_png_data_url(), "title": "TEST_iter72_b.png"},
                timeout=60,
            )
            assert up2.status_code == 200, up2.text[:300]
            mid_b = up2.json()["id"]
            created.append(mid_b)

            lst = artist_session.get(f"{API}/media", timeout=30)
            assert lst.status_code == 200
            items = lst.json()
            assert all("_id" not in it for it in items), "mongo _id leaked in /api/media"

            ids = [it["id"] for it in items]
            assert ids[0] == mid_b, f"newest upload not first: got {ids[:3]}, expected {mid_b} first"
            assert ids[1] == mid_a, f"second-newest upload not second: got {ids[:3]}"

            # verify sort key semantics: order asc primary
            orders = [it.get("order", 0) for it in items]
            assert orders == sorted(orders), f"items not sorted by order asc: {orders}"

            # within the order==0 group, created_at must be DESC
            zero_group = [it for it in items if (it.get("order") or 0) == 0 and it.get("created_at")]
            stamps = [it["created_at"] for it in zero_group]
            assert stamps == sorted(stamps, reverse=True), f"created_at not DESC within order group: {stamps[:5]}"
        finally:
            for mid in created:
                artist_session.delete(f"{API}/media/{mid}", timeout=30)

    def test_public_media_same_ordering(self, artist_session):
        me = artist_session.get(f"{API}/auth/me", timeout=30)
        assert me.status_code == 200
        uid = me.json()["id"]
        r = requests.get(f"{API}/public/media", params={"user_id": uid}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        orders = [it.get("order", 0) for it in items]
        assert orders == sorted(orders)
        zero = [it["created_at"] for it in items if (it.get("order") or 0) == 0 and it.get("created_at")]
        assert zero == sorted(zero, reverse=True)


# ── REGRESSION Iter 71 SEC-001: verify must not issue a session ──────────────
class TestSec001EmailVerifyNoToken:
    def test_email_verify_mock_otp_grants_no_session(self):
        s = requests.Session()
        send = s.post(f"{API}/auth/email/send", json={"email": ADMIN_EMAIL}, timeout=30)
        assert send.status_code in (200, 400, 429), send.text[:300]
        r = s.post(f"{API}/auth/email/verify", json={"email": ADMIN_EMAIL, "otp": "123456"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("verified") is True
        assert body.get("token") is None, f"token issued on verify: {body}"
        assert "access_token" not in s.cookies.get_dict(), "access_token cookie set by verify"
        me = s.get(f"{API}/auth/me", timeout=30)
        assert me.status_code == 401, f"verify produced an authenticated session ({me.status_code})"


# ── REGRESSION Iter 71 SEC-002: admin password rotation ─────────────────────
class TestSec002AdminPasswordRotation:
    def test_old_password_rejected(self):
        _, r = login(ADMIN_EMAIL, "Admin@123")
        assert r.status_code == 401, f"old admin password still accepted ({r.status_code})"

    def test_new_password_accepted_and_cookie_httponly(self):
        s, r = login(ADMIN_EMAIL, cred(ADMIN_EMAIL))
        assert r.status_code == 200, r.text[:300]
        set_cookie = r.headers.get("set-cookie", "")
        assert "access_token" in set_cookie, f"no access_token cookie: {set_cookie[:200]}"
        assert "httponly" in set_cookie.lower()
        me = s.get(f"{API}/auth/me", timeout=30)
        assert me.status_code == 200
        assert me.json()["email"] == ADMIN_EMAIL
        assert me.json()["role"] == "admin"
