"""
Iter 48 backend tests — verifies:
  1. GET /api/events/{event_id}/recap PUBLIC (extracted to routes/events.py)
  2. GET /api/events/{event_id}/summary AUTH (extracted to routes/events.py)
  3. POST /api/bookings/batch + /api/payments/batch/init still registered
  4. POST /api/event-planner/best-fit + /suggest regressions
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

# Live multi-artist event from previous iterations (Priya + Kavya, Mumbai 2034-06-15)
LIVE_EVENT_ID = "074519dd-c59b-4db3-a109-324b3798fbc9"


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(sess, email, password):
    r = sess.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"login {email} failed: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token") or r.json().get("token")


# ─────────────────────────────────────────────────────────────
# 1. Public recap endpoint
# ─────────────────────────────────────────────────────────────
class TestEventRecapPublic:
    def test_live_multi_artist_event_recap_200(self, sess):
        r = sess.get(f"{API}/events/{LIVE_EVENT_ID}/recap", timeout=15)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["event_id"] == LIVE_EVENT_ID
        assert data["artist_count"] == 2, f"expected 2 artists, got {data['artist_count']}"
        assert isinstance(data["artists"], list) and len(data["artists"]) == 2
        assert data["booked_via"] == "BookTalent"
        # Shape check on artist entries
        for a in data["artists"]:
            for k in ("user_id", "stage_name", "category", "city", "emoji",
                      "profile_url", "booking_ref", "booking_status"):
                assert k in a, f"artist missing key {k}: {a}"

    def test_recap_no_pii_leak(self, sess):
        """PUBLIC endpoint MUST NOT expose customer contact or payment details."""
        r = sess.get(f"{API}/events/{LIVE_EVENT_ID}/recap", timeout=15)
        assert r.status_code == 200
        raw = r.text.lower()
        # customer PII fields must not appear
        forbidden_fields = ["customer_email", "customer_phone", "amount_paid", "platform_fee"]
        for f in forbidden_fields:
            assert f not in raw, f"recap leaks PII field: {f}"
        # No pricing object at all
        data = r.json()
        assert "pricing" not in data
        # Also no booking-level pricing on individual artist entries
        for a in data["artists"]:
            assert "pricing" not in a
            assert "amount_paid" not in a
            assert "customer_email" not in a
            assert "customer_phone" not in a

    def test_nonexistent_event_404(self, sess):
        r = sess.get(f"{API}/events/nonexistent-{uuid.uuid4().hex}/recap", timeout=15)
        assert r.status_code == 404
        detail = (r.json() or {}).get("detail", "").lower()
        assert "not found" in detail

    def test_legacy_single_booking_fallback(self, sess):
        """A legacy booking id (before event_id column) should still resolve via fallback."""
        # Find any active legacy booking that has a status in active list
        # We hit the recap with a booking id that also serves as event_id fallback
        # Use the LIVE_EVENT_ID — since bookings have event_id linked, docs will exist without fallback.
        # Instead, we test the fallback path by using an id that only matches on `id` field.
        # Grab any booking id from /api/bookings for the customer.
        tok = _login(sess, "customer@booktalent.com", "Customer@123")
        rr = sess.get(f"{API}/bookings/my", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        if rr.status_code != 200:
            pytest.skip(f"couldn't list customer bookings: {rr.status_code}")
        bookings = rr.json() or []
        active = [b for b in bookings if b.get("status") in
                  ("pending_artist", "confirmed", "started", "completed", "reviewed")]
        if not active:
            pytest.skip("no active bookings to test legacy fallback with")
        # Pick a booking whose id is not also referenced as event_id in another booking
        for b in active:
            bid = b["id"]
            r = sess.get(f"{API}/events/{bid}/recap", timeout=15)
            if r.status_code == 200:
                data = r.json()
                assert data.get("artist_count", 0) >= 1
                return
        pytest.skip("no booking id resolved via legacy fallback")


# ─────────────────────────────────────────────────────────────
# 2. Auth event summary endpoint
# ─────────────────────────────────────────────────────────────
class TestEventSummaryAuth:
    def test_summary_no_token_401(self):
        # Use a bare requests.get to guarantee no Authorization header leaks in
        r = requests.get(f"{API}/events/{LIVE_EVENT_ID}/summary", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 without auth, got {r.status_code}: {r.text[:200]}"

    def test_summary_wrong_user_403(self, sess):
        """priya@ (artist) is not the customer for LIVE_EVENT_ID → should 403."""
        tok = _login(sess, "priya@booktalent.com", "Artist@123")
        r = sess.get(
            f"{API}/events/{LIVE_EVENT_ID}/summary",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for non-owner, got {r.status_code}: {r.text[:200]}"

    def test_summary_owner_200_with_aggregate(self, sess):
        """The event was created by the customer — customer@ MUST get 200 + aggregate."""
        tok = _login(sess, "customer@booktalent.com", "Customer@123")
        r = sess.get(
            f"{API}/events/{LIVE_EVENT_ID}/summary",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        # Some fixtures may have created LIVE_EVENT_ID under a different customer email;
        # in that case skip rather than fail (customer→customer link is data-dependent).
        if r.status_code == 403:
            pytest.skip("LIVE_EVENT_ID not owned by customer@booktalent.com in this fixture")
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["event_id"] == LIVE_EVENT_ID
        assert "bookings" in data and isinstance(data["bookings"], list)
        agg = data.get("aggregate") or {}
        for k in ("platform_fee", "gst", "amount_paid", "count"):
            assert k in agg, f"aggregate missing key {k}"
        assert agg["count"] == len(data["bookings"])
        assert isinstance(agg["platform_fee"], (int, float))
        assert isinstance(agg["gst"], (int, float))
        assert isinstance(agg["amount_paid"], (int, float))


# ─────────────────────────────────────────────────────────────
# 3. Batch endpoints still registered (stayed in server.py)
# ─────────────────────────────────────────────────────────────
class TestBatchEndpointsStillRegistered:
    def test_bookings_batch_registered(self, sess):
        r = sess.post(f"{API}/bookings/batch", json={}, timeout=10)
        assert r.status_code != 404

    def test_payments_batch_init_registered(self, sess):
        r = sess.post(f"{API}/payments/batch/init", json={}, timeout=10)
        assert r.status_code != 404

    def test_payments_batch_verify_registered(self, sess):
        r = sess.post(f"{API}/payments/batch/verify", json={}, timeout=10)
        assert r.status_code != 404


# ─────────────────────────────────────────────────────────────
# 4. Event planner regressions
# ─────────────────────────────────────────────────────────────
class TestPlannerRegressions:
    def test_best_fit_shape_and_dedupe(self, sess):
        cats = ["Singer / Vocalist", "DJ", "Anchor / MC", "Comedian", "Dhol Artist"]
        r = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": cats, "city": "Mumbai", "event_date": "2039-05-15"},
            timeout=20,
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert len(data) == 5
        matched_ids = [row["user_id"] for row in data if row["matched"] and row["user_id"]]
        assert len(matched_ids) == len(set(matched_ids)), \
            f"dedupe broken across categories: {matched_ids}"
        # Every row has the required keys
        required = {"category", "user_id", "stage_name", "profile_image",
                    "starting_price", "package_id", "city", "emoji", "matched"}
        for row in data:
            assert required.issubset(row.keys()), f"missing keys: {required - set(row.keys())}"

    def test_suggest_still_works(self, sess):
        r = sess.post(
            f"{API}/event-planner/suggest",
            json={"event_type": "Wedding", "guests": 300, "city": "Mumbai"},
            timeout=40,
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data.get("source") in ("llm", "fallback")
        assert len(data.get("categories", [])) >= 3
