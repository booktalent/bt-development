"""
Easebuzz Payment Gateway service helpers.

- Hash generation (initiate, response verify, retrieve) per official spec.
- All configuration (Key / Salt / URLs / environment) is loaded from the
  `payment_gateway_settings` Mongo collection so it can be flipped between
  Sandbox and Live from the Admin Panel — never hardcoded.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)


# ── IPv4-only HTTP transport ────────────────────────────────────────────
# Easebuzz's fraud/anti-abuse layer whitelists our egress IP. In cloud
# containers Python's default resolver often picks IPv6 first, so a live
# `initiateLink` call comes from an IPv6 address (e.g. `2a02:…`) and
# Easebuzz rejects it with "Request Invalid for the merchant".
#
# Binding the local socket to an IPv4 address forces httpx to use IPv4
# only. By default we bind to ``0.0.0.0`` which lets the OS pick the
# primary IPv4 interface. On multi-homed hosts, set
# ``EASEBUZZ_LOCAL_IPV4`` in the backend env to lock the egress to a
# specific IPv4 (e.g. ``91.108.121.199`` on our live VPS).
_LOCAL_IPV4 = (os.environ.get("EASEBUZZ_LOCAL_IPV4") or "0.0.0.0").strip() or "0.0.0.0"


def _ipv4_client(**kwargs: Any) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` locked to IPv4 egress."""
    transport = httpx.AsyncHTTPTransport(local_address=_LOCAL_IPV4, retries=1)
    return httpx.AsyncClient(transport=transport, **kwargs)


# Public defaults — used ONLY to seed the settings document on first boot.
# Runtime always reads from Mongo, never from these constants.
DEFAULT_SANDBOX_BASE_URL = "https://testpay.easebuzz.in"
DEFAULT_LIVE_BASE_URL = "https://pay.easebuzz.in"
# Refund API lives on the dashboard host, NOT the pay/checkout host.
DEFAULT_SANDBOX_DASHBOARD_URL = "https://testdashboard.easebuzz.in"
DEFAULT_LIVE_DASHBOARD_URL = "https://dashboard.easebuzz.in"

_UDF_FIELDS = [f"udf{i}" for i in range(1, 11)]


def _sha512_lower(s: str) -> str:
    return hashlib.sha512(s.encode("utf-8")).hexdigest().lower()


def build_initiate_hash(payload: Dict[str, Any], salt: str) -> str:
    """`key|txnid|amount|productinfo|firstname|email|udf1..udf10|salt`"""
    parts = [
        str(payload.get("key", "")),
        str(payload.get("txnid", "")),
        str(payload.get("amount", "")),
        str(payload.get("productinfo", "")),
        str(payload.get("firstname", "")),
        str(payload.get("email", "")),
    ]
    parts.extend(str(payload.get(k, "")) for k in _UDF_FIELDS)
    parts.append(salt)
    return _sha512_lower("|".join(parts))


def build_response_hash(data: Dict[str, Any], salt: str) -> str:
    """`salt|status|udf10..udf1|email|firstname|productinfo|amount|txnid|key`
    UDF order is REVERSED for response verification per Easebuzz spec."""
    parts = [
        salt,
        str(data.get("status", "")),
        str(data.get("udf10", "")),
        str(data.get("udf9", "")),
        str(data.get("udf8", "")),
        str(data.get("udf7", "")),
        str(data.get("udf6", "")),
        str(data.get("udf5", "")),
        str(data.get("udf4", "")),
        str(data.get("udf3", "")),
        str(data.get("udf2", "")),
        str(data.get("udf1", "")),
        str(data.get("email", "")),
        str(data.get("firstname", "")),
        str(data.get("productinfo", "")),
        str(data.get("amount", "")),
        str(data.get("txnid", "")),
        str(data.get("key", "")),
    ]
    return _sha512_lower("|".join(parts))


