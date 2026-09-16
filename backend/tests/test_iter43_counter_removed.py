"""BookTalent iteration-43 backend tests.

Verifies that:
  - The counter-offer feature is fully removed from the backend.
      * POST /bookings/{bid}/action REJECTS action="counter" (422 pydantic, or 400).
      * POST /bookings/{bid}/counter endpoint no longer exists (404/405).
      * BookingStatusUpdate model no longer accepts counter_price field.
  - The happy-path booking flow still works end-to-end (customer books → artist
    accepts → status becomes confirmed).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL is not set")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@booktalent.com"
ADMIN_PWD = "Admin@123"
ARTIST_EMAIL = "priya@booktalent.com"
ARTIST_PWD = "Artist@123"
CUSTOMER_EMAIL = "customer@booktalent.com"
CUSTOMER_PWD = "Customer@123"


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email, pwd):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pwd},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


# ---------- Fixtures ----------


@pytest.fixture(scope="module")
def artist_ctx():
    tok, user = _login(ARTIST_EMAIL, ARTIST_PWD)
    return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def customer_ctx():
    tok, user = _login(CUSTOMER_EMAIL, CUSTOMER_PWD)
    return {"token": tok, "user": user}


@pytest.fixture(scope="module")
def admin_ctx():
    tok, user = _login(ADMIN_EMAIL, ADMIN_PWD)
    return {"token": tok, "user": user}


def _get_artist_public_id(customer_ctx):
    """Look up Priya's user_id via the /artists list (public)."""
    r = requests.get(f"{API}/artists", timeout=15)
    assert r.status_code == 200, r.text
    for a in r.json():
        # Priya priya@booktalent.com — match by name or by user_id lookup
        name = ((a.get("first_name") or "") + " " + (a.get("last_name") or "")).lower()
        stage = (a.get("stage_name") or "").lower()
        if "priya" in name or "priya" in stage:
            return a.get("user_id") or a.get("id")
    pytest.skip("Priya artist not found in /artists list")


def _get_artist_first_package_id(artist_user_id):
    r = requests.get(f"{API}/artists/{artist_user_id}", timeout=15)
    assert r.status_code == 200, f"artist detail failed: {r.status_code} {r.text}"
    pkgs = r.json().get("packages") or []
    assert pkgs, f"Artist {artist_user_id} has no packages"
    return pkgs[0]["id"]


def _get_mandatory_addon_selections(artist_user_id):
    r = requests.get(f"{API}/artists/{artist_user_id}/addons", timeout=15)
    assert r.status_code == 200, r.text
    addons = r.json() or []
    return [{"addon_id": a["id"], "quantity": 1} for a in addons if a.get("is_mandatory")]


def _uniq_date():
    """Return a unique future date to avoid double-booking clashes across
    test runs against the shared preview environment."""
    import random
    # 2027-01..2027-12 with random day/month/year within 2027-2029
    y = random.randint(2027, 2029)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"


def _create_pending_booking(customer_ctx, artist_user_id):
    """Create a fresh pending booking for the customer→artist pair.
    Uses the real /api/artists/{id} packages list to grab a valid package_id."""
    package_id = _get_artist_first_package_id(artist_user_id)
    mandatory = _get_mandatory_addon_selections(artist_user_id)
    payload = {
        "artist_id": artist_user_id,
        "package_id": package_id,
        "addons": [],
        "addon_selections": mandatory,
        "event_date": _uniq_date(),
        "event_time": "19:00",
        "event_type": "corporate",
        "venue": "TEST Iter43 Venue",
        "city": "Mumbai",
        "guests": "50",
        "notes": f"TEST iter43 counter-removal {uuid.uuid4().hex[:8]}",
    }
    r = requests.post(
        f"{API}/bookings",
        json=payload,
        headers=_h(customer_ctx["token"]),
        timeout=20,
    )
    assert r.status_code in (200, 201), f"booking create failed: {r.status_code} {r.text}"
    return r.json()


# ---------- Tests ----------


