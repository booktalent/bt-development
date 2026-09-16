"""Iter 85 — Feb-2026 Batch 4 backend regression:
CSV Batch Payout Import (preview+apply), Refund SLA sweep, Preset /use counter,
Saved Views CRUD, and source-inspect for payment-email timeline snippet."""
import os
import asyncio
import io
import inspect
import pytest
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

BOOKING_ID = "914f366d-b1f9-41a9-88d8-65ffe394b033"
BOOKING_REF = "BT-260624-402ECF"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@booktalent.com', 'Admin@123')}"}


@pytest.fixture(scope="module")
def mgr_h():
    return {"Authorization": f"Bearer {_login('test-mgr@booktalent.com', 'Manager@123')}"}


@pytest.fixture(scope="module")
def loop():
    l = asyncio.new_event_loop()
    yield l
    l.close()


@pytest.fixture(scope="module")
def dbh(loop):
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


async def _patch_booking_for_payout(db):
    await db.bookings.update_one(
        {"id": BOOKING_ID},
        {"$set": {"payment_status": "partial", "paid_amount": 50000,
                  "pricing.artist_payable": 80000},
         "$unset": {"artist_payout_status": "", "artist_payout_id": "", "artist_paid_at": ""}},
    )


async def _cleanup_booking(db, utr=None):
    if utr:
        await db.artist_payouts.delete_many({"utr": utr})
    await db.bookings.update_one(
        {"id": BOOKING_ID},
        {"$unset": {"artist_payout_status": "", "artist_payout_id": "", "artist_paid_at": "",
                    "artist_payouts": ""}},
    )


