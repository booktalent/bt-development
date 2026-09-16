"""
Feb-2026 Requirement Batch 6.

Adds:
  1. Commercial Deal admin page endpoints (list, per-artist history).
  2. Booking-time deal snapshot helper (stamps % onto booking so future
     rate changes never retroactively affect old bookings).
  3. Contact-masking (redaction) helper for chat — auto-redact phone/
     email in messages when the booking is for a Service artist, plus
     a fire-and-forget Slack alert on any hit.
  4. Deal-change history reader (backed by existing audit_logs rows).
  5. (Bank Preset Column Mapper UI lives client-side — this router only
     exposes the existing CRUD from req_batch_5.)

All helpers are idempotent and safe to call multiple times.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger("req_batch_6")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# (2) Booking-time deal snapshot
# ═══════════════════════════════════════════════════════════════════════
async def build_deal_snapshot(db: AsyncIOMotorDatabase, artist_id: str) -> Dict[str, Any]:
    """Read the artist's current commercial deal and return a compact
    snapshot dict for embedding into a booking document.
    Safe to call in any create-booking path — never raises.
    """
    try:
        prof = await db.artist_profiles.find_one(
            {"user_id": artist_id},
            {"_id": 0, "artist_type": 1, "is_service_artist": 1,
             "percentage_deal": 1, "commercial_deal_set_at": 1},
        ) or {}
    except Exception:  # pragma: no cover
        prof = {}
    return {
        "artist_type": prof.get("artist_type") or ("service" if prof.get("is_service_artist") else "normal"),
        "is_service_artist": bool(prof.get("is_service_artist")),
        "percentage_deal": float(prof.get("percentage_deal") or 0),
        "profile_deal_set_at": prof.get("commercial_deal_set_at"),
        "snapshot_at": utcnow(),
    }


async def stamp_deal_snapshot_on_booking(db: AsyncIOMotorDatabase, booking_id: str,
                                          artist_id: str) -> None:
    """Idempotent — writes the snapshot only if the booking doesn't
    already carry one."""
    existing = await db.bookings.find_one({"id": booking_id, "deal_snapshot": {"$exists": True}},
                                           {"_id": 1})
    if existing:
        return
    snap = await build_deal_snapshot(db, artist_id)
    await db.bookings.update_one({"id": booking_id}, {"$set": {"deal_snapshot": snap}})


# ═══════════════════════════════════════════════════════════════════════
# (3) Contact-masking / redaction
# ═══════════════════════════════════════════════════════════════════════
# Deliberately conservative regexes so we don't accidentally mangle
# ordinary chat text.
_PHONE_RE = re.compile(
    # Indian 10-digit mobile (6-9 lead). Handles common visual formats:
    #   9876543210
    #   +91 9876543210 / +91-9876543210
    #   +91 9876 543210 / +91-9876-543210
    #   +91 98765 43210 / 98765 43210
    r"""
    (?:\+?91[\s\-]?|0)?     # optional country / trunk prefix
    [6-9]                    # first mobile digit
    (?:                      # remaining 9 digits with permissive separators
        \d{9}                    #   contiguous:  9876543210
      | \d{3}[\s\-]\d{6}         #   4-6 split:   9876 543210
      | \d{4}[\s\-]\d{5}         #   5-5 split:   98765 43210
      | \d{2}[\s\-]\d{3}[\s\-]\d{4}  # 3-3-4 split
    )
    """,
    re.VERBOSE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_URL_LEAK_RE = re.compile(r"\b(?:wa\.me|whatsapp\.com|t\.me|instagram\.com/direct)\S+", re.IGNORECASE)


# SEC-003 — Bypass-resistant contact masking.
# Adversarial patterns we now cover:
#   1. Full-width / mathematical digits ('9' vs '9') → NFKC normalize
#   2. Spelled-out digits ("nine eight seven six") → collapsed to digits
#   3. "at" / "dot" / "(at)" evasions in emails
#   4. Wide spacing / punctuation between digits (9-8-7-6-5-4-3-2-1-0)
#   5. Zero-width and directional marks stripped

import unicodedata

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]")
_DIGIT_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # common Hindi/Hinglish variants
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4",
    "paanch": "5", "chhe": "6", "chhah": "6", "saat": "7", "aath": "8", "nau": "9",
}
_DIGIT_WORDS_RE = re.compile(r"\b(" + "|".join(_DIGIT_WORDS) + r")\b", re.IGNORECASE)
_AT_OBFUSC_RE = re.compile(r"\s*(?:\[|\()?\s*(?:at|@)\s*(?:\]|\))?\s*", re.IGNORECASE)
_DOT_OBFUSC_RE = re.compile(r"\s*(?:\[|\()?\s*(?:dot|\.)\s*(?:\]|\))?\s*", re.IGNORECASE)


def _normalize_for_scan(text: str) -> str:
    """Aggressively normalize the string so we can spot obfuscated PII.
    We never REPLACE the user's text with this — it's only fed to the
    regexes to detect leaks. The original text is what we sub-in [phone
    hidden] against, so casual chat is untouched."""
    if not text:
        return text
    # 1. NFKC folds full-width digits (９) → ASCII (9), mathematical alnum → ASCII.
    t = unicodedata.normalize("NFKC", text)
    # 2. Strip zero-width & directional invisibles.
    t = _ZERO_WIDTH_RE.sub("", t)
    # 3. Convert digit words to digits so "nine eight seven..." becomes "9876...".
    t = _DIGIT_WORDS_RE.sub(lambda m: _DIGIT_WORDS[m.group(1).lower()], t)
    # 4. Collapse whitespace / dots / hyphens BETWEEN adjacent digits so
    #    "9 8 7 6 5 4 3 2 1 0" or "9.8.7..." become contiguous "9876543210"
    #    that the phone regex catches. Iterate because a single pass only
    #    closes every other gap.
    for _ in range(4):
        new_t = re.sub(r"(\d)[\s\.\-–—_·•]+(\d)", r"\1\2", t)
        if new_t == t:
            break
        t = new_t
    # 5. Reconstruct email obfuscations: "user (at) gmail (dot) com" → "user@gmail.com".
    t = _AT_OBFUSC_RE.sub("@", t)
    t = _DOT_OBFUSC_RE.sub(".", t)
    return t


def redact_contact_info(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Return (redacted_text, hits[]). Hits carry the redacted kind
    and a masked preview for auditing."""
    if not text:
        return text, []
    hits: List[Dict[str, str]] = []
    out = text

    # SEC-003 — Scan a normalized copy for hits. If any match is found in
    # the normalized text, we blanket-mask the ORIGINAL to be safe rather
    # than trying to reverse-map the offsets (fewer edge cases → less bypass
    # surface). Casual text with no leaks stays untouched.
    scan_text = _normalize_for_scan(text)

    def _mask(match_obj, kind: str) -> str:
        raw = match_obj.group(0)
        if kind == "phone":
            trimmed = re.sub(r"\D", "", raw)
            preview = f"…{trimmed[-4:]}" if len(trimmed) >= 4 else "…"
            hits.append({"kind": "phone", "preview": preview})
            return "[phone hidden]"
        if kind == "email":
            local = raw.split("@", 1)[0]
            preview = f"{local[:2]}…@…"
            hits.append({"kind": "email", "preview": preview})
            return "[email hidden]"
        hits.append({"kind": "url", "preview": raw[:24] + "…"})
        return "[link hidden]"

    # Order matters: strip URLs first so we don't double-match a phone
    # number that lives inside a wa.me/… link.
    out = _URL_LEAK_RE.sub(lambda m: _mask(m, "url"), out)
    out = _EMAIL_RE.sub(lambda m: _mask(m, "email"), out)
    out = _PHONE_RE.sub(lambda m: _mask(m, "phone"), out)

    # If the normalized scan surfaces PII the original regexes missed
    # (obfuscated cases), replace the entire message with a hidden marker
    # so we never leak. This is deliberately blunt — bypass attempts get
    # flagged and the message becomes useless to the recipient.
    if scan_text != text:
        extra_hits: List[Dict[str, str]] = []
        _URL_LEAK_RE.sub(lambda m: (extra_hits.append({"kind": "url", "preview": m.group(0)[:24] + "…"}) or "[link hidden]"), scan_text)
        _EMAIL_RE.sub(lambda m: (extra_hits.append({"kind": "email", "preview": (m.group(0).split("@", 1)[0][:2]) + "…@…"}) or "[email hidden]"), scan_text)
        _PHONE_RE.sub(lambda m: (extra_hits.append({"kind": "phone", "preview": "…" + re.sub(r"\D", "", m.group(0))[-4:]}) or "[phone hidden]"), scan_text)
        # Only trigger blunt replacement if the normalized scan found new hits
        # that weren't caught by the direct regex pass.
        original_hit_count = len(hits)
        if extra_hits and (out == text or len(extra_hits) > original_hit_count):
            for h in extra_hits:
                hits.append(h)
            out = "[message hidden — contains contact info]"

    return out, hits


