"""
Iter 32 — Outstation Business Rule tests.

Covers:
 1. Public settings endpoint (whitelisted keys, no admin secrets leaked)
 2. Admin PUT /admin/settings/{key} round-trip on outstation_notice
 3. Booking snapshot — artist_city, event_city, is_outstation for both same-city and outstation
 4. Contract generation — OUTSTATION LOGISTICS block + FEE INCLUSION NOTE injected
 5. Regression — pricing still 5% + 18% GST, same-city contract has no outstation block
"""
import os
import pytest
import requests
from datetime import datetime, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@booktalent.com")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@123")
CUSTOMER_EMAIL = os.environ.get("TEST_CUSTOMER_EMAIL", "customer@booktalent.com")
CUSTOMER_PASSWORD = os.environ.get("TEST_CUSTOMER_PASSWORD", "Customer@123")
ARTIST_EMAIL = os.environ.get("TEST_ARTIST_EMAIL", "priya@booktalent.com")
ARTIST_PASSWORD = os.environ.get("TEST_ARTIST_PASSWORD", "Artist@123")


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def customer_token():
    return _login(CUSTOMER_EMAIL, CUSTOMER_PASSWORD)


@pytest.fixture(scope="module")
def artist_token():
    return _login(ARTIST_EMAIL, ARTIST_PASSWORD)


@pytest.fixture(scope="module")
def priya_info():
    r = requests.get(f"{BASE_URL}/api/artists/search?q=priya", timeout=15)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items, "Priya not found in search"
    p = items[0]
    return {"user_id": p["user_id"], "city": p.get("city"), "profile_id": p.get("id")}


@pytest.fixture(scope="module")
def priya_full(priya_info):
    r = requests.get(f"{BASE_URL}/api/artists/{priya_info['user_id']}", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ─────────────────────────────────────────────────────────────
# Settings seed + public whitelist
# ─────────────────────────────────────────────────────────────
class TestSettingsSeed:
    def test_public_settings_contains_new_keys(self):
        r = requests.get(f"{BASE_URL}/api/settings/public", timeout=10)
        assert r.status_code == 200
        data = r.json()
        for key in ("outstation_notice", "booking_fee_note", "outstation_clause"):
            assert key in data, f"public settings missing {key}"
            assert isinstance(data[key], str) and data[key].strip()
        # Existing keys still exposed
        for key in ("platform_fee_pct", "gst_pct", "support_email", "support_phone"):
            assert key in data

    def test_public_settings_no_admin_secret_leak(self):
        """Public endpoint must whitelist. Ensure no razorpay/smtp/jwt keys."""
        r = requests.get(f"{BASE_URL}/api/settings/public", timeout=10)
        data = r.json()
        forbidden = ("razorpay_key_id", "razorpay_key_secret", "smtp_password",
                     "jwt_secret", "resend_api_key", "twilio_auth_token")
        for k in forbidden:
            assert k not in data, f"public leak: {k}"

    def test_admin_settings_lists_all_keys(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/settings",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200
        keys = {d["key"] for d in r.json()}
        for k in ("outstation_notice", "booking_fee_note", "outstation_clause"):
            assert k in keys, f"admin listing missing {k}"

    def test_public_settings_is_unauthenticated(self):
        """Confirm no auth headers required."""
        s = requests.Session()  # no Authorization header
        r = s.get(f"{BASE_URL}/api/settings/public", timeout=10)
        assert r.status_code == 200


class TestAdminEditRoundTrip:
    def test_admin_edit_outstation_notice_and_public_reflects(self, admin_token):
        original_r = requests.get(f"{BASE_URL}/api/settings/public", timeout=10)
        original_value = original_r.json().get("outstation_notice")
        assert original_value

        new_value = "Custom notice for {artist_city} to {event_city} TEST_ITER32"
        try:
            put_r = requests.put(
                f"{BASE_URL}/api/admin/settings/outstation_notice",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"value": new_value},
                timeout=15,
            )
            assert put_r.status_code == 200, put_r.text
            # Verify public read
            pub_r = requests.get(f"{BASE_URL}/api/settings/public", timeout=10)
            assert pub_r.json().get("outstation_notice") == new_value
        finally:
            # Restore
            requests.put(
                f"{BASE_URL}/api/admin/settings/outstation_notice",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"value": original_value},
                timeout=15,
            )

    def test_admin_settings_requires_auth(self):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings/outstation_notice",
            json={"value": "x"},
            timeout=10,
        )
        assert r.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────
# Booking outstation snapshot + contract generation
# ─────────────────────────────────────────────────────────────
def _future_date(days_ahead: int) -> str:
    # Include seconds since epoch to avoid clashing with previously booked dates on retries
    import random
    return (datetime.utcnow() + timedelta(days=days_ahead + random.randint(0, 90))).strftime("%Y-%m-%d")


