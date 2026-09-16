"""Iter 92 backend tests — admin analytics, public trust stats, notification prefs."""
import os
import pytest
import requests

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    return url.rstrip("/")


BASE_URL = _load_backend_url()
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

ADMIN_EMAIL = "admin@booktalent.com"
ADMIN_PASS = "Admin@123"
ARTIST_EMAIL = "priya@booktalent.com"
ARTIST_PASS = "Artist@123"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def artist():
    return _login(ARTIST_EMAIL, ARTIST_PASS)


# ── Admin analytics ─────────────────────────────────
def test_kpis(admin):
    r = admin.get(f"{BASE_URL}/api/admin/analytics/kpis?days=30")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["period_days", "gmv", "net_platform_revenue", "gst_collected", "bookings",
              "completed_events", "avg_booking_value", "active_artists",
              "verified_artists_total", "new_customers", "new_artists",
              "leads_new", "leads_won", "conversion_pct"]:
        assert k in d, f"missing key {k}"
    assert d["period_days"] == 30


def test_funnel(admin):
    r = admin.get(f"{BASE_URL}/api/admin/analytics/funnel")
    assert r.status_code == 200
    d = r.json()
    assert "stages" in d and len(d["stages"]) == 6
    labels = [s["label"] for s in d["stages"]]
    assert labels == ["Leads", "Quoted", "Bookings Created", "Confirmed", "Paid", "Completed Events"]
    for s in d["stages"]:
        assert "count" in s and "conversion_from_prev" in s


def test_churn(admin):
    r = admin.get(f"{BASE_URL}/api/admin/analytics/churn")
    assert r.status_code == 200
    d = r.json()
    for k in ["last_month_active", "this_month_active", "retained", "churned", "churn_pct"]:
        assert k in d


def test_daily_fills_gaps(admin):
    r = admin.get(f"{BASE_URL}/api/admin/analytics/daily?days=7")
    assert r.status_code == 200
    d = r.json()
    assert "series" in d
    # days=7 -> 8 entries (range(days,-1,-1))
    assert len(d["series"]) == 8
    for row in d["series"]:
        assert "date" in row and "gmv" in row and "bookings" in row


def test_admin_endpoints_403_for_non_admin(artist):
    for path in ["/api/admin/analytics/kpis", "/api/admin/analytics/funnel",
                 "/api/admin/analytics/churn", "/api/admin/analytics/daily"]:
        r = artist.get(f"{BASE_URL}{path}")
        assert r.status_code in (401, 403), f"{path} returned {r.status_code}"


# ── Public trust stats ─────────────────────────────
def test_trust_stats_no_auth():
    r = requests.get(f"{BASE_URL}/api/public/trust-stats")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["verified_artists", "completed_events", "cities_served",
              "top_cities", "avg_rating", "total_reviews", "total_bookings"]:
        assert k in d
    assert isinstance(d["top_cities"], list)
    assert len(d["top_cities"]) <= 10


# ── Notification preferences ───────────────────────
def test_get_prefs(artist):
    r = artist.get(f"{BASE_URL}/api/user/notification-preferences")
    assert r.status_code == 200
    d = r.json()
    assert "preferences" in d and "force_on_events" in d
    assert len(d["preferences"]) == 10
    assert len(d["force_on_events"]) == 6
    force_on = set(d["force_on_events"])
    assert force_on == {"booking.confirmed", "payment.received", "payout.released",
                        "kyc.approved", "kyc.rejected", "kyc.needs_resubmission"}
    # Ensure force_on flag present on relevant rows
    assert d["preferences"]["booking.confirmed"]["force_on"] is True
    assert d["preferences"]["marketing.digest"]["force_on"] is False


def test_patch_prefs_ignores_force_on(artist):
    body = {"preferences": {
        "marketing.digest": {"whatsapp": False, "email": False},
        "booking.confirmed": {"whatsapp": False},
    }}
    r = artist.patch(f"{BASE_URL}/api/user/notification-preferences", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["saved_events"] == ["marketing.digest"], f"saved_events unexpected: {d['saved_events']}"

    # Verify persistence
    r2 = artist.get(f"{BASE_URL}/api/user/notification-preferences")
    prefs = r2.json()["preferences"]
    assert prefs["marketing.digest"]["whatsapp"] is False
    assert prefs["marketing.digest"]["email"] is False
    # booking.confirmed force_on -> ignored, remains True
    assert prefs["booking.confirmed"]["whatsapp"] is True
