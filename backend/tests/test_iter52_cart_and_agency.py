"""
Iter 52 backend tests — Persistent Booking Cart + Agency Dashboard V2 CRM.

Covers:
  1. Cart (anon → user merge, add/patch/remove/clear, duplicate guard, snapshot).
  2. Agency CRM: offline artists, clients (+notes/follow-ups), events, staff,
     invoices, expenses, finance summary, reports, calendar, notifications,
     overview, role-guards, marketplace privacy of offline artists.
  3. Regression: /artists/search, /bookings/mine, /auth/me,
     /homepage/spotlight, /event-planner/suggest.
"""
from __future__ import annotations

import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

AGENCY = ("agency@booktalent.com", "Agency@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")
ARTIST = ("priya@booktalent.com", "Artist@123")


# ─────────────────────────────── Helpers ────────────────────────────────────
def _login(email: str, pw: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def agency_session():
    return _login(*AGENCY)


@pytest.fixture(scope="module")
def customer_session():
    return _login(*CUSTOMER)


@pytest.fixture(scope="module")
def real_artist_id() -> str:
    """Grab a real artist id from public search so cart snapshot works."""
    r = requests.get(f"{BASE_URL}/api/artists/search", timeout=15)
    assert r.status_code == 200
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert items and len(items) > 0, "No artists found in search"
    aid = items[0].get("id") or items[0].get("user_id")
    assert aid
    return aid


# ═══════════════════════════════ CART ═══════════════════════════════════════
class TestCart:
    def test_anon_empty_cart_sets_cookie(self):
        s = requests.Session()
        r = s.get(f"{BASE_URL}/api/cart", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        assert body["items"] == []
        # cookie
        assert "bt_cart_anon" in s.cookies, f"Missing bt_cart_anon cookie. Got: {list(s.cookies.keys())}"

    def test_add_item_snapshots_artist(self, real_artist_id):
        s = requests.Session()
        s.get(f"{BASE_URL}/api/cart")  # ensure cookie
        r = s.post(f"{BASE_URL}/api/cart/items",
                   json={"artist_id": real_artist_id, "event_date": "2026-06-01"},
                   timeout=15)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["status"] == "added"
        # Verify snapshot
        cart = s.get(f"{BASE_URL}/api/cart").json()
        assert len(cart["items"]) == 1
        item = cart["items"][0]
        assert item["artist_id"] == real_artist_id
        # snapshot fields exist (may be None if profile lookup missed)
        for k in ("artist_name", "artist_city", "artist_category", "package_name", "base_price"):
            assert k in item, f"Missing snapshot field {k}"

    def test_duplicate_guard(self, real_artist_id):
        s = requests.Session()
        s.get(f"{BASE_URL}/api/cart")
        payload = {"artist_id": real_artist_id, "event_date": "2026-07-15"}
        r1 = s.post(f"{BASE_URL}/api/cart/items", json=payload)
        assert r1.status_code == 200 and r1.json()["status"] == "added"
        r2 = s.post(f"{BASE_URL}/api/cart/items", json=payload)
        assert r2.status_code == 200
        assert r2.json()["status"] == "duplicate"
        cart = s.get(f"{BASE_URL}/api/cart").json()
        assert len(cart["items"]) == 1

    def test_patch_item(self, real_artist_id):
        s = requests.Session()
        s.get(f"{BASE_URL}/api/cart")
        r = s.post(f"{BASE_URL}/api/cart/items",
                   json={"artist_id": real_artist_id, "event_date": "2026-08-10"})
        item_id = r.json()["item_id"]
        p = s.patch(f"{BASE_URL}/api/cart/items/{item_id}",
                    json={"event_city": "Mumbai", "duration_hours": 5})
        assert p.status_code == 200
        cart = s.get(f"{BASE_URL}/api/cart").json()
        it = next(x for x in cart["items"] if x["id"] == item_id)
        assert it["event_city"] == "Mumbai"
        assert it["duration_hours"] == 5

    def test_remove_and_clear(self, real_artist_id):
        s = requests.Session()
        s.get(f"{BASE_URL}/api/cart")
        r1 = s.post(f"{BASE_URL}/api/cart/items",
                    json={"artist_id": real_artist_id, "event_date": "2026-09-01"})
        r2 = s.post(f"{BASE_URL}/api/cart/items",
                    json={"artist_id": real_artist_id, "event_date": "2026-09-02"})
        i1 = r1.json()["item_id"]
        d = s.delete(f"{BASE_URL}/api/cart/items/{i1}")
        assert d.status_code == 200
        cart = s.get(f"{BASE_URL}/api/cart").json()
        assert len(cart["items"]) == 1
        c = s.post(f"{BASE_URL}/api/cart/clear")
        assert c.status_code == 200
        cart = s.get(f"{BASE_URL}/api/cart").json()
        assert cart["items"] == []

    def test_anon_to_user_merge_on_login(self, real_artist_id):
        # Anon cart with 2 items
        s = requests.Session()
        s.get(f"{BASE_URL}/api/cart")
        s.post(f"{BASE_URL}/api/cart/items",
               json={"artist_id": real_artist_id, "event_date": "2026-10-01"})
        s.post(f"{BASE_URL}/api/cart/items",
               json={"artist_id": real_artist_id, "event_date": "2026-10-02"})
        # Login on the SAME session so anon cookie is preserved
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": CUSTOMER[0], "password": CUSTOMER[1]}, timeout=15)
        assert r.status_code == 200
        # First get_cart call after login merges anon -> user
        cart = s.get(f"{BASE_URL}/api/cart").json()
        dates = sorted([it["event_date"] for it in cart["items"]])
        assert "2026-10-01" in dates
        assert "2026-10-02" in dates
        # Clean up user cart
        s.post(f"{BASE_URL}/api/cart/clear")


# ═══════════════════════ AGENCY ROLE GUARDS ═════════════════════════════════
class TestAgencyRoleGuard:
    def test_customer_gets_403_on_overview(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/agency/overview")
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text[:200]}"

    def test_customer_gets_403_on_clients(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/agency/clients")
        assert r.status_code == 403

    def test_anon_gets_401_on_agency(self):
        r = requests.get(f"{BASE_URL}/api/agency/overview")
        assert r.status_code == 401


# ═══════════════════════ AGENCY OVERVIEW ════════════════════════════════════
class TestAgencyOverview:
    def test_overview_shape(self, agency_session):
        r = agency_session.get(f"{BASE_URL}/api/agency/overview")
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ("roster_artists", "offline_artists", "clients",
                  "upcoming_offline_events", "upcoming_platform_bookings",
                  "pending_bookings", "recent_activity"):
            assert k in b, f"Missing key: {k}"
        assert isinstance(b["recent_activity"], list)


# ═══════════════════════ AGENCY OFFLINE ARTISTS ═════════════════════════════
class TestOfflineArtists:
    def test_crud_and_marketplace_privacy(self, agency_session):
        # Create
        payload = {"name": f"TEST_off_{uuid.uuid4().hex[:6]}", "category": "DJ",
                   "phone": "+91 90000 00000", "base_price": 15000, "city": "Goa"}
        r = agency_session.post(f"{BASE_URL}/api/agency/offline-artists", json=payload)
        assert r.status_code == 200, r.text
        oid = r.json()["id"]

        # List
        lst = agency_session.get(f"{BASE_URL}/api/agency/offline-artists").json()
        assert any(x["id"] == oid for x in lst)

        # PRIVACY: this offline artist must NOT surface in the public marketplace
        search = requests.get(f"{BASE_URL}/api/artists/search").json()
        items = search.get("items") if isinstance(search, dict) else search
        names = [x.get("name") or x.get("stage_name") for x in items]
        assert payload["name"] not in names, "Offline artist leaked into public marketplace!"

        # Delete
        d = agency_session.delete(f"{BASE_URL}/api/agency/offline-artists/{oid}")
        assert d.status_code == 200


# ═══════════════════════ AGENCY CLIENTS CRM ═════════════════════════════════
class TestAgencyClients:
    def test_client_notes_and_followups(self, agency_session):
        cr = agency_session.post(f"{BASE_URL}/api/agency/clients",
                                 json={"name": f"TEST_client_{uuid.uuid4().hex[:6]}",
                                       "phone": "+91 99999 00000",
                                       "email": "test.client@example.com",
                                       "company": "TestCo", "city": "Mumbai"})
        assert cr.status_code == 200, cr.text
        cid = cr.json()["id"]

        # Add note
        nr = agency_session.post(f"{BASE_URL}/api/agency/clients/{cid}/notes",
                                 json={"text": "First contact via referral"})
        assert nr.status_code == 200

        # Add follow-up (should fan-out notification)
        fr = agency_session.post(f"{BASE_URL}/api/agency/clients/{cid}/follow-ups",
                                 json={"due_at": "2026-06-15T10:00:00Z",
                                       "text": "Call back re quotation"})
        assert fr.status_code == 200

        # GET detail
        detail = agency_session.get(f"{BASE_URL}/api/agency/clients/{cid}").json()
        assert len(detail["notes_log"]) >= 1
        assert len(detail["follow_ups"]) >= 1

        # Notification fired
        nots = agency_session.get(f"{BASE_URL}/api/agency/notifications").json()
        assert any(n.get("kind") == "followup" for n in nots["items"])

        # Cleanup
        agency_session.delete(f"{BASE_URL}/api/agency/clients/{cid}")


# ═══════════════════════ AGENCY EVENTS ═══════════════════════════════════════
class TestAgencyEvents:
    def test_event_crud(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/events", json={
            "title": f"TEST_evt_{uuid.uuid4().hex[:6]}",
            "event_date": "2026-07-20",
            "venue": "The Grand Palladium",
            "city": "Delhi",
            "quotation_amount": 75000,
            "checklist": [{"text": "Sound check", "done": False}],
            "artists": [{"artist_id": "offline-1", "is_offline": True, "name": "Test Artist", "price": 30000}],
        })
        assert r.status_code == 200, r.text
        eid = r.json()["id"]

        # List
        lst = agency_session.get(f"{BASE_URL}/api/agency/events").json()
        assert any(x["id"] == eid for x in lst)

        # Filter
        f = agency_session.get(f"{BASE_URL}/api/agency/events", params={"from": "2026-01-01", "to": "2027-01-01"}).json()
        assert any(x["id"] == eid for x in f)

        # Patch status
        p = agency_session.patch(f"{BASE_URL}/api/agency/events/{eid}", json={"status": "completed"})
        assert p.status_code == 200

        # Delete
        d = agency_session.delete(f"{BASE_URL}/api/agency/events/{eid}")
        assert d.status_code == 200


# ═══════════════════════ AGENCY STAFF ═══════════════════════════════════════
class TestAgencyStaff:
    def test_staff_dup_email_returns_409(self, agency_session):
        email = f"test_staff_{uuid.uuid4().hex[:6]}@example.com"
        p = {"email": email, "name": "Test Staff", "role": "coordinator"}
        r1 = agency_session.post(f"{BASE_URL}/api/agency/staff", json=p)
        assert r1.status_code == 200, r1.text
        sid = r1.json()["id"]
        r2 = agency_session.post(f"{BASE_URL}/api/agency/staff", json=p)
        assert r2.status_code == 409
        # Cleanup
        agency_session.delete(f"{BASE_URL}/api/agency/staff/{sid}")


# ═══════════════════════ AGENCY FINANCE ═════════════════════════════════════
class TestAgencyFinance:
    def test_invoice_math_and_paid(self, agency_session):
        # Need a client
        cr = agency_session.post(f"{BASE_URL}/api/agency/clients",
                                 json={"name": f"TEST_inv_client_{uuid.uuid4().hex[:6]}"})
        cid = cr.json()["id"]
        try:
            r = agency_session.post(f"{BASE_URL}/api/agency/invoices", json={
                "client_id": cid,
                "line_items": [{"desc": "Artist fee", "qty": 1, "unit_price": 50000, "amount": 50000},
                               {"desc": "Sound", "qty": 1, "unit_price": 10000, "amount": 10000}],
                "tax_pct": 18.0,
            })
            assert r.status_code == 200, r.text
            b = r.json()
            assert b["subtotal"] == 60000
            assert b["tax"] == 10800.0
            assert b["total"] == 70800.0
            iid = b["id"]

            # Mark paid
            p = agency_session.patch(f"{BASE_URL}/api/agency/invoices/{iid}", json={"status": "paid"})
            assert p.status_code == 200
            lst = agency_session.get(f"{BASE_URL}/api/agency/invoices").json()
            inv = next(x for x in lst if x["id"] == iid)
            assert inv["status"] == "paid"
            assert inv.get("paid_at")
        finally:
            agency_session.delete(f"{BASE_URL}/api/agency/clients/{cid}")

    def test_expenses_and_summary(self, agency_session):
        r = agency_session.post(f"{BASE_URL}/api/agency/expenses", json={
            "category": "Travel", "amount": 2500, "date": "2026-05-01", "notes": "TEST_exp"
        })
        assert r.status_code == 200, r.text
        s = agency_session.get(f"{BASE_URL}/api/agency/finance/summary").json()
        for k in ("invoices_by_status", "offline_revenue", "platform_commission", "expenses", "net"):
            assert k in s


# ═══════════════════════ AGENCY REPORTS & CALENDAR & NOTIFICATIONS ══════════
class TestAgencyReportsCalendar:
    def test_reports_endpoints(self, agency_session):
        rev = agency_session.get(f"{BASE_URL}/api/agency/reports/revenue")
        assert rev.status_code == 200
        assert "by_month" in rev.json()

        perf = agency_session.get(f"{BASE_URL}/api/agency/reports/artist-performance")
        assert perf.status_code == 200
        assert isinstance(perf.json(), list)

        bk = agency_session.get(f"{BASE_URL}/api/agency/reports/bookings").json()
        assert "platform" in bk and "offline" in bk

    def test_calendar(self, agency_session):
        r = agency_session.get(f"{BASE_URL}/api/agency/calendar",
                               params={"from": "2026-01-01", "to": "2027-01-01"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_notifications_read(self, agency_session):
        # Trigger one via event
        agency_session.post(f"{BASE_URL}/api/agency/events", json={
            "title": f"TEST_notif_{uuid.uuid4().hex[:6]}", "event_date": "2026-11-01"
        })
        n = agency_session.get(f"{BASE_URL}/api/agency/notifications").json()
        assert "items" in n and "unread" in n
        if n["items"]:
            nid = n["items"][0]["id"]
            rd = agency_session.post(f"{BASE_URL}/api/agency/notifications/{nid}/read")
            assert rd.status_code == 200


# ═══════════════════════ REGRESSION ═════════════════════════════════════════
class TestRegression:
    def test_artists_search(self):
        r = requests.get(f"{BASE_URL}/api/artists/search")
        assert r.status_code == 200

    def test_bookings_mine(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/bookings/mine")
        assert r.status_code == 200

    def test_auth_me(self, customer_session):
        r = customer_session.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json().get("email") == CUSTOMER[0]

    def test_homepage_spotlight(self):
        r = requests.get(f"{BASE_URL}/api/homepage/spotlight")
        assert r.status_code == 200

    def test_event_planner_suggest(self):
        r = requests.post(f"{BASE_URL}/api/event-planner/suggest",
                          json={"event_type": "Wedding", "city": "Mumbai",
                                "budget": 200000, "guests": 200,
                                "event_date": "2026-12-15"})
        assert r.status_code == 200
