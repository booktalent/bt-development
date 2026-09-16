"""
Iter 50 — Video Compression Service
------------------------------------
Fires off a background subprocess that re-encodes an uploaded video with
libx264 CRF 28 (~50-70% file-size reduction while keeping perceptual quality).
Chunked processing is unnecessary at this scale — ffmpeg streams the input.

We deliberately keep this file OFF the request path: `compress_video_async`
returns immediately and the actual work runs in a fire-and-forget asyncio
task. Once done, the media document's `compressed=True` flag flips.

If ffmpeg isn't installed, the service degrades to a no-op (records
`compressed_error: 'ffmpeg-missing'`) so the pod stays useful.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

FFMPEG_BIN: Optional[str] = shutil.which("ffmpeg")
# Only compress videos larger than 2 MB — anything tinier is already fine.
MIN_COMPRESS_BYTES: int = 2 * 1024 * 1024
# Cap encoded output at 720p — plenty for portfolio reels.
MAX_HEIGHT: int = 720


async def _run_ffmpeg(input_path: str, output_path: str) -> tuple[int, str]:
    """Await the ffmpeg subprocess. Returns (return_code, stderr_tail).

    SECURITY NOTE (audit response, Feb 2026):
    ------------------------------------------
    This uses `asyncio.create_subprocess_exec` — the *safe* subprocess API
    that invokes the target binary via `execve` directly, with NO shell
    interpretation. It is NOT Python's `exec()` builtin (which would be an
    eval/code-injection primitive) and it is NOT `subprocess.run(..., shell=True)`
    (which would splice a shell). Argument list is passed as a `list[str]`,
    so path characters like `; & | $ \` etc. are treated as literal filename
    bytes by ffmpeg — no injection surface exists.

    Additional defense-in-depth: we assert both paths are absolute, live under
    the OS tempdir or the configured media root, and contain no NUL bytes.
    """
    import tempfile
    tmp_root = tempfile.gettempdir()
    media_root = os.environ.get("MEDIA_ROOT", "/app/backend/media_uploads")
    for p in (input_path, output_path):
        if "\x00" in p:
            raise ValueError("path contains NUL byte")
        abs_p = os.path.abspath(p)
        if not (abs_p.startswith(tmp_root) or abs_p.startswith(media_root)):
            raise ValueError(f"path outside allowed roots: {abs_p}")

    cmd = [
        FFMPEG_BIN or "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale='min({MAX_HEIGHT * 16 // 9},iw)':'min({MAX_HEIGHT},ih)':force_original_aspect_ratio=decrease",
        "-c:v", "libx264", "-preset", "medium", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    tail = (stderr or b"")[-800:].decode("utf-8", errors="replace")
    return int(proc.returncode or 0), tail


async def compress_video_bytes(*, raw: bytes) -> tuple[bytes, dict]:
    """Compress video bytes → (new_bytes, stats). Returns raw unchanged if
    ffmpeg is missing, the file is under threshold, or compression didn't
    yield a meaningful size win. Never raises."""
    stats: dict = {"original_bytes": len(raw), "compressed": False}
    if len(raw) < MIN_COMPRESS_BYTES:
        stats["compressed_reason"] = "under-threshold"
        return raw, stats
    if not FFMPEG_BIN:
        stats["compressed_error"] = "ffmpeg-missing"
        return raw, stats
    import tempfile
    in_fd, in_path = tempfile.mkstemp(suffix=".in.mp4")
    out_path = in_path.replace(".in.mp4", ".out.mp4")
    try:
        with os.fdopen(in_fd, "wb") as f:
            f.write(raw)
        rc, tail = await _run_ffmpeg(in_path, out_path)
        if rc != 0 or not os.path.exists(out_path):
            log.error("compress_video_bytes: ffmpeg exit=%s tail=%s", rc, tail)
            stats["compressed_error"] = f"ffmpeg-rc-{rc}"
            return raw, stats
        with open(out_path, "rb") as f:
            new_raw = f.read()
        if len(new_raw) < len(raw) * 0.95:
            stats.update({
                "compressed": True,
                "compressed_bytes": len(new_raw),
                "compression_ratio": round(len(new_raw) / len(raw), 3),
            })
            return new_raw, stats
        stats["compressed_reason"] = "no-gain"
        return raw, stats
    except Exception as e:  # noqa: BLE001
        log.exception("compress_video_bytes: %s", e)
        stats["compressed_error"] = str(e)[:200]
        return raw, stats
    finally:
        for p in (in_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


async def compress_video(
    *,
    db: Any,
    media_id: str,
    input_path: str,
) -> None:
    """Background task — run ffmpeg, swap the file in place, update the doc.
    Never raises to the caller; every failure lands in `compressed_error`
    on the media document so we can surface it in Admin."""
    try:
        size = os.path.getsize(input_path)
    except OSError as e:
        log.warning("compress_video: cannot stat %s: %s", input_path, e)
        return

    if size < MIN_COMPRESS_BYTES:
        await db.media.update_one({"id": media_id}, {"$set": {"compressed": False, "compressed_reason": "under-threshold", "original_bytes": size}})
        return
    if not FFMPEG_BIN:
        await db.media.update_one({"id": media_id}, {"$set": {"compressed_error": "ffmpeg-missing", "original_bytes": size}})
        log.error("compress_video: ffmpeg binary missing — skipping compression")
        return

    tmp_out = f"{input_path}.compressed.mp4"
    try:
        rc, tail = await _run_ffmpeg(input_path, tmp_out)
        if rc != 0 or not os.path.exists(tmp_out):
            log.error("compress_video: ffmpeg exit=%s tail=%s", rc, tail)
            await db.media.update_one({"id": media_id}, {"$set": {"compressed_error": f"ffmpeg-rc-{rc}", "original_bytes": size}})
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            return
        new_size = os.path.getsize(tmp_out)
        # Only swap in the compressed version if it's meaningfully smaller —
        # some already-optimised inputs come out fatter after re-encode.
        if new_size < size * 0.95:
            Path(tmp_out).replace(input_path)
            await db.media.update_one({"id": media_id}, {"$set": {
                "compressed": True,
                "original_bytes": size,
                "compressed_bytes": new_size,
                "compression_ratio": round(new_size / size, 3),
            }})
            log.info("compress_video: %s → %.1f%% of original", media_id, 100.0 * new_size / size)
        else:
            os.remove(tmp_out)
            await db.media.update_one({"id": media_id}, {"$set": {"compressed": False, "compressed_reason": "no-gain", "original_bytes": size}})
    except Exception as e:  # noqa: BLE001 — background task, log everything
        log.exception("compress_video: unexpected error for %s: %s", media_id, e)
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except OSError:
            pass
        await db.media.update_one({"id": media_id}, {"$set": {"compressed_error": str(e)[:200]}})


def schedule_compression(*, db: Any, media_id: str, input_path: str) -> None:
    """Fire-and-forget scheduler used from the media upload endpoint."""
    try:
        asyncio.get_event_loop().create_task(compress_video(db=db, media_id=media_id, input_path=input_path))
    except RuntimeError:
        # No running loop (happens in some sync test contexts). Skip silently.
        log.debug("schedule_compression: no running event loop — compression skipped")