class TestCounterActionRejected:
    """POST /bookings/{bid}/action must reject action='counter'."""

    def test_counter_action_rejected_422_or_400(self, customer_ctx, artist_ctx):
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]

        # Artist tries action=counter — should fail validation
        r = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": "counter", "counter_price": 12000, "reason": "try counter"},
            headers=_h(artist_ctx["token"]),
            timeout=20,
        )
        # 422 = pydantic Literal validation, 400 = business validation
        assert r.status_code in (422, 400), (
            f"Expected 422/400 for action=counter, got {r.status_code}: {r.text}"
        )
        body_text = r.text.lower()
        # Should mention the invalid literal / action
        assert (
            "counter" in body_text
            or "literal" in body_text
            or "action" in body_text
        ), f"Error body should reference invalid action: {r.text}"

    def test_counter_price_field_ignored_by_model(self, customer_ctx, artist_ctx):
        """Even if a client sends counter_price alongside a VALID action,
        BookingStatusUpdate should not accept/persist it (extra field)."""
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]
        # Use action=reject (valid) but include counter_price — pydantic default
        # is to ignore extras; test should succeed and counter_price should be
        # dropped by the model (i.e., no server-error).
        r = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": "reject", "counter_price": 12000, "reason": "regret"},
            headers=_h(artist_ctx["token"]),
            timeout=20,
        )
        # Either 200 (extras silently dropped) or 422 (strict). Both are fine —
        # what matters is server does NOT enter counter branch.
        assert r.status_code in (200, 422), r.text
        if r.status_code == 200:
            j = r.json()
            assert j.get("status") == "rejected"


class TestCounterEndpointRemoved:
    """POST /bookings/{bid}/counter must NOT exist (404 or 405)."""

    def test_counter_endpoint_returns_404_or_405(self, customer_ctx, artist_ctx):
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]
        r = requests.post(
            f"{API}/bookings/{bid}/counter",
            json={"decision": "accept"},
            headers=_h(customer_ctx["token"]),
            timeout=20,
        )
        assert r.status_code in (404, 405), (
            f"Counter endpoint should not exist. Got {r.status_code}: {r.text}"
        )

    def test_counter_endpoint_get_also_404_or_405(self):
        # Sanity: no counter endpoint under any HTTP verb we'd typically expect
        r = requests.get(f"{API}/bookings/does-not-matter/counter", timeout=15)
        assert r.status_code in (404, 405), f"Got {r.status_code}: {r.text}"


class TestHappyPathBookingFlow:
    """Customer books → artist accepts → status=confirmed. No regression."""

    def test_full_accept_flow(self, customer_ctx, artist_ctx):
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]
        assert booking["status"] in ("pending_artist", "pending_payment"), booking
        assert "id" in booking and isinstance(booking["id"], str)
        assert "ref" in booking

        # Artist accepts
        r = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": "accept"},
            headers=_h(artist_ctx["token"]),
            timeout=25,
        )
        assert r.status_code == 200, f"accept failed: {r.status_code} {r.text}"
        j = r.json()
        assert j.get("ok") is True
        assert j.get("status") == "confirmed"

        # Verify persisted via GET (customer view)
        rg = requests.get(
            f"{API}/bookings/{bid}",
            headers=_h(customer_ctx["token"]),
            timeout=15,
        )
        assert rg.status_code == 200, rg.text
        got = rg.json().get("booking") or rg.json()
        assert got["status"] == "confirmed"
        # Model should not have a counter_price key
        assert "counter_price" not in got, "Booking doc should not carry counter_price"

    def test_reject_action_still_works(self, customer_ctx, artist_ctx):
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]
        r = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": "reject", "reason": "TEST iter43 reject path"},
            headers=_h(artist_ctx["token"]),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "rejected"


class TestValidActionsWhitelist:
    """Confirm the Literal whitelist is exactly the 6 allowed actions."""

    @pytest.mark.parametrize(
        "action",
        ["propose", "counter", "counteroffer", "COUNTER", "hold", ""],
    )
    def test_invalid_actions_rejected(self, customer_ctx, artist_ctx, action):
        artist_user_id = artist_ctx["user"]["id"]
        booking = _create_pending_booking(customer_ctx, artist_user_id)
        bid = booking["id"]
        r = requests.post(
            f"{API}/bookings/{bid}/action",
            json={"action": action},
            headers=_h(artist_ctx["token"]),
            timeout=15,
        )
        assert r.status_code in (400, 422), (
            f"action='{action}' should be rejected. Got {r.status_code}: {r.text}"
        )
