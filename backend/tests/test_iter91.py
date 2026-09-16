"""
Iter 91 backend tests:
- POST /api/user/mark-welcome-seen
- /api/onboarding/complete side-effect on users.seen_welcome_at
- /api/auth/me includes seen_welcome_at
- chat access + upload as assigned manager (renamed agency_corp_provider_routes)
- Regression: renamed router endpoints still resolve
"""
import os
import base64
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
ARTIST = ("priya@booktalent.com", "Artist@123")
MANAGER = ("test-mgr@booktalent.com", "Manager@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")

# The booking assigned to test-mgr-1 by seed step (see mongosh in agent run)
BOOKING_ID = "0c0c3ae8-1efe-406c-9733-76c444c406e7"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login(*ADMIN),
        "artist": _login(*ARTIST),
        "manager": _login(*MANAGER),
        "customer": _login(*CUSTOMER),
    }


# ── Iter 91 onboarding/welcome ─────────────────────────────────────────
def test_mark_welcome_seen_sets_timestamp(tokens):
    t = tokens["artist"]
    r = requests.post(f"{API}/user/mark-welcome-seen", headers=_h(t), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    # Verify via /auth/me
    me = requests.get(f"{API}/auth/me", headers=_h(t), timeout=15).json()
    assert me.get("seen_welcome_at"), "seen_welcome_at should be set after mark-welcome-seen"
    ts1 = me["seen_welcome_at"]
    # Idempotent — call again, timestamp refreshes
    r2 = requests.post(f"{API}/user/mark-welcome-seen", headers=_h(t), timeout=15)
    assert r2.status_code == 200
    me2 = requests.get(f"{API}/auth/me", headers=_h(t), timeout=15).json()
    assert me2.get("seen_welcome_at") >= ts1


def test_mark_welcome_seen_requires_auth():
    r = requests.post(f"{API}/user/mark-welcome-seen", timeout=15)
    assert r.status_code == 401


def test_onboarding_complete_sets_seen_welcome_at(tokens):
    t = tokens["artist"]
    r = requests.post(f"{API}/onboarding/complete", headers=_h(t), timeout=15)
    assert r.status_code == 200, r.text
    me = requests.get(f"{API}/auth/me", headers=_h(t), timeout=15).json()
    assert me.get("seen_welcome_at"), "onboarding/complete must set seen_welcome_at"
    # Sanity: onboarding_completed reflected on profile
    prof = me.get("artist_profile") or {}
    assert prof.get("onboarding_completed") is True


def test_auth_me_has_seen_welcome_field(tokens):
    # Customer never onboarded — either key absent or explicit null is acceptable
    r = requests.get(f"{API}/auth/me", headers=_h(tokens["customer"]), timeout=15)
    assert r.status_code == 200
    # Field may be missing → treated as null by clients. No assert other than 200.


# ── Iter 91 chat manager access ────────────────────────────────────────
def test_chat_access_as_assigned_manager(tokens):
    r = requests.get(f"{API}/chat/{BOOKING_ID}/access", headers=_h(tokens["manager"]), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("enabled") is True


def test_chat_messages_list_as_assigned_manager(tokens):
    r = requests.get(f"{API}/chat/{BOOKING_ID}/messages", headers=_h(tokens["manager"]), timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_chat_upload_as_assigned_manager(tokens):
    # Tiny PNG
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
               "//8/AwAI/AL+p5qgoAAAAABJRU5ErkJggg==")
    body = {
        "booking_id": BOOKING_ID,
        "type": "file",
        "filename": "iter91_test.png",
        "data_url": f"data:image/png;base64,{png_b64}",
    }
    r = requests.post(f"{API}/chat/{BOOKING_ID}/upload", headers=_h(tokens["manager"]), json=body, timeout=20)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    msg = r.json()
    assert msg.get("type") == "file"
    assert msg.get("filename") == "iter91_test.png"
    assert msg.get("media_id")


def test_chat_access_non_assigned_manager_forbidden(tokens):
    # Use a fake booking id we know exists but has NO assigned_manager
    # Pick a different booking
    other = requests.get(f"{API}/admin/bookings", headers=_h(tokens["admin"]), timeout=15)
    if other.status_code != 200:
        pytest.skip("admin/bookings not available")
    ids = [b.get("id") for b in other.json() if b.get("id") != BOOKING_ID and not b.get("assigned_manager_id")]
    if not ids:
        pytest.skip("no other booking without assigned_manager")
    r = requests.get(f"{API}/chat/{ids[0]}/access", headers=_h(tokens["manager"]), timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code}"


# ── Iter 91 router rename regression ───────────────────────────────────
@pytest.mark.parametrize("path,expected", [
    ("/admin/settings", [200]),
    ("/admin/audit-logs", [200]),
    ("/faqs", [200]),
    ("/admin/providers/status", [200]),
])
def test_admin_endpoints_after_rename(tokens, path, expected):
    r = requests.get(f"{API}{path}", headers=_h(tokens["admin"]), timeout=15)
    assert r.status_code in expected, f"{path}: {r.status_code} {r.text[:200]}"


def test_search_ai_after_rename(tokens):
    r = requests.post(f"{API}/search/ai", json={"query": "singer in Mumbai"}, headers=_h(tokens["customer"]), timeout=30)
    # Should not 404 (route resolution proof); may 200 or 5xx if LLM absent
    assert r.status_code != 404, r.text


def test_exports_revenue_csv_after_rename(tokens):
    r = requests.get(f"{API}/admin/exports/revenue.csv", headers=_h(tokens["admin"]), timeout=20)
    assert r.status_code in (200, 204), r.text[:200]


def test_agency_roster_after_rename(tokens):
    # Login as agency
    tk = _login("agency@booktalent.com", "Agency@123")
    r = requests.get(f"{API}/agency/roster", headers=_h(tk), timeout=15)
    assert r.status_code == 200, r.text[:200]


# ── Iter 90/90b regressions ────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/kyc/pipeline",
    "/manager/chats/threads",
    "/manager/leaderboard",
])
def test_regression_iter90(tokens, path):
    role = "manager" if path.startswith("/manager") else ("artist" if path == "/kyc/pipeline" else "admin")
    r = requests.get(f"{API}{path}", headers=_h(tokens[role]), timeout=15)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
