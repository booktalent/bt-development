"""Tests for Feb-2026 Requirement Batch 2:
- Agency overview ₹ KPIs
- Service artist seed + quote waiver
- Manager booking presets CRUD
- Mutual refund flow
- Booking timeline persistence
"""
import os
import time
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
MANAGER = ("test-mgr@booktalent.com", "Manager@123")
AGENCY = ("agency@booktalent.com", "Agency@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")
ARTIST_PRIYA = ("priya@booktalent.com", "Artist@123")
SERVICE_ARTIST = ("service-artist@booktalent.com", "Service@123")

TARGET_BOOKING_ID = "914f366d-b1f9-41a9-88d8-65ffe394b033"
CUSTOMER_ID = "793d2f73-fd1e-4e85-a387-043e7c2378e5"
ARTIST_ID = "test-artist-id"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s, r.json()


@pytest.fixture(scope="module")
def admin_s():
    s, _ = _login(*ADMIN)
    return s


@pytest.fixture(scope="module")
def manager_s():
    s, _ = _login(*MANAGER)
    return s


@pytest.fixture(scope="module")
def agency_s():
    s, _ = _login(*AGENCY)
    return s


@pytest.fixture(scope="module")
def customer_s():
    s, u = _login(*CUSTOMER)
    return s, u.get("user", {})


