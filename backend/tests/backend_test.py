"""BookTalent end-to-end backend tests.

Covers: auth, discovery, packages, availability, bookings, payments,
state-machine, reviews, wallet/withdrawals, media, KYC and admin.
"""
import os
import time
import uuid
import base64
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@booktalent.com"
ADMIN_PWD = "Admin@123"
CUSTOMER_EMAIL = "customer@booktalent.com"
CUSTOMER_PWD = "Customer@123"
ARTIST_EMAIL = "priya@booktalent.com"
ARTIST_PWD = "Artist@123"

# 1px PNG
TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


# ---------- helpers ----------
def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- session-scoped fixtures ----------
@pytest.fixture(scope="session")
def admin():
    t, u = _login(ADMIN_EMAIL, ADMIN_PWD)
    return {"token": t, "user": u}


@pytest.fixture(scope="session")
def artist():
    t, u = _login(ARTIST_EMAIL, ARTIST_PWD)
    return {"token": t, "user": u}


def _verify_email(email: str):
    """Helper: perform mock email-OTP send + verify so register can proceed."""
    rs = requests.post(f"{API}/auth/email/send", json={"email": email, "name": "Test"}, timeout=15)
    assert rs.status_code == 200, f"email/send failed: {rs.status_code} {rs.text}"
    otp = rs.json().get("test_otp") or "123456"
    rv = requests.post(f"{API}/auth/email/verify", json={"email": email, "otp": otp}, timeout=15)
    assert rv.status_code == 200, f"email/verify failed: {rv.status_code} {rv.text}"


@pytest.fixture(scope="session")
def customer():
    # Register a fresh TEST customer to avoid existing data interference
    email = f"TEST_cust_{uuid.uuid4().hex[:8]}@booktalent.com"
    _verify_email(email)
    payload = {
        "email": email,
        "password": "Test@1234",
        "first_name": "Test",
        "last_name": "Customer",
        "phone": "+919" + str(int(time.time()))[-9:],
        "role": "customer",
    }
    r = requests.post(f"{API}/auth/register", json=payload, timeout=20)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["token"], "user": data["user"], "email": email, "password": "Test@1234"}


