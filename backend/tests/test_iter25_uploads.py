"""
Sprint 2 (iter25) — Chunked filesystem media uploads regression suite.

Covers:
  1. Chunked upload end-to-end (init → chunk×3 → complete → GET /file)
  2. Image thumbnail generation (Pillow)
  3. Resume / status flow + idempotent chunk re-send
  4. Tenant isolation (user_id scoping)
  5. Size cap (5 GB) & invalid size rejection
  6. Invalid media type rejection
  7. Duplicate-key fix on /artists/featured (dedup is client side; server can still repeat)
  8. Regression: legacy /api/media/upload (base64) still works + /media/{id}/thumb
"""
from __future__ import annotations

import io
import os
import base64
from pathlib import Path

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://booktalent-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ARTIST_EMAIL = os.environ.get("TEST_ARTIST_EMAIL", "priya@booktalent.com")
ARTIST_PASSWORD = os.environ.get("TEST_ARTIST_PASSWORD", "Artist@123")
CUSTOMER_EMAIL = os.environ.get("TEST_CUSTOMER_EMAIL", "customer@booktalent.com")
CUSTOMER_PASSWORD = os.environ.get("TEST_CUSTOMER_PASSWORD", "Customer@123")

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB
FILE_SIZE = 3 * CHUNK_SIZE     # 12 MB → exactly 3 chunks


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def s():
    return requests.Session()


def _login(session, email, password):
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def artist_token(s):
    return _login(s, ARTIST_EMAIL, ARTIST_PASSWORD)


@pytest.fixture(scope="session")
def customer_token(s):
    return _login(s, CUSTOMER_EMAIL, CUSTOMER_PASSWORD)


@pytest.fixture
def artist_h(artist_token):
    return {"Authorization": f"Bearer {artist_token}"}


@pytest.fixture
def customer_h(customer_token):
    return {"Authorization": f"Bearer {customer_token}"}


# ── 1. CHUNKED UPLOAD END-TO-END ─────────────────────────────────────────────
class TestChunkedUploadE2E:
    def test_full_flow_12mb_binary(self, s, artist_h):
        # 1a. INIT
        init = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_test.bin", "size": FILE_SIZE,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15)
        assert init.status_code == 200, init.text
        data = init.json()
        assert "upload_id" in data
        assert data["chunk_size"] == 4194304
        assert data["expected_chunks"] == 3
        assert data["max_bytes"] == 5368709120

        upload_id = data["upload_id"]

        # 1b. Send 3 x 4 MB chunks
        payload = b"A" * CHUNK_SIZE
        expected_total = 0
        for i in range(3):
            resp = s.put(
                f"{API}/uploads/{upload_id}/chunk",
                params={"index": i},
                data=payload,
                headers={**artist_h, "Content-Type": "application/octet-stream"},
                timeout=60,
            )
            assert resp.status_code == 200, f"chunk {i} failed: {resp.status_code} {resp.text}"
            body = resp.json()
            assert body["ok"] is True
            expected_total += CHUNK_SIZE
            assert body["received_bytes"] == expected_total

        # 1c. COMPLETE
        cmp = s.post(f"{API}/uploads/{upload_id}/complete", headers=artist_h, timeout=30)
        assert cmp.status_code == 200, cmp.text
        cbody = cmp.json()
        assert "id" in cbody
        assert cbody["size"] == FILE_SIZE
        assert "has_thumb" in cbody

        media_id = cbody["id"]

        # 1d. GET file
        f = s.get(f"{API}/media/{media_id}/file", timeout=30)
        assert f.status_code == 200
        assert int(f.headers.get("content-length", 0)) == FILE_SIZE
        assert f.headers.get("content-type", "").startswith("application/octet-stream")
        assert len(f.content) == FILE_SIZE

        # 1e. STATUS shows completed
        st = s.get(f"{API}/uploads/{upload_id}/status", headers=artist_h, timeout=15)
        assert st.status_code == 200
        assert st.json()["status"] == "completed"
        assert st.json()["media_id"] == media_id

        # store for later isolation test
        pytest.priya_completed_upload_id = upload_id
        pytest.priya_media_id = media_id


