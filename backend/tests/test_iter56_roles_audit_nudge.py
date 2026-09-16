"""
Iter 56 backend regression tests.

Covers:
  * DB-backed role preset CRUD  (GET/POST/PATCH/DELETE /admin/roles)
  * Role in-use guard (cannot delete role held by any admin)
  * Audit log helper populating /admin/audit-log with all action types
  * Questionnaire completion endpoint  (/questionnaire/completion/mine)
  * Media matches shape on /artists/{id}/about
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as fp:
        for line in fp:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"

SUPER_ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
ARTIST = {"email": "priya@booktalent.com", "password": "Artist@123"}
PRIYA_ID = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"

TS = int(time.time())
NEW_ROLE_ID = f"iter56_marketing_{TS}"
NEW_ADMIN_EMAIL = f"iter56_mkt_{TS}_{uuid.uuid4().hex[:5]}@test.com"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login({email}) failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login(**SUPER_ADMIN)


@pytest.fixture(scope="module")
def artist_session():
    return _login(**ARTIST)


# ══════════════ 1. Role Preset CRUD ══════════════
class TestRolePresetCRUD:
    def test_list_roles(self, admin_session):
        r = admin_session.get(f"{API}/admin/roles", timeout=10)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # Must include super_admin with readonly true
        sa = next((x for x in rows if x["id"] == "super_admin"), None)
        assert sa is not None
        assert sa.get("readonly") is True
        assert isinstance(sa.get("permissions"), list)
        # Sanity: presets should include the 6 seeded defaults
        ids = {r["id"] for r in rows}
        for expected in ("super_admin", "operations", "finance", "content", "support", "viewer"):
            assert expected in ids, f"missing preset {expected}"

    def test_create_new_role(self, admin_session):
        perms = ["users.view", "bookings.view", "analytics.view"]
        r = admin_session.post(f"{API}/admin/roles",
                               json={"id": NEW_ROLE_ID, "permissions": perms}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("id") == NEW_ROLE_ID
        assert set(d["permissions"]) == set(perms)
        # Verify list contains it
        rows = admin_session.get(f"{API}/admin/roles", timeout=10).json()
        assert any(x["id"] == NEW_ROLE_ID for x in rows)

    def test_create_role_reserved_custom_400(self, admin_session):
        r = admin_session.post(f"{API}/admin/roles",
                               json={"id": "custom", "permissions": ["users.view"]}, timeout=10)
        assert r.status_code == 400, r.text

    def test_create_duplicate_id_400(self, admin_session):
        r = admin_session.post(f"{API}/admin/roles",
                               json={"id": NEW_ROLE_ID, "permissions": ["users.view"]}, timeout=10)
        assert r.status_code == 400, r.text

    def test_patch_super_admin_400(self, admin_session):
        r = admin_session.patch(f"{API}/admin/roles/super_admin",
                                json={"id": "super_admin", "permissions": ["users.view"]}, timeout=10)
        assert r.status_code == 400, r.text

    def test_delete_super_admin_400(self, admin_session):
        r = admin_session.delete(f"{API}/admin/roles/super_admin", timeout=10)
        assert r.status_code == 400, r.text

    def test_patch_new_role(self, admin_session):
        new_perms = ["users.view", "bookings.view", "analytics.view", "payments.view"]
        r = admin_session.patch(f"{API}/admin/roles/{NEW_ROLE_ID}",
                                json={"id": NEW_ROLE_ID, "permissions": new_perms}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d["permissions"]) == set(new_perms)
        # Verify via list
        rows = admin_session.get(f"{API}/admin/roles", timeout=10).json()
        row = next(x for x in rows if x["id"] == NEW_ROLE_ID)
        assert set(row["permissions"]) == set(new_perms)


# ══════════════ 2. Role in-use guard ══════════════
class TestRoleInUseGuard:
    """Assign a new admin the marketing role, verify delete blocks, then unblock."""
    def test_create_admin_with_new_role(self, admin_session):
        body = {
            "email": NEW_ADMIN_EMAIL,
            "password": "MktRole@123",
            "first_name": "Mkt",
            "last_name": "Admin",
            "admin_role": NEW_ROLE_ID,
        }
        r = admin_session.post(f"{API}/admin/admins", json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["admin_role"] == NEW_ROLE_ID
        # Store id for later cleanup
        pytest._iter56_admin_id = d["id"]

    def test_delete_role_in_use_400(self, admin_session):
        r = admin_session.delete(f"{API}/admin/roles/{NEW_ROLE_ID}", timeout=10)
        assert r.status_code == 400, r.text
        # Message should mention count / "hold this role"
        msg = r.text.lower()
        assert "hold" in msg or "still" in msg or "reassign" in msg

    def test_soft_delete_admin_then_delete_role_succeeds(self, admin_session):
        aid = getattr(pytest, "_iter56_admin_id", None)
        assert aid, "prerequisite admin id not set"
        d = admin_session.delete(f"{API}/admin/admins/{aid}", timeout=10)
        assert d.status_code == 200, d.text
        # Now role should be deletable
        r = admin_session.delete(f"{API}/admin/roles/{NEW_ROLE_ID}", timeout=10)
        assert r.status_code == 200, r.text
        # And listing should not include it
        rows = admin_session.get(f"{API}/admin/roles", timeout=10).json()
        assert not any(x["id"] == NEW_ROLE_ID for x in rows)


# ══════════════ 3. Audit log ══════════════
class TestAuditLog:
    def test_audit_log_has_all_action_groups(self, admin_session):
        """After previous tests we should have role.create, role.update, role.delete,
        admin.create, admin.delete (soft) events. Verify all present."""
        r = admin_session.get(f"{API}/admin/audit-log?limit=500", timeout=15)
        assert r.status_code == 200, r.text
        entries = r.json()
        assert isinstance(entries, list) and len(entries) > 0
        # Check field shape on first entry
        e = entries[0]
        for k in ("action", "actor_email", "actor_role", "created_at"):
            assert k in e, f"missing field {k} in audit entry"
        actions_seen = {x["action"] for x in entries}
        # From our above tests we expect these:
        for expected in ("role.create", "role.update", "role.delete", "admin.create", "admin.delete"):
            assert expected in actions_seen, f"missing action {expected} in {actions_seen}"

    def test_audit_log_filter_by_action(self, admin_session):
        r = admin_session.get(f"{API}/admin/audit-log?action=admin.create&limit=200", timeout=15)
        assert r.status_code == 200, r.text
        entries = r.json()
        assert isinstance(entries, list)
        assert len(entries) > 0
        assert all(x["action"] == "admin.create" for x in entries)

    def test_audit_log_valid_actions(self, admin_session):
        """All actions produced by the app should be in a known set."""
        r = admin_session.get(f"{API}/admin/audit-log?limit=500", timeout=15)
        entries = r.json()
        valid = {
            "admin.create", "admin.update", "admin.suspend", "admin.reactivate",
            "admin.delete", "admin.password_reset",
            "role.create", "role.update", "role.delete",
        }
        actions_seen = {x["action"] for x in entries}
        # All seen actions must be in valid set (no typos)
        stray = actions_seen - valid
        assert not stray, f"unexpected audit actions: {stray}"


# ══════════════ 4. Suspend/Reactivate audit + admin lifecycle ══════════════
class TestAdminLifecycleAudits:
    def test_create_suspend_reactivate_flow_creates_audits(self, admin_session):
        # Create ephemeral admin
        email = f"iter56_susp_{int(time.time())}_{uuid.uuid4().hex[:5]}@test.com"
        r = admin_session.post(f"{API}/admin/admins", json={
            "email": email, "password": "Susp@1234", "admin_role": "viewer"
        }, timeout=15)
        assert r.status_code == 200, r.text
        aid = r.json()["id"]

        # Suspend (active=False)
        s = admin_session.patch(f"{API}/admin/admins/{aid}", json={"active": False}, timeout=10)
        assert s.status_code == 200, s.text
        # Reactivate (active=True)
        a = admin_session.patch(f"{API}/admin/admins/{aid}", json={"active": True}, timeout=10)
        assert a.status_code == 200, a.text

        # Verify audit log has admin.suspend + admin.reactivate for this actor
        entries = admin_session.get(f"{API}/admin/audit-log?limit=500", timeout=15).json()
        by_target = [x for x in entries if x.get("target_email") == email or (x.get("meta") or {}).get("email") == email]
        actions = {x["action"] for x in by_target}
        # Some routes may store admin.update instead — check either family
        has_suspend = any(a in actions for a in ("admin.suspend", "admin.update"))
        has_reactivate = any(a in actions for a in ("admin.reactivate", "admin.update"))
        assert has_suspend, f"no suspend audit event for {email}: {actions}"
        assert has_reactivate, f"no reactivate audit event for {email}: {actions}"

        # Cleanup
        admin_session.delete(f"{API}/admin/admins/{aid}", timeout=10)


# ══════════════ 5. Questionnaire completion endpoint ══════════════
class TestQuestionnaireCompletion:
    def test_completion_mine_artist(self, artist_session):
        r = artist_session.get(f"{API}/questionnaire/completion/mine", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("sections_total", "sections_answered", "sections_missing",
                 "questions_total", "questions_answered"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["sections_missing"], list)
        # All entries must be strings
        assert all(isinstance(x, str) for x in d["sections_missing"]), "sections_missing must be list of strings"
        assert isinstance(d["sections_total"], int)
        assert isinstance(d["questions_total"], int)
        assert isinstance(d["questions_answered"], int)
        # Priya seed data has 15 answers, 8 sections missing per spec
        # Just verify sections_missing.length > 3 so the nudge fires
        assert len(d["sections_missing"]) > 3, f"expected >3 missing, got {d['sections_missing']}"

    def test_completion_mine_non_artist_403(self, admin_session):
        r = admin_session.get(f"{API}/questionnaire/completion/mine", timeout=15)
        assert r.status_code == 403, r.text


# ══════════════ 6. Media matches ══════════════
class TestMediaMatches:
    def test_about_has_media_matches_array(self):
        r = requests.get(f"{API}/artists/{PRIYA_ID}/about", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "media_matches" in d, "media_matches key missing"
        assert isinstance(d["media_matches"], list), "media_matches must be an array"
        # Also completion block
        assert "completion" in d
        assert set(d["completion"].keys()) >= {"sections_total", "sections_answered",
                                                "sections_missing", "questions_total", "questions_answered"}


# ══════════════ Cleanup ══════════════
def test_zzz_cleanup_iter56_traces():
    """Ensure no iter56_* leftover roles remain."""
    s = _login(**SUPER_ADMIN)
    rows = s.get(f"{API}/admin/roles", timeout=10).json()
    leftover_roles = [r["id"] for r in rows if r["id"].startswith("iter56_")]
    for rid in leftover_roles:
        s.delete(f"{API}/admin/roles/{rid}", timeout=10)
    # OK if some remain due to in-use guard — just log
    print(f"iter56 leftover roles cleaned: {leftover_roles}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
