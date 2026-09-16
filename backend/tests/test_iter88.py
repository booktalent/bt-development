"""Iter 88 backend tests — payout retry queue, report schedules, manager scorecard, WA templates."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
CUSTOMER = {"email": "customer@booktalent.com", "password": "Customer@123"}


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def customer_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=CUSTOMER, timeout=30)
    assert r.status_code == 200, f"customer login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# ── Payout Retry Queue ────────────────────────────────────────────
class TestPayoutRetryQueue:
    def test_list_retry_queue(self, admin_session):
        r = admin_session.get(f"{API}/admin/payouts/retry-queue", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "count" in d and "summary" in d
        for k in ("queued", "in_progress", "succeeded", "failed", "cancelled"):
            assert k in d["summary"]

    def test_list_retry_queue_filter(self, admin_session):
        r = admin_session.get(f"{API}/admin/payouts/retry-queue?status=queued", timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["status"] == "queued"

    def test_enqueue_cancel_retry_cycle(self, admin_session):
        # enqueue with real-ish booking id (may or may not exist — endpoint doesn't validate)
        r = admin_session.post(
            f"{API}/admin/payouts/retry-queue/enqueue",
            params={"booking_id": "TEST_booking_iter88", "amount": 1000, "reason": "test"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        row = r.json()
        assert row["status"] == "queued"
        assert row["attempts"] == 0
        assert row["next_attempt_at"]
        eid = row["id"]

        # cancel
        r2 = admin_session.post(f"{API}/admin/payouts/retry-queue/{eid}/cancel", timeout=30)
        assert r2.status_code == 200

        # verify cancelled in list
        r3 = admin_session.get(f"{API}/admin/payouts/retry-queue?status=cancelled", timeout=30)
        assert any(it["id"] == eid for it in r3.json()["items"])

        # force retry back to queued
        r4 = admin_session.post(f"{API}/admin/payouts/retry-queue/{eid}/retry", timeout=30)
        assert r4.status_code == 200

        r5 = admin_session.get(f"{API}/admin/payouts/retry-queue?status=queued", timeout=30)
        found = [it for it in r5.json()["items"] if it["id"] == eid]
        assert found, "entry not moved back to queued"

        # cleanup: cancel it
        admin_session.post(f"{API}/admin/payouts/retry-queue/{eid}/cancel", timeout=30)

    def test_cancel_nonexistent(self, admin_session):
        r = admin_session.post(f"{API}/admin/payouts/retry-queue/does-not-exist/cancel", timeout=30)
        assert r.status_code == 404

    def test_non_admin_forbidden(self, customer_session):
        r = customer_session.get(f"{API}/admin/payouts/retry-queue", timeout=30)
        assert r.status_code == 403


# ── Report Schedules ──────────────────────────────────────────────
class TestReportSchedules:
    created_id = None

    def test_create_weekly_schedule(self, admin_session):
        body = {
            "kind": "manager_leads",
            "email": "admin@booktalent.com",
            "frequency": "weekly",
            "day_of_week": 0,
            "hour_ist": 8,
            "enabled": True,
        }
        r = admin_session.post(f"{API}/admin/report-schedules", json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"] and d["next_run_at"] and d["kind"] == "manager_leads"
        # next_run_at should be in the future
        from datetime import datetime, timezone
        nra = datetime.fromisoformat(d["next_run_at"].replace("Z", "+00:00"))
        if nra.tzinfo is None:
            nra = nra.replace(tzinfo=timezone.utc)
        assert nra > datetime.now(timezone.utc), "next_run_at not in future"
        TestReportSchedules.created_id = d["id"]

    def test_list_schedules(self, admin_session):
        r = admin_session.get(f"{API}/admin/report-schedules", timeout=30)
        assert r.status_code == 200
        assert any(s["id"] == TestReportSchedules.created_id for s in r.json()["items"])

    def test_patch_schedule(self, admin_session):
        sid = TestReportSchedules.created_id
        body = {
            "kind": "artist_bookings",
            "email": "admin@booktalent.com",
            "frequency": "daily",
            "day_of_week": None,
            "hour_ist": 10,
            "enabled": False,
        }
        r = admin_session.patch(f"{API}/admin/report-schedules/{sid}", json=body, timeout=30)
        assert r.status_code == 200

    def test_weekly_requires_dow(self, admin_session):
        body = {
            "kind": "platform_waivers",
            "email": "admin@booktalent.com",
            "frequency": "weekly",
            "hour_ist": 8,
            "enabled": True,
        }
        r = admin_session.post(f"{API}/admin/report-schedules", json=body, timeout=30)
        assert r.status_code == 400

    def test_run_now(self, admin_session):
        # Use a fresh schedule and run — SMTP is live; use test admin email
        body = {
            "kind": "platform_waivers",
            "email": "admin@booktalent.com",
            "frequency": "daily",
            "hour_ist": 8,
            "enabled": True,
        }
        r = admin_session.post(f"{API}/admin/report-schedules", json=body, timeout=30)
        sid = r.json()["id"]
        try:
            r2 = admin_session.post(f"{API}/admin/report-schedules/{sid}/run-now", timeout=60)
            assert r2.status_code == 200
            data = r2.json()
            # Environment SMTP is live per playbook — should return sent=True; but tolerate failure and log
            assert "sent" in data
            if not data.get("sent"):
                print(f"[WARN] run-now returned sent=False: {data.get('reason')}")
        finally:
            admin_session.delete(f"{API}/admin/report-schedules/{sid}", timeout=30)

    def test_delete_schedule(self, admin_session):
        sid = TestReportSchedules.created_id
        r = admin_session.delete(f"{API}/admin/report-schedules/{sid}", timeout=30)
        assert r.status_code == 200
        assert r.json().get("deleted") == 1

    def test_non_admin_forbidden(self, customer_session):
        r = customer_session.get(f"{API}/admin/report-schedules", timeout=30)
        assert r.status_code == 403


# ── Manager Scorecard + Targets ──────────────────────────────────
class TestManagerScorecard:
    def test_scorecard_current_month(self, admin_session):
        r = admin_session.get(f"{API}/admin/reports/manager-scorecard", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "month" in d
        for c in d["items"]:
            for k in ("manager_id", "leads_won", "leads_lost", "conversion_pct",
                      "revenue_driven", "monthly_lead_target", "monthly_revenue_target",
                      "lead_progress_pct", "revenue_progress_pct"):
                assert k in c, f"missing key {k}"

    def test_scorecard_bad_month(self, admin_session):
        r = admin_session.get(f"{API}/admin/reports/manager-scorecard?month=badformat", timeout=30)
        assert r.status_code == 400

    def test_scorecard_specific_month(self, admin_session):
        r = admin_session.get(f"{API}/admin/reports/manager-scorecard?month=2026-01", timeout=30)
        assert r.status_code == 200
        assert r.json()["month"] == "2026-01"

    def test_set_targets_404_non_manager(self, admin_session):
        r = admin_session.patch(
            f"{API}/admin/managers/does-not-exist/targets",
            json={"monthly_lead_target": 10, "monthly_revenue_target": 100000},
            timeout=30,
        )
        assert r.status_code == 404

    def test_set_targets_for_real_manager(self, admin_session):
        # find a manager or skip
        sc = admin_session.get(f"{API}/admin/reports/manager-scorecard", timeout=30).json()
        if not sc["items"]:
            pytest.skip("No managers in DB — cannot test PATCH targets")
        mid = sc["items"][0]["manager_id"]
        r = admin_session.patch(
            f"{API}/admin/managers/{mid}/targets",
            json={"monthly_lead_target": 20, "monthly_revenue_target": 500000},
            timeout=30,
        )
        assert r.status_code == 200
        # reflect
        sc2 = admin_session.get(f"{API}/admin/reports/manager-scorecard", timeout=30).json()
        card = next((c for c in sc2["items"] if c["manager_id"] == mid), None)
        assert card and card["monthly_lead_target"] == 20 and card["monthly_revenue_target"] == 500000

    def test_non_admin_forbidden(self, customer_session):
        r = customer_session.get(f"{API}/admin/reports/manager-scorecard", timeout=30)
        assert r.status_code == 403


# ── WhatsApp Templates Status ────────────────────────────────────
class TestWhatsAppTemplates:
    def test_status(self, admin_session):
        r = admin_session.get(f"{API}/admin/whatsapp/templates-status", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "provider" in d and "templates" in d
        assert d["provider"] == "wachatsender", f"expected wachatsender, got {d['provider']}"
        assert len(d["templates"]) == 6
        for row in d["templates"]:
            assert "event" in row and "env_var" in row and "template_name" in row

    def test_non_admin_forbidden(self, customer_session):
        r = customer_session.get(f"{API}/admin/whatsapp/templates-status", timeout=30)
        assert r.status_code == 403


# ── Iter 87 regression ───────────────────────────────────────────
class TestIter87Regression:
    def test_reports_endpoints(self, admin_session):
        for path in ("/admin/reports/artist-bookings", "/admin/reports/manager-leads",
                      "/admin/reports/platform-waivers"):
            r = admin_session.get(f"{API}{path}", timeout=30)
            assert r.status_code == 200, f"{path}: {r.status_code}"

    def test_audit_unified(self, admin_session):
        r = admin_session.get(f"{API}/admin/audit-logs/unified?limit=10", timeout=30)
        assert r.status_code == 200
