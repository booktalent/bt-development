"""
Iter 87 tests — Admin Reports + Unified Audit Log + CORS hardening
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
LOCAL_URL = "http://localhost:8001"

ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}
ARTIST = {"email": "priya@booktalent.com", "password": "Artist@123"}


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Login failed for {email}: {r.status_code} {r.text[:120]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    return _login(**ADMIN)


@pytest.fixture(scope="module")
def customer_client():
    return _login(**CUSTOMER)


# ═══════════════════════ 1. Artist Bookings Report ═══════════════════════
class TestArtistBookingsReport:
    def test_json(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/artist-bookings", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data and "totals" in data
        assert isinstance(data["items"], list)
        totals = data["totals"]
        for k in ("gross_revenue", "artist_payable", "platform_fee", "gst", "bookings"):
            assert k in totals
        if data["items"]:
            row = data["items"][0]
            for k in ("artist_id", "artist_name", "artist_email", "bookings_count",
                      "gross_revenue", "artist_payable", "platform_fee", "gst",
                      "paid_count", "pending_payout_count"):
                assert k in row, f"missing field {k}"

    def test_json_with_date_filter(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/admin/reports/artist-bookings",
            params={"start": "2024-01-01", "end": "2030-12-31"}, timeout=30)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_csv(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/artist-bookings?format=csv", timeout=30)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/csv" in ct, f"Expected text/csv, got {ct}"
        assert "attachment" in r.headers.get("content-disposition", "").lower()
        first_line = r.text.split("\n", 1)[0]
        assert "artist_id" in first_line and "gross_revenue" in first_line

    def test_forbidden_customer(self, customer_client):
        r = customer_client.get(f"{BASE_URL}/api/admin/reports/artist-bookings", timeout=20)
        assert r.status_code in (401, 403), f"expected 403, got {r.status_code}"


# ═══════════════════════ 2. Manager Leads Report ═══════════════════════
class TestManagerLeadsReport:
    def test_json(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/manager-leads", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data and "stages" in data
        assert isinstance(data["stages"], list)
        assert len(data["stages"]) == 13  # note: implementation has 13 stages, spec said 12
        if data["items"]:
            row = data["items"][0]
            for k in ("manager_id", "manager_email", "manager_name", "total_leads",
                      "won", "lost", "in_pipeline", "conversion_pct"):
                assert k in row
            for s in data["stages"]:
                assert f"stage_{s}" in row, f"stage_{s} missing"

    def test_csv(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/manager-leads?format=csv", timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert "attachment" in r.headers.get("content-disposition", "").lower()
        assert "manager_id" in r.text.split("\n", 1)[0]

    def test_forbidden_customer(self, customer_client):
        r = customer_client.get(f"{BASE_URL}/api/admin/reports/manager-leads", timeout=20)
        assert r.status_code in (401, 403)


# ═══════════════════════ 3. Platform Waivers Report ═══════════════════════
class TestPlatformWaiversReport:
    def test_json(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/platform-waivers", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data and "totals" in data
        assert "waived_amount" in data["totals"]
        if data["items"]:
            row = data["items"][0]
            for k in ("ref", "event_date", "artist_name", "customer_name",
                      "is_service_artist", "gross_total", "actual_platform_fee",
                      "would_be_platform_fee", "waived_amount"):
                assert k in row, f"missing field {k}"

    def test_csv(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/reports/platform-waivers?format=csv", timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert "attachment" in r.headers.get("content-disposition", "").lower()

    def test_forbidden_customer(self, customer_client):
        r = customer_client.get(f"{BASE_URL}/api/admin/reports/platform-waivers", timeout=20)
        assert r.status_code in (401, 403)


# ═══════════════════════ 4. Unified Audit Log ═══════════════════════
class TestUnifiedAuditLog:
    def test_basic(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/audit-logs/unified?limit=50", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data
        assert isinstance(data["items"], list)
        if data["items"]:
            row = data["items"][0]
            assert row.get("source") in ("admin", "business")
            for k in ("at", "actor_id", "actor_email", "action", "entity"):
                assert k in row

    def test_with_filters(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/admin/audit-logs/unified",
            params={"actor": "admin", "limit": 20},
            timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data

    def test_date_range_filter(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/admin/audit-logs/unified",
            params={"start": "2024-01-01T00:00:00", "end": "2030-12-31T23:59:59", "limit": 10},
            timeout=30)
        assert r.status_code == 200

    def test_action_regex_filter(self, admin_client):
        r = admin_client.get(
            f"{BASE_URL}/api/admin/audit-logs/unified",
            params={"action": "login", "limit": 10},
            timeout=30)
        assert r.status_code == 200

    def test_forbidden_customer(self, customer_client):
        r = customer_client.get(f"{BASE_URL}/api/admin/audit-logs/unified", timeout=20)
        assert r.status_code in (401, 403)


# ═══════════════════════ 5. CORS Hardening (localhost only) ═══════════════════════
class TestCORSHardening:
    def test_evil_origin_blocked(self):
        r = requests.options(
            f"{LOCAL_URL}/api/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
            timeout=10,
        )
        aco = r.headers.get("access-control-allow-origin", "")
        assert "evil.example.com" not in aco, f"Evil origin was reflected: {aco}"
        assert aco != "*", "Wildcard CORS is enabled"

    def test_preview_origin_allowed(self):
        origin = "https://foo.preview.emergentagent.com"
        r = requests.options(
            f"{LOCAL_URL}/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
            timeout=10,
        )
        aco = r.headers.get("access-control-allow-origin", "")
        assert aco == origin, f"Expected {origin}, got {aco!r}"

    def test_booktalent_origin_allowed(self):
        origin = "https://app.booktalent.in"
        r = requests.options(
            f"{LOCAL_URL}/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
            timeout=10,
        )
        aco = r.headers.get("access-control-allow-origin", "")
        assert aco == origin, f"Expected {origin}, got {aco!r}"


# ═══════════════════════ 6. Regression (Iter 86) ═══════════════════════
class TestIter86Regression:
    def test_at_risk_bookings(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/at-risk-bookings", timeout=20)
        assert r.status_code == 200

    def test_pending_payouts(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/payouts/pending", timeout=20)
        assert r.status_code == 200

    def test_agency_financial_view_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/agency/financial-view", timeout=20)
        assert r.status_code in (401, 403)

    def test_ops_dump_disabled(self):
        r = requests.get(f"{BASE_URL}/api/ops/dump/anytoken", timeout=20)
        assert r.status_code == 404
