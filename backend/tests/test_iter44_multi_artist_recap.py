"""BookTalent iteration-44 backend tests.

Verifies:
  * POST /api/bookings — event_id optional, auto-generated when omitted; when
    provided must belong to another booking of the same customer, else 400.
  * Sequential bookings sharing the same event_id via body param.
  * POST /api/bookings/batch — happy path with 2 items, 0/7 items error cases.
  * POST /api/payments/batch/init — aggregates token_amount, returns event count
    and gateway.
  * POST /api/payments/batch/verify — sets pending_artist, expires_at, and
    per-booking amount_paid == its own token share.
  * GET /api/events/{event_id}/recap — public shape, no PII, artist_count,
    legacy fallback by booking id, 404 for nonexistent.
  * GET /api/events/{event_id}/summary — requires auth + ownership; 403 across
    customers.
  * Counter-offer regression (iter43) still holds.
"""

import os
import random
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL not set")
API = f"{BASE_URL}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")
PRIYA = ("priya@booktalent.com", "Artist@123")
VORTEX = ("vortex@booktalent.com", "Artist@123")
KAVYA = ("kavya@booktalent.com", "Artist@123")


def _h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _uniq_date():
    """Future date in 2029-2035 range to avoid seed collision."""
    y = random.randint(2029, 2035)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


def _first_pkg(artist_id):
    r = requests.get(f"{API}/artists/{artist_id}", timeout=15)
    assert r.status_code == 200, r.text
    pkgs = r.json().get("packages") or []
    assert pkgs, f"artist {artist_id} has no packages"
    return pkgs[0]["id"]


def _mandatory_addons(artist_id):
    r = requests.get(f"{API}/artists/{artist_id}/addons", timeout=15)
    if r.status_code != 200:
        return []
    return [{"addon_id": a["id"], "quantity": 1} for a in (r.json() or []) if a.get("is_mandatory")]


