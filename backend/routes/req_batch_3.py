"""
Feb-2026 Requirement Batch 3.

Adds:
  1. Admin Refund Auditor — list + filter + CSV/PDF export of every
     `refund_requests` row for the finance team.
  2. Bulk Payout Marker — mark many artist payouts as paid in one call
     (reuses the existing `crm_pay._record_payout` under the hood).
  3. Timeline snippet helper for email templates (used by the confirmation
     + reminder emails).

All artifacts kept in one focused router so it's easy to move later.
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from csv_safe import safe_row  # SEC — formula-injection guard

log = logging.getLogger("req_batch_3")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Timeline snippet for emails (compact 4-row table)
# ═══════════════════════════════════════════════════════════════════════
def build_email_timeline_html(booking: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    """Return a small HTML block summarising the booking's lifecycle for
    inclusion in confirmation / reminder emails. Falls back gracefully
    when there are no events yet.
    """
    # Ordered stages we care about in emails (customer + artist friendly).
    order = [
        ("lead_created",        "Booking Created"),
        ("manager_assigned",    "Manager Assigned"),
        ("artist_selected",     "Artist Selected"),
        ("booking_confirmed",   "Booking Confirmed"),
        ("payment_received",    "Payment Received"),
        ("artist_payout",       "Artist Payout"),
        ("event_completed",     "Event Day"),
        ("final_settled",       "Final Settlement"),
    ]
    ev_by_kind: Dict[str, Dict[str, Any]] = {}
    for e in events or []:
        k = e.get("kind")
        if k and k not in ev_by_kind:
            ev_by_kind[k] = e

    # If we have no events at all, still show the "created" row using
    # the booking.created_at timestamp so the email always renders.
    if not ev_by_kind and booking.get("created_at"):
        ev_by_kind["lead_created"] = {"at": booking["created_at"], "label": "Booking Created"}

    def _fmt_date(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
        except Exception:
            return (iso or "")[:10]

    rows_html: List[str] = []
    for kind, label in order:
        ev = ev_by_kind.get(kind)
        done = ev is not None
        color = "#6ee7a8" if done else "rgba(240,238,255,0.35)"
        icon = "●" if done else "○"
        when = _fmt_date(ev["at"]) if done and ev.get("at") else "—"
        row = (
            f'<tr>'
            f'<td style="padding:6px 8px;color:{color};font-size:15px;width:20px;">{icon}</td>'
            f'<td style="padding:6px 4px;color:{"#F0EEFF" if done else "rgba(240,238,255,0.55)"};font-size:13px;">{label}</td>'
            f'<td style="padding:6px 8px;color:rgba(240,238,255,0.6);font-size:12px;text-align:right;">{when}</td>'
            f'</tr>'
        )
        rows_html.append(row)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px 8px;margin-top:16px;">
      <tr><td colspan="3" style="padding:6px 10px 10px;color:rgba(240,238,255,0.55);font-size:11px;letter-spacing:1px;">
        BOOKING TIMELINE
      </td></tr>
      {''.join(rows_html)}
    </table>
    """


async def fetch_booking_events(db: AsyncIOMotorDatabase, booking_id: str) -> List[Dict[str, Any]]:
    """Read the booking_events collection sorted oldest-first."""
    if not booking_id:
        return []
    try:
        return await db.booking_events.find(
            {"booking_id": booking_id}, {"_id": 0},
        ).sort("at", 1).to_list(500)
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════
# Bulk payout marker
# ═══════════════════════════════════════════════════════════════════════
class BulkPayoutRow(BaseModel):
    booking_id: str
    amount: float = Field(gt=0)
    method: str = Field(default="neft")
    utr: str = Field(default="")
    bank_reference: Optional[str] = None
    notes: Optional[str] = None
    paid_on: Optional[str] = None


class BulkPayoutBody(BaseModel):
    default_method: str = Field(default="neft")
    default_paid_on: Optional[str] = None
    rows: List[BulkPayoutRow]


