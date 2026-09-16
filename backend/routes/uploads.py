"""
Sprint 2 — Chunked filesystem media uploads.

New parallel upload path that:
  • Streams up to 5 GB files to disk in resumable chunks
  • Stores files under MEDIA_ROOT (default /app/backend/uploads/media)
  • Generates thumbnails on image finalize (Pillow)
  • Generates video thumbnails via ffmpeg WHEN ffmpeg is installed
     (see /app/deploy/README-almalinux.md — `dnf install -y ffmpeg`)
  • Falls back gracefully if ffmpeg is missing — no crash
  • Preserves the legacy `/api/media/upload` (base64) endpoint untouched
  • Uses UUID paths so filenames are non-guessable and safe on any FS

Routes exposed (all under /api):
  POST   /uploads/init                 — reserve an upload_id + declare metadata
  PUT    /uploads/{upload_id}/chunk    — send one chunk (index=N in query)
  POST   /uploads/{upload_id}/complete — reassemble, thumbnail, insert media doc
  GET    /uploads/{upload_id}/status   — resume / progress query
  GET    /media/{media_id}/file        — stream original file (auth for private types)
"""
from __future__ import annotations

import os
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel


# ── Config ────────────────────────────────────────────────────────────────────
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT") or "/app/uploads/media")  # noqa: ephemeral-upload-storage
TMP_ROOT = Path(os.environ.get("MEDIA_TMP") or "/app/uploads/tmp")  # noqa: ephemeral-upload-storage
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
TMP_ROOT.mkdir(parents=True, exist_ok=True)

MAX_FILE_BYTES = int(os.environ.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024 * 1024))  # 5 GB
CHUNK_SIZE = int(os.environ.get("UPLOAD_CHUNK_SIZE", 4 * 1024 * 1024))  # 4 MB
ALLOWED_TYPES = ("gallery", "video", "audio", "reel", "portfolio", "brand_deck", "review")


class InitBody(BaseModel):
    filename: str
    size: int
    mime: str
    type: str = "gallery"
    title: Optional[str] = None