def _payload(artist_id, event_date=None, event_id=None, city="Mumbai"):
    return {
        "artist_id": artist_id,
        "package_id": _first_pkg(artist_id),
        "addons": [],
        "addon_selections": _mandatory_addons(artist_id),
        "event_date": event_date or _uniq_date(),
        "event_time": "19:00",
        "event_type": "corporate",
        "venue": "TEST Iter44 Venue",
        "city": city,
        "guests": "50",
        "notes": f"TEST iter44 {uuid.uuid4().hex[:6]}",
        **({"event_id": event_id} if event_id else {}),
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def customer():
    tok, user = _login(*CUSTOMER)
    return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def customer2():
    """A second customer identity for cross-owner ACL tests. We reuse
    'corporate@booktalent.com' if it exists; else fall back to admin."""
    try:
        tok, user = _login("corporate@booktalent.com", "Corporate@123")
        return {"token": tok, "user": user}
    except AssertionError:
        tok, user = _login(*ADMIN)
        return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def priya():
    tok, user = _login(*PRIYA)
    return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def vortex():
    tok, user = _login(*VORTEX)
    return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def kavya():
    tok, user = _login(*KAVYA)
    return {"token": tok, "user": user}


# ── Booking event_id resolution ──────────────────────────────────────────────

class TestBookingEventId:
    def test_create_booking_no_event_id_returns_auto_generated(self, customer, priya):
        r = requests.post(
            f"{API}/bookings",
            json=_payload(priya["user"]["id"]),
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        b = r.json()
        assert "event_id" in b and isinstance(b["event_id"], str) and len(b["event_id"]) >= 8
        # Sanity: event_id != booking id
        assert b["event_id"] != b["id"]

    def test_create_booking_invalid_event_id_400(self, customer, priya):
        bogus = str(uuid.uuid4())
        r = requests.post(
            f"{API}/bookings",
            json=_payload(priya["user"]["id"], event_id=bogus),
            headers=_h(customer["token"]),
            timeout=20,
        )
        assert r.status_code == 400, f"{r.status_code} {r.text}"
        assert "event_id" in r.text.lower()

    def test_two_sequential_bookings_share_event_id(self, customer, priya, vortex):
        d = _uniq_date()
        r1 = requests.post(
            f"{API}/bookings",
            json=_payload(priya["user"]["id"], event_date=d),
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert r1.status_code in (200, 201), r1.text
        b1 = r1.json()
        eid = b1["event_id"]

        r2 = requests.post(
            f"{API}/bookings",
            json=_payload(vortex["user"]["id"], event_date=d, event_id=eid),
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert r2.status_code in (200, 201), r2.text
        b2 = r2.json()
        assert b2["event_id"] == eid, f"expected same event_id, got {b2['event_id']} vs {eid}"


# ── Batch booking ───────────────────────────────────────────────────────────

class TestBookingBatch:
    def test_batch_happy_path_two_artists(self, customer, priya, kavya):
        d = _uniq_date()
        payload = {
            "items": [
                _payload(priya["user"]["id"], event_date=d),
                _payload(kavya["user"]["id"], event_date=d),
            ]
        }
        r = requests.post(
            f"{API}/bookings/batch",
            json=payload,
            headers=_h(customer["token"]),
            timeout=40,
        )
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        j = r.json()
        assert "event_id" in j
        assert "booking_ids" in j and len(j["booking_ids"]) == 2
        assert "booking_refs" in j and len(j["booking_refs"]) == 2
        pt = j["pricing_total"]
        assert "platform_fee" in pt and "gst" in pt and "token_amount" in pt
        assert pt["token_amount"] > 0
        # Both bookings share event_id
        for bid in j["booking_ids"]:
            g = requests.get(f"{API}/bookings/{bid}", headers=_h(customer["token"]), timeout=15)
            assert g.status_code == 200
            doc = g.json().get("booking") or g.json()
            assert doc["event_id"] == j["event_id"]
        # Stash for the next test class
        pytest.iter44_batch = {"event_id": j["event_id"], "booking_ids": j["booking_ids"], "pt": pt}

    def test_batch_zero_items_400(self, customer):
        r = requests.post(
            f"{API}/bookings/batch",
            json={"items": []},
            headers=_h(customer["token"]),
            timeout=15,
        )
        assert r.status_code == 400, f"{r.status_code} {r.text}"
        assert "at least one" in r.text.lower()

    def test_batch_seven_items_400(self, customer, priya):
        # We only need to trip the length check — payload validity is irrelevant
        # because the length gate should run BEFORE we create any doc.
        items = [_payload(priya["user"]["id"]) for _ in range(7)]
        r = requests.post(
            f"{API}/bookings/batch",
            json={"items": items},
            headers=_h(customer["token"]),
            timeout=20,
        )
        assert r.status_code == 400, f"{r.status_code} {r.text}"
        assert "6" in r.text or "more than" in r.text.lower()


# ── Batch payment ────────────────────────────────────────────────────────────

class TestBatchPayment:
    def test_payments_batch_init_and_verify(self, customer):
        assert hasattr(pytest, "iter44_batch"), "Depends on TestBookingBatch.happy path"
        batch = pytest.iter44_batch
        # Init
        r = requests.post(
            f"{API}/payments/batch/init",
            json={"booking_ids": batch["booking_ids"], "method": "upi"},
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        j = r.json()
        assert "payment_id" in j and "amount" in j and "gateway" in j
        assert j.get("count") == 2, f"expected count=2, got {j.get('count')}"
        # Sum matches per-booking token_amount total (± 1 rupee rounding)
        expected = batch["pt"]["token_amount"]
        assert abs(j["amount"] - expected) < 1.0, f"amount {j['amount']} != sum {expected}"

        # Verify with mock OTP
        v = requests.post(
            f"{API}/payments/batch/verify",
            json={"payment_id": j["payment_id"], "booking_ids": batch["booking_ids"], "mock_otp": "123456"},
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert v.status_code == 200, f"{v.status_code} {v.text}"
        vj = v.json()
        assert vj.get("ok") is True
        assert vj.get("count") == 2
        assert vj.get("event_id") == batch["event_id"]

        # Verify both bookings: pending_artist, expires_at populated, amount_paid = own share
        # Each booking's amount_paid must equal its OWN pricing.token_amount (not batch total,
        # not batch/2 — different artists can have different rates).
        sum_amount_paid = 0.0
        for bid in batch["booking_ids"]:
            g = requests.get(f"{API}/bookings/{bid}", headers=_h(customer["token"]), timeout=15)
            assert g.status_code == 200, g.text
            doc = g.json().get("booking") or g.json()
            assert doc["status"] == "pending_artist", f"{bid} status={doc['status']}"
            assert doc.get("expires_at"), f"{bid} missing expires_at"
            ap = float(doc.get("amount_paid", 0))
            own_token = float((doc.get("pricing") or {}).get("token_amount", 0) or 0)
            assert ap > 0
            # each booking gets its OWN token share, not the batch total
            assert ap < expected, f"{bid} amount_paid={ap} equals batch total {expected} — must be per-booking share"
            assert abs(ap - own_token) < 1.0, f"{bid} amount_paid={ap} != own pricing.token_amount={own_token}"
            sum_amount_paid += ap
        # Sum across bookings should equal the batch total (± rounding)
        assert abs(sum_amount_paid - expected) < 2.0, f"sum of per-booking amount_paid={sum_amount_paid} != batch total {expected}"


# ── Batch payment: regression guard (already-confirmed booking must not regress) ──

class TestBatchPaymentRegressionGuard:
    def test_batch_verify_skips_confirmed_booking(self, customer, priya, kavya):
        """If one of the bookings in a batch is already `confirmed` when
        payment_batch_verify is called, it must NOT be regressed back to
        `pending_artist`. Server should only mutate bookings whose current
        status == 'pending_payment'."""
        from pymongo import MongoClient
        # Create a fresh batch (2 items)
        d = _uniq_date()
        payload = {"items": [
            _payload(priya["user"]["id"], event_date=d),
            _payload(kavya["user"]["id"], event_date=d),
        ]}
        r = requests.post(f"{API}/bookings/batch", json=payload,
                          headers=_h(customer["token"]), timeout=40)
        assert r.status_code in (200, 201), r.text
        j = r.json()
        booking_ids = j["booking_ids"]
        # Init payment
        pi = requests.post(f"{API}/payments/batch/init",
                           json={"booking_ids": booking_ids, "method": "upi"},
                           headers=_h(customer["token"]), timeout=15)
        assert pi.status_code == 200, pi.text
        pid = pi.json()["payment_id"]
        # Pre-flip the FIRST booking to 'confirmed' directly in DB
        mongo_url = (os.environ.get("MONGO_URL") or "mongodb://localhost:27017").strip().strip('"').strip("'")
        db_name = (os.environ.get("DB_NAME") or "booktalent").strip().strip('"').strip("'")
        mc = MongoClient(mongo_url)
        db = mc[db_name]
        target_bid = booking_ids[0]
        upd = db.bookings.update_one({"id": target_bid}, {"$set": {"status": "confirmed"}})
        assert upd.modified_count == 1
        # Now hit verify — it must skip the confirmed booking
        v = requests.post(f"{API}/payments/batch/verify",
                          json={"payment_id": pid, "booking_ids": booking_ids, "mock_otp": "123456"},
                          headers=_h(customer["token"]), timeout=25)
        assert v.status_code == 200, v.text
        # Fetch both bookings back
        g0 = requests.get(f"{API}/bookings/{booking_ids[0]}", headers=_h(customer["token"]), timeout=15).json()
        g1 = requests.get(f"{API}/bookings/{booking_ids[1]}", headers=_h(customer["token"]), timeout=15).json()
        d0 = g0.get("booking") or g0
        d1 = g1.get("booking") or g1
        assert d0["status"] == "confirmed", f"pre-confirmed booking regressed to {d0['status']}"
        assert d1["status"] == "pending_artist", f"second booking should have flipped to pending_artist, got {d1['status']}"


# ── Recap public endpoint ───────────────────────────────────────────────────

class TestRecap:
    def test_recap_public_shape_and_no_pii(self, customer):
        # Reuse batch event_id (both bookings are now pending_artist)
        eid = pytest.iter44_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/recap", timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        j = r.json()
        # required fields
        for key in ("event_id", "event_date", "event_time", "event_type", "venue", "city",
                    "host_first_name", "artist_count", "artists", "booked_via"):
            assert key in j, f"missing key {key} in recap"
        assert j["booked_via"] == "BookTalent"
        assert j["artist_count"] == len(j["artists"]) == 2
        for a in j["artists"]:
            for k in ("user_id", "stage_name", "category", "city", "emoji", "booking_ref", "booking_status"):
                assert k in a, f"artist missing {k}: {a}"
        # host_first_name should be just the first token / no spaces
        assert " " not in (j["host_first_name"] or "").strip(), f"host_first_name should be first name only: {j['host_first_name']}"
        # PII/payment leakage check across full response body
        text = requests.get(f"{API}/events/{eid}/recap", timeout=15).text.lower()
        forbidden = ["customer_email", "customer_phone", "amount_paid", "platform_fee", "\"gst\""]
        for f in forbidden:
            assert f not in text, f"recap leaks forbidden field: {f}"

    def test_recap_legacy_by_booking_id_fallback(self, customer, priya):
        """A pre-existing single-artist booking whose event_id was never set on
        the doc must still be shareable via its own booking id."""
        # Create a fresh booking + pay it via the single-booking flow so it
        # becomes pending_artist; then hit /events/{booking.id}/recap. Even
        # though booking.event_id is now auto-generated (not equal to booking.id),
        # requesting recap by booking.id must return the legacy match.
        r = requests.post(
            f"{API}/bookings",
            json=_payload(priya["user"]["id"]),
            headers=_h(customer["token"]),
            timeout=25,
        )
        assert r.status_code in (200, 201), r.text
        b = r.json()
        # Pay via single-flow
        pi = requests.post(
            f"{API}/payments/init",
            json={"booking_id": b["id"], "method": "upi"},
            headers=_h(customer["token"]),
            timeout=15,
        )
        assert pi.status_code == 200, pi.text
        pv = requests.post(
            f"{API}/payments/verify",
            json={"booking_id": b["id"], "payment_id": pi.json()["payment_id"], "mock_otp": "123456"},
            headers=_h(customer["token"]),
            timeout=15,
        )
        assert pv.status_code == 200, pv.text

        # Recap by booking.id (the "legacy" fallback path)
        rr = requests.get(f"{API}/events/{b['id']}/recap", timeout=15)
        assert rr.status_code == 200, f"legacy recap by booking.id failed: {rr.status_code} {rr.text}"
        j = rr.json()
        assert j["artist_count"] >= 1
        assert any(a["booking_ref"] == b["ref"] for a in j["artists"])

    def test_recap_nonexistent_404(self):
        r = requests.get(f"{API}/events/nonexistent-id-abc-xyz/recap", timeout=15)
        assert r.status_code == 404, f"{r.status_code} {r.text}"


# ── Event summary (auth + ownership) ────────────────────────────────────────

class TestEventSummary:
    def test_owner_can_read_summary(self, customer):
        eid = pytest.iter44_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/summary", headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        j = r.json()
        assert j["event_id"] == eid
        agg = j["aggregate"]
        for k in ("platform_fee", "gst", "amount_paid", "count"):
            assert k in agg
        assert agg["count"] == 2
        assert agg["amount_paid"] > 0

    def test_summary_requires_auth(self):
        eid = pytest.iter44_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/summary", timeout=15)
        assert r.status_code in (401, 403), f"expected auth-required, got {r.status_code}"

    def test_other_customer_gets_403(self, customer2):
        """A different customer (or non-admin user) accessing another user's
        event summary must be forbidden."""
        eid = pytest.iter44_batch["event_id"]
        # If customer2 fell back to admin, skip — admin is explicitly allowed.
        if customer2["user"].get("role") == "admin":
            pytest.skip("customer2 fell back to admin — ownership check bypassed by design")
        r = requests.get(f"{API}/events/{eid}/summary", headers=_h(customer2["token"]), timeout=15)
        assert r.status_code == 403, f"expected 403 for non-owner, got {r.status_code} {r.text}"


# ── Counter-offer regression (iter43 must still hold) ───────────────────────

class TestCounterRegression:
    def test_counter_action_still_422(self, customer, priya):
        r = requests.post(
            f"{API}/bookings",
            json=_payload(priya["user"]["id"]),
            headers=_h(customer["token"]),
            timeout=20,
        )
        assert r.status_code in (200, 201), r.text
        bid = r.json()["id"]
        # Login as priya to POST action
        priya_tok, _ = _login(*PRIYA)
        c = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": "counter", "counter_price": 12000},
            headers=_h(priya_tok),
            timeout=15,
        )
        assert c.status_code == 422, f"expected 422 for action=counter, got {c.status_code} {c.text}"

    def test_counter_endpoint_still_gone(self, customer):
        r = requests.post(
            f"{API}/bookings/any-id/counter",
            json={"decision": "accept"},
            headers=_h(customer["token"]),
            timeout=15,
        )
        assert r.status_code in (404, 405), f"{r.status_code} {r.text}"
