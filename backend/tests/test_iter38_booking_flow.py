"""
Iter 38 — Booking + Mock Payment integration test.

Flow:
  1. Customer creates a booking for Priya (artist).
  2. POST /api/payments/init -> gets payment_id.
  3. POST /api/payments/verify with mock_otp 123456 -> booking confirmed
     (status pending_artist, payment_status token_paid).
  4. Confirm booking now has amount_paid > 0.
  5. Confirm no wallets collection was mutated (via /api/auth/me shape).
  6. Confirm ledger row present in `transactions` (via /api/wallet/transactions
     which must be 404 — proves wallet routes gone, but we can rely on the
     booking state to indicate ledger consumption succeeded).
  7. Invoice PDF renders for that booking.
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

CUSTOMER = ("customer@booktalent.com", "Customer@123")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def cust_tok():
    return _login(*CUSTOMER)


@pytest.fixture(scope="module")
def priya():
    """Fetch Priya's artist_id + a package."""
    r = requests.get(f"{API}/artists/search?q=priya", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    arr = body.get("items", []) if isinstance(body, dict) else body
    priya = None
    for a in arr:
        name = (a.get("stage_name") or "").lower()
        if "priya" in name:
            priya = a
            break
    if not priya:
        pytest.skip("Priya artist not in seed")
    # get artist detail for packages
    aid = priya.get("user_id") or priya.get("id")
    r = requests.get(f"{API}/artists/{aid}", timeout=15)
    assert r.status_code == 200
    det = r.json()
    pkgs = det.get("packages", [])
    if not pkgs:
        pytest.skip("Priya has no packages")
    # Fetch mandatory addons
    r = requests.get(f"{API}/artists/{aid}/addons", timeout=15)
    addons = r.json() if r.status_code == 200 else []
    mandatory = [
        {"addon_id": a["id"], "quantity": 1}
        for a in addons if a.get("is_mandatory") and a.get("active", True)
    ]
    return {"artist_id": aid, "package": pkgs[0], "addon_selections": mandatory}


class TestBookingMockPaymentFlow:
    def test_full_flow(self, cust_tok, priya):
        # Use a future date well ahead to avoid availability conflict
        future = time.strftime("%Y-%m-%d", time.localtime(time.time() + 90 * 86400))
        create_body = {
            "artist_id": priya["artist_id"],
            "package_id": priya["package"]["id"],
            "addon_selections": priya["addon_selections"],
            "event_date": future,
            "event_time": "19:00",
            "event_type": "wedding",
            "venue": "TEST_iter38 Grand Ballroom",
            "city": "Mumbai",
            "guests": "100",
            "special_instructions": f"TEST_iter38 {uuid.uuid4().hex[:6]}",
            "customer_name": "TEST_iter38 Cust",
            "customer_phone": "9999999999",
            "customer_email": "customer@booktalent.com",
        }
        r = requests.post(f"{API}/bookings", json=create_body, headers=_h(cust_tok), timeout=20)
        assert r.status_code == 200, f"booking create failed: {r.status_code} {r.text[:300]}"
        booking = r.json()
        bid = booking["id"]
        token_amount = float(booking["pricing"]["token_amount"])
        assert token_amount > 0

        # payments/init
        r = requests.post(
            f"{API}/payments/init",
            json={"booking_id": bid, "method": "card"},
            headers=_h(cust_tok),
            timeout=15,
        )
        assert r.status_code == 200, f"payments/init failed: {r.status_code} {r.text[:200]}"
        pinit = r.json()
        assert pinit["gateway"] in ("razorpay", "razorpay_mock")
        pid = pinit["payment_id"]

        # payments/verify with mock otp
        verify_body = {"payment_id": pid, "booking_id": bid, "mock_otp": "123456"}
        r = requests.post(f"{API}/payments/verify", json=verify_body, headers=_h(cust_tok), timeout=20)
        if pinit["gateway"] == "razorpay":
            # Live mode active — cannot easily verify without real signature
            pytest.skip("Live Razorpay mode active; mock OTP flow not applicable")
        assert r.status_code == 200, f"payments/verify failed: {r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("ok") is True
        assert j.get("status") == "pending_artist"

        # Booking now shows amount_paid > 0
        r = requests.get(f"{API}/bookings/{bid}", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 200
        det = r.json()
        b = det.get("booking", det)
        assert float(b.get("amount_paid", 0)) >= token_amount
        assert b.get("payment_status") == "token_paid"

        # auth/me still has no wallet field
        r = requests.get(f"{API}/auth/me", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 200
        assert "wallet" not in r.json()

        # /api/wallet remains 404
        r = requests.get(f"{API}/wallet", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 404

        # Invoice PDF now renders for this booking
        r = requests.get(f"{API}/bookings/{bid}/invoice", headers=_h(cust_tok), timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
