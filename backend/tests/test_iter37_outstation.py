"""Iter 37 — Outstation notice / clause / fee-note content + admin edit round-trip + booking regression."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")

ADMIN = {"email": "admin@booktalent.com", "password": "Admin@123"}
CUST = {"email": "customer@booktalent.com", "password": "Customer@123"}
PRIYA_ID = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"

EXPECTED_LEN = {"outstation_notice": 455, "outstation_clause": 479, "booking_fee_note": 311}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def cust_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=CUST, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


# -- Settings content --
class TestSettingsContent:
    def test_public_returns_all_three_keys_with_expected_lengths(self):
        r = requests.get(f"{BASE_URL}/api/settings/public", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k, expected in EXPECTED_LEN.items():
            assert k in d, f"{k} missing from public settings"
            assert len(d[k]) == expected, f"{k} length {len(d[k])} != {expected}"

    def test_outstation_notice_content(self):
        d = requests.get(f"{BASE_URL}/api/settings/public").json()
        n = d["outstation_notice"]
        assert "Travel, accommodation, local transportation, meals, hospitality" in n
        assert "accompanying team members, musicians, assistants, technicians" in n
        assert "{artist_city}" not in n
        assert "{event_city}" not in n

    def test_outstation_clause_content(self):
        d = requests.get(f"{BASE_URL}/api/settings/public").json()
        c = d["outstation_clause"]
        assert c.startswith("OUTSTATION LOGISTICS CLAUSE")
        assert "Artist Performance Fee or the Platform Service Fee" in c
        assert "accompanying team members" in c[-300:]

    def test_booking_fee_note_no_old_copy(self):
        d = requests.get(f"{BASE_URL}/api/settings/public").json()
        f = d["booking_fee_note"]
        # New copy references accompanying team; must not have old placeholder copy
        assert "accompanying team members" in f
        assert "discussed and managed directly" not in f
        assert "{artist_city}" not in f and "{event_city}" not in f


# -- Admin edit round-trip --
class TestAdminEditRoundtrip:
    def test_admin_can_override_and_restore(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        original = requests.get(f"{BASE_URL}/api/settings/public").json()["outstation_notice"]

        # Override
        r = requests.put(
            f"{BASE_URL}/api/admin/settings/outstation_notice",
            json={"value": "TEST_OVERRIDE_NOTICE_iter37"},
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 200
        after = requests.get(f"{BASE_URL}/api/settings/public").json()["outstation_notice"]
        assert after == "TEST_OVERRIDE_NOTICE_iter37"

        # Restore
        r2 = requests.put(
            f"{BASE_URL}/api/admin/settings/outstation_notice",
            json={"value": original},
            headers=headers,
            timeout=15,
        )
        assert r2.status_code == 200
        restored = requests.get(f"{BASE_URL}/api/settings/public").json()["outstation_notice"]
        assert restored == original
        assert len(restored) == 455


# -- Regression: booking creation with special_instructions + GST math --
class TestBookingRegression:
    def test_booking_create_with_special_instructions_and_gst_math(self, cust_token):
        headers = {"Authorization": f"Bearer {cust_token}"}
        artist = requests.get(f"{BASE_URL}/api/artists/{PRIYA_ID}", timeout=15).json()
        pkg = artist["packages"][0]
        addons = requests.get(f"{BASE_URL}/api/artists/{PRIYA_ID}/addons", timeout=15).json()
        mandatory = [{"addon_id": a["id"], "quantity": 1} for a in addons if a.get("is_mandatory")]
        payload = {
            "artist_id": PRIYA_ID,
            "package_id": pkg["id"],
            "event_date": "2027-06-15",
            "event_time": "18:00",
            "event_type": "Wedding",
            "venue": "TEST_iter37 Venue",
            "city": "Delhi",
            "customer_name": "TEST_iter37 User",
            "addon_selections": mandatory,
            "special_instructions": "TEST_iter37: green room + veg meals",
        }
        r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=headers, timeout=20)
        assert r.status_code == 200, f"Booking create failed: {r.status_code} {r.text}"
        bid = r.json()["id"]
        # Verify special_instructions persisted
        read = requests.get(f"{BASE_URL}/api/bookings/{bid}", headers=headers, timeout=15).json()
        booking = read["booking"]
        assert booking.get("special_instructions") == payload["special_instructions"]
        assert booking.get("is_outstation") is True
        # Verify GST math: platform_fee = 5% of artist_fee (incl mandatory addons); gst = 18% of platform_fee
        artist_fee = booking.get("artist_fee") or booking.get("total_artist_amount")
        platform_fee = booking.get("platform_fee") or booking.get("service_fee")
        gst = booking.get("gst") or booking.get("gst_amount")
        if artist_fee and platform_fee and gst:
            assert abs(platform_fee - round(artist_fee * 0.05)) <= 2, f"platform_fee {platform_fee} not ~5% of {artist_fee}"
            assert abs(gst - round(platform_fee * 0.18)) <= 2, f"gst {gst} not ~18% of {platform_fee}"
