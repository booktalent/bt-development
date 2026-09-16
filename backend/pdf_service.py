"""
PDF generation service for BookTalent contracts and invoices.
Pure-Python via ReportLab — no external binaries.
"""
import io
from datetime import datetime
from typing import Any, Dict
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

GOLD = colors.HexColor("#B8860B")
DARK = colors.HexColor("#1A1A2E")
MUTED = colors.HexColor("#6B7280")
LIGHT_BG = colors.HexColor("#FAF7EF")


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=DARK, alignment=TA_CENTER, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=11, textColor=GOLD, alignment=TA_CENTER, spaceAfter=14),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=DARK, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=10, textColor=DARK, leading=14, alignment=TA_JUSTIFY),
        "muted": ParagraphStyle("muted", parent=base["Normal"], fontName="Helvetica", fontSize=9, textColor=MUTED, leading=12),
        "right": ParagraphStyle("right", parent=base["Normal"], fontName="Helvetica", fontSize=10, alignment=TA_RIGHT),
    }


def _money(n: float) -> str:
    try:
        return f"INR {float(n):,.2f}"
    except Exception:
        return "INR 0.00"


def generate_contract_pdf(booking: dict, artist: dict, customer: dict, contract: dict) -> bytes:
    """Generate a professional contract PDF. Returns raw bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"Contract {booking.get('ref')}",
    )
    S = _styles()
    elems = []

    # Header
    elems.append(Paragraph("BookTalent", S["title"]))
    elems.append(Paragraph("Artist Performance Agreement", S["subtitle"]))
    elems.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceBefore=2, spaceAfter=12))

    # Meta strip
    pricing = booking.get("pricing", {})
    meta = [
        [Paragraph("<b>Contract Ref</b>", S["body"]), Paragraph(contract.get("ref", "—"), S["body"]),
         Paragraph("<b>Booking Ref</b>", S["body"]), Paragraph(booking.get("ref", "—"), S["body"])],
        [Paragraph("<b>Date of Agreement</b>", S["body"]), Paragraph(datetime.now().strftime("%d %B %Y"), S["body"]),
         Paragraph("<b>Status</b>", S["body"]), Paragraph(contract.get("status", "signed").upper(), S["body"])],
    ]
    meta_tbl = Table(meta, colWidths=[35 * mm, 50 * mm, 30 * mm, 55 * mm])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, GOLD),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(meta_tbl)
    elems.append(Spacer(1, 12))

    # Parties
    elems.append(Paragraph("PARTIES", S["h2"]))
    artist_name = artist.get("stage_name") or f"{artist.get('first_name', '')} {artist.get('last_name', '')}".strip()
    customer_name = booking.get("customer_name") or f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    parties = [
        [Paragraph("<b>ARTIST</b>", S["body"]), Paragraph("<b>CLIENT</b>", S["body"])],
        [Paragraph(f"<b>{artist_name}</b><br/>"
                   f"{artist.get('category', '')}<br/>"
                   f"{artist.get('city', '')}<br/>"
                   f"Phone: {artist.get('phone', '—')}<br/>"
                   f"Email: {artist.get('email', '—')}", S["body"]),
         Paragraph(f"<b>{customer_name}</b><br/>"
                   f"Phone: {booking.get('customer_phone', '—')}<br/>"
                   f"Email: {booking.get('customer_email', '—')}", S["body"])],
    ]
    p_tbl = Table(parties, colWidths=[85 * mm, 85 * mm])
    p_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elems.append(p_tbl)
    elems.append(Spacer(1, 10))

    # Event details
    elems.append(Paragraph("EVENT DETAILS", S["h2"]))
    event_rows = [
        ["Event Type", booking.get("event_type", "—")],
        ["Date & Time", f"{booking.get('event_date', '')}  -  {booking.get('event_time', '')}"],
        ["Venue", booking.get("venue", "—")],
        ["City", booking.get("city", "—")],
        ["Package", booking.get("package_name", "—")],
        ["Expected Guests", booking.get("guests", "—") or "—"],
        ["Language", booking.get("language_pref", "—") or "—"],
        ["Add-ons", ", ".join(booking.get("addons") or []) or "None"],
    ]
    e_tbl = Table(event_rows, colWidths=[45 * mm, 125 * mm])
    e_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(e_tbl)
    elems.append(Spacer(1, 10))

    # Financials — BookTalent is ONLY an intermediary. We only collect the
    # platform service fee + GST. The artist performance fee is settled directly
    # between Customer and Artist.
    elems.append(Paragraph("FINANCIAL TERMS", S["h2"]))
    fin_rows = [
        ["Description", "Amount"],
        ["Artist Performance Fee (paid by Client directly to Artist)", _money(pricing.get("artist_fee", pricing.get("package_fee", 0) + pricing.get("addons_total", 0)))],
        ["", ""],
        ["Platform Service Fee (5% of Artist Fee — payable to BookTalent)", _money(pricing.get("platform_fee", 0))],
        ["GST @ 18% on Platform Fee", _money(pricing.get("gst", 0))],
        ["AMOUNT PAYABLE TO BOOKTALENT", _money(pricing.get("total", 0))],
    ]
    f_tbl = Table(fin_rows, colWidths=[110 * mm, 60 * mm])
    f_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT_BG),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), GOLD),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(f_tbl)
    elems.append(Spacer(1, 6))
    elems.append(Paragraph(
        f"<i>The Artist Performance Fee of {_money(pricing.get('artist_fee', 0))} is settled directly between Client and Artist as per this agreement. BookTalent only invoices the Platform Service Fee + GST shown above.</i>",
        S["muted"],
    ))
    elems.append(Spacer(1, 14))

    # Terms
    elems.append(Paragraph("STANDARD TERMS & CONDITIONS", S["h2"]))
    terms = [
        "1. ROLE OF BOOKTALENT: BookTalent acts only as a technology platform facilitating the connection between the Customer and the Artist. The Artist Performance Fee shall be paid directly by the Customer to the Artist as mutually agreed in this contract. BookTalent shall NOT be responsible for the settlement, collection, or escrow of the Artist Performance Fee.",
        "2. The Artist agrees to perform as described above on the agreed date and time.",
        "3. The Client agrees to provide stage, sound system, electricity, hospitality and other technical requirements as per the package rider.",
        "4. CANCELLATION POLICY: Cancellations 15+ days prior to the event qualify for a full refund of the BookTalent Platform Service Fee. Within 7 days, the Platform Service Fee is non-refundable. Refund of any Artist Performance Fee already paid directly is governed by the mutual agreement between Customer and Artist.",
        "5. ARTIST CANCELLATION: In the event the Artist cancels for any reason, 100% of the BookTalent Platform Service Fee will be refunded and the Client will receive priority rebooking assistance. Refund of any Artist Performance Fee already paid is between Customer and Artist.",
        "6. PAYMENT TO ARTIST: The Artist Performance Fee of " + _money(pricing.get("artist_fee", 0)) + " shall be paid by the Customer directly to the Artist on or before the event date as mutually agreed.",
        "7. All disputes shall be resolved through BookTalent's grievance system and are subject to the jurisdiction of Mumbai, India.",
        "8. This contract is auto-generated by BookTalent and is governed by BookTalent's Master Service Agreement (https://booktalent.in/legal).",
        "9. Both parties acknowledge digital signature via the BookTalent platform constitutes acceptance of all terms herein.",
    ]
    for t in terms:
        elems.append(Paragraph(t, S["body"]))
        elems.append(Spacer(1, 3))

    elems.append(Spacer(1, 16))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elems.append(Spacer(1, 12))

    # Signatures
    sig_rows = [
        [Paragraph("__________________________", S["body"]), Paragraph("__________________________", S["body"])],
        [Paragraph(f"<b>{artist_name}</b><br/>Artist", S["muted"]),
         Paragraph(f"<b>{customer_name}</b><br/>Client", S["muted"])],
    ]
    s_tbl = Table(sig_rows, colWidths=[85 * mm, 85 * mm])
    s_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elems.append(s_tbl)
    elems.append(Spacer(1, 14))

    elems.append(Paragraph(
        f"<i>Digitally signed via BookTalent on {contract.get('signed_at', utcnow_fmt())}. Contract ID: {contract.get('id', '—')}</i>",
        S["muted"],
    ))

    doc.build(elems)
    return buf.getvalue()


def generate_invoice_pdf(booking: dict, artist: dict) -> bytes:
    """Generate a simple GST invoice for the booking."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm)
    S = _styles()
    elems = []

    elems.append(Paragraph("BookTalent Platform Service Invoice", S["title"]))
    elems.append(Paragraph("BookTalent India Pvt. Ltd. - GSTIN: 27AAFCB1234A1Z5", S["subtitle"]))
    elems.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=12))

    pricing = booking.get("pricing", {})
    rows = [
        ["Invoice No.", f"INV-{booking.get('ref', '')}"],
        ["Date", datetime.now().strftime("%d %b %Y")],
        ["Bill To", booking.get("customer_name", "—")],
        ["For Artist Booking", artist.get("stage_name") or artist.get("first_name", "—")],
        ["Event Date", booking.get("event_date", "—")],
        ["Reference Artist Fee", _money(pricing.get("artist_fee", pricing.get("package_fee", 0) + pricing.get("addons_total", 0)))],
    ]
    t = Table(rows, colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(t)
    elems.append(Spacer(1, 12))

    bill = [
        ["Description", "Amount"],
        ["Platform Service Fee (5% of Artist Fee)", _money(pricing.get("platform_fee", 0))],
        ["GST @ 18% (on Platform Service Fee only)", _money(pricing.get("gst", 0))],
        ["TOTAL PAID TO BOOKTALENT", _money(pricing.get("total", 0))],
    ]
    bt = Table(bill, colWidths=[110 * mm, 60 * mm])
    bt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), GOLD),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(bt)
    elems.append(Spacer(1, 14))
    elems.append(Paragraph(
        "<i>This invoice is only for the platform service charges collected by BookTalent. "
        f"The Artist Performance Fee of {_money(pricing.get('artist_fee', 0))} is settled directly between Customer and Artist as per the signed agreement and is NOT included on this invoice.</i>",
        S["muted"],
    ))
    elems.append(Spacer(1, 8))
    elems.append(Paragraph("Thank you for booking through BookTalent. This is a computer-generated invoice.", S["muted"]))

    doc.build(elems)
    return buf.getvalue()


def utcnow_fmt() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
