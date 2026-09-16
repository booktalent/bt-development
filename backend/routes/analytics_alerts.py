"""
Analytics Slack Alerts — near-real-time founder alerting.

Two health signals monitored on a daily cadence:

  1. GMV week-over-week drop > 20 %  → alert
  2. Monthly artist churn > 15 %      → alert

Each alert kind is debounced with a 7-day cooldown by storing a marker in
`analytics_alerts` so Slack isn't spammed when the metric stays bad.

An admin-only endpoint `POST /api/admin/analytics/run-alerts` lets ops
force a check immediately (useful for verification without waiting for
the daily tick).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from routes.iter89 import notify_slack

log = logging.getLogger("analytics_alerts")

# ─── Thresholds & cadence (fixed defaults per handoff) ─────────────────
GMV_WOW_DROP_PCT_THRESHOLD = 20.0    # alert when this-week GMV falls >20% vs prior week
CHURN_PCT_THRESHOLD = 15.0           # alert when churn > 15%
ALERT_COOLDOWN_HOURS = 24 * 7        # do not repeat the same alert kind within a week
CHECK_INTERVAL_SECONDS = 60 * 60 * 24  # daily background sweep


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Metric calculators ────────────────────────────────────────────────
async def _gmv_between(db: AsyncIOMotorDatabase, start: datetime, end: datetime) -> float:
    """Sum booking pricing.total for confirmed/completed events with
    event_date in [start, end)."""
    total = 0.0
    s = start.strftime("%Y-%m-%d")
    e = end.strftime("%Y-%m-%d")
    async for b in db.bookings.find(
        {
            "status": {"$in": ["confirmed", "completed", "reviewed"]},
            "event_date": {"$gte": s, "$lt": e},
        },
        {"_id": 0, "pricing": 1},
    ):
        total += float((b.get("pricing") or {}).get("total", 0) or 0)
    return round(total, 2)


async def compute_gmv_wow(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """This week (last 7d) vs prior week (7-14d)."""
    now = utcnow()
    this_end = now
    this_start = now - timedelta(days=7)
    prev_start = now - timedelta(days=14)
    this_gmv = await _gmv_between(db, this_start, this_end)
    prev_gmv = await _gmv_between(db, prev_start, this_start)
    if prev_gmv <= 0:
        drop_pct = 0.0
    else:
        drop_pct = round(((prev_gmv - this_gmv) / prev_gmv) * 100, 1)
    return {
        "this_week_gmv": this_gmv,
        "prev_week_gmv": prev_gmv,
        "drop_pct": drop_pct,
        "this_window": [this_start.strftime("%Y-%m-%d"), this_end.strftime("%Y-%m-%d")],
        "prev_window": [prev_start.strftime("%Y-%m-%d"), this_start.strftime("%Y-%m-%d")],
    }


async def compute_churn(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """Churn = artists active in the last 30 days who have zero bookings
    in the last 7 days."""
    now = utcnow()
    d30 = now - timedelta(days=30)
    d7 = now - timedelta(days=7)
    active_30, active_7 = set(), set()
    async for b in db.bookings.find(
        {
            "status": {"$in": ["confirmed", "completed", "reviewed"]},
            "event_date": {"$gte": d30.strftime("%Y-%m-%d")},
        },
        {"_id": 0, "artist_id": 1, "event_date": 1},
    ):
        aid = b.get("artist_id")
        if not aid:
            continue
        active_30.add(aid)
        if b.get("event_date", "") >= d7.strftime("%Y-%m-%d"):
            active_7.add(aid)
    churned = active_30 - active_7
    pct = round((len(churned) / len(active_30)) * 100, 1) if active_30 else 0.0
    return {
        "active_30d": len(active_30),
        "active_7d": len(active_7),
        "churned": len(churned),
        "churn_pct": pct,
    }


# ─── Alert dispatch w/ cooldown ────────────────────────────────────────
async def _should_alert(db: AsyncIOMotorDatabase, kind: str) -> bool:
    row = await db.analytics_alerts.find_one({"kind": kind}, sort=[("sent_at", -1)])
    if not row:
        return True
    try:
        sent_at = datetime.fromisoformat(row["sent_at"])
    except Exception:
        return True
    return (utcnow() - sent_at) >= timedelta(hours=ALERT_COOLDOWN_HOURS)


async def _record_alert(db: AsyncIOMotorDatabase, kind: str, payload: Dict[str, Any]) -> None:
    await db.analytics_alerts.insert_one({
        "kind": kind,
        "payload": payload,
        "sent_at": utcnow().isoformat(),
    })


async def run_alert_check(db: AsyncIOMotorDatabase, *, force: bool = False) -> Dict[str, Any]:
    """Compute both metrics and fire Slack alerts if breached.

    `force=True` bypasses the cooldown — used by the admin manual trigger.
    Returns a summary the caller can render.
    """
    summary: Dict[str, Any] = {"checked_at": utcnow().isoformat(), "alerts_sent": []}

    gmv = await compute_gmv_wow(db)
    summary["gmv"] = gmv
    if gmv["drop_pct"] > GMV_WOW_DROP_PCT_THRESHOLD:
        if force or await _should_alert(db, "gmv_wow_drop"):
            text = (
                f":chart_with_downwards_trend: *GMV alert — {gmv['drop_pct']}% drop week-over-week*\n"
                f"This week: ₹{gmv['this_week_gmv']:,.0f}  (window {gmv['this_window'][0]} → {gmv['this_window'][1]})\n"
                f"Prev week: ₹{gmv['prev_week_gmv']:,.0f}  (window {gmv['prev_window'][0]} → {gmv['prev_window'][1]})\n"
                f"Threshold: > {GMV_WOW_DROP_PCT_THRESHOLD}% drop\n"
                f"→ Review Admin → Founder KPI Dashboard for the driver."
            )
            await notify_slack(db, text=text)
            await _record_alert(db, "gmv_wow_drop", gmv)
            summary["alerts_sent"].append("gmv_wow_drop")

    churn = await compute_churn(db)
    summary["churn"] = churn
    if churn["churn_pct"] > CHURN_PCT_THRESHOLD:
        if force or await _should_alert(db, "churn_high"):
            text = (
                f":warning: *Artist churn alert — {churn['churn_pct']}% churned*\n"
                f"{churn['churned']} of {churn['active_30d']} artists active in the last 30d "
                f"had zero bookings in the last 7d.\n"
                f"Threshold: > {CHURN_PCT_THRESHOLD}%\n"
                f"→ Check Admin → Founder KPI Dashboard → churn card."
            )
            await notify_slack(db, text=text)
            await _record_alert(db, "churn_high", churn)
            summary["alerts_sent"].append("churn_high")

    return summary


# ─── Background loop ───────────────────────────────────────────────────
async def analytics_alerts_loop(db: AsyncIOMotorDatabase) -> None:
    """Daily sweep. Small initial delay so we don't run mid-boot."""
    await asyncio.sleep(60)
    while True:
        try:
            await run_alert_check(db)
        except Exception as e:  # noqa: BLE001
            log.warning("analytics_alerts_loop error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ─── Router (admin trigger + status view) ──────────────────────────────
def make_analytics_alerts_router(db: AsyncIOMotorDatabase, require_admin) -> APIRouter:
    r = APIRouter()

    @r.post("/admin/analytics/run-alerts")
    async def trigger_now(force: bool = Query(True, description="Bypass 7-day cooldown"),
                          _: dict = Depends(require_admin)):
        return await run_alert_check(db, force=force)

    @r.get("/admin/analytics/alert-history")
    async def alert_history(limit: int = Query(50, ge=1, le=500),
                            _: dict = Depends(require_admin)):
        rows = await db.analytics_alerts.find({}, {"_id": 0}).sort("sent_at", -1).to_list(limit)
        return {
            "items": rows,
            "count": len(rows),
            "thresholds": {
                "gmv_wow_drop_pct": GMV_WOW_DROP_PCT_THRESHOLD,
                "churn_pct": CHURN_PCT_THRESHOLD,
                "cooldown_hours": ALERT_COOLDOWN_HOURS,
            },
        }

    return r