async def should_enforce_masking(db: AsyncIOMotorDatabase, booking_id: str) -> bool:
    """Masking fires when either the booking's deal snapshot OR the
    live artist_profile marks this as a Service artist."""
    bk = await db.bookings.find_one({"id": booking_id},
                                     {"_id": 0, "deal_snapshot": 1, "artist_id": 1}) or {}
    snap = bk.get("deal_snapshot") or {}
    if snap.get("is_service_artist"):
        return True
    aid = bk.get("artist_id")
    if not aid:
        return False
    prof = await db.artist_profiles.find_one({"user_id": aid},
                                              {"_id": 0, "is_service_artist": 1}) or {}
    return bool(prof.get("is_service_artist"))


async def redact_for_thread(db: AsyncIOMotorDatabase, *, thread: Dict[str, Any],
                             sender_id: Optional[str], sender_role: Optional[str],
                             body_original: str) -> Tuple[str, List[Dict[str, str]]]:
    """SEC — thread-anchored variant so masking runs even when the thread
    is not tied to a specific booking yet. Enforces on any thread whose
    linked artist is a Service artist, or any thread marked is_managed."""
    if not body_original:
        return body_original, []

    # Fast path: `is_managed` was set at thread creation time based on
    # the artist's service flag. Fall back to a live lookup only if that
    # flag is missing (legacy threads).
    enforce = bool(thread.get("is_managed"))
    if not enforce:
        aid = thread.get("artist_id")
        if aid:
            prof = await db.artist_profiles.find_one(
                {"user_id": aid}, {"_id": 0, "is_service_artist": 1}) or {}
            enforce = bool(prof.get("is_service_artist"))
    if not enforce:
        return body_original, []

    redacted, hits = redact_contact_info(body_original)
    if not hits:
        return body_original, []

    entity_id = thread.get("booking_id") or thread.get("id") or "chat"
    # Fire-and-forget alert
    try:
        from routes.iter89 import notify_slack
        kinds = ", ".join(sorted({h["kind"] for h in hits}))
        text = (
            f":mask: *Contact leak masked* in Service-artist chat "
            f"(thread `{thread.get('id')}`) — hidden {len(hits)} item(s) ({kinds}) "
            f"from a {sender_role or '?'} message."
        )
        await notify_slack(db, text=text)
    except Exception as e:  # noqa: BLE001
        log.warning("redact slack alert failed: %s", e)

    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "actor_id": sender_id,
            "actor_role": sender_role,
            "action": "chat.contact_masked",
            "entity": "thread" if not thread.get("booking_id") else "booking",
            "entity_id": entity_id,
            "metadata": {"hits": hits, "chars": len(body_original), "thread_id": thread.get("id")},
            "created_at": utcnow(),
        })
    except Exception:
        pass
    return redacted, hits


