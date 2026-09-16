"""
Iter 60 regression tests for the P0 booking bug fixes:
- Batch booking contract (multi-artist checkout)
- Pydantic schema drift check: guests as INT must 422
- tnc_accepted=False on batch must 400 with the friendly message
- Booking ref shape BT-YYMMDD-XXXXXX
- /payments/verify returns pending_artist status
"""
import os
import datetime as dt
import re
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
KAVYA = "aa0ed1cb-6036-480d-a64f-6cc551a2a306"
PRIYA = "22c3967c-e432-41e8-bdfb-a0a54b82ee1b"
MOHIT = "4f7a1208-8248-4f39-b5bf-bd0526859d58"


@pytest.fixture(scope="module")
def customer():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={
        "email": "customer@booktalent.com", "password": "Customer@123",
    })
    assert r.status_code == 200, r.text
    return s


def _pkg(session, artist_id):
    r = session.get(f"{API}/artists/{artist_id}")
    assert r.status_code == 200, r.text
    pkgs = r.json().get("packages", [])
    assert pkgs, f"no packages for {artist_id}"
    return pkgs[0]["id"]


def _addon_selections(session, artist_id):
    """Auto-select mandatory addons so batch/single doesn't 400 for Priya."""
    r = session.get(f"{API}/artists/{artist_id}/addons")
    if r.status_code != 200:
        return []
    return [
        {"addon_id": a["id"], "quantity": 1}
        for a in r.json() or []
        if a.get("is_mandatory")
    ]


def _common_fields(future_date):
    return {
        "event_date": future_date,
        "event_time": "19:00",
        "event_type": "Wedding",
        "venue": "TEST Grand Hyatt",
        "city": "Mumbai",
        "guests": "300-600",             # STRING per Pydantic schema
        "language_pref": "Hindi",
        "notes": "iter60",
        "special_instructions": "",
        "customer_name": "TEST Iter60",
        "customer_phone": "+919000000060",
        "customer_email": "customer@booktalent.com",
        "customer_travel_allowance": 0,
        "tnc_accepted": True,
    }


# --- REGRESSION 2 — schema drift check: guests must be string ---
def test_guests_as_int_returns_422(customer):
    pkg_id = _pkg(customer, KAVYA)
    future = (dt.date.today() + dt.timedelta(days=61)).isoformat()
    payload = {
        "artist_id": KAVYA,
        "package_id": pkg_id,
        "addons": [],
        "addon_selections": [],
        **_common_fields(future),
        "guests": 150,   # <-- INT should trip Pydantic validation
    }
    r = customer.post(f"{API}/bookings", json=payload)
    assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text[:300]}"


# --- REGRESSION 3 — batch tnc_accepted=false returns 400 ---
def test_batch_tnc_false_rejected(customer):
    pkg_p = _pkg(customer, PRIYA)
    pkg_m = _pkg(customer, MOHIT)
    future = (dt.date.today() + dt.timedelta(days=62)).isoformat()
    common = _common_fields(future)
    common["tnc_accepted"] = False   # <-- reject condition
    items = [
        {"artist_id": PRIYA, "package_id": pkg_p, "addons": [],
         "addon_selections": _addon_selections(customer, PRIYA), **common},
        {"artist_id": MOHIT, "package_id": pkg_m, "addons": [],
         "addon_selections": _addon_selections(customer, MOHIT), **common},
    ]
    r = customer.post(f"{API}/bookings/batch", json={"items": items})
    assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:300]}"
    body = r.json()
    detail = (body.get("detail") or "").lower()
    assert "terms" in detail or "t&c" in detail or "tnc" in detail, f"unexpected detail: {body}"


# --- REGRESSION 4 — full happy path single + batch flows via API ---
BOOKING_REF_RE = re.compile(r"^BT-\d{6}-[A-Z0-9]{6}$")


def test_single_artist_happy_path(customer):
    pkg_id = _pkg(customer, KAVYA)
    future = (dt.date.today() + dt.timedelta(days=63)).isoformat()
    payload = {
        "artist_id": KAVYA,
        "package_id": pkg_id,
        "addons": [],
        "addon_selections": [],
        **_common_fields(future),
    }
    rb = customer.post(f"{API}/bookings", json=payload)
    assert rb.status_code in (200, 201), rb.text
    booking = rb.json()
    ri = customer.post(f"{API}/payments/init", json={
        "booking_id": booking["id"], "method": "card",
    })
    assert ri.status_code == 200, ri.text
    init = ri.json()
    rv = customer.post(f"{API}/payments/verify", json={
        "booking_id": booking["id"],
        "payment_id": init.get("payment_id"),
        "mock_otp": "123456",
    })
    assert rv.status_code == 200, rv.text
    v = rv.json()
    ref = v.get("booking_ref") or booking.get("ref")
    assert ref and BOOKING_REF_RE.match(ref), f"bad ref shape: {ref}"

    # verify final booking state
    rf = customer.get(f"{API}/bookings/{booking['id']}")
    assert rf.status_code == 200, rf.text
    final = rf.json()
    final = final.get("booking", final)
    assert final["status"] == "pending_artist"
    assert final["payment_status"] == "token_paid"


def test_batch_artist_happy_path(customer):
    pkg_p = _pkg(customer, PRIYA)
    pkg_m = _pkg(customer, MOHIT)
    future = (dt.date.today() + dt.timedelta(days=64)).isoformat()
    common = _common_fields(future)
    items = [
        {"artist_id": PRIYA, "package_id": pkg_p, "addons": [],
         "addon_selections": _addon_selections(customer, PRIYA), **common},
        {"artist_id": MOHIT, "package_id": pkg_m, "addons": [],
         "addon_selections": _addon_selections(customer, MOHIT), **common},
    ]
    rb = customer.post(f"{API}/bookings/batch", json={"items": items})
    assert rb.status_code in (200, 201), rb.text
    body = rb.json()
    assert body.get("event_id"), f"no event_id in batch response: {body}"
    booking_ids = body.get("booking_ids") or []
    assert len(booking_ids) == 2, f"expected 2 bookings, got {len(booking_ids)}"
    refs = body.get("booking_refs") or []
    assert len(refs) == 2
    for ref in refs:
        assert BOOKING_REF_RE.match(ref), f"bad ref shape: {ref}"

    # init + verify
    ri = customer.post(f"{API}/payments/batch/init", json={
        "booking_ids": booking_ids, "method": "card",
    })
    assert ri.status_code == 200, ri.text
    init = ri.json()
    rv = customer.post(f"{API}/payments/batch/verify", json={
        "payment_id": init.get("payment_id"),
        "booking_ids": booking_ids,
        "mock_otp": "123456",
    })
    assert rv.status_code == 200, rv.text
    v = rv.json()
    assert v.get("count") == 2
    v_refs = v.get("booking_refs") or []
    assert len(v_refs) == 2 and all(BOOKING_REF_RE.match(r) for r in v_refs)

    # each booking must be pending_artist / token_paid
    for bid in booking_ids:
        rf = customer.get(f"{API}/bookings/{bid}")
        assert rf.status_code == 200, rf.text
        final = rf.json()
        final = final.get("booking", final)
        assert final["status"] == "pending_artist"
        assert final["payment_status"] == "token_paid"
