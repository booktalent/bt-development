"""BookTalent iteration-45 backend tests.

Focus: Multi-Artist Event Booking privacy + regression from iter43/iter44.

Verifies:
  * POST /api/bookings/batch (iter44 regression) — 2 items succeed, share event_id
  * POST /api/payments/batch/init + /verify (iter44 regression) — one payment, N pending_artist
  * Artist privacy — GET /api/bookings/mine returns ONLY the calling artist's booking
    (never sibling artists' bookings sharing the same event_id)
  * Artist privacy — GET /api/bookings/{sibling_booking_id} returns 403 for non-owner
    artist, 200 for own booking
  * Artist privacy — GET /api/events/{event_id}/summary as an artist returns 403
    (customer-owner only)
  * Single-artist flow regression (POST /bookings + /payments/init + /verify)
  * Counter-offer regression (iter43): action=counter → 422; POST /bookings/{id}/counter → 404/405
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
    """Future date in 2036-2040 range per iter45 spec."""
    y = random.randint(2036, 2040)
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
        "venue": "TEST Iter45 Venue",
        "city": city,
        "guests": "50",
        "notes": f"TEST iter45 {uuid.uuid4().hex[:6]}",
        **({"event_id": event_id} if event_id else {}),
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def customer():
    tok, user = _login(*CUSTOMER)
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


# ── Multi-artist batch creation + shared event_id ────────────────────────────

class TestMultiArtistBatchCreation:
    def test_batch_creates_three_bookings_sharing_event_id(self, customer, priya, vortex, kavya):
        """iter45 primary flow: POST /bookings/batch with 3 items → shared event_id, 3 refs."""
        d = _uniq_date()
        payload = {"items": [
            _payload(priya["user"]["id"], event_date=d),
            _payload(vortex["user"]["id"], event_date=d),
            _payload(kavya["user"]["id"], event_date=d),
        ]}
        r = requests.post(f"{API}/bookings/batch", json=payload,
                          headers=_h(customer["token"]), timeout=45)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        j = r.json()
        assert "event_id" in j
        assert isinstance(j["booking_ids"], list) and len(j["booking_ids"]) == 3
        assert isinstance(j["booking_refs"], list) and len(j["booking_refs"]) == 3
        # Aggregate pricing sanity
        pt = j["pricing_total"]
        assert pt["platform_fee"] > 0
        assert pt["gst"] > 0
        assert pt["token_amount"] > 0
        # All 3 bookings share event_id
        for bid in j["booking_ids"]:
            g = requests.get(f"{API}/bookings/{bid}", headers=_h(customer["token"]), timeout=15)
            assert g.status_code == 200
            doc = g.json().get("booking") or g.json()
            assert doc["event_id"] == j["event_id"]
        pytest.iter45_batch = {
            "event_id": j["event_id"],
            "booking_ids": j["booking_ids"],
            "booking_refs": j["booking_refs"],
            "pricing": pt,
            "artist_map": {
                j["booking_ids"][0]: priya["user"]["id"],
                j["booking_ids"][1]: vortex["user"]["id"],
                j["booking_ids"][2]: kavya["user"]["id"],
            },
        }


# ── Unified batch payment ────────────────────────────────────────────────────

class TestBatchPayment:
    def test_batch_init_and_verify_flips_all_to_pending_artist(self, customer):
        assert hasattr(pytest, "iter45_batch")
        batch = pytest.iter45_batch
        # Init
        r = requests.post(f"{API}/payments/batch/init",
                          json={"booking_ids": batch["booking_ids"], "method": "upi"},
                          headers=_h(customer["token"]), timeout=25)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["count"] == 3
        assert "payment_id" in j and j["amount"] > 0
        # Sum matches aggregate token_amount ± rounding
        expected = batch["pricing"]["token_amount"]
        assert abs(j["amount"] - expected) < 1.0
        # Verify
        v = requests.post(f"{API}/payments/batch/verify",
                          json={"payment_id": j["payment_id"], "booking_ids": batch["booking_ids"],
                                "mock_otp": "123456"},
                          headers=_h(customer["token"]), timeout=25)
        assert v.status_code == 200, v.text
        vj = v.json()
        assert vj.get("ok") is True
        assert vj["count"] == 3
        assert vj["event_id"] == batch["event_id"]
        # All 3 bookings pending_artist + amount_paid > 0
        for bid in batch["booking_ids"]:
            g = requests.get(f"{API}/bookings/{bid}", headers=_h(customer["token"]), timeout=15)
            assert g.status_code == 200
            doc = g.json().get("booking") or g.json()
            assert doc["status"] == "pending_artist", f"{bid} status={doc['status']}"
            assert float(doc.get("amount_paid") or 0) > 0
            assert doc.get("expires_at")


# ── Artist privacy — /bookings/mine + /bookings/{id} isolation ────────────────

class TestArtistPrivacy:
    def test_artist_mine_returns_only_own_booking(self, priya, vortex, kavya):
        """Each artist's /bookings/mine must contain ONLY their own booking from the
        multi-artist event — never sibling artists' bookings sharing the same event_id."""
        assert hasattr(pytest, "iter45_batch")
        batch = pytest.iter45_batch
        artist_map = batch["artist_map"]  # booking_id -> artist_user_id

        cases = [
            (priya, priya["user"]["id"]),
            (vortex, vortex["user"]["id"]),
            (kavya, kavya["user"]["id"]),
        ]
        for artist, uid in cases:
            r = requests.get(f"{API}/bookings/mine", headers=_h(artist["token"]), timeout=15)
            assert r.status_code == 200, r.text
            all_bookings = r.json()
            # Filter to this event's bookings
            event_bookings = [b for b in all_bookings if b.get("event_id") == batch["event_id"]]
            # There should be exactly ONE from this event visible to this artist
            assert len(event_bookings) == 1, (
                f"Artist {uid} sees {len(event_bookings)} bookings from event {batch['event_id']} — expected exactly 1. "
                f"Refs: {[b.get('ref') for b in event_bookings]}"
            )
            # And it must be their own
            visible = event_bookings[0]
            assert visible["artist_id"] == uid, (
                f"Artist {uid} sees another artist's booking (artist_id={visible['artist_id']}) — LEAK"
            )
            # Sanity: sibling refs not present
            visible_ids = {b["id"] for b in event_bookings}
            siblings = [bid for bid, aid in artist_map.items() if aid != uid]
            for sib in siblings:
                assert sib not in visible_ids, f"Artist {uid} sees sibling booking {sib} — LEAK"

    def test_artist_gets_403_on_sibling_booking(self, priya, vortex, kavya):
        """GET /bookings/{sibling_id} as an artist who does not own it → 403.
        GET /bookings/{own_id} as owning artist → 200."""
        assert hasattr(pytest, "iter45_batch")
        batch = pytest.iter45_batch
        artist_map = batch["artist_map"]
        tokens = {
            priya["user"]["id"]: priya["token"],
            vortex["user"]["id"]: vortex["token"],
            kavya["user"]["id"]: kavya["token"],
        }
        for bid, owner_uid in artist_map.items():
            # Owner sees 200
            own_r = requests.get(f"{API}/bookings/{bid}", headers=_h(tokens[owner_uid]), timeout=15)
            assert own_r.status_code == 200, f"owner-artist {owner_uid} got {own_r.status_code} on own booking {bid}"
            # Every non-owner artist should get 403 (or 404, but the spec asks 403)
            for other_uid, tok in tokens.items():
                if other_uid == owner_uid:
                    continue
                r = requests.get(f"{API}/bookings/{bid}", headers=_h(tok), timeout=15)
                assert r.status_code == 403, (
                    f"non-owner artist {other_uid} accessing sibling booking {bid} got {r.status_code} — expected 403 "
                    f"(body: {r.text[:200]})"
                )


