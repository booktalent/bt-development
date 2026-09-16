"""Iter 73 — media order (post-migration), availability newest-first, auth playbook checks."""
import base64
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
        pytest.skip(f"no credentials for {email}")
    return m.group(1)


ARTIST_EMAIL = "priya@booktalent.com"
CUSTOMER_EMAIL = "customer@booktalent.com"
ADMIN_EMAIL = "admin@booktalent.com"


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
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode()


# ── Task 1: media ordering after iter73 backfill migration ───────────────────
class TestMediaOrderAfterMigration:
    def test_new_upload_is_first(self, artist_session):
        created = []
        try:
            up = artist_session.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": tiny_png_data_url(), "title": "TEST_iter73_a.png"},
                timeout=60,
            )
            assert up.status_code == 200, up.text[:300]
            mid_a = up.json()["id"]
            created.append(mid_a)
            time.sleep(1.2)
            up2 = artist_session.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": tiny_png_data_url(), "title": "TEST_iter73_b.png"},
                timeout=60,
            )
            assert up2.status_code == 200, up2.text[:300]
            mid_b = up2.json()["id"]
            created.append(mid_b)

            items = artist_session.get(f"{API}/media", timeout=30).json()
            assert all("_id" not in it for it in items), "_id leaked"
            ids = [it["id"] for it in items]
            assert ids[0] == mid_b, f"newest upload not first: {ids[:4]}"
            assert ids[1] == mid_a, f"2nd newest not second: {ids[:4]}"
            orders = [it.get("order", 0) for it in items]
            assert orders == sorted(orders), f"order not asc: {orders[:10]}"
            stamps = [it["created_at"] for it in items if (it.get("order") or 0) == 0 and it.get("created_at")]
            assert stamps == sorted(stamps, reverse=True), "created_at not DESC within order=0 group"
        finally:
            for mid in created:
                artist_session.delete(f"{API}/media/{mid}", timeout=30)

    def test_no_legacy_docs_missing_order(self, artist_session):
        items = artist_session.get(f"{API}/media", timeout=30).json()
        missing = [it["id"] for it in items if "order" not in it or it.get("order") is None]
        assert not missing, f"docs still missing order after migration: {missing[:5]}"

    def test_public_media_same_order(self, artist_session):
        uid = artist_session.get(f"{API}/auth/me", timeout=30).json()["id"]
        r = requests.get(f"{API}/public/media", params={"user_id": uid}, timeout=30)
        assert r.status_code == 200
        items = r.json()
        orders = [it.get("order", 0) for it in items]
        assert orders == sorted(orders)
        stamps = [it["created_at"] for it in items if (it.get("order") or 0) == 0 and it.get("created_at")]
        assert stamps == sorted(stamps, reverse=True)


# ── Task 2: availability newest-first ────────────────────────────────────────
class TestAvailabilityOrder:
    def test_mine_sorted_date_desc(self, artist_session):
        created = []
        try:
            for d in ["2027-03-05", "2027-03-20", "2027-03-12"]:
                r = artist_session.post(
                    f"{API}/availability", json={"date": d, "status": "available"}, timeout=30
                )
                assert r.status_code in (200, 201), f"{d}: {r.status_code} {r.text[:200]}"
                created.append(d)
            r = artist_session.get(f"{API}/availability/mine", timeout=30)
            assert r.status_code == 200, r.text[:300]
            docs = r.json()
            assert all("_id" not in d for d in docs)
            dates = [d["date"] for d in docs]
            assert dates == sorted(dates, reverse=True), f"not date DESC: {dates[:8]}"
            # relative order among the docs we created must be desc
            mine = [d for d in dates if d in created]
            assert mine == sorted(created, reverse=True), f"created docs out of order: {mine}"
        finally:
            for d in created:
                artist_session.delete(f"{API}/availability/{d}", timeout=30)


# ── Auth playbook checks ─────────────────────────────────────────────────────
class TestAuthPlaybook:
    def test_login_sets_httponly_cookie_for_all_roles(self):
        for email in (ARTIST_EMAIL, CUSTOMER_EMAIL, ADMIN_EMAIL):
            s, r = login(email, cred(email))
            assert r.status_code == 200, f"{email}: {r.status_code} {r.text[:200]}"
            sc = r.headers.get("set-cookie", "")
            assert "access_token" in sc and "httponly" in sc.lower(), f"{email}: {sc[:200]}"
            me = s.get(f"{API}/auth/me", timeout=30)
            assert me.status_code == 200 and me.json()["email"] == email

    def test_cors_credentials_on_actual_request(self):
        # NOTE: OPTIONS preflight is answered by the edge proxy (returns '*'),
        # so assert on the real request which reaches FastAPI's CORSMiddleware.
        r = requests.post(
            f"{API}/auth/login",
            json={"email": CUSTOMER_EMAIL, "password": cred(CUSTOMER_EMAIL)},
            headers={"Origin": BASE_URL},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("access-control-allow-credentials") == "true", dict(r.headers)
        assert r.headers.get("access-control-allow-origin") in (BASE_URL, BASE_URL + "/", "*")

    def test_bcrypt_hash_format(self):
        import asyncio

        from motor.motor_asyncio import AsyncIOMotorClient

        env = dotenv_values("/app/backend/.env")
        mongo_url = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME") or env.get("DB_NAME")
        if not mongo_url or not db_name:
            pytest.skip("MONGO_URL/DB_NAME unavailable")

        async def _check():
            client = AsyncIOMotorClient(mongo_url)
            try:
                u = await client[db_name].users.find_one({"email": ADMIN_EMAIL})
                return (u or {}).get("password_hash") or (u or {}).get("password")
            finally:
                client.close()

        h = asyncio.get_event_loop().run_until_complete(_check()) if False else asyncio.run(_check())
        assert h, "no password hash stored for admin"
        assert h.startswith("$2b$") or h.startswith("$2a$") or h.startswith("$2y$"), h[:10]

    def test_wrong_password_401(self):
        _, r = login(CUSTOMER_EMAIL, "definitely-wrong-pass-xyz")
        assert r.status_code in (401, 429), r.status_code