# ---------- AUTH ----------
class TestAuth:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_login_admin(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "admin"
        assert d["user"]["email"] == ADMIN_EMAIL
        assert isinstance(d["token"], str) and len(d["token"]) > 20

    def test_login_artist_seeded(self):
        r = requests.post(f"{API}/auth/login", json={"email": ARTIST_EMAIL, "password": ARTIST_PWD}, timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "artist"

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_register_and_me(self, customer):
        r = requests.get(f"{API}/auth/me", headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == customer["email"].lower()

    def test_me_requires_token(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code in (401, 403)

    def test_register_duplicate(self, customer):
        r = requests.post(f"{API}/auth/register", json={
            "email": customer["email"], "password": "Test@1234", "first_name": "x",
            "last_name": "x", "phone": "+91" + str(int(time.time()))[-10:], "role": "customer",
        }, timeout=15)
        assert r.status_code == 400


# ---------- EMAIL OTP (iter 3) ----------
class TestEmailOTP:
    def test_auth_config_email_disabled(self):
        r = requests.get(f"{API}/auth/config", timeout=15)
        assert r.status_code == 200
        d = r.json()
        # RESEND_API_KEY is empty in .env → provider disabled
        assert "email_provider_enabled" in d
        assert d["email_provider_enabled"] is False

    def test_email_send_mock_returns_test_otp(self):
        email = f"TEST_email_{uuid.uuid4().hex[:8]}@booktalent.com"
        r = requests.post(f"{API}/auth/email/send", json={"email": email, "name": "Tester"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("sent") is True
        assert d.get("mock") is True
        assert d.get("test_otp") == "123456"

    def test_email_send_cooldown_429(self):
        email = f"TEST_cool_{uuid.uuid4().hex[:8]}@booktalent.com"
        r1 = requests.post(f"{API}/auth/email/send", json={"email": email}, timeout=15)
        assert r1.status_code == 200
        # Immediate second request should be cooldown-limited
        r2 = requests.post(f"{API}/auth/email/send", json={"email": email}, timeout=15)
        assert r2.status_code == 429, f"expected 429 got {r2.status_code} {r2.text}"

    def test_email_verify_wrong_code_returns_400(self):
        email = f"TEST_wrong_{uuid.uuid4().hex[:8]}@booktalent.com"
        rs = requests.post(f"{API}/auth/email/send", json={"email": email}, timeout=15)
        assert rs.status_code == 200
        rv = requests.post(f"{API}/auth/email/verify", json={"email": email, "otp": "000000"}, timeout=15)
        assert rv.status_code == 400

    def test_email_verify_no_send_returns_400(self):
        email = f"TEST_nosend_{uuid.uuid4().hex[:8]}@booktalent.com"
        rv = requests.post(f"{API}/auth/email/verify", json={"email": email, "otp": "123456"}, timeout=15)
        assert rv.status_code == 400

    def test_email_verify_success_then_register(self):
        email = f"TEST_reg_{uuid.uuid4().hex[:8]}@booktalent.com"
        rs = requests.post(f"{API}/auth/email/send", json={"email": email, "name": "Reg"}, timeout=15)
        assert rs.status_code == 200
        otp = rs.json().get("test_otp") or "123456"
        rv = requests.post(f"{API}/auth/email/verify", json={"email": email, "otp": otp}, timeout=15)
        assert rv.status_code == 200
        assert rv.json().get("verified") is True
        # Now register should succeed
        payload = {
            "email": email, "password": "Test@1234", "first_name": "R",
            "last_name": "User", "phone": "+919" + str(int(time.time()))[-9:],
            "role": "customer",
        }
        rr = requests.post(f"{API}/auth/register", json=payload, timeout=20)
        assert rr.status_code == 200, rr.text
        data = rr.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20
        u = data["user"]
        assert u.get("verified") is True
        assert u.get("email_verified") is True

    def test_register_without_email_verify_blocked(self):
        email = f"TEST_block_{uuid.uuid4().hex[:8]}@booktalent.com"
        # NO email/send + verify first → must be rejected
        payload = {
            "email": email, "password": "Test@1234", "first_name": "B",
            "last_name": "User", "phone": "+919" + str(int(time.time()))[-9:],
            "role": "customer",
        }
        r = requests.post(f"{API}/auth/register", json=payload, timeout=15)
        assert r.status_code == 400
        # Must mention email verification
        assert "verify" in (r.json().get("detail") or "").lower()


# ---------- ARTIST DISCOVERY ----------
class TestArtists:
    def test_search_basic(self):
        r = requests.get(f"{API}/artists/search", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d or "results" in d or isinstance(d, list)

    def test_search_with_filters(self):
        r = requests.get(f"{API}/artists/search", params={"city": "Mumbai", "sort": "rating"}, timeout=15)
        assert r.status_code == 200

    def test_featured(self):
        r = requests.get(f"{API}/artists/featured", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_priya_profile(self, artist):
        r = requests.get(f"{API}/artists/{artist['user']['id']}", timeout=15)
        assert r.status_code == 200
        d = r.json()
        # accept either flat profile or nested
        assert "user" in d or "artist_profile" in d or "profile" in d or "id" in d
        # the response should include packages
        assert "packages" in d or "user" in d

    def test_categories_cities(self):
        r1 = requests.get(f"{API}/categories", timeout=15)
        r2 = requests.get(f"{API}/cities", timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200


# ---------- PACKAGES (artist CRUD) ----------
class TestPackages:
    def test_mine_and_crud(self, artist):
        r = requests.get(f"{API}/packages/mine", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        existing = r.json()
        assert isinstance(existing, list)

        payload = {"name": "TEST_PKG", "price": 25000, "duration": "60 min",
                   "description": "test", "features": ["sound"]}
        r = requests.post(f"{API}/packages", json=payload, headers=_h(artist["token"]), timeout=15)
        assert r.status_code in (200, 201)
        pid = r.json().get("id") or r.json().get("package", {}).get("id")
        assert pid

        r = requests.put(f"{API}/packages/{pid}",
                         json={"name": "TEST_PKG", "price": 30000, "duration": "60 min",
                               "description": "updated", "features": ["sound"]},
                         headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200

        r = requests.delete(f"{API}/packages/{pid}", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200


# ---------- BOOKING FLOW (full state machine) ----------
@pytest.fixture(scope="session")
def booking_ctx(customer, artist):
    # find a real package for priya
    r = requests.get(f"{API}/artists/{artist['user']['id']}", timeout=15)
    assert r.status_code == 200
    pkgs = r.json().get("packages") or []
    assert len(pkgs) >= 1, "Seed artist has no packages"
    pkg = pkgs[0]
    pid = pkg.get("id") or pkg.get("_id")

    # create booking
    body = {
        "artist_id": artist["user"]["id"],
        "package_id": pid,
        "addons": [],
        "event_date": f"2031-{(int(time.time())%12)+1:02d}-{(int(time.time())%27)+1:02d}",
        "event_time": "19:00",
        "event_type": "Wedding",
        "venue": "TEST_Venue",
        "city": "Mumbai",
        "guests": "100",
        "customer_name": "TEST Customer",
        "customer_phone": customer["user"].get("phone"),
        "customer_email": customer["user"]["email"],
    }
    r = requests.post(f"{API}/bookings", json=body, headers=_h(customer["token"]), timeout=20)
    assert r.status_code == 200, f"booking create failed: {r.status_code} {r.text}"
    bk = r.json()
    return {"booking": bk, "package": pkg}


class TestBookingFlow:
    def test_booking_pricing_breakdown(self, booking_ctx):
        bk = booking_ctx["booking"]
        assert bk["status"] == "pending_payment"
        p = bk["pricing"]
        for k in ("package_fee", "platform_fee", "gst", "total", "token_amount"):
            assert k in p
        # 5% platform fee, 18% GST, 5% token sanity
        assert p["platform_fee"] > 0
        assert p["gst"] > 0
        assert p["token_amount"] > 0

    def test_payment_init_and_verify(self, booking_ctx, customer):
        bid = booking_ctx["booking"]["id"]
        r = requests.post(f"{API}/payments/init",
                          json={"booking_id": bid, "method": "card"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        pay_id = r.json()["payment_id"]

        r = requests.post(f"{API}/payments/verify",
                          json={"payment_id": pay_id, "booking_id": bid, "mock_otp": "123456"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "pending_artist"

    def test_payment_wrong_otp(self, booking_ctx, customer):
        bid = booking_ctx["booking"]["id"]
        r = requests.post(f"{API}/payments/init",
                          json={"booking_id": bid, "method": "card"},
                          headers=_h(customer["token"]), timeout=15)
        pid = r.json()["payment_id"]
        r = requests.post(f"{API}/payments/verify",
                          json={"payment_id": pid, "booking_id": bid, "mock_otp": "000000"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 400

    def test_artist_accept_creates_contract(self, booking_ctx, artist):
        bid = booking_ctx["booking"]["id"]
        r = requests.post(f"{API}/bookings/{bid}/action",
                          json={"action": "accept"}, headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

        # contract created
        r = requests.get(f"{API}/contracts/mine", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        contracts = r.json()
        assert any(c.get("booking_id") == bid for c in contracts), "contract not created"

    def test_artist_complete_then_customer_approve(self, booking_ctx, artist, customer):
        bid = booking_ctx["booking"]["id"]
        # artist marks complete
        r = requests.post(f"{API}/bookings/{bid}/action",
                          json={"action": "complete"}, headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "completed_by_artist"

        # check artist wallet before
        wbefore = requests.get(f"{API}/wallet", headers=_h(artist["token"]), timeout=15).json()

        # customer approves
        r = requests.post(f"{API}/bookings/{bid}/action",
                          json={"action": "approve_completion"}, headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

        # wallet should have grown
        wafter = requests.get(f"{API}/wallet", headers=_h(artist["token"]), timeout=15).json()
        assert wafter["balance"] >= wbefore["balance"]

    def test_unauth_action_forbidden(self, booking_ctx):
        bid = booking_ctx["booking"]["id"]
        # no token
        r = requests.post(f"{API}/bookings/{bid}/action", json={"action": "cancel"}, timeout=15)
        assert r.status_code in (401, 403)


# ---------- REVIEWS ----------
class TestReviews:
    def test_create_and_list_review(self, booking_ctx, customer, artist):
        bid = booking_ctx["booking"]["id"]
        # create review (booking is now 'completed')
        r = requests.post(f"{API}/reviews",
                          json={"booking_id": bid, "rating": 5, "text": "TEST excellent"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200, r.text
        rid = r.json()["review_id"]

        r = requests.get(f"{API}/reviews/artist/{artist['user']['id']}", timeout=15)
        assert r.status_code == 200
        rs = r.json()
        assert any(x.get("id") == rid for x in rs)

        # artist replies
        r = requests.post(f"{API}/reviews/{rid}/reply",
                          json={"reply": "TEST thank you"},
                          headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200


# ---------- WALLET ----------
class TestWallet:
    def test_wallet_balance_and_tx(self, artist):
        r = requests.get(f"{API}/wallet", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert "balance" in r.json()

        r = requests.get(f"{API}/wallet/transactions", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_withdraw(self, artist):
        r = requests.get(f"{API}/wallet", headers=_h(artist["token"]), timeout=15)
        bal = r.json()["balance"]
        if bal < 100:
            pytest.skip("artist wallet balance too low to test withdrawal")
        r = requests.post(f"{API}/wallet/withdraw", json={"amount": 100},
                          headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert "withdrawal_id" in r.json()
        # balance reduced
        r2 = requests.get(f"{API}/wallet", headers=_h(artist["token"]), timeout=15)
        assert r2.json()["balance"] == pytest.approx(bal - 100, abs=0.01)


# ---------- MEDIA ----------
class TestMedia:
    def test_upload_get_delete(self, artist):
        r = requests.post(f"{API}/media/upload",
                          json={"type": "gallery", "data_url": TINY_PNG},
                          headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json().get("id") or r.json().get("media_id")
        assert mid

        # stream back
        r = requests.get(f"{API}/media/{mid}", timeout=15)
        assert r.status_code == 200

        # list does not include heavy data field
        r = requests.get(f"{API}/media", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        for m in r.json():
            assert "data" not in m

        # delete
        r = requests.delete(f"{API}/media/{mid}", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200


# ---------- AVAILABILITY ----------
class TestAvailability:
    def test_block_and_booking_rejected(self, artist, customer):
        date = "2028-01-15"
        r = requests.post(f"{API}/availability",
                          json={"date": date, "status": "blocked"},
                          headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200

        r = requests.get(f"{API}/availability/mine", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert any(a.get("date") == date for a in r.json())

        # attempt booking on blocked date
        pr = requests.get(f"{API}/artists/{artist['user']['id']}", timeout=15).json()
        pkgs = pr.get("packages") or []
        if not pkgs:
            pytest.skip("no packages for artist")
        pid = pkgs[0].get("id")
        body = {
            "artist_id": artist["user"]["id"],
            "package_id": pid, "addons": [],
            "event_date": date, "event_time": "20:00",
            "event_type": "Corporate", "venue": "x", "city": "Mumbai",
            "guests": "50", "customer_name": "x",
            "customer_phone": "+919999999999", "customer_email": "x@x.com",
        }
        r = requests.post(f"{API}/bookings", json=body, headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 400


# ---------- ADMIN ----------
class TestAdmin:
    def test_stats_admin_only(self, admin, customer):
        r = requests.get(f"{API}/admin/stats", headers=_h(admin["token"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        # has at least some of the expected keys
        assert any(k in data for k in ("gmv", "bookings", "users", "total_users", "total_bookings"))

        # non-admin should be 403
        r = requests.get(f"{API}/admin/stats", headers=_h(customer["token"]), timeout=15)
        assert r.status_code in (401, 403)

    def test_admin_lists(self, admin):
        for ep in ("/admin/artists", "/admin/bookings", "/admin/users", "/admin/kyc"):
            r = requests.get(f"{API}{ep}", headers=_h(admin["token"]), timeout=15)
            assert r.status_code == 200, f"{ep}: {r.status_code}"

    def test_create_coupon(self, admin):
        code = "TESTCPN" + uuid.uuid4().hex[:6].upper()
        r = requests.post(f"{API}/admin/coupons",
                          json={"code": code, "discount_type": "percent", "discount_value": 10,
                                "expires_at": "2030-12-31", "active": True},
                          headers=_h(admin["token"]), timeout=15)
        assert r.status_code in (200, 201)
        # validate (endpoint requires auth)
        r = requests.get(f"{API}/coupons/validate", params={"code": code},
                         headers=_h(admin["token"]), timeout=15)
        assert r.status_code == 200


# ---------- KYC ----------
class TestKYC:
    def test_submit(self, artist):
        r = requests.post(f"{API}/kyc/submit",
                          json={"aadhaar": TINY_PNG, "pan": TINY_PNG},
                          headers=_h(artist["token"]), timeout=20)
        assert r.status_code == 200
        r = requests.get(f"{API}/kyc/mine", headers=_h(artist["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") in ("pending", "approved", "rejected")


# ---------- NEW: Razorpay config + PDF contracts/invoice + refund + webhook ----------
class TestPaymentsConfig:
    def test_payment_config_public(self):
        r = requests.get(f"{API}/payments/config", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "razorpay_enabled" in d
        assert "currency" in d
        # keys are empty in .env → mock mode
        assert d["razorpay_enabled"] is False
        assert d.get("razorpay_key_id") in (None, "")
        assert d["currency"] == "INR"


class TestPaymentInitGateway:
    """Verify mock gateway label is returned when Razorpay disabled."""
    def test_init_returns_razorpay_mock(self, customer, artist):
        # create a fresh booking
        ad = requests.get(f"{API}/artists/{artist['user']['id']}", timeout=15).json()
        pid = ad["packages"][0]["id"]
        body = {
            "artist_id": artist["user"]["id"], "package_id": pid, "addons": [],
            "event_date": "2027-11-11", "event_time": "20:00",
            "event_type": "Wedding", "venue": "TEST", "city": "Mumbai",
            "guests": "100",
        }
        r = requests.post(f"{API}/bookings", json=body, headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200, r.text
        bid = r.json()["id"]

        # init
        r = requests.post(f"{API}/payments/init",
                          json={"booking_id": bid, "method": "upi"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("gateway") == "razorpay_mock"
        assert "payment_id" in d
        assert "amount" in d

        # also assert: passing razorpay_signature on a mock payment still uses mock_otp branch
        r2 = requests.post(f"{API}/payments/verify",
                           json={"payment_id": d["payment_id"], "booking_id": bid,
                                 "razorpay_signature": "bogus", "mock_otp": "123456"},
                           headers=_h(customer["token"]), timeout=15)
        assert r2.status_code == 200, r2.text
        v = r2.json()
        assert v.get("status") == "pending_artist"
        assert str(v.get("booking_ref", "")).startswith("BT-")
        assert v.get("gateway") == "razorpay_mock"


class TestContractsAndInvoicePDF:
    def test_contract_list_and_pdf(self, booking_ctx, customer, artist):
        # contract was created on accept earlier
        r = requests.get(f"{API}/contracts/mine", headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200
        contracts = r.json()
        match = [c for c in contracts if c.get("booking_id") == booking_ctx["booking"]["id"]]
        assert match, "expected contract for booking"
        cid = match[0]["id"]

        # download PDF as customer
        r = requests.get(f"{API}/contracts/{cid}/pdf",
                         headers={"Authorization": f"Bearer {customer['token']}"}, timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 500

        # artist can also download
        r2 = requests.get(f"{API}/contracts/{cid}/pdf",
                          headers={"Authorization": f"Bearer {artist['token']}"}, timeout=20)
        assert r2.status_code == 200
        assert r2.content[:5] == b"%PDF-"

    def test_contract_pdf_forbidden_for_stranger(self, booking_ctx):
        # create another customer
        email = f"TEST_stranger_{uuid.uuid4().hex[:6]}@booktalent.com"
        _verify_email(email)
        rr = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "Test@1234", "first_name": "S",
            "last_name": "T", "phone": "+9199" + str(int(time.time()))[-8:],
            "role": "customer",
        }, timeout=15)
        assert rr.status_code == 200
        tok = rr.json()["token"]

        # find contract
        cr = requests.get(f"{API}/contracts/mine",
                         headers=_h(tok), timeout=15)
        assert cr.status_code == 200
        # stranger has no contracts of their own
        assert all(c.get("booking_id") != booking_ctx["booking"]["id"] for c in cr.json())

        # try to fetch a real contract by id
        # First get the real contract id as admin
        adm_r = requests.post(f"{API}/auth/login",
                              json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
        adm = adm_r.json()["token"]
        all_c = requests.get(f"{API}/contracts/mine", headers=_h(adm), timeout=15).json()
        # admin sees all per server impl? if not, skip
        if not all_c:
            pytest.skip("admin cannot list all contracts in this impl")
        cid = all_c[0]["id"]
        r = requests.get(f"{API}/contracts/{cid}/pdf",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code in (403, 404)

    def test_invoice_pdf(self, booking_ctx, customer):
        bid = booking_ctx["booking"]["id"]
        r = requests.get(f"{API}/bookings/{bid}/invoice",
                         headers={"Authorization": f"Bearer {customer['token']}"}, timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"

    def test_invoice_pdf_forbidden(self, booking_ctx):
        # register a stranger
        email = f"TEST_invs_{uuid.uuid4().hex[:6]}@booktalent.com"
        _verify_email(email)
        rr = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "Test@1234", "first_name": "S",
            "last_name": "T", "phone": "+9198" + str(int(time.time()))[-8:],
            "role": "customer",
        }, timeout=15).json()
        tok = rr["token"]
        bid = booking_ctx["booking"]["id"]
        r = requests.get(f"{API}/bookings/{bid}/invoice",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code in (403, 404)


class TestRefund:
    def test_refund_admin_only(self, customer, artist, admin):
        # New booking + paid token (mock)
        ad = requests.get(f"{API}/artists/{artist['user']['id']}", timeout=15).json()
        pid = ad["packages"][0]["id"]
        body = {
            "artist_id": artist["user"]["id"], "package_id": pid, "addons": [],
            "event_date": "2027-10-10", "event_time": "18:00",
            "event_type": "Wedding", "venue": "TEST", "city": "Mumbai",
            "guests": "60",
        }
        bk = requests.post(f"{API}/bookings", json=body,
                           headers=_h(customer["token"]), timeout=15).json()
        bid = bk["id"]
        init = requests.post(f"{API}/payments/init",
                             json={"booking_id": bid, "method": "card"},
                             headers=_h(customer["token"]), timeout=15).json()
        pay_id = init["payment_id"]
        v = requests.post(f"{API}/payments/verify",
                          json={"payment_id": pay_id, "booking_id": bid, "mock_otp": "123456"},
                          headers=_h(customer["token"]), timeout=15)
        assert v.status_code == 200

        # Non-admin refund attempt → 403
        r_forbid = requests.post(f"{API}/payments/{pay_id}/refund",
                                 json={}, headers=_h(customer["token"]), timeout=15)
        assert r_forbid.status_code in (401, 403)

        # Wallet balance before
        w_before = requests.get(f"{API}/wallet",
                                headers=_h(customer["token"]), timeout=15).json().get("balance", 0)

        # Admin refund
        r = requests.post(f"{API}/payments/{pay_id}/refund",
                          json={"reason": "test_refund"},
                          headers=_h(admin["token"]), timeout=15)
        assert r.status_code == 200, r.text
        amt = r.json().get("amount")
        assert amt and amt > 0

        # Customer wallet credited
        w_after = requests.get(f"{API}/wallet",
                               headers=_h(customer["token"]), timeout=15).json().get("balance", 0)
        assert w_after >= w_before + amt - 0.01


class TestWebhook:
    def test_webhook_disabled_when_no_keys(self):
        # Razorpay disabled - should return ok:false with reason
        r = requests.post(f"{API}/payments/webhook",
                          data=b'{"event":"payment.captured"}',
                          headers={"Content-Type": "application/json"}, timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d.get("ok") is False
        assert d.get("reason") == "razorpay_disabled"
