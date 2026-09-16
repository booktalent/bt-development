"""Iter 71 — SEC-001 / SEC-002 / SEC-003 security regression tests.

Covers:
- SEC-001: /auth/email/verify and /auth/otp/verify must never issue a session.
- SEC-002: rotated admin password (ADMIN_PASSWORD env); old one rejected.
- Regression: full email-OTP signup flow + password login for all roles.
- Auth hardening checks: bcrypt hash format, httpOnly cookie, CORS credentials.
"""
import os
import re
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = base_url.rstrip("/") + "/api"

backend_env = dotenv_values("/app/backend/.env")

CREDS_FILE = Path("/app/memory/test_credentials.md")


def _creds():
    if not CREDS_FILE.exists():
        pytest.skip("Missing /app/memory/test_credentials.md")
    out = {}
    for line in CREDS_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*[^|]+\|\s*`([^`]+)`\s*\|\s*`([^`]+)`", line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


CREDS = _creds()
ADMIN_EMAIL = "admin@booktalent.com"
NEW_ADMIN_PW = CREDS.get(ADMIN_EMAIL)
OLD_ADMIN_PW = "Admin@123"


# ── SEC-002: admin password rotation ────────────────────────────────────
class TestSEC002AdminPasswordRotation:
    def test_env_password_matches_credentials_file(self):
        assert NEW_ADMIN_PW, "admin password not found in test_credentials.md"
        assert backend_env.get("ADMIN_PASSWORD") == NEW_ADMIN_PW, (
            f"ADMIN_PASSWORD env ({backend_env.get('ADMIN_PASSWORD')!r}) != creds file"
        )
        assert NEW_ADMIN_PW != OLD_ADMIN_PW

    def test_old_admin_password_rejected(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": OLD_ADMIN_PW})
        assert r.status_code == 401, f"old password accepted! {r.status_code} {r.text[:200]}"

    def test_new_admin_password_works_and_sets_cookie(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": NEW_ADMIN_PW})
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        assert isinstance(data["token"], str) and len(data["token"]) > 20
        # httpOnly cookie
        raw = r.headers.get("set-cookie", "")
        assert "access_token" in raw, f"no access_token cookie: {raw}"
        assert "httponly" in raw.lower(), f"cookie not httpOnly: {raw}"
        # session works (cookie only, no Authorization header)
        me = s.get(f"{API}/auth/me")
        assert me.status_code == 200, me.text[:200]
        assert me.json()["email"] == ADMIN_EMAIL
        assert "password_hash" not in me.json()
        assert "_id" not in me.json()

    def test_bcrypt_hash_format_in_db(self):
        from pymongo import MongoClient
        c = MongoClient(backend_env["MONGO_URL"])
        u = c[backend_env["DB_NAME"]].users.find_one({"email": ADMIN_EMAIL})
        assert u, "admin user missing in DB"
        assert u["password_hash"].startswith("$2b$"), u["password_hash"][:10]
        c.close()


# ── SEC-001: OTP verify must not issue a session ────────────────────────
class TestSEC001NoPasswordlessTakeover:
    def test_email_verify_existing_user_issues_no_session(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/email/send", json={"email": ADMIN_EMAIL})
        assert r.status_code in (200, 429), r.text[:200]
        otp = "123456"
        if r.status_code == 200:
            otp = r.json().get("test_otp") or "123456"
        v = s.post(f"{API}/auth/email/verify", json={"email": ADMIN_EMAIL, "otp": otp})
        assert v.status_code == 200, v.text[:300]
        body = v.json()
        assert body.get("verified") is True
        assert body.get("token") is None, f"TOKEN ISSUED — takeover still possible: {body}"
        assert "access_token" not in v.headers.get("set-cookie", "").lower()
        assert "access_token" not in s.cookies.get_dict()
        # session must NOT be authenticated
        me = s.get(f"{API}/auth/me")
        assert me.status_code in (401, 403), f"authenticated after OTP verify! {me.status_code}"

    def test_phone_otp_verify_issues_no_session(self):
        s = requests.Session()
        phone = "+919999000011"
        r = s.post(f"{API}/auth/otp/send", json={"phone": phone, "otp": ""})
        assert r.status_code == 200, r.text[:200]
        v = s.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": "123456"})
        assert v.status_code == 200, v.text[:300]
        body = v.json()
        assert body.get("verified") is True
        assert body.get("token") is None, f"TOKEN ISSUED: {body}"
        assert "access_token" not in s.cookies.get_dict()
        me = s.get(f"{API}/auth/me")
        assert me.status_code in (401, 403)

    def test_email_verify_wrong_otp_rejected(self):
        r = requests.post(f"{API}/auth/email/verify", json={"email": ADMIN_EMAIL, "otp": "000000"})
        assert r.status_code == 400, r.text[:200]

    def test_existing_email_cannot_reregister(self):
        r = requests.post(f"{API}/auth/register", json={
            "email": ADMIN_EMAIL, "password": "Hacked@123",
            "first_name": "H", "last_name": "X", "phone": "+919000000001",
            "role": "customer",
        })
        assert r.status_code == 400, r.text[:200]
        assert "already registered" in r.text.lower()
        # admin password unchanged
        assert requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": "Hacked@123"}).status_code == 401


# ── Regression: signup + login for all seeded roles ─────────────────────
class TestAuthRegression:
    created = []

    def test_signup_flow_new_email(self):
        s = requests.Session()
        email = f"test_iter71_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{API}/auth/email/send", json={"email": email, "name": "QA"})
        assert r.status_code == 200, r.text[:300]
        otp = r.json().get("test_otp")
        assert otp, "mock OTP not exposed while email provider disabled"
        v = s.post(f"{API}/auth/email/verify", json={"email": email, "otp": otp})
        assert v.status_code == 200 and v.json()["verified"] is True
        assert v.json().get("token") is None

        reg = s.post(f"{API}/auth/register", json={
            "email": email, "password": "QaTest@123",
            "first_name": "Qa", "last_name": "Tester",
            "phone": "+919000012345", "role": "customer",
        })
        assert reg.status_code == 200, reg.text[:300]
        d = reg.json()
        assert d["user"]["email"] == email
        assert d["user"]["role"] == "customer"
        assert d.get("token")
        assert "access_token" in reg.headers.get("set-cookie", "")
        TestAuthRegression.created.append(d["user"]["id"])

        # login with the new password works
        l = requests.post(f"{API}/auth/login", json={"email": email, "password": "QaTest@123"})
        assert l.status_code == 200, l.text[:200]

    def test_register_without_verification_blocked(self):
        email = f"test_iter71_unverified_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "QaTest@123",
            "first_name": "Qa", "last_name": "Tester",
            "phone": "+919000012346", "role": "customer",
        })
        assert r.status_code == 400 and "verify" in r.text.lower(), r.text[:200]

    @pytest.mark.parametrize("email", [
        "customer@booktalent.com", "priya@booktalent.com", "agency@booktalent.com",
    ])
    def test_seeded_role_logins(self, email):
        pw = CREDS.get(email)
        assert pw, f"no credential for {email}"
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, f"{email} login failed: {r.text[:200]}"
        me = s.get(f"{API}/auth/me")
        assert me.status_code == 200 and me.json()["email"] == email

    def test_wrong_password_401(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": "customer@booktalent.com", "password": "definitely-wrong"})
        assert r.status_code == 401

    def test_logout_clears_cookie(self):
        s = requests.Session()
        s.post(f"{API}/auth/login", json={"email": "customer@booktalent.com",
                                         "password": CREDS.get("customer@booktalent.com")})
        assert s.get(f"{API}/auth/me").status_code == 200
        s.post(f"{API}/auth/logout")
        assert s.get(f"{API}/auth/me").status_code in (401, 403)

    @classmethod
    def teardown_class(cls):
        from pymongo import MongoClient
        c = MongoClient(backend_env["MONGO_URL"])
        dbh = c[backend_env["DB_NAME"]]
        for uid in cls.created:
            dbh.users.delete_one({"id": uid})
            dbh.customer_profiles.delete_one({"user_id": uid})
        dbh.users.delete_many({"email": {"$regex": "^test_iter71_"}})
        c.close()


# ── Brute force / CORS observations ─────────────────────────────────────
class TestAuthHardeningObservations:
    def test_brute_force_lockout_after_5_failures(self):
        email = "customer@booktalent.com"
        codes = []
        for _ in range(6):
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": "bad-pw"})
            codes.append(r.status_code)
            time.sleep(0.2)
        assert 429 in codes or 423 in codes, (
            f"No brute-force lockout: 6 bad logins all returned {codes}"
        )
        # ensure legit login still works after the burst
        ok = requests.post(f"{API}/auth/login", json={"email": email, "password": CREDS.get(email)})
        assert ok.status_code == 200

    def test_cors_credentials_not_wildcard(self):
        r = requests.options(f"{API}/auth/login", headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        })
        allow_origin = r.headers.get("access-control-allow-origin", "")
        allow_creds = r.headers.get("access-control-allow-credentials", "")
        assert not (allow_creds == "true" and allow_origin in ("*", "https://evil.example.com")), (
            f"CORS reflects arbitrary origin with credentials: origin={allow_origin!r}"
        )
