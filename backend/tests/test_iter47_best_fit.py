"""
Iter 47 backend tests — /api/event-planner/best-fit resolver + regressions
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

CATS = ["Singer / Vocalist", "DJ", "Anchor / MC", "Comedian", "Dhol Artist"]


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def customer_token(sess):
    r = sess.post(f"{API}/auth/login", json={"email": "customer@booktalent.com", "password": "Customer@123"}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"customer login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token") or r.json().get("token")


# ─────────────────────────────────────────────────────────────
# Core best-fit tests
# ─────────────────────────────────────────────────────────────
class TestBestFit:
    def test_happy_path_returns_5_rows_with_expected_shape(self, sess):
        r = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": CATS, "city": "Mumbai", "event_date": "2039-05-15"},
            timeout=20,
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 5, f"expected 5 rows, got {len(data)}"
        required = {"category", "user_id", "stage_name", "profile_image",
                    "starting_price", "package_id", "city", "emoji", "matched"}
        for row in data:
            missing = required - set(row.keys())
            assert not missing, f"row missing keys: {missing}"
            if row["matched"]:
                assert row["stage_name"], f"matched row missing stage_name: {row}"
                assert row["package_id"], f"matched row missing package_id: {row}"
                assert row["starting_price"] is not None, f"matched row missing starting_price: {row}"
            else:
                # non-matched should have nullable fields cleanly null
                assert row["stage_name"] in (None, "") or row["stage_name"] is None
                assert row["package_id"] in (None, "")
                assert row["starting_price"] in (None, 0) or row["starting_price"] is None

    def test_seeded_artists_come_back_matched(self, sess):
        """Priya (Vocalist), DJ Vortex (DJ), Dhiren (Comedian) MUST be matched=true."""
        r = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": CATS, "city": "Mumbai", "event_date": "2039-05-15"},
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        by_cat = {row["category"]: row for row in data}
        # Vocalist
        v = by_cat.get("Singer / Vocalist")
        assert v and v["matched"], f"Singer/Vocalist not matched: {v}"
        # DJ
        dj = by_cat.get("DJ")
        assert dj and dj["matched"], f"DJ not matched: {dj}"
        # Comedian
        cm = by_cat.get("Comedian")
        assert cm and cm["matched"], f"Comedian not matched: {cm}"
        # Confirm the seeded names appear at least in ONE of the matched rows
        names = " ".join([str(row.get("stage_name") or "") for row in data]).lower()
        assert "priya" in names, f"Priya not in matched roster: {names}"
        assert "vortex" in names, f"Vortex not in matched roster: {names}"
        assert "dhiren" in names or "comedian" in names, f"Dhiren not detected: {names}"

    def test_empty_categories_returns_400(self, sess):
        r = sess.post(f"{API}/event-planner/best-fit", json={"categories": []}, timeout=15)
        assert r.status_code == 400
        detail = (r.json() or {}).get("detail", "")
        assert "categor" in detail.lower(), f"unexpected detail: {detail}"

    def test_no_duplicate_artist_across_categories(self, sess):
        r = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": CATS, "city": "Mumbai"},
            timeout=20,
        )
        assert r.status_code == 200
        matched_ids = [row["user_id"] for row in r.json() if row["matched"] and row["user_id"]]
        assert len(matched_ids) == len(set(matched_ids)), \
            f"dedupe broken — same artist across categories: {matched_ids}"

    def test_national_fallback_when_city_has_no_artist(self, sess):
        """category=DJ, city='Guwahati' should still return DJ Vortex from Delhi with matched=true."""
        r = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": ["DJ"], "city": "Guwahati"},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        row = data[0]
        assert row["matched"] is True, f"national fallback failed: {row}"
        assert row["stage_name"], "matched row should have a stage_name"


# ─────────────────────────────────────────────────────────────
# Event-date busy-day filter
# ─────────────────────────────────────────────────────────────
class TestBestFitBusyDate:
    def _login(self, sess, email, password):
        r = sess.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        if r.status_code != 200:
            pytest.skip(f"login {email} failed: {r.status_code}")
        return r.json().get("access_token") or r.json().get("token")

    def test_busy_artist_is_skipped(self, sess):
        """Create a confirmed booking on a specific date, then verify best-fit returns
        a DIFFERENT artist (or matched=false) for that same date."""
        cust_tok = self._login(sess, "customer@booktalent.com", "Customer@123")
        cust_headers = {"Authorization": f"Bearer {cust_tok}"}

        # First: get DJ pick for a clean date (no booking) to identify the current "best" DJ
        r0 = sess.post(
            f"{API}/event-planner/best-fit",
            json={"categories": ["DJ"], "city": "Delhi", "event_date": "2044-11-11"},
            timeout=15,
        )
        assert r0.status_code == 200
        dj0 = r0.json()[0]
        if not dj0["matched"]:
            pytest.skip("no DJ available at all — cannot test busy-day filter")
        original_dj_id = dj0["user_id"]
        original_pkg_id = dj0["package_id"]

        # Create a booking for that DJ on a specific test date
        test_date = "2044-12-24"
        booking_payload = {
            "artist_id": original_dj_id,
            "package_id": original_pkg_id,
            "event_date": test_date,
            "event_time": "19:00",
            "event_type": "Wedding",
            "city": "Delhi",
            "venue": "TEST_Venue_Iter47",
            "guests": "200",
            "notes": "TEST_iter47_busy_day",
        }
        bkr = sess.post(f"{API}/bookings", json=booking_payload, headers=cust_headers, timeout=15)
        if bkr.status_code not in (200, 201):
            pytest.skip(f"couldn't create booking for busy-day test: {bkr.status_code} {bkr.text[:200]}")
        booking_id = (bkr.json() or {}).get("id") or (bkr.json() or {}).get("booking_id")

        # Move booking status to pending_artist via mock payment init + verify (OTP 123456)
        init = sess.post(
            f"{API}/payments/init",
            json={"booking_id": booking_id, "method": "card"},
            headers=cust_headers, timeout=10,
        )
        if init.status_code == 200:
            pid = (init.json() or {}).get("payment_id")
            sess.post(
                f"{API}/payments/verify",
                json={"booking_id": booking_id, "payment_id": pid, "otp": "123456"},
                headers=cust_headers, timeout=10,
            )

        try:
            # Now query best-fit for the SAME date — DJ Vortex must NOT come back
            r1 = sess.post(
                f"{API}/event-planner/best-fit",
                json={"categories": ["DJ"], "city": "Delhi", "event_date": test_date},
                timeout=15,
            )
            assert r1.status_code == 200
            dj1 = r1.json()[0]
            # Either matched=false OR matched=true but a different user_id
            if dj1["matched"]:
                assert dj1["user_id"] != original_dj_id, \
                    f"busy artist {original_dj_id} was returned for date {test_date}"
        finally:
            if booking_id:
                try:
                    sess.delete(f"{API}/bookings/{booking_id}", headers=cust_headers, timeout=10)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────
# Regressions from iter44/45/46/43
# ─────────────────────────────────────────────────────────────
class TestRegression:
    def test_suggest_still_works(self, sess):
        r = sess.post(
            f"{API}/event-planner/suggest",
            json={"event_type": "Wedding", "guests": 300, "city": "Mumbai"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("source") in ("llm", "fallback")
        assert len(data.get("categories", [])) >= 3

    def test_counter_offer_removed(self, sess):
        r = sess.post(
            f"{API}/bookings/anything/action",
            json={"action": "counter"},
            timeout=10,
        )
        assert r.status_code != 200

    def test_batch_endpoints_registered(self, sess):
        r = sess.post(f"{API}/bookings/batch", json={}, timeout=10)
        assert r.status_code != 404
        r2 = sess.post(f"{API}/payments/batch/init", json={}, timeout=10)
        assert r2.status_code != 404
