"""
Iter 53 — Artist Payment Gating tests.

Business rules under test:
1. GET /api/bookings/mine as ARTIST must strip pricing.platform_fee/gst/total/
   token_amount/balance_due/coupon_discount but keep pricing.package_fee/
   addons_total/artist_fee.
2. GET /api/bookings/{id} as ARTIST: same pricing scrub + contact_unlocked=False
   + _contact_locked=True + customer.phone/email removed + booking.customer_phone/
   customer_email removed when amount_paid == 0.
3. GET /api/bookings/{id} as CUSTOMER (same booking) must retain full pricing.
4. GET /api/bookings/{id}/invoice: artist -> 403; customer -> 200 PDF.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback for local run
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"')
                break

ARTIST = {"email": "priya@booktalent.com", "password": "Artist@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}

FORBIDDEN_ARTIST_KEYS = (
    "platform_fee",
    "gst",
    "total",
    "token_amount",
    "balance_due",
    "coupon_discount",
)
REQUIRED_ARTIST_KEYS = ("package_fee", "addons_total", "artist_fee")


# ---------------- fixtures ----------------
def _login(creds: dict) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def artist_session():
    return _login(ARTIST)


@pytest.fixture(scope="module")
def customer_session():
    return _login(CUSTOMER)


@pytest.fixture(scope="module")
def artist_bookings(artist_session):
    r = artist_session.get(f"{BASE_URL}/api/bookings/mine", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    return data


# ---------------- Tests ----------------
class TestArtistBookingsMine:
    """/bookings/mine as artist must scrub BookTalent pricing lines."""

    def test_has_bookings(self, artist_bookings):
        # Priya is seeded with demo bookings.
        assert len(artist_bookings) > 0, "expected priya to have at least 1 booking"

    def test_pricing_redacted(self, artist_bookings):
        for b in artist_bookings:
            p = b.get("pricing") or {}
            for k in FORBIDDEN_ARTIST_KEYS:
                assert k not in p, f"booking {b.get('id')} leaked pricing.{k}={p.get(k)}"

    def test_pricing_retains_artist_keys(self, artist_bookings):
        # Bookings created via the new pricing engine expose package_fee/addons_total/artist_fee.
        # Legacy bookings (pre-Iter 53) may use `base`/`addons` schema — those are ignored here
        # because the redactor only removes forbidden keys, not add missing ones.
        modern = [b for b in artist_bookings if "package_fee" in (b.get("pricing") or {})]
        if not modern:
            pytest.skip("no bookings with modern package_fee schema (all legacy)")
        for b in modern:
            p = b["pricing"]
            for k in REQUIRED_ARTIST_KEYS:
                assert k in p, f"booking {b.get('id')} missing pricing.{k}"

    def test_unpaid_bookings_contact_locked(self, artist_bookings):
        # Any booking with amount_paid==0 must have customer contact stripped
        any_unpaid = False
        for b in artist_bookings:
            if (b.get("amount_paid", 0) or 0) == 0 and b.get("payment_status") != "paid":
                any_unpaid = True
                assert b.get("_contact_locked") is True, f"booking {b.get('id')} not marked locked"
                assert "customer_phone" not in b, f"leaked customer_phone in {b.get('id')}"
                assert "customer_email" not in b, f"leaked customer_email in {b.get('id')}"
        if not any_unpaid:
            pytest.skip("no unpaid bookings in priya's list to assert lock")


class TestArtistBookingDetail:
    """/bookings/{id} as artist must scrub + gate contact."""

    @pytest.fixture(scope="class")
    def target_booking(self, artist_session):
        r = artist_session.get(f"{BASE_URL}/api/bookings/mine", timeout=15)
        assert r.status_code == 200
        bookings = r.json()
        # Prefer an unpaid one for the strictest assertions
        unpaid = [b for b in bookings if (b.get("amount_paid", 0) or 0) == 0
                  and b.get("payment_status") != "paid"]
        target = (unpaid[0] if unpaid else bookings[0])
        return target

    def test_detail_pricing_scrubbed(self, artist_session, target_booking):
        bid = target_booking["id"]
        r = artist_session.get(f"{BASE_URL}/api/bookings/{bid}", timeout=15)
        assert r.status_code == 200, r.text
        detail = r.json()
        booking = detail["booking"]
        p = booking.get("pricing") or {}
        for k in FORBIDDEN_ARTIST_KEYS:
            assert k not in p, f"artist detail leaked pricing.{k}"
        # If this happens to be a modern-schema booking, ensure package_fee retained
        if "package_fee" in p:
            for k in REQUIRED_ARTIST_KEYS:
                assert k in p, f"artist detail missing pricing.{k}"

    def test_detail_contact_locked_when_unpaid(self, artist_session, target_booking):
        bid = target_booking["id"]
        r = artist_session.get(f"{BASE_URL}/api/bookings/{bid}", timeout=15)
        assert r.status_code == 200
        detail = r.json()
        amount_paid = detail["booking"].get("amount_paid", 0) or 0
        payment_status = detail["booking"].get("payment_status")
        if amount_paid == 0 and payment_status != "paid":
            assert detail.get("contact_unlocked") is False
            assert detail["booking"].get("_contact_locked") is True
            # top-level customer_phone / customer_email must be absent on booking dict
            assert "customer_phone" not in detail["booking"]
            assert "customer_email" not in detail["booking"]
            # customer object must have email/phone stripped
            cust = detail.get("customer") or {}
            assert "phone" not in cust, f"customer.phone leaked: {cust}"
            assert "email" not in cust, f"customer.email leaked: {cust}"
            assert cust.get("_contact_locked") is True
        else:
            pytest.skip("selected booking is already paid; contact unlock is expected")


class TestCustomerDetailUnaffected:
    """/bookings/{id} as customer must retain the full BookTalent pricing block."""

    def test_customer_sees_platform_fee_and_total(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/bookings/mine", timeout=15)
        assert r.status_code == 200
        bookings = r.json()
        if not bookings:
            pytest.skip("no bookings for customer")
        bid = bookings[0]["id"]
        detail = customer_session.get(f"{BASE_URL}/api/bookings/{bid}", timeout=15).json()
        p = detail["booking"].get("pricing") or {}
        for k in ("total", "platform_fee", "gst"):
            assert k in p, f"customer view missing pricing.{k}"


class TestInvoiceGating:
    """/bookings/{id}/invoice — artist 403, customer 200."""

    def test_artist_gets_403(self, artist_session, artist_bookings):
        if not artist_bookings:
            pytest.skip("no artist bookings")
        bid = artist_bookings[0]["id"]
        r = artist_session.get(f"{BASE_URL}/api/bookings/{bid}/invoice", timeout=15)
        assert r.status_code == 403, f"expected 403 for artist invoice, got {r.status_code}: {r.text[:200]}"

    def test_customer_gets_pdf(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/bookings/mine", timeout=15)
        bookings = r.json()
        # need a booking that has amount_paid > 0 for invoice to make sense; endpoint doesn't gate on that though
        # Try any booking of the customer
        if not bookings:
            pytest.skip("no bookings for customer")
        # Find one that would ideally be paid; if none, still test — endpoint should still return PDF
        paid = [b for b in bookings if (b.get("amount_paid", 0) or 0) > 0]
        target = paid[0] if paid else bookings[0]
        bid = target["id"]
        r = customer_session.get(f"{BASE_URL}/api/bookings/{bid}/invoice", timeout=20)
        assert r.status_code == 200, f"expected 200 PDF for customer invoice, got {r.status_code}: {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "response is not a PDF"
