"""Iter 36 — booking special_instructions field E2E.

Verifies:
  * BookingCreate accepts special_instructions
  * The booking doc persists it
  * `is_outstation` still flips correctly for cross-city bookings
  * When absent/blank, the booking still saves cleanly
"""
import os
import pytest
import httpx

BASE = os.environ.get("BOOKTALENT_TEST_URL", "http://localhost:8001") + "/api"


def _login(email: str, password: str) -> str:
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def _priya_setup():
    """Return (customer_token, priya_id, package_id, mandatory_selections)."""
    ctok = _login("customer@booktalent.com", "Customer@123")
    priya_id = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"
    prof = httpx.get(f"{BASE}/artists/{priya_id}", timeout=10).json()
    pkg_id = prof["packages"][0]["id"]
    addons = httpx.get(f"{BASE}/artists/{priya_id}/addons", timeout=10).json()
    mandatory = [{"addon_id": a["id"], "quantity": 1} for a in addons if a.get("is_mandatory")]
    return ctok, priya_id, pkg_id, mandatory


@pytest.mark.parametrize("instructions,city,expected_out", [
    ("Vegetarian meals; green room with mirror; arrival by 4 pm", "Delhi", True),
    ("", "Mumbai", False),
    ("Just show up", "Bombay", False),  # alias-equivalent to Mumbai
])
def test_booking_special_instructions_and_outstation(instructions, city, expected_out):
    ctok, priya_id, pkg_id, mandatory = _priya_setup()
    body = {
        "artist_id": priya_id,
        "package_id": pkg_id,
        "event_date": "2027-06-15",
        "event_time": "18:00",
        "event_type": "Wedding",
        "venue": "Test Venue",
        "city": city,
        "customer_name": "TEST_iter36 SI test",
        "addon_selections": mandatory,
        "special_instructions": instructions,
    }
    r = httpx.post(f"{BASE}/bookings", json=body,
                   headers={"Authorization": f"Bearer {ctok}"}, timeout=15)
    assert r.status_code == 200, r.text
    bid = r.json()["id"]

    read = httpx.get(f"{BASE}/bookings/{bid}",
                     headers={"Authorization": f"Bearer {ctok}"}, timeout=10)
    assert read.status_code == 200
    booking = read.json()["booking"]
    assert booking.get("special_instructions") == instructions.strip()
    assert booking.get("is_outstation") is expected_out


def test_missing_special_instructions_defaults_to_empty():
    """Backwards-compat: existing clients that don't send the field must still work."""
    ctok, priya_id, pkg_id, mandatory = _priya_setup()
    r = httpx.post(f"{BASE}/bookings", json={
        "artist_id": priya_id, "package_id": pkg_id,
        "event_date": "2027-06-15", "event_time": "18:00",
        "event_type": "Wedding", "venue": "Test", "city": "Mumbai",
        "customer_name": "TEST_iter36 no-SI",
        "addon_selections": mandatory,
    }, headers={"Authorization": f"Bearer {ctok}"}, timeout=15)
    assert r.status_code == 200
    bid = r.json()["id"]
    read = httpx.get(f"{BASE}/bookings/{bid}",
                     headers={"Authorization": f"Bearer {ctok}"}, timeout=10).json()
    assert read["booking"].get("special_instructions", "") == ""
