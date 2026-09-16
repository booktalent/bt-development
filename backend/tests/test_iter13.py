"""
Iter 13 — REGRESSION test suite after structural refactor.
server.py split into routes/{reviews,wallet,coupons,blogs,disputes,kyc}.py
Endpoint paths and contracts are UNCHANGED — only the implementation file moved.
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")

PAID_BID = "cca6a262-8393-4970-bd38-021dc13d52c7"
UNPAID_BID = "060a549a-0952-4425-84c0-422210ee501e"
CUSTOMER_UID = "793d2f73-fd1e-4e85-a387-043e7c2378e5"

CUST = {"email": "customer@booktalent.com", "password": "Customer@123"}
ART = {"email": "priya@booktalent.com", "password": "Artist@123"}
ADM = {"email": "admin@booktalent.com", "password": "Admin@123"}

TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {
        "customer": _login(CUST),
        "artist": _login(ART),
        "admin": _login(ADM),
    }


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ────────────── Untouched core endpoints ──────────────
class TestCoreUntouched:
    def test_auth_me(self, tokens):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["email"] == CUST["email"]

    def test_bookings_mine(self, tokens):
        r = requests.get(f"{BASE_URL}/api/bookings/mine", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_artists_search(self):
        r = requests.get(f"{BASE_URL}/api/artists/search", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), (list, dict))

    def test_admin_stats(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200

    def test_contracts_mine(self, tokens):
        r = requests.get(f"{BASE_URL}/api/contracts/mine", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_notifications(self, tokens):
        r = requests.get(f"{BASE_URL}/api/notifications", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200


# ────────────── Wallet (routes/wallet.py) ──────────────
class TestWallet:
    def test_get_wallet(self, tokens):
        r = requests.get(f"{BASE_URL}/api/wallet", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "balance" in j

    def test_wallet_transactions(self, tokens):
        r = requests.get(f"{BASE_URL}/api/wallet/transactions", headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_withdraw_negative_rejected(self, tokens):
        r = requests.post(f"{BASE_URL}/api/wallet/withdraw",
                          headers=H(tokens["customer"]), json={"amount": -100}, timeout=20)
        assert r.status_code == 400

    def test_withdraw_zero_rejected(self, tokens):
        r = requests.post(f"{BASE_URL}/api/wallet/withdraw",
                          headers=H(tokens["customer"]), json={"amount": 0}, timeout=20)
        assert r.status_code == 400

    def test_withdraw_overbalance_rejected(self, tokens):
        r = requests.post(f"{BASE_URL}/api/wallet/withdraw",
                          headers=H(tokens["customer"]), json={"amount": 9_999_999_999}, timeout=20)
        assert r.status_code == 400


# ────────────── Reviews (routes/reviews.py) ──────────────
class TestReviews:
    def test_admin_reviews_pending(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/reviews?status=pending",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_reviews_all(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/reviews?status=all",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_reviews_artist_public(self, tokens):
        # Look up an artist id (priya)
        artist_token = tokens["artist"]
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=H(artist_token), timeout=20).json()
        r = requests.get(f"{BASE_URL}/api/reviews/artist/{me['id']}", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_review_reply_unknown_id_404(self, tokens):
        r = requests.post(f"{BASE_URL}/api/reviews/nonexistent-id/reply",
                          headers=H(tokens["artist"]), json={"reply": "thanks"}, timeout=20)
        assert r.status_code == 404

    def test_review_report_auth(self, tokens):
        r = requests.post(f"{BASE_URL}/api/reviews/nonexistent-id/report",
                          headers=H(tokens["customer"]), timeout=20)
        # report endpoint just inserts — should return 200
        assert r.status_code == 200


# ────────────── Coupons (routes/coupons.py) ──────────────
class TestCoupons:
    @pytest.fixture(scope="class")
    def coupon_id(self, tokens):
        code = f"TESTREG{uuid.uuid4().hex[:6].upper()}"
        body = {
            "code": code,
            "description": "regression test coupon",
            "discount_type": "percent",
            "discount_value": 10,
            "max_uses": 100,
            "per_user_limit": 1,
            "expires_at": "2030-12-31",
            "min_order": 0,
            "applies_to": "all",
            "active": True,
        }
        r = requests.post(f"{BASE_URL}/api/admin/coupons",
                          headers=H(tokens["admin"]), json=body, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["code"] == code
        assert "id" in j
        return j["id"]

    def test_list_coupons(self, tokens, coupon_id):
        r = requests.get(f"{BASE_URL}/api/admin/coupons",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert coupon_id in ids

    def test_redemptions_empty(self, tokens, coupon_id):
        r = requests.get(f"{BASE_URL}/api/admin/coupons/{coupon_id}/redemptions",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_analytics(self, tokens, coupon_id):
        r = requests.get(f"{BASE_URL}/api/admin/coupons/analytics",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Our new coupon must appear
        assert any(c["id"] == coupon_id for c in data)

    def test_validate_existing_test20(self, tokens):
        r = requests.get(f"{BASE_URL}/api/coupons/validate",
                         headers=H(tokens["customer"]),
                         params={"code": "TEST20", "base_amount": 10000}, timeout=20)
        # Endpoint must respond (either valid or with HTTP error from validator)
        assert r.status_code in (200, 400, 404), r.text
        if r.status_code == 200:
            j = r.json()
            assert j["code"] == "TEST20"
            assert "discount_amount" in j

    def test_delete_coupon(self, tokens, coupon_id):
        r = requests.delete(f"{BASE_URL}/api/admin/coupons/{coupon_id}",
                            headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        # Verify removal
        r2 = requests.get(f"{BASE_URL}/api/admin/coupons",
                          headers=H(tokens["admin"]), timeout=20)
        ids = [c["id"] for c in r2.json()]
        assert coupon_id not in ids


# ────────────── Blogs (routes/blogs.py) ──────────────
class TestBlogs:
    def test_list_blogs(self):
        r = requests.get(f"{BASE_URL}/api/blogs", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_get_blog(self, tokens):
        slug = f"reg-{uuid.uuid4().hex[:8]}"
        body = {
            "title": "Regression Test Blog",
            "slug": slug,
            "content": "TEST_ content for iteration 13.",
            "excerpt": "regression",
            "tags": ["test"],
            "published": True,
        }
        r = requests.post(f"{BASE_URL}/api/admin/blogs",
                          headers=H(tokens["admin"]), json=body, timeout=20)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{BASE_URL}/api/blogs/{slug}", timeout=20)
        assert r2.status_code == 200
        assert r2.json()["slug"] == slug

    def test_booktalent_audit_blog(self):
        r = requests.get(f"{BASE_URL}/api/blogs/booktalent-audit", timeout=20)
        # Endpoint should respond — either 200 (exists) or 404 (not seeded)
        assert r.status_code in (200, 404), r.text


# ────────────── Disputes (routes/disputes.py) ──────────────
class TestDisputes:
    def test_admin_disputes_list(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/disputes",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_dispute_invalid_booking_403(self, tokens):
        r = requests.post(f"{BASE_URL}/api/disputes",
                          headers=H(tokens["customer"]),
                          json={"booking_id": "non-existent", "reason": "test"}, timeout=20)
        assert r.status_code == 403


# ────────────── KYC (routes/kyc.py) ──────────────
class TestKYC:
    def test_kyc_submit_invalid_aadhaar_length(self, tokens):
        r = requests.post(f"{BASE_URL}/api/kyc/submit",
                          headers=H(tokens["artist"]),
                          json={"aadhaar_number": "12345", "aadhaar": TINY_PNG}, timeout=20)
        assert r.status_code == 400

    def test_kyc_submit_invalid_pan_format(self, tokens):
        r = requests.post(f"{BASE_URL}/api/kyc/submit",
                          headers=H(tokens["artist"]),
                          json={"pan_number": "bad-pan", "pan": TINY_PNG}, timeout=20)
        assert r.status_code == 400

    def test_kyc_submit_missing_docs(self, tokens):
        r = requests.post(f"{BASE_URL}/api/kyc/submit",
                          headers=H(tokens["artist"]),
                          json={"full_name": "No Docs"}, timeout=20)
        assert r.status_code == 400

    def test_kyc_submit_valid(self, tokens):
        r = requests.post(f"{BASE_URL}/api/kyc/submit",
                          headers=H(tokens["artist"]),
                          json={
                              "aadhaar_number": "123456789012",
                              "full_name": "Priya Test",
                              "aadhaar": TINY_PNG,
                          }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

    def test_kyc_mine(self, tokens):
        r = requests.get(f"{BASE_URL}/api/kyc/mine",
                         headers=H(tokens["artist"]), timeout=20)
        assert r.status_code == 200
        j = r.json()
        assert j is not None
        assert j.get("status") in ("pending", "approved", "rejected", "needs_resubmission")

    def test_admin_kyc_list(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/kyc",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_kyc_decide(self, tokens):
        # Artist user_id via /auth/me
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=H(tokens["artist"]), timeout=20).json()
        r = requests.post(f"{BASE_URL}/api/admin/kyc/decide",
                          headers=H(tokens["admin"]),
                          json={"artist_id": me["id"], "decision": "approve"}, timeout=20)
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["status"] == "approved"


# ────────────── Iter 12 chat-gate regression (must still pass) ──────────────
class TestChatGateRegression:
    def test_unpaid_access_disabled(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{UNPAID_BID}/access",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_paid_access_enabled(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{PAID_BID}/access",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_unpaid_messages_403(self, tokens):
        r = requests.get(f"{BASE_URL}/api/chat/{UNPAID_BID}/messages",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 403


# ────────────── Iter 11 P3 regression ──────────────
class TestIter11Regression:
    def test_ai_search(self):
        r = requests.post(f"{BASE_URL}/api/search/ai",
                          json={"query": "Singer in Mumbai", "limit": 3}, timeout=60)
        assert r.status_code == 200

    def test_paid_ics(self, tokens):
        r = requests.get(f"{BASE_URL}/api/bookings/{PAID_BID}/calendar.ics",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200
        assert "text/calendar" in r.headers.get("content-type", "").lower()

    def test_customer_csv(self, tokens):
        r = requests.get(f"{BASE_URL}/api/exports/my-bookings.csv",
                         headers=H(tokens["customer"]), timeout=20)
        assert r.status_code == 200

    def test_admin_revenue_csv(self, tokens):
        r = requests.get(f"{BASE_URL}/api/admin/exports/revenue.csv",
                         headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
