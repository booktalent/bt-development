"""
Email service — sends transactional emails via Gmail SMTP.

Requires the following env vars (set in backend/.env):
    SMTP_HOST         - smtp.gmail.com
    SMTP_PORT         - 587 (STARTTLS)
    SMTP_USER         - Gmail address used to authenticate
    SMTP_PASSWORD     - 16-char Google App Password (2FA required on the account)
    SMTP_FROM_EMAIL   - address that appears in the From header
    SMTP_FROM_NAME    - display name shown next to the address

If SMTP_USER / SMTP_PASSWORD are missing, we degrade to mock mode: emails
are logged instead of sent. Mock mode never returns the OTP to the caller —
the OTP is only visible in server logs (this closes the previous
"passwordless-login" backdoor).
"""
import os
import ssl
import asyncio
import logging
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid
from typing import Optional

log = logging.getLogger("booktalent.email")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587").strip() or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = (os.environ.get("SMTP_PASSWORD", "") or "").replace(" ", "").strip()
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USER).strip()
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "BookTalent").strip()

SMTP_ENABLED = bool(SMTP_USER and SMTP_PASSWORD)

if SMTP_ENABLED:
    log.info("Gmail SMTP configured host=%s port=%s user=%s", SMTP_HOST, SMTP_PORT, SMTP_USER)
else:
    log.warning("SMTP disabled — SMTP_USER / SMTP_PASSWORD env vars missing. Emails will be mocked.")


def is_email_enabled() -> bool:
    return SMTP_ENABLED


def generate_otp() -> str:
    """Cryptographically secure 6-digit numeric OTP.

    The previous implementation returned a hard-coded ``123456`` when the
    provider was disabled — that was a passwordless-login backdoor. We now
    always return a fresh random code regardless of provider state.
    """
    return f"{secrets.randbelow(900000) + 100000}"


def _send_sync(to_email: str, subject: str, html: str, text_fallback: Optional[str] = None) -> dict:
    """Blocking SMTP send. Wrapped by :func:`asyncio.to_thread` in the async helpers."""
    if not SMTP_ENABLED:
        log.info("[MOCK email] to=%s subject=%s", to_email, subject)
        return {"sent": True, "mock": True}

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=SMTP_FROM_EMAIL.split("@")[-1] if "@" in SMTP_FROM_EMAIL else "booktalent.in")
    # Plain-text fallback — some clients (Apple Mail preview, screen readers)
    # rely on this even when HTML is present.
    plain = text_fallback or "This email requires an HTML-capable client to view."
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        log.info("SMTP OK to=%s subject=%s", to_email, subject)
        return {"sent": True, "mock": False}
    except smtplib.SMTPAuthenticationError as e:
        log.error("SMTP auth failed (%s). Check SMTP_PASSWORD is a Gmail App Password.", e)
        return {"sent": False, "mock": False, "error": "SMTP authentication failed — check App Password"}
    except Exception as e:  # noqa: BLE001
        log.error("SMTP send failed to=%s subject=%s error=%s", to_email, subject, e)
        return {"sent": False, "mock": False, "error": str(e)}


