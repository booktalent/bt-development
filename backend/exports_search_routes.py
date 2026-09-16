"""
Iteration 11 — final P3 utilities:
  • ICS calendar generation + endpoint (download or attach)
  • CSV exports for customer/agency invoice history
  • AI semantic search (Emergent LLM key, falls back gracefully)
  • Redis pubsub auto-detect for chat (multi-replica scaling)
"""
from __future__ import annotations

import os
import re
import csv
import io
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from csv_safe import safe_row  # SEC — formula-injection guard

log = logging.getLogger("booktalent.iter11")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(x) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return "0.00"


class AISearchBody(BaseModel):
    query: str
    limit: int = 12


# ─────────────────────────────────────────────────────────────────
# ICS calendar generation
# ─────────────────────────────────────────────────────────────────
def build_ics(*, uid: str, summary: str, description: str, location: str,
              start_dt: datetime, end_dt: Optional[datetime] = None) -> bytes:
    """RFC-5545 compliant minimal ICS (single VEVENT)."""
    if end_dt is None:
        end_dt = start_dt + timedelta(hours=3)
    fmt = "%Y%m%dT%H%M%SZ"
    now = datetime.now(timezone.utc)
    body = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//BookTalent//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}@booktalent\r\n"
        f"DTSTAMP:{now.strftime(fmt)}\r\n"
        f"DTSTART:{start_dt.astimezone(timezone.utc).strftime(fmt)}\r\n"
        f"DTEND:{end_dt.astimezone(timezone.utc).strftime(fmt)}\r\n"
        f"SUMMARY:{summary[:120]}\r\n"
        f"DESCRIPTION:{description[:500].replace(chr(10),' ')}\r\n"
        f"LOCATION:{location[:120]}\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return body.encode("utf-8")