# ── 2. IMAGE THUMBNAIL ───────────────────────────────────────────────────────
class TestImageThumbnail:
    def test_jpeg_upload_produces_thumb(self, s, artist_h):
        # Generate ~2 MB JPEG in memory
        img = Image.new("RGB", (3000, 2000), color=(90, 40, 160))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        raw = buf.getvalue()
        # pad to at least ~1 MB — JPEG at plain color compresses to a few KB so add noise
        if len(raw) < 200 * 1024:
            # regenerate with noise
            import random
            noisy = Image.new("RGB", (2000, 2000))
            pixels = noisy.load()
            for y in range(0, 2000, 4):
                for x in range(0, 2000, 4):
                    pixels[x, y] = (random.randrange(256), random.randrange(256), random.randrange(256))
            buf = io.BytesIO()
            noisy.save(buf, format="JPEG", quality=95)
            raw = buf.getvalue()
        size = len(raw)

        # INIT
        init = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_image.jpg", "size": size,
            "mime": "image/jpeg", "type": "gallery",
        }, headers=artist_h, timeout=15).json()
        upload_id = init["upload_id"]
        chunks = init["expected_chunks"]

        # send chunks
        for i in range(chunks):
            fragment = raw[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
            r = s.put(
                f"{API}/uploads/{upload_id}/chunk",
                params={"index": i}, data=fragment,
                headers={**artist_h, "Content-Type": "application/octet-stream"},
                timeout=60,
            )
            assert r.status_code == 200, r.text

        cmp = s.post(f"{API}/uploads/{upload_id}/complete", headers=artist_h, timeout=30)
        assert cmp.status_code == 200, cmp.text
        cbody = cmp.json()
        assert cbody["has_thumb"] is True, "expected has_thumb=True for JPEG upload"

        media_id = cbody["id"]
        # thumb endpoint returns image/jpeg
        t = s.get(f"{API}/media/{media_id}/thumb", timeout=15)
        assert t.status_code == 200
        assert t.headers.get("content-type", "").startswith("image/jpeg")
        assert len(t.content) > 100  # actual bytes

        # file endpoint should also return the JPEG
        f = s.get(f"{API}/media/{media_id}/file", timeout=15)
        assert f.status_code == 200
        assert f.headers.get("content-type", "").startswith("image/jpeg")


# ── 3. RESUME / STATUS + IDEMPOTENT CHUNK ───────────────────────────────────
class TestResumeAndIdempotent:
    def test_status_and_idempotent_chunk(self, s, artist_h):
        init = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_resume.bin", "size": FILE_SIZE,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15).json()
        upload_id = init["upload_id"]

        payload = b"B" * CHUNK_SIZE
        # send chunks 0 and 1
        for i in (0, 1):
            r = s.put(
                f"{API}/uploads/{upload_id}/chunk",
                params={"index": i}, data=payload,
                headers={**artist_h, "Content-Type": "application/octet-stream"},
                timeout=60,
            )
            assert r.status_code == 200

        # status should show in_progress + 8 MB
        st = s.get(f"{API}/uploads/{upload_id}/status", headers=artist_h, timeout=15).json()
        assert st["status"] == "in_progress"
        assert st["received_bytes"] == 2 * CHUNK_SIZE
        assert st["size"] == FILE_SIZE

        # send chunk 1 again → idempotent (resumed)
        r = s.put(
            f"{API}/uploads/{upload_id}/chunk",
            params={"index": 1}, data=payload,
            headers={**artist_h, "Content-Type": "application/octet-stream"},
            timeout=60,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("resumed") is True

        # send chunk 2 and complete
        r = s.put(
            f"{API}/uploads/{upload_id}/chunk",
            params={"index": 2}, data=payload,
            headers={**artist_h, "Content-Type": "application/octet-stream"},
            timeout=60,
        )
        assert r.status_code == 200

        cmp = s.post(f"{API}/uploads/{upload_id}/complete", headers=artist_h, timeout=30)
        assert cmp.status_code == 200


# ── 4. TENANT ISOLATION ──────────────────────────────────────────────────────
class TestTenantIsolation:
    def test_other_user_cannot_access(self, s, artist_h, customer_h):
        # priya creates an upload
        init = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_priva.bin", "size": FILE_SIZE,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15).json()
        upload_id = init["upload_id"]

        # customer tries to see status → 404
        r = s.get(f"{API}/uploads/{upload_id}/status", headers=customer_h, timeout=15)
        assert r.status_code == 404, f"expected 404 got {r.status_code}"

        # customer tries to send a chunk → 404
        r = s.put(
            f"{API}/uploads/{upload_id}/chunk",
            params={"index": 0}, data=b"X" * 1024,
            headers={**customer_h, "Content-Type": "application/octet-stream"},
            timeout=15,
        )
        assert r.status_code == 404

        # customer tries to complete → 404
        r = s.post(f"{API}/uploads/{upload_id}/complete", headers=customer_h, timeout=15)
        assert r.status_code == 404


# ── 5. SIZE CAP ──────────────────────────────────────────────────────────────
class TestSizeCap:
    def test_size_over_5gb_rejected(self, s, artist_h):
        r = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_huge.bin", "size": 6 * 1024 * 1024 * 1024,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15)
        assert r.status_code == 413, f"got {r.status_code} {r.text}"

    def test_zero_size_rejected(self, s, artist_h):
        r = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_zero.bin", "size": 0,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15)
        assert r.status_code == 413

    def test_negative_size_rejected(self, s, artist_h):
        r = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_neg.bin", "size": -100,
            "mime": "application/octet-stream", "type": "gallery",
        }, headers=artist_h, timeout=15)
        assert r.status_code == 413