# ─── Templates ─────────────────────────────────────────────────────────────
def _otp_html(name: str, otp: str, purpose: str = "Verify your email") -> str:
    """Premium dark-luxury OTP email template using inline CSS + tables."""
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#F0EEFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
        <tr><td style="padding:32px 40px 16px;">
          <div style="display:inline-block;font-family:'Times New Roman',serif;font-size:24px;font-weight:700;color:#F0EEFF;">
            Book<span style="color:#D4AF37;">Talent</span>
          </div>
        </td></tr>
        <tr><td style="padding:0 40px;">
          <div style="height:1px;background:linear-gradient(to right,transparent,#D4AF37,transparent);"></div>
        </td></tr>
        <tr><td style="padding:32px 40px;">
          <div style="font-family:'Times New Roman',serif;font-size:28px;font-weight:700;color:#F0EEFF;line-height:1.2;margin-bottom:10px;">
            {purpose}
          </div>
          <p style="font-size:14px;color:rgba(240,238,255,0.6);line-height:1.6;margin:0 0 24px;">
            Hi {name or 'there'}, use the verification code below to continue. This code expires in <b>10 minutes</b>.
          </p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">
            <tr><td align="center" style="background:linear-gradient(135deg,rgba(212,175,55,0.12),rgba(109,40,217,0.08));border:1px solid rgba(212,175,55,0.3);border-radius:14px;padding:24px;">
              <div style="font-size:11px;color:rgba(240,238,255,0.5);letter-spacing:2px;margin-bottom:10px;">VERIFICATION CODE</div>
              <div style="font-family:'Courier New',monospace;font-size:38px;font-weight:700;color:#F1D17A;letter-spacing:10px;">{otp}</div>
            </td></tr>
          </table>
          <p style="font-size:13px;color:rgba(240,238,255,0.6);line-height:1.6;margin:18px 0 0;">
            If you didn't request this code, you can safely ignore this email — your account remains secure.
          </p>
        </td></tr>
        <tr><td style="padding:0 40px 28px;">
          <div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0;"></div>
          <p style="font-size:11px;color:rgba(240,238,255,0.4);margin:0;text-align:center;">
            © 2026 BookTalent · India's Premium Talent Marketplace
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _password_reset_html(name: str, otp: str, reset_link: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#F0EEFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
        <tr><td style="padding:32px 40px 16px;">
          <div style="display:inline-block;font-family:'Times New Roman',serif;font-size:24px;font-weight:700;color:#F0EEFF;">
            Book<span style="color:#D4AF37;">Talent</span>
          </div>
        </td></tr>
        <tr><td style="padding:0 40px;">
          <div style="height:1px;background:linear-gradient(to right,transparent,#D4AF37,transparent);"></div>
        </td></tr>
        <tr><td style="padding:32px 40px;">
          <div style="font-family:'Times New Roman',serif;font-size:28px;font-weight:700;color:#F0EEFF;line-height:1.2;margin-bottom:10px;">
            Reset your <span style="color:#D4AF37;">password</span>
          </div>
          <p style="font-size:14px;color:rgba(240,238,255,0.6);line-height:1.6;margin:0 0 20px;">
            Hi {name or 'there'}, we received a request to reset your BookTalent password. You can either click the button below or enter the 6-digit code on the reset page. Both expire in <b>10 minutes</b>.
          </p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 4px;">
            <tr><td align="center">
              <a href="{reset_link}" style="display:inline-block;background:linear-gradient(135deg,#D4AF37,#B8931F);color:#0F0F1B;text-decoration:none;font-weight:700;padding:14px 32px;border-radius:10px;font-size:14px;letter-spacing:0.5px;">Reset Password →</a>
            </td></tr>
          </table>
          <p style="font-size:12px;color:rgba(240,238,255,0.45);text-align:center;margin:8px 0 24px;">Or copy this link: <span style="color:rgba(240,238,255,0.65);word-break:break-all;">{reset_link}</span></p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0 0;">
            <tr><td align="center" style="background:linear-gradient(135deg,rgba(212,175,55,0.12),rgba(109,40,217,0.08));border:1px solid rgba(212,175,55,0.3);border-radius:14px;padding:24px;">
              <div style="font-size:11px;color:rgba(240,238,255,0.5);letter-spacing:2px;margin-bottom:10px;">RESET CODE</div>
              <div style="font-family:'Courier New',monospace;font-size:38px;font-weight:700;color:#F1D17A;letter-spacing:10px;">{otp}</div>
            </td></tr>
          </table>
          <p style="font-size:13px;color:rgba(240,238,255,0.6);line-height:1.6;margin:18px 0 0;">
            Didn't request a password reset? You can safely ignore this email — your password stays the same.
          </p>
        </td></tr>
        <tr><td style="padding:0 40px 28px;">
          <div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0;"></div>
          <p style="font-size:11px;color:rgba(240,238,255,0.4);margin:0;text-align:center;">
            © 2026 BookTalent · India's Premium Talent Marketplace
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# ─── Public async helpers ──────────────────────────────────────────────────
async def send_otp_email(to_email: str, otp: str, name: str = "", purpose: str = "Verify your email") -> dict:
    """Send an OTP email for signup / email verification."""
    subject = f"Your BookTalent verification code: {otp}"
    html = _otp_html(name, otp, purpose=purpose)
    text = f"Your BookTalent verification code is {otp}. It expires in 10 minutes."
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)


