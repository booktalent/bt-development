"""Tests for Feb-2026 requirement batch: finance quote, admin stats new KPIs,
manager add-customer/booking-on-behalf, tech rider, advance-pending broadcast,
KYC accept-terms."""
import io
import os
import time
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
MANAGER = ("test-mgr@booktalent.com", "Manager@123")
ARTIST = ("priya@booktalent.com", "Artist@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s, r.json()


@pytest.fixture(scope="module")
def admin_s():
    s, _ = _login(*ADMIN)
    return s


@pytest.fixture(scope="module")
def manager_s():
    s, _ = _login(*MANAGER)
    return s


@pytest.fixture(scope="module")
def artist_s():
    s, u = _login(*ARTIST)
    return s, u["user"]


@pytest.fixture(scope="module")
def priya_artist_id(artist_s):
    _, u = artist_s
    return u["id"]


# ─── 1. finance/quote ─────────────────────────────────────────────────
class TestFinanceQuote:
    def test_quote_normal_artist(self, priya_artist_id):
        r = requests.get(f"{API}/finance/quote",
                         params={"artist_id": priya_artist_id, "package_fee": 100000}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("platform_fee") == 5000, d
        assert d.get("gst_amount", 0) > 0, d
        assert d.get("gst_visible") is True, d
        assert d.get("is_service_artist") is False, d

    def test_quote_service_artist(self, admin_s):
        # find any service artist profile
        prof = None
        r = admin_s.get(f"{API}/admin/kyc/queue", params={"limit": 200})
        # fallback: query directly via any list
        # try to fetch service artist by iterating list
        r2 = admin_s.get(f"{API}/admin/artists", timeout=30)
        if r2.status_code == 200:
            artists = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
            for a in artists:
                if a.get("is_service_artist"):
                    prof = a
                    break
        if not prof:
            pytest.skip("No service artist found in DB")
        aid = prof.get("user_id") or prof.get("id")
        r = requests.get(f"{API}/finance/quote",
                         params={"artist_id": aid, "package_fee": 100000}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("is_service_artist") is True
        assert "waiver_message" in d
        assert d.get("platform_fee_waiver") == -d.get("platform_fee")


# ─── 2. admin/stats new fields ────────────────────────────────────────
class TestAdminStats:
    def test_stats_has_new_kpis(self, admin_s):
        r = admin_s.get(f"{API}/admin/stats", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["new_leads", "active_bookings", "upcoming_events",
                  "agreements_pending", "customer_payment_pending",
                  "overdue_payments", "artist_payout_pending",
                  "agency_bookings", "remaining_amount"]:
            assert k in d, f"missing key {k}"
            assert isinstance(d[k], (int, float)), f"{k} not numeric: {d[k]!r}"


# ─── 3. manager add customer + list + booking-on-behalf ───────────────
class TestManagerFlow:
    unique_email = f"TEST_mgr_cust_{int(time.time())}@example.com"

    def test_add_customer_creates(self, manager_s):
        r = manager_s.post(f"{API}/manager/customers",
                           json={"email": self.unique_email, "first_name": "TEST"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        # first call may or may not be existing (depends on prior state)
        assert "user" in d
        TestManagerFlow.new_id = d["user"]["id"]

    def test_add_customer_idempotent(self, manager_s):
        r = manager_s.post(f"{API}/manager/customers",
                           json={"email": self.unique_email, "first_name": "TEST"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("existing") is True

    def test_list_customers(self, manager_s):
        r = manager_s.get(f"{API}/manager/customers", params={"q": "TEST_mgr_cust"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)

    def test_booking_on_behalf(self, manager_s, priya_artist_id):
        cid = getattr(TestManagerFlow, "new_id", None)
        assert cid, "no customer created"
        payload = {
            "customer_id": cid,
            "artist_id": priya_artist_id,
            "package_fee": 50000,
            "event_type": "Corporate",
            "event_date": "2026-12-31",
            "number_of_days": 1,
            "venue": "TEST Venue",
            "venue_address": "TEST Address",
            "city": "Mumbai",
        }
        r = manager_s.post(f"{API}/manager/bookings", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        bk = d["booking"]
        assert bk.get("assigned_manager_id"), bk
        assert bk.get("created_on_behalf") is True
        assert float(bk.get("pricing", {}).get("total") or 0) > 0


# ─── 4. tech rider ────────────────────────────────────────────────────
class TestTechRider:
    def test_upload_and_meta(self, artist_s):
        s, u = artist_s
        pdf = b"%PDF-1.4\n%TEST\n"
        r = s.post(
            f"{API}/artist/tech-rider/upload",
            files={"file": ("rider.pdf", pdf, "application/pdf")},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        # meta
        r2 = s.get(f"{API}/artist/tech-rider/mine", timeout=30)
        assert r2.status_code == 200
        f = r2.json().get("file")
        assert f and f.get("url"), r2.json()

    def test_download(self, artist_s):
        s, u = artist_s
        r = s.get(f"{API}/artist/tech-rider/{u['id']}/download", timeout=30, allow_redirects=True)
        assert r.status_code == 200, r.text[:200]

    def test_delete(self, artist_s):
        s, _ = artist_s
        r = s.delete(f"{API}/artist/tech-rider/mine", timeout=30)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ─── 5. advance-pending broadcast ─────────────────────────────────────
class TestAdvanceBroadcast:
    def test_broadcast(self, admin_s):
        r = admin_s.post(f"{API}/admin/advance-pending/broadcast", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert isinstance(d.get("bookings_touched"), int)
        assert isinstance(d.get("notifications_pushed"), int)
        assert d["bookings_touched"] >= 0
        assert d["notifications_pushed"] >= 0


# ─── 6. KYC accept-terms ──────────────────────────────────────────────
class TestKycAcceptTerms:
    def test_accept_terms(self, admin_s):
        # Find candidate artist in kyc_approved or tnc_pending
        # Use admin/kyc/queue with status
        candidate = None
        for st in ("tnc_pending", "kyc_approved"):
            r = admin_s.get(f"{API}/admin/kyc/queue", params={"status": st, "limit": 5})
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    candidate = items[0]
                    break
        if not candidate:
            # Try to move a kyc_under_review artist to approved
            r = admin_s.get(f"{API}/admin/kyc/queue", params={"status": "kyc_under_review", "limit": 5})
            items = r.json().get("items", []) if r.status_code == 200 else []
            if not items:
                pytest.skip("No KYC-approvable artist to test accept-terms")
            aid = items[0]["user_id"]
            rv = admin_s.post(f"{API}/admin/kyc/{aid}/review",
                              json={"action": "approve", "artist_type": "normal"})
            if rv.status_code != 200:
                pytest.skip(f"Cannot approve artist for test: {rv.status_code} {rv.text}")
            candidate = {"user_id": aid}

        # Now we need to log in as that artist. We can't — we don't know password.
        # Only priya is available with known creds. Check if priya qualifies.
        priya_s, priya_u = _login(*ARTIST)
        r = priya_s.get(f"{API}/kyc/me", timeout=30)
        if r.status_code != 200:
            pytest.skip("cannot fetch priya kyc")
        st = r.json().get("kyc_status")
        if st not in ("kyc_approved", "tnc_pending"):
            pytest.skip(f"priya kyc_status={st}; cannot test accept-terms without approvable artist login")
        r = priya_s.post(f"{API}/kyc/accept-terms", json={"accepted": True}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("kyc_status") == "live"
        assert d.get("agreement_url")
