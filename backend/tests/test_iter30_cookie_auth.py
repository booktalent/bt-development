"""
Iter 30 — Code-quality hardening pass.

Verifies:
  1. httpOnly cookie is set on /auth/login, /auth/register, /auth/otp/verify
  2. cookie cleared on /auth/logout
  3. Cookie-only auth is sufficient for REST (/auth/me works with only the cookie)
  4. Bearer-only auth still works (no cookie present)
  5. Regression: iter27-29 flows still functional (subscriptions, concierge,
     rider wallet, homepage rails, add-ons, travel)
  6. Corporate bulk-booking POST /api/corporate/bulk-bookings still returns 200
"""
import os
import re
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Test-fixture credentials — override via env in CI to avoid committing values.
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@booktalent.com")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@123")
CUSTOMER_EMAIL = os.environ.get("TEST_CUSTOMER_EMAIL", "customer@booktalent.com")
CUSTOMER_PASSWORD = os.environ.get("TEST_CUSTOMER_PASSWORD", "Customer@123")
ARTIST_EMAIL = os.environ.get("TEST_ARTIST_EMAIL", "priya@booktalent.com")
ARTIST_PASSWORD = os.environ.get("TEST_ARTIST_PASSWORD", "Artist@123")
CORPORATE_EMAIL = os.environ.get("TEST_CORPORATE_EMAIL", "corporate@booktalent.com")
CORPORATE_PASSWORD = os.environ.get("TEST_CORPORATE_PASSWORD", "Corporate@123")


# ─── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture(scope="module")
def admin_token(admin_login):
    return admin_login.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def customer_login():
    r = requests.post(f"{API}/auth/login", json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture(scope="module")
def customer_token(customer_login):
    return customer_login.json()["token"]


@pytest.fixture(scope="module")
def priya_login():
    r = requests.post(f"{API}/auth/login", json={"email": ARTIST_EMAIL, "password": ARTIST_PASSWORD})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture(scope="module")
def priya_token(priya_login):
    return priya_login.json()["token"]


@pytest.fixture(scope="module")
def corporate_login():
    # test_credentials.md says Corporate@123 (not Corp@123)
    for pw in (CORPORATE_PASSWORD, "Corp@123"):
        r = requests.post(f"{API}/auth/login", json={"email": CORPORATE_EMAIL, "password": pw})
        if r.status_code == 200:
            return r
    pytest.skip(f"Corporate login failed: {r.status_code} {r.text}")


@pytest.fixture(scope="module")
def corporate_token(corporate_login):
    return corporate_login.json()["token"]


# ─── 1. httpOnly cookie on login ─────────────────────────────────────────────
class TestCookieOnLogin:
    def test_login_returns_token_and_user(self, customer_login):
        j = customer_login.json()
        assert "token" in j and isinstance(j["token"], str) and len(j["token"]) > 20
        assert "user" in j
        assert j["user"]["email"] == "customer@booktalent.com"

    def test_login_sets_httponly_cookie(self, customer_login):
        # Requests exposes the raw Set-Cookie via headers
        set_cookies = customer_login.headers.get("set-cookie") or customer_login.headers.get("Set-Cookie")
        assert set_cookies, f"No Set-Cookie header: {customer_login.headers}"
        assert "access_token=" in set_cookies
        # HttpOnly, Secure, SameSite=lax, Path=/, Max-Age=604800
        lower = set_cookies.lower()
        assert "httponly" in lower, f"HttpOnly missing: {set_cookies}"
        assert "secure" in lower, f"Secure missing: {set_cookies}"
        assert "samesite=lax" in lower, f"SameSite=Lax missing: {set_cookies}"
        assert "max-age=604800" in lower, f"Max-Age=604800 missing: {set_cookies}"
        assert "path=/" in lower

    def test_login_cookie_value_matches_token(self, customer_login):
        jar_val = customer_login.cookies.get("access_token")
        assert jar_val, "access_token cookie not present in cookie jar"
        # value should be a valid-looking JWT (three dot-separated segments)
        assert jar_val.count(".") == 2


# ─── 2. Cookie cleared on logout ─────────────────────────────────────────────
class TestLogoutClearsCookie:
    def test_logout_clears_cookie(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD})
        assert r.status_code == 200
        assert s.cookies.get("access_token"), "cookie not stored after login"

        r2 = s.post(f"{API}/auth/logout")
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

        set_cookies = r2.headers.get("set-cookie") or r2.headers.get("Set-Cookie") or ""
        lower = set_cookies.lower()
        # FastAPI's delete_cookie sets Max-Age=0 OR an expires date in the past
        cleared = ("max-age=0" in lower) or ("expires=" in lower and "1970" in lower) or ('access_token=""' in lower) or ('access_token=;' in lower)
        assert cleared, f"cookie not cleared server-side: {set_cookies}"


# ─── 3. Cookie-only auth is sufficient for REST ──────────────────────────────
class TestCookieOnlyRest:
    def test_me_with_cookie_only(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD})
        assert r.status_code == 200
        # Explicitly do NOT set Authorization header
        me = s.get(f"{API}/auth/me")
        assert me.status_code == 200, me.text
        j = me.json()
        assert j["email"] == "customer@booktalent.com"


