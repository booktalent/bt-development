"""Iter 84 — Feb-2026 Batch 3 backend regression: Refund Auditor, Preset Sharing,
email timeline snippet, Bulk Payout Marker."""
import os
import asyncio
import pytest
import requests
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

BOOKING_ID = "914f366d-b1f9-41a9-88d8-65ffe394b033"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@booktalent.com", "Admin@123")


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def mgr_token():
    return _login("test-mgr@booktalent.com", "Manager@123")


@pytest.fixture(scope="module")
def mgr_h(mgr_token):
    return {"Authorization": f"Bearer {mgr_token}"}


# ─────────────── (1) Refund Auditor ───────────────
class TestRefundAuditor:
    def test_list(self, admin_h):
        r = requests.get(f"{API}/admin/refunds/audit", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "totals" in data
        t = data["totals"]
        for k in ("count", "amount_pending", "amount_accepted", "amount_rejected"):
            assert k in t
        assert isinstance(t["count"], int)

    def test_filter_accepted(self, admin_h):
        r = requests.get(f"{API}/admin/refunds/audit?status=accepted", headers=admin_h, timeout=15)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == "accepted"

    def test_filter_date(self, admin_h):
        r = requests.get(
            f"{API}/admin/refunds/audit?from_date=2020-01-01&to_date=2030-12-31",
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200

    def test_csv_export(self, admin_h):
        r = requests.get(f"{API}/admin/refunds/audit/export.csv", headers=admin_h, timeout=20)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()
        first_line = r.text.splitlines()[0]
        assert first_line.startswith("Booking Ref,Event Date,Booking Total,Refund Amount"), first_line

    def test_pdf_export(self, admin_h):
        r = requests.get(f"{API}/admin/refunds/audit/export.pdf", headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text[:500]
        assert "application/pdf" in r.headers.get("content-type", "").lower()
        assert r.content[:7].startswith(b"%PDF-1."), r.content[:20]


# ─────────────── (2) Preset sharing ───────────────
class TestPresetSharing:
    preset_id = None

    def test_create_shared(self, mgr_h):
        payload = {
            "name": f"TEST_shared_{os.urandom(3).hex()}",
            "event_type": "wedding",
            "shared": True,
        }
        r = requests.post(f"{API}/manager/booking-presets", json=payload, headers=mgr_h, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        p = d.get("preset") or {}
        assert p.get("shared") is True
        assert p.get("owned") is True
        TestPresetSharing.preset_id = p.get("id")
        assert TestPresetSharing.preset_id

    def test_list_includes(self, mgr_h):
        r = requests.get(f"{API}/manager/booking-presets", headers=mgr_h, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items") or r.json().get("presets") or []
        # fallback if key differs
        if not items and isinstance(r.json(), list):
            items = r.json()
        found = [x for x in items if x.get("id") == TestPresetSharing.preset_id]
        assert found, f"created preset not in list: {r.json()}"
        assert found[0].get("owned") is True

    def test_toggle_share_off(self, mgr_h):
        pid = TestPresetSharing.preset_id
        r = requests.patch(f"{API}/manager/booking-presets/{pid}/share",
                           json={"shared": False}, headers=mgr_h, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True and d.get("shared") is False

    def test_delete(self, mgr_h):
        pid = TestPresetSharing.preset_id
        r = requests.delete(f"{API}/manager/booking-presets/{pid}", headers=mgr_h, timeout=15)
        assert r.status_code == 200, r.text


# ─────────────── (3) Email timeline snippet ───────────────
class TestTimelineHelper:
    def test_build_html(self):
        async def _run():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            from routes.req_batch_3 import build_email_timeline_html, fetch_booking_events
            bk = await db.bookings.find_one({"id": BOOKING_ID})
            assert bk, "seed booking missing"
            events = await fetch_booking_events(db, BOOKING_ID)
            html = build_email_timeline_html(bk, events)
            assert isinstance(html, str) and len(html) > 0
            assert "BOOKING TIMELINE" in html
            assert "Booking Created" in html
            client.close()

        # Ensure backend cwd is on path (for `routes.` import).
        import sys
        sys.path.insert(0, "/app/backend")
        asyncio.get_event_loop().run_until_complete(_run())


# ─────────────── (4) Bulk Payout ───────────────
class TestBulkPayout:
    def test_pending_list(self, admin_h):
        r = requests.get(f"{API}/admin/payouts/pending-list?limit=5", headers=admin_h, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "count" in d
        for it in d["items"]:
            for k in ("booking_id", "booking_ref", "artist_email", "outstanding"):
                assert k in it
            assert it["outstanding"] > 0

    def test_bulk_mark_paid(self, admin_h):
        async def _prep():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            await db.bookings.update_one(
                {"id": BOOKING_ID},
                {"$set": {"payment_status": "partial", "paid_amount": 50000,
                          "pricing.artist_payable": 80000},
                 "$unset": {"artist_payout_status": ""}},
            )
            # remove any prior test payouts
            await db.artist_payouts.delete_many({"utr": "TEST-QA-001"})
            client.close()

        import sys
        sys.path.insert(0, "/app/backend")
        asyncio.get_event_loop().run_until_complete(_prep())

        body = {
            "default_method": "neft",
            "rows": [{
                "booking_id": BOOKING_ID,
                "amount": 80000,
                "utr": "TEST-QA-001",
                "notes": "qa",
            }],
        }
        r = requests.post(f"{API}/admin/payouts/bulk-mark-paid", json=body,
                          headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["succeeded"] == 1, d
        assert d["failed"] == 0, d
        assert d["results"][0].get("payout_id"), d

        # cleanup
        async def _cleanup():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            await db.artist_payouts.delete_many({"utr": "TEST-QA-001"})
            await db.bookings.update_one(
                {"id": BOOKING_ID},
                {"$unset": {"artist_payout_status": "", "artist_payout_id": "",
                            "artist_payout_paid_at": ""}},
            )
            client.close()

        asyncio.get_event_loop().run_until_complete(_cleanup())
