"""BookTalent iteration-4 backend tests.

Covers:
  - Onboarding (GET /onboarding/me, POST /onboarding/complete)
  - New profile fields persisted on artist_profiles (PUT /users/me)
  - Expanded media types + 100MB limit (POST /media/upload)
  - Booking-with-unavailable-date returns 400 + alternatives
  - Artist accept side-effects: contract + auto-block + mock confirmation email
  - Counter offer (action=counter) + counter decision (POST /bookings/{id}/counter)
  - Upload signed contract + dual-signed flips to fully_signed
"""
import os
import time
import uuid
import base64
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@booktalent.com"
ADMIN_PWD = "Admin@123"
ARTIST_EMAIL = "priya@booktalent.com"
ARTIST_PWD = "Artist@123"

TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
TINY_PDF_B64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50IDE+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL01lZGlhQm94WzAgMCA1OTUgODQyXT4+CmVuZG9iago="
TINY_PDF_DATA_URL = f"data:application/pdf;base64,{TINY_PDF_B64}"


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _verify_email(email: str):
    r = requests.post(f"{API}/auth/email/send", json={"email": email, "name": "T"}, timeout=15)
    assert r.status_code == 200, r.text
    otp = r.json().get("test_otp") or "123456"
    rv = requests.post(f"{API}/auth/email/verify", json={"email": email, "otp": otp}, timeout=15)
    assert rv.status_code == 200, rv.text


@pytest.fixture(scope="session")
def fresh_artist():
    """Brand-new artist with no profile / packages / media → onboarding required."""
    email = f"TEST_iter4_artist_{uuid.uuid4().hex[:8]}@booktalent.com"
    _verify_email(email)
    pwd = "Artist@1234"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd,
        "first_name": "Test", "last_name": "Artist",
        "phone": "+91" + str(int(time.time() * 1000))[-10:],
        "role": "artist",
    }, timeout=20)
    assert r.status_code == 200, r.text
    return {"token": r.json()["token"], "user": r.json()["user"], "email": email}


@pytest.fixture(scope="session")
def fresh_customer():
    email = f"TEST_iter4_cust_{uuid.uuid4().hex[:8]}@booktalent.com"
    _verify_email(email)
    pwd = "Cust@1234"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd,
        "first_name": "Test", "last_name": "Customer",
        "phone": "+91" + str(int(time.time() * 1000))[-10:],
        "role": "customer",
    }, timeout=20)
    assert r.status_code == 200, r.text
    return {"token": r.json()["token"], "user": r.json()["user"], "email": email}


@pytest.fixture(scope="session")
def seeded_artist():
    t, u = _login(ARTIST_EMAIL, ARTIST_PWD)
    return {"token": t, "user": u}


@pytest.fixture(scope="session")
def admin_user():
    t, u = _login(ADMIN_EMAIL, ADMIN_PWD)
    return {"token": t, "user": u}