def _create_booking(customer_token, priya_full, city: str, day_offset: int):
    # priya_full has shape { profile, user, packages, media, reviews, availability }
    profile = priya_full.get("profile", {})
    artist_uid = profile.get("user_id") or priya_full.get("user", {}).get("id")
    pkg_id = priya_full["packages"][0]["id"]

    # Auto-select mandatory artist add-ons
    ad_r = requests.get(f"{BASE_URL}/api/artists/{artist_uid}/addons", timeout=10)
    mandatory = []
    if ad_r.status_code == 200:
        for a in (ad_r.json() or []):
            if a.get("is_mandatory"):
                mandatory.append({"addon_id": a["id"], "quantity": 1})

    body = {
        "artist_id": artist_uid,
        "package_id": pkg_id,
        "addons": [],
        "addon_selections": mandatory,
        "event_date": _future_date(day_offset),
        "event_time": "8:00 PM",
        "event_type": "Wedding",
        "venue": "The Leela Palace",
        "city": city,
        "guests": "300-600",
        "language_pref": "Hindi",
        "notes": "TEST_ITER32 outstation booking",
        "customer_name": "TEST Customer",
        "customer_phone": "+911234567890",
        "customer_email": "customer@booktalent.com",
        "coupon_code": "",
    }
    r = requests.post(
        f"{BASE_URL}/api/bookings",
        headers={"Authorization": f"Bearer {customer_token}"},
        json=body,
        timeout=20,
    )
    assert r.status_code in (200, 201), f"create_booking failed: {r.status_code} {r.text}"
    return r.json()


def _confirm_payment(customer_token, booking_id: str):
    init = requests.post(
        f"{BASE_URL}/api/payments/init",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"booking_id": booking_id, "method": "card"},
        timeout=15,
    )
    assert init.status_code == 200, f"payment init failed: {init.text}"
    ver = requests.post(
        f"{BASE_URL}/api/payments/verify",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "booking_id": booking_id,
            "payment_id": init.json()["payment_id"],
            "mock_otp": "123456",
        },
        timeout=15,
    )
    assert ver.status_code == 200, f"payment verify failed: {ver.text}"


def _artist_accept(artist_token, booking_id: str):
    r = requests.post(
        f"{BASE_URL}/api/bookings/{booking_id}/action",
        headers={"Authorization": f"Bearer {artist_token}"},
        json={"action": "accept", "reason": None},
        timeout=15,
    )
    assert r.status_code == 200, f"artist accept failed: {r.status_code} {r.text}"


def _get_booking(customer_token, bid: str):
    r = requests.get(
        f"{BASE_URL}/api/bookings/{bid}",
        headers={"Authorization": f"Bearer {customer_token}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Endpoint wraps as {booking, artist, artist_profile, customer}
    return data.get("booking", data)


def _get_contract_for_booking(customer_token, bid: str):
    # Fetch via /contracts/mine and find booking
    r = requests.get(
        f"{BASE_URL}/api/contracts/mine",
        headers={"Authorization": f"Bearer {customer_token}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    for c in r.json():
        if c.get("booking_id") == bid:
            return c
    return None


class TestOutstationBooking:
    def test_outstation_booking_snapshot_and_contract(self, customer_token, artist_token, priya_full):
        assert priya_full.get("profile", {}).get("city"), "Priya missing city"
        # Outstation: event in Delhi, Priya in Mumbai
        booking = _create_booking(customer_token, priya_full, city="Delhi", day_offset=45)
        bid = booking["id"]

        # Snapshot at creation time
        assert booking.get("is_outstation") is True
        assert (booking.get("artist_city") or "").lower() == "mumbai"
        assert booking.get("event_city") == "Delhi"

        # Fetched via GET should match
        got = _get_booking(customer_token, bid)
        assert got.get("is_outstation") is True
        assert got.get("event_city") == "Delhi"

        # Complete payment → then artist accepts → contract is generated
        _confirm_payment(customer_token, bid)
        _artist_accept(artist_token, bid)

        contract = _get_contract_for_booking(customer_token, bid)
        assert contract is not None, "contract not created after artist accept"
        body = contract["body"]
        assert "OUTSTATION LOGISTICS" in body, "outstation clause header missing"
        assert "Mumbai" in body and "Delhi" in body, "artist_city → event_city not present in contract"
        assert "FEE INCLUSION NOTE" in body, "fee inclusion note missing"

    def test_same_city_booking_no_outstation(self, customer_token, artist_token, priya_full):
        booking = _create_booking(customer_token, priya_full, city="Mumbai", day_offset=60)
        bid = booking["id"]
        assert booking.get("is_outstation") is False
        assert booking.get("event_city") == "Mumbai"
        assert (booking.get("artist_city") or "").lower() == "mumbai"

        _confirm_payment(customer_token, bid)
        _artist_accept(artist_token, bid)

        contract = _get_contract_for_booking(customer_token, bid)
        assert contract is not None
        body = contract["body"]
        assert "OUTSTATION LOGISTICS" not in body, "same-city booking must not include outstation block"
        # Fee inclusion note should always be present
        assert "FEE INCLUSION NOTE" in body


class TestPricingRegression:
    def test_pricing_still_5pct_and_18pct_gst(self, customer_token, priya_full):
        booking = _create_booking(customer_token, priya_full, city="Bangalore", day_offset=90)
        pricing = booking.get("pricing", {})
        artist_fee = float(pricing.get("artist_fee") or (pricing.get("package_fee", 0) + pricing.get("addons_total", 0)))
        platform_fee = float(pricing.get("platform_fee"))
        gst = float(pricing.get("gst"))
        # 5% of artist_fee ±1 rupee rounding
        assert abs(platform_fee - round(artist_fee * 0.05)) <= 1, f"platform_fee ≠ 5% (got {platform_fee}, expected ~{artist_fee*0.05})"
        # 18% GST on platform_fee ±1 rupee
        assert abs(gst - round(platform_fee * 0.18)) <= 1, f"gst ≠ 18% of platform_fee (got {gst}, expected ~{platform_fee*0.18})"
