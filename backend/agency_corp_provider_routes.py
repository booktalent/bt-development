"""
Iteration 9 — P2 features:
  • Agency dashboard (roster management + agency-wide bookings)
  • Corporate dashboard (bulk booking + cost centre)
  • Chat enhancements (file/voice upload + video-call escalation)
  • Real-provider wiring scaffolds for Twilio (SMS), Gupshup/Meta (WhatsApp), FCM (Push)

All provider integrations auto-detect their env keys and fall back to mock-mode
when keys are absent — no code change needed when keys arrive.
"""
from __future__ import annotations

import os
import uuid
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from csv_safe import safe_row  # SEC — formula-injection guard

log = logging.getLogger("booktalent.iter9")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def clean(d):
    if not d:
        return d
    d.pop("_id", None)
    return d


# ────────────────────────────────────────────────────────────
# Pydantic — module level for FastAPI body detection
# ────────────────────────────────────────────────────────────
class AgencyArtistInvite(BaseModel):
    artist_email: str
    commission_pct: float = 10.0
    # Iter 54 — When the invited email doesn't have a BookTalent account yet,
    # the agency can optionally seed the artist's basic profile. The system
    # auto-provisions a pending artist account and emails an activation link.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    stage_name: Optional[str] = None


class AgencyRespond(BaseModel):
    accept: bool


class CorporateBulkBooking(BaseModel):
    artist_id: str
    package_id: str
    event_date: str
    event_type: str = "Corporate"
    venue: str = ""
    city: str = ""
    notes: str = ""
    cost_centre: Optional[str] = None
    po_number: Optional[str] = None
    headcount: int = 50


class CorporateBulkBatch(BaseModel):
    bookings: List[CorporateBulkBooking]


class ChatUploadBody(BaseModel):
    booking_id: str
    type: Literal["file", "voice", "video-request"]
    data_url: Optional[str] = None       # base64 data url for file/voice
    filename: Optional[str] = None
    duration_sec: Optional[float] = None  # for voice notes
    note: Optional[str] = None            # for video-request


class ProviderTest(BaseModel):
    to: str
    message: str = "BookTalent test message"


