"""
Iter 64 — Automatic Easebuzz Refund System.

Tests the refund-on-cancel/reject/auto-expire path end-to-end against a
staged completed payment. The real Easebuzz API is NOT called by these
tests (we validate that our helper correctly attempts and records the
refund, including graceful failure handling).
"""
from __future__ import annotations

import os
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest.mark.asyncio
async def test_auto_refund_success(db):
    from routes.easebuzz import set_refund_context, _auto_refund_payment_doc

    set_refund_context(
        db=db,
        new_id=lambda: uuid.uuid4().hex,
        utcnow=lambda: datetime.now(timezone.utc).isoformat(),
    )

    # Seed a completed Easebuzz payment
    pay_id = uuid.uuid4().hex
    booking_id = uuid.uuid4().hex
    txnid = f"BTTEST{uuid.uuid4().hex[:8].upper()}"
    await db.payments.insert_one({
        "id": pay_id, "gateway": "easebuzz", "environment": "sandbox",
        "user_id": "test-cust", "booking_id": booking_id,
        "amount": 500.0, "status": "completed", "txnid": txnid,
        "easepayid": "TESTEASEID", "created_at": datetime.now(timezone.utc),
        "gateway_response": {"email": "test@example.com", "phone": "9999999999"},
    })

    with patch("routes.easebuzz.refund_txn", new=AsyncMock(return_value={
        "status": True, "refund_id": "RUTEST01", "easebuzz_id": "TESTEASEID",
        "refund_amount": 500.0, "reason": "Refund initiated",
    })):
        pay = await db.payments.find_one({"id": pay_id})
        r = await _auto_refund_payment_doc(pay, reason="test reason", actor="test")

    assert r["ok"] is True, r
    assert r["status"] == "successful"
    updated = await db.payments.find_one({"id": pay_id})
    assert updated["refund_status"] == "successful"
    assert updated["refund_id"] == "RUTEST01"
    assert updated["refund_amount"] == 500.0
    assert updated["status"] == "refunded"

    # Idempotency — second call must skip
    r2 = await _auto_refund_payment_doc(updated, reason="another attempt", actor="test")
    assert r2.get("already") is True
    await db.payments.delete_one({"id": pay_id})


@pytest.mark.asyncio
async def test_auto_refund_failure_creates_admin_alert(db):
    from routes.easebuzz import set_refund_context, _auto_refund_payment_doc
    set_refund_context(
        db=db,
        new_id=lambda: uuid.uuid4().hex,
        utcnow=lambda: datetime.now(timezone.utc).isoformat(),
    )
    pay_id = uuid.uuid4().hex
    txnid = f"BTTEST{uuid.uuid4().hex[:8].upper()}"
    await db.payments.insert_one({
        "id": pay_id, "gateway": "easebuzz", "environment": "sandbox",
        "user_id": "test-cust", "booking_id": uuid.uuid4().hex,
        "amount": 250.0, "status": "completed", "txnid": txnid,
        "created_at": datetime.now(timezone.utc),
        "gateway_response": {"email": "x@y.com", "phone": "9999999999"},
    })

    admin_id = "test-admin-" + uuid.uuid4().hex[:6]
    await db.users.insert_one({"id": admin_id, "role": "admin", "email": "audit@bt.com"})

    with patch("routes.easebuzz.refund_txn", new=AsyncMock(return_value={
        "status": False, "reason": "insufficient_settled_balance",
    })):
        pay = await db.payments.find_one({"id": pay_id})
        r = await _auto_refund_payment_doc(pay, reason="rejection", actor="test")

    assert r["ok"] is False
    assert r["status"] == "failed"
    updated = await db.payments.find_one({"id": pay_id})
    assert updated["refund_status"] == "failed"
    assert "insufficient" in (updated.get("refund_error") or "")
    # An admin notification must have been created.
    notif = await db.notifications.find_one({"user_id": admin_id, "type": "refund.failed"})
    assert notif is not None

    # Cleanup
    await db.payments.delete_one({"id": pay_id})
    await db.notifications.delete_many({"user_id": admin_id})
    await db.users.delete_one({"id": admin_id})
