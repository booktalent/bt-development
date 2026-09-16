"""
Live chat — WebSocket based 1-1 messaging tied to a booking.

Endpoint:    /api/ws/chat/{booking_id}?token=<jwt>
Persistence: db.chat_messages
REST:        GET  /api/chat/{booking_id}/messages
             POST /api/chat/{booking_id}/messages   (REST fallback)
             POST /api/chat/{booking_id}/read        (mark all as read)
"""
from __future__ import annotations

import os
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from jwt import decode as jwt_decode, PyJWTError
from pydantic import BaseModel

log = logging.getLogger("booktalent.chat")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def clean(d):
    if not d:
        return d
    d.pop("_id", None)
    return d


class ChatMessageBody(BaseModel):
    content: str
    type: str = "text"  # text | system | image-ref


class ConnectionManager:
    """In-process room manager. Keyed by booking_id → set of (ws, user_id).

    If REDIS_URL is set, also fans out via Redis pubsub so multiple replicas
    of the API can share broadcasts. Otherwise stays in-process (single replica).
    """
    def __init__(self):
        self.rooms: Dict[str, Set[tuple]] = {}
        self._redis = None
        self._redis_url = os.environ.get("REDIS_URL", "").strip()
        self._pubsub_task = None
        self._channel = "booktalent:chat"
        # Lazy: only connect when first asked
        self._redis_init_attempted = False

    async def _ensure_redis(self):
        if self._redis_init_attempted or not self._redis_url:
            return
        self._redis_init_attempted = True
        try:
            import redis.asyncio as redis_async  # type: ignore
            self._redis = await redis_async.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            # Subscriber loop
            import asyncio as _asyncio
            self._pubsub_task = _asyncio.create_task(self._pubsub_loop())
            log.info("ChatBox Redis pubsub enabled @ %s", self._redis_url)
        except Exception as e:
            log.warning("Redis pubsub not enabled (%s) — in-process only", e)
            self._redis = None

    async def _pubsub_loop(self):
        import json as _json
        pub = self._redis.pubsub()
        await pub.subscribe(self._channel)
        async for msg in pub.listen():
            if msg["type"] != "message":
                continue
            try:
                payload = _json.loads(msg["data"])
                room = payload.pop("__room", None)
                origin = payload.pop("__origin", None)
                if not room or origin == os.getpid():
                    continue
                await self._local_broadcast(room, payload)
            except Exception:
                continue

    async def connect(self, room: str, ws: WebSocket, user_id: str):
        await self._ensure_redis()
        await ws.accept()
        self.rooms.setdefault(room, set()).add((ws, user_id))

    def disconnect(self, room: str, ws: WebSocket, user_id: str):
        if room in self.rooms:
            self.rooms[room].discard((ws, user_id))
            if not self.rooms[room]:
                self.rooms.pop(room, None)

    async def _local_broadcast(self, room: str, payload: dict, exclude_ws: Optional[WebSocket] = None):
        dead = []
        for ws, _uid in list(self.rooms.get(room, [])):
            if ws is exclude_ws:
                continue
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append((ws, _uid))
        for ws, uid in dead:
            self.disconnect(room, ws, uid)

    async def broadcast(self, room: str, payload: dict, exclude_ws: Optional[WebSocket] = None):
        await self._local_broadcast(room, payload, exclude_ws=exclude_ws)
        # Fan out to other replicas via Redis (if enabled)
        if self._redis:
            try:
                fan_payload = dict(payload)
                fan_payload["__room"] = room
                fan_payload["__origin"] = os.getpid()
                await self._redis.publish(self._channel, json.dumps(fan_payload))
            except Exception:
                pass

    def participants(self, room: str) -> List[str]:
        return list({uid for _, uid in self.rooms.get(room, set())})


def _is_chat_unlocked(booking: dict) -> bool:
    """Chat is locked until the customer pays the Platform Service Fee + GST.

    Unlocked once `payment_status` leaves "unpaid" (token_paid, completed, refunded)
    OR the booking has progressed past the initial `pending_payment` status — which
    handles legacy bookings created before the payment_status field existed.
    """
    b = booking or {}
    ps = b.get("payment_status")
    status = b.get("status")
    # New gated path: explicit payment success.
    if ps and ps != "unpaid":
        return True
    # Legacy / status-driven path: any booking past pending_payment is implicitly paid.
    if status and status != "pending_payment":
        return True
    return False


