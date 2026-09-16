"""Iter 71 — SEC-003: Easebuzz callback must be FAIL-CLOSED.

Posts a hash-valid `status=success` callback for a synthetic pending payment.
Because the txnid does not exist at Easebuzz, the retrieve API cannot confirm
success, so the payment MUST end as `failed` (previously it fell through to
`completed` = free-booking vulnerability).
"""
import hashlib
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
backend_env = dotenv_values("/app/backend/.env")


def _response_hash(d, salt):
    parts = [salt, str(d.get("status", ""))] + \
        [str(d.get(f"udf{i}", "")) for i in range(10, 0, -1)] + \
        [str(d.get("email", "")), str(d.get("firstname", "")), str(d.get("productinfo", "")),
         str(d.get("amount", "")), str(d.get("txnid", "")), str(d.get("key", ""))]
    return hashlib.sha512("|".join(parts).encode()).hexdigest()


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(backend_env["MONGO_URL"])
    yield c[backend_env["DB_NAME"]]
    c.close()


@pytest.fixture
def settings(mongo):
    s = mongo.payment_gateway_settings.find_one({"_id": "active"})
    assert s, "payment_gateway_settings missing"
    env = s.get("environment", "sandbox")
    return s[env]


def test_callback_fail_closed_when_retrieve_cannot_confirm(mongo, settings):
    txnid = "BTTEST" + uuid.uuid4().hex[:10].upper()
    pid = str(uuid.uuid4())
    mongo.payments.insert_one({
        "id": pid, "txnid": txnid, "gateway": "easebuzz", "status": "pending",
        "amount": 100.0, "user_id": "TEST_iter71", "booking_ids": [],
        "payment_kind": "test", "created_at": datetime.now(timezone.utc),
    })
    try:
        form = {
            "key": settings["key"], "txnid": txnid, "amount": "100.0",
            "productinfo": "TEST_iter71", "firstname": "QA",
            "email": "qa_iter71@example.com", "phone": "9999999999",
            "status": "success",
            **{f"udf{i}": "" for i in range(1, 11)},
        }
        form["udf1"] = pid
        form["hash"] = _response_hash(form, settings["salt"])

        r = requests.post(f"{API}/payments/easebuzz/callback/success",
                          data=form, allow_redirects=False, timeout=60)
        assert r.status_code in (303, 307, 302), f"{r.status_code} {r.text[:200]}"
        assert "status=failure" in r.headers.get("location", ""), r.headers.get("location")

        pay = mongo.payments.find_one({"id": pid})
        assert pay["status"] == "failed", (
            f"FAIL-OPEN: payment marked {pay['status']} without retrieve confirmation"
        )
        assert "retrieve_status" in (pay.get("failure_reason") or "")
    finally:
        mongo.payments.delete_one({"id": pid})
        mongo.payment_logs.delete_many({"txnid": txnid})


def test_callback_bad_hash_rejected(mongo, settings):
    txnid = "BTTEST" + uuid.uuid4().hex[:10].upper()
    pid = str(uuid.uuid4())
    mongo.payments.insert_one({
        "id": pid, "txnid": txnid, "gateway": "easebuzz", "status": "pending",
        "amount": 100.0, "user_id": "TEST_iter71", "created_at": datetime.now(timezone.utc),
    })
    try:
        form = {"key": settings["key"], "txnid": txnid, "amount": "100.0",
                "productinfo": "TEST_iter71", "firstname": "QA",
                "email": "qa_iter71@example.com", "status": "success",
                "hash": "deadbeef"}
        r = requests.post(f"{API}/payments/easebuzz/callback/success",
                          data=form, allow_redirects=False, timeout=60)
        assert "status=failure" in r.headers.get("location", "")
        assert mongo.payments.find_one({"id": pid})["status"] == "pending"
    finally:
        mongo.payments.delete_one({"id": pid})
        mongo.payment_logs.delete_many({"txnid": txnid})