# Provider clients are imported lazily so missing libs don't break startup
def _twilio_send_sms(to: str, body: str) -> Dict[str, Any]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    frm = os.environ.get("TWILIO_FROM", "").strip()
    if not (sid and tok and frm):
        return {"status": "mocked", "reason": "no_keys"}
    try:
        from twilio.rest import Client  # type: ignore
        cli = Client(sid, tok)
        msg = cli.messages.create(body=body, from_=frm, to=to)
        return {"status": "sent", "sid": msg.sid}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _gupshup_send_whatsapp(to: str, body: str) -> Dict[str, Any]:
    api_key = os.environ.get("WHATSAPP_TOKEN", "").strip()
    src = os.environ.get("WHATSAPP_FROM", "").strip()
    if not (api_key and src):
        return {"status": "mocked", "reason": "no_keys"}
    try:
        import requests  # type: ignore
        r = requests.post(
            "https://api.gupshup.io/wa/api/v1/msg",
            headers={"apikey": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={"channel": "whatsapp", "source": src, "destination": to, "message": body},
            timeout=10,
        )
        return {"status": "sent" if r.ok else "failed", "code": r.status_code, "body": r.text[:200]}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _fcm_send_push(token: str, title: str, body: str) -> Dict[str, Any]:
    key = os.environ.get("FCM_SERVER_KEY", "").strip()
    if not (key and token):
        return {"status": "mocked", "reason": "no_keys"}
    try:
        import requests  # type: ignore
        r = requests.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={"Authorization": f"key={key}", "Content-Type": "application/json"},
            json={"to": token, "notification": {"title": title, "body": body}},
            timeout=10,
        )
        return {"status": "sent" if r.ok else "failed", "code": r.status_code}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def make_router(db, get_current_user, admin_only) -> APIRouter:
    r = APIRouter()

    # ────────────────────────────────────────────────────────────
    # AGENCY — roster, invites, bookings
    # ────────────────────────────────────────────────────────────
    @r.post("/agency/invite")
    async def agency_invite(body: AgencyArtistInvite, user: dict = Depends(get_current_user)):
        if user["role"] != "agency":
            raise HTTPException(403, "Only agencies can invite artists")
        email = body.artist_email.lower().strip()
        if not email or "@" not in email:
            raise HTTPException(400, "Valid artist email is required")
        artist_user = await db.users.find_one({"email": email})
        auto_provisioned = False

        if not artist_user:
            # Iter 54 — Auto-provision a stub artist account so agencies can
            # onboard brand-new artists who don't have a BookTalent account yet.
            # We create the user with `pending_activation=true` and a random
            # unusable password. The artist claims the account via the standard
            # /forgot-password flow (email link) or by signing up with the same
            # email (which will hit the existing 'email already registered'
            # error — future iter will add a claim-account endpoint).
            import secrets as _secrets
            from server import hash_password  # local import — avoids cycle at boot

            uid = new_id()
            first = (body.first_name or "").strip()
            last = (body.last_name or "").strip()
            if not first and not last:
                # Fall back: derive a placeholder name from the local part.
                first = email.split("@", 1)[0].replace(".", " ").title()
                last = ""
            random_pw = _secrets.token_urlsafe(24)
            artist_user = {
                "id": uid,
                "email": email,
                "password_hash": hash_password(random_pw),
                "first_name": first,
                "last_name": last,
                "phone": (body.phone or "").strip() or None,
                "role": "artist",
                "kyc_status": "unverified",
                "verified": False,
                "email_verified": False,
                "pending_activation": True,
                "provisioned_by_agency_id": user["id"],
                "provisioned_by_agency_name": user.get("company_name") or user.get("first_name", "Agency"),
                "created_at": utcnow(),
                "updated_at": utcnow(),
            }
            await db.users.insert_one(artist_user)
            # Companion artist_profile so the roster row can join on it.
            stage_name = (body.stage_name or f"{first} {last}").strip() or first or "Artist"
            await db.artist_profiles.insert_one({
                "id": new_id(),
                "user_id": uid,
                "stage_name": stage_name,
                "category": (body.category or "").strip() or "Vocalist",
                "subcategories": [],
                "city": (body.city or "").strip() or "",
                "state": "",
                "country": "India",
                "bio": "",
                "tagline": f"Represented by {artist_user['provisioned_by_agency_name']}",
                "languages": [],
                "genres": [],
                "event_types": [],
                "rating_avg": 0,
                "review_count": 0,
                "profile_completion": 15,
                "suspended": False,
                "pending_activation": True,
                "created_at": utcnow(),
            })
            auto_provisioned = True

        if artist_user.get("role") != "artist":
            raise HTTPException(400, "User is not an artist")
        existing = await db.agency_roster.find_one({"agency_id": user["id"], "artist_id": artist_user["id"]})
        if existing and existing.get("status") == "active":
            raise HTTPException(400, "Artist already in your roster")
        if existing and existing.get("status") == "pending":
            raise HTTPException(400, "Invite already pending")

        # Auto-provisioned artists are added to the roster as active
        # immediately — the agency created the account so consent is implicit.
        # Existing BookTalent artists still see a pending invite they must accept.
        status = "active" if auto_provisioned else "pending"
        doc = {
            "id": new_id(),
            "agency_id": user["id"],
            "agency_name": user.get("company_name") or user.get("first_name", "Agency"),
            "artist_id": artist_user["id"],
            "artist_email": artist_user["email"],
            "commission_pct": body.commission_pct,
            "status": status,
            "auto_provisioned": auto_provisioned,
            "created_at": utcnow(),
        }
        if auto_provisioned:
            doc["decided_at"] = utcnow()
        await db.agency_roster.insert_one(doc)

        # Notify the artist (in-app) — the notification is created regardless of
        # whether the account was just auto-provisioned; it will surface when
        # the artist logs in for the first time.
        if auto_provisioned:
            title = f"You've been added to {doc['agency_name']} on BookTalent"
            body_text = (
                f"{doc['agency_name']} created a BookTalent account for you at {body.commission_pct}% "
                "commission. Use the 'Forgot password' link on the login page to set your password."
            )
        else:
            title = f"Agency invite from {doc['agency_name']}"
            body_text = f"You've been invited to join {doc['agency_name']} at {body.commission_pct}% commission."
        await db.notifications.insert_one({
            "id": new_id(), "user_id": artist_user["id"], "type": "agency.invite",
            "title": title,
            "body": body_text,
            "link": "/dashboard?tab=agency",
            "read": False, "created_at": utcnow(),
        })
        out = clean(doc)
        out["auto_provisioned"] = auto_provisioned
        return out

    @r.get("/agency/roster")
    async def agency_roster(user: dict = Depends(get_current_user)):
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        rows = await db.agency_roster.find({"agency_id": user["id"]}).sort("created_at", -1).to_list(500)
        out = []
        for row in rows:
            row = clean(row)
            prof = await db.artist_profiles.find_one(
                {"user_id": row["artist_id"]},
                {"stage_name": 1, "category": 1, "city": 1, "rating_avg": 1, "review_count": 1, "user_id": 1, "_id": 0},
            )
            row["artist"] = prof
            out.append(row)
        return out

    @r.get("/agency/invites")
    async def agency_invites_mine(user: dict = Depends(get_current_user)):
        if user["role"] != "artist":
            raise HTTPException(403, "Artists only")
        rows = await db.agency_roster.find({"artist_id": user["id"], "status": "pending"}).sort("created_at", -1).to_list(100)
        # Iter 63 — enrich with agency name so the artist banner has context.
        out = []
        for row in rows:
            row = clean(row)
            u = await db.users.find_one(
                {"id": row["agency_id"]},
                {"_id": 0, "first_name": 1, "last_name": 1, "email": 1, "company_name": 1},
            )
            row["agency"] = u or {}
            out.append(row)
        return out

    @r.post("/agency/invite/{invite_id}/respond")
    async def agency_invite_respond(invite_id: str, body: AgencyRespond, user: dict = Depends(get_current_user)):
        inv = await db.agency_roster.find_one({"id": invite_id, "artist_id": user["id"]})
        if not inv:
            raise HTTPException(404, "Invite not found")
        new_status = "active" if body.accept else "declined"
        await db.agency_roster.update_one({"id": invite_id}, {"$set": {"status": new_status, "decided_at": utcnow()}})
        await db.notifications.insert_one({
            "id": new_id(), "user_id": inv["agency_id"], "type": "agency.response",
            "title": f"Invite {new_status}",
            "body": f"{user.get('first_name', 'Artist')} {body.accept and 'joined your roster' or 'declined your invite'}.",
            "read": False, "created_at": utcnow(),
        })
        return {"ok": True, "status": new_status}

    @r.post("/agency/remove/{artist_id}")
    async def agency_remove(artist_id: str, user: dict = Depends(get_current_user)):
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        result = await db.agency_roster.update_one(
            {"agency_id": user["id"], "artist_id": artist_id, "status": {"$in": ["active", "pending"]}},
            {"$set": {"status": "removed", "removed_at": utcnow()}},
        )
        if result.matched_count == 0:
            raise HTTPException(404, "Artist not in your roster")
        return {"ok": True}

    @r.patch("/agency/roster/{artist_id}/commission")
    async def agency_update_commission(artist_id: str, body: dict, user: dict = Depends(get_current_user)):
        """Sprint 6 — update an artist's commission % for this agency."""
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        try:
            pct = float(body.get("commission_pct"))
        except (TypeError, ValueError):
            raise HTTPException(400, "commission_pct is required")
        if pct < 0 or pct > 50:
            raise HTTPException(400, "commission_pct must be 0-50")
        result = await db.agency_roster.update_one(
            {"agency_id": user["id"], "artist_id": artist_id, "status": "active"},
            {"$set": {"commission_pct": pct, "updated_at": utcnow()}},
        )
        if result.matched_count == 0:
            raise HTTPException(404, "Artist not in your active roster")
        return {"ok": True, "commission_pct": pct}

    @r.get("/agency/bookings")
    async def agency_bookings(user: dict = Depends(get_current_user)):
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        roster = await db.agency_roster.find({"agency_id": user["id"], "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [r["artist_id"] for r in roster]
        if not artist_ids:
            return []
        rows = await db.bookings.find({"artist_id": {"$in": artist_ids}}).sort("created_at", -1).to_list(500)
        return [clean(r) for r in rows]

    @r.get("/agency/gst-report.csv")
    async def agency_gst_report(quarter: Optional[str] = None, user: dict = Depends(get_current_user)):
        """
        Streams a CSV of every confirmed booking's platform fee + GST for the
        given quarter (or the current quarter if none given).
        Format: `2026-Q3`  →  Jul-Sep 2026.
        """
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        import io, csv
        from datetime import datetime as _dt
        # Resolve quarter start / end
        now = _dt.utcnow()
        if quarter and "-Q" in quarter:
            year, q = quarter.split("-Q")
            year = int(year); q = int(q)
        else:
            year = now.year
            q = (now.month - 1) // 3 + 1
        q_start_month = (q - 1) * 3 + 1
        q_end_month = q_start_month + 2
        start = f"{year:04d}-{q_start_month:02d}-01"
        # Last day of q_end_month
        if q_end_month == 12:
            end = f"{year:04d}-12-31"
        else:
            end = f"{year:04d}-{q_end_month + 1:02d}-01"

        roster = await db.agency_roster.find({"agency_id": user["id"], "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [r["artist_id"] for r in roster]
        rows = []
        if artist_ids:
            async for b in db.bookings.find({
                "artist_id": {"$in": artist_ids},
                "status": {"$in": ["confirmed", "completed", "reviewed"]},
                "event_date": {"$gte": start, "$lt": end},
            }):
                rows.append(b)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Booking Ref", "Artist", "Customer", "Event Date", "Event Type",
            "Artist Fee (INR)", "Platform Service Fee (5%)", "GST on Fee (18%)",
            "Total Collected by BookTalent", "Status",
        ])
        total_fee = total_gst = 0.0
        for b in rows:
            p = b.get("pricing", {}) or {}
            fee = float(p.get("platform_fee", 0))
            gst = float(p.get("gst", 0))
            total_fee += fee
            total_gst += gst
            writer.writerow(safe_row([
                b.get("ref", b.get("id", "")),
                b.get("artist_name", b.get("artist_id", "")),
                b.get("customer_name", ""),
                b.get("event_date", ""),
                b.get("event_type", ""),
                float(p.get("artist_fee", 0)),
                fee, gst, fee + gst,
                b.get("status", ""),
            ]))
        writer.writerow([])
        writer.writerow(["TOTALS", "", "", "", "", "", total_fee, total_gst, total_fee + total_gst, ""])

        csv_bytes = buf.getvalue().encode("utf-8")
        from fastapi.responses import Response
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="gst-report-{year}-Q{q}.csv"'},
        )

    @r.get("/agency/availability")
    async def agency_availability(date: str, user: dict = Depends(get_current_user)):
        """
        On a given YYYY-MM-DD, returns which roster artists are free vs busy.
        Handy for agencies rebalancing bookings across their roster.
        """
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        roster = await db.agency_roster.find({"agency_id": user["id"], "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [r["artist_id"] for r in roster]
        if not artist_ids:
            return {"date": date, "free": [], "busy": []}
        # Any availability doc with status blocked/booked/premium on this date OR
        # any pending_artist/confirmed booking with matching event_date = busy.
        busy_ids = set()
        async for a in db.availability.find({
            "user_id": {"$in": artist_ids}, "date": date,
            "status": {"$in": ["blocked", "booked"]},
        }):
            busy_ids.add(a["user_id"])
        async for b in db.bookings.find({
            "artist_id": {"$in": artist_ids}, "event_date": date,
            "status": {"$in": ["pending_artist", "confirmed", "started"]},
        }):
            busy_ids.add(b["artist_id"])
        # Enrich with basic artist info from artist_profiles
        profiles = {}
        async for p in db.artist_profiles.find({"user_id": {"$in": artist_ids}}):
            profiles[p["user_id"]] = {
                "user_id": p["user_id"],
                "stage_name": p.get("stage_name"),
                "category": p.get("category"),
                "city": p.get("city"),
                "starting_price": p.get("starting_price"),
                "slug": p.get("slug"),
            }
        free = [profiles.get(aid) for aid in artist_ids if aid not in busy_ids and profiles.get(aid)]
        busy = [profiles.get(aid) for aid in artist_ids if aid in busy_ids and profiles.get(aid)]
        return {"date": date, "free": free, "busy": busy, "roster_count": len(artist_ids)}

    @r.get("/agency/stats")
    async def agency_stats(user: dict = Depends(get_current_user)):
        if user["role"] != "agency":
            raise HTTPException(403, "Agency only")
        roster_count = await db.agency_roster.count_documents({"agency_id": user["id"], "status": "active"})
        pending_invites = await db.agency_roster.count_documents({"agency_id": user["id"], "status": "pending"})
        roster = await db.agency_roster.find({"agency_id": user["id"], "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [r["artist_id"] for r in roster]
        commission_map = {r["artist_id"]: float(r.get("commission_pct", 10)) for r in roster}
        gmv = 0.0
        commission = 0.0
        bookings = 0
        async for b in db.bookings.find({"artist_id": {"$in": artist_ids}, "status": {"$in": ["confirmed", "completed", "reviewed"]}}):
            total = float(b.get("pricing", {}).get("total", 0))
            gmv += total
            commission += total * commission_map.get(b["artist_id"], 10) / 100
            bookings += 1
        return {
            "roster": roster_count, "pending_invites": pending_invites,
            "bookings": bookings, "gmv": gmv,
            "commission_earned": round(commission, 2),
        }

    # ────────────────────────────────────────────────────────────
    # CORPORATE — bulk bookings + cost centre
    # ────────────────────────────────────────────────────────────
    @r.post("/corporate/bulk-bookings")
    async def corporate_bulk(body: CorporateBulkBatch, user: dict = Depends(get_current_user)):
        if user["role"] != "corporate":
            raise HTTPException(403, "Corporate accounts only")
        created = []
        errors = []
        for i, item in enumerate(body.bookings):
            try:
                pkg = await db.packages.find_one({"id": item.package_id, "artist_id": item.artist_id})
                if not pkg:
                    errors.append({"index": i, "error": "package_not_found"})
                    continue
                bid = new_id()
                price = float(pkg.get("price", 0))
                gst = round(price * 0.18, 2)
                platform_fee = round(price * 0.05, 2)
                total = round(price + gst + platform_fee, 2)
                booking = {
                    "id": bid,
                    "ref": f"BT-{datetime.now(timezone.utc).strftime('%y%m%d')}-{bid[:6].upper()}",
                    "customer_id": user["id"],
                    "customer_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("company_name", ""),
                    "customer_email": user.get("email"),
                    "customer_phone": user.get("phone"),
                    "artist_id": item.artist_id,
                    "package_id": item.package_id,
                    "event_date": item.event_date,
                    "event_type": item.event_type,
                    "venue": item.venue,
                    "city": item.city,
                    "notes": item.notes,
                    "status": "pending_artist",
                    "headcount": item.headcount,
                    "cost_centre": item.cost_centre,
                    "po_number": item.po_number,
                    "is_corporate_bulk": True,
                    "pricing": {"base": price, "addons": 0, "gst": gst, "platform_fee": platform_fee, "total": total},
                    "amount_paid": 0,
                    "created_at": utcnow(),
                }
                await db.bookings.insert_one(booking)
                # Block the date pre-emptively
                await db.availability.update_one(
                    {"user_id": item.artist_id, "date": item.event_date},
                    {"$set": {"user_id": item.artist_id, "date": item.event_date, "status": "tentative", "booking_id": bid}},
                    upsert=True,
                )
                created.append(clean(booking))
                # Notify artist
                await db.notifications.insert_one({
                    "id": new_id(), "user_id": item.artist_id, "type": "booking.corporate",
                    "title": f"Corporate booking — {item.event_date}",
                    "body": f"PO {item.po_number or '—'} from {booking['customer_name']}",
                    "read": False, "created_at": utcnow(),
                })
            except Exception as e:
                errors.append({"index": i, "error": str(e)})

        return {"ok": True, "created": len(created), "bookings": created, "errors": errors}

    @r.get("/corporate/bookings")
    async def corporate_bookings(user: dict = Depends(get_current_user)):
        if user["role"] != "corporate":
            raise HTTPException(403, "Corporate only")
        rows = await db.bookings.find({"customer_id": user["id"]}).sort("created_at", -1).to_list(500)
        return [clean(r) for r in rows]

    @r.get("/corporate/stats")
    async def corporate_stats(user: dict = Depends(get_current_user)):
        if user["role"] != "corporate":
            raise HTTPException(403, "Corporate only")
        total = 0.0
        cnt = 0
        by_cost_centre: Dict[str, Dict[str, float]] = {}
        async for b in db.bookings.find({"customer_id": user["id"]}):
            t = float(b.get("pricing", {}).get("total", 0))
            total += t
            cnt += 1
            cc = b.get("cost_centre") or "Unassigned"
            by_cost_centre.setdefault(cc, {"spend": 0, "bookings": 0})
            by_cost_centre[cc]["spend"] += t
            by_cost_centre[cc]["bookings"] += 1
        return {"total_spend": round(total, 2), "bookings": cnt, "by_cost_centre": by_cost_centre}

    # ────────────────────────────────────────────────────────────
    # CHAT enhancements — file / voice / video-request
    # ────────────────────────────────────────────────────────────
    @r.post("/chat/{booking_id}/upload")
    async def chat_upload(booking_id: str, body: ChatUploadBody, user: dict = Depends(get_current_user)):
        booking = await db.bookings.find_one({"id": booking_id})
        if not booking:
            raise HTTPException(404, "Booking not found")
        # Iter 91 — Assigned managers can moderate the chat too.
        is_participant = user["id"] in (booking.get("customer_id"), booking.get("artist_id"))
        is_manager = user.get("role") == "manager" and booking.get("assigned_manager_id") == user["id"]
        if user["role"] != "admin" and not is_participant and not is_manager:
            raise HTTPException(403, "Not a participant")
        # Payment gate — block file / voice / video-request uploads until Platform Service Fee paid.
        # Legacy bookings (no payment_status field) are unlocked once they're past `pending_payment`.
        # Managers and admins bypass the payment gate (moderator access).
        if user["role"] != "admin" and not is_manager:
            ps = booking.get("payment_status")
            status = booking.get("status")
            unlocked = (ps and ps != "unpaid") or (status and status != "pending_payment")
            if not unlocked:
                raise HTTPException(
                    403,
                    "Chat Access Denied — Complete Platform Service Fee payment to unlock chat.",
                )

        media_id = None
        if body.type in ("file", "voice"):
            if not body.data_url or not body.data_url.startswith("data:"):
                raise HTTPException(400, "data_url required for file/voice messages")
            try:
                header, b64 = body.data_url.split(",", 1)
                mime = header.split(";")[0].replace("data:", "")
            except Exception:
                raise HTTPException(400, "Malformed data url")
            # Cap voice notes at 5 MB, files at 15 MB
            cap = 5 * 1024 * 1024 if body.type == "voice" else 15 * 1024 * 1024
            if (len(b64) * 3) // 4 > cap:
                raise HTTPException(400, f"{body.type} too large (cap {cap // (1024*1024)} MB)")
            media_id = new_id()
            await db.media.insert_one({
                "id": media_id, "user_id": user["id"], "type": "chat",
                "mime": mime, "data": b64, "created_at": utcnow(),
                "booking_id": booking_id, "filename": body.filename, "duration_sec": body.duration_sec,
            })

        sender_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user.get("email", "")
        content_text = {
            "file": body.filename or "Attached a file",
            "voice": f"Voice note ({int(body.duration_sec or 0)}s)",
            "video-request": body.note or "Requested a video call",
        }.get(body.type, "Attachment")

        msg = {
            "id": new_id(),
            "booking_id": booking_id,
            "sender_id": user["id"],
            "sender_role": user.get("role"),
            "sender_name": sender_name,
            "content": content_text,
            "type": body.type,
            "media_id": media_id,
            "filename": body.filename,
            "duration_sec": body.duration_sec,
            "read_by": [user["id"]],
            "created_at": utcnow(),
        }
        await db.chat_messages.insert_one(msg)

        # Off-line in-app notification for the other party
        other = booking["artist_id"] if user["id"] == booking["customer_id"] else booking["customer_id"]
        if other:
            await db.notifications.insert_one({
                "id": new_id(), "user_id": other, "type": "chat",
                "title": f"New {body.type.replace('-', ' ')} from {sender_name}",
                "body": content_text[:120],
                "link": f"/dashboard/bookings/{booking_id}",
                "read": False, "created_at": utcnow(),
            })
        return clean(dict(msg))

    # ────────────────────────────────────────────────────────────
    # PROVIDER TEST HOOKS — admin can test each integration
    # ────────────────────────────────────────────────────────────
    @r.post("/admin/providers/test/sms")
    async def test_sms(body: ProviderTest, _: dict = Depends(admin_only)):
        return _twilio_send_sms(body.to, body.message)

    @r.post("/admin/providers/test/whatsapp")
    async def test_whatsapp(body: ProviderTest, _: dict = Depends(admin_only)):
        return _gupshup_send_whatsapp(body.to, body.message)

    @r.post("/admin/providers/test/push")
    async def test_push(body: ProviderTest, _: dict = Depends(admin_only)):
        return _fcm_send_push(body.to, "BookTalent", body.message)

    @r.get("/admin/providers/status")
    async def providers_status(_: dict = Depends(admin_only)):
        """Live status of every external provider — single pane of glass."""
        def has(*keys: str) -> bool:
            return all(os.environ.get(k, "").strip() for k in keys)
        return {
            "email_resend": {"live": has("RESEND_API_KEY"), "env_keys": ["RESEND_API_KEY"]},
            "sms_twilio": {"live": has("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"),
                           "env_keys": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"]},
            "whatsapp_gupshup": {"live": has("WHATSAPP_TOKEN", "WHATSAPP_FROM"),
                                 "env_keys": ["WHATSAPP_TOKEN", "WHATSAPP_FROM"]},
            "push_fcm": {"live": has("FCM_SERVER_KEY"), "env_keys": ["FCM_SERVER_KEY"]},
            "easebuzz": {"live": True, "env_keys": ["payment_gateway_settings (DB)"]},
            "stripe": {"live": has("STRIPE_SECRET_KEY"), "env_keys": ["STRIPE_SECRET_KEY"]},
        }

    return r


# Public helpers so notification_service can call them
twilio_send_sms = _twilio_send_sms
gupshup_send_whatsapp = _gupshup_send_whatsapp
fcm_send_push = _fcm_send_push
