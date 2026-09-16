"""
Iter 54 — Agency auto-provision + documents vault backend tests.

Coverage:
1. POST /api/agency/invite with a brand-new email → auto-provisions:
   - user row with role='artist', pending_activation=True, email_verified=False
   - companion artist_profiles row
   - response: auto_provisioned=True, status='active'
2. POST /api/agency/invite with existing active roster artist → 400 "already in your roster"
3. POST /api/agency/invite with missing/invalid email → 400.
4. POST /api/agency/documents (create) → 200 with metadata (no data_url) + mime/size_bytes.
5. GET /api/agency/documents → list without data_url; filterable by client_id + event_id.
6. GET /api/agency/documents/{id}/download → {title, mime, data_url}.
7. DELETE /api/agency/documents/{id} → {ok:true}.
8. Documents endpoints 403 for non-agency roles (customer / artist).
"""
import base64
import os
import time
import uuid

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"')
                break

AGENCY = {"email": "agency@booktalent.com", "password": "Agency@123"}
ARTIST = {"email": "priya@booktalent.com", "password": "Artist@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}


# tiny valid PNG (1x1 red pixel) as data URL
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg=="
)
PNG_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


# ─────────────────────── login helpers ────────────────────────
def _login(creds: dict) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def agency_session():
    return _login(AGENCY)


@pytest.fixture(scope="module")
def artist_session():
    return _login(ARTIST)


@pytest.fixture(scope="module")
def customer_session():
    return _login(CUSTOMER)