# ══════════════════════════════════════════════════════════════════════
# 1. Agency Overview KPIs
# ══════════════════════════════════════════════════════════════════════
def test_agency_overview_new_financial_fields(agency_s):
    r = agency_s.get(f"{API}/agency/overview", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("advance_received", "remaining_amount", "artist_payout_pending"):
        assert k in data, f"missing {k} in agency overview: {list(data.keys())}"
        assert isinstance(data[k], (int, float)), f"{k} is not numeric: {type(data[k])}"


# ══════════════════════════════════════════════════════════════════════
# 2. Service Artist seed + Quote waiver
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def service_artist_id(admin_s):
    r = admin_s.post(f"{API}/admin/seed/service-artist", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("ok") is True
    assert d.get("user_id")
    # second call idempotent
    r2 = admin_s.post(f"{API}/admin/seed/service-artist", timeout=30)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2.get("ok") is True
    assert d2.get("existed") is True
    assert d2.get("user_id") == d.get("user_id")
    return d["user_id"]


def test_service_artist_quote_waiver(admin_s, service_artist_id):
    r = admin_s.get(
        f"{API}/finance/quote",
        params={"artist_id": service_artist_id, "package_fee": 100000},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    q = r.json()
    assert q.get("is_service_artist") is True, q
    assert float(q.get("platform_fee_waiver")) == -5000, q
    assert float(q.get("platform_fee_net")) == 0, q
    assert q.get("waiver_message"), q
    assert float(q.get("booktalent_commission")) == 10000, q
    assert float(q.get("artist_payable")) == 90000, q


# ══════════════════════════════════════════════════════════════════════
# 3. Manager booking presets CRUD
# ══════════════════════════════════════════════════════════════════════
def test_manager_preset_crud(manager_s):
    name = f"TEST_preset_{int(time.time())}"
    body = {"name": name, "event_type": "Wedding", "city": "Mumbai",
            "number_of_days": 2, "default_package_fee": 75000}
    r = manager_s.post(f"{API}/manager/booking-presets", json=body, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("ok") is True
    pid = d["preset"]["id"]

    r2 = manager_s.get(f"{API}/manager/booking-presets", timeout=30)
    assert r2.status_code == 200
    items = r2.json().get("items", [])
    ids = [x.get("id") for x in items]
    assert pid in ids, f"created preset not in list: {ids}"

    r3 = manager_s.delete(f"{API}/manager/booking-presets/{pid}", timeout=30)
    assert r3.status_code == 200
    assert r3.json().get("ok") is True

    r4 = manager_s.get(f"{API}/manager/booking-presets", timeout=30)
    assert r4.status_code == 200
    ids2 = [x.get("id") for x in r4.json().get("items", [])]
    assert pid not in ids2


# ══════════════════════════════════════════════════════════════════════
# 4. Mutual refund flow — needs a booking with paid_amount>0
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def refund_booking_id():
    """Ensure target booking exists and is patched for the refund test."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "booktalent")

    async def prep():
        c = AsyncIOMotorClient(mongo_url)
        db = c[db_name]
        bk = await db.bookings.find_one({"id": TARGET_BOOKING_ID})
        if not bk:
            # Create minimal booking
            await db.bookings.insert_one({
                "id": TARGET_BOOKING_ID,
                "customer_id": CUSTOMER_ID,
                "artist_id": ARTIST_ID,
                "paid_amount": 50000,
                "pricing": {"total": 100000},
                "status": "confirmed",
                "history": [],
                "created_at": "2026-01-01T00:00:00+00:00",
            })
        else:
            await db.bookings.update_one(
                {"id": TARGET_BOOKING_ID},
                {"$set": {
                    "customer_id": CUSTOMER_ID,
                    "artist_id": ARTIST_ID,
                    "paid_amount": 50000,
                    "pricing": {"total": 100000},
                }},
            )
        # Reset any existing refund_request so we get a clean pending state
        await db.refund_requests.delete_many({"booking_id": TARGET_BOOKING_ID})
        # Clear existing timeline events for cleanliness
        await db.booking_events.delete_many({"booking_id": TARGET_BOOKING_ID,
                                             "kind": {"$in": ["refund_requested", "refund_accepted"]}})
        c.close()

    asyncio.get_event_loop().run_until_complete(prep()) if False else asyncio.run(prep())
    return TARGET_BOOKING_ID


def test_mutual_refund_flow(refund_booking_id):
    bid = refund_booking_id
    # Login as the specific customer with id=CUSTOMER_ID
    # The main customer@booktalent.com may not be that id. We need a user with id=CUSTOMER_ID.
    # Try logging in as customer@booktalent.com and check id.
    cs, cuser_json = _login(*CUSTOMER)
    cust_id = cuser_json.get("user", {}).get("id")
    if cust_id != CUSTOMER_ID:
        # Patch booking to use this customer's id instead
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "booktalent")

        async def repatch():
            c = AsyncIOMotorClient(mongo_url)
            db = c[db_name]
            await db.bookings.update_one({"id": bid}, {"$set": {"customer_id": cust_id}})
            c.close()
        asyncio.run(repatch())

    # Now ensure artist_id maps to a real user we can log in as. Use priya.
    ps, puser_json = _login(*ARTIST_PRIYA)
    priya_id = puser_json.get("user", {}).get("id")
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "booktalent")

    async def patch_artist():
        c = AsyncIOMotorClient(mongo_url)
        db = c[db_name]
        await db.bookings.update_one({"id": bid}, {"$set": {"artist_id": priya_id}})
        c.close()
    asyncio.run(patch_artist())

    # As customer, request refund
    r = cs.post(f"{API}/bookings/{bid}/refund-request",
                json={"amount": 15000, "reason": "test"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("ok") is True

    # Status = pending_counter_ack
    r2 = cs.get(f"{API}/bookings/{bid}/refund-status", timeout=30)
    assert r2.status_code == 200
    st = r2.json().get("request") or {}
    assert st.get("status") == "pending_counter_ack", st

    # As artist priya, accept
    r3 = ps.post(f"{API}/bookings/{bid}/refund-accept", timeout=30)
    assert r3.status_code == 200, r3.text
    d3 = r3.json()
    assert d3.get("ok") is True
    assert float(d3.get("amount")) == 15000

    # Status = accepted
    r4 = cs.get(f"{API}/bookings/{bid}/refund-status", timeout=30)
    assert r4.status_code == 200
    st2 = r4.json().get("request") or {}
    assert st2.get("status") == "accepted", st2


# ══════════════════════════════════════════════════════════════════════
# 5. Timeline persistence
# ══════════════════════════════════════════════════════════════════════
def test_booking_timeline_has_refund_events():
    bid = TARGET_BOOKING_ID
    cs, _ = _login(*CUSTOMER)
    r = cs.get(f"{API}/bookings/{bid}/timeline", timeout=30)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    assert isinstance(items, list) and len(items) >= 2, items
    kinds = [it.get("kind") for it in items]
    assert "refund_requested" in kinds, kinds
    assert "refund_accepted" in kinds, kinds
    for it in items:
        assert "kind" in it and "label" in it and "at" in it, it