# ── 6. INVALID TYPE ──────────────────────────────────────────────────────────
class TestInvalidType:
    def test_unknown_type_rejected(self, s, artist_h):
        r = s.post(f"{API}/uploads/init", json={
            "filename": "TEST_bad.bin", "size": 100,
            "mime": "application/octet-stream", "type": "xyz",
        }, headers=artist_h, timeout=15)
        assert r.status_code == 400


# ── 7. LEGACY /api/media/upload REGRESSION ──────────────────────────────────
class TestLegacyMedia:
    def test_legacy_base64_upload_still_works(self, s, customer_h):
        # ~100 KB PNG data URL
        img = Image.new("RGB", (400, 400), color=(255, 128, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        data_url = f"data:image/png;base64,{b64}"

        r = s.post(
            f"{API}/media/upload",
            json={"data_url": data_url, "type": "gallery", "title": "TEST_legacy"},
            headers=customer_h, timeout=30,
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        assert "id" in doc
        media_id = doc["id"]

        # thumb endpoint should still work for legacy media (base64 fallback)
        t = s.get(f"{API}/media/{media_id}/thumb", timeout=15)
        assert t.status_code == 200
        assert t.headers.get("content-type", "").startswith("image/")

        # /api/media/{id} — legacy endpoint actually streams raw bytes (not JSON)
        m = s.get(f"{API}/media/{media_id}", timeout=15)
        assert m.status_code == 200
        assert m.headers.get("content-type", "").startswith("image/")
        assert len(m.content) > 100


# ── 8. FEATURED ARTISTS (dedup handled by frontend) ─────────────────────────
class TestFeatured:
    def test_featured_endpoint_returns_200(self, s):
        r = s.get(f"{API}/artists/featured?limit=8", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # backend may return duplicates — that's OK; frontend dedupes.


# ── 9. Sprint 1 regression: mobile hamburger unrelated to backend, but check
#      key endpoints from previous iters are still up.
class TestSprint1Regression:
    def test_cities_up(self, s):
        r = s.get(f"{API}/cities", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_search_ai_up(self, s):
        # /search/ai — accepts a POST body; verify it exists / doesn't 500 without body
        r = s.post(f"{API}/search/ai", json={"q": "singer for wedding"}, timeout=30)
        # allowed responses: 200 or 400/422 (validation), never 500
        assert r.status_code in (200, 400, 401, 422), f"unexpected {r.status_code} {r.text[:200]}"

    def test_wallet_endpoint_auth(self, s, artist_h):
        r = s.get(f"{API}/wallet/me", headers=artist_h, timeout=15)
        # endpoint should exist (either 200 or 404 for no wallet), not 500
        assert r.status_code in (200, 404), r.text[:200]

    def test_kyc_endpoint_up(self, s, artist_h):
        r = s.get(f"{API}/kyc/me", headers=artist_h, timeout=15)
        assert r.status_code in (200, 404)