# ─────────────────────────── ONBOARDING ───────────────────────────
class TestOnboarding:
    def test_onboarding_required_for_fresh_artist(self, fresh_artist):
        r = requests.get(f"{API}/onboarding/me", headers=_h(fresh_artist["token"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["required"] is True
        assert data["completed"] is False
        # all 5 checks present
        for k in ("step1_basic", "step2_branding", "step3_media", "step4_packages", "step5_availability"):
            assert k in data["checks"], f"missing check {k}"
            assert data["checks"][k] is False, f"{k} should be False for fresh artist"
        assert data["next_step"] == 1

    def test_onboarding_not_required_for_customer(self, fresh_customer):
        r = requests.get(f"{API}/onboarding/me", headers=_h(fresh_customer["token"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["required"] is False
        assert data["completed"] is True

    def test_onboarding_complete_flips_completed(self, fresh_artist):
        r = requests.post(f"{API}/onboarding/complete", headers=_h(fresh_artist["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        r2 = requests.get(f"{API}/onboarding/me", headers=_h(fresh_artist["token"]), timeout=15)
        assert r2.status_code == 200
        assert r2.json()["completed"] is True

    def test_onboarding_complete_forbidden_for_customer(self, fresh_customer):
        r = requests.post(f"{API}/onboarding/complete", headers=_h(fresh_customer["token"]), timeout=15)
        assert r.status_code == 403


# ─────────────────────────── PROFILE FIELDS ───────────────────────────
class TestProfileFields:
    def test_new_profile_fields_persist(self, seeded_artist):
        payload = {
            "awards": ["TEST_Filmfare 2024", "TEST_Award B"],
            "certifications": ["TEST_Grade 8 Vocal"],
            "youtube_url": "https://youtube.com/@test_iter4",
            "instagram_url": "https://instagram.com/test_iter4",
            "spotify_url": "https://open.spotify.com/artist/TEST_iter4",
            "onboarding_step": 4,
            "faqs": [{"q": "TEST Q?", "a": "TEST A"}],
        }
        r = requests.put(f"{API}/users/me", json=payload, headers=_h(seeded_artist["token"]), timeout=15)
        assert r.status_code == 200, r.text

        # verify via /artists/{id} which returns key 'profile' (the artist_profile doc)
        r2 = requests.get(f"{API}/artists/{seeded_artist['user']['id']}", timeout=15)
        assert r2.status_code == 200
        prof = r2.json().get("profile") or r2.json().get("artist_profile") or {}
        assert "TEST_Filmfare 2024" in (prof.get("awards") or [])
        assert "TEST_Grade 8 Vocal" in (prof.get("certifications") or [])
        assert prof.get("youtube_url") == payload["youtube_url"]
        assert prof.get("instagram_url") == payload["instagram_url"]
        assert prof.get("spotify_url") == payload["spotify_url"]
        assert prof.get("onboarding_step") == 4
        assert isinstance(prof.get("faqs"), list) and len(prof["faqs"]) == 1

    def test_new_profile_fields_persist_on_fresh_artist(self, fresh_artist):
        """Verify the iter-4 follow-up fix: fields also persist for a freshly-registered artist."""
        payload = {
            "awards": ["TEST_Fresh Award"],
            "certifications": ["TEST_Fresh Cert"],
            "youtube_url": "https://youtube.com/@test_fresh",
            "instagram_url": "https://instagram.com/test_fresh",
            "spotify_url": "https://open.spotify.com/artist/TEST_fresh",
            "onboarding_step": 3,
        }
        r = requests.put(f"{API}/users/me", json=payload, headers=_h(fresh_artist["token"]), timeout=15)
        assert r.status_code == 200, r.text

        r2 = requests.get(f"{API}/artists/{fresh_artist['user']['id']}", timeout=15)
        assert r2.status_code == 200, r2.text
        prof = r2.json().get("profile") or r2.json().get("artist_profile") or {}
        assert "TEST_Fresh Award" in (prof.get("awards") or []), f"awards missing in fresh-artist profile: {prof}"
        assert "TEST_Fresh Cert" in (prof.get("certifications") or [])
        assert prof.get("youtube_url") == payload["youtube_url"]
        assert prof.get("instagram_url") == payload["instagram_url"]
        assert prof.get("spotify_url") == payload["spotify_url"]
        assert prof.get("onboarding_step") == 3


# ─────────────────────────── MEDIA TYPES + SIZE ───────────────────────────
class TestMediaUpload:
    @pytest.mark.parametrize("mtype", ["audio", "document", "press_kit", "brand_deck", "clip"])
    def test_new_media_types_accepted(self, seeded_artist, mtype):
        body = {"type": mtype, "data_url": TINY_PNG, "title": f"TEST_{mtype}"}
        r = requests.post(f"{API}/media/upload", json=body, headers=_h(seeded_artist["token"]), timeout=20)
        assert r.status_code == 200, f"{mtype} → {r.status_code} {r.text}"
        assert r.json().get("type") == mtype

    def test_5mb_file_succeeds(self, seeded_artist):
        # 5 MB binary → base64 ≈ 6.7 MB — should succeed under 12 MB cap
        blob = os.urandom(5 * 1024 * 1024)
        b64 = base64.b64encode(blob).decode()
        data_url = f"data:application/octet-stream;base64,{b64}"
        r = requests.post(f"{API}/media/upload",
                          json={"type": "document", "data_url": data_url, "title": "TEST_5mb"},
                          headers=_h(seeded_artist["token"]), timeout=60)
        assert r.status_code == 200, f"5 MB upload should succeed, got {r.status_code} {r.text[:200]}"
        assert r.json().get("size") >= 5 * 1024 * 1024

    def test_15mb_file_rejected_with_413(self, seeded_artist):
        # 15 MB binary exceeds the 12 MB MongoDB-BSON-safe cap → should 413 (NOT 500)
        blob = os.urandom(15 * 1024 * 1024)
        b64 = base64.b64encode(blob).decode()
        data_url = f"data:application/octet-stream;base64,{b64}"
        r = requests.post(f"{API}/media/upload",
                          json={"type": "document", "data_url": data_url, "title": "TEST_15mb"},
                          headers=_h(seeded_artist["token"]), timeout=120)
        assert r.status_code == 413, f"15 MB upload should return 413, got {r.status_code} {r.text[:200]}"
        detail = (r.json().get("detail") or "").lower()
        assert "too large" in detail and "12" in detail, f"error message should mention 12 MB cap, got: {detail}"


# ─────────────────────────── BOOKING + ALTERNATIVES + ACCEPT ───────────────────────────
@pytest.fixture(scope="session")
def priya_package(seeded_artist):
    r = requests.get(f"{API}/artists/{seeded_artist['user']['id']}", timeout=15)
    assert r.status_code == 200
    pkgs = r.json().get("packages") or []
    assert pkgs, "Priya should have a package"
    return pkgs[0]


@pytest.fixture(scope="session")
def confirmed_booking(fresh_customer, seeded_artist, priya_package):
    """Create & accept a booking on a unique TEST date → auto-blocks priya for that date."""
    event_date = f"2040-{(int(time.time()) % 12) + 1:02d}-{(int(time.time()) % 27) + 1:02d}"  # unique across runs
    body = {
        "artist_id": seeded_artist["user"]["id"],
        "package_id": priya_package.get("id") or priya_package.get("_id"),
        "addons": [],
        "event_date": event_date,
        "event_time": "20:00",
        "event_type": "Wedding",
        "venue": "TEST_Iter4 Venue",
        "city": "Mumbai",
        "guests": "150",
        "customer_name": "TEST Iter4 Customer",
        "customer_email": fresh_customer["user"]["email"],
        "customer_phone": fresh_customer["user"].get("phone"),
    }
    r = requests.post(f"{API}/bookings", json=body, headers=_h(fresh_customer["token"]), timeout=20)
    assert r.status_code == 200, r.text
    bk = r.json()
    bid = bk["id"]

    # accept directly as the artist (they can accept from pending_payment per server.py logic)
    r2 = requests.post(f"{API}/bookings/{bid}/action",
                       json={"action": "accept"},
                       headers=_h(seeded_artist["token"]), timeout=15)
    assert r2.status_code == 200, r2.text
    return {"booking_id": bid, "ref": bk.get("ref"), "event_date": event_date}


class TestAcceptSideEffects:
    def test_status_confirmed(self, confirmed_booking, fresh_customer):
        r = requests.get(f"{API}/bookings/{confirmed_booking['booking_id']}",
                         headers=_h(fresh_customer["token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["booking"]["status"] == "confirmed"

    def test_contract_created(self, confirmed_booking, seeded_artist):
        r = requests.get(f"{API}/contracts/mine", headers=_h(seeded_artist["token"]), timeout=15)
        assert r.status_code == 200
        assert any(c.get("booking_id") == confirmed_booking["booking_id"] for c in r.json()), \
            "auto-contract not found"

    def test_event_date_auto_blocked(self, confirmed_booking, seeded_artist):
        r = requests.get(f"{API}/availability/mine", headers=_h(seeded_artist["token"]), timeout=15)
        assert r.status_code == 200
        slots = r.json()
        match = [s for s in slots if s.get("date") == confirmed_booking["event_date"]]
        assert match, f"availability slot not auto-created for {confirmed_booking['event_date']}"
        assert match[0]["status"] == "booked"


class TestBookingAlternatives:
    def test_unavailable_date_returns_400_and_alternatives(self, fresh_customer, seeded_artist, priya_package, confirmed_booking):
        # confirmed_booking already blocked 2030-06-15 → request the same slot again
        body = {
            "artist_id": seeded_artist["user"]["id"],
            "package_id": priya_package.get("id") or priya_package.get("_id"),
            "addons": [],
            "event_date": confirmed_booking["event_date"],
            "event_time": "20:00",
            "event_type": "Wedding",
            "venue": "TEST_dup",
            "city": "Mumbai",
            "guests": "50",
            "customer_email": fresh_customer["user"]["email"],
        }
        r = requests.post(f"{API}/bookings", json=body, headers=_h(fresh_customer["token"]), timeout=20)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail")
        assert isinstance(detail, dict), f"detail must be a dict with alternatives, got {detail}"
        assert "message" in detail
        assert "alternatives" in detail
        assert "date" in detail
        assert detail["date"] == confirmed_booking["event_date"]
        assert isinstance(detail["alternatives"], list)
        # if alternatives exist, schema check
        for alt in detail["alternatives"]:
            for k in ("user_id", "stage_name", "category", "city", "rating_avg", "emoji"):
                assert k in alt, f"alt missing {k}: {alt}"


# ─────────────────────────── COUNTER FLOW (REMOVED) ───────────────────────────
# Counter-offer feature was removed in iter43 — BookTalent enforces fixed
# pricing (lead-gen model). The fixture + TestCounterFlow class that used to
# live here have been deleted. See test_iter43_counter_removed.py for the
# replacement regression tests that assert the feature is gone.


# ─────────────────────────── SIGNED CONTRACT UPLOAD ───────────────────────────
class TestSignedContractUpload:
    def test_upload_signed_by_both_flips_status(self, confirmed_booking, seeded_artist, fresh_customer):
        # Find the contract for confirmed booking
        rc = requests.get(f"{API}/contracts/mine", headers=_h(seeded_artist["token"]), timeout=15)
        contracts = [c for c in rc.json() if c.get("booking_id") == confirmed_booking["booking_id"]]
        assert contracts, "contract missing"
        cid = contracts[0]["id"]

        # artist uploads signed
        ra = requests.post(f"{API}/contracts/upload-signed",
                           json={"contract_id": cid, "data_url": TINY_PDF_DATA_URL, "signed_by": "artist"},
                           headers=_h(seeded_artist["token"]), timeout=20)
        assert ra.status_code == 200, ra.text
        assert ra.json().get("media_id")

        # confirm contract has signed_artist_media_id but not yet fully_signed
        rc2 = requests.get(f"{API}/contracts/{cid}", headers=_h(seeded_artist["token"]), timeout=15)
        assert rc2.status_code == 200
        c1 = rc2.json()
        assert c1.get("signed_artist_media_id")
        assert c1.get("status") != "fully_signed"

        # customer uploads signed
        rb = requests.post(f"{API}/contracts/upload-signed",
                           json={"contract_id": cid, "data_url": TINY_PDF_DATA_URL, "signed_by": "customer"},
                           headers=_h(fresh_customer["token"]), timeout=20)
        assert rb.status_code == 200, rb.text

        rc3 = requests.get(f"{API}/contracts/{cid}", headers=_h(seeded_artist["token"]), timeout=15)
        c2 = rc3.json()
        assert c2.get("signed_customer_media_id")
        assert c2.get("status") == "fully_signed", f"status should be fully_signed, got {c2.get('status')}"
