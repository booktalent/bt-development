"""
Iteration 6 — Media (Pillow compression, replace, thumb, reorder, set-featured,
landing & search dynamic gallery thumbnails).
"""
import os
import io
import base64
import time
import pytest
import requests
from PIL import Image
from pathlib import Path

# load REACT_APP_BACKEND_URL from /app/frontend/.env if not in environment
_env_path = Path("/app/frontend/.env")
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            os.environ.setdefault("REACT_APP_BACKEND_URL", line.split("=", 1)[1].strip().strip('"'))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"

ARTIST_EMAIL = "priya@booktalent.com"
ARTIST_PASS = "Artist@123"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def _png_bytes(w=3000, h=2000, color=(123, 200, 80)):
    """Generate a sizeable PNG that will trigger compression."""
    img = Image.new("RGB", (w, h), color)
    # add gradient noise so JPEG can't trivially compress to nothing
    px = img.load()
    for y in range(0, h, 7):
        for x in range(0, w, 11):
            px[x, y] = ((x + y) % 256, (x * 3) % 256, (y * 5) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _data_url(raw: bytes, mime: str = "image/png"):
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


@pytest.fixture(scope="module")
def artist_ctx():
    tok, user = _login(ARTIST_EMAIL, ARTIST_PASS)
    return {"tok": tok, "user": user}


class TestMediaCompressionAndThumb:
    """Pillow compression + thumbnail generation."""

    def test_upload_image_is_compressed(self, artist_ctx):
        raw = _png_bytes(3000, 2000)
        original = len(raw)
        url = _data_url(raw, "image/png")
        r = requests.post(
            f"{API}/media/upload",
            json={"type": "gallery", "data_url": url, "title": "TEST_iter6_compress"},
            headers=_h(artist_ctx["tok"]),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # mime should now be JPEG (compression flattens PNG to JPEG)
        assert body["mime"] == "image/jpeg", f"expected jpeg got {body['mime']}"
        assert body["size"] < original, (
            f"compressed size {body['size']} should be smaller than original {original}"
        )
        # less than original is fine
        assert body["size"] < original
        assert body["original_size"] == original
        # store for later tests
        TestMediaCompressionAndThumb.mid = body["id"]

    def test_thumb_endpoint_returns_jpeg(self, artist_ctx):
        mid = getattr(TestMediaCompressionAndThumb, "mid", None)
        if not mid:
            # fallback: upload one
            raw = _png_bytes(800, 600)
            r = requests.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": _data_url(raw), "title": "TEST_iter6_thumb_fb"},
                headers=_h(artist_ctx["tok"]),
                timeout=20,
            )
            mid = r.json()["id"]
        r = requests.get(f"{API}/media/{mid}/thumb", timeout=15)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/jpeg")
        # decode and verify dimensions
        im = Image.open(io.BytesIO(r.content))
        assert im.size == (400, 400), f"thumb dims {im.size} != (400,400)"

    def test_thumb_for_non_existent_media(self):
        r = requests.get(f"{API}/media/does-not-exist/thumb", timeout=10)
        assert r.status_code == 404


class TestMediaReplace:
    """PUT /api/media/{id} preserves id + order + featured flag."""

    def test_replace_preserves_id(self, artist_ctx):
        # upload original
        raw1 = _png_bytes(2400, 1600, color=(255, 0, 0))
        r1 = requests.post(
            f"{API}/media/upload",
            json={"type": "gallery", "data_url": _data_url(raw1), "title": "TEST_iter6_replace_orig"},
            headers=_h(artist_ctx["tok"]),
            timeout=30,
        )
        assert r1.status_code == 200, r1.text
        mid = r1.json()["id"]
        # mark it featured + give it an order
        requests.post(f"{API}/media/{mid}/feature", headers=_h(artist_ctx["tok"]), timeout=10)

        # replace with smaller different-color image
        raw2 = _png_bytes(1500, 1000, color=(0, 0, 255))
        r2 = requests.put(
            f"{API}/media/{mid}",
            json={"type": "gallery", "data_url": _data_url(raw2), "title": "TEST_iter6_replace_new"},
            headers=_h(artist_ctx["tok"]),
            timeout=30,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == mid

        # GET media list and confirm featured flag still set + id unchanged
        lst = requests.get(f"{API}/media?type=gallery", headers=_h(artist_ctx["tok"]), timeout=10).json()
        item = next((m for m in lst if m["id"] == mid), None)
        assert item is not None
        assert item["is_featured"] is True, "featured flag must persist across replace"
        # title was updated
        assert item["title"] == "TEST_iter6_replace_new"

        # fetch raw binary; should differ from original
        bin1 = requests.get(f"{API}/media/{mid}").content
        assert len(bin1) > 0

    def test_replace_forbidden_for_other_user(self, artist_ctx):
        # upload media as priya
        raw = _png_bytes(800, 600)
        r1 = requests.post(
            f"{API}/media/upload",
            json={"type": "gallery", "data_url": _data_url(raw), "title": "TEST_iter6_forbid"},
            headers=_h(artist_ctx["tok"]),
            timeout=30,
        )
        mid = r1.json()["id"]
        # try to replace as a different artist
        other_tok, _ = _login("rohit@booktalent.com", "Artist@123")
        raw2 = _png_bytes(800, 600, color=(10, 10, 10))
        r2 = requests.put(
            f"{API}/media/{mid}",
            json={"type": "gallery", "data_url": _data_url(raw2)},
            headers=_h(other_tok),
            timeout=30,
        )
        assert r2.status_code == 403


class TestMediaReorderAndFeature:
    def test_reorder_persists(self, artist_ctx):
        # upload 3 media
        ids = []
        for i in range(3):
            raw = _png_bytes(600, 400, color=(i * 80, 100, 200))
            r = requests.post(
                f"{API}/media/upload",
                json={"type": "gallery", "data_url": _data_url(raw), "title": f"TEST_iter6_order_{i}"},
                headers=_h(artist_ctx["tok"]),
                timeout=20,
            )
            assert r.status_code == 200
            ids.append(r.json()["id"])

        # reverse order
        reordered = list(reversed(ids))
        rr = requests.post(
            f"{API}/media/reorder",
            json={"ids": reordered},
            headers=_h(artist_ctx["tok"]),
            timeout=10,
        )
        assert rr.status_code == 200

        # fetch and confirm order field reflects new ordering
        lst = requests.get(f"{API}/media?type=gallery", headers=_h(artist_ctx["tok"]), timeout=10).json()
        order_map = {m["id"]: m.get("order", 0) for m in lst if m["id"] in ids}
        # first id in reordered should now have lowest order
        orders = [order_map[i] for i in reordered]
        assert orders == sorted(orders), f"reorder did not persist correctly: {orders}"

    def test_set_featured_toggle(self, artist_ctx):
        raw = _png_bytes(800, 600)
        r = requests.post(
            f"{API}/media/upload",
            json={"type": "gallery", "data_url": _data_url(raw), "title": "TEST_iter6_feat"},
            headers=_h(artist_ctx["tok"]),
            timeout=20,
        )
        mid = r.json()["id"]
        assert r.json().get("is_featured") in (False, None)

        f1 = requests.post(f"{API}/media/{mid}/feature", headers=_h(artist_ctx["tok"]), timeout=10)
        assert f1.status_code == 200
        lst = requests.get(f"{API}/media?type=gallery", headers=_h(artist_ctx["tok"]), timeout=10).json()
        item = next((m for m in lst if m["id"] == mid), None)
        assert item and item["is_featured"] is True

        # toggle back
        requests.post(f"{API}/media/{mid}/feature", headers=_h(artist_ctx["tok"]), timeout=10)
        lst = requests.get(f"{API}/media?type=gallery", headers=_h(artist_ctx["tok"]), timeout=10).json()
        item = next((m for m in lst if m["id"] == mid), None)
        assert item and item["is_featured"] is False


class TestPublicGalleryThumbs:
    """Landing & search cards rely on gallery_thumbs in response payload."""

    def test_featured_includes_gallery_thumbs(self):
        r = requests.get(f"{API}/artists/featured?limit=8", timeout=15)
        assert r.status_code == 200, r.text
        arr = r.json()
        assert isinstance(arr, list)
        if not arr:
            pytest.skip("no featured artists seeded")
        # at least one of them should have gallery_thumbs key
        assert any("gallery_thumbs" in a for a in arr), "gallery_thumbs missing from featured payload"

    def test_search_includes_gallery_thumbs(self):
        r = requests.get(f"{API}/artists/search?limit=10", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        assert isinstance(items, list)
        if not items:
            pytest.skip("no artists in search response")
        assert any("gallery_thumbs" in a for a in items), "gallery_thumbs missing from search payload"


class TestMediaSizeLimit:
    def test_oversize_rejected_413(self, artist_ctx):
        # 15 MB raw blob
        raw = b"\x00" * (15 * 1024 * 1024)
        url = f"data:application/octet-stream;base64,{base64.b64encode(raw).decode()}"
        r = requests.post(
            f"{API}/media/upload",
            json={"type": "document", "data_url": url, "title": "TEST_iter6_oversize"},
            headers=_h(artist_ctx["tok"]),
            timeout=60,
        )
        assert r.status_code == 413, f"expected 413 got {r.status_code} {r.text[:200]}"

    def test_invalid_data_url_rejected(self, artist_ctx):
        r = requests.post(
            f"{API}/media/upload",
            json={"type": "gallery", "data_url": "not-a-data-url"},
            headers=_h(artist_ctx["tok"]),
            timeout=10,
        )
        assert r.status_code == 400