async def send_password_reset_email(to_email: str, name: str, otp: str, reset_link: str) -> dict:
    """Send a password-reset email containing both a magic link and a 6-digit OTP."""
    subject = "Reset your BookTalent password"
    html = _password_reset_html(name, otp, reset_link)
    text = (
        f"Hi {name or 'there'},\n\n"
        f"Reset your BookTalent password using this link (valid 10 minutes):\n{reset_link}\n\n"
        f"Or enter this code on the reset page: {otp}\n\n"
        "If you didn't request this, you can ignore this email."
    )
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)


# ─── Welcome email (post-signup) ────────────────────────────────────────
def _welcome_html(name: str, role: str, dashboard_url: str, next_step_label: str, next_step_desc: str) -> str:
    role_line = {
        "customer": "You're all set to discover India's finest artists and book them for your next event.",
        "artist": "Your artist profile is ready to be filled out. Once approved, you'll start receiving bookings.",
        "agency": "Your agency workspace is live. Invite your roster and start accepting bookings on their behalf.",
        "corporate": "Your corporate workspace is ready — book curated talent for company events with a single invoice.",
    }.get(role, "Welcome aboard!")
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#F0EEFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
        <tr><td style="padding:32px 40px 16px;">
          <div style="display:inline-block;font-family:'Times New Roman',serif;font-size:24px;font-weight:700;color:#F0EEFF;">
            Book<span style="color:#D4AF37;">Talent</span>
          </div>
        </td></tr>
        <tr><td style="padding:0 40px;">
          <div style="height:1px;background:linear-gradient(to right,transparent,#D4AF37,transparent);"></div>
        </td></tr>
        <tr><td style="padding:32px 40px 8px;">
          <div style="font-family:'Times New Roman',serif;font-size:30px;font-weight:700;color:#F0EEFF;line-height:1.2;margin-bottom:12px;">
            Welcome to <span style="color:#D4AF37;">BookTalent</span>, {name or 'there'} ✨
          </div>
          <p style="font-size:15px;color:rgba(240,238,255,0.72);line-height:1.65;margin:0 0 18px;">
            {role_line}
          </p>
          <p style="font-size:14px;color:rgba(240,238,255,0.6);line-height:1.65;margin:0 0 22px;">
            You've joined 68,000+ event planners and artists on India's most premium talent marketplace. Here's what to do next.
          </p>
        </td></tr>
        <tr><td style="padding:8px 40px 8px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:rgba(212,175,55,0.08);border:1px solid rgba(212,175,55,0.25);border-radius:14px;">
            <tr><td style="padding:20px 22px;">
              <div style="font-size:11px;color:#D4AF37;letter-spacing:2px;margin-bottom:6px;">NEXT STEP</div>
              <div style="font-family:'Times New Roman',serif;font-size:20px;color:#F0EEFF;font-weight:700;margin-bottom:6px;">{next_step_label}</div>
              <p style="font-size:13px;color:rgba(240,238,255,0.65);margin:0 0 14px;line-height:1.6;">{next_step_desc}</p>
              <a href="{dashboard_url}" style="display:inline-block;background:linear-gradient(135deg,#D4AF37,#B8931F);color:#0F0F1B;text-decoration:none;font-weight:700;padding:11px 22px;border-radius:9px;font-size:13px;letter-spacing:0.4px;">Open Dashboard →</a>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:24px 40px 12px;">
          <div style="font-size:13px;color:rgba(240,238,255,0.55);line-height:1.65;">
            Need a hand? Reply to this email and our concierge team will be right with you.
          </div>
        </td></tr>
        <tr><td style="padding:0 40px 28px;">
          <div style="height:1px;background:rgba(255,255,255,0.08);margin:16px 0;"></div>
          <p style="font-size:11px;color:rgba(240,238,255,0.4);margin:0;text-align:center;">
            © 2026 BookTalent · India's Premium Talent Marketplace
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


