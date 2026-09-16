"""
Iter9 backend tests:
- Reviews w/ photos+videos moderation pipeline (auto-approve text-only, pending for media)
- Admin reviews moderation (list + decide)
- Agency: invite, roster, invites-mine, respond, remove, bookings, stats + duplicate guard + role perms
- Corporate: bulk-bookings, bookings, stats + role perms
- Chat upload: file / voice / video-request + size caps
- Provider hooks: status, test endpoints + admin role gating
"""
import os
import base64
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
AGENCY = ("agency@booktalent.com", "Agency@123")
CORPORATE = ("corporate@booktalent.com", "Corporate@123")


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login {email} {r.status_code} {r.text[:200]}"
    return r.json()


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --- Session fixtures ---
@pytest.fixture(scope="session")
def admin():
    return _login(*ADMIN)

@pytest.fixture(scope="session")
def customer():
    return _login(*CUSTOMER)

@pytest.fixture(scope="session")
def artist():
    return _login(*ARTIST)

@pytest.fixture(scope="session")
def alt_artist():
    return _login(*ALT_ARTIST)

@pytest.fixture(scope="session")
def agency():
    return _login(*AGENCY)

@pytest.fixture(scope="session")
def corporate():
    return _login(*CORPORATE)


# ───────────────────────── Provider Hooks ─────────────────────────
class TestProviders:
    def test_providers_status_admin(self, admin):
        r = requests.get(f"{API}/admin/providers/status", headers=h(admin["token"]))
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # All six expected keys
        for k in ["email_resend", "sms_twilio", "whatsapp_gupshup", "push_fcm", "razorpay", "stripe"]:
            assert k in data, f"Missing provider {k}"
            assert "live" in data[k] and isinstance(data[k]["live"], bool)
            assert isinstance(data[k]["env_keys"], list) and len(data[k]["env_keys"]) >= 1

    def test_providers_status_non_admin_403(self, customer):
        r = requests.get(f"{API}/admin/providers/status", headers=h(customer["token"]))
        assert r.status_code == 403, r.text[:200]

    def test_provider_test_sms_mocked(self, admin):
        r = requests.post(f"{API}/admin/providers/test/sms",
                          headers=h(admin["token"]),
                          json={"to": "+919999999999", "message": "iter9 test"})
        assert r.status_code == 200, r.text
        body = r.json()
        # No keys present -> mocked
        assert body.get("status") in ("mocked", "sent", "failed")
        if body["status"] == "mocked":
            assert body.get("reason") == "no_keys"

    def test_provider_test_whatsapp_mocked(self, admin):
        r = requests.post(f"{API}/admin/providers/test/whatsapp",
                          headers=h(admin["token"]),
                          json={"to": "+919999999999", "message": "iter9"})
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("mocked", "sent", "failed")

    def test_provider_test_push_mocked(self, admin):
        r = requests.post(f"{API}/admin/providers/test/push",
                          headers=h(admin["token"]),
                          json={"to": "dummy-fcm-token", "message": "iter9"})
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("mocked", "sent", "failed")

    def test_provider_test_non_admin_403(self, customer):
        r = requests.post(f"{API}/admin/providers/test/sms",
                          headers=h(customer["token"]),
                          json={"to": "+910", "message": "x"})
        assert r.status_code == 403


