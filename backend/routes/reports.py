"""
Iter 87 — Admin Reports + Unified Audit Log Viewer.

Three focused reports for the super_admin:
  * artist_bookings   — revenue + booking count per artist (with paid/pending split)
  * manager_leads     — lead pipeline breakdown per manager (12 stages)
  * platform_waivers  — bookings where the 5% platform fee was waived (Service Artists)

Every endpoint returns JSON by default and CSV when ?format=csv is passed
so the admin panel can offer one-click download.

Also exposes:
  * GET /admin/audit-logs/unified — merges the two audit collections
    (admin_audit_log + audit_logs) into a single time-sorted feed with
    filters for actor, action, entity, date range.
"""
from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from csv_safe import safe_row  # SEC — formula-injection guard

log = logging.getLogger("reports")


# ─── CSV helper ─────────────────────────────────────────────────────
def _rows_to_csv(rows: List[Dict[str, Any]], columns: List[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(safe_row([row.get(c, "") for c in columns]))
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Router factory ─────────────────────────────────────────────────
def make_reports_router(db: AsyncIOMotorDatabase, require_admin) -> APIRouter:
    r = APIRouter()

    # ══════════════════════════════════════════════════════════════
    # 1. Artist-wise booking report
    # ══════════════════════════════════════════════════════════════
    @r.get("/admin/reports/artist-bookings")
    async def report_artist_bookings(
        start: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
        end: Optional[str] = Query(None),
        format: str = Query("json", regex="^(json|csv)$"),
        _: dict = Depends(require_admin),
    ):
        q: Dict[str, Any] = {"status": {"$in": ["confirmed", "started", "completed", "reviewed"]}}
        if start:
            q.setdefault("event_date", {})["$gte"] = start
        if end:
            q.setdefault("event_date", {})["$lte"] = end

        # Aggregate per artist
        agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "artist_id": "", "artist_name": "", "artist_email": "",
            "bookings_count": 0, "gross_revenue": 0.0, "artist_payable": 0.0,
            "platform_fee": 0.0, "gst": 0.0,
            "paid_count": 0, "pending_payout_count": 0,
        })
        async for b in db.bookings.find(q, {"_id": 0}):
            aid = b.get("artist_id") or "unknown"
            row = agg[aid]
            row["artist_id"] = aid
            pricing = b.get("pricing") or {}
            row["bookings_count"] += 1
            row["gross_revenue"] += float(pricing.get("total", 0) or 0)
            row["artist_payable"] += float(pricing.get("artist_payable", pricing.get("artist_fee", 0)) or 0)
            row["platform_fee"] += float(pricing.get("platform_fee", 0) or 0)
            row["gst"] += float(pricing.get("gst", 0) or 0)
            if b.get("artist_payout_status") == "paid":
                row["paid_count"] += 1
            else:
                row["pending_payout_count"] += 1

        # Enrich with artist names
        for aid, row in agg.items():
            u = await db.users.find_one({"id": aid}, {"first_name": 1, "last_name": 1, "email": 1}) or {}
            p = await db.artist_profiles.find_one({"user_id": aid}, {"stage_name": 1}) or {}
            row["artist_name"] = p.get("stage_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Unknown"
            row["artist_email"] = u.get("email", "")

        rows = sorted(agg.values(), key=lambda x: x["gross_revenue"], reverse=True)

        if format == "csv":
            return _rows_to_csv(
                rows,
                ["artist_id", "artist_name", "artist_email", "bookings_count",
                 "gross_revenue", "artist_payable", "platform_fee", "gst",
                 "paid_count", "pending_payout_count"],
                f"artist_bookings_{(start or 'all')}_{(end or 'now')}.csv",
            )
        return {"items": rows, "count": len(rows),
                "totals": {
                    "gross_revenue": sum(r["gross_revenue"] for r in rows),
                    "artist_payable": sum(r["artist_payable"] for r in rows),
                    "platform_fee": sum(r["platform_fee"] for r in rows),
                    "gst": sum(r["gst"] for r in rows),
                    "bookings": sum(r["bookings_count"] for r in rows),
                }}

    # ══════════════════════════════════════════════════════════════
    # 2. Manager-wise lead report
    # ══════════════════════════════════════════════════════════════
    @r.get("/admin/reports/manager-leads")
    async def report_manager_leads(
        format: str = Query("json", regex="^(json|csv)$"),
        _: dict = Depends(require_admin),
    ):
        STAGES = [
            "new_lead", "contacted", "requirement_received", "artist_suggested",
            "quotation_sent", "negotiation", "booking_pending", "booking_confirmed",
            "payment_pending", "event_upcoming", "event_completed",
            "closed", "lost_cancelled",
        ]

        # All active managers (so managers with zero leads still show up)
        managers = await db.users.find(
            {"role": "manager"}, {"id": 1, "email": 1, "first_name": 1, "last_name": 1}
        ).to_list(500)

        rows: List[Dict[str, Any]] = []
        for m in managers:
            row: Dict[str, Any] = {
                "manager_id": m["id"],
                "manager_email": m.get("email", ""),
                "manager_name": f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
                "total_leads": 0,
                "won": 0,
                "lost": 0,
                "in_pipeline": 0,
            }
            for s in STAGES:
                cnt = await db.leads.count_documents({"assigned_manager_id": m["id"], "stage": s})
                row[f"stage_{s}"] = cnt
                row["total_leads"] += cnt
                if s == "closed":
                    row["won"] += cnt
                elif s == "lost_cancelled":
                    row["lost"] += cnt
                else:
                    row["in_pipeline"] += cnt
            # Conversion rate = won / (won + lost) when either is > 0
            denom = row["won"] + row["lost"]
            row["conversion_pct"] = round((row["won"] / denom) * 100, 1) if denom else 0
            rows.append(row)

        rows.sort(key=lambda x: x["total_leads"], reverse=True)

        if format == "csv":
            columns = ["manager_id", "manager_email", "manager_name", "total_leads",
                       "won", "lost", "in_pipeline", "conversion_pct"] + [f"stage_{s}" for s in STAGES]
            return _rows_to_csv(rows, columns, "manager_leads.csv")
        return {"items": rows, "count": len(rows), "stages": STAGES}

    # ══════════════════════════════════════════════════════════════
    # 3. Platform fee waiver report (Service Artists)
    # ══════════════════════════════════════════════════════════════
    @r.get("/admin/reports/platform-waivers")
    async def report_platform_waivers(
        start: Optional[str] = None,
        end: Optional[str] = None,
        format: str = Query("json", regex="^(json|csv)$"),
        _: dict = Depends(require_admin),
    ):
        # A waiver is present when pricing.platform_fee_waived == True (set
        # by financial_engine for Service Artists) OR pricing.platform_fee == 0
        # despite a total > 0.
        q: Dict[str, Any] = {
            "$or": [
                {"pricing.platform_fee_waived": True},
                {"pricing.platform_fee": 0, "pricing.total": {"$gt": 0}},
            ]
        }
        if start:
            q.setdefault("event_date", {})["$gte"] = start
        if end:
            q.setdefault("event_date", {})["$lte"] = end

        rows: List[Dict[str, Any]] = []
        total_waived = 0.0
        async for b in db.bookings.find(q, {"_id": 0}):
            pricing = b.get("pricing") or {}
            # Compute what the platform fee would have been at the configured rate
            settings = await db.platform_settings.find_one({"id": "platform"}) or {}
            pct = float(settings.get("platform_fee_percent", 5))
            base = float(pricing.get("package_fee", 0) or 0) + float(pricing.get("addons_total", 0) or 0)
            would_be_fee = round(base * pct / 100, 2)
            actual_fee = float(pricing.get("platform_fee", 0) or 0)
            waived_amount = max(0, round(would_be_fee - actual_fee, 2))
            total_waived += waived_amount
            u = await db.users.find_one({"id": b.get("artist_id")}, {"first_name": 1, "last_name": 1, "email": 1}) or {}
            p = await db.artist_profiles.find_one({"user_id": b.get("artist_id")},
                                                    {"stage_name": 1, "is_service_artist": 1}) or {}
            rows.append({
                "booking_id": b.get("id"),
                "ref": b.get("ref"),
                "event_date": b.get("event_date"),
                "artist_id": b.get("artist_id"),
                "artist_name": p.get("stage_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
                "is_service_artist": p.get("is_service_artist", False),
                "gross_total": float(pricing.get("total", 0) or 0),
                "actual_platform_fee": actual_fee,
                "would_be_platform_fee": would_be_fee,
                "waived_amount": waived_amount,
                "customer_name": b.get("customer_name", ""),
            })

        rows.sort(key=lambda x: x["event_date"] or "", reverse=True)

        if format == "csv":
            return _rows_to_csv(
                rows,
                ["ref", "event_date", "artist_name", "customer_name",
                 "is_service_artist", "gross_total", "actual_platform_fee",
                 "would_be_platform_fee", "waived_amount"],
                f"platform_waivers_{(start or 'all')}_{(end or 'now')}.csv",
            )
        return {"items": rows, "count": len(rows),
                "totals": {"waived_amount": round(total_waived, 2)}}

    # ══════════════════════════════════════════════════════════════
    # 4. Unified Audit Log Viewer
    # ══════════════════════════════════════════════════════════════
    @r.get("/admin/audit-logs/unified")
    async def unified_audit_log(
        actor: Optional[str] = Query(None, description="Email or user_id substring match"),
        action: Optional[str] = None,
        entity: Optional[str] = None,
        start: Optional[str] = Query(None, description="ISO datetime"),
        end: Optional[str] = None,
        limit: int = 200,
        _: dict = Depends(require_admin),
    ):
        """Merges the two audit collections into a single time-sorted feed.

        Sources:
          * admin_audit_log — RBAC / admin actions (server.py:audit_log)
          * audit_logs      — CRM / booking / financial actions (settings.py:record_audit)
        """
        limit = max(1, min(int(limit), 1000))

        # ── source 1: admin_audit_log ──
        q1: Dict[str, Any] = {}
        if action:
            q1["action"] = {"$regex": action, "$options": "i"}
        if actor:
            q1["$or"] = [
                {"actor_email": {"$regex": actor, "$options": "i"}},
                {"actor_id": actor},
            ]
        if start:
            q1.setdefault("created_at", {})["$gte"] = start
        if end:
            q1.setdefault("created_at", {})["$lte"] = end
        admin_rows = await db.admin_audit_log.find(q1, {"_id": 0}).sort("created_at", -1).to_list(limit)

        # ── source 2: audit_logs ──
        q2: Dict[str, Any] = {}
        if action:
            q2["action"] = {"$regex": action, "$options": "i"}
        if entity:
            q2["entity"] = entity
        if actor:
            q2["$or"] = [
                {"actor_email": {"$regex": actor, "$options": "i"}},
                {"actor_id": actor},
            ]
        if start:
            q2.setdefault("at", {})["$gte"] = start
        if end:
            q2.setdefault("at", {})["$lte"] = end
        biz_rows = await db.audit_logs.find(q2, {"_id": 0}).sort("at", -1).to_list(limit)

        # Normalise into a single shape
        unified: List[Dict[str, Any]] = []
        for row in admin_rows:
            unified.append({
                "source": "admin",
                "at": row.get("created_at"),
                "actor_id": row.get("actor_id"),
                "actor_email": row.get("actor_email"),
                "actor_role": row.get("actor_role", "admin"),
                "action": row.get("action"),
                "entity": row.get("target_type") or row.get("entity"),
                "entity_id": row.get("target_id") or row.get("entity_id"),
                "old_value": row.get("old_value"),
                "new_value": row.get("new_value"),
                "metadata": row.get("meta") or row.get("metadata"),
                "ip": row.get("ip"),
            })
        for row in biz_rows:
            unified.append({
                "source": "business",
                "at": row.get("at") or row.get("created_at"),
                "actor_id": row.get("actor_id"),
                "actor_email": row.get("actor_email"),
                "actor_role": row.get("actor_role"),
                "action": row.get("action"),
                "entity": row.get("entity"),
                "entity_id": row.get("entity_id"),
                "old_value": row.get("old_value"),
                "new_value": row.get("new_value"),
                "metadata": row.get("metadata") or row.get("meta"),
                "ip": row.get("ip"),
            })

        unified.sort(key=lambda x: x.get("at") or "", reverse=True)
        unified = unified[:limit]
        return {"items": unified, "count": len(unified)}

    return r