# ═══════════════════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════════════════
def make_req_batch_3_router(db: AsyncIOMotorDatabase, get_current_user, require_admin) -> APIRouter:
    r = APIRouter()

    # ═══════════════════════════════════════════════════════════════
    # (1) Admin Refund Auditor
    # ═══════════════════════════════════════════════════════════════
    async def _hydrate_refund(row: Dict[str, Any]) -> Dict[str, Any]:
        """Attach booking ref, customer/artist emails so the row is
        self-contained in the list + CSV/PDF export."""
        bid = row.get("booking_id")
        bk = await db.bookings.find_one(
            {"id": bid},
            {"_id": 0, "ref": 1, "customer_id": 1, "artist_id": 1, "event_date": 1, "pricing": 1},
        ) or {}
        cust = await db.users.find_one({"id": bk.get("customer_id")},
                                        {"_id": 0, "email": 1, "first_name": 1, "last_name": 1}) or {}
        art = await db.users.find_one({"id": bk.get("artist_id")},
                                       {"_id": 0, "email": 1, "first_name": 1, "last_name": 1}) or {}
        row.pop("_id", None)
        row["booking_ref"] = bk.get("ref") or bid
        row["event_date"] = bk.get("event_date")
        row["booking_total"] = float((bk.get("pricing") or {}).get("total") or 0)
        row["customer_email"] = cust.get("email") or ""
        row["customer_name"] = f"{cust.get('first_name','')} {cust.get('last_name','')}".strip()
        row["artist_email"] = art.get("email") or ""
        row["artist_name"] = f"{art.get('first_name','')} {art.get('last_name','')}".strip()
        return row

    @r.get("/admin/refunds/audit")
    async def refund_audit(
        status: Optional[str] = Query(None, description="pending_counter_ack | accepted | rejected"),
        from_date: Optional[str] = Query(None, description="ISO date lower bound (inclusive)"),
        to_date: Optional[str] = Query(None, description="ISO date upper bound (inclusive)"),
        q: Optional[str] = Query(None, description="Free text — matches booking ref or party email"),
        limit: int = Query(200, ge=1, le=1000),
        _: dict = Depends(require_admin),
    ):
        filt: Dict[str, Any] = {}
        if status:
            filt["status"] = status
        if from_date:
            filt.setdefault("created_at", {})["$gte"] = from_date
        if to_date:
            filt.setdefault("created_at", {})["$lte"] = to_date + "T23:59:59Z"

        rows = await db.refund_requests.find(filt).sort("created_at", -1).to_list(limit)
        hydrated = [await _hydrate_refund(r) for r in rows]

        if q:
            ql = q.lower()
            hydrated = [
                h for h in hydrated
                if ql in (h.get("booking_ref") or "").lower()
                or ql in (h.get("customer_email") or "").lower()
                or ql in (h.get("artist_email") or "").lower()
            ]

        # Aggregate totals for the top-of-page summary card.
        totals = {
            "count": len(hydrated),
            "amount_pending": round(sum(h["amount"] for h in hydrated if h["status"] == "pending_counter_ack"), 2),
            "amount_accepted": round(sum(h["amount"] for h in hydrated if h["status"] == "accepted"), 2),
            "amount_rejected": round(sum(h["amount"] for h in hydrated if h["status"] == "rejected"), 2),
        }
        return {"items": hydrated, "totals": totals}

    @r.get("/admin/refunds/audit/export.csv")
    async def refund_audit_csv(
        status: Optional[str] = Query(None),
        from_date: Optional[str] = Query(None),
        to_date: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        _: dict = Depends(require_admin),
    ):
        data = await refund_audit(status=status, from_date=from_date, to_date=to_date, q=q, limit=1000, _={})  # type: ignore
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "Booking Ref", "Event Date", "Booking Total", "Refund Amount",
            "Status", "Reason", "Requested By", "Counter Party", "Customer",
            "Customer Email", "Artist", "Artist Email", "Created", "Accepted On",
        ])
        for h in data["items"]:
            w.writerow(safe_row([
                h.get("booking_ref"), h.get("event_date"), h.get("booking_total"),
                h.get("amount"), h.get("status"), h.get("reason", ""),
                h.get("requested_by_role"), h.get("counter_role"),
                h.get("customer_name"), h.get("customer_email"),
                h.get("artist_name"), h.get("artist_email"),
                (h.get("created_at") or "")[:19],
                (h.get("counter_accepted_at") or "")[:19],
            ]))
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=refund-audit-{datetime.now().strftime('%Y%m%d')}.csv"},
        )

    @r.get("/admin/refunds/audit/export.pdf")
    async def refund_audit_pdf(
        status: Optional[str] = Query(None),
        from_date: Optional[str] = Query(None),
        to_date: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        _: dict = Depends(require_admin),
    ):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"PDF library unavailable: {e}")

        data = await refund_audit(status=status, from_date=from_date, to_date=to_date, q=q, limit=1000, _={})  # type: ignore

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            leftMargin=12 * mm, rightMargin=12 * mm,
            topMargin=14 * mm, bottomMargin=12 * mm,
            title="BookTalent · Refund Audit",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title", parent=styles["Title"], fontSize=18,
            textColor=colors.HexColor("#0F0F1B"), spaceAfter=4,
        )
        muted = ParagraphStyle(
            "Muted", parent=styles["Normal"], fontSize=9,
            textColor=colors.HexColor("#666666"), spaceAfter=8,
        )
        flow: List[Any] = []
        flow.append(Paragraph("BookTalent · Refund Auditor", title_style))
        filter_bits = []
        if status:     filter_bits.append(f"status={status}")
        if from_date:  filter_bits.append(f"from={from_date}")
        if to_date:    filter_bits.append(f"to={to_date}")
        if q:          filter_bits.append(f"q={q}")
        flow.append(Paragraph(
            f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
            f"Filters: {' · '.join(filter_bits) or 'none'}",
            muted,
        ))

        # Summary table
        t = data["totals"]
        summary_data = [
            ["Total rows", str(t["count"]),
             "Pending ₹", f"₹{t['amount_pending']:,.0f}",
             "Accepted ₹", f"₹{t['amount_accepted']:,.0f}",
             "Rejected ₹", f"₹{t['amount_rejected']:,.0f}"],
        ]
        summary_tbl = Table(summary_data, hAlign="LEFT")
        summary_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F1E4")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F0F1B")),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D4AF37")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E0D5AC")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        flow.append(summary_tbl)
        flow.append(Spacer(0, 10))

        # Main data table
        header = ["Booking", "Event", "Amount", "Status", "Requested By",
                  "Customer", "Artist", "Reason", "Created"]
        table_data = [header]
        for h in data["items"]:
            table_data.append([
                Paragraph(str(h.get("booking_ref") or "")[:18], styles["Normal"]),
                str(h.get("event_date") or ""),
                f"₹{h.get('amount', 0):,.0f}",
                str(h.get("status") or ""),
                str(h.get("requested_by_role") or ""),
                Paragraph((h.get("customer_email") or "")[:36], styles["Normal"]),
                Paragraph((h.get("artist_email") or "")[:36], styles["Normal"]),
                Paragraph(str(h.get("reason") or "")[:60], styles["Normal"]),
                (h.get("created_at") or "")[:10],
            ])
        tbl = Table(
            table_data, repeatRows=1,
            colWidths=[26 * mm, 22 * mm, 22 * mm, 32 * mm, 22 * mm,
                       46 * mm, 46 * mm, 46 * mm, 22 * mm],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F0F1B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#D4AF37")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.HexColor("#FFFFFF"), colors.HexColor("#FAF6E8")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        flow.append(tbl)
        flow.append(Spacer(0, 8))
        flow.append(Paragraph(
            "Confidential · For BookTalent finance & audit use only.",
            muted,
        ))
        doc.build(flow)
        buf.seek(0)
        return StreamingResponse(
            buf, media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=refund-audit-{datetime.now().strftime('%Y%m%d')}.pdf"},
        )

    # ═══════════════════════════════════════════════════════════════
    # (2) Bulk Payout Marker
    # ═══════════════════════════════════════════════════════════════
    @r.post("/admin/payouts/bulk-mark-paid")
    async def bulk_mark_paid(body: BulkPayoutBody, user: dict = Depends(require_admin)):
        """Mark many artist payouts as paid in a single call. Uses the
        same `_record_payout` writer as the single-payout admin action so
        the artist_payouts ledger + booking.artist_payout_status stay
        consistent.
        """
        # Import here so this router can be dropped in without a hard
        # dependency on crm_pay module load order.
        try:
            from routes.crm_pay import _record_payout as record_payout  # type: ignore
        except Exception:
            record_payout = None  # type: ignore

        default_paid_on = body.default_paid_on or utcnow()[:10]

        results: List[Dict[str, Any]] = []
        succeeded = 0
        total_amount = 0.0
        for row in body.rows:
            bk = await db.bookings.find_one({"id": row.booking_id})
            if not bk:
                results.append({"booking_id": row.booking_id, "ok": False, "error": "booking_not_found"})
                continue
            method = row.method or body.default_method or "neft"
            paid_on = row.paid_on or default_paid_on
            payload = {
                "amount": row.amount,
                "method": method,
                "utr": row.utr or "",
                "bank_reference": row.bank_reference or "",
                "notes": row.notes or "Bulk mark-paid",
                "paid_on": paid_on,
            }
            try:
                if record_payout:
                    # Build the ManualPayoutBody the same way the single-payout endpoint does.
                    try:
                        from routes.crm_pay import ManualPayoutBody as _MPB  # type: ignore
                        mpb = _MPB(**payload)
                    except Exception:
                        # Fallback — pass a shim object with the same attrs.
                        class _Shim:
                            def __init__(self, **kw): self.__dict__.update(kw)
                        mpb = _Shim(**payload)  # type: ignore
                    doc = await record_payout(db, bk, user, mpb)
                    payout_id = doc.get("id") if isinstance(doc, dict) else None
                else:
                    # Fallback: direct write matching the schema used elsewhere.
                    payout_id = str(uuid.uuid4())
                    await db.artist_payouts.insert_one({
                        "id": payout_id,
                        "booking_id": row.booking_id,
                        "artist_id": bk.get("artist_id"),
                        "amount": row.amount,
                        "method": method,
                        "utr": row.utr or "",
                        "bank_reference": row.bank_reference or "",
                        "notes": row.notes or "Bulk mark-paid",
                        "paid_on": paid_on,
                        "created_at": utcnow(),
                        "created_by": user.get("id"),
                    })
                    await db.bookings.update_one(
                        {"id": row.booking_id},
                        {"$set": {
                            "artist_payout_status": "paid",
                            "artist_payout_id": payout_id,
                            "artist_payout_paid_at": utcnow(),
                        }, "$push": {"artist_payouts": {
                            "amount": row.amount, "paid_on": paid_on,
                            "method": method, "utr": row.utr or "",
                        }}},
                    )

                # Emit timeline event for the booking.
                try:
                    from routes.req_batch_2 import emit_booking_event
                    await emit_booking_event(
                        db, booking_id=row.booking_id, kind="artist_payout",
                        label=f"Artist Payout · ₹{row.amount:,.0f}",
                        actor_id=user.get("id"), actor_role="admin",
                        metadata={"amount": row.amount, "utr": row.utr, "bulk": True},
                    )
                except Exception:
                    pass

                # Audit
                try:
                    await db.audit_logs.insert_one({
                        "id": str(uuid.uuid4()),
                        "actor_id": user.get("id"), "actor_role": user.get("role"),
                        "action": "payout.bulk_mark_paid",
                        "entity": "booking", "entity_id": row.booking_id,
                        "metadata": payload | {"payout_id": payout_id},
                        "created_at": utcnow(),
                    })
                except Exception:
                    pass

                results.append({"booking_id": row.booking_id, "ok": True, "payout_id": payout_id})
                succeeded += 1
                total_amount += float(row.amount)
            except Exception as e:  # noqa: BLE001
                log.warning("bulk payout for %s failed: %s", row.booking_id, e)
                results.append({"booking_id": row.booking_id, "ok": False, "error": str(e)})

        return {
            "ok": succeeded == len(body.rows),
            "processed": len(body.rows),
            "succeeded": succeeded,
            "failed": len(body.rows) - succeeded,
            "total_amount": round(total_amount, 2),
            "results": results,
        }

    @r.get("/admin/payouts/pending-list")
    async def pending_payouts(limit: int = Query(200, ge=1, le=1000),
                              _: dict = Depends(require_admin)):
        """Convenience listing — bookings that received payment but where
        the artist payout is not yet marked paid. Used by the bulk-marker
        UI as a pick list."""
        rows: List[Dict[str, Any]] = []
        cur = db.bookings.find(
            {
                "payment_status": {"$in": ["partial", "paid", "fully_paid"]},
                "$or": [
                    {"artist_payout_status": {"$ne": "paid"}},
                    {"artist_payout_status": {"$exists": False}},
                ],
            },
            {"_id": 0, "id": 1, "ref": 1, "event_date": 1, "artist_id": 1,
             "pricing": 1, "paid_amount": 1, "artist_payouts": 1},
        ).sort("event_date", -1)
        async for bk in cur:
            if len(rows) >= limit:
                break
            artist_share = float((bk.get("pricing") or {}).get("artist_payable")
                                 or (bk.get("pricing") or {}).get("artist_amount") or 0)
            paid_out = sum(float(p.get("amount") or 0) for p in (bk.get("artist_payouts") or []))
            outstanding = max(0.0, artist_share - paid_out)
            if outstanding <= 0:
                continue
            art = await db.users.find_one({"id": bk.get("artist_id")},
                                           {"_id": 0, "email": 1, "first_name": 1, "last_name": 1}) or {}
            rows.append({
                "booking_id": bk["id"],
                "booking_ref": bk.get("ref"),
                "event_date": bk.get("event_date"),
                "artist_email": art.get("email"),
                "artist_name": f"{art.get('first_name','')} {art.get('last_name','')}".strip(),
                "outstanding": round(outstanding, 2),
                "artist_share": round(artist_share, 2),
                "paid_out": round(paid_out, 2),
            })
        return {"items": rows, "count": len(rows)}

    return r
