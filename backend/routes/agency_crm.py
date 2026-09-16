"""
/api/agency — Agency Management System (Iter 52).

Endpoints (all require role in {agency, admin}):

Offline artists (private, agency-managed):
  POST   /agency/offline-artists           create
  GET    /agency/offline-artists           list
  PATCH  /agency/offline-artists/{id}      update
  DELETE /agency/offline-artists/{id}      delete

Offline clients (private CRM):
  POST   /agency/clients                   create
  GET    /agency/clients                   list
  GET    /agency/clients/{id}              detail (with notes + follow-ups)
  PATCH  /agency/clients/{id}              update
  DELETE /agency/clients/{id}              delete
  POST   /agency/clients/{id}/notes        add note
  POST   /agency/clients/{id}/follow-ups   add follow-up reminder

Offline events (private):
  POST   /agency/events                    create
  GET    /agency/events                    list
  GET    /agency/events/{id}               detail
  PATCH  /agency/events/{id}               update
  DELETE /agency/events/{id}               delete

Staff:
  POST   /agency/staff                     create (invites by email)
  GET    /agency/staff                     list
  PATCH  /agency/staff/{id}                update role/permissions
  DELETE /agency/staff/{id}                revoke

Finance:
  POST   /agency/invoices                  create quotation → invoice
  GET    /agency/invoices                  list
  PATCH  /agency/invoices/{id}             mark paid/void
  POST   /agency/expenses                  add expense
  GET    /agency/expenses                  list
  GET    /agency/finance/summary           dashboard totals

Reports:
  GET    /agency/reports/revenue           by month
  GET    /agency/reports/artist-performance
  GET    /agency/reports/bookings

Notifications:
  GET    /agency/notifications             feed
  POST   /agency/notifications/{id}/read   mark read

Calendar aggregate:
  GET    /agency/calendar?from=&to=        combined events + platform bookings
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, EmailStr
from motor.motor_asyncio import AsyncIOMotorDatabase


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return doc
    return {k: v for k, v in doc.items() if k != "_id"}


# ─────────────────────────────── Models ──────────────────────────────────────
class OfflineArtistIn(BaseModel):
    linked_artist_id: Optional[str] = None  # if this offline record is *also* a BT artist
    name: str
    stage_name: Optional[str] = None
    category: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    base_price: Optional[float] = 0
    city: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ClientIn(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    city: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class NoteIn(BaseModel):
    text: str


class FollowUpIn(BaseModel):
    due_at: str  # ISO date/datetime
    text: str


class EventArtistLine(BaseModel):
    artist_id: str            # offline_artist.id OR linked BT artist_id
    is_offline: bool = True   # False = pulled from BT roster
    name: str
    price: float = 0
    role: Optional[str] = None  # "lead", "backup", "sound", etc.
    status: str = "assigned"   # assigned|confirmed|cancelled


class EventIn(BaseModel):
    title: str
    client_id: Optional[str] = None
    event_date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    event_type: Optional[str] = None
    artists: List[EventArtistLine] = Field(default_factory=list)
    addons: List[dict] = Field(default_factory=list)
    quotation_amount: Optional[float] = 0
    checklist: List[dict] = Field(default_factory=list)  # [{text, done}]
    docs: List[dict] = Field(default_factory=list)       # [{name, url}]
    payment_status: str = "unpaid"                       # unpaid|partial|paid
    notes: Optional[str] = None


class StaffIn(BaseModel):
    email: EmailStr
    name: str
    role: str = "coordinator"  # manager|coordinator|accountant|booking_executive
    permissions: List[str] = Field(default_factory=list)


class InvoiceIn(BaseModel):
    client_id: str
    event_id: Optional[str] = None
    line_items: List[dict]  # [{desc, qty, unit_price, amount}]
    tax_pct: float = 18.0
    due_date: Optional[str] = None
    notes: Optional[str] = None


class ExpenseIn(BaseModel):
    category: str
    amount: float
    date: str
    notes: Optional[str] = None
    receipt_url: Optional[str] = None


# ─────────────────────────── Router factory ──────────────────────────────────
def make_agency_crm_router(db: AsyncIOMotorDatabase, get_current_user):
    r = APIRouter(prefix="/agency", tags=["agency-crm"])

    async def _guard(user: dict) -> str:
        if user.get("role") not in ("agency", "admin"):
            raise HTTPException(403, "Agency access required")
        return user["id"]

    # ═══════════════════════════ OFFLINE ARTISTS ═════════════════════════════
    @r.post("/offline-artists")
    async def create_offline_artist(body: OfflineArtistIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        doc = {"id": uuid.uuid4().hex, "agency_id": aid, **body.model_dump(), "created_at": _now_iso()}
        await db.agency_offline_artists.insert_one(doc)
        return _clean(doc)

    @r.get("/offline-artists")
    async def list_offline_artists(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        items = await db.agency_offline_artists.find({"agency_id": aid}).sort("created_at", -1).to_list(500)
        return [_clean(i) for i in items]

    @r.patch("/offline-artists/{oid}")
    async def update_offline_artist(oid: str, body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        allowed = {"name", "stage_name", "category", "phone", "email", "base_price", "city", "notes", "tags", "linked_artist_id"}
        upd = {k: v for k, v in body.items() if k in allowed}
        upd["updated_at"] = _now_iso()
        r_ = await db.agency_offline_artists.update_one({"id": oid, "agency_id": aid}, {"$set": upd})
        if r_.matched_count == 0:
            raise HTTPException(404, "Offline artist not found")
        return {"status": "ok"}

    @r.delete("/offline-artists/{oid}")
    async def delete_offline_artist(oid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        r_ = await db.agency_offline_artists.delete_one({"id": oid, "agency_id": aid})
        if r_.deleted_count == 0:
            raise HTTPException(404, "Offline artist not found")
        return {"status": "ok"}

    # ═══════════════════════════ CLIENTS (CRM) ═══════════════════════════════
    @r.post("/clients")
    async def create_client(body: ClientIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        doc = {
            "id": uuid.uuid4().hex, "agency_id": aid, **body.model_dump(),
            "notes_log": [], "follow_ups": [], "created_at": _now_iso(),
        }
        await db.agency_clients.insert_one(doc)
        return _clean(doc)

    @r.get("/clients")
    async def list_clients(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        items = await db.agency_clients.find({"agency_id": aid}).sort("created_at", -1).to_list(500)
        return [_clean(i) for i in items]

    @r.get("/clients/{cid}")
    async def get_client(cid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        c = await db.agency_clients.find_one({"id": cid, "agency_id": aid})
        if not c:
            raise HTTPException(404, "Client not found")
        events = await db.agency_offline_events.find({"agency_id": aid, "client_id": cid}).sort("event_date", -1).to_list(200)
        invoices = await db.agency_invoices.find({"agency_id": aid, "client_id": cid}).sort("created_at", -1).to_list(200)
        return {**_clean(c), "events": [_clean(e) for e in events], "invoices": [_clean(i) for i in invoices]}

    @r.patch("/clients/{cid}")
    async def update_client(cid: str, body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        allowed = {"name", "phone", "email", "company", "city", "tags", "notes"}
        upd = {k: v for k, v in body.items() if k in allowed}
        upd["updated_at"] = _now_iso()
        r_ = await db.agency_clients.update_one({"id": cid, "agency_id": aid}, {"$set": upd})
        if r_.matched_count == 0:
            raise HTTPException(404, "Client not found")
        return {"status": "ok"}

    @r.delete("/clients/{cid}")
    async def delete_client(cid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        r_ = await db.agency_clients.delete_one({"id": cid, "agency_id": aid})
        if r_.deleted_count == 0:
            raise HTTPException(404, "Client not found")
        return {"status": "ok"}

    @r.post("/clients/{cid}/notes")
    async def add_client_note(cid: str, body: NoteIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        note = {"id": uuid.uuid4().hex, "text": body.text, "author": user.get("first_name") or user.get("email"), "at": _now_iso()}
        r_ = await db.agency_clients.update_one({"id": cid, "agency_id": aid}, {"$push": {"notes_log": note}})
        if r_.matched_count == 0:
            raise HTTPException(404, "Client not found")
        return note

    @r.post("/clients/{cid}/follow-ups")
    async def add_client_followup(cid: str, body: FollowUpIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        fu = {"id": uuid.uuid4().hex, "due_at": body.due_at, "text": body.text, "done": False, "created_at": _now_iso()}
        r_ = await db.agency_clients.update_one({"id": cid, "agency_id": aid}, {"$push": {"follow_ups": fu}})
        if r_.matched_count == 0:
            raise HTTPException(404, "Client not found")
        # Also fan out to notifications
        await db.agency_notifications.insert_one({
            "id": uuid.uuid4().hex, "agency_id": aid, "kind": "followup",
            "title": f"Follow-up scheduled: {body.text[:40]}",
            "meta": {"client_id": cid, "due_at": body.due_at},
            "read": False, "created_at": _now_iso(),
        })
        return fu

    # ═══════════════════════════ EVENTS ══════════════════════════════════════
    @r.post("/events")
    async def create_event(body: EventIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        doc = {"id": uuid.uuid4().hex, "agency_id": aid, **body.model_dump(), "status": "scheduled", "created_at": _now_iso()}
        await db.agency_offline_events.insert_one(doc)
        # Notification fan-out
        await db.agency_notifications.insert_one({
            "id": uuid.uuid4().hex, "agency_id": aid, "kind": "event_created",
            "title": f"New event: {body.title}",
            "meta": {"event_id": doc["id"], "date": body.event_date},
            "read": False, "created_at": _now_iso(),
        })
        return _clean(doc)

    @r.get("/events")
    async def list_events(
        user: dict = Depends(get_current_user),
        status: Optional[str] = None,
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
    ):
        aid = await _guard(user)
        q: dict = {"agency_id": aid}
        if status:
            q["status"] = status
        if from_date or to_date:
            q["event_date"] = {}
            if from_date: q["event_date"]["$gte"] = from_date
            if to_date: q["event_date"]["$lte"] = to_date
        items = await db.agency_offline_events.find(q).sort("event_date", 1).to_list(500)
        return [_clean(i) for i in items]

    @r.get("/events/{eid}")
    async def get_event(eid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        e = await db.agency_offline_events.find_one({"id": eid, "agency_id": aid})
        if not e:
            raise HTTPException(404, "Event not found")
        client = None
        if e.get("client_id"):
            client = await db.agency_clients.find_one({"id": e["client_id"], "agency_id": aid})
        return {**_clean(e), "client": _clean(client)}

    @r.patch("/events/{eid}")
    async def update_event(eid: str, body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        allowed = {"title", "client_id", "event_date", "start_time", "end_time", "venue", "city",
                   "event_type", "artists", "addons", "quotation_amount", "checklist", "docs",
                   "payment_status", "notes", "status"}
        upd = {k: v for k, v in body.items() if k in allowed}
        upd["updated_at"] = _now_iso()
        r_ = await db.agency_offline_events.update_one({"id": eid, "agency_id": aid}, {"$set": upd})
        if r_.matched_count == 0:
            raise HTTPException(404, "Event not found")
        return {"status": "ok"}

    @r.delete("/events/{eid}")
    async def delete_event(eid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        r_ = await db.agency_offline_events.delete_one({"id": eid, "agency_id": aid})
        if r_.deleted_count == 0:
            raise HTTPException(404, "Event not found")
        return {"status": "ok"}

    # ═══════════════════════════ STAFF ═══════════════════════════════════════
    @r.post("/staff")
    async def create_staff(body: StaffIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        # Idempotency: don't allow duplicates by email under the same agency
        existing = await db.agency_staff.find_one({"agency_id": aid, "email": str(body.email).lower()})
        if existing:
            raise HTTPException(409, "Staff already invited")
        doc = {
            "id": uuid.uuid4().hex, "agency_id": aid,
            "email": str(body.email).lower(), "name": body.name,
            "role": body.role, "permissions": body.permissions,
            "status": "invited", "invited_at": _now_iso(),
        }
        await db.agency_staff.insert_one(doc)
        return _clean(doc)

    @r.get("/staff")
    async def list_staff(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        items = await db.agency_staff.find({"agency_id": aid}).sort("invited_at", -1).to_list(200)
        return [_clean(i) for i in items]

    @r.patch("/staff/{sid}")
    async def update_staff(sid: str, body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        allowed = {"role", "permissions", "status", "name"}
        upd = {k: v for k, v in body.items() if k in allowed}
        r_ = await db.agency_staff.update_one({"id": sid, "agency_id": aid}, {"$set": upd})
        if r_.matched_count == 0:
            raise HTTPException(404, "Staff not found")
        return {"status": "ok"}

    @r.delete("/staff/{sid}")
    async def delete_staff(sid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        r_ = await db.agency_staff.delete_one({"id": sid, "agency_id": aid})
        if r_.deleted_count == 0:
            raise HTTPException(404, "Staff not found")
        return {"status": "ok"}

    # ═══════════════════════════ INVOICES + EXPENSES ═════════════════════════
    @r.post("/invoices")
    async def create_invoice(body: InvoiceIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        subtotal = sum(float(li.get("amount", 0)) for li in body.line_items)
        tax = round(subtotal * body.tax_pct / 100.0, 2)
        total = round(subtotal + tax, 2)
        seq = await db.agency_invoices.count_documents({"agency_id": aid})
        number = f"AG-{datetime.now(timezone.utc).strftime('%Y%m')}-{seq + 1:04d}"
        doc = {
            "id": uuid.uuid4().hex, "agency_id": aid, "number": number,
            "client_id": body.client_id, "event_id": body.event_id,
            "line_items": body.line_items, "tax_pct": body.tax_pct,
            "subtotal": subtotal, "tax": tax, "total": total,
            "status": "sent", "due_date": body.due_date, "notes": body.notes,
            "created_at": _now_iso(),
        }
        await db.agency_invoices.insert_one(doc)
        return _clean(doc)

    @r.get("/invoices")
    async def list_invoices(user: dict = Depends(get_current_user), status: Optional[str] = None):
        aid = await _guard(user)
        q: dict = {"agency_id": aid}
        if status:
            q["status"] = status
        items = await db.agency_invoices.find(q).sort("created_at", -1).to_list(500)
        return [_clean(i) for i in items]

    @r.patch("/invoices/{iid}")
    async def update_invoice(iid: str, body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        allowed = {"status", "notes", "due_date"}
        upd = {k: v for k, v in body.items() if k in allowed}
        if "status" in upd and upd["status"] == "paid":
            upd["paid_at"] = _now_iso()
        r_ = await db.agency_invoices.update_one({"id": iid, "agency_id": aid}, {"$set": upd})
        if r_.matched_count == 0:
            raise HTTPException(404, "Invoice not found")
        return {"status": "ok"}

    @r.post("/expenses")
    async def create_expense(body: ExpenseIn, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        doc = {"id": uuid.uuid4().hex, "agency_id": aid, **body.model_dump(), "created_at": _now_iso()}
        await db.agency_expenses.insert_one(doc)
        return _clean(doc)

    @r.get("/expenses")
    async def list_expenses(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        items = await db.agency_expenses.find({"agency_id": aid}).sort("date", -1).to_list(500)
        return [_clean(i) for i in items]

    @r.get("/finance/summary")
    async def finance_summary(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        # Sum invoice totals by status
        cursor = db.agency_invoices.aggregate([
            {"$match": {"agency_id": aid}},
            {"$group": {"_id": "$status", "total": {"$sum": "$total"}, "count": {"$sum": 1}}},
        ])
        by_status = {b["_id"] or "sent": {"total": b["total"], "count": b["count"]} async for b in cursor}

        # Platform bookings revenue (agent commissions)
        # Reuse roster commission — we compute quickly from bookings collection.
        roster = await db.agency_roster.find({"agency_id": aid, "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [x["artist_id"] for x in roster]
        commission_map = {x["artist_id"]: float(x.get("commission_pct", 15)) for x in roster}
        platform_gross = 0.0
        platform_commission = 0.0
        if artist_ids:
            pipeline = [
                {"$match": {"artist_id": {"$in": artist_ids}, "status": {"$in": ["confirmed", "completed"]}}},
                {"$group": {"_id": "$artist_id", "gross": {"$sum": "$amount_paid"}}},
            ]
            async for row in db.bookings.aggregate(pipeline):
                platform_gross += row["gross"]
                platform_commission += row["gross"] * commission_map.get(row["_id"], 15) / 100.0

        # Expenses total
        exp_cursor = db.agency_expenses.aggregate([
            {"$match": {"agency_id": aid}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ])
        expenses_total = 0.0
        async for r_ in exp_cursor:
            expenses_total = float(r_.get("total", 0))

        return {
            "invoices_by_status": by_status,
            "offline_revenue": sum(v["total"] for v in by_status.values() if v),
            "offline_paid": by_status.get("paid", {}).get("total", 0),
            "offline_outstanding": by_status.get("sent", {}).get("total", 0) + by_status.get("partial", {}).get("total", 0),
            "platform_gross": round(platform_gross, 2),
            "platform_commission": round(platform_commission, 2),
            "expenses": expenses_total,
            "net": round(sum(v["total"] for v in by_status.values() if v) + platform_commission - expenses_total, 2),
        }

    # ═══════════════════════════ REPORTS ═════════════════════════════════════
    @r.get("/reports/revenue")
    async def revenue_report(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        pipeline = [
            {"$match": {"agency_id": aid, "status": {"$in": ["paid", "partial"]}}},
            {"$addFields": {"month": {"$substr": ["$created_at", 0, 7]}}},
            {"$group": {"_id": "$month", "total": {"$sum": "$total"}, "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        rows = [{"month": b["_id"], "total": b["total"], "invoices": b["count"]} async for b in db.agency_invoices.aggregate(pipeline)]
        return {"by_month": rows}

    @r.get("/reports/artist-performance")
    async def artist_performance(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        roster = await db.agency_roster.find({"agency_id": aid, "status": "active"}).sort("created_at", -1).to_list(500)
        out = []
        for r_ in roster:
            gross = 0.0
            count = 0
            async for b in db.bookings.aggregate([
                {"$match": {"artist_id": r_["artist_id"], "status": {"$in": ["confirmed", "completed"]}}},
                {"$group": {"_id": None, "gross": {"$sum": "$amount_paid"}, "count": {"$sum": 1}}},
            ]):
                gross = b["gross"]; count = b["count"]
            profile = await db.artist_profiles.find_one({"user_id": r_["artist_id"]})
            out.append({
                "artist_id": r_["artist_id"],
                "name": (profile or {}).get("stage_name") or "Unknown",
                "commission_pct": r_.get("commission_pct", 15),
                "platform_gross": gross,
                "platform_bookings": count,
                "commission_earned": round(gross * r_.get("commission_pct", 15) / 100.0, 2),
            })
        out.sort(key=lambda x: x["platform_gross"], reverse=True)
        return out

    @r.get("/reports/bookings")
    async def bookings_report(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        roster = await db.agency_roster.find({"agency_id": aid, "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [x["artist_id"] for x in roster]
        platform = []
        if artist_ids:
            async for b in db.bookings.find({"artist_id": {"$in": artist_ids}}).sort("created_at", -1).limit(200):
                platform.append(_clean(b))
        offline = [_clean(e) async for e in db.agency_offline_events.find({"agency_id": aid}).sort("event_date", -1).limit(200)]
        return {"platform": platform, "offline": offline}

    # ═══════════════════════════ CALENDAR ════════════════════════════════════
    @r.get("/calendar")
    async def calendar_aggregate(
        user: dict = Depends(get_current_user),
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
    ):
        aid = await _guard(user)
        events: List[dict] = []

        # Offline events
        oq: dict = {"agency_id": aid}
        if from_date or to_date:
            oq["event_date"] = {}
            if from_date: oq["event_date"]["$gte"] = from_date
            if to_date: oq["event_date"]["$lte"] = to_date
        async for e in db.agency_offline_events.find(oq):
            events.append({
                "kind": "offline",
                "id": e["id"],
                "title": e.get("title"),
                "date": e.get("event_date"),
                "start_time": e.get("start_time"),
                "end_time": e.get("end_time"),
                "venue": e.get("venue"),
                "city": e.get("city"),
                "status": e.get("status"),
            })

        # Platform bookings for roster artists
        roster = await db.agency_roster.find({"agency_id": aid, "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [x["artist_id"] for x in roster]
        if artist_ids:
            bq: dict = {"artist_id": {"$in": artist_ids}}
            if from_date or to_date:
                bq["event_date"] = {}
                if from_date: bq["event_date"]["$gte"] = from_date
                if to_date: bq["event_date"]["$lte"] = to_date
            async for b in db.bookings.find(bq):
                events.append({
                    "kind": "platform",
                    "id": b.get("id"),
                    "title": b.get("event_type") or "Platform Booking",
                    "date": b.get("event_date"),
                    "start_time": b.get("start_time"),
                    "end_time": b.get("end_time"),
                    "venue": b.get("venue_name"),
                    "city": b.get("city"),
                    "status": b.get("status"),
                    "artist_id": b.get("artist_id"),
                })

        # Follow-ups & payment dues
        async for c in db.agency_clients.find({"agency_id": aid, "follow_ups": {"$exists": True, "$ne": []}}):
            for fu in c.get("follow_ups", []):
                if fu.get("done"):
                    continue
                events.append({
                    "kind": "followup",
                    "id": fu["id"],
                    "title": f"Follow-up: {c.get('name')}",
                    "date": (fu["due_at"] or "")[:10],
                    "client_id": c["id"],
                })

        events.sort(key=lambda x: (x.get("date") or "", x.get("start_time") or ""))
        return events

    # ═══════════════════════════ NOTIFICATIONS ═══════════════════════════════
    @r.get("/notifications")
    async def list_notifications(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        items = await db.agency_notifications.find({"agency_id": aid}).sort("created_at", -1).limit(100).to_list(100)
        unread = sum(1 for i in items if not i.get("read"))
        return {"items": [_clean(i) for i in items], "unread": unread}

    @r.post("/notifications/{nid}/read")
    async def read_notification(nid: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        await db.agency_notifications.update_one({"id": nid, "agency_id": aid}, {"$set": {"read": True}})
        return {"status": "ok"}

    # ═══════════════════════════ ENHANCED OVERVIEW ═══════════════════════════
    @r.get("/overview")
    async def agency_overview(user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        roster_count = await db.agency_roster.count_documents({"agency_id": aid, "status": "active"})
        offline_artists = await db.agency_offline_artists.count_documents({"agency_id": aid})
        clients_count = await db.agency_clients.count_documents({"agency_id": aid})
        offline_events_upcoming = await db.agency_offline_events.count_documents({"agency_id": aid, "event_date": {"$gte": today}})

        roster = await db.agency_roster.find({"agency_id": aid, "status": "active"}).sort("created_at", -1).to_list(500)
        artist_ids = [x["artist_id"] for x in roster]
        pending_bookings = 0
        upcoming_platform = 0
        if artist_ids:
            pending_bookings = await db.bookings.count_documents({"artist_id": {"$in": artist_ids}, "status": "pending_confirmation"})
            upcoming_platform = await db.bookings.count_documents({"artist_id": {"$in": artist_ids}, "event_date": {"$gte": today}, "status": {"$in": ["confirmed", "pending_confirmation"]}})

        # Recent activity (last 10 notifications)
        recent = [_clean(n) for n in await db.agency_notifications.find({"agency_id": aid}).sort("created_at", -1).limit(8).to_list(8)]

        # ── Financial figures scoped to this agency's roster ─────────
        # Advance received / remaining / payout pending for platform bookings
        # of artists on the agency's active roster.
        advance_received = 0.0
        remaining_amount = 0.0
        payout_pending = 0.0
        if artist_ids:
            async for b in db.bookings.find(
                {
                    "artist_id": {"$in": artist_ids},
                    "status": {"$in": ["confirmed", "started", "completed", "reviewed"]},
                },
                {"_id": 0, "pricing": 1, "paid_amount": 1,
                 "artist_payout_status": 1, "artist_payouts": 1},
            ):
                pricing = b.get("pricing") or {}
                total = float(pricing.get("total") or 0)
                paid = float(b.get("paid_amount") or 0)
                artist_share = float(pricing.get("artist_payable") or pricing.get("artist_amount") or 0)
                paid_out = sum(float(p.get("amount") or 0) for p in (b.get("artist_payouts") or []))
                advance_received += min(paid, total)
                remaining_amount += max(0.0, total - paid)
                if (b.get("artist_payout_status") or "").lower() != "paid" and artist_share > paid_out:
                    payout_pending += (artist_share - paid_out)

        return {
            "roster_artists": roster_count,
            "offline_artists": offline_artists,
            "clients": clients_count,
            "upcoming_offline_events": offline_events_upcoming,
            "upcoming_platform_bookings": upcoming_platform,
            "pending_bookings": pending_bookings,
            "recent_activity": recent,
            "advance_received": round(advance_received, 2),
            "remaining_amount": round(remaining_amount, 2),
            "artist_payout_pending": round(payout_pending, 2),
        }

    # ═══════════════════════════ DOCUMENTS (Iter 54) ═════════════════════════
    # Shared document vault scoped to the agency. Supports client_id / event_id
    # tagging so files show up on the related record's detail view.
    @r.post("/documents")
    async def create_document(body: dict, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        title = (body.get("title") or "").strip()
        data_url = body.get("data_url") or ""
        if not title:
            raise HTTPException(400, "Title is required")
        if not data_url.startswith("data:") or "," not in data_url:
            raise HTTPException(400, "File payload must be a valid data URL")
        # Extract mime + size (approx) for the listing card.
        header, _, b64 = data_url.partition(",")
        if not b64.strip():
            raise HTTPException(400, "File payload is empty")
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "application/octet-stream"
        # base64 → bytes ratio ~ 4/3, subtract padding.
        size_bytes = int(len(b64.strip()) * 3 / 4) - (b64.count("=") if b64 else 0)
        # Iter 54 — Hard 10 MB server-side cap so a hostile client can't bypass
        # the 8 MB UI limit and bloat the mongo collection.
        if size_bytes > 10 * 1024 * 1024:
            raise HTTPException(413, "File too large (max 10 MB)")
        doc = {
            "id": uuid.uuid4().hex,
            "agency_id": aid,
            "title": title,
            "kind": (body.get("kind") or "other").strip(),  # contract | agreement | invoice | id | other
            "client_id": body.get("client_id") or None,
            "event_id": body.get("event_id") or None,
            "notes": (body.get("notes") or "").strip() or None,
            "mime": mime,
            "size_bytes": size_bytes,
            "data_url": data_url,  # inline storage — fine for MVP, migrate to S3 later
            "uploaded_by": user["id"],
            "uploaded_by_name": f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user.get("email"),
            "created_at": _now_iso(),
        }
        await db.agency_documents.insert_one(doc)
        # Metadata-only response — don't ship the base64 back on create.
        return {k: v for k, v in _clean(doc).items() if k != "data_url"}

    @r.get("/documents")
    async def list_documents(
        client_id: Optional[str] = None,
        event_id: Optional[str] = None,
        kind: Optional[str] = None,
        user: dict = Depends(get_current_user),
    ):
        aid = await _guard(user)
        q: dict = {"agency_id": aid}
        if client_id: q["client_id"] = client_id
        if event_id: q["event_id"] = event_id
        if kind: q["kind"] = kind
        rows = await db.agency_documents.find(q, {"data_url": 0}).sort("created_at", -1).to_list(500)
        return [_clean(x) for x in rows]

    @r.get("/documents/{did}/download")
    async def download_document(did: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        doc = await db.agency_documents.find_one({"id": did, "agency_id": aid})
        if not doc:
            raise HTTPException(404, "Document not found")
        return {"title": doc["title"], "mime": doc.get("mime"), "data_url": doc.get("data_url")}

    @r.delete("/documents/{did}")
    async def delete_document(did: str, user: dict = Depends(get_current_user)):
        aid = await _guard(user)
        result = await db.agency_documents.delete_one({"id": did, "agency_id": aid})
        if result.deleted_count == 0:
            raise HTTPException(404, "Document not found")
        return {"ok": True}

    return r
