"""
Iter 55 backend regression tests.

Covers:
  * Super-admin RBAC schema endpoints  (GET /admin/rbac/roles, /admin/rbac/me)
  * Admin CRUD                          (POST/GET/PATCH/DELETE /admin/admins)
  * RBAC enforcement on sensitive routes (analytics.view / admins.manage /
    users.suspend)
  * Safety guards (cannot demote/deactivate/delete self as last super admin)
  * Public artist "About" endpoint     (GET /artists/{id}/about)
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from /app/frontend/.env directly (dev containers only)
    with open("/app/frontend/.env") as fp:
        for line in fp:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"

SUPER_ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
PRIYA_ID = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"


# ────────────────────────── helpers ──────────────────────────
def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login({email}) failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login(**SUPER_ADMIN)


@pytest.fixture(scope="module")
def ephemeral_admin_email():
    return f"iter55_finance_{int(time.time())}_{uuid.uuid4().hex[:6]}@test.com"


@pytest.fixture(scope="module")
def created_admin(admin_session, ephemeral_admin_email):
    """Create a finance admin once, share across the module, delete at teardown."""
    body = {
        "email": ephemeral_admin_email,
        "password": "Finance@123",
        "first_name": "Fin",
        "last_name": "Admin",
        "admin_role": "finance",
    }
    r = admin_session.post(f"{API}/admin/admins", json=body, timeout=15)
    assert r.status_code == 200, f"create finance admin failed: {r.status_code} {r.text}"
    data = r.json()
    yield data
    # Teardown — soft delete
    try:
        admin_session.delete(f"{API}/admin/admins/{data['id']}", timeout=10)
    except Exception:
        pass


# ══════════════ 1. RBAC schema ══════════════
class TestRBACSchema:
    def test_get_rbac_roles(self, admin_session):
        r = admin_session.get(f"{API}/admin/rbac/roles", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "permissions" in data and "role_presets" in data
        assert isinstance(data["permissions"], list)
        assert len(data["permissions"]) == 15, f"expected 15 permissions, got {len(data['permissions'])}"
        # Six preset keys (super_admin/operations/finance/content/support/viewer)
        for key in ["super_admin", "operations", "finance", "content", "support", "viewer"]:
            assert key in data["role_presets"], f"missing preset: {key}"

    def test_get_rbac_me_super_admin(self, admin_session):
        r = admin_session.get(f"{API}/admin/rbac/me", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["admin_role"] == "super_admin"
        assert isinstance(data["admin_permissions"], list)
        assert len(data["admin_permissions"]) == 15


# ══════════════ 2. Admin CRUD ══════════════
class TestAdminCRUD:
    def test_create_finance_admin(self, created_admin):
        assert created_admin["admin_role"] == "finance"
        assert created_admin["active"] is True
        # Finance preset has 6 perms per server.py:268-269
        assert len(created_admin["admin_permissions"]) == 6
        expected = {"users.view", "bookings.view", "payments.view", "payments.refund",
                    "subscriptions.manage", "analytics.view"}
        assert set(created_admin["admin_permissions"]) == expected

    def test_list_admins_contains_both(self, admin_session, created_admin):
        r = admin_session.get(f"{API}/admin/admins", timeout=10)
        assert r.status_code == 200
        rows = r.json()
        ids = {row["id"] for row in rows}
        emails = {row["email"] for row in rows}
        assert SUPER_ADMIN["email"] in emails
        assert created_admin["id"] in ids

    def test_duplicate_email_400(self, admin_session, created_admin, ephemeral_admin_email):
        r = admin_session.post(f"{API}/admin/admins", json={
            "email": ephemeral_admin_email, "password": "Dup@123", "admin_role": "viewer"
        }, timeout=10)
        assert r.status_code == 400, r.text

    def test_patch_downgrade_to_viewer(self, admin_session, created_admin):
        r = admin_session.patch(f"{API}/admin/admins/{created_admin['id']}",
                                json={"admin_role": "viewer"}, timeout=10)
        assert r.status_code == 200
        # Verify by re-listing
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        row = next(x for x in rows if x["id"] == created_admin["id"])
        assert row["admin_role"] == "viewer"
        # Viewer preset per server.py:272 = 4 perms
        assert len(row["admin_permissions"]) == 4
        assert set(row["admin_permissions"]) == {
            "users.view", "bookings.view", "payments.view", "analytics.view",
        }

    def test_delete_last_super_admin_blocked(self, admin_session):
        """Deleting admin@booktalent.com (last super_admin) must return 400."""
        # Look up its id
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        super_row = next(x for x in rows if x["email"] == SUPER_ADMIN["email"])
        r = admin_session.delete(f"{API}/admin/admins/{super_row['id']}", timeout=10)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"

    def test_soft_delete_finance_admin(self, admin_session, created_admin):
        # Create a throwaway to actually delete (created_admin lifetime is module).
        email = f"iter55_del_{int(time.time())}_{uuid.uuid4().hex[:5]}@test.com"
        c = admin_session.post(f"{API}/admin/admins", json={
            "email": email, "password": "Del@123", "admin_role": "viewer"}, timeout=10)
        assert c.status_code == 200
        target_id = c.json()["id"]
        d = admin_session.delete(f"{API}/admin/admins/{target_id}", timeout=10)
        assert d.status_code == 200
        # Verify it no longer appears in the list
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        assert target_id not in {row["id"] for row in rows}


# ══════════════ 3. Safety guards ══════════════
class TestSelfServiceGuards:
    def test_super_cannot_deactivate_self(self, admin_session):
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        me = next(x for x in rows if x["email"] == SUPER_ADMIN["email"])
        r = admin_session.patch(f"{API}/admin/admins/{me['id']}",
                                json={"active": False}, timeout=10)
        assert r.status_code == 400, r.text

    def test_super_cannot_demote_self(self, admin_session):
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        me = next(x for x in rows if x["email"] == SUPER_ADMIN["email"])
        r = admin_session.patch(f"{API}/admin/admins/{me['id']}",
                                json={"admin_role": "viewer"}, timeout=10)
        assert r.status_code == 400, r.text

    def test_super_cannot_delete_self(self, admin_session):
        rows = admin_session.get(f"{API}/admin/admins", timeout=10).json()
        me = next(x for x in rows if x["email"] == SUPER_ADMIN["email"])
        r = admin_session.delete(f"{API}/admin/admins/{me['id']}", timeout=10)
        # Route returns 400 either from self-check or last-super-admin check.
        assert r.status_code == 400, r.text


# ══════════════ 4. RBAC enforcement (finance admin) ══════════════
class TestRBACEnforcement:
    @pytest.fixture(scope="class")
    def finance_session(self, created_admin, ephemeral_admin_email):
        # Reset finance role first (previous test downgraded to viewer)
        s_admin = _login(**SUPER_ADMIN)
        r = s_admin.patch(f"{API}/admin/admins/{created_admin['id']}",
                          json={"admin_role": "finance"}, timeout=10)
        assert r.status_code == 200
        return _login(ephemeral_admin_email, "Finance@123")

    def test_finance_can_hit_analytics_view(self, finance_session):
        """/admin/stats is gated by analytics.view — finance HAS it."""
        r = finance_session.get(f"{API}/admin/stats", timeout=15)
        assert r.status_code == 200, r.text

    def test_finance_blocked_from_admins_list(self, finance_session):
        """Finance lacks admins.manage."""
        r = finance_session.get(f"{API}/admin/admins", timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_finance_blocked_from_suspend(self, finance_session):
        """Finance lacks users.suspend."""
        r = finance_session.post(f"{API}/admin/artists/{PRIYA_ID}/suspend", timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_finance_rbac_me(self, finance_session):
        r = finance_session.get(f"{API}/admin/rbac/me", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["admin_role"] == "finance"
        assert "payments.view" in data["admin_permissions"]
        assert "admins.manage" not in data["admin_permissions"]


# ══════════════ 5. Public /artists/{id}/about ══════════════
class TestArtistAbout:
    def test_public_access_no_auth(self):
        """Endpoint must be publicly accessible (no cookie)."""
        r = requests.get(f"{API}/artists/{PRIYA_ID}/about", timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        data = r.json()
        for key in ("universal", "category", "category_slug", "raw_answers_count"):
            assert key in data, f"missing key: {key}"
        assert isinstance(data["universal"], list)
        assert isinstance(data["category"], list)

    def test_answer_object_shape(self):
        r = requests.get(f"{API}/artists/{PRIYA_ID}/about", timeout=15)
        data = r.json()
        # Priya has answers per prior iterations; at least universal should be
        # non-empty. If it is empty we still verify the structural contract.
        pool = data["universal"] + data["category"]
        if pool:
            first = pool[0]
            for k in ("id", "question", "type", "answer", "section", "options"):
                assert k in first, f"missing field {k} in answer object"

    def test_unknown_artist_returns_empty_scaffold(self):
        # Unknown id → prof is empty dict, so returns empty arrays with 200 (per code).
        r = requests.get(f"{API}/artists/{uuid.uuid4().hex}/about", timeout=15)
        # Route currently returns 200 with empty arrays for unknown ids (not
        # 404 unless suspended). Either is acceptable.
        assert r.status_code in (200, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