async def redact_and_alert(db: AsyncIOMotorDatabase, *, booking_id: str,
                            sender_id: Optional[str], sender_role: Optional[str],
                            body_original: str) -> Tuple[str, List[Dict[str, str]]]:
    """Wrapper — decides whether to mask, then fires Slack + audit if it did."""
    if not body_original:
        return body_original, []
    enforce = await should_enforce_masking(db, booking_id)
    if not enforce:
        return body_original, []
    redacted, hits = redact_contact_info(body_original)
    if not hits:
        return body_original, []

    # Slack fire-and-forget so we never break the chat write.
    try:
        from routes.iter89 import notify_slack
        bk = await db.bookings.find_one({"id": booking_id}, {"_id": 0, "ref": 1}) or {}
        kinds = ", ".join(sorted({h["kind"] for h in hits}))
        text = (
            f":mask: *Contact leak masked* on Service-artist booking "
            f"*{bk.get('ref') or booking_id}* — hidden {len(hits)} item(s) ({kinds}) "
            f"from a {sender_role or '?'} message. Review Admin → Audit Logs if concerning."
        )
        await notify_slack(db, text=text)
    except Exception as e:  # noqa: BLE001
        log.warning("redact slack alert failed: %s", e)

    # Audit trail
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "actor_id": sender_id,
            "actor_role": sender_role,
            "action": "chat.contact_masked",
            "entity": "booking",
            "entity_id": booking_id,
            "metadata": {"hits": hits, "chars": len(body_original)},
            "created_at": utcnow(),
        })
    except Exception:
        pass
    return redacted, hits


