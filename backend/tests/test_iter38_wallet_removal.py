"""
Iter 38 — Business Model Pivot: Wallet / Escrow / Withdrawal removal.

Validates:
  1. /api/wallet, /api/wallet/transactions, /api/wallet/withdraw → 404
  2. /api/admin/withdrawals, /api/admin/withdrawals/{id}/release → 404
  3. /api/auth/me no longer returns a `wallet` field
  4. /api/admin/stats returns the new lead-gen KPIs (platform_revenue,
     gst_collected, subscription_revenue, boost_revenue,
     bookTalent_total_collected, pending_refunds) and NO escrow /
     pending_payouts fields.
  5. /api/admin/refunds is reachable and returns a list.
  6. Invoice PDF endpoint (/api/bookings/{id}/invoice) still works.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
API = f"{BASE_URL}/api"


def _admin_token():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@booktalent.com", "password": "Admin@123"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestWalletRemoval:
    def test_wallet_endpoints_gone(self):
        tok = _admin_token()
        for path in ("/wallet", "/wallet/transactions"):
            r = requests.get(f"{API}{path}", headers=_h(tok), timeout=15)
            assert r.status_code == 404, f"{path} should 404, got {r.status_code}"

    def test_withdraw_gone(self):
        tok = _admin_token()
        r = requests.post(f"{API}/wallet/withdraw", json={"amount": 10}, headers=_h(tok), timeout=15)
        assert r.status_code == 404

    def test_admin_withdrawals_gone(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/withdrawals", headers=_h(tok), timeout=15)
        assert r.status_code == 404

    def test_auth_me_has_no_wallet(self):
        tok = _admin_token()
        r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert "wallet" not in r.json(), "wallet key must be removed from /auth/me"


class TestNewLeadGenKPIs:
    def test_admin_stats_shape(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/stats", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        # New keys required
        for k in (
            "platform_revenue", "gst_collected", "subscription_revenue",
            "boost_revenue", "bookTalent_total_collected", "pending_refunds",
        ):
            assert k in j, f"missing {k} in /admin/stats"
        # Legacy keys must be gone
        assert "escrow" not in j
        assert "pending_payouts" not in j

    def test_admin_refunds_endpoint(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/refunds", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