def build_retrieve_hash(payload: Dict[str, Any], salt: str) -> str:
    """`key|txnid|amount|email|phone|salt`"""
    parts = [
        str(payload.get("key", "")),
        str(payload.get("txnid", "")),
        str(payload.get("amount", "")),
        str(payload.get("email", "")),
        str(payload.get("phone", "")),
        salt,
    ]
    return _sha512_lower("|".join(parts))


def normalise_amount(amount: float | int | str) -> str:
    """Always send amount as a 2-decimal string. Same value must be used for
    the request-hash, the API call and the response-hash verification, else
    Easebuzz will silently mismatch."""
    return f"{float(amount):.2f}"


async def initiate_link(base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST form-urlencoded payload to `{base}/payment/initiateLink`."""
    url = base_url.rstrip("/") + "/payment/initiateLink"
    async with _ipv4_client(timeout=30.0) as client:
        r = await client.post(
            url,
            content=urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    try:
        return r.json()
    except Exception:
        return {"status": 0, "raw": r.text}


async def retrieve_txn(base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST form-urlencoded payload to `{base}/transaction/v1/retrieve`."""
    url = base_url.rstrip("/") + "/transaction/v1/retrieve"
    async with _ipv4_client(timeout=30.0) as client:
        r = await client.post(
            url,
            content=urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    try:
        return r.json()
    except Exception:
        return {"status": 0, "raw": r.text}


def build_refund_hash(payload: Dict[str, Any], salt: str) -> str:
    """Refund hash sequence: `key|txnid|amount|refund_amount|email|phone|salt`."""
    parts = [
        str(payload.get("key", "")),
        str(payload.get("txnid", "")),
        str(payload.get("amount", "")),
        str(payload.get("refund_amount", "")),
        str(payload.get("email", "")),
        str(payload.get("phone", "")),
        salt,
    ]
    return _sha512_lower("|".join(parts))


def dashboard_url_for(base_url: str) -> str:
    """Given a pay/checkout base_url, return the corresponding dashboard host
    used by the Refund + Refund-Status APIs."""
    if not base_url:
        return DEFAULT_LIVE_DASHBOARD_URL
    if "testpay" in base_url or "test" in base_url:
        return DEFAULT_SANDBOX_DASHBOARD_URL
    return DEFAULT_LIVE_DASHBOARD_URL


async def refund_txn(dashboard_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST JSON payload to `{dashboard}/transaction/v1/refund`.

    Payload must include: key, txnid (original easebuzz txnid), amount
    (original payment amount as float), refund_amount, email, phone, hash.
    Returns Easebuzz response — success looks like:
        {"status": true, "refund_amount": N, "easebuzz_id": "...",
         "refund_id": "RU...", "reason": "Refund initiated..."}
    """
    url = dashboard_url.rstrip("/") + "/transaction/v1/refund"
    async with _ipv4_client(timeout=30.0) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    try:
        return r.json()
    except Exception:
        return {"status": False, "raw": r.text, "http_status": r.status_code}


def default_settings_document() -> Dict[str, Any]:
    """Seed document used the first time the admin visits Payment Settings.
    Sandbox credentials come pre-filled (from the user's ask). Admin must
    populate the Live keys before flipping `environment` to `live`."""
    return {
        "_id": "active",
        "provider": "easebuzz",
        "enabled": True,
        "environment": "sandbox",
        "sandbox": {
            "key": "1OCWIXWTP",
            "salt": "ZPGNO0AHZ",
            "base_url": DEFAULT_SANDBOX_BASE_URL,
        },
        "live": {
            "key": "",
            "salt": "",
            "base_url": DEFAULT_LIVE_BASE_URL,
        },
        # Frontend routes the browser back to these after success/failure.
        # `{FRONTEND}` is substituted with REACT_APP_BACKEND_URL at runtime.
        "success_url": "/booking/payment-return",
        "failure_url": "/booking/payment-return",
        # Optional webhook override — leave blank to use default backend route.
        "webhook_url": "",
    }
