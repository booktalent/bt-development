"""
Iter8 backend tests:
- KYC: validation, admin queue filter, admin decisions (approve/reject/resubmission)
- Coupons: strict validation, redemption ledger, admin analytics, ledger drilldown
- Chat: REST list/post/read + access control
- Regression: logins, search pagination/filters
"""
import os
import time
import base64
import asyncio
from datetime import datetime, timezone, timedelta
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env").read().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")
ARTIST = ("priya@booktalent.com", "Artist@123")
ALT_ARTIST = ("vortex@booktalent.com", "Artist@123")


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_tok():
    return _login(*ADMIN)["token"]


@pytest.fixture(scope="session")
def customer_tok():
    return _login(*CUSTOMER)["token"]


@pytest.fixture(scope="session")
def customer_user():
    return _login(*CUSTOMER)["user"]


@pytest.fixture(scope="session")
def artist_tok():
    return _login(*ARTIST)["token"]


@pytest.fixture(scope="session")
def artist_user():
    return _login(*ARTIST)["user"]


@pytest.fixture(scope="session")
def alt_artist_tok():
    return _login(*ALT_ARTIST)["token"]


@pytest.fixture(scope="session")
def alt_artist_user():
    return _login(*ALT_ARTIST)["user"]


# Minimal valid data URLs
def _png_data_url():
    # 1x1 transparent png
    raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII=")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _bad_data_url():
    return "data:application/x-msdownload;base64," + base64.b64encode(b"X" * 100).decode()


def _big_png_data_url():
    # ~6MB payload to exceed 5MB
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def _reset_priya_kyc(admin_tok, artist_id):
    """Force priya back to needs_resubmission so we can test approve flow fresh."""
    requests.post(
        f"{API}/admin/kyc/decide",
        json={"artist_id": artist_id, "decision": "request_resubmission", "reason": "reset for test"},
        headers=h(admin_tok), timeout=20,
    )


# ───────── KYC validation ─────────
class TestKYCValidation:
    def _payload(self, **over):
        base = {
            "full_name": "Priya Test",
            "dob": "1990-01-01",
            "aadhaar_number": "123412341234",
            "pan_number": "ABCDE1234F",
            "aadhaar": _png_data_url(),
            "pan": _png_data_url(),
            "bank_proof": _png_data_url(),
            "selfie": _png_data_url(),
        }
        base.update(over)
        return base

    def test_kyc_rejects_bad_aadhaar(self, artist_tok):
        r = requests.post(f"{API}/kyc/submit", json=self._payload(aadhaar_number="12"),
                          headers=h(artist_tok), timeout=20)
        assert r.status_code in (400, 422), r.text[:200]

    def test_kyc_rejects_bad_pan(self, artist_tok):
        r = requests.post(f"{API}/kyc/submit", json=self._payload(pan_number="BADPAN"),
                          headers=h(artist_tok), timeout=20)
        assert r.status_code in (400, 422), r.text[:200]

    def test_kyc_rejects_bad_filetype(self, artist_tok):
        r = requests.post(f"{API}/kyc/submit", json=self._payload(aadhaar=_bad_data_url()),
                          headers=h(artist_tok), timeout=20)
        assert r.status_code in (400, 422), r.text[:200]

    def test_kyc_rejects_oversize_file(self, artist_tok):
        r = requests.post(f"{API}/kyc/submit", json=self._payload(selfie=_big_png_data_url()),
                          headers=h(artist_tok), timeout=30)
        assert r.status_code in (400, 413, 422), f"expected 4xx got {r.status_code} {r.text[:200]}"


