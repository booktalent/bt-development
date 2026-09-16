"""
Iter 81 — Local-disk video storage (drop-in replacement for Emergent Object Storage).

Photos & small documents continue to use the legacy base64-in-Mongo path
in `server.py`. Only VIDEO uploads (up to 1GB) route through here.

Files are written to ``LOCAL_STORAGE_DIR`` (defaults to ``/app/uploads``)
and content-type is remembered in a sidecar ``<file>.meta`` so we can
stream the file back with the correct MIME. That's it — no Emergent
dependency, no external service.

Env
---
``LOCAL_STORAGE_DIR``   Absolute path where video bytes are stored. Nginx
                        can also front this directory for zero-copy
                        streaming (see deploy notes).

Public API (unchanged from Iter 76 so callers don't need edits)
-----
```
from storage import init_storage, put_object, get_object
init_storage()                                # at FastAPI startup
result = put_object("booktalent/videos/<uuid>.mp4", raw_bytes, "video/mp4")
data, mime = get_object(result["path"])
```
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

log = logging.getLogger("storage")

# Root of the on-disk store. Kept outside /app/backend so re-deploys /
# hot-reloads never accidentally wipe user uploads.
LOCAL_STORAGE_DIR = Path(
    (os.environ.get("LOCAL_STORAGE_DIR") or "/app/uploads").rstrip("/")
).resolve()


def _safe_path(rel_path: str) -> Path:
    """Resolve a caller-supplied relative path against ``LOCAL_STORAGE_DIR``
    while blocking directory-traversal (``..``, absolute paths, symlinks).
    """
    # Normalise: strip any leading slash, collapse ``..`` segments, prevent
    # absolute paths. We must reject anything that escapes the storage root.
    rel = rel_path.lstrip("/").replace("\\", "/")
    target = (LOCAL_STORAGE_DIR / rel).resolve()
    try:
        target.relative_to(LOCAL_STORAGE_DIR)
    except ValueError:
        raise RuntimeError(f"Refusing path outside storage root: {rel_path}")
    return target


def init_storage(force: bool = False) -> str:
    """Ensure the storage root exists. Kept idempotent + same signature as
    the old Emergent helper so ``server.py`` doesn't need any changes."""
    LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Local object storage ready at %s", LOCAL_STORAGE_DIR)
    return str(LOCAL_STORAGE_DIR)


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Write ``data`` to disk under ``path`` (relative to the storage root).
    Overwrites on collision (same contract as before). Content-type is
    persisted in a sidecar file so :func:`get_object` can return it later.
    """
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file then atomic-rename — protects against partial
    # writes if the process is killed mid-upload.
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    # Persist content-type in a sidecar (kept tiny and readable).
    (target.parent / (target.name + ".meta")).write_text(
        (content_type or "application/octet-stream").strip(), encoding="utf-8"
    )
    size = target.stat().st_size
    log.info("Stored %s (%d bytes, %s)", path, size, content_type)
    return {"path": path, "size": size, "content_type": content_type}


def get_object(path: str) -> Tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for the stored object.

    Raises :class:`FileNotFoundError` when the object is missing — the
    caller in ``server.py`` already turns that into an HTTP 502 with a
    friendly "temporarily unavailable" message.
    """
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Object not found: {path}")
    data = target.read_bytes()
    meta_file = target.parent / (target.name + ".meta")
    ct = "application/octet-stream"
    if meta_file.exists():
        try:
            ct = meta_file.read_text(encoding="utf-8").strip() or ct
        except Exception:
            pass
    return data, ct


def delete_object(path: str) -> bool:
    """Optional helper — best-effort delete. Missing file is treated as
    success so cleanup routines are idempotent."""
    try:
        target = _safe_path(path)
        if target.exists():
            target.unlink()
        meta = target.parent / (target.name + ".meta")
        if meta.exists():
            meta.unlink()
        return True
    except Exception as e:
        log.warning("Failed to delete %s: %s", path, e)
        return False
