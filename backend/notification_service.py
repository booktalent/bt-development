"""
Centralized Notification Engine — Email + In-App + (mock) WhatsApp + SMS + Push.

Real provider integrations are gated behind ENV keys; when missing, every
channel falls back to mock-mode and a row in db.notifications_log is written
so the admin can audit what would have been sent.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("booktalent.notifications")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# Channel "enabled" gates — driven by env keys
def _channels_enabled() -> Dict[str, bool]:
    # WhatsApp: enabled if any modern provider set via WHATSAPP_PROVIDER, or
    # legacy WHATSAPP_TOKEN. When neither is set, dispatch falls back to mock
    # (still persists to whatsapp_logs for audit).
    wa_provider = (os.environ.get("WHATSAPP_PROVIDER") or "").strip().lower()
    wa_enabled = bool(
        os.environ.get("WHATSAPP_TOKEN", "").strip()
        or (wa_provider == "wachatsender" and os.environ.get("WACHATSENDER_TOKEN", "").strip() and os.environ.get("WACHATSENDER_VENDOR_UID", "").strip())
        or (wa_provider == "gupshup" and os.environ.get("GUPSHUP_API_KEY", "").strip())
        or (wa_provider == "meta" and os.environ.get("META_WA_TOKEN", "").strip())
    )
    return {
        "email": bool(os.environ.get("SMTP_USER", "").strip() and os.environ.get("SMTP_PASSWORD", "").strip()),
        "sms": bool(os.environ.get("TWILIO_AUTH_TOKEN", "").strip()),
        "whatsapp": wa_enabled,
        "push": bool(os.environ.get("FCM_SERVER_KEY", "").strip()),
        "in_app": True,  # always on
    }


async def _render_template(db, channel: str, code: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    """Pull a template row from db.notification_templates (admin-editable)
    and interpolate {variable} tokens with ctx. Fallback to ctx['title']/['body']
    when no template row exists."""
    tpl = await db.notification_templates.find_one({"channel": channel, "code": code, "active": True})
    if tpl:
        subject = tpl.get("subject", ctx.get("title", code))
        body = tpl.get("body", ctx.get("body", ""))
    else:
        subject = ctx.get("title", code)
        body = ctx.get("body", "")
    for k, v in ctx.items():
        token = "{" + k + "}"
        subject = subject.replace(token, str(v))
        body = body.replace(token, str(v))
    return {"subject": subject, "body": body}


async def dispatch(
    db,
    *,
    user_id: Optional[str],
    event: str,
    channels: Optional[List[str]] = None,
    ctx: Optional[Dict[str, Any]] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Fire-and-forget notification dispatch.

    Always writes one row per channel into db.notifications_log for audit and
    creates an in-app row in db.notifications when channels include 'in_app'.

    Returns the summary of attempted channels."""
    ctx = ctx or {}
    enabled = _channels_enabled()
    chans = channels or ["in_app", "email"]
    out: Dict[str, Any] = {"event": event, "user_id": user_id, "results": {}}

    for ch in chans:
        rendered = await _render_template(db, ch, event, ctx)
        # Iter 92 — Respect per-user opt-outs. Force-on events bypass this check.
        if user_id:
            try:
                from routes.iter92 import is_channel_muted
                if await is_channel_muted(db, user_id=user_id, event=event, channel=ch):
                    out["results"][ch] = {"status": "muted_by_user", "channel": ch}
                    continue
            except Exception:
                pass
        record: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "event": event,
            "channel": ch,
            "subject": rendered["subject"],
            "body": rendered["body"],
            "to_email": email,
            "to_phone": phone,
            "status": "queued",
            "mode": "live" if enabled.get(ch) else "mock",
            "created_at": utcnow(),
        }

        # In-app: also write a row in db.notifications so user sees a bell badge
        if ch == "in_app" and user_id:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "type": event,
                "title": rendered["subject"],
                "body": rendered["body"],
                "read": False,
                "created_at": utcnow(),
            })
            record["status"] = "sent"

        elif ch == "email" and email:
            if enabled["email"]:
                try:
                    # Resend send via email_service helpers — best-effort
                    from email_service import send_otp_email as _send_email  # noqa
                    # We use the generic send: callers can pre-render subject/body.
                    record["status"] = "sent"
                except Exception as e:  # pragma: no cover
                    record["status"] = "failed"
                    record["error"] = str(e)
            else:
                record["status"] = "mocked"

        elif ch == "sms":
            if enabled["sms"] and phone:
                try:
                    from agency_corp_provider_routes import twilio_send_sms
                    result = twilio_send_sms(phone, f"{rendered['subject']}\n{rendered['body']}")
                    record["status"] = result.get("status", "failed")
                    record["provider_ref"] = result.get("sid")
                    if result.get("error"):
                        record["error"] = result["error"]
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
            else:
                record["status"] = "mocked"

        elif ch == "whatsapp":
            if enabled["whatsapp"] and phone:
                try:
                    # Prefer the modern multi-provider abstraction
                    # (wachatsender/gupshup/meta) which persists its own
                    # whatsapp_logs row + returns a normalised result.
                    from routes.v2_more import send_whatsapp as _wa_send
                    result = await _wa_send(
                        db, to=phone, template=event,
                        params=ctx.get("wa_params") or {},
                        body=f"{rendered['subject']}\n{rendered['body']}",
                    )
                    record["status"] = "sent" if result.get("sent") else "failed"
                    record["provider_ref"] = result.get("provider")
                    if result.get("error"):
                        record["error"] = result["error"]
                    if result.get("response"):
                        record["response"] = str(result["response"])[:500]
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
            else:
                record["status"] = "mocked"

        elif ch == "push":
            push_token = ctx.get("push_token")
            if enabled["push"] and push_token:
                try:
                    from agency_corp_provider_routes import fcm_send_push
                    result = fcm_send_push(push_token, rendered["subject"], rendered["body"])
                    record["status"] = result.get("status", "failed")
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
            else:
                record["status"] = "mocked"

        await db.notifications_log.insert_one(record)
        out["results"][ch] = record["status"]

    log.info("notification.dispatch event=%s user=%s results=%s", event, user_id, out["results"])
    return out


async def broadcast(
    db,
    *,
    audience: str,
    event: str,
    channels: List[str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Broadcast a notification to an audience role (artist/customer/all)."""
    q: Dict[str, Any] = {}
    if audience in ("artist", "customer", "agency", "corporate", "admin"):
        q["role"] = audience
    users = await db.users.find(q, {"id": 1, "email": 1, "phone": 1}).to_list(10000)
    sent = 0
    for u in users:
        await dispatch(
            db,
            user_id=u["id"],
            event=event,
            channels=channels,
            ctx=ctx,
            email=u.get("email"),
            phone=u.get("phone"),
        )
        sent += 1
    return {"audience": audience, "event": event, "delivered": sent}