# ───────────────────────── Agency ─────────────────────────
class TestAgency:
    def test_invite_duplicate_pending_rejected(self, agency):
        # priya already has pending invite per seed; duplicate should 400
        r = requests.post(f"{API}/agency/invite",
                          headers=h(agency["token"]),
                          json={"artist_email": "priya@booktalent.com", "commission_pct": 15})
        assert r.status_code == 400, f"Expected 400 dup-pending, got {r.status_code} {r.text[:200]}"

    def test_invite_unknown_artist_404(self, agency):
        r = requests.post(f"{API}/agency/invite",
                          headers=h(agency["token"]),
                          json={"artist_email": "no-such-artist@example.com", "commission_pct": 12})
        assert r.status_code == 404

    def test_invite_non_artist_rejected(self, agency):
        # customer email is not an artist
        r = requests.post(f"{API}/agency/invite",
                          headers=h(agency["token"]),
                          json={"artist_email": "customer@booktalent.com", "commission_pct": 12})
        assert r.status_code == 400

    def test_roster_returns_list(self, agency):
        r = requests.get(f"{API}/agency/roster", headers=h(agency["token"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) >= 1
        # Each row should contain artist sub-profile
        sample = rows[0]
        assert "artist_id" in sample and "status" in sample and "commission_pct" in sample

    def test_invites_mine_artist(self, artist):
        r = requests.get(f"{API}/agency/invites", headers=h(artist["token"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # Should have at least 1 pending from agency seed
        assert any(row.get("status") == "pending" for row in rows), \
            f"No pending invite for priya, got {rows}"

    def test_invites_non_artist_403(self, customer):
        r = requests.get(f"{API}/agency/invites", headers=h(customer["token"]))
        assert r.status_code == 403

    def test_stats(self, agency):
        r = requests.get(f"{API}/agency/stats", headers=h(agency["token"]))
        assert r.status_code == 200
        data = r.json()
        for k in ("roster", "pending_invites", "bookings", "gmv", "commission_earned"):
            assert k in data, f"missing key {k}"
        assert data["pending_invites"] >= 1

    def test_bookings(self, agency):
        r = requests.get(f"{API}/agency/bookings", headers=h(agency["token"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_agency_endpoints_403_for_non_agency(self, customer):
        for path in ("/agency/roster", "/agency/stats", "/agency/bookings"):
            r = requests.get(f"{API}{path}", headers=h(customer["token"]))
            assert r.status_code == 403, f"{path} expected 403, got {r.status_code}"

    def test_remove_endpoint_idempotent(self, agency):
        # Removing a non-existent artist should still return ok=true (update_one no-op)
        r = requests.post(f"{API}/agency/remove/non-existent-artist-id",
                          headers=h(agency["token"]),
                          json={})
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ───────────────────────── Corporate ─────────────────────────
@pytest.fixture(scope="session")
def priya_pkg(artist):
    # Get first package for priya
    r = requests.get(f"{API}/artists/by-email?email=priya@booktalent.com")
    # fallback: query packages via her id
    me = artist["user"]
    # priya user id != customer id, fetch via /artists/{id} or /packages?artist_id=
    # Use generic profile endpoint
    rp = requests.get(f"{API}/users/me", headers=h(artist["token"]))
    artist_id = rp.json()["id"] if rp.status_code == 200 else me.get("id")
    rk = requests.get(f"{API}/packages?artist_id={artist_id}")
    if rk.status_code != 200:
        # try artist profile route
        rk = requests.get(f"{API}/artists/{artist_id}")
        if rk.status_code == 200:
            pkgs = rk.json().get("packages", [])
        else:
            pkgs = []
    else:
        pkgs = rk.json() if isinstance(rk.json(), list) else rk.json().get("packages", [])
    assert pkgs, f"Need at least one priya package for corporate bulk test, got {pkgs}"
    return {"artist_id": artist_id, "package_id": pkgs[0]["id"]}


class TestCorporate:
    def test_bulk_bookings_partial(self, corporate, priya_pkg):
        future = (datetime.now(timezone.utc) + timedelta(days=120)).strftime("%Y-%m-%d")
        future2 = (datetime.now(timezone.utc) + timedelta(days=121)).strftime("%Y-%m-%d")
        body = {"bookings": [
            {**priya_pkg, "event_date": future,
             "event_type": "Corporate", "venue": "Test HQ", "city": "Mumbai",
             "cost_centre": "ENG-CC1", "po_number": "PO-ITER9-001", "headcount": 100},
            {"artist_id": priya_pkg["artist_id"], "package_id": "no-such-pkg",
             "event_date": future2, "event_type": "Corporate", "venue": "BadVenue",
             "city": "Mumbai", "cost_centre": "ENG-CC1", "po_number": "PO-ITER9-002"},
        ]}
        r = requests.post(f"{API}/corporate/bulk-bookings",
                          headers=h(corporate["token"]), json=body)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["created"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["error"] == "package_not_found"

    def test_corporate_bookings_list(self, corporate):
        r = requests.get(f"{API}/corporate/bookings", headers=h(corporate["token"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert any(b.get("is_corporate_bulk") for b in rows), "No corporate-bulk booking found"

    def test_corporate_stats(self, corporate):
        r = requests.get(f"{API}/corporate/stats", headers=h(corporate["token"]))
        assert r.status_code == 200
        d = r.json()
        for k in ("total_spend", "bookings", "by_cost_centre"):
            assert k in d
        assert d["bookings"] >= 1
        # Verify cost-centre map shape
        assert isinstance(d["by_cost_centre"], dict)
        if "ENG-CC1" in d["by_cost_centre"]:
            assert "spend" in d["by_cost_centre"]["ENG-CC1"]
            assert "bookings" in d["by_cost_centre"]["ENG-CC1"]

    def test_corporate_endpoints_403_for_non_corporate(self, customer):
        for path in ("/corporate/bookings", "/corporate/stats"):
            r = requests.get(f"{API}{path}", headers=h(customer["token"]))
            assert r.status_code == 403


# ───────────────────────── Reviews + Moderation ─────────────────────────
@pytest.fixture(scope="session")
def completed_booking_for_review(customer, alt_artist):
    """Find or create a completed booking customer→alt_artist that has no review yet."""
    # List customer's bookings
    r = requests.get(f"{API}/bookings/mine", headers=h(customer["token"]))
    if r.status_code != 200:
        pytest.skip(f"Cannot list customer bookings: {r.status_code}")
    bookings = r.json() if isinstance(r.json(), list) else r.json().get("bookings", [])
    # Find a confirmed/completed booking we haven't reviewed
    for b in bookings:
        if b.get("status") in ("completed", "confirmed"):
            # Check if review exists
            chk = requests.get(f"{API}/reviews/artist/{b['artist_id']}")
            existing_review = False
            if chk.status_code == 200:
                for rv in chk.json():
                    if rv.get("booking_id") == b["id"]:
                        existing_review = True
                        break
            if not existing_review:
                return b
    pytest.skip("No reviewable booking available for customer")


def _tiny_image_data_url():
    # 1x1 transparent PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


class TestReviewsModeration:
    def test_admin_reviews_list_filters(self, admin):
        for status in ("pending", "approved", "rejected", "all"):
            r = requests.get(f"{API}/admin/reviews?status={status}", headers=h(admin["token"]))
            assert r.status_code == 200, f"{status} -> {r.status_code} {r.text[:200]}"
            assert isinstance(r.json(), list)

    def test_admin_reviews_non_admin_403(self, customer):
        r = requests.get(f"{API}/admin/reviews", headers=h(customer["token"]))
        assert r.status_code == 403

    def test_review_with_photo_goes_pending_and_moderation_flow(self, customer, admin, completed_booking_for_review):
        b = completed_booking_for_review
        # POST review with a photo
        payload = {
            "booking_id": b["id"],
            "rating": 5,
            "text": "TEST_iter9 with media",
            "photos": [_tiny_image_data_url()],
            "videos": [],
        }
        r = requests.post(f"{API}/reviews", headers=h(customer["token"]), json=payload)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["status"] == "pending", f"Expected pending, got {data}"
        rid = data["review_id"]

        # Admin sees it in pending list
        ar = requests.get(f"{API}/admin/reviews?status=pending", headers=h(admin["token"]))
        assert ar.status_code == 200
        ids = [d["id"] for d in ar.json()]
        assert rid in ids, f"Newly-created pending review {rid} missing from admin pending list"

        # Admin approves
        mr = requests.post(f"{API}/admin/reviews/{rid}/moderate",
                           headers=h(admin["token"]),
                           json={"decision": "approve", "reason": "iter9 test approve"})
        assert mr.status_code == 200, mr.text[:200]

        # Confirm it now appears in approved list
        ap = requests.get(f"{API}/admin/reviews?status=approved", headers=h(admin["token"]))
        ids_app = [d["id"] for d in ap.json()]
        assert rid in ids_app


# ───────────────────────── Chat upload ─────────────────────────
@pytest.fixture(scope="session")
def chat_booking(customer):
    r = requests.get(f"{API}/bookings/mine", headers=h(customer["token"]))
    if r.status_code != 200:
        pytest.skip("Cannot list bookings")
    bookings = r.json() if isinstance(r.json(), list) else r.json().get("bookings", [])
    if not bookings:
        pytest.skip("Customer has no bookings for chat test")
    return bookings[0]


class TestChatUpload:
    def test_chat_file_upload(self, customer, chat_booking):
        bid = chat_booking["id"]
        r = requests.post(f"{API}/chat/{bid}/upload",
                          headers=h(customer["token"]),
                          json={
                              "booking_id": bid,
                              "type": "file",
                              "data_url": "data:application/pdf;base64,"
                                          + base64.b64encode(b"hello-iter9-file").decode(),
                              "filename": "iter9.pdf",
                          })
        assert r.status_code == 200, r.text[:300]
        msg = r.json()
        assert msg["type"] == "file" and msg["filename"] == "iter9.pdf"
        assert msg.get("media_id")

    def test_chat_voice_upload(self, customer, chat_booking):
        bid = chat_booking["id"]
        r = requests.post(f"{API}/chat/{bid}/upload",
                          headers=h(customer["token"]),
                          json={
                              "booking_id": bid,
                              "type": "voice",
                              "data_url": "data:audio/webm;base64,"
                                          + base64.b64encode(b"\x00" * 1024).decode(),
                              "duration_sec": 4.2,
                          })
        assert r.status_code == 200, r.text[:300]
        msg = r.json()
        assert msg["type"] == "voice"
        assert "Voice note" in msg["content"]

    def test_chat_video_request(self, customer, chat_booking):
        bid = chat_booking["id"]
        r = requests.post(f"{API}/chat/{bid}/upload",
                          headers=h(customer["token"]),
                          json={"booking_id": bid, "type": "video-request",
                                "note": "Can we do a video call tomorrow?"})
        assert r.status_code == 200, r.text[:300]
        msg = r.json()
        assert msg["type"] == "video-request"
        assert msg["media_id"] is None

    def test_chat_voice_oversize_rejected(self, customer, chat_booking):
        bid = chat_booking["id"]
        # 6 MB base64 buffer -> raw > 5 MB cap
        oversize = base64.b64encode(b"\x00" * (6 * 1024 * 1024)).decode()
        r = requests.post(f"{API}/chat/{bid}/upload",
                          headers=h(customer["token"]),
                          json={"booking_id": bid, "type": "voice",
                                "data_url": "data:audio/webm;base64," + oversize,
                                "duration_sec": 60})
        assert r.status_code == 400, f"expected 400 cap, got {r.status_code} {r.text[:200]}"

    def test_chat_stranger_403(self, alt_artist, chat_booking):
        # vortex is not on customer's booking
        bid = chat_booking["id"]
        r = requests.post(f"{API}/chat/{bid}/upload",
                          headers=h(alt_artist["token"]),
                          json={"booking_id": bid, "type": "video-request", "note": "intrusion"})
        assert r.status_code == 403