def _sanitize_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext and len(ext) <= 8 else ".bin"


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _generate_video_thumb(video_path: Path, out_path: Path) -> bool:
    """Extract a poster frame at t=1s. Returns True on success, False otherwise.
    Silently returns False if ffmpeg is missing so the upload flow never breaks."""
    if not _ffmpeg_available():
        return False
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                "-ss", "1", "-i", str(video_path),
                "-vframes", "1", "-vf", "scale=400:-1", str(out_path),
            ],
            check=True, timeout=30,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def make_router(
    *,
    db,
    get_current_user: Callable,
    utcnow: Callable,
    new_id: Callable,
    clean: Callable,
    log,
    compress_image: Callable,
    make_thumbnail: Callable,
) -> APIRouter:
    r = APIRouter()

    # ── 1. INIT ──────────────────────────────────────────────────────────────
    @r.post("/uploads/init")
    async def upload_init(body: InitBody, user: dict = Depends(get_current_user)):
        if body.size <= 0 or body.size > MAX_FILE_BYTES:
            raise HTTPException(413, f"File size must be between 1 byte and {MAX_FILE_BYTES // (1024*1024)} MB")
        if body.type not in ALLOWED_TYPES:
            raise HTTPException(400, f"Unknown media type: {body.type}")

        upload_id = new_id()
        ext = _sanitize_ext(body.filename)
        session_dir = TMP_ROOT / upload_id
        session_dir.mkdir(parents=True, exist_ok=True)

        await db.upload_sessions.insert_one({
            "id": upload_id,
            "user_id": user["id"],
            "filename": body.filename[:200],
            "size": body.size,
            "mime": body.mime[:100],
            "type": body.type,
            "title": (body.title or "")[:200],
            "ext": ext,
            "received_bytes": 0,
            "chunk_count": 0,
            "status": "in_progress",
            "created_at": utcnow(),
        })

        expected_chunks = (body.size + CHUNK_SIZE - 1) // CHUNK_SIZE
        return {
            "upload_id": upload_id,
            "chunk_size": CHUNK_SIZE,
            "expected_chunks": expected_chunks,
            "max_bytes": MAX_FILE_BYTES,
        }

    # ── 2. CHUNK ─────────────────────────────────────────────────────────────
    @r.put("/uploads/{upload_id}/chunk")
    async def upload_chunk(upload_id: str, index: int, request: Request, user: dict = Depends(get_current_user)):
        session = await db.upload_sessions.find_one({"id": upload_id})
        if not session or session["user_id"] != user["id"]:
            raise HTTPException(404, "Upload session not found")
        if session["status"] not in ("in_progress",):
            raise HTTPException(400, f"Session already {session['status']}")
        if index < 0 or index > 100000:
            raise HTTPException(400, "Invalid chunk index")

        session_dir = TMP_ROOT / upload_id
        if not session_dir.exists():
            raise HTTPException(404, "Session storage missing")

        chunk_path = session_dir / f"part_{index:06d}"

        # If the chunk was already fully received (resume-friendly), short-circuit
        if chunk_path.exists() and chunk_path.stat().st_size > 0:
            return {"ok": True, "resumed": True, "received_bytes": session["received_bytes"]}

        # Stream the request body to disk chunk-by-chunk to avoid loading everything in RAM
        received = 0
        buffered = bytearray()
        async for piece in request.stream():
            if not piece:
                continue
            buffered.extend(piece)
            received += len(piece)
            # Guard against a client sending a chunk >2× the declared chunk_size
            if received > CHUNK_SIZE * 2:
                raise HTTPException(413, "Chunk exceeds size limit")
        chunk_path.write_bytes(bytes(buffered))

        # Also guard against the total exceeding declared file size
        new_total = session["received_bytes"] + received
        if new_total > session["size"] + CHUNK_SIZE:
            chunk_path.unlink(missing_ok=True)
            raise HTTPException(413, "Aggregate size exceeds declared file size")

        await db.upload_sessions.update_one(
            {"id": upload_id},
            {"$inc": {"received_bytes": received, "chunk_count": 1}, "$set": {"last_chunk_at": utcnow()}},
        )
        return {"ok": True, "received_bytes": new_total}

    # ── 3. COMPLETE ──────────────────────────────────────────────────────────
    @r.post("/uploads/{upload_id}/complete")
    async def upload_complete(upload_id: str, user: dict = Depends(get_current_user)):
        session = await db.upload_sessions.find_one({"id": upload_id})
        if not session or session["user_id"] != user["id"]:
            raise HTTPException(404, "Upload session not found")
        if session["status"] != "in_progress":
            raise HTTPException(400, f"Session already {session['status']}")

        session_dir = TMP_ROOT / upload_id
        chunk_files = sorted(session_dir.glob("part_*"))
        if not chunk_files:
            raise HTTPException(400, "No chunks received")

        # Reassemble into MEDIA_ROOT
        media_id = new_id()
        subdir = MEDIA_ROOT / user["id"]
        subdir.mkdir(parents=True, exist_ok=True)
        final_path = subdir / f"{media_id}{session['ext']}"

        try:
            with open(final_path, "wb") as out:
                for cf in chunk_files:
                    with open(cf, "rb") as f:
                        while True:
                            b = f.read(1024 * 1024)
                            if not b:
                                break
                            out.write(b)
        except Exception as e:
            log.exception("Failed to reassemble upload %s: %s", upload_id, e)
            raise HTTPException(500, "Failed to reassemble upload")
        finally:
            shutil.rmtree(session_dir, ignore_errors=True)

        final_size = final_path.stat().st_size
        if abs(final_size - session["size"]) > CHUNK_SIZE:
            final_path.unlink(missing_ok=True)
            await db.upload_sessions.update_one({"id": upload_id}, {"$set": {"status": "failed"}})
            raise HTTPException(400, f"Size mismatch — declared {session['size']}, got {final_size}")

        # Generate thumbnail
        thumb_path = None
        mime = session["mime"]
        if mime.startswith("image/"):
            try:
                with open(final_path, "rb") as f:
                    tbytes, _tmime = make_thumbnail(f.read(), mime)
                if tbytes:
                    tp = subdir / f"{media_id}-thumb.jpg"
                    tp.write_bytes(tbytes)
                    thumb_path = str(tp)
            except Exception as e:
                log.warning("Image thumbnail failed for %s: %s", media_id, e)
        elif mime.startswith("video/"):
            try:
                tp = subdir / f"{media_id}-thumb.jpg"
                # Run ffmpeg off the event loop so we don't block
                loop = asyncio.get_running_loop()
                ok = await loop.run_in_executor(None, _generate_video_thumb, final_path, tp)
                if ok:
                    thumb_path = str(tp)
            except Exception as e:
                log.warning("Video thumbnail failed for %s: %s", media_id, e)

        # Insert media doc — new schema uses `path` and `thumb_path` (filesystem)
        # instead of `data`/`thumb` (base64). Both schemas coexist; readers pick.
        media_doc = {
            "id": media_id,
            "user_id": user["id"],
            "type": session["type"],
            "mime": mime,
            "size": final_size,
            "title": session.get("title") or session["filename"],
            "path": str(final_path),
            "thumb_path": thumb_path,
            "storage": "filesystem",   # discriminator for legacy 'data' vs new 'path'
            "is_featured": False,
            "order": 0,
            "created_at": utcnow(),
        }
        await db.media.insert_one(media_doc)
        await db.upload_sessions.update_one(
            {"id": upload_id},
            {"$set": {"status": "completed", "media_id": media_id, "completed_at": utcnow()}},
        )

        # Never return path / thumb_path (leak-safe)
        return {
            "id": media_id,
            "type": media_doc["type"],
            "mime": mime,
            "size": final_size,
            "title": media_doc["title"],
            "has_thumb": bool(thumb_path),
        }

    # ── 4. STATUS / RESUME ───────────────────────────────────────────────────
    @r.get("/uploads/{upload_id}/status")
    async def upload_status(upload_id: str, user: dict = Depends(get_current_user)):
        session = await db.upload_sessions.find_one({"id": upload_id})
        if not session or session["user_id"] != user["id"]:
            raise HTTPException(404, "Upload session not found")
        return {
            "id": session["id"],
            "status": session["status"],
            "received_bytes": session["received_bytes"],
            "size": session["size"],
            "chunk_count": session["chunk_count"],
            "media_id": session.get("media_id"),
        }

    # ── 5. SERVE FILE ────────────────────────────────────────────────────────
    @r.get("/media/{media_id}/file")
    async def media_file(media_id: str, request: Request):
        """Stream the original file. Portfolio media (gallery/video/reel) is
        public; KYC / review / contract / agreement types are gated to the
        owner or an admin with KYC permissions (SEC-001)."""
        doc = await db.media.find_one({"id": media_id})
        if not doc:
            raise HTTPException(404, "Not found")
        if doc.get("storage") != "filesystem" or not doc.get("path"):
            raise HTTPException(404, "Not available via file endpoint (legacy media)")
        # SEC-001 / SEC-003 gate for private types.
        mtype = (doc.get("type") or "").lower()
        if mtype in {"kyc", "review", "contract", "agreement", "chat"}:
            auth = request.headers.get("Authorization") or ""
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not token:
                raise HTTPException(401, "Authentication required for this asset.")
            try:
                import jwt as _jwt
                payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
                caller = await db.users.find_one({"id": payload.get("sub")})
            except Exception:
                raise HTTPException(401, "Invalid or expired token.")
            if not caller:
                raise HTTPException(401, "Invalid session.")
            owner = doc.get("user_id") == caller.get("id")
            perms = (
                caller.get("perms")
                or caller.get("permissions")
                or caller.get("admin_permissions")
                or []
            )
            kyc_admin = caller.get("role") == "admin" or "kyc.manage" in perms or "kyc.view" in perms
            # Chat participants (customer/artist/manager) may view.
            chat_participant = False
            if mtype == "chat":
                thread = None
                if doc.get("thread_id"):
                    thread = await db.chat_v2_threads.find_one({"id": doc["thread_id"]})
                if not thread and doc.get("booking_id"):
                    thread = await db.chat_v2_threads.find_one({"booking_id": doc["booking_id"]})
                if thread and caller.get("id") in {thread.get("customer_id"), thread.get("artist_id"), thread.get("manager_id")}:
                    chat_participant = True
                elif doc.get("booking_id"):
                    bk = await db.bookings.find_one({"id": doc["booking_id"]},
                                                     {"_id": 0, "customer_id": 1, "artist_id": 1, "manager_id": 1}) or {}
                    if caller.get("id") in {bk.get("customer_id"), bk.get("artist_id"), bk.get("manager_id")}:
                        chat_participant = True
            if not (owner or kyc_admin or chat_participant):
                raise HTTPException(403, "You do not have permission to view this asset.")
        p = Path(doc["path"])
        if not p.exists():
            raise HTTPException(410, "File missing on disk")
        return FileResponse(
            p,
            media_type=doc.get("mime") or "application/octet-stream",
            filename=doc.get("title") or p.name,
        )

    return r