# ── Artist privacy — /events/{event_id}/summary ownership ────────────────────

class TestEventSummaryOwnership:
    def test_customer_owner_can_read_summary(self, customer):
        assert hasattr(pytest, "iter45_batch")
        eid = pytest.iter45_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/summary", headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["event_id"] == eid
        assert j["aggregate"]["count"] == 3

    def test_artist_gets_403_on_event_summary(self, priya):
        """Artists (not the booking customer) must be forbidden from GET /events/{id}/summary."""
        assert hasattr(pytest, "iter45_batch")
        eid = pytest.iter45_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/summary", headers=_h(priya["token"]), timeout=15)
        assert r.status_code == 403, f"expected 403 for artist on event summary, got {r.status_code} {r.text}"

    def test_unauthenticated_gets_401_or_403(self):
        assert hasattr(pytest, "iter45_batch")
        eid = pytest.iter45_batch["event_id"]
        r = requests.get(f"{API}/events/{eid}/summary", timeout=15)
        assert r.status_code in (401, 403), f"expected auth-required, got {r.status_code}"


# ── Single-artist flow regression ────────────────────────────────────────────

class TestSingleArtistRegression:
    def test_single_flow_still_works(self, customer, priya):
        """POST /bookings + /payments/init + /payments/verify (no batch) still works
        end-to-end, and yields a booking_ref not an event_refs list."""
        r = requests.post(f"{API}/bookings",
                          json=_payload(priya["user"]["id"]),
                          headers=_h(customer["token"]), timeout=25)
        assert r.status_code in (200, 201), r.text
        b = r.json()
        assert "id" in b and "ref" in b and "event_id" in b
        # Init
        pi = requests.post(f"{API}/payments/init",
                           json={"booking_id": b["id"], "method": "upi"},
                           headers=_h(customer["token"]), timeout=20)
        assert pi.status_code == 200, pi.text
        pj = pi.json()
        assert "payment_id" in pj
        # Verify
        pv = requests.post(f"{API}/payments/verify",
                           json={"booking_id": b["id"], "payment_id": pj["payment_id"], "mock_otp": "123456"},
                           headers=_h(customer["token"]), timeout=20)
        assert pv.status_code == 200, pv.text
        vj = pv.json()
        assert "booking_ref" in vj
        # Verify state
        g = requests.get(f"{API}/bookings/{b['id']}", headers=_h(customer["token"]), timeout=15)
        doc = g.json().get("booking") or g.json()
        assert doc["status"] == "pending_artist"
        assert float(doc.get("amount_paid") or 0) > 0


