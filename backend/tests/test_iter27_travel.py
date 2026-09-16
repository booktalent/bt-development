"""
Sprint 4 — Travel & Accommodation — Backend API tests (iter27).

Covers:
 - PUT /api/packages/{pid} — new travel fields persist round-trip
 - Booking captures travel_requirements snapshot from package at booking time
 - Business math regression: pricing.total = round(artist_fee*0.05) + round(artist_fee*0.05*0.18)
   (Travel does NOT get added to total — customer-borne)
 - Travel snapshot immutability (package edited after booking → old snapshot unchanged)
"""
from __future__ import annotations

import os
import datetime as dt
import uuid
import pytest
import requests


def _load_env():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("REACT_APP_BACKEND_URL"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("REACT_APP_BACKEND_URL")


BASE_URL = _load_env().rstrip("/")
API = f"{BASE_URL}/api"

PRIYA_ID = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"
PRIYA_EMAIL, PRIYA_PW = "priya@booktalent.com", "Artist@123"
CUST_EMAIL, CUST_PW = "customer@booktalent.com", "Customer@123"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {email} failed → {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


@pytest.fixture(scope="module")
def artist_ctx():
    tok, u = _login(PRIYA_EMAIL, PRIYA_PW)
    return {"token": tok, "user": u, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def customer_ctx():
    tok, u = _login(CUST_EMAIL, CUST_PW)
    return {"token": tok, "user": u, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def cleanup_mandatory(artist_ctx):
    """Ensure no mandatory add-on interferes — flip Priya's mandatory addons off for this run."""
    r = requests.get(f"{API}/artist/addons", headers=artist_ctx["h"], timeout=15)
    saved_ids = []
    if r.status_code == 200:
        for a in r.json():
            if a.get("is_mandatory"):
                requests.patch(f"{API}/artist/addons/{a['id']}",
                               json={"is_mandatory": False},
                               headers=artist_ctx["h"], timeout=15)
                saved_ids.append(a["id"])
    yield
    # restore
    for aid in saved_ids:
        requests.patch(f"{API}/artist/addons/{aid}",
                       json={"is_mandatory": True},
                       headers=artist_ctx["h"], timeout=15)


@pytest.fixture(scope="module")
def test_package(artist_ctx):
    """Create a dedicated TEST package for this run + delete at teardown."""
    payload = {
        "name": "TEST_Sprint4_Pkg",
        "description": "Test package for travel/accom fields",
        "price": 100000,
        "duration": "2 hours",
        "features": ["live band"],
        "is_popular": False,
    }
    r = requests.post(f"{API}/packages", json=payload, headers=artist_ctx["h"], timeout=15)
    assert r.status_code == 200, r.text
    pkg = r.json()
    yield pkg
    requests.delete(f"{API}/packages/{pkg['id']}", headers=artist_ctx["h"], timeout=15)


def _future_date(n=45):
    return (dt.date.today() + dt.timedelta(days=n + int(uuid.uuid4().int % 20))).isoformat()


# ─── PACKAGE TRAVEL FIELDS ROUNDTRIP ─────────────────────────────────────────
class TestPackageTravelFieldsUpdate:
    def test_update_package_with_all_travel_fields(self, artist_ctx, test_package):
        pid = test_package["id"]
        payload = {
            "name": "TEST_Sprint4_Pkg",
            "description": "Test package for travel/accom fields",
            "price": 100000,
            "duration": "2 hours",
            "features": ["live band"],
            "is_popular": False,
            "travel_required": True,
            "accommodation_required": True,
            "hotel_category": "5-star",
            "flight_class": "business",
            "team_size": 4,
            "arrival_buffer_days": 1,
            "local_transport_required": True,
            "meals_required": True,
            "travel_notes": "Vegetarian meals only",
        }
        r = requests.put(f"{API}/packages/{pid}", json=payload, headers=artist_ctx["h"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Verify persistence via public GET /artists/{user_id}
        r2 = requests.get(f"{API}/artists/{PRIYA_ID}", timeout=15)
        assert r2.status_code == 200, r2.text
        pkg = next((p for p in r2.json().get("packages", []) if p["id"] == pid), None)
        assert pkg is not None
        assert pkg["travel_required"] is True
        assert pkg["accommodation_required"] is True
        assert pkg["hotel_category"] == "5-star"
        assert pkg["flight_class"] == "business"
        assert pkg["team_size"] == 4
        assert pkg["arrival_buffer_days"] == 1
        assert pkg["local_transport_required"] is True
        assert pkg["meals_required"] is True
        assert pkg["travel_notes"] == "Vegetarian meals only"


# ─── BOOKING SNAPSHOT ────────────────────────────────────────────────────────
class TestBookingTravelSnapshot:
    def test_booking_captures_travel_requirements(self, customer_ctx, test_package, cleanup_mandatory):
        pid = test_package["id"]
        payload = {
            "artist_id": PRIYA_ID,
            "package_id": pid,
            "event_date": _future_date(60),
            "event_time": "19:00",
            "event_type": "wedding",
            "venue": "TEST Grand Ballroom",
            "city": "Mumbai",
            "notes": "TEST booking iter27 travel",
        }
        r = requests.post(f"{API}/bookings", json=payload, headers=customer_ctx["h"], timeout=20)
        assert r.status_code == 200, r.text
        b = r.json()
        tr = b.get("travel_requirements")
        assert tr is not None, "travel_requirements missing on booking"
        assert tr["travel_required"] is True
        assert tr["accommodation_required"] is True
        assert tr["hotel_category"] == "5-star"
        assert tr["flight_class"] == "business"
        assert tr["team_size"] == 4
        assert tr["arrival_buffer_days"] == 1
        assert tr["local_transport_required"] is True
        assert tr["meals_required"] is True
        assert tr["travel_notes"] == "Vegetarian meals only"

        # stash for GET verification
        customer_ctx["_iter27_booking_id"] = b["id"]
        customer_ctx["_iter27_pricing"] = b["pricing"]

    def test_get_booking_returns_travel_requirements(self, customer_ctx):
        bid = customer_ctx.get("_iter27_booking_id")
        assert bid
        r = requests.get(f"{API}/bookings/{bid}", headers=customer_ctx["h"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        booking = body.get("booking", body)
        tr = booking.get("travel_requirements")
        assert tr is not None
        assert tr["flight_class"] == "business"
        assert tr["hotel_category"] == "5-star"
        assert tr["team_size"] == 4


# ─── BUSINESS MATH REGRESSION (travel NOT added to total) ────────────────────
class TestPricingMathRegression:
    def test_travel_does_not_affect_total(self, customer_ctx, test_package):
        """
        Pkg price = 100000, no addons, no coupon.
        artist_fee = 100000, platform_fee = 5000, gst = 900, total = 5900.
        Travel/accommodation MUST NOT be added into `total`.
        """
        pricing = customer_ctx.get("_iter27_pricing")
        assert pricing is not None
        assert pricing["artist_fee"] == 100000.0
        assert pricing["platform_fee"] == round(100000 * 0.05, 2)  # 5000
        assert pricing["gst"] == round(pricing["platform_fee"] * 0.18, 2)  # 900
        assert pricing["total"] == round(pricing["platform_fee"] + pricing["gst"], 2)  # 5900
        assert pricing["total"] == 5900
        # travel keys should NOT bleed into pricing
        for k in ("travel_required", "accommodation_required", "hotel_category",
                  "flight_class", "team_size"):
            assert k not in pricing, f"travel field {k} leaked into pricing"


# ─── SNAPSHOT IMMUTABILITY ───────────────────────────────────────────────────
class TestTravelSnapshotImmutability:
    def test_package_edit_after_booking_does_not_alter_history(self, artist_ctx, customer_ctx, test_package):
        pid = test_package["id"]
        bid = customer_ctx.get("_iter27_booking_id")
        assert bid

        # Change package travel fields
        payload = {
            "name": "TEST_Sprint4_Pkg",
            "description": "Test package for travel/accom fields",
            "price": 100000,
            "duration": "2 hours",
            "features": ["live band"],
            "is_popular": False,
            "travel_required": False,           # flipped
            "accommodation_required": False,    # flipped
            "hotel_category": "3-star",         # changed
            "flight_class": "economy",          # changed
            "team_size": 1,
            "arrival_buffer_days": 0,
            "local_transport_required": False,
            "meals_required": False,
            "travel_notes": "",
        }
        r = requests.put(f"{API}/packages/{pid}", json=payload, headers=artist_ctx["h"], timeout=15)
        assert r.status_code == 200, r.text

        # existing booking must still reflect original snapshot
        r2 = requests.get(f"{API}/bookings/{bid}", headers=customer_ctx["h"], timeout=15)
        booking = r2.json().get("booking", r2.json())
        tr = booking.get("travel_requirements")
        assert tr["flight_class"] == "business", f"snapshot mutated → {tr}"
        assert tr["hotel_category"] == "5-star"
        assert tr["team_size"] == 4


# ─── EMPTY/NEUTRAL TRAVEL PACKAGE (regression) ───────────────────────────────
class TestPackageWithoutTravel:
    def test_package_defaults_are_falsy(self, artist_ctx, customer_ctx, cleanup_mandatory):
        # Create a NEW package with no travel fields set
        payload = {
            "name": "TEST_NoTravel_Pkg",
            "description": "simple",
            "price": 50000,
            "duration": "1 hour",
            "features": [],
            "is_popular": False,
        }
        r = requests.post(f"{API}/packages", json=payload, headers=artist_ctx["h"], timeout=15)
        assert r.status_code == 200
        pkg = r.json()
        try:
            assert pkg.get("travel_required") is False
            assert pkg.get("accommodation_required") is False
            assert pkg.get("hotel_category") in (None, "")
            assert pkg.get("flight_class") in (None, "")

            # Book it
            payload_b = {
                "artist_id": PRIYA_ID,
                "package_id": pkg["id"],
                "event_date": _future_date(120),
                "event_time": "18:00",
                "event_type": "corporate",
                "venue": "TEST Office",
                "city": "Bengaluru",
            }
            r2 = requests.post(f"{API}/bookings", json=payload_b, headers=customer_ctx["h"], timeout=20)
            assert r2.status_code == 200, r2.text
            b = r2.json()
            tr = b.get("travel_requirements")
            assert tr is not None
            assert tr["travel_required"] is False
            assert tr["accommodation_required"] is False

            # Math: 50000 artist fee → 2500 platform → 450 gst → 2950 total
            pr = b["pricing"]
            assert pr["artist_fee"] == 50000.0
            assert pr["platform_fee"] == 2500.0
            assert pr["gst"] == 450.0
            assert pr["total"] == 2950.0
        finally:
            requests.delete(f"{API}/packages/{pkg['id']}", headers=artist_ctx["h"], timeout=15)
