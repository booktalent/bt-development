"""
Elite Concierge Chat — priority-queue support channel for Platinum + Elite artists.

Design choices (kept minimal on purpose):
  • REST-only (client polls every ~10-15s). Support conversations are low
    frequency so we don't need WebSockets and can piggyback on the existing
    Nginx `/api/*` proxy without adding new WS routes.
  • One thread per artist. Reopening a closed one is idempotent.
  • Admins see all threads sorted by priority (elite → platinum → other) then
    last_message_at. Any lower-tier artist that somehow reaches the endpoint
    gets a 403 (feature gate).

Collections
-----------
concierge_threads   { id, artist_id, plan, priority, status, subject,
                      last_message_at, unread_admin, unread_artist,
                      created_at, updated_at }
concierge_messages  { id, thread_id, sender_id, sender_role, body,
                      created_at, read }
"""
from __future__ import annotations
from datetime import datetime
from typing import Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


PRIORITY = {"elite": 100, "platinum": 80, "gold": 40, "silver": 20, "free": 0}
ALLOWED_PLANS = {"platinum", "elite"}  # <-- feature gate


class MessageBody(BaseModel):
    body: str


class OpenThreadBody(BaseModel):
    subject: str = "General"
    first_message: Optional[str] = None


def make_router(*, db, get_current_user, admin_only, utcnow, new_id, clean, notify_dispatch=None) -> APIRouter:
    r = APIRouter()

    async def _resolve_plan_code(user_id: str) -> str:
        prof = await db.artist_profiles.find_one({"user_id": user_id}, {"plan_code": 1})
        return (prof or {}).get("plan_code") or "free"

    async def _gate(user: dict) -> str:
        if user["role"] not in ("artist", "agency"):
            raise HTTPException(403, "Concierge is for artists / agencies")
        plan = await _resolve_plan_code(user["id"])
        if plan not in ALLOWED_PLANS:
            raise HTTPException(
                403,
                "Elite Concierge is a Platinum/Elite benefit. Upgrade your plan to unlock it.",
            )
        return plan

    # ── ARTIST ENDPOINTS ─────────────────────────────────────────────
    @r.get("/concierge/my-thread")
    async def my_thread(user: dict = Depends(get_current_user)):
        plan = await _gate(user)
        doc = await db.concierge_threads.find_one({"artist_id": user["id"]})
        return {"thread": clean(doc) if doc else None, "plan": plan}

    @r.post("/concierge/open")
    async def open_thread(body: OpenThreadBody, user: dict = Depends(get_current_user)):
        plan = await _gate(user)
        existing = await db.concierge_threads.find_one({"artist_id": user["id"]})
        now = utcnow()
        if existing:
            # Reopen if closed
            if existing.get("status") == "closed":
                await db.concierge_threads.update_one(
                    {"id": existing["id"]},
                    {"$set": {"status": "open", "updated_at": now}},
                )
                existing["status"] = "open"
            return {"thread": clean(existing)}
        tid = new_id()
        doc = {
            "id": tid,
            "artist_id": user["id"],
            "artist_name": user.get("full_name") or user.get("email"),
            "plan": plan,
            "priority": PRIORITY.get(plan, 0),
            "status": "open",
            "subject": body.subject or "General",
            "last_message_at": now,
            "unread_admin": 0,
            "unread_artist": 0,
            "created_at": now,
            "updated_at": now,
        }
        await db.concierge_threads.insert_one(doc)
        if body.first_message:
            await _post_message(tid, user["id"], "artist", body.first_message, now)
        return {"thread": clean(doc)}

    @r.get("/concierge/messages")
    async def list_my_messages(user: dict = Depends(get_current_user), limit: int = 200):
        await _gate(user)
        thread = await db.concierge_threads.find_one({"artist_id": user["id"]})
        if not thread:
            return {"thread": None, "messages": []}
        msgs = await db.concierge_messages.find({"thread_id": thread["id"]}).sort("created_at", 1).limit(limit).to_list(limit)
        # Mark admin-authored messages as read for this artist
        if thread.get("unread_artist"):
            await db.concierge_threads.update_one({"id": thread["id"]}, {"$set": {"unread_artist": 0}})
        return {"thread": clean(thread), "messages": [clean(m) for m in msgs]}

    @r.post("/concierge/send")
    async def artist_send(body: MessageBody, user: dict = Depends(get_current_user)):
        await _gate(user)
        thread = await db.concierge_threads.find_one({"artist_id": user["id"]})
        if not thread or thread.get("status") == "closed":
            raise HTTPException(400, "No open concierge thread — open one first")
        msg = await _post_message(thread["id"], user["id"], "artist", body.body, utcnow())
        # Notify admins
        await db.notifications.insert_one({
            "id": new_id(), "user_id": "__admin__", "type": "concierge",
            "title": f"[{thread['plan'].upper()}] New concierge message",
            "body": f"{thread.get('artist_name')}: {body.body[:120]}",
            "read": False, "created_at": utcnow(),
            "meta": {"thread_id": thread["id"]},
        })
        return {"ok": True, "message": clean(msg)}

    # ── ADMIN ENDPOINTS ──────────────────────────────────────────────
    @r.get("/admin/concierge/threads")
    async def admin_list(_: dict = Depends(admin_only), status: Optional[str] = None, limit: int = 100):
        q: dict = {}
        if status:
            q["status"] = status
        # Priority queue: elite first, then platinum, then most-recent activity
        docs = await db.concierge_threads.find(q).sort([("priority", -1), ("last_message_at", -1)]).limit(limit).to_list(limit)
        return [clean(d) for d in docs]

    @r.get("/admin/concierge/{thread_id}/messages")
    async def admin_read(thread_id: str, _: dict = Depends(admin_only), limit: int = 500):
        thread = await db.concierge_threads.find_one({"id": thread_id})
        if not thread:
            raise HTTPException(404, "Thread not found")
        msgs = await db.concierge_messages.find({"thread_id": thread_id}).sort("created_at", 1).limit(limit).to_list(limit)
        # Mark artist-authored messages as read by admin
        if thread.get("unread_admin"):
            await db.concierge_threads.update_one({"id": thread_id}, {"$set": {"unread_admin": 0}})
        return {"thread": clean(thread), "messages": [clean(m) for m in msgs]}

    @r.post("/admin/concierge/{thread_id}/send")
    async def admin_send(thread_id: str, body: MessageBody, admin: dict = Depends(admin_only)):
        thread = await db.concierge_threads.find_one({"id": thread_id})
        if not thread:
            raise HTTPException(404, "Thread not found")
        msg = await _post_message(thread_id, admin["id"], "admin", body.body, utcnow())
        # In-app notification (always fires)
        await db.notifications.insert_one({
            "id": new_id(), "user_id": thread["artist_id"], "type": "concierge",
            "title": "🎩 Concierge replied",
            "body": body.body[:120], "read": False, "created_at": utcnow(),
        })
        # Multi-channel — email + WhatsApp fire when provider keys are set;
        # fall back to a mock-log row otherwise so admins can audit.
        if notify_dispatch:
            try:
                artist = await db.users.find_one({"id": thread["artist_id"]})
                if artist:
                    plan = thread.get("plan", "elite")
                    sla_hours = {"elite": 2, "platinum": 6}.get(plan, 24)
                    await notify_dispatch(
                        db,
                        user_id=thread["artist_id"],
                        event="concierge_reply",
                        channels=["email", "whatsapp", "in_app"],
                        email=artist.get("email"),
                        phone=artist.get("phone"),
                        ctx={
                            "title": "🎩 BookTalent Concierge replied to your ticket",
                            "body": f"Subject: {thread.get('subject', 'General')}\n\n{body.body}\n\n— BookTalent Support (SLA: {sla_hours}h)",
                            "artist_name": (artist.get("full_name") or artist.get("email", "").split("@")[0]),
                            "subject": thread.get("subject", "General"),
                            "reply_body": body.body[:400],
                            "plan": plan.upper(),
                            "sla_hours": sla_hours,
                            "thread_id": thread_id,
                        },
                    )
            except Exception as e:
                import logging
                logging.getLogger("booktalent.concierge").warning("notify_dispatch failed: %s", e)
        return {"ok": True, "message": clean(msg)}

    @r.post("/admin/concierge/{thread_id}/close")
    async def admin_close(thread_id: str, _: dict = Depends(admin_only)):
        r_ = await db.concierge_threads.update_one({"id": thread_id}, {"$set": {"status": "closed", "updated_at": utcnow()}})
        if r_.matched_count == 0:
            raise HTTPException(404, "Thread not found")
        return {"ok": True}

    # ── SHARED HELPER ────────────────────────────────────────────────
    async def _post_message(thread_id: str, sender_id: str, sender_role: str, text: str, now):
        text = (text or "").strip()
        if not text:
            raise HTTPException(400, "Empty message")
        if len(text) > 4000:
            raise HTTPException(400, "Message too long (max 4000)")
        msg = {
            "id": new_id(),
            "thread_id": thread_id,
            "sender_id": sender_id,
            "sender_role": sender_role,
            "body": text,
            "created_at": now,
            "read": False,
        }
        await db.concierge_messages.insert_one(msg)
        # Bump unread counters + last_message_at
        unread_field = "unread_admin" if sender_role == "artist" else "unread_artist"
        await db.concierge_threads.update_one(
            {"id": thread_id},
            {"$set": {"last_message_at": now, "updated_at": now}, "$inc": {unread_field: 1}},
        )
        return msg

    return r
