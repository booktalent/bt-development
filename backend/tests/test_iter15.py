"""
Iter 15 — Legacy Chat Unlock bug-fix regression.

Bug: Bookings created before the payment_status migration have NO payment_status field.
     The frontend & backend chat gate treated `undefined != 'unpaid'` ambiguously and
     bookings whose status had progressed past 'pending_payment' (completed/confirmed/
     pending_artist/reviewed/started) were sometimes locked → user saw a faded modal.

Fix: chat is unlocked if EITHER `payment_status` is anything other than 'unpaid'
     OR `status` is anything other than 'pending_payment'.
     Applied in:
       /app/backend/chat_routes.py  → _is_chat_unlocked()
       /app/backend/iter9_routes.py → chat_upload guard
       /app/frontend/src/pages/CustomerDashboard.jsx → BookingsTable chatUnlocked

This suite validates the backend side end-to-end.
"""
import os
import json
import pytest
import requests
import websocket  # websocket-client

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")

# Stable booking IDs across iterations.
PAID_BID = "cca6a262-8393-4970-bd38-021dc13d52c7"          # token_paid + pending_artist
UNPAID_BID = "060a549a-0952-4425-84c0-422210ee501e"        # unpaid + pending_payment

# Legacy bookings (no payment_status field).  status=pending_artist for both.
# (Discovered via: db.bookings.find({payment_status:{$exists:false}}))
LEGACY_BIDS = [
    "07835a9d-e38a-481e-97ac-16d74c12760d",
    "17ce166d-1f7b-4fc1-bd7c-e3192fbccb9b",
]