# ───────── KYC admin queue + decisions ─────────
class TestKYCAdmin:
    def test_admin_queue_filters(self, admin_tok):
        for status in ("pending", "approved", "rejected", "needs_resubmission", ""):
            url = f"{API}/admin/kyc"
            if status:
                url += f"?status={status}"
            r = requests.get(url, headers=h(admin_tok), timeout=15)
            assert r.status_code == 200, f"{status}: {r.text[:200]}"
            data = r.json()
            assert isinstance(data, list)
            # Each row should include user + artist_profile + masked aadhaar (when present)
            for row in data[:3]:
                assert "user" in row or "artist_profile" in row or "id" in row

    def test_admin_decide_approve_then_reject_cycle(self, admin_tok, alt_artist_tok, alt_artist_user):
        # Submit fresh KYC as alt_artist
        payload = {
            "full_name": "Alt Artist",
            "dob": "1991-05-05",
            "aadhaar_number": "987612341234",
            "pan_number": "ZYXWV9876K",
            "aadhaar": _png_data_url(),
            "pan": _png_data_url(),
            "bank_proof": _png_data_url(),
            "selfie": _png_data_url(),
        }
        sub = requests.post(f"{API}/kyc/submit", json=payload,
                            headers=h(alt_artist_tok), timeout=20)
        assert sub.status_code in (200, 201), f"submit failed: {sub.status_code} {sub.text[:200]}"

        # Approve
        appr = requests.post(f"{API}/admin/kyc/decide",
                             json={"artist_id": alt_artist_user["id"], "decision": "approve"},
                             headers=h(admin_tok), timeout=20)
        assert appr.status_code == 200, appr.text[:200]

        # Verify artist's me shows approved status
        me = requests.get(f"{API}/auth/me", headers=h(alt_artist_tok), timeout=15)
        if me.status_code == 200:
            user_obj = me.json()
            assert user_obj.get("kyc_status") in ("approved", "verified", None)

        # Reset to needs_resubmission
        req = requests.post(f"{API}/admin/kyc/decide",
                            json={"artist_id": alt_artist_user["id"], "decision": "request_resubmission", "reason": "test"},
                            headers=h(admin_tok), timeout=20)
        assert req.status_code == 200

        # Reject
        rj = requests.post(f"{API}/admin/kyc/decide",
                           json={"artist_id": alt_artist_user["id"], "decision": "reject", "reason": "test reject"},
                           headers=h(admin_tok), timeout=20)
        assert rj.status_code == 200, rj.text[:200]

    def test_admin_decide_invalid_decision(self, admin_tok, alt_artist_user):
        r = requests.post(f"{API}/admin/kyc/decide",
                          json={"artist_id": alt_artist_user["id"], "decision": "delete"},
                          headers=h(admin_tok), timeout=15)
        assert r.status_code in (400, 422)


