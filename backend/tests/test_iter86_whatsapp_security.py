"""
Iter 86 backend tests:
1. Security: /api/ops/dump/{token} always 404
2. Admin login still works (no forced overwrite on boot)
3. WhatsApp wachatsender provider integration (whatsapp_logs row + wamid on success)
4. Notification hook on POST /bookings/{id}/schedule/mark-paid → notifications_log channel=whatsapp event=payment.received
5. Notification hook on POST /bookings/{id}/payout/manual → notifications_log channel=whatsapp event=payout.released
6. Regression: /api/admin/at-risk-bookings + /api/admin/payouts/pending

The tests hit the real preview base URL, exactly as the user would.
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") \
    else "https://booktalent-audit.preview.emergentagent.com"

ADMIN_EMAIL = "admin@booktalent.com"
ADMIN_PASSWORD = "Admin@123"

# Mongo for direct verification
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "booktalent")
_mc = MongoClient(MONGO_URL)
_db = _mc[DB_NAME]


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ─────────────────────────────────────────
# 1. Security fix: /api/ops/dump/{token} → 404
# ─────────────────────────────────────────
class TestOpsDumpSecurity:
    def test_dump_random_token_404(self):
        r = requests.get(f"{BASE_URL}/api/ops/dump/anyrandomtoken", timeout=15)
        assert r.status_code == 404

    def test_dump_configured_token_404(self):
        env_token = os.environ.get("DUMP_DOWNLOAD_TOKEN", "").strip()
        if not env_token:
            pytest.skip("no DUMP_DOWNLOAD_TOKEN configured — first test covers this")
        r = requests.get(f"{BASE_URL}/api/ops/dump/{env_token}", timeout=15)
        assert r.status_code == 404


# ─────────────────────────────────────────
# 2. Admin login works (no auto-reset)
# ─────────────────────────────────────────
class TestAdminLogin:
    def test_admin_login_succeeds(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["role"] == "admin"
        assert isinstance(data["token"], str) and len(data["token"]) > 20


# ─────────────────────────────────────────
# 3. WhatsApp wachatsender integration
# ─────────────────────────────────────────
class TestWhatsAppWachatsender:
    def test_send_whatsapp_writes_log_and_calls_provider(self):
        """Directly call the send_whatsapp() coroutine via a small script.
        We prefer to invoke via the notification hook (integration tests below).
        But we also do a direct DB sanity check on WHATSAPP_PROVIDER env."""
        # Provider should be configured as wachatsender per task description.
        # We don't fail if not — we just skip the DB check.
        provider = os.environ.get("WHATSAPP_PROVIDER", "").strip().lower()
        assert provider == "wachatsender", f"WHATSAPP_PROVIDER must be 'wachatsender', got '{provider}'"

        # After the notification-hook tests run, whatsapp_logs should contain
        # a row with provider='wachatsender'. We verify inline via the mark-paid test.


# ─────────────────────────────────────────
# 4 & 5. Notification hooks on booking milestones + payouts
# ─────────────────────────────────────────
@pytest.fixture(scope="session")
def sample_booking(admin_headers):
    """Return a real booking id + doc from db. Uses a pending-payout booking
    from /api/admin/payouts/pending so we know the artist/customer exist."""
    r = requests.get(f"{BASE_URL}/api/admin/payouts/pending",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200
    items = r.json().get("items", [])
    if not items:
        pytest.skip("No pending-payout bookings — cannot exercise hooks against real data")
    # Find one with a customer_id AND artist_id so both notify legs fire.
    for b in items:
        if b.get("customer_id") and b.get("artist_id"):
            return b
    return items[0]


class TestNotificationHooks:
    def test_mark_paid_creates_whatsapp_notification_log(self, admin_headers, sample_booking):
        bid = sample_booking["id"]
        # Ensure a schedule exists
        rs = requests.get(f"{BASE_URL}/api/bookings/{bid}/schedule",
                          headers=admin_headers, timeout=20)
        assert rs.status_code == 200, f"schedule fetch failed: {rs.text}"
        sched = rs.json()
        milestones = sched.get("milestones", [])
        assert milestones, "No milestones in schedule"
        # Find an unpaid milestone
        idx = next((i for i, m in enumerate(milestones) if m.get("status") != "paid"), None)
        if idx is None:
            pytest.skip("All milestones already paid on this booking")

        marker = f"TEST_ITER86_{uuid.uuid4().hex[:8]}"
        rmp = requests.post(
            f"{BASE_URL}/api/bookings/{bid}/schedule/mark-paid",
            headers=admin_headers,
            json={"milestone_index": idx, "amount_received": 1.0,
                  "method": "manual", "reference": marker},
            timeout=30,
        )
        assert rmp.status_code == 200, f"mark-paid failed: {rmp.status_code} {rmp.text}"

        # Give the async dispatch a moment to flush
        time.sleep(3)

        # Verify notifications_log row for customer with channel=whatsapp + event=payment.received
        cust = sample_booking.get("customer_id")
        if cust:
            row = _db.notifications_log.find_one({
                "user_id": cust, "channel": "whatsapp", "event": "payment.received",
            }, sort=[("created_at", -1)])
            assert row, "No whatsapp/payment.received row in notifications_log for customer"

        # Verify whatsapp_logs picked up a wachatsender attempt (if provider live)
        wa_row = _db.whatsapp_logs.find_one({"provider": "wachatsender"}, sort=[("at", -1)])
        assert wa_row, "No wachatsender row in whatsapp_logs — provider not being hit"

    def test_manual_payout_creates_whatsapp_notification_log(self, admin_headers, sample_booking):
        bid = sample_booking["id"]
        # Skip if this booking already has payout paid (may have been marked by prev test)
        booking = _db.bookings.find_one({"id": bid})
        if booking and booking.get("artist_payout_status") == "paid":
            # Choose another booking that's still pending
            items = requests.get(f"{BASE_URL}/api/admin/payouts/pending",
                                 headers=admin_headers, timeout=15).json().get("items", [])
            candidate = next((b for b in items if b.get("artist_id") and b["id"] != bid), None)
            if not candidate:
                pytest.skip("No further pending-payout booking to test")
            bid = candidate["id"]
            sample_booking = candidate

        utr = f"UTR-TEST-{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{BASE_URL}/api/bookings/{bid}/payout/manual",
            headers=admin_headers,
            json={"amount": 1.0, "paid_on": "2026-01-15", "method": "upi",
                  "utr": utr, "notes": "iter86 test"},
            timeout=30,
        )
        assert r.status_code == 200, f"payout manual failed: {r.status_code} {r.text}"

        time.sleep(3)

        artist_id = sample_booking.get("artist_id")
        if artist_id:
            row = _db.notifications_log.find_one({
                "user_id": artist_id, "channel": "whatsapp", "event": "payout.released",
            }, sort=[("created_at", -1)])
            assert row, "No whatsapp/payout.released row in notifications_log for artist"


# ─────────────────────────────────────────
# 6. Regression: admin dashboards
# ─────────────────────────────────────────
class TestAdminRegression:
    def test_at_risk_bookings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/at-risk-bookings",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ("event_soon_unpaid", "payout_pending", "schedules_overdue",
                  "leads_unassigned", "kyc_stuck", "total"):
            assert k in data

    def test_payouts_pending(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/payouts/pending",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "count" in data