def make_exports_search_router(db, get_current_user, admin_only) -> APIRouter:
    r = APIRouter()

    # ─────────────────────────────────────────────────────────────
    # ICS download for any booking the user is a party to
    # ─────────────────────────────────────────────────────────────
    @r.get("/bookings/{bid}/calendar.ics")
    async def booking_ics(bid: str, user: dict = Depends(get_current_user)):
        b = await db.bookings.find_one({"id": bid})
        if not b:
            raise HTTPException(404, "Booking not found")
        if user["role"] != "admin" and user["id"] not in (b.get("customer_id"), b.get("artist_id")):
            raise HTTPException(403, "Not your booking")
        # Build start datetime
        try:
            event_dt = datetime.fromisoformat(f"{b['event_date']}T{b.get('event_time', '19:00')}:00+05:30")
        except Exception:
            try:
                event_dt = datetime.fromisoformat(b["event_date"] + "T19:00:00+05:30")
            except Exception:
                event_dt = datetime.now(timezone.utc) + timedelta(days=7)

        artist = await db.artist_profiles.find_one({"user_id": b["artist_id"]}, {"stage_name": 1, "_id": 0})
        artist_name = (artist or {}).get("stage_name") or "Artist"
        summary = f"BookTalent — {artist_name} · {b.get('event_type', 'Event')}"
        description = (
            f"Booking Ref: {b.get('ref', bid[:8])}\n"
            f"Artist: {artist_name}\n"
            f"Customer: {b.get('customer_name', '')}\n"
            f"Venue: {b.get('venue', '')}\n"
            f"City: {b.get('city', '')}\n"
            f"Notes: {b.get('notes', '')}"
        )
        location = f"{b.get('venue', '')}, {b.get('city', '')}".strip(", ")
        ics = build_ics(uid=bid, summary=summary, description=description,
                        location=location, start_dt=event_dt)
        return Response(
            content=ics, media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="booking_{b.get("ref", bid[:8])}.ics"'},
        )

    # ─────────────────────────────────────────────────────────────
    # CSV invoice export — customer scope
    # ─────────────────────────────────────────────────────────────
    @r.get("/exports/my-bookings.csv")
    async def my_bookings_csv(user: dict = Depends(get_current_user)):
        if user["role"] == "agency":
            roster = await db.agency_roster.find({"agency_id": user["id"], "status": "active"}).sort("created_at", -1).to_list(500)
            artist_ids = [r["artist_id"] for r in roster]
            commission_map = {r["artist_id"]: float(r.get("commission_pct", 10)) for r in roster}
            bookings = await db.bookings.find({"artist_id": {"$in": artist_ids}}).sort("created_at", -1).to_list(2000)
        elif user["role"] in ("customer", "corporate"):
            bookings = await db.bookings.find({"customer_id": user["id"]}).sort("created_at", -1).to_list(2000)
            commission_map = {}
        elif user["role"] == "artist":
            bookings = await db.bookings.find({"artist_id": user["id"]}).sort("created_at", -1).to_list(2000)
            commission_map = {}
        else:
            raise HTTPException(403, "Not allowed for this role")

        buf = io.StringIO()
        w = csv.writer(buf)
        is_agency = user["role"] == "agency"
        headers = [
            "Booking Ref", "Date", "Event Type", "Status",
            "Customer", "Artist ID",
            "Artist Fee", "Platform Service Fee", "GST", "BookTalent Total",
            "Amount Paid", "Created At",
        ]
        if is_agency:
            headers += ["Commission %", "Commission Earned"]
        w.writerow(headers)
        for b in bookings:
            p = b.get("pricing", {}) or {}
            artist_fee = float(p.get("artist_fee", p.get("package_fee", 0) + p.get("addons_total", 0)))
            row = [
                b.get("ref", ""), b.get("event_date", ""), b.get("event_type", ""), b.get("status", ""),
                b.get("customer_name", ""), b.get("artist_id", ""),
                _money(artist_fee), _money(p.get("platform_fee", 0)), _money(p.get("gst", 0)),
                _money(p.get("total", 0)),
                _money(b.get("amount_paid", 0)),
                b.get("created_at", "")[:19].replace("T", " "),
            ]
            if is_agency:
                comm_pct = commission_map.get(b["artist_id"], 0)
                comm_amt = round(artist_fee * comm_pct / 100, 2)
                row += [f"{comm_pct:.1f}", _money(comm_amt)]
            w.writerow(safe_row(row))
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="bookings_{user["role"]}_{datetime.now().strftime("%Y%m%d")}.csv"'},
        )

    # ─────────────────────────────────────────────────────────────
    # Admin GMV / Revenue CSV
    # ─────────────────────────────────────────────────────────────
    @r.get("/admin/exports/revenue.csv")
    async def admin_revenue_csv(days: int = 90, _: dict = Depends(admin_only)):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Booking Ref", "Created", "Event Date", "Status", "Customer",
                    "Artist ID", "Artist Fee (marketplace)", "Platform Fee (BT)", "GST", "BT Total"])
        async for b in db.bookings.find({"created_at": {"$gte": cutoff}}):
            p = b.get("pricing", {}) or {}
            artist_fee = float(p.get("artist_fee", p.get("package_fee", 0) + p.get("addons_total", 0)))
            w.writerow(safe_row([
                b.get("ref", ""), b.get("created_at", "")[:10], b.get("event_date", ""),
                b.get("status", ""), b.get("customer_name", ""), b.get("artist_id", ""),
                _money(artist_fee), _money(p.get("platform_fee", 0)),
                _money(p.get("gst", 0)), _money(p.get("total", 0)),
            ]))
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="bookTalent_revenue_{days}d.csv"'},
        )

    # ─────────────────────────────────────────────────────────────
    # AI semantic search — Emergent LLM key powered
    # Falls back to regex search when no key / no SDK
    # ─────────────────────────────────────────────────────────────
    @r.post("/search/ai")
    async def ai_search(body: AISearchBody):
        """
        Natural-language search over artists.
        Example: "fun energetic Bollywood singer for corporate event in Mumbai under 50k"

        Uses Emergent LLM key + emergentintegrations to extract structured filters
        from the query, then runs an existing structured search.
        """
        raw_q = (body.query or "").strip()
        if not raw_q:
            raise HTTPException(400, "Query required")

        filters: Dict[str, Any] = {}
        rationale = None

        key = os.environ.get("EMERGENT_LLM_KEY", "").strip()
        try:
            if key:
                from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
                system = (
                    "You convert a customer's free-text artist search into a JSON object with "
                    "ONLY these optional keys: category, city, max_price (number INR), "
                    "language, event_type, min_rating (0-5 float), keywords (string). "
                    "Categories include: Singer, Vocalist, DJ, Comedian, Dancer, Anchor, Band, Magician, Folk, Bollywood. "
                    "Cities: Mumbai, Delhi NCR, Bangalore, Chennai, Hyderabad, Kolkata, Pune, Jaipur, Ahmedabad, Goa. "
                    "Always include a 'keywords' string with the search intent. "
                    "Output ONLY raw JSON, no markdown."
                )
                chat = LlmChat(
                    api_key=key, session_id=str(uuid.uuid4()),
                    system_message=system,
                ).with_model("openai", "gpt-4o-mini")
                resp = await chat.send_message(UserMessage(text=raw_q))
                import json as _json, re as _re
                m = _re.search(r"\{.*\}", resp, _re.S)
                if m:
                    filters = _json.loads(m.group(0))
                rationale = "ai_parsed"
        except Exception as e:
            log.warning("AI semantic-search fallback: %s", e)
            rationale = f"fallback_{type(e).__name__}"

        # If no AI or AI failed → cheap regex heuristic
        if not filters:
            import re as _re
            q_low = raw_q.lower()
            for cat in ["singer", "vocalist", "dj", "comedian", "dancer", "anchor", "band", "magician", "folk", "bollywood"]:
                if cat in q_low:
                    filters["category_hint"] = cat
                    break
            for city, label in [("mumbai", "Mumbai"), ("delhi", "Delhi NCR"), ("bangalore", "Bangalore"),
                                ("chennai", "Chennai"), ("hyderabad", "Hyderabad"), ("kolkata", "Kolkata"),
                                ("pune", "Pune"), ("jaipur", "Jaipur"), ("goa", "Goa")]:
                if city in q_low:
                    filters["city"] = label
                    break
            # Price capture: handles "60000", "60,000", "60 000", "60k", "₹60,000",
            # "1.5 lakh". Greedy `[\d,.\s]+` grabs the whole numeric run; we then
            # strip separators + parse the (possibly-decimal) unit multiplier.
            mprice = _re.search(
                r"(?:under|below|less than|max(?:imum)?)\s*(?:₹|rs\.?\s*)?"
                r"([\d][\d,.\s]*)\s*(k|lakh|l)?\b",
                q_low,
            )
            if mprice:
                val_raw = _re.sub(r"[,\s]", "", mprice.group(1)).rstrip(".")
                try:
                    val = float(val_raw)
                    unit = mprice.group(2)
                    if unit == "k":
                        val *= 1_000
                    elif unit in ("lakh", "l"):
                        val *= 100_000
                    filters["max_price"] = int(val)
                except ValueError:
                    pass
            filters["keywords"] = raw_q
            rationale = rationale or "regex"

        # ── Category + city synonyms — the artist catalogue uses genre-specific
        # labels ('Bollywood Vocalist', 'Stand-up Comedian') while the AI / regex
        # layer emits canonical tokens ('Singer', 'Comedian', 'DJ'). Same story
        # for cities — the AI canonicalises 'Delhi' to 'Delhi NCR' but seed
        # rows may store either. Expand both directions so results match.
        CATEGORY_ALIASES = {
            "singer":    ["singer", "vocalist", "bollywood", "playback"],
            "vocalist":  ["vocalist", "singer", "bollywood"],
            "dj":        ["dj", "music producer", "electronic"],
            "comedian":  ["comedian", "stand-up", "stand up", "comic"],
            "dancer":    ["dancer", "choreographer"],
            "anchor":    ["anchor", "host", "emcee", "mc"],
            "band":      ["band", "musician"],
            "magician":  ["magician", "illusionist"],
            "folk":      ["folk", "traditional"],
            "bollywood": ["bollywood", "hindi", "vocalist"],
        }
        CITY_ALIASES = {
            "delhi":      ["Delhi", "Delhi NCR", "New Delhi", "NCR"],
            "delhi ncr":  ["Delhi", "Delhi NCR", "New Delhi", "NCR"],
            "new delhi":  ["Delhi", "Delhi NCR", "New Delhi"],
            "mumbai":     ["Mumbai", "Bombay"],
            "bangalore":  ["Bangalore", "Bengaluru"],
            "kolkata":    ["Kolkata", "Calcutta"],
            "chennai":    ["Chennai", "Madras"],
        }

        def _expand(term: str) -> list[str]:
            if not term:
                return []
            key = str(term).strip().lower()
            aliases = CATEGORY_ALIASES.get(key, [])
            return [key] + [a for a in aliases if a != key]

        # Run a structured search. Strict-AND on city + price + min_rating;
        # category-like terms fan out into the keyword OR list so aliases match
        # (e.g. "Singer" matches "Bollywood Vocalist", "Playback", "Folk").
        q: Dict[str, Any] = {}
        if filters.get("city"):
            city_key = str(filters["city"]).strip().lower()
            aliases = CITY_ALIASES.get(city_key)
            if aliases:
                q["city"] = {"$in": aliases}
            else:
                q["city"] = {"$regex": filters["city"], "$options": "i"}
        if filters.get("language"):
            q["languages"] = {"$regex": filters["language"], "$options": "i"}
        if filters.get("min_rating"):
            q["rating_avg"] = {"$gte": float(filters["min_rating"])}

        or_terms = []
        seen_kw: set[str] = set()
        for term in (filters.get("category"), filters.get("category_hint"), filters.get("event_type")):
            for kw in _expand(term):
                if kw in seen_kw:
                    continue
                seen_kw.add(kw)
                or_terms.extend([
                    {"stage_name": {"$regex": kw, "$options": "i"}},
                    {"bio":        {"$regex": kw, "$options": "i"}},
                    {"tagline":    {"$regex": kw, "$options": "i"}},
                    {"category":   {"$regex": kw, "$options": "i"}},
                ])
        # `keywords` — search only meaningful tokens, not the entire raw sentence
        # (a full-sentence regex like "singer in mumbai under 50000" matches nothing).
        raw_kw = filters.get("keywords") or ""
        STOP = {"in", "for", "under", "below", "less", "than", "max", "maximum",
                "the", "a", "an", "and", "or", "with", "at", "on", "of",
                "rs", "inr", "₹", "k", "lakh", "l"}
        for tok in re.findall(r"[a-z]{3,}", str(raw_kw).lower()):
            if tok in STOP or tok in seen_kw:
                continue
            seen_kw.add(tok)
            or_terms.extend([
                {"stage_name": {"$regex": tok, "$options": "i"}},
                {"bio":        {"$regex": tok, "$options": "i"}},
                {"tagline":    {"$regex": tok, "$options": "i"}},
                {"category":   {"$regex": tok, "$options": "i"}},
            ])
        if or_terms:
            q["$or"] = or_terms

        cur = db.artist_profiles.find(q).sort([("boost_rank", -1), ("rating_avg", -1)]).limit(max(body.limit * 3, 24))
        items = await cur.to_list(max(body.limit * 3, 24))
        max_price = filters.get("max_price")
        out_items = []
        for p in items:
            p.pop("_id", None)
            # Pull cheapest package → starting_price; honour max_price filter post-hoc
            pkgs = await db.packages.find({"artist_id": p["user_id"]}, {"price": 1, "_id": 0}).to_list(20)
            starting_price = min((float(pp.get("price", 0)) for pp in pkgs), default=None)
            p["starting_price"] = starting_price
            if max_price and starting_price and starting_price > max_price:
                continue
            # enrich with gallery thumbs for rotating cards
            gallery = await db.media.find(
                {"user_id": p["user_id"], "type": "gallery"},
                {"data": 0, "thumb": 0},
            ).sort([("is_featured", -1), ("order", 1)]).limit(6).to_list(6)
            p["gallery_thumbs"] = [{"id": g["id"], "is_featured": g.get("is_featured", False)} for g in gallery]
            out_items.append(p)
            if len(out_items) >= body.limit:
                break
        return {
            "query": raw_q, "filters": filters, "mode": rationale,
            "items": out_items, "total": len(out_items),
        }

    return r
