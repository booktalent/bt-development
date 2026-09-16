"""
Iter 57 — Backend regression: iter 56 endpoints must still work.
Also verifies RBAC permissions returned by /admin/rbac/me for role presets
so the frontend guardrails filter correctly.

No new backend changes in iter 57 (frontend UX polish only), so this file is
a lightweight regression + role preset shape sanity check.
"""
import os
import re
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def super_admin():
    return _login("admin@booktalent.com", "Admin@123")


@pytest.fixture(scope="module")
def priya():
    return _login("priya@booktalent.com", "Artist@123")


# ─── Iter 56 regression endpoints ─────────────────────────────────────────
class TestIter56Regression:
    def test_rbac_me_super_admin(self, super_admin):
        r = super_admin.get(f"{API}/admin/rbac/me")
        assert r.status_code == 200
        data = r.json()
        assert data.get("admin_role") == "super_admin"
        perms = set(data.get("admin_permissions") or [])
        # super_admin must include admins.manage
        assert "admins.manage" in perms
        assert "artists.moderate" in perms

    def test_roles_list(self, super_admin):
        r = super_admin.get(f"{API}/admin/roles")
        assert r.status_code == 200
        roles = r.json()
        assert isinstance(roles, list)
        role_ids = {x["id"] for x in roles}
        assert {"super_admin", "finance", "support", "content"}.issubset(role_ids)
        # super_admin readonly
        sa = next(x for x in roles if x["id"] == "super_admin")
        assert sa.get("readonly") is True

    def test_audit_log_list(self, super_admin):
        r = super_admin.get(f"{API}/admin/audit-log?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_questionnaire_completion_priya(self, priya):
        r = priya.get(f"{API}/questionnaire/completion/mine")
        assert r.status_code == 200
        data = r.json()
        for k in ("sections_total", "sections_answered", "sections_missing",
                  "questions_total", "questions_answered"):
            assert k in data, f"missing key {k}"
        assert isinstance(data["sections_missing"], list)

    def test_completion_forbidden_for_admin(self, super_admin):
        r = super_admin.get(f"{API}/questionnaire/completion/mine")
        assert r.status_code == 403

    def test_artist_about_priya_has_media_matches_and_completion(self, super_admin, priya):
        # find priya user id
        me = priya.get(f"{API}/auth/me").json()
        priya_id = me["id"]
        r = super_admin.get(f"{API}/artists/{priya_id}/about")
        assert r.status_code == 200
        data = r.json()
        assert "media_matches" in data
        assert "completion" in data
        assert isinstance(data["media_matches"], list)


# ─── Iter 57 — Role preset perms shape for frontend guardrails ───────────
EXPECTED_PERMS = {
    "finance":  {"users.view", "bookings.view", "payments.view", "payments.refund",
                 "subscriptions.manage", "analytics.view"},
    "support":  {"users.view", "bookings.view", "artists.moderate", "notifications.send"},
    "content":  {"users.view", "cms.manage", "notifications.send", "analytics.view"},
}


class TestRolePresetShapes:
    def test_finance_preset(self, super_admin):
        roles = super_admin.get(f"{API}/admin/roles").json()
        finance = next(x for x in roles if x["id"] == "finance")
        assert set(finance["permissions"]) == EXPECTED_PERMS["finance"]

    def test_support_preset(self, super_admin):
        roles = super_admin.get(f"{API}/admin/roles").json()
        support = next(x for x in roles if x["id"] == "support")
        assert set(support["permissions"]) == EXPECTED_PERMS["support"]

    def test_content_preset(self, super_admin):
        roles = super_admin.get(f"{API}/admin/roles").json()
        content = next(x for x in roles if x["id"] == "content")
        assert set(content["permissions"]) == EXPECTED_PERMS["content"]


# ─── Iter 57 — Create iter57 admins for frontend sidebar tests ───────────
# These test admins get created here so the frontend tests can reuse them.
# We do NOT delete them at the end so the frontend playwright pass can log
# in. The final cleanup happens in the last test class.
ITER57_ADMINS = [
    {"email": "iter57_finance@booktalent.com", "password": "Finance@123", "role": "finance"},
    {"email": "iter57_support@booktalent.com", "password": "Support@123", "role": "support"},
    {"email": "iter57_content@booktalent.com", "password": "Content@123", "role": "content"},
]


class TestCreateIter57Admins:
    def test_create_all(self, super_admin):
        # Clean slate first — remove any leftover iter57 admins
        existing = super_admin.get(f"{API}/admin/admins").json()
        for a in existing:
            if a["email"].startswith("iter57_"):
                super_admin.delete(f"{API}/admin/admins/{a['id']}?hard=true")

        for spec in ITER57_ADMINS:
            r = super_admin.post(f"{API}/admin/admins", json={
                "email": spec["email"],
                "password": spec["password"],
                "first_name": spec["role"].title(),
                "last_name": "Admin",
                "admin_role": spec["role"],
            })
            assert r.status_code in (200, 201), f"create {spec['email']} failed: {r.status_code} {r.text}"
            data = r.json()
            assert data["admin_role"] == spec["role"]

    def test_finance_admin_rbac_me(self):
        s = _login("iter57_finance@booktalent.com", "Finance@123")
        r = s.get(f"{API}/admin/rbac/me")
        assert r.status_code == 200
        data = r.json()
        assert data["admin_role"] == "finance"
        assert set(data["admin_permissions"]) == EXPECTED_PERMS["finance"]

    def test_support_admin_rbac_me(self):
        s = _login("iter57_support@booktalent.com", "Support@123")
        r = s.get(f"{API}/admin/rbac/me")
        assert r.status_code == 200
        data = r.json()
        assert data["admin_role"] == "support"
        assert set(data["admin_permissions"]) == EXPECTED_PERMS["support"]

    def test_content_admin_rbac_me(self):
        s = _login("iter57_content@booktalent.com", "Content@123")
        r = s.get(f"{API}/admin/rbac/me")
        assert r.status_code == 200
        data = r.json()
        assert data["admin_role"] == "content"
        assert set(data["admin_permissions"]) == EXPECTED_PERMS["content"]

    def test_finance_admin_cannot_view_audit_log(self):
        """Bug reveal: audit sidebar has no `perm` on the frontend, but the
        backend requires admins.manage — finance admin will 403 if they click
        the audit tab. Verifies backend still gates correctly."""
        s = _login("iter57_finance@booktalent.com", "Finance@123")
        r = s.get(f"{API}/admin/audit-log")
        assert r.status_code == 403

    def test_finance_admin_can_view_bookings(self):
        s = _login("iter57_finance@booktalent.com", "Finance@123")
        r = s.get(f"{API}/admin/bookings")
        assert r.status_code == 200

    @pytest.mark.xfail(reason="Iter 57 RBAC leak — /admin/artists uses admin_only, not require_permission('artists.moderate'). Sidebar UI hides for finance but backend endpoint is still reachable.", strict=True)
    def test_finance_admin_cannot_moderate_artists(self):
        s = _login("iter57_finance@booktalent.com", "Finance@123")
        r = s.get(f"{API}/admin/artists")
        assert r.status_code == 403

    @pytest.mark.xfail(reason="Iter 57 RBAC leak — /admin/refunds uses admin_only, not require_permission('payments.refund'). Sidebar UI hides for support but backend endpoint is still reachable.", strict=True)
    def test_support_admin_cannot_view_refunds(self):
        s = _login("iter57_support@booktalent.com", "Support@123")
        r = s.get(f"{API}/admin/refunds")
        assert r.status_code == 403


# ─── Cleanup — always run last ───────────────────────────────────────────
class TestCleanup:
    def test_z_cleanup_iter57_admins(self, super_admin):
        existing = super_admin.get(f"{API}/admin/admins").json()
        for a in existing:
            if a["email"].startswith("iter57_"):
                r = super_admin.delete(f"{API}/admin/admins/{a['id']}?hard=true")
                assert r.status_code in (200, 204), f"delete {a['email']}: {r.status_code}"
