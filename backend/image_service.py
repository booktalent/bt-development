"""
Image optimization helper using Pillow.
- compress_image: resize large originals down to a sensible max dimension + quality
- make_thumbnail: square center-crop thumbnail
Returns (bytes, mime). Falls through unchanged for non-image content.
"""
import io
import logging
from PIL import Image, ImageOps

log = logging.getLogger("booktalent.images")

MAX_W = 2000
MAX_H = 2000
QUALITY = 82
THUMB_SIZE = 400  # square thumb


def _to_pil(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw))
    # honour EXIF rotation
    img = ImageOps.exif_transpose(img)
    return img


def compress_image(raw: bytes, mime: str) -> tuple[bytes, str]:
    """Resize + recompress large images. JPEG/PNG/WEBP only; others pass through."""
    if not mime.startswith("image/") or mime in ("image/gif", "image/svg+xml"):
        return raw, mime
    try:
        img = _to_pil(raw)
    except Exception as e:
        log.warning("compress_image: open failed (%s) — returning original", e)
        return raw, mime
    # if RGBA → flatten on white for JPEG output
    out_format = "JPEG"
    out_mime = "image/jpeg"
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode != "RGB":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format=out_format, quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue(), out_mime


def make_thumbnail(raw: bytes, mime: str, size: int = THUMB_SIZE) -> tuple[bytes, str] | tuple[None, None]:
    """Square center-cropped thumbnail. Returns (None, None) for non-images."""
    if not mime.startswith("image/") or mime == "image/svg+xml":
        return None, None
    try:
        img = _to_pil(raw)
    except Exception as e:
        log.warning("make_thumbnail: open failed (%s)", e)
        return None, None
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (24, 24, 40))  # luxury dark fill
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img = ImageOps.fit(img, (size, size), method=Image.LANCZOS, centering=(0.5, 0.5))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80, optimize=True)
    return buf.getvalue(), "image/jpeg"