# ═════════════ (1) CSV Batch Preview + Apply ═════════════
class TestCSVBatch:
    def test_preview_matches_ref(self, admin_h, dbh, loop):
        loop.run_until_complete(_patch_booking_for_payout(dbh))
        try:
            csv_body = (
                "Value Date,Narration,Reference No,Debit\n"
                f"2026-09-16,{BOOKING_REF} payout to artist,U1,80000\n"
                "2026-09-16,random narration nothing matches,U2,12345\n"
            )
            files = {"file": ("bank.csv", csv_body, "text/csv")}
            r = requests.post(f"{API}/admin/payouts/batch-preview",
                              headers=admin_h, files=files, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            matched = d.get("matched") or []
            assert len(matched) >= 1, f"no matches: {d}"
            m = next((m for m in matched if m["booking_id"] == BOOKING_ID), None)
            assert m is not None, f"target booking not matched: {matched}"
            assert m["match_reason"] == "ref"
            assert abs(m["amount"] - 80000) < 0.01
            assert abs(m["outstanding"] - 80000) < 0.01
            assert abs(m["delta"] - 0.0) < 0.01
            # second row should be unmatched
            unmatched = d.get("unmatched") or []
            assert any(u.get("reason") == "no_match" for u in unmatched)
        finally:
            loop.run_until_complete(_cleanup_booking(dbh))

    def test_apply_marks_paid(self, admin_h, dbh, loop):
        loop.run_until_complete(_patch_booking_for_payout(dbh))
        utr = "TESTQA4-001"
        try:
            body = {
                "rows": [{"booking_id": BOOKING_ID, "amount": 80000,
                          "utr": utr, "method": "neft"}],
                "default_method": "neft",
            }
            r = requests.post(f"{API}/admin/payouts/batch-apply",
                              headers=admin_h, json=body, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["succeeded"] == 1, d
            assert d["failed"] == 0, d
            assert d["results"][0].get("payout_id"), d
        finally:
            loop.run_until_complete(_cleanup_booking(dbh, utr=utr))


# ═════════════ (2) Refund SLA sweep ═════════════
class TestRefundSLA:
    RID = "test-sla-42"

    def test_sweep_idempotent(self, admin_h, dbh, loop):
        async def seed():
            await dbh.refund_requests.delete_many({"id": self.RID})
            await dbh.refund_requests.insert_one({
                "id": self.RID, "booking_id": BOOKING_ID, "amount": 15000,
                "status": "pending_counter_ack",
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
                "requested_by_role": "customer",
            })

        async def cleanup():
            await dbh.refund_requests.delete_many({"id": self.RID})

        loop.run_until_complete(seed())
        try:
            r = requests.post(f"{API}/admin/refunds/sla-sweep", headers=admin_h, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["alerted"] >= 1
            assert self.RID in (d.get("request_ids") or [])

            # idempotent
            r2 = requests.post(f"{API}/admin/refunds/sla-sweep", headers=admin_h, timeout=30)
            assert r2.status_code == 200, r2.text
            d2 = r2.json()
            assert self.RID not in (d2.get("request_ids") or [])

            # slack_logs verify
            async def check_log():
                doc = await dbh.slack_logs.find_one(sort=[("_id", -1)])
                return doc

            log_doc = loop.run_until_complete(check_log())
            if log_doc is not None:
                text_field = log_doc.get("text") or log_doc.get("message") or ""
                assert "Refund SLA Breach" in text_field, f"unexpected slack log: {log_doc}"
        finally:
            loop.run_until_complete(cleanup())


# ═════════════ (3) Preset /use counter ═════════════
class TestPresetUse:
    def test_use_counter(self, mgr_h, dbh, loop):
        r = requests.post(f"{API}/manager/booking-presets", headers=mgr_h,
                          json={"name": "TEST_QA_use", "event_type": "corporate", "shared": True},
                          timeout=15)
        assert r.status_code in (200, 201), r.text
        pid = (r.json().get("preset") or r.json()).get("id")
        assert pid, r.json()
        try:
            r1 = requests.post(f"{API}/manager/booking-presets/{pid}/use", headers=mgr_h, timeout=15)
            assert r1.status_code == 200, r1.text
            assert r1.json().get("usage_count") == 1

            r2 = requests.post(f"{API}/manager/booking-presets/{pid}/use", headers=mgr_h, timeout=15)
            assert r2.status_code == 200, r2.text
            assert r2.json().get("usage_count") == 2

            rl = requests.get(f"{API}/manager/booking-presets", headers=mgr_h, timeout=15)
            assert rl.status_code == 200
            items = rl.json().get("items") or rl.json().get("presets") or rl.json()
            found = next((x for x in items if x.get("id") == pid), None)
            assert found is not None
            assert int(found.get("usage_count") or 0) == 2
            assert found.get("last_used_at")
        finally:
            requests.delete(f"{API}/manager/booking-presets/{pid}", headers=mgr_h, timeout=15)

    def test_use_permission_denied(self, mgr_h, dbh, loop):
        """Try to /use another manager's private preset."""
        # find any preset owned by someone else and not shared
        async def find_other():
            me = await dbh.users.find_one({"email": "test-mgr@booktalent.com"}, {"_id": 0, "id": 1})
            my_id = me["id"] if me else None
            return await dbh.manager_booking_presets.find_one(
                {"manager_id": {"$ne": my_id}, "shared": {"$ne": True}}, {"_id": 0, "id": 1}
            )
        other = loop.run_until_complete(find_other())
        if not other:
            pytest.skip("No other manager's private preset to test with")
        r = requests.post(f"{API}/manager/booking-presets/{other['id']}/use",
                          headers=mgr_h, timeout=15)
        assert r.status_code in (403, 404), r.status_code


# ═════════════ (5) Saved views CRUD ═════════════
class TestSavedViews:
    def test_crud(self, admin_h):
        r = requests.post(f"{API}/admin/refunds/saved-views", headers=admin_h,
                          json={"name": "TEST_QA-view", "filters": {"status": "accepted"}},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        vid = d["view"]["id"]

        rl = requests.get(f"{API}/admin/refunds/saved-views", headers=admin_h, timeout=15)
        assert rl.status_code == 200
        items = rl.json().get("items") or []
        assert any(v["id"] == vid for v in items)

        rd = requests.delete(f"{API}/admin/refunds/saved-views/{vid}", headers=admin_h, timeout=15)
        assert rd.status_code == 200
        assert rd.json().get("ok") is True

        rl2 = requests.get(f"{API}/admin/refunds/saved-views", headers=admin_h, timeout=15)
        items2 = rl2.json().get("items") or []
        assert not any(v["id"] == vid for v in items2)


# ═════════════ (4) Email timeline snippet source-inspect ═════════════
class TestEmailTimelineSnippet:
    def test_import(self):
        from routes.req_batch_3 import build_email_timeline_html  # noqa
        assert callable(build_email_timeline_html)

    def test_crm_pay_reminder_uses_snippet(self):
        import routes.crm_pay as cp
        src = inspect.getsource(cp)
        assert "build_email_timeline_html" in src
        assert "timeline_html" in src

    def test_easebuzz_receipt_passes_timeline(self):
        import routes.easebuzz as eb
        src = inspect.getsource(eb)
        assert "timeline_html=" in src
        assert "build_email_timeline_html" in src

    def test_email_service_receipt_accepts_kwarg(self):
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("email_service_mod", "/app/backend/email_service.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sig = inspect.signature(mod.send_payment_receipt_email)
        assert "timeline_html" in sig.parameters
