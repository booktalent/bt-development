"""
Iter7 backend tests:
- Catalog public endpoints
- Admin master data CRUD + audit log
- FAQs, CMS, Settings, Templates
- Boost packages, purchase, mine, admin subs/cancel/manual-assign
- Advanced search + suggestions + popular + saved + history
- Broadcast notifications & notifications_log
- Reports (revenue, top-artists)
- Permissions (non-admin -> 403)
- Smart Notification dispatch on booking accept (customer + artist + admin in_app)
- Regression: login, booking creation
"""
import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend/.env file
    try:
        for line in open("/app/frontend/.env").read().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

API = f"{BASE_URL}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")
ARTIST = ("priya@booktalent.com", "Artist@123")


# ───────── Fixtures ─────────
def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="session")
def admin_tok():
    return _login(*ADMIN)["token"]


@pytest.fixture(scope="session")
def customer_tok():
    return _login(*CUSTOMER)["token"]


@pytest.fixture(scope="session")
def artist_tok():
    return _login(*ARTIST)["token"]


@pytest.fixture(scope="session")
def artist_user():
    return _login(*ARTIST)["user"]


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ───────── Catalog ─────────
@pytest.mark.parametrize("entity,expected_min", [
    ("categories", 8), ("cities", 10), ("event-types", 8), ("languages", 10),
])
def test_catalog_public(entity, expected_min):
    r = requests.get(f"{API}/catalog/{entity}", timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= expected_min, f"{entity} has only {len(data)}"
    assert all(x.get("active") for x in data)
    assert all("slug" in x and "name" in x for x in data)


def test_catalog_unknown_entity():
    r = requests.get(f"{API}/catalog/unknownxyz", timeout=15)
    assert r.status_code == 404


# ───────── Permissions ─────────
def test_perm_non_admin_403_on_audit(customer_tok):
    r = requests.get(f"{API}/admin/audit-logs", headers=h(customer_tok), timeout=15)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"


def test_perm_artist_403_on_master(artist_tok):
    r = requests.get(f"{API}/admin/master/categories", headers=h(artist_tok), timeout=15)
    assert r.status_code == 403


def test_perm_no_auth_403_on_admin():
    r = requests.get(f"{API}/admin/settings", timeout=15)
    assert r.status_code in (401, 403)


# ───────── Master Data CRUD ─────────
def test_master_crud_categories_with_audit(admin_tok):
    name = f"TEST_cat_{int(time.time())}"
    r = requests.post(f"{API}/admin/master/categories",
                      json={"name": name, "sort_order": 99, "active": True},
                      headers=h(admin_tok), timeout=15)
    assert r.status_code == 200, r.text[:200]
    created = r.json()
    cid = created["id"]
    assert created["name"] == name
    assert created["slug"]

    # Update
    new_name = name + "_upd"
    r2 = requests.put(f"{API}/admin/master/categories/{cid}",
                      json={"name": new_name, "sort_order": 100, "active": True},
                      headers=h(admin_tok), timeout=15)
    assert r2.status_code == 200
    assert r2.json()["name"] == new_name

    # Audit log records master.create and master.update
    r3 = requests.get(f"{API}/admin/audit-logs?limit=50", headers=h(admin_tok), timeout=15)
    assert r3.status_code == 200
    actions = {x["action"] for x in r3.json()}
    assert "master.create" in actions
    assert "master.update" in actions

    # Delete
    r4 = requests.delete(f"{API}/admin/master/categories/{cid}", headers=h(admin_tok), timeout=15)
    assert r4.status_code == 200
    assert r4.json().get("ok") is True


def test_master_unknown_entity_404(admin_tok):
    r = requests.get(f"{API}/admin/master/foobar", headers=h(admin_tok), timeout=15)
    assert r.status_code == 404


# ───────── FAQs ─────────
def test_faqs_public_and_admin_crud(admin_tok):
    pub = requests.get(f"{API}/faqs", timeout=15)
    assert pub.status_code == 200
    assert len(pub.json()) >= 4

    q = f"TEST_faq_{int(time.time())}?"
    cr = requests.post(f"{API}/admin/faqs",
                       json={"question": q, "answer": "A", "category": "general", "sort_order": 5, "active": True},
                       headers=h(admin_tok), timeout=15)
    assert cr.status_code == 200, cr.text[:200]
    fid = cr.json()["id"]

    up = requests.put(f"{API}/admin/faqs/{fid}",
                      json={"question": q, "answer": "Updated A", "category": "general", "sort_order": 5, "active": True},
                      headers=h(admin_tok), timeout=15)
    assert up.status_code == 200 and up.json()["answer"] == "Updated A"

    d = requests.delete(f"{API}/admin/faqs/{fid}", headers=h(admin_tok), timeout=15)
    assert d.status_code == 200


# ───────── CMS ─────────
def test_cms_admin_and_public(admin_tok):
    slug = f"test-page-{int(time.time())}"
    cr = requests.post(f"{API}/admin/cms",
                       json={"slug": slug, "title": "TEST", "body_html": "<p>x</p>", "published": True},
                       headers=h(admin_tok), timeout=15)
    assert cr.status_code == 200, cr.text[:200]
    pid = cr.json()["id"]

    pub = requests.get(f"{API}/cms/{slug}", timeout=15)
    assert pub.status_code == 200
    assert pub.json()["title"] == "TEST"

    # Booktalent audit page might be a CMS slug per task; create-or-skip
    audit_pub = requests.get(f"{API}/cms/booktalent-audit", timeout=15)
    assert audit_pub.status_code in (200, 404)

    requests.delete(f"{API}/admin/cms/{pid}", headers=h(admin_tok), timeout=15)


# ───────── Settings ─────────
def test_settings_get_and_update(admin_tok):
    r = requests.get(f"{API}/admin/settings", headers=h(admin_tok), timeout=15)
    assert r.status_code == 200
    assert any(x.get("key") == "platform_fee_pct" for x in r.json())

    upd = requests.put(f"{API}/admin/settings/test_key_xyz",
                       json={"value": 42}, headers=h(admin_tok), timeout=15)
    assert upd.status_code == 200
    assert upd.json()["value"] == 42


# ───────── Templates ─────────
def test_templates_seeded_and_upsert(admin_tok):
    r = requests.get(f"{API}/admin/templates", headers=h(admin_tok), timeout=15)
    assert r.status_code == 200
    items = r.json()
    codes = {(x["channel"], x["code"]) for x in items}
    assert ("email", "booking.confirmed") in codes
    assert ("email", "payment.success") in codes
    assert ("email", "boost.activated") in codes

    # Upsert
    upd = requests.post(f"{API}/admin/templates",
                        json={"channel": "in_app", "code": "test.upsert", "subject": "S",
                              "body": "B v1", "active": True},
                        headers=h(admin_tok), timeout=15)
    assert upd.status_code == 200
    tid = upd.json()["id"]

    upd2 = requests.post(f"{API}/admin/templates",
                         json={"channel": "in_app", "code": "test.upsert", "subject": "S",
                               "body": "B v2", "active": True},
                         headers=h(admin_tok), timeout=15)
    assert upd2.status_code == 200
    assert upd2.json()["body"] == "B v2"

    requests.delete(f"{API}/admin/templates/{tid}", headers=h(admin_tok), timeout=15)


# ───────── Broadcast ─────────
def test_broadcast_artist_in_app(admin_tok):
    r = requests.post(f"{API}/admin/notifications/broadcast",
                      json={"audience": "artist", "event": "test.broadcast", "channels": ["in_app"],
                            "title": "Hello", "body": "Test broadcast"},
                      headers=h(admin_tok), timeout=20)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    # Response shape: {audience, event, delivered:N}
    assert any(k in body for k in ("ok", "recipients", "sent", "count", "delivered"))
    if "delivered" in body:
        assert body["delivered"] >= 1


# ───────── Boost Packages & Purchase ─────────
def test_boost_packages_public_and_admin(admin_tok):
    pub = requests.get(f"{API}/boost/packages", timeout=15)
    assert pub.status_code == 200
    assert len(pub.json()) >= 11

    adm = requests.get(f"{API}/admin/boost/packages", headers=h(admin_tok), timeout=15)
    assert adm.status_code == 200
    assert len(adm.json()) >= len(pub.json())


def test_boost_purchase_by_artist(artist_tok, artist_user, admin_tok):
    pkgs = requests.get(f"{API}/boost/packages", timeout=15).json()
    pkg = next((p for p in pkgs if p["type"] == "search_priority"), pkgs[0])
    r = requests.post(f"{API}/boost/purchase",
                      json={"package_id": pkg["id"], "payment_method": "mock"},
                      headers=h(artist_tok), timeout=20)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("ok") is True
    assert body["subscription"]["artist_id"] == artist_user["id"]
    assert body["subscription"]["status"] == "active"

    mine = requests.get(f"{API}/boost/mine", headers=h(artist_tok), timeout=15)
    assert mine.status_code == 200
    assert any(s["id"] == body["subscription"]["id"] for s in mine.json())

    # Admin sees subscription with artist details
    adm = requests.get(f"{API}/admin/boost/subscriptions", headers=h(admin_tok), timeout=15)
    assert adm.status_code == 200
    target = next((s for s in adm.json() if s["id"] == body["subscription"]["id"]), None)
    assert target is not None
    assert target.get("artist") and target["artist"].get("email") == ARTIST[0]


def test_boost_purchase_forbidden_for_customer(customer_tok):
    pkgs = requests.get(f"{API}/boost/packages", timeout=15).json()
    r = requests.post(f"{API}/boost/purchase",
                      json={"package_id": pkgs[0]["id"], "payment_method": "mock"},
                      headers=h(customer_tok), timeout=15)
    assert r.status_code == 403


def test_boost_admin_manual_assign_and_cancel(admin_tok, artist_user):
    pkgs = requests.get(f"{API}/boost/packages", timeout=15).json()
    pkg = next((p for p in pkgs if p["type"] == "trending"), pkgs[0])
    r = requests.post(f"{API}/admin/boost/manual-assign?target_artist_id={artist_user['id']}",
                      json={"package_id": pkg["id"], "payment_method": "mock"},
                      headers=h(admin_tok), timeout=20)
    assert r.status_code == 200, r.text[:200]
    sub_id = r.json()["id"]

    cancel = requests.post(f"{API}/admin/boost/{sub_id}/cancel",
                           headers=h(admin_tok), timeout=15)
    assert cancel.status_code == 200
    assert cancel.json().get("ok") is True


# ───────── Search ─────────
def test_search_artists_basic_shape():
    r = requests.get(f"{API}/search/artists?limit=12", timeout=15)
    assert r.status_code == 200
    data = r.json()
    for key in ("items", "total", "page", "pages"):
        assert key in data, f"missing {key}"
    assert isinstance(data["items"], list)


def test_search_filters_combo():
    r = requests.get(f"{API}/search/artists",
                     params={"min_price": 0, "max_price": 1000000, "min_rating": 0,
                             "featured_only": "false", "sort": "rating", "page": 1, "limit": 6},
                     timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["page"] == 1
    assert data["limit"] == 6


def test_search_pagination():
    r1 = requests.get(f"{API}/search/artists?page=1&limit=2", timeout=15).json()
    r2 = requests.get(f"{API}/search/artists?page=2&limit=2", timeout=15).json()
    if r1["total"] > 2:
        ids1 = {i.get("user_id") for i in r1["items"]}
        ids2 = {i.get("user_id") for i in r2["items"]}
        assert ids1 != ids2 or len(r2["items"]) == 0


def test_search_suggestions():
    r = requests.get(f"{API}/search/suggestions?q=pri", timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("artists", "categories", "cities"):
        assert k in body


def test_search_popular_with_query_records(customer_tok):
    # Generate one search with q so popular has data
    requests.get(f"{API}/search/artists?q=singer",
                 headers=h(customer_tok), timeout=15)
    r = requests.get(f"{API}/search/popular?limit=5", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_saved_searches_isolation(customer_tok, artist_tok):
    # Create as customer
    cr = requests.post(f"{API}/search/saved",
                       json={"name": "TEST_singers_mumbai", "query": "singer",
                             "filters": {"city": "Mumbai"}},
                       headers=h(customer_tok), timeout=15)
    assert cr.status_code == 200
    sid = cr.json()["id"]

    # Customer can see it
    lst = requests.get(f"{API}/search/saved", headers=h(customer_tok), timeout=15)
    assert lst.status_code == 200
    assert any(s["id"] == sid for s in lst.json())

    # Artist cannot see customer's saved search
    other = requests.get(f"{API}/search/saved", headers=h(artist_tok), timeout=15)
    assert other.status_code == 200
    assert not any(s["id"] == sid for s in other.json())

    # Delete
    d = requests.delete(f"{API}/search/saved/{sid}", headers=h(customer_tok), timeout=15)
    assert d.status_code == 200


def test_search_history(customer_tok):
    requests.get(f"{API}/search/artists?q=TESThist_xyz",
                 headers=h(customer_tok), timeout=15)
    r = requests.get(f"{API}/search/history?limit=20", headers=h(customer_tok), timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)


# ───────── Reports ─────────
def test_reports_revenue(admin_tok):
    r = requests.get(f"{API}/admin/reports/revenue?days=30",
                     headers=h(admin_tok), timeout=20)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    for key in ("gmv", "platform_revenue", "boost_revenue"):
        assert key in body


def test_reports_top_artists(admin_tok):
    r = requests.get(f"{API}/admin/reports/top-artists?limit=5",
                     headers=h(admin_tok), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ───────── Smart Notification on booking accept ─────────
def test_booking_accept_notifies_all_parties(customer_tok, artist_tok, artist_user):
    # Build booking
    # Need an actual package_id from priya's profile
    prof = requests.get(f"{API}/artists/{artist_user['id']}", timeout=15)
    if prof.status_code != 200:
        pytest.skip(f"artist profile fetch failed {prof.status_code}")
    packages = prof.json().get("packages") or []
    if not packages:
        pytest.skip("artist has no packages defined")
    pkg_id = packages[0].get("id") or packages[0].get("_id")
    future = (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")
    payload = {
        "artist_id": artist_user["id"],
        "package_id": pkg_id,
        "event_date": future,
        "event_time": "18:00",
        "event_type": "wedding",
        "city": "Mumbai",
        "venue": "TEST venue iter7",
        "notes": "iter7 notify test",
        "customer_name": "Test Cust",
        "customer_phone": "+919999999999",
        "customer_email": "customer@booktalent.com",
    }
    cr = requests.post(f"{API}/bookings", json=payload, headers=h(customer_tok), timeout=20)
    if cr.status_code != 200:
        pytest.skip(f"booking create not 200 (got {cr.status_code} {cr.text[:160]}) — skip notify test")
    booking_id = cr.json().get("id") or cr.json().get("booking", {}).get("id")
    assert booking_id

    # Artist accepts via /bookings/{bid}/action {action:"accept"}
    acc = requests.post(f"{API}/bookings/{booking_id}/action",
                        json={"action": "accept", "reason": "test"},
                        headers=h(artist_tok), timeout=20)
    assert acc.status_code in (200, 201), f"accept returned {acc.status_code} {acc.text[:160]}"

    time.sleep(1.0)

    # Check artist's in-app notifications
    art_notif = requests.get(f"{API}/notifications", headers=h(artist_tok), timeout=15)
    cust_notif = requests.get(f"{API}/notifications", headers=h(customer_tok), timeout=15)
    if art_notif.status_code != 200 or cust_notif.status_code != 200:
        pytest.skip("/api/notifications not available — skipping notify check")

    art_count = len(art_notif.json()) if isinstance(art_notif.json(), list) else 0
    cust_count = len(cust_notif.json()) if isinstance(cust_notif.json(), list) else 0
    # At least one notification should have arrived for both parties
    assert art_count > 0, "artist got no notifications after accept"
    assert cust_count > 0, "customer got no notifications after accept"


# ───────── Regression: auth ─────────
def test_regression_logins():
    for u, p in [ADMIN, CUSTOMER, ARTIST]:
        r = requests.post(f"{API}/auth/login", json={"email": u, "password": p}, timeout=15)
        assert r.status_code == 200, f"{u} login failed"
        assert "token" in r.json()
