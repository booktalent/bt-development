"""
Iter 83 — Centralised Financial Engine.

Backend is the ONLY source of truth for price calculation. Frontend never
sums line items — it just displays what /api/finance/quote returns. This
prevents the classic "customer sees ₹1,05,000 but admin dashboard sees
₹1,18,000" desync bugs when GST%, Platform Fee%, or waiver logic changes.

Every place that used to inline `fee * 1.18` etc. must now call
`compute_price()` and use the resulting breakdown.

Business rules encoded (Sec 2-4, 5, 10, 38, 61):
  1. Artist Fee comes from the package + add-ons (no changes).
  2. Platform Fee = platform_fee_percent × Artist Fee.
  3. If artist is a "BookTalent Service Artist" (percentage_deal>0):
       → Platform Fee is fully WAIVED (customer sees the fee, then a
         matching negative waiver line, net = 0). Never merged silently.
       → BookTalent's revenue on that booking comes from the artist-side
         percentage deal (Sec 38), NOT the platform fee.
  4. GST is applied ONLY to (Artist Fee + Platform Fee NET after waiver).
     When gst_percent == 0, GST line is hidden in the response.
  5. Total = Artist Fee + Net Platform Fee + GST.
  6. BookTalent commission = artist_fee × percentage_deal (Sec 38).
     Artist payable = artist_fee − commission (Sec 61).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from routes.settings import get_settings


def _q(x: Any) -> float:
    """Round to 2 decimals half-up (money display convention in INR)."""
    if x is None:
        return 0.0
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


async def _artist_commercial(db: AsyncIOMotorDatabase, artist_id: Optional[str]) -> Dict[str, Any]:
    """Fetch a service-artist's commercial deal. Returns
    ``{"is_service": bool, "percentage_deal": float}``. Percentage is 0
    for a regular platform artist.
    """
    if not artist_id:
        return {"is_service": False, "percentage_deal": 0.0}
    prof = await db.artist_profiles.find_one(
        {"user_id": artist_id},
        {"is_service_artist": 1, "percentage_deal": 1, "_id": 0},
    ) or {}
    pct = float(prof.get("percentage_deal") or 0)
    return {
        "is_service": bool(prof.get("is_service_artist")) and pct > 0,
        "percentage_deal": pct,
    }


async def compute_price(
    db: AsyncIOMotorDatabase,
    *,
    artist_id: Optional[str] = None,
    package_fee: float = 0.0,
    addons_total: float = 0.0,
    coupon_discount: float = 0.0,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the canonical price breakdown for a booking.

    All amounts are rounded to 2 decimal places. The response is safe to
    return directly from public APIs — no secret fields.
    """
    s = settings or await get_settings(db)
    gst_pct = float(s.get("gst_percent", 18.0))
    fee_pct = float(s.get("platform_fee_percent", 5.0))
    commercial = await _artist_commercial(db, artist_id)

    artist_fee = _q(max(0.0, float(package_fee) + float(addons_total) - float(coupon_discount)))
    platform_fee_gross = _q(artist_fee * fee_pct / 100)
    platform_fee_waiver = _q(-platform_fee_gross) if commercial["is_service"] else 0.0
    platform_fee_net = _q(platform_fee_gross + platform_fee_waiver)

    taxable = _q(artist_fee + platform_fee_net)
    gst_amount = _q(taxable * gst_pct / 100) if gst_pct > 0 else 0.0
    total = _q(taxable + gst_amount)

    booktalent_commission = _q(artist_fee * commercial["percentage_deal"] / 100)
    artist_payable = _q(artist_fee - booktalent_commission)

    return {
        "artist_fee": artist_fee,
        "platform_fee_percent": fee_pct,
        "platform_fee": platform_fee_gross,        # gross (before waiver)
        "platform_fee_waiver": platform_fee_waiver,
        "platform_fee_net": platform_fee_net,      # after waiver — this is what the customer actually pays
        "is_service_artist": commercial["is_service"],
        "waiver_message": (
            f"Your {fee_pct:g}% Platform Fee has been waived for this artist."
            if commercial["is_service"] else ""
        ),
        "gst_percent": gst_pct,
        "gst_amount": gst_amount,
        "gst_visible": gst_pct > 0,                # UI: hide GST rows when 0
        "coupon_discount": _q(coupon_discount),
        "total": total,
        # settlement-side (admin/artist dashboards use these; safe to return
        # to the customer too since amounts are their own money)
        "booktalent_percentage": commercial["percentage_deal"],
        "booktalent_commission": booktalent_commission,
        "artist_payable": artist_payable,
    }


def build_payment_milestones(total: float, event_date_iso: Optional[str],
                             schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Given the total amount, event date, and configured schedule, return
    the concrete milestone list with amount + due-date resolved.

    ``schedule[i]`` shape:
      { "milestone": "booking_advance", "label": "...", "percent": 30,
        "offset_days": -7 | None, "mandatory": True }
    """
    from datetime import datetime, timezone, timedelta

    out: List[Dict[str, Any]] = []
    remaining = _q(total)
    # Pass 1: compute non-last amounts
    for i, m in enumerate(schedule):
        pct = float(m.get("percent", 0))
        amt = _q(total * pct / 100)
        # Last milestone absorbs rounding drift so the sum equals the total exactly.
        if i == len(schedule) - 1:
            amt = _q(remaining)
        remaining = _q(remaining - amt)

        offset = m.get("offset_days")
        due_iso: Optional[str] = None
        if offset is None:
            # No offset → due at booking confirmation (i.e. immediately)
            due_iso = None
        elif event_date_iso:
            try:
                base = datetime.fromisoformat(event_date_iso.replace("Z", "+00:00"))
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                due_iso = (base + timedelta(days=int(offset))).date().isoformat()
            except Exception:
                due_iso = None
        out.append({
            "milestone": m.get("milestone"),
            "label": m.get("label"),
            "percent": pct,
            "amount": amt,
            "due_date": due_iso,       # None means "at booking confirmation"
            "mandatory": bool(m.get("mandatory", True)),
            "status": "pending",       # will flip to paid / overdue later
        })
    return out