async def send_welcome_email(to_email: str, name: str, role: str, base_url: str = "") -> dict:
    """Fired the moment a signup completes. Non-blocking (call via asyncio.create_task)."""
    base = (base_url or "").rstrip("/")
    dashboards = {
        "customer": (f"{base}/search", "Book your first artist",
                     "Browse 5,200+ vetted artists across 32 cities and lock in your date with our secure booking flow."),
        "artist": (f"{base}/artist", "Complete your artist profile",
                   "Add your bio, showreel and rate card — the more complete your profile, the higher you rank in search."),
        "agency": (f"{base}/agency", "Invite your first artist",
                   "Send referral links to the artists on your roster and start managing bookings from one dashboard."),
        "corporate": (f"{base}/corporate", "Plan your first event",
                      "Curated talent, single invoice, transparent GST — everything your finance team needs."),
    }
    url, label, desc = dashboards.get(role, (base + "/", "Explore BookTalent",
                                              "Discover artists and start creating unforgettable events."))
    subject = "Welcome to BookTalent ✨"
    html = _welcome_html(name, role, url, label, desc)
    text = (
        f"Hi {name or 'there'},\n\n"
        f"Welcome to BookTalent. Your account is ready.\n\n"
        f"Next step: {label} — {url}\n\n"
        "Need help? Just reply to this email."
    )
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)


async def send_booking_confirmation_email(to_email: str, name: str, booking_ref: str, artist_name: str, event_date: str, timeline_html: str = "") -> dict:
    subject = f"Booking Confirmed — {booking_ref}"
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,sans-serif;color:#F0EEFF;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;">
  <tr><td style="padding:36px;">
    <div style="font-family:'Times New Roman',serif;font-size:22px;font-weight:700;color:#F0EEFF;margin-bottom:18px;">Book<span style="color:#D4AF37;">Talent</span></div>
    <h2 style="font-family:'Times New Roman',serif;font-size:28px;color:#F0EEFF;margin:0 0 8px;">Booking <span style="color:#D4AF37;">Confirmed</span></h2>
    <p style="color:rgba(240,238,255,0.7);font-size:14px;line-height:1.6;">Hi {name}, your booking with <b>{artist_name}</b> on <b>{event_date}</b> is confirmed.</p>
    <p style="color:rgba(240,238,255,0.7);font-size:14px;">Booking Reference: <code style="color:#F1D17A;background:rgba(212,175,55,0.12);padding:3px 9px;border-radius:6px;">{booking_ref}</code></p>
    {timeline_html or ""}
  </td></tr>