def make_chat_router(db, get_current_user) -> APIRouter:
    r = APIRouter()
    manager = ConnectionManager()

    async def _check_access(booking_id: str, user_id: str, role: str, *, enforce_payment: bool = True) -> dict:
        b = await db.bookings.find_one({"id": booking_id})
        if not b:
            raise HTTPException(404, "Booking not found")
        # Iter 91 — Assigned manager can moderate the chat too.
        is_participant = user_id in (b.get("customer_id"), b.get("artist_id"))
        is_manager = role == "manager" and b.get("assigned_manager_id") == user_id
        if role != "admin" and not is_participant and not is_manager:
            raise HTTPException(403, "Not a participant on this booking")
        # Payment gate: customer/artist cannot chat until the platform service fee is paid.
        # Admin + assigned manager always bypass (moderator access / dispute support).
        if enforce_payment and role != "admin" and not is_manager and not _is_chat_unlocked(b):
            raise HTTPException(
                403,
                "Chat Access Denied — Complete Platform Service Fee payment to unlock chat.",
            )
        return b

    @r.get("/chat/{booking_id}/access")
    async def chat_access(booking_id: str, user: dict = Depends(get_current_user)):
        """Lightweight check used by the UI to decide whether to render the live chat
        or a 'Complete Platform Fee Payment to Unlock Chat' lock card."""
        b = await db.bookings.find_one({"id": booking_id})
        if not b:
            raise HTTPException(404, "Booking not found")
        is_participant = user["id"] in (b.get("customer_id"), b.get("artist_id"))
        is_manager = user["role"] == "manager" and b.get("assigned_manager_id") == user["id"]
        if user["role"] != "admin" and not is_participant and not is_manager:
            raise HTTPException(403, "Not a participant on this booking")
        unlocked = _is_chat_unlocked(b) or user["role"] == "admin" or is_manager
        return {
            "enabled": unlocked,
            "payment_status": b.get("payment_status") or "unpaid",
            "booking_status": b.get("status"),
            "reason": None if unlocked else "Chat will be available after successful payment of the Platform Service Fee.",
        }

    @r.get("/chat/{booking_id}/messages")
    async def list_messages(booking_id: str, limit: int = 200, user: dict = Depends(get_current_user)):
        await _check_access(booking_id, user["id"], user["role"])
        msgs = await db.chat_messages.find({"booking_id": booking_id}).sort("created_at", 1).to_list(limit)
        return [clean(m) for m in msgs]

    @r.post("/chat/{booking_id}/messages")
    async def post_message(booking_id: str, body: ChatMessageBody, user: dict = Depends(get_current_user)):
        booking = await _check_access(booking_id, user["id"], user["role"])
        raw = body.content[:4000]
        # SEC-001 — Contact-masking on the live booking chat. Builds a
        # thread-shaped dict so the shared helper enforces on Service
        # artists exactly as it does for chat_v2.
        visible = raw
        try:
            from routes.req_batch_6 import redact_for_thread
            _thread_shape = {
                "id": booking_id,
                "booking_id": booking_id,
                "artist_id": booking.get("artist_id"),
                "customer_id": booking.get("customer_id"),
                "manager_id": booking.get("manager_id"),
                "is_managed": bool(booking.get("is_managed") or booking.get("is_service_artist")),
            }
            visible, _hits = await redact_for_thread(
                db, thread=_thread_shape,
                sender_id=user["id"], sender_role=user.get("role"),
                body_original=raw,
            )
        except Exception:  # noqa: BLE001
            # Fail-closed on Service-artist bookings: if the masker breaks,
            # drop the message entirely rather than leak contact info.
            if booking.get("is_service_artist") or booking.get("is_managed"):
                raise HTTPException(503, "Message could not be verified. Please try again in a moment.")
        msg = {
            "id": new_id(),
            "booking_id": booking_id,
            "sender_id": user["id"],
            "sender_role": user["role"],
            "sender_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("email", ""),
            "content": visible,
            "content_original": raw,
            "type": body.type,
            "read_by": [user["id"]],
            "created_at": utcnow(),
        }
        await db.chat_messages.insert_one(msg)
        # Push to anyone live in the room
        await manager.broadcast(booking_id, {"event": "message", "message": clean(dict(msg))})
        # Off-line notification: write an in-app row for the other party
        other = booking["artist_id"] if user["id"] == booking["customer_id"] else booking["customer_id"]
        if other and other not in manager.participants(booking_id):
            try:
                await db.notifications.insert_one({
                    "id": new_id(),
                    "user_id": other,
                    "type": "chat",
                    "title": f"New message from {msg['sender_name']}",
                    "body": visible[:120],
                    "link": f"/dashboard/bookings/{booking_id}",
                    "read": False,
                    "created_at": utcnow(),
                })
            except Exception:
                pass
        return clean(dict(msg))

    @r.post("/chat/{booking_id}/read")
    async def mark_read(booking_id: str, user: dict = Depends(get_current_user)):
        await _check_access(booking_id, user["id"], user["role"])
        result = await db.chat_messages.update_many(
            {"booking_id": booking_id, "read_by": {"$ne": user["id"]}},
            {"$push": {"read_by": user["id"]}},
        )
        await manager.broadcast(booking_id, {"event": "read", "by": user["id"], "at": utcnow()})
        return {"ok": True, "updated": result.modified_count}

    @r.websocket("/ws/chat/{booking_id}")
    async def ws_chat(websocket: WebSocket, booking_id: str, token: str | None = Query(None)):
        # Auth priority: httpOnly cookie (preferred, XSS-safe) → ?token= query
        # (legacy). Browsers send same-origin cookies with WS handshakes
        # automatically, so the cookie path is the primary one going forward.
        auth_token = token or websocket.cookies.get("access_token")
        if not auth_token:
            await websocket.close(code=4001)
            return
        try:
            payload = jwt_decode(auth_token, os.environ["JWT_SECRET"], algorithms=["HS256"])
            user_id = payload.get("sub")
        except PyJWTError:
            await websocket.close(code=4001)
            return
        if not user_id:
            await websocket.close(code=4001)
            return
        user = await db.users.find_one({"id": user_id})
        if not user:
            await websocket.close(code=4001)
            return
        # Booking + access check
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            await websocket.close(code=4004)
            return
        if user.get("role") != "admin" and user_id not in (booking.get("customer_id"), booking.get("artist_id")):
            await websocket.close(code=4003)
            return
        # Payment gate — chat locked until Platform Service Fee + GST is paid.
        if user.get("role") != "admin" and not _is_chat_unlocked(booking):
            await websocket.close(code=4402, reason="payment_required")
            return

        await manager.connect(booking_id, websocket, user_id)
        await manager.broadcast(booking_id, {"event": "presence", "joined": user_id, "participants": manager.participants(booking_id)})
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                ev = data.get("event")
                if ev == "message":
                    content = (data.get("content") or "")[:4000]
                    if not content.strip():
                        continue
                    # SEC-001 — Contact-masking on WebSocket chat path too.
                    visible = content
                    try:
                        from routes.req_batch_6 import redact_for_thread
                        _thread_shape = {
                            "id": booking_id,
                            "booking_id": booking_id,
                            "artist_id": booking.get("artist_id"),
                            "customer_id": booking.get("customer_id"),
                            "manager_id": booking.get("manager_id"),
                            "is_managed": bool(booking.get("is_managed") or booking.get("is_service_artist")),
                        }
                        visible, _hits = await redact_for_thread(
                            db, thread=_thread_shape,
                            sender_id=user_id, sender_role=user.get("role"),
                            body_original=content,
                        )
                    except Exception:
                        # Fail-closed on Service artist bookings.
                        if booking.get("is_service_artist") or booking.get("is_managed"):
                            continue
                    msg = {
                        "id": new_id(),
                        "booking_id": booking_id,
                        "sender_id": user_id,
                        "sender_role": user.get("role"),
                        "sender_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("email", ""),
                        "content": visible,
                        "content_original": content,
                        "type": data.get("type") or "text",
                        "read_by": [user_id],
                        "created_at": utcnow(),
                    }
                    await db.chat_messages.insert_one(msg)
                    await manager.broadcast(booking_id, {"event": "message", "message": clean(dict(msg))})
                    # Off-line side: write in-app notification
                    other = booking["artist_id"] if user_id == booking["customer_id"] else booking["customer_id"]
                    if other and other not in manager.participants(booking_id):
                        try:
                            await db.notifications.insert_one({
                                "id": new_id(),
                                "user_id": other,
                                "type": "chat",
                                "title": f"New message from {msg['sender_name']}",
                                "body": visible[:120],
                                "link": f"/dashboard/bookings/{booking_id}",
                                "read": False,
                                "created_at": utcnow(),
                            })
                        except Exception:
                            pass
                elif ev == "typing":
                    # Ephemeral — just broadcast, don't store
                    await manager.broadcast(booking_id, {"event": "typing", "by": user_id, "name": f"{user.get('first_name', '')}".strip() or "Someone"}, exclude_ws=websocket)
                elif ev == "read":
                    await db.chat_messages.update_many(
                        {"booking_id": booking_id, "read_by": {"$ne": user_id}},
                        {"$push": {"read_by": user_id}},
                    )
                    await manager.broadcast(booking_id, {"event": "read", "by": user_id, "at": utcnow()})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.warning("chat ws error: %s", e)
        finally:
            manager.disconnect(booking_id, websocket, user_id)
            await manager.broadcast(booking_id, {"event": "presence", "left": user_id, "participants": manager.participants(booking_id)})

    return r
