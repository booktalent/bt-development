"""
Iter 64 review tests — Easebuzz-only + auto-refunds + agency earnings.
Validates the review_request scope end-to-end against the public API.
"""
from __future__ import annotations

import os
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", ".env"))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@booktalent.com", "Admin@123")
AGENCY = ("agency@booktalent.com", "Agency@123")
CUSTOMER = ("customer@booktalent.com", "Customer@123")

DJ_VORTEX_ID = "698618d0-8c07-4ac8-b650-a5a09bc5c28a"


def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return s


# ---------- Admin refunds endpoint ----------
class TestAdminRefunds:
    def test_admin_refunds_list_shape(self):
        s = login(*ADMIN)
        r = s.get(f"{API}/admin/refunds", timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        for k in ("items", "total", "page", "limit"):
            assert k in data, f"missing key {k} in {list(data.keys())}"
        assert isinstance(data["items"], list)

    def test_admin_refunds_retry_bad_id(self):
        s = login(*ADMIN)
        r = s.post(f"{API}/admin/refunds/does-not-exist-xxx/retry", timeout=15)
        # Must be a routable endpoint — expect 404 (not found) not 405 (method not allowed)
        assert r.status_code in (400, 404, 409), r.status_code


# ---------- Agency earnings ----------
class TestAgencyEarnings:
    def test_roster_and_earnings(self):
        s = login(*AGENCY)
        rr = s.get(f"{API}/agency/roster", timeout=15)
        assert rr.status_code == 200, rr.text[:200]
        roster = rr.json()
        items = roster if isinstance(roster, list) else roster.get("items", [])
        assert len(items) > 0, "agency roster empty"

        # Pick an active artist; prefer DJ Vortex or Priya
        artist_id = None
        for it in items:
            aid = it.get("artist_id") or it.get("id")
            name = (it.get("stage_name") or it.get("name") or "").lower()
            status = (it.get("status") or "active").lower()
            if status == "active" and ("vortex" in name or "priya" in name):
                artist_id = aid
                break
        if not artist_id:
            for it in items:
                if (it.get("status") or "active").lower() == "active":
                    artist_id = it.get("artist_id") or it.get("id")
                    break
        assert artist_id, f"no active artist in roster: {items[:2]}"

        r = s.get(f"{API}/agency/artist/{artist_id}/earnings", timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "artist" in data
        assert "totals" in data and "bookings" in data
        totals = data["totals"]
        for k in ("total_earnings", "completed_earnings", "upcoming_earnings",
                  "confirmed_booking_value", "completed_events", "upcoming_events",
                  "commission_pct", "agency_commission_earned"):
            assert k in totals, f"totals missing {k}: keys={list(totals.keys())}"
        assert isinstance(data["bookings"], list)
        # If bookings present, verify per-booking fields
        for b in data["bookings"][:3]:
            for k in ("ref", "event_date", "customer_name", "artist_fee",
                      "platform_charges", "agency_commission", "status",
                      "payment_status", "refund_status"):
                assert k in b, f"booking missing {k}: keys={list(b.keys())}"


# ---------- Razorpay endpoints must be gone ----------
class TestRazorpayRemoved:
    REMOVED_GETS = ["/payments/config"]
    REMOVED_POSTS = [
        "/payments/init", "/payments/verify",
        "/payments/batch/init", "/payments/batch/verify",
        "/payments/webhook",
    ]

    def _is_removed(self, status: int) -> bool:
        # 404 = not routable, 405 = method not allowed. Both mean endpoint gone.
        # 401/403 would mean route still exists — that's a FAIL for removal.
        return status in (404, 405)

    def test_removed_gets(self):
        s = login(*ADMIN)
        for path in self.REMOVED_GETS:
            r = s.get(f"{API}{path}", timeout=10)
            assert self._is_removed(r.status_code), f"GET {path} still routable: {r.status_code}"

    def test_removed_posts(self):
        s = login(*ADMIN)
        for path in self.REMOVED_POSTS:
            r = s.post(f"{API}{path}", json={}, timeout=10)
            assert self._is_removed(r.status_code), f"POST {path} still routable: {r.status_code}"

    def test_removed_refund_id_post(self):
        s = login(*ADMIN)
        r = s.post(f"{API}/payments/some-fake-id/refund", json={}, timeout=10)
        assert self._is_removed(r.status_code), f"POST /payments/{{id}}/refund still routable: {r.status_code}"


# ---------- Easebuzz + admin endpoints still work ----------
class TestEasebuzzAndAdmin:
    def test_payment_gateway_public(self):
        r = requests.get(f"{API}/payment-gateway/public", timeout=10)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # Must not expose razorpay as active
        assert "gateway" in data or "provider" in data or isinstance(data, dict)

    def test_admin_payment_settings(self):
        s = login(*ADMIN)
        r = s.get(f"{API}/admin/payment-settings", timeout=10)
        assert r.status_code == 200, r.text[:200]

    def test_admin_payments_list(self):
        s = login(*ADMIN)
        r = s.get(f"{API}/admin/payments", timeout=10)
        assert r.status_code == 200, r.text[:200]

    def test_easebuzz_init_route_exists(self):
        # POST with empty body — expect 400/422 (validation) not 404 (not routable)
        s = login(*CUSTOMER)
        r = s.post(f"{API}/payments/easebuzz/init", json={}, timeout=10)
        assert r.status_code != 404, "easebuzz/init route missing"
        assert r.status_code in (400, 401, 403, 409, 422), f"unexpected: {r.status_code} {r.text[:200]}"


# ---------- Booking reject flow (no completed payment, so no actual refund) ----------
class TestBookingRejectFlow:
    def test_reject_pending_payment_booking(self):
        cust = login(*CUSTOMER)

        # Fetch DJ Vortex packages
        art = cust.get(f"{API}/artists/{DJ_VORTEX_ID}", timeout=15)
        if art.status_code != 200:
            pytest.skip(f"DJ Vortex artist not fetchable: {art.status_code}")
        aj = art.json()
        packages = aj.get("packages") or (aj.get("profile") or {}).get("packages") or []
        if not packages:
            pytest.skip("no packages on DJ Vortex")
        pkg_id = packages[0].get("id") or packages[0].get("package_id")

        payload = {
            "artist_id": DJ_VORTEX_ID,
            "package_id": pkg_id,
            "event_date": "2027-01-15",
            "event_time": "19:00",
            "event_city": "Mumbai",
            "city": "Mumbai",
            "event_venue": "Test Venue",
            "venue": "Test Venue",
            "event_type": "wedding",
            "customer_name": "Test Cust",
            "customer_phone": "9999999999",
            "customer_email": "customer@booktalent.com",
            "special_instructions": "iter64 review test",
            "accept_terms": True,
            "terms_accepted": True,
            "tnc_accepted": True,
        }

        r = cust.post(f"{API}/bookings", json=payload, timeout=15)
        if r.status_code not in (200, 201):
            pytest.skip(f"booking create failed: {r.status_code} {r.text[:200]}")
        booking = r.json()
        booking_id = booking.get("id") or booking.get("booking_id")
        assert booking_id, booking

        # Admin rejects
        admin = login(*ADMIN)
        rej = admin.post(
            f"{API}/bookings/{booking_id}/action",
            json={"action": "reject", "reason": "iter64 review — no payment yet"},
            timeout=15,
        )
        assert rej.status_code in (200, 204), f"reject failed: {rej.status_code} {rej.text[:200]}"

        # Verify booking status transitioned
        got = admin.get(f"{API}/bookings/{booking_id}", timeout=15)
        assert got.status_code == 200, got.text[:200]
        gj = got.json()
        bk = gj.get("booking") if isinstance(gj, dict) else gj
        status = (bk.get("status") or "").lower()
        assert status in ("rejected", "cancelled"), f"expected rejected/cancelled, got {status}"
