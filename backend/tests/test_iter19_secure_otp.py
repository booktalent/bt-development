"""Iter19 — secure OTP generation + auth regression tests."""
import os
import re
import sys
import pytest
import requests
from unittest.mock import patch

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from frontend/.env directly
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

sys.path.insert(0, "/app/backend")


# ---------- Module-level (secrets / random) checks ----------
class TestEmailServiceModule:
    """Verify email_service.py uses secrets, not random."""

    def test_secrets_imported(self):
        with open("/app/backend/email_service.py") as f:
            src = f.read()
        assert "import secrets" in src, "email_service.py must import secrets"

    def test_random_not_imported(self):
        with open("/app/backend/email_service.py") as f:
            src = f.read()
        # Should NOT have `import random` or `from random`
        assert not re.search(r"^\s*import\s+random\b", src, re.MULTILINE), \
            "email_service.py must NOT import random"
        assert not re.search(r"^\s*from\s+random\s+import", src, re.MULTILINE), \
            "email_service.py must NOT import from random"

    def test_generate_otp_mock_mode(self):
        """In mock-mode (RESEND_ENABLED False) always returns 123456."""
        import importlib
        import email_service
        importlib.reload(email_service)
        # Force mock mode
        email_service.RESEND_ENABLED = False
        otp = email_service.generate_otp()
        assert otp == "123456", f"mock-mode OTP expected 123456, got {otp}"

    def test_generate_otp_live_mode_uses_secrets(self):
        """When RESEND_ENABLED=True, returns 6-digit strings using secrets."""
        import importlib
        import email_service
        importlib.reload(email_service)
        email_service.RESEND_ENABLED = True
        otps = [email_service.generate_otp() for _ in range(100)]
        # All are 6-digit numeric strings
        for otp in otps:
            assert re.fullmatch(r"\d{6}", otp), f"OTP not 6-digit numeric: {otp}"
            assert 100000 <= int(otp) <= 999999, f"OTP out of range: {otp}"
        # High uniqueness (should be near-100 in a real CSPRNG; allow slack)
        unique = len(set(otps))
        assert unique >= 90, f"Only {unique}/100 unique OTPs — RNG looks broken"

    def test_generate_otp_uses_secrets_randbelow(self):
        """Static verification: source calls secrets.randbelow."""
        with open("/app/backend/email_service.py") as f:
            src = f.read()
        assert "secrets.randbelow" in src, \
            "generate_otp must call secrets.randbelow"


# ---------- Auth regression ----------
class TestAuthRegression:
    def test_customer_login_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "customer@booktalent.com", "password": "Customer@123"},
                          timeout=15)
        assert r.status_code == 200, f"login {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "token" in data and isinstance(data["token"], str) and len(data["token"]) > 10
        assert data["user"]["email"] == "customer@booktalent.com"

    def test_admin_login_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "admin@booktalent.com", "password": "Admin@123"},
                          timeout=15)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_artist_login_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "priya@booktalent.com", "password": "Artist@123"},
                          timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == "priya@booktalent.com"

    def test_register_new_user(self):
        import uuid
        email = f"test_iter19_{uuid.uuid4().hex[:8]}@example.com"
        # Step 1: send OTP (mock returns 123456)
        r0 = requests.post(f"{BASE_URL}/api/auth/email/send",
                           json={"email": email, "name": "Iter19"}, timeout=15)
        assert r0.status_code == 200, f"email/send {r0.status_code}: {r0.text[:200]}"
        # Step 2: verify OTP
        r1 = requests.post(f"{BASE_URL}/api/auth/email/verify",
                           json={"email": email, "otp": "123456"}, timeout=15)
        assert r1.status_code == 200, f"email/verify {r1.status_code}: {r1.text[:200]}"
        # Step 3: register
        r = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"email": email, "password": "TestPass@123",
                                "first_name": "Iter19", "last_name": "Tester",
                                "role": "customer", "phone": "+919999999999"},
                          timeout=15)
        assert r.status_code in (200, 201), f"register {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == email


# ---------- Regression endpoints from iter11-18 ----------
@pytest.fixture(scope="module")
def customer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "customer@booktalent.com", "password": "Customer@123"},
                      timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@booktalent.com", "password": "Admin@123"},
                      timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


class TestRegressionEndpoints:
    PAID = "cca6a262-8393-4970-bd38-021dc13d52c7"
    UNPAID = "060a549a-0952-4425-84c0-422210ee501e"

    def test_chat_access_paid(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/chat/{self.PAID}/access",
                         headers={"Authorization": f"Bearer {customer_token}"}, timeout=15)
        assert r.status_code == 200
        assert r.json().get("enabled") is True

    def test_chat_access_unpaid(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/chat/{self.UNPAID}/access",
                         headers={"Authorization": f"Bearer {customer_token}"}, timeout=15)
        assert r.status_code == 200
        assert r.json().get("enabled") is False

    def test_search_ai(self):
        r = requests.post(f"{BASE_URL}/api/search/ai", json={"query": "DJ in Delhi"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert data.get("total", 0) >= 1, f"expected DJ Vortex hit, got {data}"

    def test_booking_ics(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/bookings/{self.PAID}/calendar.ics",
                         headers={"Authorization": f"Bearer {customer_token}"}, timeout=15)
        assert r.status_code == 200
        assert "BEGIN:VCALENDAR" in r.text

    def test_customer_csv(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/exports/my-bookings.csv",
                         headers={"Authorization": f"Bearer {customer_token}"}, timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_admin_revenue_csv(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/exports/revenue.csv",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_wallet(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/wallet",
                         headers={"Authorization": f"Bearer {customer_token}"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data

    def test_admin_coupons(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/coupons",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_kyc(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/kyc",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200

    def test_reviews_artist(self):
        # priya user_id from search results
        r = requests.post(f"{BASE_URL}/api/search/ai", json={"query": "Priya Sharma"}, timeout=30)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert items, "expected Priya in search"
        uid = items[0].get("user_id") or items[0].get("id")
        r2 = requests.get(f"{BASE_URL}/api/reviews/artist/{uid}", timeout=15)
        assert r2.status_code == 200
