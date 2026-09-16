"""
Iter 58 regression: verify the full customer booking → payment flow still works
end-to-end on the backend. This exists as the anchor test for the P0 bug
"Not authenticated during artist booking payment" — the frontend interceptor
change is UX-only; the backend contract must remain unchanged.
"""
import os
import datetime as dt
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:3000").rstrip("/")
API = f"{BASE_URL}/api"
ARTIST_ID = "aa0ed1cb-6036-480d-a64f-6cc551a2a306"


@pytest.fixture(scope="module")
def customer_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={
        "email": "customer@booktalent.com", "password": "Customer@123"
    })
    assert r.status_code == 200, r.text
    return s


def test_auth_me_probe_401_when_anonymous():
    """A fresh anonymous /auth/me must return 401 (frontend depends on this)."""
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401
    body = r.json()
    assert body.get("detail") in ("Not authenticated", None) or "detail" in body


def test_auth_me_ok_when_logged_in(customer_session):
    r = customer_session.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "customer@booktalent.com"


def test_artist_packages_exist(customer_session):
    r = customer_session.get(f"{API}/artists/{ARTIST_ID}")
    assert r.status_code == 200
    pkgs = r.json().get("packages", [])
    assert isinstance(pkgs, list) and len(pkgs) > 0, "Artist must have packages seeded"


def test_full_booking_payment_flow(customer_session):
    # 1. get a package
    pkgs = customer_session.get(f"{API}/artists/{ARTIST_ID}").json()["packages"]
    pkg = pkgs[0]

    # 2. book
    future = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    payload = {
        "artist_id": ARTIST_ID,
        "package_id": pkg["id"],
        "event_date": future,
        "event_time": "19:00",
        "event_type": "wedding",
        "customer_name": "TEST Iter58",
        "customer_phone": "+919000000058",
        "customer_email": "customer@booktalent.com",
        "venue": "TEST Venue",
        "city": "Mumbai",
        "guests_count": 100,
        "notes": "iter58 regression",
        "addon_selections": [],
        "tnc_accepted": True,
    }
    r = customer_session.post(f"{API}/bookings", json=payload)
    assert r.status_code in (200, 201), r.text
    booking = r.json()
    booking_id = booking["id"]

    # 3. payment init
    r = customer_session.post(f"{API}/payments/init", json={
        "booking_id": booking_id, "method": "card"
    })
    assert r.status_code == 200, r.text
    init = r.json()
    assert "payment_id" in init or "order_id" in init or "razorpay_order_id" in init

    # 4. payment verify (mock OTP)
    verify_payload = {
        "booking_id": booking_id,
        "mock_otp": "123456",
    }
    # Some builds require payment_id/order_id passthrough — include if present
    for k in ("payment_id", "order_id", "razorpay_order_id", "razorpay_payment_id"):
        if k in init:
            verify_payload[k] = init[k]
    r = customer_session.post(f"{API}/payments/verify", json=verify_payload)
    assert r.status_code == 200, r.text
    verified = r.json()

    # 5. verify final booking state
    r = customer_session.get(f"{API}/bookings/{booking_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    final = body.get("booking", body)
    assert final["status"] == "pending_artist", f"unexpected status {final['status']}"
    assert final["payment_status"] == "token_paid", f"unexpected payment_status {final['payment_status']}"


def test_bookings_requires_auth():
    """Anonymous POST /bookings must return 401 so the interceptor can catch it."""
    r = requests.post(f"{API}/bookings", json={"artist_id": ARTIST_ID})
    assert r.status_code == 401