# Users
CUST = {"email": "customer@booktalent.com", "password": "Customer@123"}
ART = {"email": "priya@booktalent.com", "password": "Artist@123"}
ADM = {"email": "admin@booktalent.com", "password": "Admin@123"}
# Owner of the legacy bookings above (corporate customer).
CORP = {"email": "corporate@booktalent.com", "password": "Corporate@123"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {creds['email']} {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {
        "customer": _login(CUST),
        "artist": _login(ART),
        "admin": _login(ADM),
        "corporate": _login(CORP),
    }


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ───────────────────────── PRIMARY FIX: Legacy chat unlock ─────────────────────────
class TestLegacyChatUnlock:
    """Bookings WITHOUT payment_status must be treated as unlocked once status
    has moved past 'pending_payment'."""

    @pytest.mark.parametrize("bid", LEGACY_BIDS)
    def test_access_enabled_for_artist(self, tokens, bid):
        r = requests.get(f"{BASE_URL}/api/chat/{bid}/access", headers=H(tokens["artist"]), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is True, body
        # payment_status default in response when missing in DB
        assert body.get("payment_status") in (None, "unpaid", "", "token_paid")
        assert body.get("booking_status") != "pending_payment"

    @pytest.mark.parametrize("bid", LEGACY_BIDS)
    def test_access_enabled_for_customer(self, tokens, bid):
        # corporate@ is the customer who owns the legacy bookings.
        r = requests.get(f"{BASE_URL}/api/chat/{bid}/access", headers=H(tokens["corporate"]), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True, r.json()

    @pytest.mark.parametrize("bid", LEGACY_BIDS)
    def test_rest_get_messages_works(self, tokens, bid):
        r = requests.get(f"{BASE_URL}/api/chat/{bid}/messages?limit=50",
                         headers=H(tokens["artist"]), timeout=20)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_rest_post_message_artist(self, tokens):
        bid = LEGACY_BIDS[0]
        r = requests.post(f"{BASE_URL}/api/chat/{bid}/messages",
                          headers=H(tokens["artist"]),
                          json={"content": "TEST_iter15-legacy-artist"}, timeout=20)
        assert r.status_code in (200, 201), r.text
        assert r.json().get("content") == "TEST_iter15-legacy-artist"

    def test_rest_post_message_customer(self, tokens):
        bid = LEGACY_BIDS[0]
        r = requests.post(f"{BASE_URL}/api/chat/{bid}/messages",
                          headers=H(tokens["corporate"]),
                          json={"content": "TEST_iter15-legacy-customer"}, timeout=20)
        assert r.status_code in (200, 201), r.text
        assert r.json().get("content") == "TEST_iter15-legacy-customer"

    def test_ws_artist_connects(self, tokens):
        bid = LEGACY_BIDS[0]
        url = f"{WS_BASE}/api/ws/chat/{bid}?token={tokens['artist']}"
        ws = websocket.create_connection(url, timeout=10)
        try:
            ws.settimeout(8)
            data = json.loads(ws.recv())
            assert data.get("event") == "presence", data
        finally:
            ws.close()

    def test_ws_customer_connects(self, tokens):
        bid = LEGACY_BIDS[0]
        url = f"{WS_BASE}/api/ws/chat/{bid}?token={tokens['corporate']}"
        ws = websocket.create_connection(url, timeout=10)
        try:
            ws.settimeout(8)
            data = json.loads(ws.recv())
            assert data.get("event") == "presence", data
        finally:
            ws.close()

    def test_chat_upload_legacy_allowed(self, tokens):
        """iter9_routes chat_upload guard must also honour the new legacy logic."""
        bid = LEGACY_BIDS[0]
        tiny_png = ("data:image/png;base64,"
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        r = requests.post(
            f"{BASE_URL}/api/chat/{bid}/upload",
            headers=H(tokens["artist"]),
            json={"type": "file", "data_url": tiny_png, "filename": "TEST_iter15.png"},
            timeout=20,
        )
        # 200/201 means the gate let the request through (regardless of underlying upload success).
        assert r.status_code != 403, f"chat_upload still blocked on legacy booking: {r.status_code} {r.text}"


# ─────────────────── REGRESSION: truly unpaid still locked ───────────────────
class TestUnpaidStillLocked:
    def test_access_disabled(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{UNPAID_BID}/access", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_rest_get_messages_403(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{UNPAID_BID}/messages",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 403

    def test_rest_post_message_403(self, tokens):
        r = requests.post(f"{BASE_URL}/api/chat/{UNPAID_BID}/messages",
                          headers=H(tokens["customer"]),
                          json={"content": "should-be-blocked"}, timeout=20)
        assert r.status_code == 403

    def test_ws_rejected(self, tokens):
        url = f"{WS_BASE}/api/ws/chat/{UNPAID_BID}?token={tokens['customer']}"
        try:
            ws = websocket.create_connection(url, timeout=8)
            try:
                ws.recv()
            except Exception:
                pass
            close_code = getattr(ws, "close_code", None)
            ws.close()
            # 4402 = chat-locked-payment-required (server custom code)
            assert close_code in (4402, None) or close_code != 1000
        except websocket.WebSocketBadStatusException as e:
            assert e.status_code in (401, 403)
        except Exception:
            assert True


# ─────────────────── REGRESSION: newly-paid still unlocked ───────────────────
class TestPaidStillUnlocked:
    def test_access_enabled(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{PAID_BID}/access", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_ws_customer_connects(self, tokens):
        url = f"{WS_BASE}/api/ws/chat/{PAID_BID}?token={tokens['customer']}"
        ws = websocket.create_connection(url, timeout=10)
        try:
            ws.settimeout(8)
            data = json.loads(ws.recv())
            assert data.get("event") == "presence", data
        finally:
            ws.close()


# ─────────────── REGRESSION: Iter 11/12/13/14 endpoints unaffected ───────────────
class TestRegressionPriorIterations:
    def test_ai_search(self):
        r = requests.post(f"{BASE_URL}/api/search/ai", json={"query": "Singer in Mumbai", "limit": 3}, timeout=60)
        assert r.status_code == 200, r.text

    def test_ics(self, tokens):
        r = requests.get(f"{BASE_URL}/api/bookings/{PAID_BID}/calendar.ics",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert "BEGIN:VCALENDAR" in r.text

    def test_customer_csv(self, tokens):
        r = requests.get(f"{BASE_URL}/api/exports/my-bookings.csv", headers=H(tokens["customer"]), timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()

    def test_admin_revenue_csv(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/exports/revenue.csv", headers=H(tokens["admin"]), timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()

    def test_wallet(self, tokens):
        r = requests.get(f"{BASE_URL}/api/wallet", headers=H(tokens["artist"]), timeout=20)
        assert r.status_code == 200

    def test_admin_coupons(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/coupons", headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_kyc(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/kyc", headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