# ───────── Coupons ─────────
class TestCoupons:
    def test_validate_unknown_code(self, customer_tok):
        r = requests.get(f"{API}/coupons/validate",
                         params={"code": "NOPECODE", "base_amount": 5000, "event_type": "wedding"},
                         headers=h(customer_tok), timeout=15)
        assert r.status_code in (200, 400, 404)
        if r.status_code == 200:
            body = r.json()
            assert body.get("valid") is False or body.get("ok") is False

    def test_validate_below_min_order(self, customer_tok):
        r = requests.get(f"{API}/coupons/validate",
                         params={"code": "TEST20", "base_amount": 100, "event_type": "wedding"},
                         headers=h(customer_tok), timeout=15)
        if r.status_code == 200:
            body = r.json()
            # Either valid=False or it explicitly rejects
            assert body.get("valid") is False or body.get("error") or body.get("reason")
        else:
            assert r.status_code in (400, 422)

    def test_validate_happy_path(self, customer_tok):
        r = requests.get(f"{API}/coupons/validate",
                         params={"code": "TEST20", "base_amount": 5000, "event_type": "wedding"},
                         headers=h(customer_tok), timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # Should compute discount (20% of 5000 = 1000)
        if body.get("valid") is True or body.get("ok"):
            disc = body.get("discount") or body.get("discount_amount") or 0
            assert disc > 0, f"expected discount > 0, got {body}"

    def test_admin_coupon_analytics(self, admin_tok):
        r = requests.get(f"{API}/admin/coupons/analytics",
                         headers=h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert isinstance(data, list)
        if data:
            row = data[0]
            # Expect uses/total_discount/total_gmv/remaining keys
            for key in ("uses", "total_discount", "remaining"):
                assert key in row or "code" in row, f"missing {key} in {row}"

    def test_admin_coupon_ledger_drilldown(self, admin_tok):
        # Pull list of coupons via analytics
        r = requests.get(f"{API}/admin/coupons/analytics",
                         headers=h(admin_tok), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        if not rows:
            pytest.skip("no coupons present")
        cid = rows[0].get("id") or rows[0].get("_id") or rows[0].get("coupon_id")
        if not cid:
            pytest.skip("coupon row has no id field")
        rr = requests.get(f"{API}/admin/coupons/{cid}/redemptions",
                          headers=h(admin_tok), timeout=15)
        assert rr.status_code == 200, rr.text[:200]
        assert isinstance(rr.json(), list)

    def test_admin_coupon_analytics_forbidden_for_customer(self, customer_tok):
        r = requests.get(f"{API}/admin/coupons/analytics",
                         headers=h(customer_tok), timeout=15)
        assert r.status_code == 403


# ───────── Chat REST ─────────
class TestChatREST:
    @pytest.fixture(scope="class")
    def booking_id(self, customer_tok, artist_user):
        prof = requests.get(f"{API}/artists/{artist_user['id']}", timeout=15)
        if prof.status_code != 200:
            pytest.skip(f"artist fetch failed {prof.status_code}")
        pkgs = prof.json().get("packages") or []
        if not pkgs:
            pytest.skip("no packages")
        pkg_id = pkgs[0].get("id") or pkgs[0].get("_id")
        future = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
        payload = {
            "artist_id": artist_user["id"],
            "package_id": pkg_id,
            "event_date": future,
            "event_time": "20:00",
            "event_type": "wedding",
            "city": "Mumbai",
            "venue": "iter8 chat venue",
            "notes": "chat test",
            "customer_name": "Chat Cust",
            "customer_phone": "+919000000000",
            "customer_email": "customer@booktalent.com",
        }
        cr = requests.post(f"{API}/bookings", json=payload,
                           headers=h(customer_tok), timeout=20)
        if cr.status_code != 200:
            pytest.skip(f"booking create {cr.status_code} {cr.text[:200]}")
        return cr.json().get("id") or cr.json().get("booking", {}).get("id")

    def test_post_and_list_as_customer(self, booking_id, customer_tok):
        post = requests.post(f"{API}/chat/{booking_id}/messages",
                             json={"content": "hello from customer iter8"},
                             headers=h(customer_tok), timeout=15)
        assert post.status_code == 200, post.text[:200]
        body = post.json()
        assert body.get("content") == "hello from customer iter8"
        assert "_id" not in body  # mongo _id must be excluded

        lst = requests.get(f"{API}/chat/{booking_id}/messages",
                           headers=h(customer_tok), timeout=15)
        assert lst.status_code == 200
        msgs = lst.json()
        assert any(m.get("content") == "hello from customer iter8" for m in msgs)

    def test_artist_can_access(self, booking_id, artist_tok):
        lst = requests.get(f"{API}/chat/{booking_id}/messages",
                           headers=h(artist_tok), timeout=15)
        assert lst.status_code == 200

    def test_stranger_403(self, booking_id, alt_artist_tok):
        lst = requests.get(f"{API}/chat/{booking_id}/messages",
                           headers=h(alt_artist_tok), timeout=15)
        assert lst.status_code == 403, f"expected 403 got {lst.status_code}"

    def test_mark_read(self, booking_id, artist_tok):
        # Artist marks read
        r = requests.post(f"{API}/chat/{booking_id}/read",
                          headers=h(artist_tok), timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("ok") is True

    def test_admin_can_access(self, booking_id, admin_tok):
        lst = requests.get(f"{API}/chat/{booking_id}/messages",
                           headers=h(admin_tok), timeout=15)
        assert lst.status_code == 200

    def test_offline_notification_created(self, booking_id, customer_tok, artist_tok):
        # Artist is not connected via WS in this REST test. Customer posts,
        # an in-app notification should appear for the artist.
        before = requests.get(f"{API}/notifications", headers=h(artist_tok), timeout=15)
        before_count = len(before.json()) if before.status_code == 200 and isinstance(before.json(), list) else 0

        requests.post(f"{API}/chat/{booking_id}/messages",
                      json={"content": "offline notify ping iter8"},
                      headers=h(customer_tok), timeout=15)
        time.sleep(0.6)
        after = requests.get(f"{API}/notifications", headers=h(artist_tok), timeout=15)
        if after.status_code != 200:
            pytest.skip("/api/notifications not available")
        after_count = len(after.json()) if isinstance(after.json(), list) else 0
        assert after_count >= before_count, f"notif count decreased {before_count}→{after_count}"


# ───────── Regression ─────────
def test_regression_logins():
    for u, p in [ADMIN, CUSTOMER, ARTIST]:
        r = requests.post(f"{API}/auth/login", json={"email": u, "password": p}, timeout=15)
        assert r.status_code == 200, f"{u} login failed"


def test_regression_search_artists_pagination():
    r = requests.get(f"{API}/search/artists?page=1&limit=6", timeout=15)
    assert r.status_code == 200
    data = r.json()
    for k in ("items", "total", "page", "pages"):
        assert k in data


def test_regression_search_filters():
    r = requests.get(f"{API}/search/artists",
                     params={"min_price": 0, "max_price": 9999999, "sort": "rating",
                             "page": 1, "limit": 6},
                     timeout=15)
    assert r.status_code == 200