</table></td></tr></table></body></html>"""
    text = f"Hi {name}, your booking with {artist_name} on {event_date} is confirmed. Reference: {booking_ref}"
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)


# ─── Event-day reminder ────────────────────────────────────────────────
def _reminder_html(name: str, role: str, artist_name: str, event_date: str,
                   event_time: str, load_in_time: str, venue: str, city: str,
                   map_link: str, booking_ref: str, timeline_html: str = "") -> str:
    intro = (
        f"Today's the day, {name or 'there'}! Your event with <b>{artist_name}</b> is happening this evening."
        if role == "customer"
        else f"Show time, {name or 'there'}! You're performing today. Here's the game plan."
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#F0EEFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
        <tr><td style="padding:32px 40px 12px;">
          <div style="display:inline-block;font-family:'Times New Roman',serif;font-size:24px;font-weight:700;color:#F0EEFF;">
            Book<span style="color:#D4AF37;">Talent</span>
          </div>
        </td></tr>
        <tr><td style="padding:0 40px;">
          <div style="height:1px;background:linear-gradient(to right,transparent,#D4AF37,transparent);"></div>
        </td></tr>
        <tr><td style="padding:28px 40px 8px;">
          <div style="font-family:'Times New Roman',serif;font-size:28px;font-weight:700;color:#F0EEFF;line-height:1.2;margin-bottom:10px;">
            Event <span style="color:#D4AF37;">today</span>
          </div>
          <p style="font-size:14px;color:rgba(240,238,255,0.7);line-height:1.65;margin:0 0 16px;">{intro}</p>
        </td></tr>
        <tr><td style="padding:8px 40px 8px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:16px 20px;">
            <tr>
              <td style="padding:6px 0;color:rgba(240,238,255,0.6);font-size:12px;letter-spacing:1px;">DATE</td>
              <td style="padding:6px 0;text-align:right;color:#F0EEFF;font-size:14px;font-weight:600;">{event_date}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:rgba(240,238,255,0.6);font-size:12px;letter-spacing:1px;">SHOW TIME</td>
              <td style="padding:6px 0;text-align:right;color:#D4AF37;font-size:18px;font-weight:700;">{event_time or 'TBC'}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:rgba(240,238,255,0.6);font-size:12px;letter-spacing:1px;">LOAD-IN BY</td>
              <td style="padding:6px 0;text-align:right;color:#F1D17A;font-size:15px;font-weight:600;">{load_in_time or 'TBC'}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:rgba(240,238,255,0.6);font-size:12px;letter-spacing:1px;">VENUE</td>
              <td style="padding:6px 0;text-align:right;color:#F0EEFF;font-size:13px;max-width:60%;">{venue}<br/><span style="color:rgba(240,238,255,0.55);font-size:12px;">{city}</span></td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:rgba(240,238,255,0.6);font-size:12px;letter-spacing:1px;">BOOKING</td>
              <td style="padding:6px 0;text-align:right;"><code style="color:#F1D17A;background:rgba(212,175,55,0.12);padding:3px 9px;border-radius:6px;font-size:12px;">{booking_ref}</code></td>
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:16px 40px 8px;" align="center">
          <a href="{map_link}" style="display:inline-block;background:linear-gradient(135deg,#D4AF37,#B8931F);color:#0F0F1B;text-decoration:none;font-weight:700;padding:12px 26px;border-radius:10px;font-size:14px;letter-spacing:0.4px;">Open in Google Maps →</a>
        </td></tr>
        <tr><td style="padding:16px 40px 8px;">
          <div style="background:rgba(109,40,217,0.08);border:1px solid rgba(109,40,217,0.25);border-radius:10px;padding:14px 16px;">
            <div style="font-size:11px;color:#B794F4;letter-spacing:1px;margin-bottom:4px;">TIP</div>
            <p style="font-size:13px;color:rgba(240,238,255,0.7);margin:0;line-height:1.55;">
              { 'Confirm sound-check timing with the artist and keep the venue contact handy.' if role == 'customer' else 'Reach the venue by load-in time, do a sound check, and confirm the run-of-show with the customer.' }
            </p>
          </div>
        </td></tr>
        <tr><td style="padding:8px 40px 0;">{timeline_html or ""}</td></tr>
        <tr><td style="padding:0 40px 28px;">
          <div style="height:1px;background:rgba(255,255,255,0.08);margin:20px 0 12px;"></div>
          <p style="font-size:11px;color:rgba(240,238,255,0.4);margin:0;text-align:center;">
            © 2026 BookTalent · India's Premium Talent Marketplace
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


async def send_event_reminder_email(to_email: str, name: str, role: str, artist_name: str,
                                     event_date: str, event_time: str, load_in_time: str,
                                     venue: str, city: str, map_link: str, booking_ref: str,
                                     timeline_html: str = "") -> dict:
    """Sent the morning of an event to both customer and artist."""
    if not to_email:
        return {"sent": False, "mock": True, "error": "no_email"}
    subject = f"Today at {event_time or ''} — your event with {artist_name}".strip()
    html = _reminder_html(name, role, artist_name, event_date, event_time,
                          load_in_time, venue, city, map_link, booking_ref, timeline_html)
    text = (
        f"Event reminder — {event_date}\n"
        f"Show time: {event_time}\nLoad-in: {load_in_time}\n"
        f"Venue: {venue}, {city}\nMap: {map_link}\n"
        f"Booking: {booking_ref}"
    )
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)


def _payment_receipt_html(name: str, refs: list, amount: float, txnid: str,
                          gateway: str, easepayid: str = "", artist_name: str = "",
                          event_date: str = "", timeline_html: str = "") -> str:
    ref_rows = "".join(
        f'<tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Booking</td>'
        f'<td style="padding:6px 0;text-align:right;"><code style="color:#F1D17A;background:rgba(212,175,55,0.12);padding:3px 9px;border-radius:6px;font-size:13px;">{r}</code></td></tr>'
        for r in refs
    )
    easepay_row = (
        f'<tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Gateway Ref</td>'
        f'<td style="padding:6px 0;text-align:right;font-family:monospace;font-size:12px;color:#F0EEFF;">{easepayid}</td></tr>'
        if easepayid else ""
    )
    artist_row = (
        f'<tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Artist</td>'
        f'<td style="padding:6px 0;text-align:right;color:#F0EEFF;font-size:13px;">{artist_name}</td></tr>'
        if artist_name else ""
    )
    event_row = (
        f'<tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Event Date</td>'
        f'<td style="padding:6px 0;text-align:right;color:#F0EEFF;font-size:13px;">{event_date}</td></tr>'
        if event_date else ""
    )
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#09090F;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#F0EEFF;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090F;padding:32px 0;"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#0F0F1B;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
  <tr><td style="padding:32px 40px 8px;">
    <div style="font-family:'Times New Roman',serif;font-size:22px;font-weight:700;color:#F0EEFF;">Book<span style="color:#D4AF37;">Talent</span></div>
  </td></tr>
  <tr><td style="padding:0 40px;"><div style="height:1px;background:linear-gradient(to right,transparent,#D4AF37,transparent);"></div></td></tr>
  <tr><td style="padding:24px 40px 8px;">
    <h1 style="font-family:'Times New Roman',serif;font-size:26px;color:#F0EEFF;margin:0 0 6px;">Payment <span style="color:#D4AF37;">Received</span></h1>
    <p style="color:rgba(240,238,255,0.65);font-size:14px;line-height:1.6;margin:0 0 8px;">Hi {name or 'there'}, we've received your booking token. The artist has 24 hours to accept — you'll get another email the moment they confirm.</p>
  </td></tr>
  <tr><td style="padding:8px 40px 24px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:16px 20px;">
      <tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Amount Paid</td>
          <td style="padding:6px 0;text-align:right;color:#D4AF37;font-size:20px;font-weight:700;">₹{amount:,.2f}</td></tr>
      <tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Transaction ID</td>
          <td style="padding:6px 0;text-align:right;font-family:monospace;font-size:12px;color:#F0EEFF;">{txnid}</td></tr>
      {easepay_row}
      <tr><td style="padding:6px 0;color:rgba(240,238,255,0.7);font-size:13px;">Payment Gateway</td>
          <td style="padding:6px 0;text-align:right;color:#F0EEFF;font-size:13px;">{gateway.title()}</td></tr>
      {artist_row}
      {event_row}
      {ref_rows}
    </table>
  </td></tr>
  <tr><td style="padding:0 40px 8px;">{timeline_html or ""}</td></tr>
  <tr><td style="padding:0 40px 32px;">
    <p style="color:rgba(240,238,255,0.5);font-size:12px;line-height:1.6;margin:0;">Keep this receipt for your records. Questions? Reply to this email and our concierge team will help.</p>
  </td></tr>
</table></td></tr></table></body></html>"""


async def send_payment_receipt_email(
    to_email: str, name: str, booking_refs: list, amount: float, txnid: str,
    gateway: str, easepayid: str = "", artist_name: str = "", event_date: str = "",
    timeline_html: str = "",
) -> dict:
    """Sent the instant a payment is verified. Includes txnid, gateway ref,
    amount and all booking references (single or batch)."""
    if not to_email:
        return {"sent": False, "mock": True, "error": "no_email"}
    subject = f"Payment received — ₹{amount:,.2f} · {txnid}"
    html = _payment_receipt_html(name, booking_refs, amount, txnid, gateway, easepayid, artist_name, event_date, timeline_html)
    text = f"Payment of ₹{amount:,.2f} received. Transaction: {txnid}. Bookings: {', '.join(booking_refs)}"
    return await asyncio.to_thread(_send_sync, to_email, subject, html, text)