# ── Iter43 regression: counter offers removed ────────────────────────────────

class TestCounterRegressionIter43:
    def test_counter_action_returns_422(self, customer, priya):
        r = requests.post(f"{API}/bookings",
                          json=_payload(priya["user"]["id"]),
                          headers=_h(customer["token"]), timeout=20)
        assert r.status_code in (200, 201)
        bid = r.json()["id"]
        priya_tok, _ = _login(*PRIYA)
        c = requests.post(f"{API}/bookings/{bid}/action",
                          json={"action": "counter", "counter_price": 12000},
                          headers=_h(priya_tok), timeout=15)
        assert c.status_code == 422, f"expected 422 got {c.status_code} {c.text}"

    def test_counter_endpoint_gone(self, customer):
        r = requests.post(f"{API}/bookings/any-id/counter",
                          json={"decision": "accept"},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code in (404, 405), f"{r.status_code} {r.text}"


# ── Iter44 regression: batch endpoints without prior event_id ────────────────

class TestBatchRegressionIter44:
    def test_batch_no_prior_event_id_auto_mints(self, customer, priya, vortex):
        d = _uniq_date()
        payload = {"items": [
            _payload(priya["user"]["id"], event_date=d),
            _payload(vortex["user"]["id"], event_date=d),
        ]}
        r = requests.post(f"{API}/bookings/batch", json=payload,
                          headers=_h(customer["token"]), timeout=40)
        assert r.status_code in (200, 201), r.text
        j = r.json()
        assert j.get("event_id"), "batch endpoint did not auto-mint event_id"
        assert len(j["booking_ids"]) == 2

    def test_batch_zero_items_400(self, customer):
        r = requests.post(f"{API}/bookings/batch", json={"items": []},
                          headers=_h(customer["token"]), timeout=15)
        assert r.status_code == 400