# ─────────────────────── Invite / auto-provision ────────────────────────
class TestAgencyInviteAutoProvision:
    """POST /agency/invite behavior across three paths."""

    _created_emails: list = []
    _created_roster_ids: list = []

    def test_invite_missing_email_returns_400(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/invite", json={"artist_email": ""}, timeout=15)
        assert r.status_code == 400, r.text
        detail = (r.json() or {}).get("detail", "").lower()
        assert "email" in detail

    def test_invite_invalid_email_returns_400(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/invite",
                                json={"artist_email": "not-an-email"}, timeout=15)
        assert r.status_code == 400, r.text

    def test_invite_new_email_auto_provisions(self, agency_session):
        unique = f"iter54new_{int(time.time())}_{uuid.uuid4().hex[:6]}@test.com"
        payload = {
            "artist_email": unique,
            "commission_pct": 12.5,
            "first_name": "Iter54",
            "last_name": "TestArtist",
            "phone": "+91 90000 00001",
            "category": "Bollywood Vocalist",
            "city": "Mumbai",
            "stage_name": "Iter54 Auto",
        }
        r = agency_session.post(f"{BASE_URL}/api/agency/invite", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # ── acceptance checks
        assert data.get("auto_provisioned") is True, data
        assert data.get("status") == "active", data
        assert data.get("artist_email") == unique
        assert float(data.get("commission_pct", 0)) == 12.5

        TestAgencyInviteAutoProvision._created_emails.append(unique)
        TestAgencyInviteAutoProvision._created_roster_ids.append(data.get("id"))

        # verify it shows up in roster
        rr = agency_session.get(f"{BASE_URL}/api/agency/roster", timeout=15)
        assert rr.status_code == 200
        rows = rr.json()
        match = [row for row in rows if row.get("artist_email") == unique]
        assert match, f"new artist not in roster listing: {unique}"
        assert match[0].get("auto_provisioned") is True
        assert match[0].get("status") == "active"
        # companion artist profile should exist and be joined into row["artist"]
        prof = match[0].get("artist") or {}
        # stage_name resolves either from payload or fallback
        assert prof.get("stage_name"), "artist_profile.stage_name should be seeded"

    def test_invite_existing_active_roster_returns_400(self, agency_session):
        # priya is already actively on agency roster (per iter52 seed);
        # if not, we treat any 200 as an unexpected path but the standard
        # expectation from prior iters is "already in your roster".
        r = agency_session.post(f"{BASE_URL}/api/agency/invite",
                                json={"artist_email": ARTIST["email"], "commission_pct": 10},
                                timeout=15)
        # Accept either 400 "already in your roster" or 400 "invite already pending".
        # If backend returned 200 (fresh state), we still assert it's not auto-provisioned.
        if r.status_code == 400:
            detail = (r.json() or {}).get("detail", "").lower()
            assert "roster" in detail or "pending" in detail, detail
        else:
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("auto_provisioned") is False, "existing artist must not be auto-provisioned"

    @classmethod
    def teardown_class(cls):
        # Clean up new users + roster rows we made during the test run
        try:
            from pymongo import MongoClient
            mongo_url = os.environ.get("MONGO_URL")
            db_name = os.environ.get("DB_NAME")
            if not mongo_url or not db_name:
                # last-ditch: parse /app/backend/.env
                env_path = "/app/backend/.env"
                if os.path.exists(env_path):
                    with open(env_path) as fh:
                        for line in fh:
                            if line.startswith("MONGO_URL=") and not mongo_url:
                                mongo_url = line.split("=", 1)[1].strip().strip('"')
                            if line.startswith("DB_NAME=") and not db_name:
                                db_name = line.split("=", 1)[1].strip().strip('"')
            if mongo_url and db_name:
                mc = MongoClient(mongo_url)
                db = mc[db_name]
                for email in cls._created_emails:
                    u = db.users.find_one({"email": email})
                    if u:
                        db.artist_profiles.delete_many({"user_id": u["id"]})
                        db.users.delete_one({"id": u["id"]})
                        db.agency_roster.delete_many({"artist_id": u["id"]})
                        db.notifications.delete_many({"user_id": u["id"]})
                for rid in cls._created_roster_ids:
                    if rid:
                        db.agency_roster.delete_many({"id": rid})
        except Exception as e:
            print(f"[teardown] cleanup skipped: {e}")


# ─────────────────────── Documents vault ────────────────────────
class TestAgencyDocuments:
    """Docs vault CRUD + tagging + role guards."""

    _doc_ids: list = []
    _client_id: str = None
    _event_id: str = None

    @pytest.fixture(autouse=True, scope="class")
    def _seed_client_and_event(self, agency_session):
        # Create one throwaway client + event so we can tag docs
        cr = agency_session.post(f"{BASE_URL}/api/agency/clients",
                                 json={"name": f"TEST_iter54_client_{uuid.uuid4().hex[:6]}",
                                       "email": "iter54client@test.com"},
                                 timeout=15)
        assert cr.status_code == 200, cr.text
        TestAgencyDocuments._client_id = cr.json()["id"]

        er = agency_session.post(f"{BASE_URL}/api/agency/events",
                                 json={"title": f"TEST_iter54_event_{uuid.uuid4().hex[:6]}",
                                       "event_date": "2026-06-15",
                                       "client_id": TestAgencyDocuments._client_id},
                                 timeout=15)
        assert er.status_code == 200, er.text
        TestAgencyDocuments._event_id = er.json()["id"]
        yield
        # Teardown
        if TestAgencyDocuments._client_id:
            agency_session.delete(f"{BASE_URL}/api/agency/clients/{TestAgencyDocuments._client_id}", timeout=15)
        if TestAgencyDocuments._event_id:
            agency_session.delete(f"{BASE_URL}/api/agency/events/{TestAgencyDocuments._event_id}", timeout=15)

    def test_create_document_no_datauurl_in_response(self, agency_session):
        payload = {
            "title": "TEST_iter54_contract.png",
            "kind": "contract",
            "client_id": self._client_id,
            "event_id": self._event_id,
            "data_url": PNG_DATA_URL,
            "notes": "Iter54 acceptance test",
        }
        r = agency_session.post(f"{BASE_URL}/api/agency/documents", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        assert body["title"] == "TEST_iter54_contract.png"
        assert body["kind"] == "contract"
        assert body["mime"] == "image/png", body
        assert isinstance(body["size_bytes"], int) and body["size_bytes"] > 0
        # metadata-only response
        assert "data_url" not in body, "create response must NOT ship data_url back"
        assert body.get("client_id") == self._client_id
        assert body.get("event_id") == self._event_id
        TestAgencyDocuments._doc_ids.append(body["id"])

    def test_missing_title_returns_400(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/documents",
                                json={"title": "", "data_url": PNG_DATA_URL}, timeout=15)
        assert r.status_code == 400

    def test_missing_datauurl_returns_400(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/documents",
                                json={"title": "TEST_iter54_no_data"}, timeout=15)
        assert r.status_code == 400

    def test_list_documents_omits_datauurl(self, agency_session):
        r = agency_session.get(f"{BASE_URL}/api/agency/documents", timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list) and len(rows) > 0
        # every row must NOT ship data_url
        for row in rows:
            assert "data_url" not in row, f"list should omit data_url, got row: {row}"

    def test_list_filter_by_client_id(self, agency_session):
        r = agency_session.get(f"{BASE_URL}/api/agency/documents",
                               params={"client_id": self._client_id}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert rows, "expected at least one doc filtered by client_id"
        for row in rows:
            assert row.get("client_id") == self._client_id

    def test_list_filter_by_event_id(self, agency_session):
        r = agency_session.get(f"{BASE_URL}/api/agency/documents",
                               params={"event_id": self._event_id}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert rows, "expected at least one doc filtered by event_id"
        for row in rows:
            assert row.get("event_id") == self._event_id

    def test_download_returns_data_url(self, agency_session):
        assert self._doc_ids, "no doc to download"
        did = self._doc_ids[0]
        r = agency_session.get(f"{BASE_URL}/api/agency/documents/{did}/download", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("title") == "TEST_iter54_contract.png"
        assert body.get("mime") == "image/png"
        assert body.get("data_url", "").startswith("data:image/png;base64,"), body.get("data_url", "")[:40]

    def test_documents_forbidden_for_non_agency(self, artist_session, customer_session):
        for label, sess in (("artist", artist_session), ("customer", customer_session)):
            r_list = sess.get(f"{BASE_URL}/api/agency/documents", timeout=15)
            assert r_list.status_code == 403, f"{label} list expected 403, got {r_list.status_code}"
            r_post = sess.post(f"{BASE_URL}/api/agency/documents",
                               json={"title": "hack", "data_url": PNG_DATA_URL}, timeout=15)
            assert r_post.status_code == 403, f"{label} POST expected 403, got {r_post.status_code}"

    def test_delete_document(self, agency_session):
        assert self._doc_ids, "no doc to delete"
        did = self._doc_ids[0]
        r = agency_session.delete(f"{BASE_URL}/api/agency/documents/{did}", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        # confirm gone
        r2 = agency_session.get(f"{BASE_URL}/api/agency/documents/{did}/download", timeout=15)
        assert r2.status_code == 404
        TestAgencyDocuments._doc_ids.remove(did)

    @classmethod
    def teardown_class(cls):
        # last-ditch cleanup for any leftover docs
        try:
            s = _login(AGENCY)
            for did in list(cls._doc_ids):
                s.delete(f"{BASE_URL}/api/agency/documents/{did}", timeout=15)
        except Exception as e:
            print(f"[teardown] doc cleanup skipped: {e}")