# ═══════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_6_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ── (1) Commercial-deal list for the Admin page ────────────────
    @r.get("/admin/artists/commercial-deals")
    async def list_commercial_deals(
        q: Optional[str] = Query(None, description="filter by name/email"),
        type_filter: Optional[str] = Query(None, description="normal | service"),
        limit: int = Query(500, ge=1, le=2000),
        _: dict = Depends(require_admin),
    ):
        # Roll up profile + user + rough booking counts in one page.
        profile_filter: Dict[str, Any] = {"kyc_status": {"$in": ["live", "kyc_approved", "tnc_pending"]}}
        if type_filter == "service":
            profile_filter["is_service_artist"] = True
        elif type_filter == "normal":
            profile_filter["is_service_artist"] = {"$ne": True}

        profs = await db.artist_profiles.find(
            profile_filter,
            {"_id": 0, "user_id": 1, "stage_name": 1, "artist_type": 1,
             "is_service_artist": 1, "percentage_deal": 1,
             "commercial_deal_set_at": 1, "commercial_deal_set_by": 1,
             "kyc_status": 1, "city": 1},
        ).limit(limit).to_list(limit)

        user_ids = [p["user_id"] for p in profs]
        users = await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "email": 1, "first_name": 1, "last_name": 1},
        ).to_list(len(user_ids))
        by_uid = {u["id"]: u for u in users}

        out: List[Dict[str, Any]] = []
        for p in profs:
            u = by_uid.get(p["user_id"], {})
            name = p.get("stage_name") or (
                f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("email") or p["user_id"]
            )
            row = {
                "artist_id": p["user_id"],
                "name": name,
                "email": u.get("email"),
                "city": p.get("city"),
                "artist_type": p.get("artist_type") or ("service" if p.get("is_service_artist") else "normal"),
                "is_service_artist": bool(p.get("is_service_artist")),
                "percentage_deal": float(p.get("percentage_deal") or 0),
                "kyc_status": p.get("kyc_status"),
                "commercial_deal_set_at": p.get("commercial_deal_set_at"),
                "commercial_deal_set_by": p.get("commercial_deal_set_by"),
            }
            if q:
                ql = q.lower()
                blob = f"{row['name']} {row.get('email') or ''} {row.get('city') or ''}".lower()
                if ql not in blob:
                    continue
            out.append(row)

        # Summary tiles for the page header.
        totals = {
            "count": len(out),
            "service_count": sum(1 for r in out if r["is_service_artist"]),
            "normal_count": sum(1 for r in out if not r["is_service_artist"]),
            "avg_service_pct": round(
                sum(r["percentage_deal"] for r in out if r["is_service_artist"])
                / max(1, sum(1 for r in out if r["is_service_artist"])),
                2,
            ),
        }
        return {"items": out, "totals": totals}

    # ── (4) Per-artist deal-change history ─────────────────────────
    @r.get("/admin/artists/{artist_id}/deal-history")
    async def deal_history(artist_id: str, _: dict = Depends(require_admin)):
        rows = await db.audit_logs.find(
            {
                "entity_id": artist_id,
                "action": {"$in": [
                    "artist.commercial_deal_updated",
                    "kyc.approved_with_deal",
                ]},
            },
            {"_id": 0},
        ).sort("created_at", -1).to_list(200)
        # Actor email hydration
        actor_ids = list({r.get("actor_id") for r in rows if r.get("actor_id")})
        actors: Dict[str, str] = {}
        if actor_ids:
            async for u in db.users.find(
                {"id": {"$in": actor_ids}},
                {"_id": 0, "id": 1, "email": 1},
            ):
                actors[u["id"]] = u.get("email") or u["id"]
        for row in rows:
            row["actor_email"] = actors.get(row.get("actor_id"))
        return {"items": rows, "count": len(rows)}

    return r