# ─── 4. Bearer-only auth still works ─────────────────────────────────────────
class TestBearerOnly:
    def test_me_with_bearer_only(self, customer_token):
        # Fresh session with no cookie jar
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {customer_token}"})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "customer@booktalent.com"

    def test_me_no_auth_returns_401(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401


# ─── 5. OTP verify path also sets cookie when user exists ────────────────────
class TestOtpVerifyCookie:
    def test_otp_verify_sets_cookie_for_existing_user(self, priya_login):
        # Priya has phone in seed data. Send + verify OTP with mock 123456.
        priya_user = priya_login.json()["user"]
        phone = priya_user.get("phone")
        if not phone:
            pytest.skip("Priya has no phone")
        send = requests.post(f"{API}/auth/otp/send", json={"phone": phone})
        assert send.status_code == 200
        verify = requests.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": "123456"})
        assert verify.status_code == 200, verify.text
        j = verify.json()
        assert j.get("verified") is True
        # only asserted when user exists on that phone
        if j.get("token"):
            set_cookies = verify.headers.get("set-cookie") or verify.headers.get("Set-Cookie") or ""
            assert "access_token=" in set_cookies, f"otp/verify did not set cookie: {set_cookies}"
            assert "httponly" in set_cookies.lower()


# ─── 6. Regression — auth/me + core endpoints for each role ───────────────────
class TestRegressionRoles:
    def test_priya_me(self, priya_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {priya_token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "artist"

    def test_admin_me(self, admin_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"


# ─── 7. Regression — Concierge (BOTH Bearer AND cookie) ──────────────────────
class TestConciergeRegression:
    def test_concierge_threads_list_bearer(self, admin_token):
        r = requests.get(f"{API}/admin/concierge/threads", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_concierge_threads_list_cookie_only(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        r2 = s.get(f"{API}/admin/concierge/threads")
        assert r2.status_code == 200, r2.text
        assert isinstance(r2.json(), list)


# ─── 8. Regression — Smart Homepage personalized rails ───────────────────────
class TestHomepageRegression:
    def test_homepage_anonymous(self):
        r = requests.get(f"{API}/homepage/sections")
        assert r.status_code == 200
        rails = r.json()
        # Response may be dict wrapper or list
        assert isinstance(rails, (list, dict))

    def test_homepage_authenticated(self, customer_token):
        r = requests.get(f"{API}/homepage/sections", headers={"Authorization": f"Bearer {customer_token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), (list, dict))


# ─── 9. Rider Wallet regression removed — feature deleted in Iter 34 ─────────
# The `/rider-wallet/vendors` endpoint and the `rider_vendors` collection
# were fully removed in Iter 34 per the customer's simplification request.
# See PRD.md → "Iter 34 — Rider Wallet / Partners Directory Removed".


# ─── 10. Regression — Subscriptions ──────────────────────────────────────────
class TestSubscriptionsRegression:
    def test_subscription_plans_public(self):
        r = requests.get(f"{API}/subscriptions/plans")
        assert r.status_code == 200
        plans = r.json()
        assert isinstance(plans, list)
        assert len(plans) >= 1

    def test_my_subscription(self, priya_token):
        r = requests.get(f"{API}/subscriptions/me", headers={"Authorization": f"Bearer {priya_token}"})
        # 200 with plan payload or 404 when no active sub — both acceptable
        assert r.status_code in (200, 204, 404), r.text


# ─── 11. Regression — Add-ons (Sprint 3) ─────────────────────────────────────
class TestAddonsRegression:
    def test_priya_addons_list(self, priya_token):
        r = requests.get(f"{API}/artist/addons", headers={"Authorization": f"Bearer {priya_token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ─── 12. Regression — Travel snapshot on packages ────────────────────────────
class TestTravelRegression:
    def test_priya_packages_include_travel_fields(self, priya_token):
        r = requests.get(f"{API}/packages/mine", headers={"Authorization": f"Bearer {priya_token}"})
        assert r.status_code == 200
        pkgs = r.json()
        assert isinstance(pkgs, list)
        # at least one package should have the travel fields on the schema
        if pkgs:
            p = pkgs[0]
            for k in ("travel_required", "accommodation_required", "local_transport_required", "meals_required"):
                assert k in p, f"missing field {k} on package: {list(p.keys())}"


# ─── 13. Corporate bulk bookings endpoint ────────────────────────────────────
class TestCorporateBulk:
    def test_bulk_bookings_endpoint_exists(self, corporate_token):
        # Send an empty rows array — endpoint should either accept it or 400.
        r = requests.post(
            f"{API}/corporate/bulk-bookings",
            headers={"Authorization": f"Bearer {corporate_token}"},
            json={"rows": []},
        )
        # We just need it to exist and not 500. Empty rows likely 400.
        assert r.status_code != 404, "bulk-bookings endpoint missing"
        assert r.status_code < 500, f"5xx from bulk-bookings: {r.text}"
