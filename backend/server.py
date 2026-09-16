"""
BookTalent — Production-grade Talent Marketplace API
FastAPI + MongoDB + JWT
"""
from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import asyncio
import uuid
import logging
import base64
import io
import hmac
import hashlib
import re
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Literal, Any, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict

from pdf_service import generate_contract_pdf, generate_invoice_pdf
from email_service import (
    is_email_enabled, generate_otp, send_otp_email, send_booking_confirmation_email,
    send_payment_receipt_email, send_password_reset_email, send_welcome_email,
    send_event_reminder_email,
)
from image_service import compress_image, make_thumbnail
from urllib.parse import quote_plus
import rate_limit
from admin_config_routes import make_router as make_admin_config_router
from agency_corp_provider_routes import make_router as make_agency_corp_router
from exports_search_routes import make_exports_search_router
from chat_routes import make_chat_router
from notification_service import dispatch as notify_dispatch
from routes import reviews as routes_reviews
from routes import coupons as routes_coupons
from routes import blogs as routes_blogs
from routes import disputes as routes_disputes
from routes import kyc as routes_kyc
from routes import uploads as routes_uploads
from routes import addons as routes_addons
from routes import subscriptions as routes_subscriptions
from routes import homepage as routes_homepage
from routes import concierge as routes_concierge
from routes import insights as routes_insights
from routes import city_aliases as routes_city_aliases
from routes import outstation_report as routes_outstation_report
from routes import cms_seo as routes_cms_seo
from routes import questionnaire as routes_questionnaire
from routes.easebuzz import make_easebuzz_router, set_refund_context, auto_refund_bookings

def _cat_req_slug(s: str) -> str:
    """Iter 66 — reused by /auth/register when saving category_request payload."""
    s = (s or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "custom"

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
PLATFORM_FEE_PCT = float(os.environ.get("PLATFORM_FEE_PCT", 5))
GST_PCT = float(os.environ.get("GST_PCT", 18))
TOKEN_PCT = float(os.environ.get("TOKEN_PCT", 5))

# Payment gateway = Easebuzz (only). Legacy Razorpay integration removed —
# all keys / URLs live in `payment_gateway_settings` collection.

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="BookTalent API")
api = APIRouter(prefix="/api")

# CORS hardening (Iter 87): default is a safe dev-only list. In production
# set CORS_ORIGINS to a comma-separated allowlist of your frontend origins.
# Using ["*"] with allow_credentials=True is unsafe AND a browser hard-rejects
# it, so an explicit allowlist is required for cookie/JWT auth flows.
_cors_raw = os.environ.get("CORS_ORIGINS", "").strip()
if _cors_raw and _cors_raw != "*":
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _cors_origin_regex = None
else:
    # Sensible fallback for local dev + preview environments.
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        # Iter 99.4 SEC-004 — canonical production origins pinned here so we
        # don't rely on a wildcard subdomain regex that could accidentally
        # trust a sibling *.preview.emergentagent.com attacker origin.
        "https://booktalent.in",
        "https://www.booktalent.in",
    ]
    # Preview subdomain only allowed if it is THIS exact app's preview host.
    # We infer it from BACKEND_PUBLIC_URL when set; otherwise no wildcard.
    _preview_host = (os.environ.get("BACKEND_PUBLIC_URL") or "").rstrip("/")
    if _preview_host and _preview_host.startswith("https://"):
        _cors_origins.append(_preview_host)
    _cors_origin_regex = None  # No wildcard regex in prod (SEC-004).

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booktalent")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def make_token(user_id: str, role: str, exp_hours: int = 24 * 7) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=exp_hours),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def clean(doc: Optional[dict]) -> Optional[dict]:
    """Remove _id and sensitive fields from a Mongo doc."""
    if not doc:
        return doc
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return doc


def new_id() -> str:
    return str(uuid.uuid4())


def booking_ref() -> str:
    return "BT-" + datetime.now().strftime("%y%m%d") + "-" + uuid.uuid4().hex[:6].upper()


# ─────────────────────────────────────────────────────────────────────────────
# Auth dependency
# ─────────────────────────────────────────────────────────────────────────────
async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"id": payload["sub"]})
    if not user:
        raise HTTPException(401, "User not found")
    return clean(user)


async def get_current_user_optional(authorization: str | None) -> dict | None:
    """Sprint 5 Smart Homepage — resolve caller if a valid token is present.

    Never raises — returns None for anonymous or invalid-token requests so that
    public endpoints can gracefully fall back to non-personalized output.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload["sub"]})
        return clean(user) if user else None
    except Exception:
        return None


# ─── httpOnly cookie helpers (defense-in-depth against XSS token theft) ──
# Setting the JWT as an httpOnly cookie prevents JavaScript from reading it,
# which shuts down the classic XSS-token-exfiltration path. The frontend
# still stores the same token in localStorage so WebSocket auth (which can't
# send headers) keeps working via the ?token= query param.
_COOKIE_NAME = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days — matches JWT expiry


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,      # HTTPS-only (both Emergent preview + user's VPS are HTTPS)
        samesite="lax",   # allows normal navigation, blocks cross-site CSRF
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/")


# ─── City alias canonicalisation (Iter 35) ─────────────────────────────
# Module-level cache — refreshed lazily on the first booking after startup so
# admin edits via /admin/settings/city_aliases don't require a redeploy.
_CITY_ALIAS_MAP: dict = {}


async def _refresh_city_aliases() -> None:
    global _CITY_ALIAS_MAP
    _CITY_ALIAS_MAP = await routes_city_aliases.load_alias_map(db)


def _outstation_check(artist_city: str | None, event_city: str | None, alias_map: dict) -> bool:
    """True when the two cities are DIFFERENT after alias canonicalisation."""
    if not artist_city or not event_city:
        return False
    a = routes_city_aliases.canonical_city(artist_city, alias_map)
    b = routes_city_aliases.canonical_city(event_city, alias_map)
    return a != b


async def require_role(roles: list[str]):
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(403, f"Requires role: {roles}")
        return user
    return _dep


async def admin_only(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


# ─── Iter 55 — RBAC helpers ────────────────────────────────────────────────
# Available admin permissions. A super_admin implicitly has all of them.
ADMIN_PERMISSIONS = [
    "admins.manage",       # Create/edit/delete other admins (super admin only)
    "users.view",
    "users.edit",
    "users.suspend",
    "users.delete",
    "artists.moderate",    # verify / feature / suspend artist profiles
    "bookings.view",
    "bookings.override",   # extend/force-accept/reject/refund bookings
    "payments.view",
    "payments.refund",
    "cms.manage",          # blogs, pages, CTAs
    "settings.manage",     # site settings, pricing rules
    "analytics.view",
    "notifications.send",
    "subscriptions.manage",
]

# Iter 56 — Presets are now DB-backed. This dict is the SEED that gets
# inserted into `admin_roles` on first boot; after that ops can create /
# edit / delete presets from the UI. `super_admin` is protected — always
# reset to the full permission list to prevent lockouts.
DEFAULT_ADMIN_ROLE_PRESETS = {
    "super_admin":    ADMIN_PERMISSIONS,
    "operations":     ["users.view", "users.edit", "artists.moderate", "bookings.view",
                       "bookings.override", "payments.view", "analytics.view"],
    "finance":        ["users.view", "bookings.view", "payments.view", "payments.refund",
                       "subscriptions.manage", "analytics.view"],
    "content":        ["users.view", "cms.manage", "notifications.send", "analytics.view"],
    "support":        ["users.view", "bookings.view", "artists.moderate", "notifications.send"],
    "viewer":         ["users.view", "bookings.view", "payments.view", "analytics.view"],
}


async def get_role_presets() -> Dict[str, List[str]]:
    """Load role → permissions map from Mongo. Falls back to the seed dict
    if the collection is empty (fresh install, migration in progress)."""
    docs = await db.admin_roles.find({}, {"_id": 0, "id": 1, "permissions": 1}).to_list(200)
    if not docs:
        return dict(DEFAULT_ADMIN_ROLE_PRESETS)
    return {d["id"]: d.get("permissions", []) for d in docs}


async def audit_log(actor: dict, action: str, target: Optional[dict] = None, meta: Optional[dict] = None) -> None:
    """Iter 56 — Write a single audit entry. Never raises."""
    try:
        entry = {
            "id": new_id(),
            "action": action,
            "actor_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "actor_role": actor.get("admin_role"),
            "target_id": (target or {}).get("id"),
            "target_email": (target or {}).get("email"),
            "target_role": (target or {}).get("admin_role"),
            "meta": meta or {},
            "created_at": utcnow(),
        }
        await db.admin_audit_log.insert_one(entry)
    except Exception:
        # Auditing failure must never break the underlying action.
        pass


def admin_has_permission(admin: dict, permission: str) -> bool:
    """Return True if the admin user has the given permission.
    Super admins (or admins without an explicit permission list — legacy seed)
    are treated as having all permissions."""
    if admin.get("admin_role") == "super_admin":
        return True
    perms = admin.get("admin_permissions")
    # Legacy admins created before RBAC have no admin_permissions field →
    # keep them full-access so we don't break existing installs.
    if perms is None:
        return True
    return permission in perms


def require_permission(permission: str):
    """Dependency factory: `admin: dict = Depends(require_permission('bookings.override'))`.
    Bakes the admin_only check in so route decorators stay one-liner."""
    async def _dep(admin: dict = Depends(admin_only)) -> dict:
        if not admin_has_permission(admin, permission):
            raise HTTPException(403, f"Missing permission: {permission}")
        return admin
    return _dep


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────
class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    first_name: str
    last_name: str = ""
    phone: str = ""
    # Iter 66 — Corporate role temporarily hidden from public signup. Kept in
    # the Literal so existing corporate users can still be created via the
    # admin panel + backfilled data. Public /auth/register rejects it below.
    role: Literal["customer", "artist", "agency", "corporate", "manager"]
    # artist-specific
    category: Optional[str] = None
    city: Optional[str] = None
    # Iter 66 — Optional payload for artists whose desired category isn't in
    # the master list yet. When present, we create a `category_requests` row
    # right after user creation and flag the artist profile as
    # category_pending=true.
    category_request: Optional[dict] = None
    # Iter 67 — Same idea for city: when the artist's city isn't in
    # cities_master yet, save a `city_requests` row for admin review.
    city_request: Optional[dict] = None
    # agency / corporate
    company_name: Optional[str] = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class OTPBody(BaseModel):
    phone: str
    otp: Optional[str] = None


class UpdateProfileBody(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    tagline: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    languages: Optional[List[str]] = None
    genres: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    travel_range: Optional[str] = None
    notice_period_days: Optional[int] = None
    experience_years: Optional[int] = None
    category: Optional[str] = None
    subcategories: Optional[List[str]] = None
    socials: Optional[Dict[str, str]] = None
    available_for_booking: Optional[bool] = None
    stage_name: Optional[str] = None
    bank: Optional[Dict[str, str]] = None
    # rich profile fields
    awards: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    faqs: Optional[List[Dict[str, str]]] = None  # [{q, a}]
    youtube_url: Optional[str] = None
    instagram_url: Optional[str] = None
    spotify_url: Optional[str] = None
    onboarding_completed: Optional[bool] = None
    onboarding_step: Optional[int] = None
    # customer specific
    company_name: Optional[str] = None


class PackageBody(BaseModel):
    name: str
    description: str = ""
    price: float
    duration: str = ""
    features: List[str] = []
    is_popular: bool = False
    # Sprint 4 — Travel & Accommodation requirements (borne by customer separately)
    travel_required: bool = False
    accommodation_required: bool = False
    hotel_category: Optional[str] = None            # e.g. "3-star", "4-star", "5-star"
    flight_class: Optional[str] = None              # e.g. "economy", "premium-economy", "business"
    team_size: Optional[int] = None                 # number of people to accommodate
    arrival_buffer_days: Optional[int] = None       # days needed before event
    local_transport_required: bool = False
    meals_required: bool = False
    travel_notes: str = ""                          # free-form additional rider notes


class MediaUploadBody(BaseModel):
    """Used for base64 uploads via JSON for convenience."""
    type: Literal[
        "profile", "cover", "gallery", "video", "reel",
        "audio", "document", "press_kit", "brand_deck", "clip",
        "kyc", "review",
    ]
    data_url: str  # data:image/...;base64,XXX
    title: Optional[str] = None
    is_featured: bool = False


class AvailabilityBody(BaseModel):
    date: str  # YYYY-MM-DD
    status: Literal["available", "blocked", "booked", "premium"]
    # For status == "premium" — a multiplier applied to the artist's base package
    # price on this date (e.g. 1.5 for weekend rate, 2.0 for festival dates).
    premium_multiplier: Optional[float] = None
    premium_label: Optional[str] = None  # e.g. "Weekend", "Diwali", "New Year"


class AddonSelection(BaseModel):
    addon_id: str
    quantity: int = 1


class BookingCreate(BaseModel):
    artist_id: str
    package_id: str
    addons: List[str] = []                       # legacy: hardcoded slugs (dhol/anchor/photo/extra-hour)
    addon_selections: List[AddonSelection] = []  # Sprint 3: artist-defined add-ons
    event_date: str
    event_time: str
    event_type: str
    # Iter 83 — Sec 20/21/22. New booking-form fields:
    #   event_type_other  → free-text when event_type == "Others"
    #   number_of_days    → multi-day bookings (default 1)
    #   venue_address     → full postal address (separate from venue name)
    event_type_other: Optional[str] = Field(None, max_length=200)
    number_of_days: int = Field(1, ge=1, le=30)
    venue_address: Optional[str] = Field(None, max_length=500)
    venue: str
    city: str
    guests: Optional[str] = None
    language_pref: Optional[str] = None
    notes: str = ""
    # Iter 36 — Customer-facing free-text field for outstation asks,
    # dietary requirements, green-room needs etc. Persisted to booking doc,
    # surfaced to artist + printed in the contract PDF.
    special_instructions: str = ""
    coupon_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    # Iter 44 — Multi-Artist Event support. If provided, the new booking is
    # attached to an existing event umbrella so a single "Booking Recap" page
    # can render every artist the customer hired for that event. Ownership is
    # enforced: the event_id must belong to another booking of the same user.
    event_id: Optional[str] = None
    # Iter 52.5 — Optional travel allowance the customer commits to pay the
    # artist direct-to-artist. Snapshotted to booking + contract PDF. The
    # platform never handles this money — it exists for auditability only.
    customer_travel_allowance: Optional[float] = 0
    # Iter 52.5 — Terms & Conditions declaration checkbox from the Review step.
    # We reject the booking if this is False so the acceptance is captured
    # in-flow (audit trail).
    tnc_accepted: bool = False


class BookingStatusUpdate(BaseModel):
    # Counter-offer flow removed — BookTalent enforces a fixed-pricing
    # lead-generation model. Artists can only accept or reject.
    action: Literal["accept", "reject", "start", "complete", "approve_completion", "cancel"]
    reason: Optional[str] = None


class PaymentInitBody(BaseModel):
    booking_id: str
    method: Literal["card", "upi", "netbanking"]


class PaymentVerifyBody(BaseModel):
    booking_id: str
    payment_id: str
    # mock-mode fields
    mock_otp: Optional[str] = "123456"


class ReviewBody(BaseModel):
    booking_id: str
    rating: int = Field(ge=1, le=5)
    text: str
    photos: List[str] = []  # data urls — images
    videos: List[str] = []  # data urls — short clips (≤ 30 MB)


class ReviewReplyBody(BaseModel):
    reply: str


class ReviewModerateBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason: Optional[str] = None


class MessageBody(BaseModel):
    to_user_id: str
    text: str
    booking_id: Optional[str] = None


class CouponBody(BaseModel):
    code: str
    description: str = ""
    discount_type: Literal["percent", "flat"]
    discount_value: float
    max_uses: int = 1000
    per_user_limit: int = 1
    expires_at: str  # YYYY-MM-DD
    min_order: float = 0
    applies_to: str = "all"  # all/wedding/corporate/category-slug
    active: bool = True


class BlogBody(BaseModel):
    title: str
    slug: str
    content: str
    cover_image: Optional[str] = None
    excerpt: str = ""
    tags: List[str] = []
    published: bool = True


class NotificationBody(BaseModel):
    user_id: str
    type: str
    title: str
    body: str


class BoostBody(BaseModel):
    plan: Literal["starter", "pro", "elite"]


class KYCSubmitBody(BaseModel):
    aadhaar_number: Optional[str] = None       # raw 12-digit Aadhaar number
    pan_number: Optional[str] = None           # raw PAN like ABCDE1234F
    full_name: Optional[str] = None
    dob: Optional[str] = None                  # YYYY-MM-DD
    aadhaar: Optional[str] = None              # data url — Aadhaar doc image/pdf
    pan: Optional[str] = None                  # data url — PAN doc image/pdf
    bank_proof: Optional[str] = None           # data url — cancelled cheque / passbook
    selfie: Optional[str] = None               # data url — live selfie for face-match


class KYCDecideBody(BaseModel):
    artist_id: str
    decision: Literal["approve", "reject", "request_resubmission"]
    reason: Optional[str] = None


class DisputeBody(BaseModel):
    booking_id: str
    reason: str
    description: str = ""


class DisputeResolveBody(BaseModel):
    decision: Literal["refund", "release", "partial"]
    amount: Optional[float] = None
    note: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────
@api.post("/auth/register")
async def register(body: RegisterBody, response: Response):
    email = body.email.lower()
    # Iter 66 — Corporate signup is hidden from the public site while we
    # decide what makes that role distinct from the Normal Customer flow.
    # Existing Corporate users keep working; admins can still create new
    # ones from the admin panel via /admin/users. Public signup only
    # accepts the three consumer-facing roles.
    if body.role == "corporate":
        raise HTTPException(400, "Corporate signup is not currently available. Please register as a Customer.")

    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    # Require prior email verification via /api/auth/email/verify
    email_otp = await db.email_otps.find_one({"email": email})
    if not email_otp or not email_otp.get("verified"):
        raise HTTPException(400, "Please verify your email first")
    # Consume the OTP record so the same verified token can't be reused later
    await db.email_otps.delete_one({"email": email})

    uid = new_id()
    now = utcnow()
    user_doc = {
        "id": uid,
        "email": email,
        "password_hash": hash_password(body.password),
        "first_name": body.first_name,
        "last_name": body.last_name,
        "phone": body.phone,
        "role": body.role,
        "kyc_status": "unverified",
        "verified": True,
        "email_verified": True,
        "created_at": now,
        "updated_at": now,
        "company_name": body.company_name,
    }
    await db.users.insert_one(user_doc)

    # Create role-specific profile
    if body.role == "artist":
        # Iter 66 — When the artist typed a category that isn't in the master
        # list, use their requested name as the placeholder and mark the
        # profile as pending admin approval so search UI can hide it until
        # admin decides.
        cat_req = body.category_request if isinstance(body.category_request, dict) else None
        placeholder_category = (cat_req.get("name") if cat_req else body.category) or "Vocalist"
        category_pending = bool(cat_req and cat_req.get("name"))
        pending_req_id = new_id() if category_pending else None

        # Iter 67 — Same for city: use requested city as placeholder if
        # provided.
        city_req = body.city_request if isinstance(body.city_request, dict) else None
        placeholder_city = (city_req.get("name") if city_req else body.city) or ""
        city_pending = bool(city_req and city_req.get("name"))
        pending_city_req_id = new_id() if city_pending else None

        await db.artist_profiles.insert_one({
            "id": new_id(),
            "user_id": uid,
            "stage_name": f"{body.first_name} {body.last_name}".strip(),
            "category": placeholder_category,
            "subcategories": [],
            "city": placeholder_city,
            "state": "",
            "country": "India",
            "bio": "",
            "tagline": "",
            "languages": [],
            "genres": [],
            "event_types": [],
            "travel_range": "Pan India",
            "experience_years": 0,
            "notice_period_days": 7,
            "available_for_booking": True,
            "profile_image": None,
            "cover_image": None,
            "socials": {},
            "rating_avg": 0,
            "review_count": 0,
            "events_done": 0,
            "followers": 0,
            "profile_views": 0,
            "is_featured": False,
            "is_boosted": False,
            "boost_expires": None,
            "kyc_status": "unverified",
            "category_pending": category_pending,
            "pending_category_id": pending_req_id,
            "pending_category_name": placeholder_category if category_pending else None,
            "city_pending": city_pending,
            "pending_city_id": pending_city_req_id,
            "pending_city_name": placeholder_city if city_pending else None,
            "created_at": now,
            "updated_at": now,
        })
        # Save the request row + notify admins so nothing is lost per spec.
        if category_pending:
            req_doc = {
                "id": pending_req_id,
                "artist_id": uid,
                "artist_name": f"{body.first_name} {body.last_name}".strip() or email,
                "artist_email": email,
                "stage_name": f"{body.first_name} {body.last_name}".strip(),
                "city": placeholder_city or (body.city or ""),
                "requested_name": (cat_req.get("name") or "").strip(),
                "requested_slug": _cat_req_slug(cat_req.get("name") or ""),
                "description": (cat_req.get("description") or "").strip(),
                "example_artists": (cat_req.get("example_artists") or "").strip(),
                "portfolio_link": (cat_req.get("portfolio_link") or "").strip(),
                "status": "pending",
                "created_at": now,
            }
            await db.category_requests.insert_one(req_doc)
            try:
                async for adm in db.users.find({"role": "admin"}, {"_id": 0, "id": 1}):
                    await db.notifications.insert_one({
                        "id": new_id(), "user_id": adm["id"],
                        "type": "category.request",
                        "title": "New Artist Category request",
                        "body": f"{req_doc['artist_name']} requested '{req_doc['requested_name']}' at signup.",
                        "link": f"/admin?tab=category-requests&highlight={pending_req_id}",
                        "read": False, "created_at": now,
                    })
            except Exception:
                pass

        # Iter 67 — City request row (mirror of category).
        if city_pending:
            city_doc = {
                "id": pending_city_req_id,
                "artist_id": uid,
                "artist_name": f"{body.first_name} {body.last_name}".strip() or email,
                "artist_email": email,
                "stage_name": f"{body.first_name} {body.last_name}".strip(),
                "category": placeholder_category,
                "requested_name": (city_req.get("name") or "").strip(),
                "requested_slug": _cat_req_slug(city_req.get("name") or ""),
                "state": (city_req.get("state") or "").strip(),
                "country": (city_req.get("country") or "India").strip(),
                "description": (city_req.get("description") or "").strip(),
                "reason": (city_req.get("reason") or "").strip(),
                "status": "pending",
                "created_at": now,
            }
            await db.city_requests.insert_one(city_doc)
            try:
                async for adm in db.users.find({"role": "admin"}, {"_id": 0, "id": 1}):
                    await db.notifications.insert_one({
                        "id": new_id(), "user_id": adm["id"],
                        "type": "city.request",
                        "title": "New Artist City request",
                        "body": f"{city_doc['artist_name']} requested '{city_doc['requested_name']}' at signup.",
                        "link": f"/admin?tab=city-requests&highlight={pending_city_req_id}",
                        "read": False, "created_at": now,
                    })
            except Exception:
                pass
    elif body.role == "agency":
        await db.agencies.insert_one({
            "id": new_id(),
            "user_id": uid,
            "name": body.company_name or f"{body.first_name} Agency",
            "city": body.city or "",
            "created_at": now,
        })

    token = make_token(uid, body.role)
    user_doc.pop("password_hash", None)
    user_doc.pop("_id", None)
    _set_auth_cookie(response, token)

    # Iter 78 — fire welcome email in the background so we never block the
    # signup response on SMTP latency. Failures are logged inside the helper.
    frontend_url = os.environ.get("FRONTEND_URL", "").strip()
    asyncio.create_task(send_welcome_email(email, body.first_name or "", body.role, frontend_url))

    return {"token": token, "user": user_doc}


@api.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    email = body.email.lower()
    # Iter 78 — per-IP + per-email rate limits: 10 attempts per 15 min per IP,
    # 5 per 15 min per targeted email. Blocks scripted credential-stuffing.
    rate_limit.check(request, "login_ip", limit=10, window_seconds=900,
                     error_msg="Too many login attempts — please wait a few minutes.")
    rate_limit.check(request, "login_email", limit=5, window_seconds=900, key_extra=email,
                     error_msg="Too many login attempts for this account — please wait a few minutes.")
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email or password")
    # Successful login → wipe both counters so the user isn't punished on
    # their next legitimate attempt.
    ip = rate_limit.ip_of(request)
    rate_limit.reset("login_ip", ip)
    rate_limit.reset("login_email", ip, email)
    token = make_token(user["id"], user["role"])
    _set_auth_cookie(response, token)
    return {"token": token, "user": clean(user)}


@api.post("/auth/logout")
async def logout(response: Response):
    """Clear the httpOnly auth cookie. The frontend must also clear localStorage."""
    _clear_auth_cookie(response)
    return {"ok": True}


@api.get("/auth/config")
async def auth_config():
    """Public config — frontend uses this to know whether to show 'test OTP' hint."""
    return {
        "email_provider_enabled": is_email_enabled(),
    }


@api.post("/auth/otp/send")
async def otp_send(body: OTPBody):
    # Iter 77 — Phone-based OTP is deprecated. We do not have an SMS gateway
    # wired in, and email-based OTP now handles signup verification. This
    # endpoint used to hard-code the OTP to `123456`, which was a
    # passwordless-login backdoor. It is now disabled.
    raise HTTPException(410, "Phone OTP is disabled — please verify via email instead")


@api.post("/auth/otp/verify")
async def otp_verify(body: OTPBody):
    # Iter 77 — see /auth/otp/send. Disabled to close the mock-OTP backdoor.
    raise HTTPException(410, "Phone OTP is disabled — please verify via email instead")


# ─── Email verification ────────────────────────────────────────────────
class EmailOTPSendBody(BaseModel):
    email: EmailStr
    name: Optional[str] = ""


class EmailOTPVerifyBody(BaseModel):
    email: EmailStr
    otp: str


@api.post("/auth/email/send")
async def email_otp_send(body: EmailOTPSendBody, request: Request):
    email = body.email.lower()

    # Iter 78 — per-IP throttle to protect our Gmail quota. Emails already
    # have a 60-sec per-address cooldown below; this stops a single IP from
    # hammering signups for many addresses.
    rate_limit.check(request, "email_send_ip", limit=8, window_seconds=600,
                     error_msg="Too many verification requests — please wait a few minutes.")

    # 60-second cooldown
    existing = await db.email_otps.find_one({"email": email})
    if existing:
        try:
            sent_at = datetime.fromisoformat(existing.get("sent_at", utcnow()))
        except Exception:
            sent_at = datetime.now(timezone.utc)
        if (datetime.now(timezone.utc) - sent_at) < timedelta(seconds=60):
            raise HTTPException(429, "Please wait 60 seconds before requesting a new code")

    otp = generate_otp()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    name = body.name or ""
    # If a user already exists, prefer their stored name
    u = await db.users.find_one({"email": email})
    if u and not name:
        name = (u.get("first_name") or "").strip()

    await db.email_otps.update_one(
        {"email": email},
        {"$set": {
            "email": email, "otp": otp,
            "sent_at": utcnow(), "expires_at": expires,
            "verified": False, "attempts": (existing.get("attempts", 0) + 1) if existing else 1,
        }},
        upsert=True,
    )
    result = await send_otp_email(email, otp, name)
    return {
        "sent": result.get("sent", False),
        "mock": result.get("mock", False),
        # Iter 77 — never leak the OTP to the caller (removes the previous
        # `123456` / mock-mode backdoor). The OTP only reaches the user's inbox.
        "test_otp": None,
    }


@api.post("/auth/email/verify")
async def email_otp_verify(body: EmailOTPVerifyBody):
    email = body.email.lower()
    rec = await db.email_otps.find_one({"email": email})
    if not rec:
        raise HTTPException(400, "No verification code requested for this email")
    # Expiry check
    try:
        expires = datetime.fromisoformat(rec.get("expires_at", utcnow()))
    except Exception:
        expires = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(400, "Code expired — please request a new one")
    # Iter 77 — track wrong-code attempts. After 5 misses, invalidate the OTP
    # so the caller must request a fresh code (brute-force protection).
    verify_attempts = int(rec.get("verify_attempts", 0))
    if verify_attempts >= 5:
        await db.email_otps.delete_one({"email": email})
        raise HTTPException(400, "Too many wrong attempts — please request a new code")
    if str(rec.get("otp")) != str(body.otp).strip():
        await db.email_otps.update_one(
            {"email": email}, {"$inc": {"verify_attempts": 1}},
        )
        raise HTTPException(400, "Invalid code")

    await db.email_otps.update_one(
        {"email": email}, {"$set": {"verified": True, "verified_at": utcnow()}},
    )
    # Iter 71 — SEC-001 hardening. This endpoint used to issue a full
    # session token (and set the auth cookie) whenever the email matched
    # an existing user. That was a passwordless-account-takeover: because
    # the mock OTP is `123456` in dev mode (and real OTPs can be captured),
    # anyone could log in as ANY user (including admin) without ever
    # supplying a password.
    #
    # Fix: this endpoint now ONLY marks the email address as verified. It
    # never issues a session. If the email already belongs to a registered
    # user, the caller must go through /auth/login with their password.
    # The subsequent /auth/register call will reject re-registration with
    # a "Email already registered" 400 — the correct behaviour.
    return {"verified": True, "token": None}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    # enrich with profile
    if user["role"] == "artist":
        prof = await db.artist_profiles.find_one({"user_id": user["id"]})
        user["artist_profile"] = clean(prof) if prof else None
    return user


@api.post("/auth/forgot-password")
async def forgot_password(body: dict, request: Request):
    """Iter 77 — Send both a reset LINK (magic token) and a 6-digit OTP via
    Gmail SMTP. The caller can complete the reset with either. We always
    return ``{sent: True}`` so an attacker can't enumerate registered
    addresses.
    """
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")

    # Iter 78 — 5 requests / 15 min per IP, 3 requests / hour per targeted
    # email. Prevents reset-email spam of a single address (which also
    # protects our Gmail sending quota).
    rate_limit.check(request, "forgot_ip", limit=5, window_seconds=900,
                     error_msg="Too many reset requests — please wait a few minutes.")
    rate_limit.check(request, "forgot_email", limit=3, window_seconds=3600, key_extra=email,
                     error_msg="Too many reset requests for this account — please wait an hour.")

    u = await db.users.find_one({"email": email})
    if u:
        token = new_id()
        otp = generate_otp()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        # Fresh row per request — this invalidates any older pending resets.
        await db.password_resets.delete_many({"user_id": u["id"], "used": False})
        await db.password_resets.insert_one({
            "id": token,
            "user_id": u["id"],
            "email": email,
            "otp": otp,
            "expires_at": expires,
            "used": False,
            "verify_attempts": 0,
            "created_at": utcnow(),
        })
        frontend_url = os.environ.get("FRONTEND_URL", "").strip().rstrip("/") or ""
        reset_link = f"{frontend_url}/reset-password?token={token}&email={email}"
        name = (u.get("first_name") or "").strip()
        result = await send_password_reset_email(email, name, otp, reset_link)
        log.info("Password reset email sent=%s to=%s", result.get("sent"), email)
    return {"sent": True}  # never reveal whether email exists


class ResetPasswordBody(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=6)
    otp: Optional[str] = None
    token: Optional[str] = None


@api.post("/auth/reset-password")
async def reset_password(body: ResetPasswordBody):
    """Iter 77 — Consume either an OTP or a token from ``/auth/forgot-password``
    and set a new password. Both paths require the code/token to be
    non-expired and not previously consumed. On success the record is
    marked ``used`` so it can't be replayed.
    """
    email = body.email.lower()
    if not body.otp and not body.token:
        raise HTTPException(400, "Provide either the emailed code or the reset link token")

    u = await db.users.find_one({"email": email})
    if not u:
        # generic 400 so we don't leak which addresses exist
        raise HTTPException(400, "Invalid or expired reset code")

    query = {"user_id": u["id"], "used": False}
    if body.token:
        query["id"] = body.token
    rec = await db.password_resets.find_one(query, sort=[("created_at", -1)])
    if not rec:
        raise HTTPException(400, "Invalid or expired reset code")

    try:
        expires = datetime.fromisoformat(rec.get("expires_at", utcnow()))
    except Exception:
        expires = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(400, "Reset code expired — please request a new one")

    # OTP path — check code with brute-force limit
    if body.otp and not body.token:
        if int(rec.get("verify_attempts", 0)) >= 5:
            await db.password_resets.update_one({"id": rec["id"]}, {"$set": {"used": True}})
            raise HTTPException(400, "Too many wrong attempts — please request a new code")
        if str(rec.get("otp", "")) != str(body.otp).strip():
            await db.password_resets.update_one(
                {"id": rec["id"]}, {"$inc": {"verify_attempts": 1}},
            )
            raise HTTPException(400, "Invalid reset code")

    # Update password + mark reset consumed
    await db.users.update_one(
        {"id": u["id"]},
        {"$set": {"password_hash": hash_password(body.new_password), "updated_at": utcnow()}},
    )
    await db.password_resets.update_one({"id": rec["id"]}, {"$set": {"used": True, "used_at": utcnow()}})
    log.info("Password reset for user_id=%s email=%s", u["id"], email)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# USER / PROFILE
# ─────────────────────────────────────────────────────────────────────────────
@api.put("/users/me")
async def update_me(body: UpdateProfileBody, user: dict = Depends(get_current_user)):
    update_user = {}
    update_artist = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None:
            continue
        if k in ("first_name", "last_name", "phone", "company_name"):
            update_user[k] = v
        else:
            update_artist[k] = v
    if update_user:
        update_user["updated_at"] = utcnow()
        await db.users.update_one({"id": user["id"]}, {"$set": update_user})
    if update_artist and user["role"] == "artist":
        update_artist["updated_at"] = utcnow()
        await db.artist_profiles.update_one({"user_id": user["id"]}, {"$set": update_artist})
        # Keep the SEO slug in sync when stage_name/category/city changes
        if any(k in update_artist for k in ("stage_name", "category", "city")):
            from routes.cms_seo import artist_slug as _mk_slug
            prof = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
            if prof.get("stage_name"):
                await db.artist_profiles.update_one(
                    {"user_id": user["id"]},
                    {"$set": {"slug": _mk_slug(prof)}},
                )
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# ARTIST ONBOARDING
# ─────────────────────────────────────────────────────────────────────────────
class OnboardingStepBody(BaseModel):
    step: int  # 1..5
    completed: Optional[bool] = False


@api.get("/onboarding/me")
async def get_onboarding_status(user: dict = Depends(get_current_user)):
    if user["role"] != "artist":
        return {"required": False, "completed": True}
    profile = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
    media_count = await db.media.count_documents({"user_id": user["id"], "type": {"$in": ["profile", "cover", "gallery"]}})
    pkg_count = await db.packages.count_documents({"artist_id": user["id"]})
    avail_count = await db.availability.count_documents({"user_id": user["id"]})

    checks = {
        "step1_basic": bool(profile.get("stage_name") and profile.get("category") and profile.get("city")),
        "step2_branding": bool(profile.get("bio") and (profile.get("languages") or [])),
        "step3_media": media_count > 0,
        "step4_packages": pkg_count > 0,
        "step5_availability": avail_count > 0,
    }
    done = all(checks.values()) or profile.get("onboarding_completed", False)
    next_step = next((i + 1 for i, k in enumerate(checks.keys()) if not checks[k]), 6)
    return {
        "required": True,
        "completed": done,
        "next_step": next_step,
        "checks": checks,
        "current_step": profile.get("onboarding_step", next_step),
    }


@api.post("/onboarding/complete")
async def complete_onboarding(user: dict = Depends(get_current_user)):
    if user["role"] != "artist":
        raise HTTPException(403, "Artists only")
    await db.artist_profiles.update_one(
        {"user_id": user["id"]},
        {"$set": {"onboarding_completed": True, "onboarding_completed_at": utcnow()}},
    )
    # Iter 91 — Completing onboarding also implicitly marks the welcome
    # modal as seen (so it never auto-opens again).
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"seen_welcome_at": utcnow()}},
    )
    return {"ok": True}


# Iter 91 — Dismiss the welcome/onboarding modal without completing it.
# Used by the wizard's "×" close button so the modal doesn't auto-open
# on every login for artists who chose to explore the dashboard first.
@api.post("/user/mark-welcome-seen")
async def mark_welcome_seen(user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"seen_welcome_at": utcnow()}},
    )
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA — base64 stored in GridFS-like collection
# ─────────────────────────────────────────────────────────────────────────────
@api.post("/media/upload")
async def media_upload(body: MediaUploadBody, user: dict = Depends(get_current_user)):
    # Iter 76.8 — Enforce the subscription plan's `max_media` limit.
    # Applies to the artist gallery only — profile/cover images are
    # infrastructure assets, not gallery items. Elite (500) is effectively
    # "unlimited" for realistic use.
    if user.get("role") == "artist" and (body.type or "gallery") == "gallery":
        try:
            from routes.subscriptions import resolve_plan
            plan = await resolve_plan(db, user["id"])
            limit = int(plan.get("max_media") or 6)
            current = await db.media.count_documents({
                "user_id": user["id"], "type": "gallery",
                "deleted": {"$ne": True},
            })
            if current >= limit:
                raise HTTPException(
                    402,
                    f"Your {plan.get('name','Free')} plan allows up to {limit} gallery uploads "
                    f"(you have {current}). Upgrade your plan or remove an existing item to add more.",
                )
        except HTTPException:
            raise
        except Exception as _e:
            log.warning("Plan-gate check for media failed: %s", _e)
    # parse data url
    if not body.data_url.startswith("data:"):
        raise HTTPException(400, "Invalid data URL")
    try:
        header, b64 = body.data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "") or "application/octet-stream"
        raw = base64.b64decode(b64)
    except Exception as e:
        raise HTTPException(400, f"Could not decode file: {e}")
    MAX_BINARY = 12 * 1024 * 1024
    if len(raw) > MAX_BINARY:
        raise HTTPException(413, f"File too large for local storage (max {MAX_BINARY // (1024*1024)} MB binary). Please use a smaller file or host externally.")

    original_size = len(raw)
    thumb_b64 = None
    video_stats: dict = {}
    if mime.startswith("image/"):
        # Compress original (reduces JPEG to ~30% of original on average)
        try:
            raw, mime = compress_image(raw, mime)
        except Exception as _e:
            log.warning("compress_image failed: %s", _e)
        # Generate thumbnail (square 400x400)
        try:
            tbytes, _tmime = make_thumbnail(raw, mime)
            if tbytes:
                thumb_b64 = base64.b64encode(tbytes).decode()
        except Exception as _e:
            log.warning("make_thumbnail failed: %s", _e)
    elif mime.startswith("video/"):
        # Iter 50 — FFmpeg pipeline. Re-encodes to 720p H.264 CRF 28 when the
        # file is >2 MB, keeping perceptual quality but shedding 30-70% size.
        try:
            from video_compression import compress_video_bytes  # noqa: WPS433
            raw, video_stats = await compress_video_bytes(raw=raw)
        except Exception as _e:
            log.warning("compress_video_bytes failed: %s", _e)

    final_b64 = base64.b64encode(raw).decode()
    mid = new_id()
    doc = {
        "id": mid,
        "user_id": user["id"],
        "type": body.type,
        "mime": mime,
        "size": len(raw),
        "original_size": original_size,
        "title": body.title,
        "is_featured": body.is_featured,
        "data": final_b64,  # compressed base64
        "thumb": thumb_b64,  # 400x400 base64 jpeg (None for non-images)
        "order": 0,
        "created_at": utcnow(),
        **({f"video_{k}": v for k, v in video_stats.items()} if video_stats else {}),
    }
    await db.media.insert_one(doc)

    # Convenience: if profile/cover, set on artist profile and remove the previous one
    if user["role"] == "artist" and body.type in ("profile", "cover"):
        key = "profile_image" if body.type == "profile" else "cover_image"
        existing = await db.artist_profiles.find_one({"user_id": user["id"]})
        old_id = (existing or {}).get(key)
        if old_id and old_id != mid:
            await db.media.delete_one({"id": old_id})
        await db.artist_profiles.update_one(
            {"user_id": user["id"]},
            {"$set": {key: mid, "updated_at": utcnow()}},
        )

    # never return the raw data field
    doc.pop("data", None)
    doc.pop("thumb", None)
    doc.pop("_id", None)
    return doc


@api.get("/media/{media_id}/thumb")
async def media_thumb(media_id: str, request: Request):
    doc = await db.media.find_one({"id": media_id})
    if not doc:
        raise HTTPException(404, "Not found")
    # SEC-001 — private-type thumbs (KYC/review) require auth too, because
    # some doc thumbnails visibly reveal the underlying document.
    await _authorize_media_access(doc, request)
    # New filesystem-stored media (Sprint 2 chunked uploads) — serve the JPEG thumb from disk
    if doc.get("storage") == "filesystem" and doc.get("thumb_path"):
        from pathlib import Path as _P
        tp = _P(doc["thumb_path"])
        if tp.exists():
            return FileResponse(tp, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=300"})
    # Legacy base64-in-Mongo media path
    if doc.get("thumb"):
        raw = base64.b64decode(doc["thumb"])
        return StreamingResponse(io.BytesIO(raw), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=300"})
    # Fall back to original (non-image types still go through here)
    raw = base64.b64decode(doc.get("data", ""))
    return StreamingResponse(io.BytesIO(raw), media_type=doc.get("mime", "application/octet-stream"))


@api.put("/media/{media_id}")
async def media_replace(media_id: str, body: MediaUploadBody, user: dict = Depends(get_current_user)):
    """Replace an existing media item's binary while preserving its id + order + featured flag."""
    existing = await db.media.find_one({"id": media_id})
    if not existing:
        raise HTTPException(404, "Not found")
    if existing["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Forbidden")

    if not body.data_url.startswith("data:"):
        raise HTTPException(400, "Invalid data URL")
    try:
        header, b64 = body.data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "") or "application/octet-stream"
        raw = base64.b64decode(b64)
    except Exception as e:
        raise HTTPException(400, f"Could not decode file: {e}")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 12 MB binary).")

    original_size = len(raw)
    thumb_b64 = None
    if mime.startswith("image/"):
        try:
            raw, mime = compress_image(raw, mime)
        except Exception:
            pass
        try:
            tbytes, _ = make_thumbnail(raw, mime)
            if tbytes:
                thumb_b64 = base64.b64encode(tbytes).decode()
        except Exception:
            pass

    await db.media.update_one(
        {"id": media_id},
        {"$set": {
            "mime": mime,
            "size": len(raw),
            "original_size": original_size,
            "data": base64.b64encode(raw).decode(),
            "thumb": thumb_b64,
            "title": body.title or existing.get("title"),
            "updated_at": utcnow(),
        }},
    )
    # If profile/cover, bump the profile updated_at for cache busting
    if user["role"] == "artist" and existing.get("type") in ("profile", "cover"):
        await db.artist_profiles.update_one(
            {"user_id": user["id"]}, {"$set": {"updated_at": utcnow()}},
        )
    return {"ok": True, "id": media_id, "size": len(raw)}


# Iter 99.3 SEC-001 — Media types that MUST require auth + ownership/admin.
# Portfolio-type media (profile, cover, gallery, video, reel) remain public
# because they render on public artist pages. Sensitive docs are gated below.
_PRIVATE_MEDIA_TYPES = {"kyc", "review", "contract", "agreement", "chat"}


def _has_kyc_admin_perm(user: dict) -> bool:
    """True if user is admin/subadmin with KYC visibility permission."""
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    # Sub-admins may store perms under any of these keys (historical drift).
    perms = (
        user.get("perms")
        or user.get("permissions")
        or user.get("admin_permissions")
        or []
    )
    return "kyc.manage" in perms or "kyc.view" in perms


async def _is_chat_participant(doc: dict, caller: dict) -> bool:
    """True when caller either owns the chat media, is the booking's
    customer/artist/assigned-manager, or is the other side of the chat
    thread that carries this attachment."""
    if not caller:
        return False
    if doc.get("user_id") == caller.get("id"):
        return True
    # Look up an owning thread / booking to authorize the counterparty.
    thread = None
    if doc.get("thread_id"):
        thread = await db.chat_v2_threads.find_one({"id": doc["thread_id"]})
    if not thread and doc.get("booking_id"):
        thread = await db.chat_v2_threads.find_one({"booking_id": doc["booking_id"]})
    if thread:
        allowed_ids = {
            thread.get("customer_id"), thread.get("artist_id"), thread.get("manager_id")
        }
        if caller.get("id") in allowed_ids:
            return True
    if doc.get("booking_id"):
        bk = await db.bookings.find_one({"id": doc["booking_id"]},
                                         {"_id": 0, "customer_id": 1, "artist_id": 1, "manager_id": 1}) or {}
        if caller.get("id") in {bk.get("customer_id"), bk.get("artist_id"), bk.get("manager_id")}:
            return True
    return False


async def _authorize_media_access(doc: dict, request: Request) -> None:
    """Raise 401/403 unless media is public OR caller is owner OR caller is
    an admin with KYC perms. Called from /media/{id} and /media/{id}/thumb."""
    mtype = (doc.get("type") or "").lower()
    if mtype not in _PRIVATE_MEDIA_TYPES:
        return  # public portfolio asset
    # Extract bearer token from Authorization header (JSON API) — same logic
    # as get_current_user but without raising for missing header up-front so
    # we can differentiate 401 vs 403.
    auth = request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Authentication required for this asset.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        caller = await db.users.find_one({"id": payload.get("sub")})
    except Exception:
        raise HTTPException(401, "Invalid or expired token.")
    if not caller:
        raise HTTPException(401, "Invalid session.")
    if doc.get("user_id") == caller.get("id"):
        return
    # Chat attachments: allow booking participants (customer, artist, manager).
    if mtype == "chat" and await _is_chat_participant(doc, caller):
        return
    if _has_kyc_admin_perm(caller):
        return
    raise HTTPException(403, "You do not have permission to view this asset.")


@api.get("/media/{media_id}")
async def media_get(media_id: str, request: Request):
    doc = await db.media.find_one({"id": media_id})
    if not doc:
        raise HTTPException(404, "Not found")
    await _authorize_media_access(doc, request)
    # Iter 76 — When the media was stored in Emergent Object Storage
    # (large videos), fetch its bytes from there instead of decoding a
    # base64 blob in Mongo. Small photos & legacy rows keep the base64
    # path untouched.
    if doc.get("storage_path"):
        try:
            from storage import get_object  # local import to keep cold-path fast
            raw, ct = get_object(doc["storage_path"])
            return StreamingResponse(io.BytesIO(raw), media_type=ct or doc.get("mime", "application/octet-stream"))
        except Exception as _e:
            log.error("Object-storage fetch failed for %s: %s", media_id, _e)
            raise HTTPException(502, "Media temporarily unavailable, please retry.")
    raw = base64.b64decode(doc["data"])
    return StreamingResponse(io.BytesIO(raw), media_type=doc.get("mime", "application/octet-stream"))


# ─── Iter 76 — Chunked large-video upload ────────────────────────────────
#
# Photos (< 12 MB) continue to POST /media/upload as base64 data URLs.
# Videos up to 1 GB use this 3-step chunked flow so we bypass the
# Kubernetes ingress body-size limits AND avoid holding the whole file
# in the app process's memory:
#
#   1. POST /media/video/start   → creates a session, returns session_id.
#   2. POST /media/video/chunk   → append a 5 MB slice by index.
#   3. POST /media/video/finish  → assemble → upload to Object Storage
#                                   → insert media doc → return media_id.
#
# Chunks live under /tmp/bt_uploads/<session_id> until finish() or the
# next reboot; sessions carry a short TTL so orphans are cleaned up.

import shutil
import tempfile

_VIDEO_TMP_ROOT = os.path.join(tempfile.gettempdir(), "bt_uploads")
os.makedirs(_VIDEO_TMP_ROOT, exist_ok=True)
_MAX_VIDEO_BYTES = 1024 * 1024 * 1024  # 1 GB per file
# Iter 99.2 — Chunk size reduced from 8 MB to 4 MB so uploads work on VPS
# setups with default nginx `client_max_body_size` (often 1 MB out of the
# box; 4 MB slots comfortably under the common 10 MB cap admins bump to).
# VPS operators still need to set: `client_max_body_size 20M;` in nginx.
_MAX_CHUNK_BYTES = 4 * 1024 * 1024      # 4 MB per chunk


class VideoUploadStartBody(BaseModel):
    filename: str
    mime: str
    size: int
    type: str = "gallery"  # matches Media type — usually "gallery"
    title: Optional[str] = ""


@api.post("/media/video/start")
async def video_upload_start(body: VideoUploadStartBody, user: dict = Depends(get_current_user)):
    if not body.mime.startswith("video/"):
        raise HTTPException(400, "Only video files can use the large-file endpoint.")
    if body.size <= 0 or body.size > _MAX_VIDEO_BYTES:
        raise HTTPException(413, f"Video too large. Max {_MAX_VIDEO_BYTES // (1024*1024)} MB.")
    # Iter 76.8 — Enforce the plan's max_media cap on video uploads too.
    if user.get("role") == "artist" and (body.type or "gallery") == "gallery":
        try:
            from routes.subscriptions import resolve_plan
            plan = await resolve_plan(db, user["id"])
            limit = int(plan.get("max_media") or 6)
            current = await db.media.count_documents({
                "user_id": user["id"], "type": "gallery",
                "deleted": {"$ne": True},
            })
            if current >= limit:
                raise HTTPException(
                    402,
                    f"Your {plan.get('name','Free')} plan allows up to {limit} gallery uploads "
                    f"(you have {current}). Upgrade your plan or remove an existing item to add more.",
                )
        except HTTPException:
            raise
        except Exception as _e:
            log.warning("Plan-gate check for video-start failed: %s", _e)

    sid = new_id()
    session_dir = os.path.join(_VIDEO_TMP_ROOT, sid)
    os.makedirs(session_dir, exist_ok=True)
    await db.video_upload_sessions.insert_one({
        "id": sid, "user_id": user["id"],
        "filename": body.filename, "mime": body.mime, "size": body.size,
        "type": body.type, "title": body.title or body.filename,
        "chunks_received": 0, "assembled": False, "session_dir": session_dir,
        "created_at": utcnow(),
    })
    return {"session_id": sid, "chunk_size": _MAX_CHUNK_BYTES}


@api.post("/media/video/chunk")
async def video_upload_chunk(
    session_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    sess = await db.video_upload_sessions.find_one({"id": session_id, "user_id": user["id"]})
    if not sess:
        raise HTTPException(404, "Upload session not found or expired.")
    if sess.get("assembled"):
        raise HTTPException(400, "This upload session is already finalised.")
    chunk_path = os.path.join(sess["session_dir"], f"part_{chunk_index:06d}.bin")
    # Stream chunk to disk so we never buffer > chunk_size in memory.
    data = await chunk.read()
    if len(data) > _MAX_CHUNK_BYTES:
        raise HTTPException(413, f"Chunk too large. Max {_MAX_CHUNK_BYTES // (1024*1024)} MB per chunk.")
    Path(chunk_path).write_bytes(data)
    await db.video_upload_sessions.update_one(
        {"id": session_id}, {"$inc": {"chunks_received": 1}},
    )
    return {"ok": True, "chunk_index": chunk_index, "bytes": len(data)}


@api.post("/media/video/finish")
async def video_upload_finish(
    session_id: str = Form(...),
    poster_data_url: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    sess = await db.video_upload_sessions.find_one({"id": session_id, "user_id": user["id"]})
    if not sess:
        raise HTTPException(404, "Upload session not found or expired.")
    if sess.get("assembled"):
        raise HTTPException(400, "Already finalised.")

    session_dir = sess["session_dir"]
    # Assemble chunks in ascending index order.
    parts = sorted(f for f in os.listdir(session_dir) if f.startswith("part_"))
    if not parts:
        raise HTTPException(400, "No chunks received.")

    assembled_path = os.path.join(session_dir, "_assembled.bin")
    total_size = 0
    with open(assembled_path, "wb") as out:
        for p in parts:
            with open(os.path.join(session_dir, p), "rb") as ch:
                buf = ch.read()
                out.write(buf)
                total_size += len(buf)

    if total_size == 0:
        raise HTTPException(400, "Empty upload.")
    if total_size > _MAX_VIDEO_BYTES:
        raise HTTPException(413, "Assembled file exceeds 1 GB limit.")

    # Upload assembled file to Emergent Object Storage.
    ext = (sess["filename"].rsplit(".", 1)[-1] if "." in sess["filename"] else "mp4").lower()
    mid = new_id()
    storage_path = f"booktalent/videos/{user['id']}/{mid}.{ext}"
    try:
        from storage import put_object
        with open(assembled_path, "rb") as f:
            raw = f.read()
        put_object(storage_path, raw, sess["mime"])
    except Exception as e:
        log.error("Object storage upload failed for session %s: %s", session_id, e)
        raise HTTPException(502, "Storage upload failed — please retry.")
    finally:
        # Always clean the tmp session dir so 1GB files don't accumulate.
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass

    # Iter 76.5 — Client-supplied poster frame. Client captures the first
    # frame in a <canvas> and passes a small JPEG data URL. Stored in the
    # `thumb` field so existing `/api/media/{id}/thumb` serves it with
    # zero extra endpoints. Silently skips on failure.
    thumb_b64 = None
    if poster_data_url and poster_data_url.startswith("data:image/"):
        try:
            _hdr, _b64 = poster_data_url.split(",", 1)
            poster_raw = base64.b64decode(_b64)
            # Normalise + clip to square 400x400 using the existing helper.
            tbytes, _tm = make_thumbnail(poster_raw, "image/jpeg")
            if tbytes:
                thumb_b64 = base64.b64encode(tbytes).decode()
        except Exception as _e:
            log.warning("Video poster decode failed for %s: %s", mid, _e)

    doc = {
        "id": mid, "user_id": user["id"],
        "type": sess.get("type") or "gallery",
        "mime": sess["mime"], "size": total_size,
        "original_size": total_size,
        "title": sess.get("title") or sess["filename"],
        "is_featured": False,
        "storage_path": storage_path,
        "thumb": thumb_b64,  # base64 jpeg first-frame poster (client-captured)
        "order": 0,
        "created_at": utcnow(),
    }
    await db.media.insert_one(doc)
    await db.video_upload_sessions.update_one(
        {"id": session_id}, {"$set": {"assembled": True, "media_id": mid, "assembled_at": utcnow()}},
    )
    return {"ok": True, "id": mid, "size": total_size, "storage_path": storage_path, "has_poster": bool(thumb_b64)}


# ─── Iter 76.5 — Featured Reel (hero video on artist profile) ────────────

@api.post("/media/{media_id}/feature-reel")
async def media_feature_reel(media_id: str, user: dict = Depends(get_current_user)):
    """Toggle an artist's featured reel — the muted-autoplay hero video
    at the top of their public profile. Only videos are eligible.
    Passing the currently-featured id again clears the reel."""
    if user["role"] != "artist":
        raise HTTPException(403, "Only artists have a featured reel.")
    doc = await db.media.find_one({"id": media_id, "user_id": user["id"]})
    if not doc:
        raise HTTPException(404, "Media not found")
    if not (doc.get("mime") or "").startswith("video/"):
        raise HTTPException(400, "Only videos can be a featured reel.")

    profile = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
    current = profile.get("featured_video_id")
    new_value = None if current == media_id else media_id
    await db.artist_profiles.update_one(
        {"user_id": user["id"]},
        {"$set": {"featured_video_id": new_value, "updated_at": utcnow()}},
    )
    return {"ok": True, "featured_video_id": new_value}


# ─── Iter 76.5 — Boost Insights (ROI mini-chart) ─────────────────────────

@api.get("/boost/insights")
async def boost_insights(user: dict = Depends(get_current_user)):
    """Return the artist's last-14-days profile views + booking requests,
    plus the active-boost windows overlaid so the artist can see the ROI
    of every purchase.

    Uses aggregate counts from the notifications + bookings + analytics
    collections we already write to — no schema changes needed.
    """
    if user["role"] != "artist":
        return {"active_boosts": [], "days": []}

    # Build a 14-day timeline ending today (UTC).
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    today = _dt.now(_tz.utc).date()
    day_keys = [(today - _td(days=i)).isoformat() for i in range(13, -1, -1)]

    # Views — pulled from analytics_events "profile_view" if available;
    # fall back to profile_views counter increments (zero'd per day).
    daily_views: Dict[str, int] = {d: 0 for d in day_keys}
    async for ev in db.analytics_events.find({
        "user_id": user["id"], "event": "profile_view",
        "created_at": {"$gte": (today - _td(days=13)).isoformat()},
    }, {"created_at": 1, "_id": 0}):
        try:
            d = str(ev.get("created_at", ""))[:10]
            if d in daily_views:
                daily_views[d] += 1
        except Exception:
            pass

    # Booking requests — count bookings that referenced this artist per day.
    daily_bookings: Dict[str, int] = {d: 0 for d in day_keys}
    async for b in db.bookings.find({
        "artist_id": user["id"],
        "created_at": {"$gte": (today - _td(days=13)).isoformat()},
    }, {"created_at": 1, "_id": 0}):
        try:
            d = str(b.get("created_at", ""))[:10]
            if d in daily_bookings:
                daily_bookings[d] += 1
        except Exception:
            pass

    # Active boost windows — used to shade the chart client-side.
    active = []
    async for sub in db.boost_subscriptions.find({
        "user_id": user["id"], "status": {"$in": ["active", "expired"]},
    }, {"_id": 0}):
        active.append({
            "id": sub.get("id"),
            "package_name": (sub.get("package_snapshot") or {}).get("name") or sub.get("plan"),
            "starts_at": sub.get("starts_at") or sub.get("created_at"),
            "expires_at": sub.get("expires_at"),
            "status": sub.get("status"),
        })

    days = [{"date": d, "views": daily_views[d], "bookings": daily_bookings[d]} for d in day_keys]
    return {
        "active_boosts": active[-5:],  # latest 5 for compact rendering
        "days": days,
        "totals": {
            "views_14d": sum(daily_views.values()),
            "bookings_14d": sum(daily_bookings.values()),
        },
    }


@api.get("/media")
async def media_list(
    type: Optional[str] = None,
    user_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = {"user_id": user_id or user["id"]}
    if type:
        q["type"] = type
    items = await db.media.find(q, {"data": 0}).sort([("order", 1), ("created_at", -1)]).to_list(500)
    return [clean(x) for x in items]


@api.get("/public/media")
async def public_media_list(user_id: str, type: Optional[str] = None):
    q = {"user_id": user_id}
    if type:
        q["type"] = type
    items = await db.media.find(q, {"data": 0}).sort([("order", 1), ("created_at", -1)]).to_list(500)
    return [clean(x) for x in items]


@api.delete("/media/{media_id}")
async def media_delete(media_id: str, user: dict = Depends(get_current_user)):
    doc = await db.media.find_one({"id": media_id})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Forbidden")
    await db.media.delete_one({"id": media_id})
    return {"ok": True}


@api.post("/media/{media_id}/feature")
async def media_feature(media_id: str, user: dict = Depends(get_current_user)):
    doc = await db.media.find_one({"id": media_id})
    if not doc or doc["user_id"] != user["id"]:
        raise HTTPException(404, "Not found")
    await db.media.update_one({"id": media_id}, {"$set": {"is_featured": not doc.get("is_featured", False)}})
    return {"ok": True}


@api.post("/media/reorder")
async def media_reorder(body: dict, user: dict = Depends(get_current_user)):
    ids = body.get("ids", [])
    for i, mid in enumerate(ids):
        await db.media.update_one({"id": mid, "user_id": user["id"]}, {"$set": {"order": i}})
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# ARTIST DISCOVERY / SEARCH
# ─────────────────────────────────────────────────────────────────────────────
@api.get("/artists/search")
async def artists_search(
    q: Optional[str] = None,
    category: Optional[str] = None,
    city: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    language: Optional[str] = None,
    sort: str = "relevance",
    page: int = 1,
    limit: int = 12,
):
    # Only LIVE artists appear in public search (KYC + T&C + Agreement complete).
    # Non-live/kyc-pending artists must be invisible to customers.
    query: dict = {"suspended": {"$ne": True}, "kyc_status": "live"}
    if category:
        query["category"] = category
    if city:
        query["city"] = city
    if language:
        query["languages"] = language
    if q:
        query["$or"] = [
            {"stage_name": {"$regex": q, "$options": "i"}},
            {"bio": {"$regex": q, "$options": "i"}},
            {"category": {"$regex": q, "$options": "i"}},
        ]

    sort_field = {
        "newest": ("created_at", -1),
        "rating": ("rating_avg", -1),
        "popular": ("events_done", -1),
        "relevance": ("is_boosted", -1),
    }.get(sort, ("is_boosted", -1))

    total = await db.artist_profiles.count_documents(query)
    docs = await db.artist_profiles.find(query).sort([sort_field, ("rating_avg", -1)]).skip((page - 1) * limit).limit(limit).to_list(limit)

    out = []
    for p in docs:
        p = clean(p)
        pkgs = await db.packages.find({"artist_id": p["user_id"]}).to_list(20)
        if pkgs:
            p["starting_price"] = min(float(pp.get("price", 0)) for pp in pkgs)
            p["packages_count"] = len(pkgs)
        else:
            p["starting_price"] = None
            p["packages_count"] = 0
        if min_price is not None and (p["starting_price"] is None or p["starting_price"] < min_price):
            continue
        if max_price is not None and (p["starting_price"] is None or p["starting_price"] > max_price):
            continue
        # Gallery thumbs for dynamic-thumbnail rotation
        gallery = await db.media.find(
            {"user_id": p["user_id"], "type": "gallery"},
            {"data": 0, "thumb": 0},
        ).sort([("is_featured", -1), ("order", 1)]).limit(8).to_list(8)
        p["gallery_thumbs"] = [{"id": g["id"], "is_featured": g.get("is_featured", False)} for g in gallery]
        out.append(p)
    return {"total": total, "page": page, "items": out}


@api.get("/artists/featured")
async def artists_featured(limit: int = 8):
    # LIVE-only gate: featured strip is public, so keep same rule as search.
    base = {"suspended": {"$ne": True}, "kyc_status": "live"}
    docs = await db.artist_profiles.find({**base, "$or": [{"is_featured": True}, {"is_boosted": True}]}).limit(limit).to_list(limit)
    if len(docs) < limit:
        extra = await db.artist_profiles.find({**base, "is_featured": {"$ne": True}}).sort("rating_avg", -1).limit(limit - len(docs)).to_list(limit)
        docs.extend(extra)
    out = []
    for p in docs:
        p = clean(p)
        pkgs = await db.packages.find({"artist_id": p["user_id"]}).to_list(20)
        p["starting_price"] = min((float(pp.get("price", 0)) for pp in pkgs), default=None)
        gallery = await db.media.find(
            {"user_id": p["user_id"], "type": "gallery"},
            {"data": 0, "thumb": 0},
        ).sort([("is_featured", -1), ("order", 1)]).limit(8).to_list(8)
        p["gallery_thumbs"] = [{"id": g["id"], "is_featured": g.get("is_featured", False)} for g in gallery]
        out.append(p)
    return out


@api.get("/artists/{user_id}")
async def artist_detail(user_id: str):
    prof = await db.artist_profiles.find_one({"user_id": user_id})
    if not prof:
        raise HTTPException(404, "Artist not found")
    # Iter 52.8 — suspended artists must not be reachable via the public
    # profile URL either (deep-links, share links, cached SEO cards).
    if prof.get("suspended"):
        raise HTTPException(404, "Artist not found")
    # LIVE-only gate for public detail page. Non-live artists (kyc pending,
    # T&C not accepted, agreement not generated) must 404 on the public URL.
    if prof.get("kyc_status") != "live":
        raise HTTPException(404, "Artist not found")
    # increment view counter (best-effort)
    await db.artist_profiles.update_one({"user_id": user_id}, {"$inc": {"profile_views": 1}})
    prof = clean(prof)
    user = await db.users.find_one({"id": user_id})
    packages = await db.packages.find({"artist_id": user_id}).sort("price", 1).to_list(50)
    media = await db.media.find({"user_id": user_id, "type": {"$in": ["gallery", "video", "reel", "profile", "cover"]}}, {"data": 0}).to_list(200)
    reviews = await db.reviews.find({"artist_id": user_id, "moderated": {"$ne": "rejected"}}).sort("created_at", -1).limit(20).to_list(20)
    availability = await db.availability.find({"user_id": user_id}).to_list(200)
    return {
        "profile": prof,
        "user": clean(user),
        "packages": [clean(p) for p in packages],
        "media": [clean(m) for m in media],
        "reviews": [clean(r) for r in reviews],
        "availability": [clean(a) for a in availability],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PACKAGES
# ─────────────────────────────────────────────────────────────────────────────
@api.post("/packages")
async def create_package(body: PackageBody, user: dict = Depends(get_current_user)):
    if user["role"] != "artist":
        raise HTTPException(403, "Artists only")
    doc = body.model_dump()
    doc.update({"id": new_id(), "artist_id": user["id"], "created_at": utcnow()})
    await db.packages.insert_one(doc)
    return clean(doc)


@api.get("/packages/mine")
async def list_my_packages(user: dict = Depends(get_current_user)):
    docs = await db.packages.find({"artist_id": user["id"]}).sort("price", 1).to_list(50)
    return [clean(d) for d in docs]


@api.put("/packages/{pid}")
async def update_package(pid: str, body: PackageBody, user: dict = Depends(get_current_user)):
    res = await db.packages.update_one({"id": pid, "artist_id": user["id"]}, {"$set": body.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api.delete("/packages/{pid}")
async def delete_package(pid: str, user: dict = Depends(get_current_user)):
    await db.packages.delete_one({"id": pid, "artist_id": user["id"]})
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# AVAILABILITY
# ─────────────────────────────────────────────────────────────────────────────
@api.post("/availability")
async def set_availability(body: AvailabilityBody, user: dict = Depends(get_current_user)):
    update_doc = {
        "id": new_id(), "user_id": user["id"], "date": body.date, "status": body.status,
    }
    if body.status == "premium":
        update_doc["premium_multiplier"] = float(body.premium_multiplier or 1.5)
        update_doc["premium_label"] = body.premium_label or "Premium date"
    await db.availability.update_one(
        {"user_id": user["id"], "date": body.date},
        {"$set": update_doc},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/availability/{date_str}")
async def clear_availability(date_str: str, user: dict = Depends(get_current_user)):
    await db.availability.delete_one({"user_id": user["id"], "date": date_str})
    return {"ok": True}


@api.get("/availability/mine")
async def my_availability(user: dict = Depends(get_current_user)):
    # Iter 73 — Newest-first so the artist sees their latest entries at the
    # top of the "Existing Entries" list on the Availability tab.
    docs = await db.availability.find({"user_id": user["id"]}).sort("date", -1).to_list(500)
    return [clean(d) for d in docs]


@api.get("/artists/{user_id}/availability")
async def artist_availability(user_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None):
    """
    Public read of an artist's blocked/booked/premium dates for the given range.
    Used by the profile calendar + booking date-picker so customers see live
    availability and any weekend/festival premium pricing.
    """
    q: dict = {"user_id": user_id, "status": {"$in": ["blocked", "booked", "premium"]}}
    if from_date and to_date:
        q["date"] = {"$gte": from_date, "$lte": to_date}
    elif from_date:
        q["date"] = {"$gte": from_date}
    docs = await db.availability.find(q).to_list(1000)
    blocked = sorted({d.get("date") for d in docs if d.get("status") in ("blocked", "booked") and d.get("date")})
    premium = [
        {"date": d["date"], "multiplier": d.get("premium_multiplier", 1.5), "label": d.get("premium_label", "Premium")}
        for d in docs if d.get("status") == "premium" and d.get("date")
    ]
    premium.sort(key=lambda x: x["date"])
    return {"blocked_dates": blocked, "premium_dates": premium, "count": len(blocked) + len(premium)}


@api.get("/artists/{user_id}/quote")
async def artist_quote(user_id: str, city: str):
    """
    Pre-flight venue check for the artist profile "Where's your event?" prompt.

    Returns whether the given event city is outstation for this artist (using
    the canonical city-alias map so Bombay/Mumbai count as the same city),
    plus the packages with an outstation surcharge applied when relevant so
    the customer sees the *right* price BEFORE hitting Book Now.

    Contract:
      GET /api/artists/{user_id}/quote?city=Mumbai
      →  {
           artist_city: "Mumbai",
           event_city:  "Mumbai",
           is_outstation: false,
           outstation_multiplier: 1.0,
           outstation_notice: "…",              (only when outstation)
           packages: [{id, name, base_price, quoted_price, ...}]
         }

    Business rules:
      * `outstation_multiplier` comes from admin/settings public payload
        (`outstation_price_multiplier`, default 1.15 — a 15% surcharge to
        absorb higher-effort quoting). Falls back to 1.0 if the setting is
        absent, so the endpoint stays backward-compatible.
      * The multiplier is APPLIED to `base_price` to produce `quoted_price`.
        The customer sees quoted_price on the artist card; the booking flow
        still stores base_price + will let them add explicit TA / rider costs
        on the review step (Iter 52.5 additions).
    """
    if not city or not city.strip():
        raise HTTPException(400, "city is required")

    profile = await db.artist_profiles.find_one({"user_id": user_id})
    if not profile:
        raise HTTPException(404, "Artist not found")
    # Iter 52.8 — suspended artists cannot be quoted either.
    if profile.get("suspended"):
        raise HTTPException(404, "Artist not found")

    if not _CITY_ALIAS_MAP:
        await _refresh_city_aliases()

    artist_city = profile.get("city")
    is_out = _outstation_check(artist_city, city, _CITY_ALIAS_MAP)

    settings = await db.settings.find_one({"key": "platform"}) or {}
    multiplier = float(settings.get("outstation_price_multiplier") or 1.0) if is_out else 1.0
    notice = settings.get("outstation_notice") or (
        "Travel, accommodation, local transportation, meals, hospitality, and any other "
        "outstation expenses are NOT included in the Artist Package Fee. Please arrange "
        "these directly with the artist."
    )

    # Package list — apply the outstation multiplier for a quoted display price.
    pkgs_out: list[dict] = []
    async for p in db.packages.find({"artist_id": user_id}).sort("price", 1):
        base = float(p.get("price") or 0)
        pkgs_out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "duration": p.get("duration"),
            "description": p.get("description"),
            "is_popular": bool(p.get("is_popular")),
            "base_price": base,
            "quoted_price": round(base * multiplier, 2),
            "travel_required": bool(p.get("travel_required")),
            "accommodation_required": bool(p.get("accommodation_required")),
        })

    # Iter 52.7 — Distil the Travel & Hospitality rider from the answers the
    # artist already filled in during onboarding (`profile.answers`). This is
    # what the customer sees BEFORE confirming an outstation booking, so no
    # duplicate input is asked of the artist elsewhere.
    ans = (profile.get("answers") or {}) if isinstance(profile.get("answers"), dict) else {}
    def _first(*keys):
        for k in keys:
            v = ans.get(k)
            if v not in (None, "", [], {}): return v
        return None
    hosp = _first("hospitality_needs") or []
    if isinstance(hosp, str):
        hosp = [x.strip() for x in hosp.split(",") if x.strip()]
    food_prefs = [h for h in hosp if h in ("Vegetarian Meal", "Non-Vegetarian Meal", "Jain Meal")]

    rider = {
        "travel_modes":    _first("travel_modes") or [],
        "flight_class":    _first("flight_class"),
        "local_transport": _first("local_transport") or _first("pickup_required"),
        "hotel_required":  _first("hotel_required"),
        "hotel_category":  _first("hotel_category"),
        "rooms_required":  _first("rooms_required") or _first("travel_party_size"),
        "food_preference": ", ".join(food_prefs) if food_prefs else _first("food_preference"),
        "hospitality_needs": hosp,
        "green_room_required": ("Green Room" in hosp) or bool(_first("separate_green_rooms")),
        "sound_provider":  _first("sound_provider"),
        "sound_details":   _first("sound_details", "sound_requirements"),
        "light_details":   _first("light_details", "light_requirements", "own_lighting"),
        "technical_notes": _first("technical_notes"),
        "travel_notes":    _first("travel_notes"),
        "travel_who_pays": _first("travel_who_pays"),
        "additional_conditions": _first("additional_conditions", "other_conditions"),
    }
    # Also snapshot which entries actually have content so the FE can render
    # empty-state gracefully.
    rider["has_any"] = any(
        (v if not isinstance(v, list) else len(v) > 0)
        for k, v in rider.items() if k != "has_any"
    )

    return {
        "artist_id": user_id,
        "artist_city": artist_city,
        "event_city": city.strip(),
        "is_outstation": is_out,
        "outstation_multiplier": multiplier,
        "outstation_surcharge_pct": round((multiplier - 1) * 100, 2) if is_out else 0,
        "outstation_notice": notice if is_out else "",
        "packages": pkgs_out,
        "rider": rider,   # ← Travel & Hospitality snapshot from questionnaire
    }




@api.get("/artists/{user_id}/suggested")
async def artist_suggested(user_id: str, date_str: Optional[str] = None, limit: int = 4):
    """
    Complementary artists for cross-selling during the booking flow.
    Rule of thumb: same city, DIFFERENT category, sorted by rating.
    If `date` is passed, filter out artists who are busy/blocked on that day.
    """
    src = await db.artist_profiles.find_one({"user_id": user_id})
    if not src:
        raise HTTPException(404, "Artist not found")
    q: dict = {
        "user_id": {"$ne": user_id},
        "city": src.get("city"),
        "category": {"$ne": src.get("category")},
        "is_active": {"$ne": False},
        "suspended": {"$ne": True},   # Iter 52.8 — hide suspended
    }
    cands = await db.artist_profiles.find(q).sort([("rating_avg", -1), ("review_count", -1)]).to_list(limit * 3)

    if date_str and cands:
        cand_ids = [c["user_id"] for c in cands]
        busy = set()
        async for a in db.availability.find({
            "user_id": {"$in": cand_ids}, "date": date_str,
            "status": {"$in": ["blocked", "booked"]},
        }):
            busy.add(a["user_id"])
        async for b in db.bookings.find({
            "artist_id": {"$in": cand_ids}, "event_date": date_str,
            "status": {"$in": ["pending_artist", "confirmed", "started"]},
        }):
            busy.add(b["artist_id"])
        cands = [c for c in cands if c["user_id"] not in busy]

    out = []
    for c in cands[:limit]:
        out.append({
            "user_id": c["user_id"],
            "stage_name": c.get("stage_name"),
            "category": c.get("category"),
            "city": c.get("city"),
            "starting_price": c.get("starting_price"),
            "rating_avg": c.get("rating_avg", 0),
            "review_count": c.get("review_count", 0),
            "slug": c.get("slug"),
            "profile_image": c.get("profile_image"),
        })
    return {"suggested": out}


# ─────────────────────────────────────────────────────────────────────────────
# BOOKINGS
# ─────────────────────────────────────────────────────────────────────────────
def calc_booking_pricing(package_price: float, addon_total: float, coupon_discount: float = 0) -> dict:
    """
    BookTalent is ONLY an intermediary marketplace. We do NOT collect the artist's
    performance fee — it is settled directly between Customer and Artist.

    The only amount BookTalent collects from the Customer is:
        Platform Service Fee (5% of the Artist Fee) + 18% GST on that fee.

    Coupon discounts apply to the artist_fee (reducing what the customer owes
    the artist, and proportionally the platform_fee + GST).
    """
    artist_fee = round(max(0, package_price + addon_total - coupon_discount), 2)
    platform_fee = round(artist_fee * (PLATFORM_FEE_PCT / 100), 2)   # only thing BookTalent invoices
    gst = round(platform_fee * (GST_PCT / 100), 2)                   # GST is only on the platform fee
    total = round(platform_fee + gst, 2)                              # amount payable to BookTalent
    # Token / balance no longer apply — BookTalent charges 100% upfront on the
    # platform fee; the artist fee is settled directly.
    return {
        "package_fee": package_price,
        "addons_total": addon_total,
        "coupon_discount": coupon_discount,
        "artist_fee": artist_fee,         # paid by customer directly to artist
        "platform_fee": platform_fee,     # the only line BookTalent collects pre-tax
        "gst": gst,                       # 18% on platform_fee
        "total": total,                   # platform_fee + gst (BookTalent invoice total)
        "token_amount": total,            # legacy field — token-equivalent now equals full BookTalent amount
        "balance_due": 0,
    }


ADDON_PRICES = {
    "dhol": 3500, "anchor": 5000, "photo": 4000, "extra-hour": 8000,
}


@api.post("/bookings")
async def create_booking(body: BookingCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ("customer", "corporate", "agency"):
        raise HTTPException(403, "Only customers can create bookings")
    # Iter 52.5 — enforce Terms & Conditions declaration from the Review step.
    if not body.tnc_accepted:
        raise HTTPException(400, "Please accept the Terms & Conditions before proceeding")

    # Iter 99 — LIVE-only gate for booking creation.
    # A booking must never be created against an artist who has not completed
    # KYC → T&C → Agreement (i.e. `kyc_status != "live"`). This complements
    # the search/detail 404 gate so the state machine is enforced end-to-end.
    artist_profile = await db.artist_profiles.find_one({"user_id": body.artist_id}) or {}
    if not artist_profile:
        raise HTTPException(404, "Artist not found")
    if artist_profile.get("suspended") or artist_profile.get("kyc_status") != "live":
        raise HTTPException(400, "This artist is not currently accepting bookings.")

    pkg = await db.packages.find_one({"id": body.package_id, "artist_id": body.artist_id})
    if not pkg:
        raise HTTPException(404, "Package not found")

    artist = await db.users.find_one({"id": body.artist_id})
    if not artist:
        raise HTTPException(404, "Artist not found")
    # LIVE-only gate: booking creation must fail for non-live artists so that
    # KYC-pending / T&C-pending / agreement-pending artists can never be booked
    # (matches the "not visible / not bookable" business rule).
    if artist_profile.get("suspended") or artist_profile.get("kyc_status") != "live":
        raise HTTPException(400, "This artist is not currently accepting bookings.")
    # Warm the city-alias cache on first use — subsequent bookings reuse it.
    if not _CITY_ALIAS_MAP:
        await _refresh_city_aliases()

    # check availability
    av = await db.availability.find_one({"user_id": body.artist_id, "date": body.event_date})
    if av and av.get("status") in ("booked", "blocked"):
        # Smart suggestion: find similar artists
        prof = await db.artist_profiles.find_one({"user_id": body.artist_id}) or {}
        suggestions = []
        for q in [
            {"user_id": {"$ne": body.artist_id}, "category": prof.get("category"), "city": prof.get("city"), "suspended": {"$ne": True}},
            {"user_id": {"$ne": body.artist_id}, "category": prof.get("category"), "suspended": {"$ne": True}},
            {"user_id": {"$ne": body.artist_id}, "city": prof.get("city"), "suspended": {"$ne": True}},
        ]:
            if len(suggestions) >= 3:
                break
            for s in await db.artist_profiles.find(q).sort("rating_avg", -1).limit(3).to_list(3):
                if s["user_id"] not in [x["user_id"] for x in suggestions]:
                    suggestions.append(s)
                    if len(suggestions) >= 3:
                        break
        suggestion_data = [
            {
                "user_id": s["user_id"],
                "stage_name": s["stage_name"],
                "category": s.get("category"),
                "city": s.get("city"),
                "rating_avg": s.get("rating_avg", 0),
                "emoji": s.get("emoji", "🎤"),
            }
            for s in suggestions
        ]
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Selected date is not available",
                "alternatives": suggestion_data,
                "date": body.event_date,
            },
        )

    addon_total = sum(ADDON_PRICES.get(a, 0) for a in body.addons)

    # Sprint 3 — artist-defined add-ons on top of the legacy slug-based ones
    from routes.addons import snapshot_addons
    addon_snapshots, addon_v2_total = await snapshot_addons(
        db, body.artist_id, [s.model_dump() for s in body.addon_selections],
    )
    addon_total += addon_v2_total

    coupon_discount = 0
    coupon_doc = None
    if body.coupon_code:
        try:
            base = float(pkg["price"]) + addon_total
            coupon_doc, coupon_discount = await _validate_coupon(
                body.coupon_code, user_id=user["id"], base_amount=base, event_type=body.event_type,
            )
        except HTTPException as ce:
            # Surface coupon error to the customer instead of silently dropping
            raise ce

    pricing = calc_booking_pricing(float(pkg["price"]), addon_total, coupon_discount)

    # Iter 44 — Resolve or generate the event umbrella. If the customer passed
    # an event_id we validate they already own another booking under it; else
    # we mint a fresh event_id so future artists can be added to this event.
    event_id_final: Optional[str] = None
    if body.event_id:
        owned = await db.bookings.find_one({"event_id": body.event_id, "customer_id": user["id"]})
        if not owned:
            raise HTTPException(400, "event_id does not belong to you")
        event_id_final = body.event_id
    else:
        event_id_final = new_id()

    bid = new_id()
    ref = booking_ref()
    doc = {
        "id": bid,
        "ref": ref,
        "event_id": event_id_final,
        "customer_id": user["id"],
        "artist_id": body.artist_id,
        "package_id": body.package_id,
        "package_name": pkg["name"],
        "addons": body.addons,
        "addon_snapshots": addon_snapshots,
        # Sprint 4 — snapshot the travel/accommodation requirements from the package
        # at booking creation time so future edits to the package don't change history
        "travel_requirements": {
            "travel_required": bool(pkg.get("travel_required")),
            "accommodation_required": bool(pkg.get("accommodation_required")),
            "hotel_category": pkg.get("hotel_category"),
            "flight_class": pkg.get("flight_class"),
            "team_size": pkg.get("team_size"),
            "arrival_buffer_days": pkg.get("arrival_buffer_days"),
            "local_transport_required": bool(pkg.get("local_transport_required")),
            "meals_required": bool(pkg.get("meals_required")),
            "travel_notes": pkg.get("travel_notes", ""),
        },
        "event_date": body.event_date,
        "event_time": body.event_time,
        "event_type": body.event_type,
        # Iter 83 — Sec 20/21/22
        "event_type_other": (body.event_type_other or "").strip() if body.event_type == "Others" else None,
        "number_of_days": int(body.number_of_days or 1),
        "venue": body.venue,
        "venue_address": (body.venue_address or "").strip(),
        "city": body.city,
        # Iter 52.5 — Customer-offered travel allowance (direct-to-artist,
        # informational only). Printed on the contract PDF.
        "customer_travel_allowance": float(body.customer_travel_allowance or 0),
        # Iter 52.5 — T&C declaration audit trail (also enforced at request-time
        # via the 400 guard above).
        "tnc_accepted": True,
        "tnc_accepted_at": datetime.now(timezone.utc).isoformat(),
        # Outstation Business Rule — snapshot both cities and flag mismatch at
        # booking-creation time so history is immutable even if the artist
        # profile city or the customer's event city is edited later.
        # City aliases (Delhi/NCR/New Delhi etc.) are canonicalised first so
        # intra-region events don't wrongly trigger the outstation gate.
        "artist_city": artist_profile.get("city") if artist_profile else None,
        "event_city": body.city,
        "is_outstation": _outstation_check(
            artist_profile.get("city") if artist_profile else None,
            body.city,
            _CITY_ALIAS_MAP,
        ),
        "guests": body.guests,
        "language_pref": body.language_pref,
        "notes": body.notes,
        "special_instructions": (body.special_instructions or "").strip(),
        "customer_name": body.customer_name or f"{user.get('first_name','')} {user.get('last_name','')}".strip(),
        "customer_phone": body.customer_phone or user.get("phone"),
        "customer_email": body.customer_email or user.get("email"),
        "coupon_code": body.coupon_code,
        "pricing": pricing,
        "status": "pending_payment",  # pending_payment → pending_artist → confirmed → started → completed → reviewed
        "payment_status": "unpaid",
        "amount_paid": 0,
        "history": [{"at": utcnow(), "action": "created", "by": user["id"]}],
        "created_at": utcnow(),
    }
    await db.bookings.insert_one(doc)

    # Iter 99 — Stamp the artist's commercial deal onto the booking so
    # future rate changes never retroactively affect old bookings' payouts.
    try:
        from routes.req_batch_6 import stamp_deal_snapshot_on_booking
        await stamp_deal_snapshot_on_booking(db, bid, body.artist_id)
    except Exception as _e:  # noqa: BLE001
        log.warning("deal snapshot failed for %s: %s", bid, _e)
    if coupon_doc and coupon_discount > 0:
        await db.coupon_redemptions.insert_one({
            "id": new_id(),
            "coupon_id": coupon_doc["id"],
            "coupon_code": coupon_doc["code"],
            "user_id": user["id"],
            "booking_id": bid,
            "discount_amount": coupon_discount,
            "booking_total": pricing["total"],
            "created_at": utcnow(),
        })
        await db.coupons.update_one(
            {"id": coupon_doc["id"]},
            {"$inc": {"usage_count": 1, "total_discount": coupon_discount}},
        )

    # notifications: artist
    await db.notifications.insert_one({
        "id": new_id(), "user_id": body.artist_id, "type": "booking_request",
        "title": "New booking inquiry", "body": f"New inquiry for {body.event_date}", "read": False, "created_at": utcnow(),
        "link": f"/dashboard/bookings/{bid}",
    })

    return clean(doc)


# ─────────────────────────────────────────────────────────────────────────────
# Iter 44 — Multi-Artist Cart Batch Booking
# ─────────────────────────────────────────────────────────────────────────────
class BookingBatchCreate(BaseModel):
    items: List[BookingCreate]
    event_id: Optional[str] = None  # shared event umbrella (auto-generated if omitted)


@api.post("/bookings/batch")
async def create_booking_batch(body: BookingBatchCreate, user: dict = Depends(get_current_user)):
    """Create N bookings in one shot, all sharing a single event_id so the
    customer can see them together on the Booking Recap page and pay for all
    Platform Service Fees in a single Razorpay checkout. Each booking still
    has its own 24-hour Artist Confirmation window, its own contract, and its
    own pending_artist → confirmed lifecycle."""
    if user["role"] not in ("customer", "corporate", "agency"):
        raise HTTPException(403, "Only customers can create bookings")
    if not body.items:
        raise HTTPException(400, "At least one booking item is required")
    if len(body.items) > 6:
        raise HTTPException(400, "Cannot batch more than 6 artists per event")

    # Resolve umbrella event_id (validate ownership if provided).
    event_id_final: Optional[str]
    if body.event_id:
        owned = await db.bookings.find_one({"event_id": body.event_id, "customer_id": user["id"]})
        if not owned:
            raise HTTPException(400, "event_id does not belong to you")
        event_id_final = body.event_id
    else:
        event_id_final = None  # first item will mint it, then we stamp the rest

    created_ids: List[str] = []
    created_refs: List[str] = []
    total_platform_fee = 0.0
    total_gst = 0.0
    total_token = 0.0
    # Each item shares the umbrella event_id — we simply forward-call the
    # single-booking creator to reuse ALL the availability, coupon,
    # outstation, snapshot and notification logic. The FIRST item mints
    # the event_id when caller didn't provide one; every subsequent item
    # attaches to it. Any 400 short-circuits the entire batch (best-effort
    # — no cross-doc transaction).
    for idx, item in enumerate(body.items):
        # Only pass event_id once we have one that already belongs to the
        # customer — otherwise create_booking's ownership gate rejects it.
        item.event_id = event_id_final if event_id_final else None
        doc = await create_booking(item, user)  # returns cleaned booking dict
        if event_id_final is None:
            event_id_final = doc.get("event_id")
        created_ids.append(doc["id"])
        created_refs.append(doc["ref"])
        p = doc.get("pricing", {})
        total_platform_fee += float(p.get("platform_fee", 0) or 0)
        total_gst += float(p.get("gst", 0) or 0)
        total_token += float(p.get("token_amount", p.get("total", 0)) or 0)

    return {
        "event_id": event_id_final,
        "booking_ids": created_ids,
        "booking_refs": created_refs,
        "pricing_total": {
            "platform_fee": round(total_platform_fee, 2),
            "gst": round(total_gst, 2),
            "token_amount": round(total_token, 2),
        },
    }


class BatchPaymentInit(BaseModel):
    booking_ids: List[str]
    method: Literal["card", "upi", "netbanking"]


# NOTE: Legacy /payments/batch/init + /payments/batch/verify endpoints removed
# in the Iter 64 payment cleanup. Multi-booking checkout now flows exclusively
# through /api/payments/easebuzz/init (routes/easebuzz.py), which handles
# batch booking IDs natively.


# Iter 48 — /events/{id}/recap + /events/{id}/summary moved to routes/events.py


# Iter 48 — /events/{id}/recap + /events/{id}/summary moved to routes/events.py
# (registered near the bottom of this file alongside the other route modules).


# Iter 53 — Artist Payment Gating: platform fee, GST and BookTalent-side totals
# are BookTalent-only lines. Artists must never see them (transparent
# business-model rule). They only see: package_name, pricing.package_fee.
# We keep pricing.addons_total + artist_fee (their earnings) too, but scrub
# platform_fee / gst / total / token_amount / balance_due before serialising.
_ARTIST_PRICING_REDACT_KEYS = (
    "platform_fee",
    "gst",
    "total",
    "token_amount",
    "balance_due",
    "coupon_discount",
)


def _redact_pricing_for_artist(booking_doc: dict) -> None:
    """Remove BookTalent-facing pricing lines from a booking dict in-place."""
    p = booking_doc.get("pricing")
    if isinstance(p, dict):
        for k in _ARTIST_PRICING_REDACT_KEYS:
            p.pop(k, None)


@api.get("/bookings/mine")
async def my_bookings(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    q: dict = {}
    if user["role"] == "artist":
        q["artist_id"] = user["id"]
    elif user["role"] == "admin":
        pass
    else:
        q["customer_id"] = user["id"]
    if status:
        q["status"] = status
    docs = await db.bookings.find(q).sort("created_at", -1).to_list(500)
    out = []
    for d in docs:
        cleaned = clean(d)
        paid = (cleaned.get("payment_status") == "paid") or (cleaned.get("amount_paid", 0) > 0)
        # Iter 52.8 — Same contact-privacy rule as GET /bookings/{bid}.
        if not paid and user["role"] == "artist":
            for k in ("customer_phone", "customer_email"):
                cleaned.pop(k, None)
            cleaned["_contact_locked"] = True
        # Iter 53 — Business-model transparency: strip platform-fee / total
        # from every artist-facing booking payload regardless of payment state.
        if user["role"] == "artist":
            _redact_pricing_for_artist(cleaned)
        out.append(cleaned)
    return out


# ─── Iter 74 — Booking Drafts + Recent Views ─────────────────────────────
#
# * booking_drafts: one row per (user_id, artist_id). Upserted every time
#   the customer taps "Save & Finish Later" or (later) via a debounced
#   auto-save from BookingFlow. Restored on next visit so the customer
#   picks up on ANY device.
# * recent_views: capped log per user of the last artists they viewed.
#   Only 8 kept per user, oldest evicted. Rendered on the Customer
#   Dashboard as "Recently Viewed" so they can jump back with one tap.

class BookingDraftBody(BaseModel):
    artist_id: str
    form: Dict[str, Any] = {}
    step: int = 1

async def _artist_snapshot(user_id: str) -> Dict[str, Any]:
    """Compact artist card used inside drafts & recent-view lists."""
    profile = await db.artist_profiles.find_one({"user_id": user_id})
    user = await db.users.find_one({"id": user_id})
    if not profile or not user:
        return {"user_id": user_id, "stage_name": "Artist", "category": "", "city": "",
                "profile_image": None, "slug": None}
    return {
        "user_id": user_id,
        "stage_name": profile.get("stage_name") or f"{user.get('first_name','')} {user.get('last_name','')}".strip(),
        "category": profile.get("category", ""),
        "city": profile.get("city", ""),
        "profile_image": profile.get("profile_image"),
        "slug": profile.get("slug"),
    }


@api.post("/customer/booking-drafts")
async def upsert_booking_draft(body: BookingDraftBody, user: dict = Depends(get_current_user)):
    if user["role"] not in ("customer", "corporate"):
        raise HTTPException(403, "Only customers can save booking drafts")
    now = utcnow()
    snap = await _artist_snapshot(body.artist_id)
    payload = {
        "user_id": user["id"],
        "artist_id": body.artist_id,
        "form": body.form or {},
        "step": max(1, min(int(body.step or 1), 5)),
        "artist_snapshot": snap,
        "updated_at": now,
    }
    await db.booking_drafts.update_one(
        {"user_id": user["id"], "artist_id": body.artist_id},
        {"$set": payload, "$setOnInsert": {"id": new_id(), "created_at": now}},
        upsert=True,
    )
    return {"ok": True, "updated_at": now}


@api.get("/customer/booking-drafts")
async def list_booking_drafts(user: dict = Depends(get_current_user)):
    if user["role"] not in ("customer", "corporate"):
        return []
    docs = await db.booking_drafts.find({"user_id": user["id"]}).sort("updated_at", -1).to_list(30)
    return [clean(d) for d in docs]


@api.get("/customer/booking-drafts/{artist_id}")
async def get_booking_draft(artist_id: str, user: dict = Depends(get_current_user)):
    doc = await db.booking_drafts.find_one({"user_id": user["id"], "artist_id": artist_id})
    if not doc:
        raise HTTPException(404, "No draft for this artist")
    return clean(doc)


@api.delete("/customer/booking-drafts/{artist_id}")
async def delete_booking_draft(artist_id: str, user: dict = Depends(get_current_user)):
    r = await db.booking_drafts.delete_one({"user_id": user["id"], "artist_id": artist_id})
    return {"ok": True, "deleted": r.deleted_count}


@api.post("/customer/recent-views/{artist_id}")
async def record_recent_view(artist_id: str, user: dict = Depends(get_current_user)):
    # Only track for customers so we don't clutter artists/admins.
    if user["role"] not in ("customer", "corporate"):
        return {"ok": True, "tracked": False}
    now = utcnow()
    snap = await _artist_snapshot(artist_id)
    if not snap.get("stage_name"):
        return {"ok": True, "tracked": False}
    # Upsert — reset viewed_at so re-viewing the same artist bumps them up.
    await db.recent_views.update_one(
        {"user_id": user["id"], "artist_id": artist_id},
        {"$set": {"viewed_at": now, "artist_snapshot": snap},
         "$setOnInsert": {"id": new_id(), "user_id": user["id"], "artist_id": artist_id, "created_at": now}},
        upsert=True,
    )
    # Trim to the 8 most recent so the collection stays tiny per user.
    keep = await db.recent_views.find({"user_id": user["id"]}).sort("viewed_at", -1).skip(8).to_list(200)
    if keep:
        await db.recent_views.delete_many({"_id": {"$in": [k["_id"] for k in keep]}})
    return {"ok": True, "tracked": True}


@api.get("/customer/recent-views")
async def list_recent_views(user: dict = Depends(get_current_user)):
    if user["role"] not in ("customer", "corporate"):
        return []
    docs = await db.recent_views.find({"user_id": user["id"]}).sort("viewed_at", -1).limit(8).to_list(8)
    return [clean(d) for d in docs]





@api.get("/bookings/{bid}")
async def get_booking(bid: str, user: dict = Depends(get_current_user)):
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")
    if user["role"] != "admin" and user["id"] not in (doc["customer_id"], doc["artist_id"]):
        raise HTTPException(403, "Forbidden")
    artist = await db.users.find_one({"id": doc["artist_id"]})
    artist_p = await db.artist_profiles.find_one({"user_id": doc["artist_id"]})
    customer = await db.users.find_one({"id": doc["customer_id"]})

    # Iter 52.8 — Contact-details privacy gate.
    # Business rule: mobile number + email are exchanged ONLY after the
    # customer has settled the Platform Service Fee. Admins always see
    # everything. The redact-until-paid rule prevents artists from being
    # side-solicited before BookTalent has captured its fee, and protects
    # customer PII from artists who might reject the booking anyway.
    paid = (doc.get("payment_status") == "paid") or (doc.get("amount_paid", 0) > 0)
    redact_customer_contact = not paid and user["role"] == "artist"
    redact_artist_contact  = not paid and user["role"] in ("customer", "corporate", "agency")

    customer_clean = clean(customer) if customer else None
    artist_clean = clean(artist) if artist else None
    if customer_clean and redact_customer_contact:
        for k in ("phone", "email", "whatsapp", "alt_phone"):
            customer_clean.pop(k, None)
        customer_clean["_contact_locked"] = True
    if artist_clean and redact_artist_contact:
        for k in ("phone", "email", "whatsapp", "alt_phone"):
            artist_clean.pop(k, None)
        artist_clean["_contact_locked"] = True

    # Iter 53 — For artist viewers, strip platform-fee / GST / grand-total from
    # the pricing block AND the top-level booking fields the customer sees.
    booking_clean = clean(doc)
    if user["role"] == "artist":
        _redact_pricing_for_artist(booking_clean)
        # customer_phone / customer_email also live on the flat booking doc.
        if not paid:
            for k in ("customer_phone", "customer_email"):
                booking_clean.pop(k, None)
            booking_clean["_contact_locked"] = True

    return {
        "booking": booking_clean,
        "artist": artist_clean,
        "artist_profile": clean(artist_p) if artist_p else None,
        "customer": customer_clean,
        "contact_unlocked": paid,
    }


@api.post("/bookings/{bid}/action")
async def booking_action(bid: str, body: BookingStatusUpdate, user: dict = Depends(get_current_user)):
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")

    is_customer = user["id"] == doc["customer_id"]
    is_artist = user["id"] == doc["artist_id"]
    is_admin = user["role"] == "admin"

    new_status = doc["status"]
    history_entry = {"at": utcnow(), "action": body.action, "by": user["id"], "reason": body.reason}

    if body.action == "accept" and (is_artist or is_admin) and doc["status"] in ("pending_artist", "pending_payment"):
        new_status = "confirmed"
        await _create_contract(doc)
        # Auto-block the event date so no double-booking
        await db.availability.update_one(
            {"user_id": doc["artist_id"], "date": doc["event_date"]},
            {"$set": {"id": new_id(), "user_id": doc["artist_id"], "date": doc["event_date"], "status": "booked", "booking_id": doc["id"]}},
            upsert=True,
        )
        # Booking confirmation email to customer
        try:
            artist_p = await db.artist_profiles.find_one({"user_id": doc["artist_id"]}) or {}
            artist_u = await db.users.find_one({"id": doc["artist_id"]}) or {}
            artist_name = artist_p.get("stage_name") or f"{artist_u.get('first_name', '')} {artist_u.get('last_name', '')}".strip()
            # Build compact timeline snippet for the email body.
            try:
                from routes.req_batch_3 import build_email_timeline_html, fetch_booking_events
                _events = await fetch_booking_events(db, doc["id"])
                timeline_html = build_email_timeline_html(doc, _events)
            except Exception:
                timeline_html = ""
            await send_booking_confirmation_email(
                doc.get("customer_email") or "",
                doc.get("customer_name") or "",
                doc.get("ref", ""),
                artist_name,
                doc.get("event_date", ""),
                timeline_html=timeline_html,
            )
            # Smart notification: confirm both parties + admin via dispatcher
            await notify_dispatch(db, user_id=doc["customer_id"], event="booking.confirmed",
                channels=["in_app", "email", "whatsapp"],
                ctx={"title": "Booking confirmed", "body": f"Your booking {doc['ref']} with {artist_name} for {doc['event_date']} is confirmed.",
                     "artist_name": artist_name, "event_date": doc.get("event_date", ""), "ref": doc.get("ref", "")},
                email=doc.get("customer_email"),
                phone=doc.get("customer_phone"))
            await notify_dispatch(db, user_id=doc["artist_id"], event="booking.confirmed",
                channels=["in_app", "email", "whatsapp"],
                ctx={"title": "You accepted a booking", "body": f"Booking {doc['ref']} is now confirmed. Event: {doc['event_date']}",
                     "ref": doc.get("ref", ""), "event_date": doc.get("event_date", "")},
                email=artist_u.get("email"),
                phone=artist_u.get("phone"))
            # Notify all admins
            async for adm in db.users.find({"role": "admin"}, {"id": 1, "email": 1}):
                await notify_dispatch(db, user_id=adm["id"], event="booking.confirmed.admin",
                    channels=["in_app"],
                    ctx={"title": "New booking confirmed", "body": f"Booking {doc['ref']} confirmed: {artist_name} → {doc.get('customer_name', '')}"})
        except Exception as _e:
            log.warning("Confirmation email failed: %s", _e)
    elif body.action == "reject" and (is_artist or is_admin) and doc["status"] in ("pending_artist", "pending_payment"):
        new_status = "rejected"
        # Iter 64 — Automatic Easebuzz refund. The customer's Platform Service
        # Fee is refunded back to the original payment source with no admin
        # intervention. See _mark_platform_fee_refundable for idempotency logic.
        if doc.get("amount_paid", 0) > 0:
            await _mark_platform_fee_refundable(
                doc, "Artist rejected booking",
                actor=f"artist:{user['id']}" if is_artist else f"admin:{user['id']}",
            )
    elif body.action == "start" and is_artist and doc["status"] == "confirmed":
        new_status = "started"
    elif body.action == "complete" and is_artist and doc["status"] in ("confirmed", "started"):
        new_status = "completed_by_artist"
    elif body.action == "approve_completion" and (is_customer or is_admin) and doc["status"] in ("completed_by_artist", "completed"):
        new_status = "completed"
        # BookTalent is a lead-generation marketplace only — no artist wallet
        # settlement. We simply mark the booking complete and bump artist
        # stats. Artist Performance Fee is settled directly Customer ↔ Artist.
        await _record_completion(doc)
    elif body.action == "cancel" and (is_customer or is_admin or is_artist) and doc["status"] in ("pending_artist", "pending_payment", "confirmed"):
        # Iter 75.5 — Mandatory cancellation reason. Reject the request
        # (400) if the caller didn't supply a real reason. Enforced for
        # every actor role so the audit trail is always complete.
        reason_text = (body.reason or "").strip()
        if not reason_text:
            raise HTTPException(400, "Cancellation reason is required.")
        if len(reason_text) < 3:
            raise HTTPException(400, "Please provide a more descriptive reason (min 3 chars).")

        new_status = "cancelled"
        # Who cancelled? We derive from the acting user's role so the
        # customer branch can never sneak into the artist-refund path.
        actor_role = "artist" if is_artist else ("customer" if is_customer else "admin")
        # Persist cancellation metadata directly on the booking so admins,
        # customers and artists can all see WHO cancelled, WHY and WHEN
        # without having to trawl the history array.
        extra_updates = {
            "cancel_reason": reason_text,
            "cancelled_by": actor_role,
            "cancelled_by_user_id": user["id"],
            "cancelled_at": utcnow(),
        }

        # Iter 75 — Business rule: refunds are only owed to the customer when
        # the ARTIST (or admin acting on the artist's behalf) walks away from
        # a paid booking. A CUSTOMER-initiated cancellation of a paid booking
        # forfeits the Platform Service Fee — no refund is triggered.
        refund_note = f"Booking cancelled by {actor_role}: {reason_text}"
        if is_artist and doc.get("amount_paid", 0) > 0:
            await _mark_platform_fee_refundable(
                doc, refund_note, actor=f"artist:{user['id']}",
            )
        elif is_admin and doc.get("amount_paid", 0) > 0:
            # Admin overrides can go either way — treat as refund by default
            # so support can protect the customer when needed.
            await _mark_platform_fee_refundable(
                doc, refund_note, actor=f"admin:{user['id']}",
            )
        # Customer branch: intentionally no refund call. The extra_updates
        # above still record the reason so admins can audit forfeitures.
    else:
        raise HTTPException(400, "Action not allowed in current state")

    await db.bookings.update_one(
        {"id": bid},
        {"$set": {"status": new_status, "updated_at": utcnow(),
                  **(extra_updates if body.action == "cancel" and new_status == "cancelled" else {})},
         "$push": {"history": history_entry}},
    )

    # notifications
    notify_user = doc["customer_id"] if is_artist else doc["artist_id"]
    await db.notifications.insert_one({
        "id": new_id(), "user_id": notify_user, "type": "booking_update",
        "title": f"Booking {body.action}", "body": f"Booking {doc['ref']} → {new_status}",
        "read": False, "created_at": utcnow(), "link": f"/dashboard/bookings/{bid}",
    })

    return {"ok": True, "status": new_status}


def _format_travel_reqs(reqs: dict) -> str:
    """Sprint 4 — render travel/accommodation snapshot for the contract PDF."""
    if not reqs or not (
        reqs.get("travel_required") or reqs.get("accommodation_required")
        or reqs.get("meals_required") or reqs.get("local_transport_required")
        or reqs.get("travel_notes")
    ):
        return "  None specified.\n"
    lines = []
    if reqs.get("travel_required"):
        cls = reqs.get("flight_class") or "economy"
        lines.append(f"  Flight/Travel     : Yes ({cls}) for {reqs.get('team_size') or 1} person(s)")
    if reqs.get("accommodation_required"):
        cat = reqs.get("hotel_category") or "3-star"
        lines.append(f"  Accommodation     : Yes — {cat} hotel for {reqs.get('team_size') or 1} person(s)")
    if reqs.get("arrival_buffer_days"):
        lines.append(f"  Arrival buffer    : {reqs['arrival_buffer_days']} day(s) prior to event")
    if reqs.get("local_transport_required"):
        lines.append("  Local transport   : Required (airport pickup + venue transfers)")
    if reqs.get("meals_required"):
        lines.append("  Meals             : Required (all meals during stay)")
    if reqs.get("travel_notes"):
        lines.append(f"  Additional notes  : {reqs['travel_notes']}")
    return "\n".join(lines) + "\n"


async def _create_contract(booking: dict) -> str:
    cid = new_id()
    artist = await db.users.find_one({"id": booking["artist_id"]})
    artist_p = await db.artist_profiles.find_one({"user_id": booking["artist_id"]})

    # Pull admin-editable outstation clause + fee note from system_settings so
    # legal/policy tweaks don't require a redeploy.
    clause_doc = await db.system_settings.find_one({"key": "outstation_clause"})
    fee_note_doc = await db.system_settings.find_one({"key": "booking_fee_note"})
    outstation_clause = (clause_doc or {}).get("value") or (
        "For outstation bookings, all travel, accommodation, food, local "
        "transportation, hospitality and any additional logistics required for "
        "the Artist or accompanying team shall be arranged and paid separately "
        "by the Customer. These expenses are not included in the Artist "
        "Performance Fee or the Platform Service Fee."
    )
    fee_note = (fee_note_doc or {}).get("value") or (
        "Travel, accommodation, local transport, food, hospitality and any "
        "other outstation expenses are NOT included in the Artist Package Fee."
    )
    outstation_block = ""
    if booking.get("is_outstation"):
        outstation_block = (
            f"OUTSTATION LOGISTICS ({booking.get('artist_city') or '—'} → "
            f"{booking.get('event_city') or booking.get('city') or '—'}):\n"
            f"  {outstation_clause}\n\n"
        )

    body_text = f"""
BOOKTALENT ARTIST PERFORMANCE AGREEMENT

Booking Reference: {booking['ref']}
Date of Agreement: {datetime.now().strftime('%B %d, %Y')}

ARTIST: {artist_p.get('stage_name') if artist_p else (artist.get('first_name') + ' ' + artist.get('last_name', ''))}
CLIENT: {booking.get('customer_name')}

EVENT DETAILS:
  Event Type : {booking.get('event_type')}
  Date       : {booking.get('event_date')} at {booking.get('event_time')}
  Venue      : {booking.get('venue')}, {booking.get('city')}
  Package    : {booking.get('package_name')}

TRAVEL & ACCOMMODATION (borne by Client, in addition to the Artist Fee):
{_format_travel_reqs(booking.get('travel_requirements') or {})}{
    ("  Customer Travel Allowance offered (direct-to-artist) : ₹" + f"{float(booking.get('customer_travel_allowance') or 0):.2f}" + chr(10))
    if float(booking.get('customer_travel_allowance') or 0) > 0 else ""
}{outstation_block}{"SPECIAL INSTRUCTIONS FROM CLIENT:" + chr(10) + "  " + (booking.get("special_instructions") or "").strip() + chr(10) + chr(10) if (booking.get("special_instructions") or "").strip() else ""}FINANCIAL TERMS:
  Artist Performance Fee (paid by Client directly to Artist) : ₹{booking['pricing'].get('artist_fee', booking['pricing'].get('package_fee', 0) + booking['pricing'].get('addons_total', 0)):.2f}

  Platform Service Fee (5% — payable to BookTalent)          : ₹{booking['pricing']['platform_fee']:.2f}
  GST (18% on Platform Fee)                                  : ₹{booking['pricing']['gst']:.2f}
  AMOUNT PAYABLE TO BOOKTALENT                                : ₹{booking['pricing']['total']:.2f}

FEE INCLUSION NOTE:
  {fee_note}

STANDARD TERMS:
  1. BookTalent acts only as a technology platform facilitating the connection
     between the Customer and the Artist. The Artist Performance Fee shall be
     paid directly by the Customer to the Artist as mutually agreed.
     BookTalent shall NOT be responsible for the settlement of the
     Artist Performance Fee.
  2. The Artist agrees to perform as described above on the agreed date.
  3. The Client agrees to provide stage, sound, hospitality as per package rider.
  4. Cancellation by Client 15+ days prior: full refund of the Platform Service Fee.
  5. Cancellation by Client within 7 days: Platform Service Fee is non-refundable.
  6. Cancellation by Artist: 100% refund of Platform Service Fee + priority rebooking.
  7. Refund of any Artist Performance Fee already paid directly is governed by
     the mutual agreement between Customer and Artist.
  8. This contract is auto-generated and governed by BookTalent's Standard Agreement.

Digital signatures recorded electronically upon booking confirmation.
"""
    await db.contracts.insert_one({
        "id": cid,
        "booking_id": booking["id"],
        "artist_id": booking["artist_id"],
        "customer_id": booking["customer_id"],
        "ref": "CT-" + booking["ref"].split("-", 1)[1],
        "body": body_text,
        "status": "signed",  # auto-signed on accept
        "signed_at": utcnow(),
        "created_at": utcnow(),
    })
    await db.bookings.update_one({"id": booking["id"]}, {"$set": {"contract_id": cid}})
    return cid


async def _mark_platform_fee_refundable(booking: dict, note: str, actor: str = "system"):
    """
    Iter 64 — Automatic Easebuzz refund.

    When a booking is rejected / cancelled / auto-expired, we no longer wait
    for admin action. We call the Easebuzz refund API directly for every
    completed payment tied to the booking. Duplicate protection lives in
    `_auto_refund_payment_doc` (skips already-refunded rows).

    For legacy Razorpay / mock payments, we still write the ledger row so
    admin can see the "would-have-refunded" record.
    """
    # 1. Direct refund attempt for every Easebuzz-completed payment.
    try:
        refund_results = await auto_refund_bookings([booking["id"]], reason=note, actor=actor)
    except Exception as e:
        log.error("Auto-refund dispatch failed for %s: %s", booking.get("id"), e)
        refund_results = []

    # 2. Legacy mock/razorpay rows — flag for admin visibility only. Never
    #    triggers real money movement.
    await db.payments.update_many(
        {
            "booking_id": booking["id"],
            "status": "completed",
            "gateway": {"$ne": "easebuzz"},
        },
        {"$set": {"refund_pending": True, "refund_note": note,
                  "refund_flagged_at": utcnow(),
                  "refund_status": "not_applicable"}},
    )

    # 3. Audit trail on the customer ledger.
    await db.transactions.insert_one({
        "id": new_id(), "user_id": booking["customer_id"], "type": "refund_flagged",
        "amount": float(booking.get("amount_paid", 0)),
        "status": "processing",
        "description": note, "booking_id": booking["id"],
        "refund_results": refund_results, "created_at": utcnow(),
    })

    # 4. Bubble successes back to caller for testing/debugging.
    return refund_results


# ─── 24-Hour Artist Confirmation window — auto-expiry worker ─────────────
async def _auto_expire_bookings_once():
    """
    Runs on a schedule. Any booking that has been in `pending_artist` for
    longer than `confirmation_deadline_hours` (default 24) is auto-cancelled
    and the Platform Service Fee flagged for refund. Notifies customer + artist.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    stale = db.bookings.find({
        "status": {"$in": ["pending_artist", "pending_payment"]},
        "expires_at": {"$lte": now_iso},
    })
    async for doc in stale:
        try:
            await db.bookings.update_one(
                {"id": doc["id"], "status": {"$in": ["pending_artist", "pending_payment"]}},
                {"$set": {"status": "auto_expired", "expired_at": utcnow()},
                 "$push": {"history": {"at": utcnow(), "action": "auto_expired", "by": "system",
                                        "reason": "Artist did not confirm within 24 hours"}}},
            )
            if doc.get("amount_paid", 0) > 0:
                await _mark_platform_fee_refundable(
                    doc, "Artist did not accept booking within allowed timeline",
                    actor="system:auto_expire",
                )
            # Customer + artist notifications (in-app + email via dispatcher)
            try:
                artist_u = await db.users.find_one({"id": doc.get("artist_id")}) or {}
                await notify_dispatch(db, user_id=doc["customer_id"], event="booking.auto_expired",
                    channels=["in_app", "email"],
                    ctx={"title": "Booking request expired",
                         "body": f"Your booking request {doc.get('ref', '')} expired because the artist did not confirm within 24 hours. Your Platform Service Fee will be refunded within 5-7 business days.",
                         "ref": doc.get("ref", "")},
                    email=doc.get("customer_email"))
                await notify_dispatch(db, user_id=doc["artist_id"], event="booking.auto_expired",
                    channels=["in_app", "email"],
                    ctx={"title": "Booking request expired",
                         "body": f"Booking {doc.get('ref', '')} expired because you did not respond within 24 hours."},
                    email=artist_u.get("email"))
            except Exception as _e:
                log.warning("Auto-expire notify failed: %s", _e)
        except Exception as e:
            log.error("Auto-expire booking %s failed: %s", doc.get("id"), e)


async def _auto_expire_loop():
    """Background loop that ticks the auto-expiry check every N minutes."""
    interval_min = int(os.environ.get("BOOKING_EXPIRY_CHECK_MINUTES", "15"))
    log.info("Auto-expiry loop starting (every %d min)", interval_min)
    while True:
        try:
            await _auto_expire_bookings_once()
        except Exception as e:
            log.error("Auto-expiry tick failed: %s", e)
        # Iter 52.9 — Piggy-back subscription-expiry sweep on the same loop
        # so we don't spin up another cron. Flips active → expired past ETA,
        # downgrades premium_badge, and fires 7-day/1-day warning notices.
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            soon_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            async for s in db.artist_subscriptions.find({"status": "active", "expires_at": {"$lt": now_iso}}):
                await db.artist_subscriptions.update_one(
                    {"_id": s["_id"]},
                    {"$set": {"status": "expired", "expired_at": now_iso}},
                )
                await db.artist_profiles.update_one(
                    {"user_id": s["artist_id"]},
                    {"$set": {"premium_badge": False, "plan_code": "free", "plan_rank": 0}},
                )
                await db.notifications.insert_one({
                    "id": new_id(), "user_id": s["artist_id"], "type": "subscription",
                    "title": "Subscription expired",
                    "body": "Your subscription has expired. Renew to keep premium benefits.",
                    "read": False, "created_at": now_iso,
                })
            async for s in db.artist_subscriptions.find({"status": "active", "expires_at": {"$lte": soon_iso, "$gte": now_iso}}):
                try:
                    dt_exp = datetime.fromisoformat(s["expires_at"].replace("Z", "+00:00"))
                except Exception:
                    continue
                days = int((dt_exp - datetime.now(timezone.utc)).total_seconds() // 86400)
                marker = f"expiry_warn_{days}d_sent"
                if days in (7, 1) and not s.get(marker):
                    await db.artist_subscriptions.update_one({"_id": s["_id"]}, {"$set": {marker: True}})
                    await db.notifications.insert_one({
                        "id": new_id(), "user_id": s["artist_id"], "type": "subscription",
                        "title": f"Subscription expires in {days} day{'s' if days != 1 else ''}",
                        "body": "Renew now to avoid losing premium benefits.",
                        "read": False, "created_at": now_iso,
                    })
        except Exception as e:
            log.error("Subscription expiry sweep failed: %s", e)
        await asyncio.sleep(interval_min * 60)


async def _record_completion(booking: dict):
    """
    Marketplace model: BookTalent does NOT collect the Artist Performance Fee.
    That is settled directly Customer ↔ Artist. This helper just bumps artist
    stats and writes an informational ledger row.
    """
    artist_fee = float(booking["pricing"].get(
        "artist_fee",
        booking["pricing"].get("package_fee", 0)
        + booking["pricing"].get("addons_total", 0)
        - booking["pricing"].get("coupon_discount", 0),
    ))
    await db.transactions.insert_one({
        "id": new_id(), "user_id": booking["artist_id"], "type": "direct_settlement",
        "amount": artist_fee, "status": "informational",
        "description": f"Direct settlement from customer for booking {booking['ref']} (not processed by BookTalent)",
        "booking_id": booking["id"], "created_at": utcnow(),
    })
    await db.artist_profiles.update_one(
        {"user_id": booking["artist_id"]},
        {"$inc": {"events_done": 1}},
    )


# ─── Event-day reminder worker (Iter 79) ──────────────────────────────────
def _parse_hhmm(t: str) -> Optional[tuple]:
    """Parse ``HH:MM`` (or common variants) → ``(hour, minute)``. ``None`` on fail."""
    if not t:
        return None
    s = str(t).strip().lower().replace(".", ":")
    # strip AM/PM suffix
    ampm = None
    if s.endswith("am") or s.endswith("pm"):
        ampm = s[-2:]
        s = s[:-2].strip()
    parts = s.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return None
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h, m


def _compute_load_in(event_time: str, offset_minutes: int = 60) -> str:
    """Return a load-in HH:MM string ~1 hour before show time, or ``''`` on parse fail."""
    hm = _parse_hhmm(event_time)
    if not hm:
        return ""
    h, m = hm
    total = h * 60 + m - offset_minutes
    if total < 0:
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def _map_link(venue: str, city: str) -> str:
    q = quote_plus(f"{(venue or '').strip()}, {(city or '').strip()}".strip(", "))
    return f"https://www.google.com/maps/search/?api=1&query={q}"


async def _send_reminder_for_booking(doc: dict):
    """Fire reminder emails to both customer and artist for a single booking."""
    artist_u = await db.users.find_one({"id": doc.get("artist_id")}) or {}
    prof = await db.artist_profiles.find_one({"user_id": doc.get("artist_id")}) or {}
    artist_name = prof.get("stage_name") or f"{artist_u.get('first_name','')} {artist_u.get('last_name','')}".strip() or "your artist"
    customer_u = await db.users.find_one({"id": doc.get("customer_id")}) or {}
    load_in = _compute_load_in(doc.get("event_time") or "")
    map_link = _map_link(doc.get("venue") or "", doc.get("city") or "")

    tasks = []
    # Build a compact timeline snippet once for both audiences.
    try:
        from routes.req_batch_3 import build_email_timeline_html, fetch_booking_events
        _events = await fetch_booking_events(db, doc.get("id") or "")
        timeline_html = build_email_timeline_html(doc, _events)
    except Exception:
        timeline_html = ""
    cust_email = doc.get("customer_email") or customer_u.get("email")
    if cust_email:
        tasks.append(send_event_reminder_email(
            cust_email, customer_u.get("first_name") or "there", "customer",
            artist_name, doc.get("event_date") or "", doc.get("event_time") or "",
            load_in, doc.get("venue") or "", doc.get("city") or "",
            map_link, doc.get("ref") or "",
            timeline_html=timeline_html,
        ))
    if artist_u.get("email"):
        tasks.append(send_event_reminder_email(
            artist_u["email"], artist_u.get("first_name") or "there", "artist",
            artist_name, doc.get("event_date") or "", doc.get("event_time") or "",
            load_in, doc.get("venue") or "", doc.get("city") or "",
            map_link, doc.get("ref") or "",
            timeline_html=timeline_html,
        ))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    await db.bookings.update_one(
        {"id": doc["id"]},
        {"$set": {"reminder_sent_at": utcnow()},
         "$push": {"history": {"at": utcnow(), "action": "reminder_sent", "by": "system",
                                "reason": "Event-day reminder emailed to customer + artist"}}},
    )
    log.info("Event reminder sent for booking=%s event_date=%s", doc.get("ref"), doc.get("event_date"))


async def _event_reminder_tick():
    """Look for confirmed/started bookings whose event is today (IST) and whose
    reminder has not yet been sent, then only send once local IST time is
    past 07:00 so the email genuinely lands 'morning of'.
    """
    # BookTalent is India-first — all event dates are stored as YYYY-MM-DD in
    # the artist's local calendar (Asia/Kolkata). We use a fixed +5:30 offset
    # rather than pulling pytz just to avoid a new dep.
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if ist_now.hour < 7:
        return  # too early — wait for the next tick
    today_str = ist_now.strftime("%Y-%m-%d")

    cursor = db.bookings.find({
        "status": {"$in": ["confirmed", "started"]},
        "event_date": today_str,
        "reminder_sent_at": {"$in": [None, ""]},
    })
    async for doc in cursor:
        try:
            await _send_reminder_for_booking(doc)
        except Exception as e:  # noqa: BLE001
            log.error("Reminder for booking %s failed: %s", doc.get("id"), e)


async def _event_reminder_loop():
    """Check hourly. Cheap enough — a couple of index-backed queries and
    ~2 SMTP sends per event that day."""
    interval_min = int(os.environ.get("EVENT_REMINDER_CHECK_MINUTES", "60"))
    log.info("Event-reminder loop starting (every %d min, sends after 07:00 IST)", interval_min)
    while True:
        try:
            await _event_reminder_tick()
        except Exception as e:  # noqa: BLE001
            log.error("Event-reminder tick failed: %s", e)
        await asyncio.sleep(interval_min * 60)


@api.post("/admin/bookings/{booking_id}/send-reminder")
async def admin_send_reminder(booking_id: str, admin: dict = Depends(require_permission("bookings.view"))):
    """Iter 79 — Admin-only manual trigger. Useful for testing the reminder
    email + resending if a customer/artist reports they didn't receive it.
    Does NOT check the 07:00-IST gate and does NOT check ``event_date``, so
    admins can dry-run any booking's reminder email on demand.
    """
    doc = await db.bookings.find_one({"id": booking_id})
    if not doc:
        raise HTTPException(404, "Booking not found")
    await _send_reminder_for_booking(doc)
    return {"ok": True, "booking_ref": doc.get("ref"), "event_date": doc.get("event_date")}


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENTS — Easebuzz-only (Iter 64)
# All payment init/verify/refund/webhook endpoints now live in routes/easebuzz.py.
# Legacy /payments/config, /payments/init, /payments/verify, /payments/webhook
# and manual /payments/{id}/refund removed as part of Razorpay cleanup.
# Frontend must call /api/payments/easebuzz/init and rely on the automatic
# refund flow triggered from booking action (reject/cancel/auto-expire).
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────
# ── Reviews endpoints moved to routes/reviews.py (Iter 13) ───────────────────


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS / MESSAGES
# ─────────────────────────────────────────────────────────────────────────────
@api.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    docs = await db.notifications.find({"user_id": user["id"]}).sort("created_at", -1).limit(50).to_list(50)
    return [clean(d) for d in docs]


@api.post("/notifications/read-all")
async def read_all_notifications(user: dict = Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/notifications/{nid}/read")
async def read_notification(nid: str, user: dict = Depends(get_current_user)):
    await db.notifications.update_one({"id": nid, "user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/messages")
async def send_message(body: MessageBody, user: dict = Depends(get_current_user)):
    mid = new_id()
    # find or create conversation
    convo = await db.conversations.find_one({"participants": {"$all": [user["id"], body.to_user_id]}})
    if not convo:
        cid = new_id()
        await db.conversations.insert_one({
            "id": cid, "participants": [user["id"], body.to_user_id],
            "booking_id": body.booking_id, "last_message": body.text,
            "created_at": utcnow(), "updated_at": utcnow(),
        })
    else:
        cid = convo["id"]
        await db.conversations.update_one({"id": cid}, {"$set": {"last_message": body.text, "updated_at": utcnow()}})

    await db.messages.insert_one({
        "id": mid, "conversation_id": cid, "from_user_id": user["id"], "to_user_id": body.to_user_id,
        "text": body.text, "booking_id": body.booking_id, "read": False, "created_at": utcnow(),
    })
    await db.notifications.insert_one({
        "id": new_id(), "user_id": body.to_user_id, "type": "message",
        "title": "New message", "body": body.text[:80], "read": False, "created_at": utcnow(),
        "link": "/dashboard/messages",
    })
    return {"id": mid, "conversation_id": cid}


@api.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    docs = await db.conversations.find({"participants": user["id"]}).sort("updated_at", -1).to_list(100)
    # enrich with other party name
    out = []
    for c in docs:
        other_id = [p for p in c["participants"] if p != user["id"]][0] if len(c["participants"]) > 1 else user["id"]
        other = await db.users.find_one({"id": other_id})
        unread = await db.messages.count_documents({"conversation_id": c["id"], "to_user_id": user["id"], "read": False})
        out.append({**clean(c), "other": clean(other), "unread": unread})
    return out


@api.get("/conversations/{cid}/messages")
async def conversation_messages(cid: str, user: dict = Depends(get_current_user)):
    convo = await db.conversations.find_one({"id": cid})
    if not convo or user["id"] not in convo["participants"]:
        raise HTTPException(403, "Forbidden")
    msgs = await db.messages.find({"conversation_id": cid}).sort("created_at", 1).to_list(500)
    # mark received as read
    await db.messages.update_many({"conversation_id": cid, "to_user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return [clean(m) for m in msgs]


# ─────────────────────────────────────────────────────────────────────────────
# KYC — moved to routes/kyc.py (Iter 13)
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────────────────────
@api.get("/admin/stats")
async def admin_stats(_: dict = Depends(require_permission("analytics.view"))):
    # BookTalent is a lead-generation marketplace. We surface the marketplace
    # volume (artist fees — informational) and, most importantly, what the
    # platform actually collects: Platform Service Fee + GST.
    total_gmv = 0.0          # marketplace volume (artist fees only — not BT revenue)
    platform_rev = 0.0       # what BT invoiced (platform_fee only — net of GST)
    gst_collected = 0.0
    async for b in db.bookings.find({"status": {"$in": ["confirmed", "completed", "reviewed", "started", "completed_by_artist"]}}):
        p = b.get("pricing", {}) or {}
        total_gmv += float(p.get("artist_fee", p.get("package_fee", 0) + p.get("addons_total", 0)))
        platform_rev += float(p.get("platform_fee", 0))
        gst_collected += float(p.get("gst", 0))

    # Subscription + boost revenue — direct platform income streams.
    subs_rev = 0.0
    async for s in db.subscriptions.find({"status": {"$in": ["active", "expired"]}}):
        subs_rev += float(s.get("price_paid", 0) or s.get("price", 0) or 0)
    boost_rev = 0.0
    async for bs in db.boost_subscriptions.find({"status": {"$in": ["active", "expired"]}}):
        boost_rev += float(bs.get("price_paid", 0) or (bs.get("package_snapshot") or {}).get("price", 0) or 0)

    total_bookings = await db.bookings.count_documents({})
    pending_bookings = await db.bookings.count_documents({"status": {"$in": ["pending_artist", "pending_payment"]}})
    today = datetime.now().strftime("%Y-%m-%d")
    bookings_today = await db.bookings.count_documents({"created_at": {"$gte": today}})
    total_users = await db.users.count_documents({})
    total_artists = await db.users.count_documents({"role": "artist"})
    total_customers = await db.users.count_documents({"role": "customer"})
    open_disputes = await db.disputes.count_documents({"status": "open"})
    pending_refunds = await db.payments.count_documents({"refund_pending": True, "status": "completed"})
    pending_kyc = await db.kyc_submissions.count_documents({"status": "pending"})

    # avg rating
    avgs = await db.artist_profiles.find({"rating_avg": {"$gt": 0}}).to_list(1000)
    avg_rating = (sum(a["rating_avg"] for a in avgs) / len(avgs)) if avgs else 0

    # ── Feb 2026 requirement batch — Founder-visible KPIs ─────────
    now_iso = datetime.now(timezone.utc).isoformat()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_leads = await db.leads.count_documents({"stage": {"$in": ["new", "new_lead", "qualification"]}})
    active_bookings = await db.bookings.count_documents({"status": {"$in": ["confirmed", "started"]}})
    upcoming_events = await db.bookings.count_documents({
        "status": {"$in": ["confirmed", "started"]},
        "event_date": {"$gte": today_str},
    })
    agreements_pending = await db.artist_profiles.count_documents({"kyc_status": {"$in": ["kyc_approved", "tnc_pending"]}})
    customer_payment_pending = await db.bookings.count_documents({
        "status": {"$in": ["confirmed", "pending_payment"]},
        "payment_status": {"$in": ["pending", "partial"]},
    })
    overdue_payments = await db.bookings.count_documents({
        "payment_status": {"$in": ["pending", "partial", "overdue"]},
        "event_date": {"$lt": today_str},
    })
    payout_pending = await db.bookings.count_documents({
        "payment_status": {"$in": ["partial", "paid", "fully_paid"]},
        "$or": [
            {"artist_payout_status": {"$ne": "paid"}},
            {"artist_payout_status": {"$exists": False}},
        ],
    })
    agency_bookings = await db.bookings.count_documents({"agency_id": {"$exists": True, "$ne": None}})

    # Remaining amount across active bookings (Total − paid_amount)
    remaining_total = 0.0
    async for b in db.bookings.find(
        {"status": {"$in": ["confirmed", "started"]}},
        {"_id": 0, "pricing": 1, "paid_amount": 1},
    ):
        p = b.get("pricing") or {}
        total = float(p.get("total") or 0)
        paid = float(b.get("paid_amount") or 0)
        remaining_total += max(0.0, total - paid)

    return {
        "gmv": total_gmv,                       # marketplace artist-fee volume (informational)
        "platform_revenue": round(platform_rev, 2),  # BookTalent net platform fee earnings
        "gst_collected": round(gst_collected, 2),
        "subscription_revenue": round(subs_rev, 2),
        "boost_revenue": round(boost_rev, 2),
        "bookTalent_total_collected": round(platform_rev + gst_collected + subs_rev + boost_rev, 2),
        "total_bookings": total_bookings,
        "pending_bookings": pending_bookings,
        "bookings_today": bookings_today,
        "total_users": total_users,
        "total_artists": total_artists,
        "total_customers": total_customers,
        "open_disputes": open_disputes,
        "pending_refunds": pending_refunds,
        "pending_kyc": pending_kyc,
        "avg_rating": round(avg_rating, 2),
        # Feb-2026 requirement KPIs
        "new_leads": new_leads,
        "active_bookings": active_bookings,
        "upcoming_events": upcoming_events,
        "agreements_pending": agreements_pending,
        "customer_payment_pending": customer_payment_pending,
        "overdue_payments": overdue_payments,
        "artist_payout_pending": payout_pending,
        "agency_bookings": agency_bookings,
        "remaining_amount": round(remaining_total, 2),
    }


@api.get("/admin/artists")
async def admin_list_artists(status: Optional[str] = None, _: dict = Depends(require_permission("artists.moderate"))):
    q: dict = {}
    if status == "pending":
        q["kyc_status"] = "pending"
    elif status == "verified":
        q["kyc_status"] = "approved"
    elif status == "featured":
        q["is_featured"] = True
    docs = await db.artist_profiles.find(q).to_list(500)
    out = []
    for p in docs:
        p = clean(p)
        u = await db.users.find_one({"id": p["user_id"]})
        p["user"] = clean(u) if u else None
        out.append(p)
    return out


@api.get("/admin/bookings")
async def admin_bookings(status: Optional[str] = None, _: dict = Depends(admin_only)):
    q: dict = {} if not status else {"status": status}
    docs = await db.bookings.find(q).sort("created_at", -1).to_list(500)
    return [clean(d) for d in docs]


# ── Admin 24-Hr Confirmation window overrides ────────────────────────────
class _BookingOverride(BaseModel):
    hours: Optional[int] = None
    reason: Optional[str] = None


@api.post("/admin/bookings/{bid}/extend")
async def admin_booking_extend(bid: str, body: _BookingOverride, admin: dict = Depends(admin_only)):
    """Extend the 24-hour Artist Confirmation window by `hours`."""
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["status"] not in ("pending_artist", "pending_payment"):
        raise HTTPException(400, "Booking is not pending confirmation")
    hours = max(1, int(body.hours or 24))
    current_expiry = doc.get("expires_at")
    try:
        base = datetime.fromisoformat(current_expiry) if current_expiry else datetime.now(timezone.utc)
    except Exception:
        base = datetime.now(timezone.utc)
    new_expiry = (base + timedelta(hours=hours)).isoformat()
    await db.bookings.update_one({"id": bid}, {
        "$set": {"expires_at": new_expiry},
        "$push": {"history": {"at": utcnow(), "action": "admin_extend", "by": admin["id"],
                               "hours": hours, "reason": body.reason or ""}},
    })
    return {"ok": True, "expires_at": new_expiry, "extended_by_hours": hours}


@api.post("/admin/bookings/{bid}/force-accept")
async def admin_booking_force_accept(bid: str, body: _BookingOverride, admin: dict = Depends(admin_only)):
    """Admin forces booking into Confirmed state on artist's behalf."""
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["status"] not in ("pending_artist", "pending_payment"):
        raise HTTPException(400, "Booking is not pending confirmation")
    await db.bookings.update_one({"id": bid}, {
        "$set": {"status": "confirmed", "confirmed_at": utcnow(), "confirmed_by_admin": True},
        "$push": {"history": {"at": utcnow(), "action": "admin_force_accept", "by": admin["id"],
                               "reason": body.reason or ""}},
    })
    await _create_contract(doc)
    await db.availability.update_one(
        {"user_id": doc["artist_id"], "date": doc["event_date"]},
        {"$set": {"id": new_id(), "user_id": doc["artist_id"], "date": doc["event_date"],
                  "status": "booked", "booking_id": doc["id"]}},
        upsert=True,
    )
    return {"ok": True, "status": "confirmed"}


@api.post("/admin/bookings/{bid}/force-reject")
async def admin_booking_force_reject(bid: str, body: _BookingOverride, admin: dict = Depends(admin_only)):
    """Admin forces booking into Rejected state; Platform Service Fee flagged for refund."""
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["status"] not in ("pending_artist", "pending_payment", "confirmed"):
        raise HTTPException(400, "Booking cannot be force-rejected in its current state")
    await db.bookings.update_one({"id": bid}, {
        "$set": {"status": "rejected", "rejected_at": utcnow(), "rejected_by_admin": True},
        "$push": {"history": {"at": utcnow(), "action": "admin_force_reject", "by": admin["id"],
                               "reason": body.reason or ""}},
    })
    if doc.get("amount_paid", 0) > 0:
        await _mark_platform_fee_refundable(doc, body.reason or f"Admin force-reject for {doc.get('ref', bid)}")
    return {"ok": True, "status": "rejected"}


@api.post("/admin/bookings/{bid}/manual-refund")
async def admin_booking_manual_refund(bid: str, body: _BookingOverride, admin: dict = Depends(admin_only)):
    """
    Admin manually flags a booking's payment for refund. Actual money-back is
    processed via the Razorpay refund API (or manual bank transfer in mock mode).
    """
    doc = await db.bookings.find_one({"id": bid})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc.get("amount_paid", 0) <= 0:
        raise HTTPException(400, "No amount was collected for this booking")
    await _mark_platform_fee_refundable(doc, body.reason or f"Manual refund by admin for {doc.get('ref', bid)}")
    await db.bookings.update_one({"id": bid}, {
        "$push": {"history": {"at": utcnow(), "action": "admin_manual_refund", "by": admin["id"],
                               "reason": body.reason or ""}},
    })
    return {"ok": True, "refund_pending": True}


@api.get("/admin/users")
async def admin_users(role: Optional[str] = None, include_deleted: bool = False, _: dict = Depends(require_permission("users.view"))):
    q: dict = {} if not role else {"role": role}
    if not include_deleted:
        q["deleted"] = {"$ne": True}
    docs = await db.users.find(q).sort("created_at", -1).to_list(500)
    return [clean(d) for d in docs]


# ═══════════════════════════════════════════════════════════════════════════
# Iter 55 — Admin RBAC: multiple admins with per-permission access control
# ═══════════════════════════════════════════════════════════════════════════
class AdminCreateBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    admin_role: str = "viewer"          # one of ADMIN_ROLE_PRESETS or "custom"
    admin_permissions: Optional[List[str]] = None  # required when admin_role == "custom"


class AdminUpdateBody(BaseModel):
    admin_role: Optional[str] = None
    admin_permissions: Optional[List[str]] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)      # super-admin can reset another admin's password


@api.get("/admin/rbac/roles")
async def admin_rbac_roles(_: dict = Depends(admin_only)):
    """List all available permissions + preset roles. Any admin can read this
    so the UI can render permission checklists — write endpoints are still gated."""
    return {
        "permissions": ADMIN_PERMISSIONS,
        "role_presets": await get_role_presets(),
    }


@api.get("/admin/rbac/me")
async def admin_rbac_me(admin: dict = Depends(admin_only)):
    """Return the caller's own RBAC permissions so the frontend can hide
    modules the current admin doesn't have access to."""
    if admin.get("admin_role") == "super_admin":
        perms = ADMIN_PERMISSIONS
    else:
        perms = admin.get("admin_permissions") or ADMIN_PERMISSIONS
    return {
        "admin_role": admin.get("admin_role", "super_admin"),
        "admin_permissions": perms,
    }


# ══════════════ Iter 56 — DB-backed role preset CRUD ══════════════════════
class RolePresetBody(BaseModel):
    id: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    permissions: List[str]


@api.get("/admin/roles")
async def admin_list_roles(_: dict = Depends(require_permission("admins.manage"))):
    presets = await get_role_presets()
    return [{"id": rid, "permissions": perms, "readonly": rid == "super_admin"}
            for rid, perms in presets.items()]


@api.post("/admin/roles")
async def admin_create_role(body: RolePresetBody, admin: dict = Depends(require_permission("admins.manage"))):
    if body.id == "custom":
        raise HTTPException(400, "'custom' is a reserved role id")
    if await db.admin_roles.find_one({"id": body.id}):
        raise HTTPException(400, "Role id already exists")
    perms = [p for p in body.permissions if p in ADMIN_PERMISSIONS]
    await db.admin_roles.insert_one({"id": body.id, "permissions": perms, "created_at": utcnow()})
    await audit_log(admin, "role.create", meta={"role_id": body.id, "permissions": perms})
    return {"ok": True, "id": body.id, "permissions": perms}


@api.patch("/admin/roles/{rid}")
async def admin_update_role(rid: str, body: RolePresetBody, admin: dict = Depends(require_permission("admins.manage"))):
    if rid == "super_admin":
        raise HTTPException(400, "super_admin permissions are hard-coded and cannot be edited")
    if rid != body.id:
        raise HTTPException(400, "Role id in URL and body must match")
    perms = [p for p in body.permissions if p in ADMIN_PERMISSIONS]
    result = await db.admin_roles.update_one(
        {"id": rid},
        {"$set": {"permissions": perms, "updated_at": utcnow()}},
        upsert=True,
    )
    await audit_log(admin, "role.update", meta={"role_id": rid, "permissions": perms})
    return {"ok": True, "permissions": perms, "upserted": bool(result.upserted_id)}


@api.delete("/admin/roles/{rid}")
async def admin_delete_role(rid: str, admin: dict = Depends(require_permission("admins.manage"))):
    if rid == "super_admin":
        raise HTTPException(400, "super_admin role is protected")
    # If any admin still holds this role, refuse — force reassignment first.
    in_use = await db.users.count_documents({"role": "admin", "admin_role": rid, "deleted": {"$ne": True}})
    if in_use:
        raise HTTPException(400, f"{in_use} admin(s) still hold this role. Reassign them first.")
    result = await db.admin_roles.delete_one({"id": rid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Role not found")
    await audit_log(admin, "role.delete", meta={"role_id": rid})
    return {"ok": True}


# ══════════════ Iter 56 — Audit log endpoint ══════════════════════════════
@api.get("/admin/audit-log")
async def admin_audit_log_list(
    action: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 200,
    _: dict = Depends(require_permission("admins.manage")),
):
    q: dict = {}
    if action:
        q["action"] = action
    if actor_id:
        q["actor_id"] = actor_id
    docs = await db.admin_audit_log.find(q).sort("created_at", -1).limit(min(limit, 500)).to_list(500)
    return [clean(d) for d in docs]


@api.get("/admin/admins")
async def admin_list_admins(_: dict = Depends(require_permission("admins.manage"))):
    # Iter 76.6 — Latest admin first (matches every other chronological
    # list in the app: newest entry on top).
    docs = await db.users.find({"role": "admin", "deleted": {"$ne": True}}).sort("created_at", -1).to_list(200)
    return [{
        "id": d["id"],
        "email": d["email"],
        "first_name": d.get("first_name"),
        "last_name": d.get("last_name"),
        "admin_role": d.get("admin_role") or "super_admin",  # legacy = super
        "admin_permissions": d.get("admin_permissions") or ADMIN_PERMISSIONS,
        "active": not d.get("suspended", False),
        "created_at": d.get("created_at"),
    } for d in docs]


@api.post("/admin/admins")
async def admin_create_admin(body: AdminCreateBody, super_admin: dict = Depends(require_permission("admins.manage"))):
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already in use")

    presets = await get_role_presets()
    # Resolve permission set: preset role OR explicit permission list.
    if body.admin_role == "custom":
        if not body.admin_permissions:
            raise HTTPException(400, "admin_permissions required for custom role")
        permissions = [p for p in body.admin_permissions if p in ADMIN_PERMISSIONS]
    elif body.admin_role in presets:
        permissions = presets[body.admin_role]
    else:
        raise HTTPException(400, f"Unknown role '{body.admin_role}'")

    # Only super_admin can mint another super_admin (belt-and-braces beyond
    # the require_permission gate — 'admins.manage' is the same key).
    if body.admin_role == "super_admin" and super_admin.get("admin_role") != "super_admin":
        raise HTTPException(403, "Only a super admin can create another super admin")

    doc = {
        "id": new_id(),
        "email": email,
        "password_hash": hash_password(body.password),
        "first_name": (body.first_name or "").strip() or "Admin",
        "last_name": (body.last_name or "").strip() or "",
        "role": "admin",
        "admin_role": body.admin_role,
        "admin_permissions": permissions,
        "kyc_status": "approved",
        "verified": True,
        "created_by_admin_id": super_admin["id"],
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    await db.users.insert_one(doc)
    await audit_log(super_admin, "admin.create",
                    target={"id": doc["id"], "email": doc["email"], "admin_role": doc["admin_role"]},
                    meta={"permissions": permissions})
    return {
        "id": doc["id"], "email": doc["email"], "admin_role": doc["admin_role"],
        "admin_permissions": doc["admin_permissions"], "active": True,
    }


@api.patch("/admin/admins/{uid}")
async def admin_update_admin(uid: str, body: AdminUpdateBody, super_admin: dict = Depends(require_permission("admins.manage"))):
    target = await db.users.find_one({"id": uid, "role": "admin"})
    if not target:
        raise HTTPException(404, "Admin not found")
    if uid == super_admin["id"] and body.admin_role and body.admin_role != "super_admin":
        raise HTTPException(400, "You cannot demote yourself. Ask another super admin to do it.")

    presets = await get_role_presets()
    updates: Dict[str, Any] = {"updated_at": utcnow()}
    audit_meta: dict = {}
    audit_action = "admin.update"
    if body.admin_role is not None:
        if body.admin_role == "custom":
            if body.admin_permissions is None:
                raise HTTPException(400, "admin_permissions required for custom role")
        elif body.admin_role in presets:
            updates["admin_permissions"] = presets[body.admin_role]
        elif body.admin_role == "super_admin":
            if super_admin.get("admin_role") != "super_admin":
                raise HTTPException(403, "Only a super admin can grant super_admin")
            updates["admin_permissions"] = ADMIN_PERMISSIONS
        else:
            raise HTTPException(400, f"Unknown role '{body.admin_role}'")
        updates["admin_role"] = body.admin_role
        audit_meta["role_from"] = target.get("admin_role")
        audit_meta["role_to"] = body.admin_role

    if body.admin_permissions is not None:
        updates["admin_permissions"] = [p for p in body.admin_permissions if p in ADMIN_PERMISSIONS]
        audit_meta["permissions"] = updates["admin_permissions"]

    if body.active is not None:
        # Prevent locking yourself out of the last super_admin seat.
        if not body.active and uid == super_admin["id"]:
            raise HTTPException(400, "You cannot deactivate yourself")
        updates["suspended"] = not body.active
        audit_action = "admin.reactivate" if body.active else "admin.suspend"

    if body.password:
        updates["password_hash"] = hash_password(body.password)
        # Password resets deserve their own audit action for compliance.
        await audit_log(super_admin, "admin.password_reset",
                        target={"id": target["id"], "email": target["email"], "admin_role": target.get("admin_role")})

    await db.users.update_one({"id": uid}, {"$set": updates})
    if audit_meta or body.active is not None:
        await audit_log(super_admin, audit_action,
                        target={"id": target["id"], "email": target["email"], "admin_role": target.get("admin_role")},
                        meta=audit_meta)
    return {"ok": True}


@api.delete("/admin/admins/{uid}")
async def admin_delete_admin(uid: str, super_admin: dict = Depends(require_permission("admins.manage"))):
    if uid == super_admin["id"]:
        raise HTTPException(400, "You cannot delete yourself")
    target = await db.users.find_one({"id": uid, "role": "admin"})
    if not target:
        raise HTTPException(404, "Admin not found")
    # Guard the last super admin — refuse to delete if it's the only one.
    if target.get("admin_role") == "super_admin":
        remaining = await db.users.count_documents({"role": "admin", "admin_role": "super_admin", "id": {"$ne": uid}, "deleted": {"$ne": True}})
        if remaining == 0:
            raise HTTPException(400, "Cannot delete the last super admin. Promote another admin first.")
    await db.users.update_one({"id": uid}, {"$set": {"deleted": True, "suspended": True, "updated_at": utcnow()}})
    await audit_log(super_admin, "admin.delete",
                    target={"id": target["id"], "email": target["email"], "admin_role": target.get("admin_role")})
    return {"ok": True}


# /admin/kyc and /admin/kyc/decide moved to routes/kyc.py (Iter 13)


@api.post("/admin/artists/{user_id}/feature")
async def admin_feature(user_id: str, _: dict = Depends(require_permission("artists.moderate"))):
    a = await db.artist_profiles.find_one({"user_id": user_id})
    if not a:
        raise HTTPException(404, "Not found")
    await db.artist_profiles.update_one({"user_id": user_id}, {"$set": {"is_featured": not a.get("is_featured", False)}})
    return {"ok": True}


@api.post("/admin/artists/{user_id}/suspend")
async def admin_suspend(user_id: str, _: dict = Depends(require_permission("users.suspend"))):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "Not found")
    suspended = not u.get("suspended", False)
    # Iter 52.8 — Mirror the suspension flag onto artist_profiles so the
    # public search/featured/quote/spotlight queries can filter it out with a
    # single index-friendly clause (`suspended: {$ne: true}`). Without this
    # mirror the flag lived only on `users` and every public read continued
    # to surface a suspended artist — the exact bug the user just reported.
    await db.users.update_one({"id": user_id}, {"$set": {"suspended": suspended}})
    await db.artist_profiles.update_one({"user_id": user_id}, {"$set": {"suspended": suspended}})
    return {"ok": True, "suspended": suspended}


# ─── Admin: edit / delete any user (Iter 40) ─────────────────────────────────
class AdminUserEditBody(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[Literal["customer", "artist", "agency", "corporate", "admin"]] = None
    # Artist-profile-only fields
    stage_name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    starting_price: Optional[float] = None
    bio: Optional[str] = None


@api.put("/admin/users/{user_id}")
async def admin_edit_user(user_id: str, body: AdminUserEditBody, _: dict = Depends(require_permission("users.edit"))):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User not found")

    user_updates: Dict[str, Any] = {}
    for k in ("first_name", "last_name", "phone", "role"):
        v = getattr(body, k)
        if v is not None:
            user_updates[k] = v
    if body.email is not None:
        e = body.email.strip().lower()
        clash = await db.users.find_one({"email": e, "id": {"$ne": user_id}})
        if clash:
            raise HTTPException(400, "Email already in use")
        user_updates["email"] = e
    if user_updates:
        user_updates["updated_at"] = utcnow()
        await db.users.update_one({"id": user_id}, {"$set": user_updates})

    profile_updates: Dict[str, Any] = {}
    for k in ("stage_name", "category", "city", "starting_price", "bio"):
        v = getattr(body, k)
        if v is not None:
            profile_updates[k] = v
    if profile_updates and (u.get("role") == "artist" or body.role == "artist"):
        profile_updates["updated_at"] = utcnow()
        await db.artist_profiles.update_one({"user_id": user_id}, {"$set": profile_updates})
        # Keep SEO slug fresh when identifying fields change.
        if any(k in profile_updates for k in ("stage_name", "category", "city")):
            from routes.cms_seo import artist_slug as _mk_slug
            prof = await db.artist_profiles.find_one({"user_id": user_id}) or {}
            if prof.get("stage_name"):
                await db.artist_profiles.update_one(
                    {"user_id": user_id}, {"$set": {"slug": _mk_slug(prof)}}
                )
    return {"ok": True}


@api.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, hard: bool = False, admin: dict = Depends(require_permission("users.delete"))):
    """
    Delete a user account.
      • hard=false  → soft delete: mark deleted + anonymise email, keep history
      • hard=true   → wipe the user + role profile + owned artifacts. Bookings
                      are preserved (foreign-key value only) so financial
                      records stay intact.
    Admins cannot delete themselves.
    """
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot delete your own admin account")
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(404, "User not found")

    if not hard:
        await db.users.update_one(
            {"id": user_id},
            {"$set": {
                "suspended": True,
                "deleted": True,
                "deleted_at": utcnow(),
                "email": f"deleted-{user_id[:8]}@booktalent.deleted",
            }},
        )
        return {"ok": True, "mode": "soft"}

    # Hard delete — remove user document + role-specific data.
    await db.users.delete_one({"id": user_id})
    for coll in ("artist_profiles", "agencies", "corporate_profiles", "customer_profiles",
                 "kyc_submissions", "subscriptions", "boost_subscriptions",
                 "packages", "media", "notifications", "announcement_reads",
                 "reviews", "onboarding_progress"):
        try:
            await db[coll].delete_many({"user_id": user_id})
        except Exception:
            pass
    # Reviews referencing the user by artist_id
    await db.reviews.delete_many({"artist_id": user_id})
    return {"ok": True, "mode": "hard"}


@api.get("/admin/refunds/legacy-flagged")
async def admin_refunds_legacy(_: dict = Depends(require_permission("payments.view"))):
    """Legacy list of payments flagged for admin refund (razorpay_mock rows).
    New auto-refunds are handled via /admin/refunds (routes/easebuzz.py)."""
    docs = await db.payments.find({"refund_pending": True, "status": "completed"}).sort("refund_flagged_at", -1).to_list(500)
    out = []
    for d in docs:
        d = clean(d)
        u = await db.users.find_one({"id": d.get("user_id")})
        d["user"] = clean(u) if u else None
        out.append(d)
    return out


# COUPONS
async def _validate_coupon(code: str, *, user_id: str, base_amount: float, event_type: Optional[str] = None) -> tuple[dict, float]:
    """Returns (coupon_doc, discount_amount) or raises 400."""
    c = await db.coupons.find_one({"code": code.upper()})
    if not c:
        raise HTTPException(404, "Invalid coupon code")
    if not c.get("active", False):
        raise HTTPException(400, "Coupon is inactive")
    # Expiry
    try:
        exp = c.get("expires_at", "")
        if exp and exp < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            raise HTTPException(400, "Coupon has expired")
    except HTTPException:
        raise
    except Exception:
        pass
    # Min order
    if base_amount < float(c.get("min_order", 0)):
        raise HTTPException(400, f"Order must be at least ₹{c.get('min_order', 0)} to use this coupon")
    # Max uses
    if c.get("usage_count", 0) >= int(c.get("max_uses", 1000)):
        raise HTTPException(400, "Coupon usage limit reached")
    # Per-user limit
    per_user_used = await db.coupon_redemptions.count_documents({"coupon_id": c["id"], "user_id": user_id})
    if per_user_used >= int(c.get("per_user_limit", 1)):
        raise HTTPException(400, "You've already used this coupon the maximum number of times")
    # applies_to
    applies_to = c.get("applies_to", "all")
    if applies_to != "all" and event_type and applies_to.lower() != event_type.lower():
        raise HTTPException(400, f"Coupon valid only for {applies_to} bookings")
    # Compute discount
    if c["discount_type"] == "percent":
        discount = round(base_amount * float(c["discount_value"]) / 100, 2)
    else:
        discount = float(c["discount_value"])
    discount = min(discount, base_amount)  # never exceed base
    return c, discount


# ── Coupons / Blogs / Disputes endpoints moved to routes/ (Iter 13) ──────────


# CONTRACTS
@api.get("/contracts/mine")
async def my_contracts(user: dict = Depends(get_current_user)):
    if user["role"] == "admin":
        q = {}
    elif user["role"] == "artist":
        q = {"artist_id": user["id"]}
    else:
        q = {"customer_id": user["id"]}
    docs = await db.contracts.find(q).sort("created_at", -1).to_list(500)
    return [clean(d) for d in docs]


@api.get("/contracts/{cid}")
async def get_contract(cid: str, user: dict = Depends(get_current_user)):
    doc = await db.contracts.find_one({"id": cid})
    if not doc:
        raise HTTPException(404, "Not found")
    if user["role"] != "admin" and user["id"] not in (doc["artist_id"], doc["customer_id"]):
        raise HTTPException(403, "Forbidden")
    return clean(doc)


@api.get("/contracts/{cid}/pdf")
async def download_contract_pdf(cid: str, user: dict = Depends(get_current_user)):
    contract = await db.contracts.find_one({"id": cid})
    if not contract:
        raise HTTPException(404, "Contract not found")
    if user["role"] != "admin" and user["id"] not in (contract["artist_id"], contract["customer_id"]):
        raise HTTPException(403, "Forbidden")
    booking = await db.bookings.find_one({"id": contract["booking_id"]})
    artist_user = await db.users.find_one({"id": contract["artist_id"]}) or {}
    artist_profile = await db.artist_profiles.find_one({"user_id": contract["artist_id"]}) or {}
    customer = await db.users.find_one({"id": contract["customer_id"]}) or {}
    artist_merged = {**artist_user, **artist_profile}
    pdf_bytes = generate_contract_pdf(booking, artist_merged, customer, contract)
    filename = f"contract_{contract.get('ref', cid[:8])}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/bookings/{bid}/invoice")
async def download_invoice_pdf(bid: str, user: dict = Depends(get_current_user)):
    booking = await db.bookings.find_one({"id": bid})
    if not booking:
        raise HTTPException(404, "Booking not found")
    if user["role"] != "admin" and user["id"] not in (booking["customer_id"], booking["artist_id"]):
        raise HTTPException(403, "Forbidden")
    # Iter 53 — The Platform Service Fee invoice is a BookTalent-to-Customer
    # document. Artists must not download it (contains platform fee + GST
    # they shouldn't see).
    if user["role"] == "artist":
        raise HTTPException(403, "Platform invoices are issued only to the customer.")
    artist_user = await db.users.find_one({"id": booking["artist_id"]}) or {}
    artist_profile = await db.artist_profiles.find_one({"user_id": booking["artist_id"]}) or {}
    pdf_bytes = generate_invoice_pdf(booking, {**artist_user, **artist_profile})
    filename = f"invoice_{booking.get('ref', bid[:8])}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Counter-offer endpoint removed — BookTalent enforces fixed pricing.


# Upload signed contract (artist or customer)
class UploadSignedBody(BaseModel):
    contract_id: str
    data_url: str
    signed_by: Literal["artist", "customer"]


@api.post("/contracts/upload-signed")
async def upload_signed_contract(body: UploadSignedBody, user: dict = Depends(get_current_user)):
    contract = await db.contracts.find_one({"id": body.contract_id})
    if not contract:
        raise HTTPException(404, "Contract not found")
    if user["id"] not in (contract["artist_id"], contract["customer_id"]) and user["role"] != "admin":
        raise HTTPException(403, "Forbidden")
    if not body.data_url.startswith("data:"):
        raise HTTPException(400, "Invalid data URL")
    header, b64 = body.data_url.split(",", 1)
    mime = header.split(";")[0].replace("data:", "")
    raw = base64.b64decode(b64)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 25 MB)")
    mid = new_id()
    await db.media.insert_one({
        "id": mid, "user_id": user["id"], "type": "document",
        "mime": mime, "data": b64, "size": len(raw),
        "title": f"signed_contract_{contract.get('ref')}_{body.signed_by}",
        "contract_id": body.contract_id, "created_at": utcnow(),
    })
    # Add to contract's version history
    sig_field = f"signed_{body.signed_by}_media_id"
    await db.contracts.update_one(
        {"id": body.contract_id},
        {"$set": {sig_field: mid, f"signed_{body.signed_by}_at": utcnow()},
         "$push": {"history": {"action": "uploaded_signed", "by": user["id"], "media_id": mid, "at": utcnow()}}},
    )
    # If both signed, flip to fully_signed
    fresh = await db.contracts.find_one({"id": body.contract_id})
    if fresh.get("signed_artist_media_id") and fresh.get("signed_customer_media_id"):
        await db.contracts.update_one(
            {"id": body.contract_id},
            {"$set": {"status": "fully_signed", "fully_signed_at": utcnow()}},
        )
    return {"ok": True, "media_id": mid}


# BOOST
@api.post("/boost/activate")
async def activate_boost(body: BoostBody, user: dict = Depends(get_current_user)):
    plans = {"starter": (999, 7), "pro": (2499, 30), "elite": (7499, 90)}
    if body.plan not in plans:
        raise HTTPException(400, "Invalid plan")
    price, days = plans[body.plan]
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    await db.artist_profiles.update_one(
        {"user_id": user["id"]},
        {"$set": {"is_boosted": True, "boost_expires": expires, "boost_plan": body.plan}},
    )
    await db.transactions.insert_one({
        "id": new_id(), "user_id": user["id"], "type": "boost",
        "amount": -price, "status": "completed",
        "description": f"Boost plan {body.plan} activated for {days} days",
        "created_at": utcnow(),
    })
    return {"ok": True, "expires": expires}


# ANALYTICS (artist self)
@api.get("/analytics/me")
async def my_analytics(user: dict = Depends(get_current_user)):
    if user["role"] == "artist":
        profile = await db.artist_profiles.find_one({"user_id": user["id"]}) or {}
        bookings = await db.bookings.find({"artist_id": user["id"]}).to_list(5000)
        total_earnings = sum(
            float(b.get("pricing", {}).get("package_fee", 0)) + float(b.get("pricing", {}).get("addons_total", 0))
            for b in bookings if b.get("status") in ("completed", "reviewed")
        )
        pending = sum(
            float(b.get("pricing", {}).get("token_amount", 0))
            for b in bookings if b.get("status") in ("confirmed", "started", "completed_by_artist")
        )
        return {
            "earnings": total_earnings,
            "total_bookings": len(bookings),
            "pending_requests": sum(1 for b in bookings if b.get("status") in ("pending_artist", "pending_payment")),
            "profile_views": profile.get("profile_views", 0),
            "rating": profile.get("rating_avg", 0),
            "reviews": profile.get("review_count", 0),
            "events_done": profile.get("events_done", 0),
            "pending_amount": pending,
        }
    else:
        bookings = await db.bookings.find({"customer_id": user["id"]}).to_list(5000)
        total_spent = sum(float(b.get("amount_paid", 0)) for b in bookings)
        return {
            "total_spent": total_spent,
            "total_bookings": len(bookings),
            "completed": sum(1 for b in bookings if b.get("status") in ("completed", "reviewed")),
            "upcoming": sum(1 for b in bookings if b.get("status") in ("confirmed", "started")),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SEED & STARTUP
# ─────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.artist_profiles.create_index("user_id", unique=True)
    await db.bookings.create_index("id", unique=True)
    await db.bookings.create_index("artist_id")
    await db.bookings.create_index("customer_id")
    await db.bookings.create_index([("status", 1), ("expires_at", 1)])
    await db.coupons.create_index("code", unique=True)
    await db.media.create_index("user_id")
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    # Iter 74 — Booking drafts & Recent views indexes.
    await db.booking_drafts.create_index([("user_id", 1), ("artist_id", 1)], unique=True)
    await db.booking_drafts.create_index([("user_id", 1), ("updated_at", -1)])
    await db.recent_views.create_index([("user_id", 1), ("artist_id", 1)], unique=True)
    await db.recent_views.create_index([("user_id", 1), ("viewed_at", -1)])
    # Iter 76 — Video upload sessions (chunked).
    await db.video_upload_sessions.create_index([("user_id", 1), ("created_at", -1)])
    # Iter 76 — Emergent Object Storage session key. Failure is
    # non-fatal so photo/base64 uploads keep working even when the
    # object-storage backend is unreachable.
    try:
        from storage import init_storage
        init_storage()
        log.info("[iter76] Object storage session initialised.")
    except Exception as _e:
        log.warning("[iter76] Object storage init failed (video uploads will error): %s", _e)

    # Iter 73 — Backfill `order: 0` on legacy media docs that predate the
    # order field. MongoDB sorts missing values BEFORE numeric 0, so
    # without this migration newly uploaded gallery items (which always
    # write `order:0`) end up AFTER every legacy item in the tie-breaker
    # `.sort([('order',1),('created_at',-1)])` query. Idempotent — safe
    # to run on every boot.
    try:
        res = await db.media.update_many(
            {"order": {"$exists": False}}, {"$set": {"order": 0}},
        )
        if res.modified_count:
            log.info("[iter73] backfilled order=0 on %d media docs", res.modified_count)
    except Exception as _e:
        log.warning("[iter73] media order backfill failed: %s", _e)

    # seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@booktalent.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": new_id(), "email": admin_email,
            "password_hash": hash_password(admin_password),
            "first_name": "Super", "last_name": "Admin",
            "role": "admin",
            "admin_role": "super_admin",
            "admin_permissions": ADMIN_PERMISSIONS,
            "kyc_status": "approved", "verified": True,
            "created_at": utcnow(), "updated_at": utcnow(),
        })
    else:
        # SECURITY: Do NOT auto-reset the admin password on every boot. Doing so
        # would silently overwrite any password rotation the super_admin performs
        # via the UI. Password rotation is now an explicit opt-in via
        # `ADMIN_PASSWORD_FORCE_RESET=1` (single-boot escape hatch).
        upd = {}
        if os.environ.get("ADMIN_PASSWORD_FORCE_RESET", "").lower() in ("1", "true", "yes"):
            if not verify_password(admin_password, existing.get("password_hash", "")):
                upd["password_hash"] = hash_password(admin_password)
                log.warning("[seed] Admin password force-reset via ADMIN_PASSWORD_FORCE_RESET env")
        # Backfill RBAC fields for the legacy seed admin so it becomes the super admin.
        if not existing.get("admin_role"):
            upd["admin_role"] = "super_admin"
            upd["admin_permissions"] = ADMIN_PERMISSIONS
        if upd:
            await db.users.update_one({"email": admin_email}, {"$set": upd})

    # Iter 56 — Seed default role presets into `admin_roles` on fresh install.
    for rid, perms in DEFAULT_ADMIN_ROLE_PRESETS.items():
        if not await db.admin_roles.find_one({"id": rid}):
            await db.admin_roles.insert_one({
                "id": rid, "permissions": perms,
                "created_at": utcnow(), "seeded": True,
            })
    # Always overwrite super_admin permissions with the code list so a
    # code-level addition to ADMIN_PERMISSIONS auto-propagates.
    await db.admin_roles.update_one(
        {"id": "super_admin"},
        {"$set": {"permissions": ADMIN_PERMISSIONS, "updated_at": utcnow()}},
    )

    # seed demo data only once
    seed_marker = await db.meta.find_one({"_id": "seed_v3"})
    if not seed_marker:
        await _seed_demo()
        await db.meta.insert_one({"_id": "seed_v3", "seeded_at": utcnow()})
    log.info("BookTalent API ready")
    # Start the 24-hr Artist Confirmation auto-expiry background loop.
    asyncio.create_task(_auto_expire_loop())
    # Iter 79 — Event-day reminder loop (fires the morning of each event).
    asyncio.create_task(_event_reminder_loop())
    # Iter 84 — Payment milestone reminder loop (Sec 35).
    from routes.crm_pay import payment_reminder_loop as _prl  # noqa
    asyncio.create_task(_prl(db))
    # Iter 88 — Payout auto-retry + report scheduling background loops.
    from routes.iter88 import payout_retry_loop as _pl, report_schedule_loop as _rsl  # noqa
    asyncio.create_task(_pl(db))
    asyncio.create_task(_rsl(db))
    # Analytics Slack alerts — daily GMV/churn health sweep.
    from routes.analytics_alerts import analytics_alerts_loop as _aal  # noqa
    asyncio.create_task(_aal(db))
    # Refund SLA Slack alerts — 48h counter-party ack breach sweep.
    from routes.req_batch_4 import refund_sla_loop as _rsla  # noqa
    asyncio.create_task(_rsla(db))
    # Refund SLA escalation ladder — 72h / 96h tiers.
    from routes.req_batch_5 import escalation_loop as _resc  # noqa
    asyncio.create_task(_resc(db))
    # Iter 90 — One-shot KYC status backfill (align all 3 collections
    # to artist_profiles.kyc_status). Idempotent, safe every boot.
    try:
        from kyc_sync import backfill_all as _kyc_backfill  # noqa
        stats = await _kyc_backfill(db)
        if stats["fixed"]:
            log.info("[kyc_sync] backfill fixed %d/%d drifted users", stats["fixed"], stats["scanned"])
    except Exception as e:  # noqa: BLE001
        log.warning("[kyc_sync] backfill failed: %s", e)


async def _seed_demo():
    """Seed demo artists, packages, reviews so the app is not empty."""
    log.info("Seeding demo data…")
    artists = [
        ("priya@booktalent.com", "Priya", "Sharma", "Bollywood Vocalist", "Mumbai", "🎤", True,
         "Award-winning Bollywood vocalist with 8 years of experience. Performed at 300+ events.", 4.9, 284, 312,
         [("Acoustic Solo", 35000, "2 hours", ["20 songs", "Own setup", "1 dedication"], False),
          ("Premium Bollywood", 55000, "3 hours", ["35+ songs", "Pro PA system", "Tabla player", "3 dedications"], True),
          ("Royal Concert", 120000, "5 hours", ["Live band", "Stage lighting", "LED backdrop", "Unlimited songs"], False)]),
        ("vortex@booktalent.com", "DJ", "Vortex", "DJ / Music Producer", "Delhi", "🎧", True,
         "EDM and Bollywood DJ. Performed at top clubs and 200+ events across India.", 4.8, 198, 248,
         [("Club Night", 40000, "4 hours", ["EDM + Bollywood", "Own console", "Lighting"], True),
          ("Wedding Premium", 65000, "6 hours", ["Full setup", "LED screens", "Photo wall"], False)]),
        ("rohit@booktalent.com", "Rohit", "Gupta", "Stand-up Comedian", "Bangalore", "🎭", False,
         "Award winning stand-up comedian with 6 years of experience. 100+ corporate shows.", 4.7, 156, 196,
         [("Corporate 45min", 30000, "45 mins", ["Clean comedy", "Mic + setup"], True),
          ("Festival Show", 55000, "90 mins", ["Full setlist", "Q&A", "Meet & greet"], False)]),
        ("kavya@booktalent.com", "Kavya", "Menon", "Carnatic Vocalist", "Chennai", "🎤", True,
         "Trained Carnatic vocalist blending classical with Bollywood. Pan-India performer.", 4.9, 142, 168,
         [("Classical Recital", 45000, "2 hours", ["Tanpura + Mridangam"], False),
          ("Fusion Concert", 75000, "3 hours", ["Full band", "Bollywood + Classical"], True)]),
        ("aamir@booktalent.com", "Aamir", "Qureshi", "Sufi Vocalist", "Delhi", "🎵", False,
         "Sufi & Ghazal vocalist with classical training. Soulful performances for elite events.", 4.8, 118, 142,
         [("Sufi Soiree", 60000, "2.5 hours", ["Harmonium + Tabla", "Original setlist"], True)]),
        ("deepika@booktalent.com", "Deepika", "Rao", "Ghazal Singer", "Pune", "🎶", False,
         "Ghazal and semi-classical specialist. Intimate evening performances.", 4.6, 88, 102,
         [("Intimate Evening", 38000, "2 hours", ["Acoustic", "Curated setlist"], True)]),
    ]
    for email, fn, ln, cat, city, emoji, featured, bio, rating, reviews, events, packages in artists:
        if await db.users.find_one({"email": email}):
            continue
        uid = new_id()
        now = utcnow()
        await db.users.insert_one({
            "id": uid, "email": email, "password_hash": hash_password("Artist@123"),
            "first_name": fn, "last_name": ln, "phone": f"+91 98765 {uid[:5]}",
            "role": "artist", "kyc_status": "approved", "verified": True,
            "created_at": now, "updated_at": now,
        })
        await db.artist_profiles.insert_one({
            "id": new_id(), "user_id": uid, "stage_name": f"{fn} {ln}",
            "category": cat, "subcategories": [],
            "city": city, "state": "", "country": "India",
            "bio": bio, "tagline": f"{cat} — {city}",
            "languages": ["Hindi", "English"], "genres": [cat], "event_types": ["Weddings", "Corporate"],
            "travel_range": "Pan India", "experience_years": 8, "notice_period_days": 7,
            "available_for_booking": True, "profile_image": None, "cover_image": None,
            "socials": {}, "rating_avg": rating, "review_count": reviews, "events_done": events,
            "followers": reviews * 7, "profile_views": reviews * 30,
            "is_featured": featured, "is_boosted": featured, "kyc_status": "approved",
            "emoji": emoji,
            "created_at": now, "updated_at": now,
        })
        for name, price, dur, feats, popular in packages:
            await db.packages.insert_one({
                "id": new_id(), "artist_id": uid, "name": name, "description": "",
                "price": price, "duration": dur, "features": feats, "is_popular": popular,
                "created_at": now,
            })

    # seed a demo customer
    if not await db.users.find_one({"email": "customer@booktalent.com"}):
        cid = new_id()
        await db.users.insert_one({
            "id": cid, "email": "customer@booktalent.com",
            "password_hash": hash_password("Customer@123"),
            "first_name": "Rajesh", "last_name": "Kapoor", "phone": "+91 98765 43210",
            "role": "customer", "kyc_status": "unverified", "verified": False,
            "created_at": utcnow(),
        })

    # seed a coupon
    if not await db.coupons.find_one({"code": "WEDDING20"}):
        await db.coupons.insert_one({
            "id": new_id(), "code": "WEDDING20", "description": "20% off on wedding bookings",
            "discount_type": "percent", "discount_value": 20, "max_uses": 500, "usage_count": 284,
            "expires_at": "2026-12-31", "min_order": 0, "applies_to": "wedding", "active": True,
            "created_at": utcnow(),
        })
        await db.coupons.insert_one({
            "id": new_id(), "code": "FIRST500", "description": "₹500 off first booking",
            "discount_type": "flat", "discount_value": 500, "max_uses": 1000, "usage_count": 0,
            "expires_at": "2026-12-31", "min_order": 5000, "applies_to": "all", "active": True,
            "created_at": utcnow(),
        })

    log.info("Demo data seeded.")


# ─────────────────────────────────────────────────────────────────────────────
@api.get("/")
async def root():
    return {"ok": True, "service": "BookTalent API", "version": "1.0.0"}


@api.get("/categories")
async def categories():
    return [
        {"slug": "singer", "name": "Singers & Vocalists", "icon": "🎤"},
        {"slug": "dj", "name": "DJs & Music", "icon": "🎧"},
        {"slug": "comedian", "name": "Comedians", "icon": "🎭"},
        {"slug": "dancer", "name": "Dancers", "icon": "💃"},
        {"slug": "anchor", "name": "Anchors / Emcees", "icon": "🎙️"},
        {"slug": "band", "name": "Live Bands", "icon": "🎸"},
        {"slug": "magician", "name": "Magicians", "icon": "🎩"},
        {"slug": "folk", "name": "Folk Artists", "icon": "🪕"},
    ]


@api.get("/cities")
async def cities():
    return ["Mumbai", "Delhi NCR", "Bangalore", "Chennai", "Hyderabad", "Kolkata", "Pune", "Jaipur", "Ahmedabad", "Goa"]


# ── Token-gated one-shot DB dump download (for VPS migration) ────────────
# Reads token from DUMP_DOWNLOAD_TOKEN env var (no hardcoded secret).
# Unset the env var (or delete this block) once your VPS restore is done.
import hmac as _hmac
import subprocess as _subprocess
from fastapi.responses import FileResponse as _FileResponse
_DUMP_PATH = "/app/booktalent-mongodb-dump.archive.gz"


async def _regenerate_dump() -> None:
    """Run mongodump synchronously into the archive path. Raises on failure."""
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "booktalent"
    tmp_path = _DUMP_PATH + ".tmp"
    proc = _subprocess.run(
        ["mongodump", f"--uri={mongo_url}", f"--db={db_name}",
         f"--archive={tmp_path}", "--gzip"],
        capture_output=True, timeout=180,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"mongodump failed: {proc.stderr.decode()[:400]}")
    os.replace(tmp_path, _DUMP_PATH)


@api.get("/ops/dump/{token}")
async def dump_download(token: str):
    # SECURITY (Iter 86): Endpoint deprecated. Unauthenticated bearer-token DB
    # dump was an exfiltration risk if the token ever leaked. Full DB export is
    # now available ONLY to the authenticated super_admin via
    # `POST /api/admin/db-export` + `GET /api/admin/db-export` below.
    raise HTTPException(status_code=404, detail="Not found")


@api.post("/admin/db-export")
async def admin_db_export_refresh(admin: dict = Depends(admin_only)):
    """Super-admin only: regenerate a fresh mongodump archive on disk.
    Returns metadata (size, generated_at). Actual download is via GET below."""
    if admin.get("admin_role") not in (None, "super_admin"):
        # Only super_admin (or legacy admins with no role field) may export the DB.
        raise HTTPException(403, "Super admin only")
    await _regenerate_dump()
    stat = os.stat(_DUMP_PATH)
    await audit_log(admin, "db.export.refresh",
                    meta={"size_bytes": stat.st_size})
    return {
        "ok": True,
        "size_bytes": stat.st_size,
        "generated_at": utcnow(),
        "download_url": f"/api/admin/db-export",
    }


@api.get("/admin/db-export")
async def admin_db_export_download(admin: dict = Depends(admin_only)):
    """Super-admin only: stream the latest mongodump archive."""
    if admin.get("admin_role") not in (None, "super_admin"):
        raise HTTPException(403, "Super admin only")
    if not os.path.exists(_DUMP_PATH):
        await _regenerate_dump()
    await audit_log(admin, "db.export.download",
                    meta={"size_bytes": os.stat(_DUMP_PATH).st_size})
    return _FileResponse(
        _DUMP_PATH,
        media_type="application/gzip",
        filename="booktalent-mongodb-dump.archive.gz",
    )


# ─── Iter 47 — AI Planner "Add All To Cart" best-fit resolver ────────────────
class BestFitRequest(BaseModel):
    categories: List[str]                  # e.g. ["Singer / Vocalist", "DJ", "Anchor / MC"]
    city: Optional[str] = None
    event_date: Optional[str] = None       # ISO YYYY-MM-DD — skip artists busy that day
    budget_hint: Optional[str] = None      # ignored today, reserved for future ranking


class BestFitArtist(BaseModel):
    category: str
    user_id: Optional[str] = None
    stage_name: Optional[str] = None
    profile_image: Optional[str] = None
    starting_price: Optional[float] = None
    package_id: Optional[str] = None
    city: Optional[str] = None
    emoji: Optional[str] = None
    matched: bool = False                  # False when nothing available for this category


@api.post("/event-planner/best-fit", response_model=List[BestFitArtist])
async def event_planner_best_fit(body: BestFitRequest):
    """Resolves LLM-generated category labels into concrete artist recommendations
    (one per category) that the customer can drop into their cart in one tap.
    Never 500s — every requested category comes back with at least a stub row
    so the frontend can render a placeholder even when no artist is available."""
    if not body.categories:
        raise HTTPException(400, "categories list is required")

    city = (body.city or "").strip()
    busy_ids: set = set()
    if body.event_date:
        booked = await db.bookings.find(
            {"event_date": body.event_date,
             "status": {"$in": ["pending_artist", "confirmed", "started", "completed"]}},
            {"artist_id": 1},
        ).to_list(500)
        busy_ids = {b["artist_id"] for b in booked}

    out: List[BestFitArtist] = []
    seen_ids: set = set()

    for cat_label in body.categories:
        # The LLM emits multi-part labels like "Singer / Vocalist", "Anchor / MC".
        # Real artist_profiles.category values are things like "Bollywood Vocalist"
        # or "DJ / Music Producer". Match any of the label's alt terms as a
        # case-insensitive SUBSTRING so both directions of naming line up.
        parts = [p.strip() for p in re.split(r"[/,]", cat_label or "") if p.strip()]
        if not parts:
            out.append(BestFitArtist(category=cat_label, matched=False))
            continue
        cat_regex = "|".join(re.escape(p) for p in parts)

        q: dict = {
            "$or": [{"listing_status": {"$exists": False}}, {"listing_status": {"$ne": "hidden"}}],
            "category": {"$regex": cat_regex, "$options": "i"},
            "suspended": {"$ne": True},   # Iter 52.8 — hide suspended artists
        }
        if city:
            # Prefix match on city — accepts "Mumbai" and "Mumbai, India" alike.
            q["city"] = {"$regex": f"^{re.escape(city)}", "$options": "i"}

        profiles = await db.artist_profiles.find(q).sort(
            [("rating_avg", -1), ("bookings_count", -1)]
        ).to_list(20)

        # City fallback — if no artist in the requested city, cast a wider net
        # nationally so we always propose SOMEBODY per category.
        if not profiles and city:
            q.pop("city", None)
            profiles = await db.artist_profiles.find(q).sort(
                [("rating_avg", -1), ("bookings_count", -1)]
            ).to_list(20)

        pick: Optional[dict] = None
        for prof in profiles:
            uid = prof.get("user_id")
            if not uid or uid in seen_ids or uid in busy_ids:
                continue
            pick = prof
            break

        if not pick:
            out.append(BestFitArtist(category=cat_label, matched=False))
            continue
        seen_ids.add(pick["user_id"])

        pkgs = await db.packages.find({"artist_id": pick["user_id"]}).sort("price", 1).to_list(10)
        cheapest = pkgs[0] if pkgs else None

        out.append(BestFitArtist(
            category=cat_label,
            user_id=pick["user_id"],
            stage_name=pick.get("stage_name"),
            profile_image=pick.get("profile_image"),
            starting_price=float(cheapest["price"]) if cheapest else None,
            package_id=cheapest.get("id") if cheapest else None,
            city=pick.get("city"),
            emoji=pick.get("emoji", "🎤"),
            matched=True,
        ))

    return out




app.include_router(api)


# Iter 61 — Easebuzz Payment Gateway (admin-configurable, DB-backed settings).
# Registered LATER (below iter7 and subscription routers) so the activator
# helpers exposed on those routers are available.
_easebuzz_registered = False


# Iteration 7 — Enterprise routes (Admin ERP, Boost, Notifications, Advanced Search)
_iter7_router = make_admin_config_router(db, get_current_user, admin_only)
app.include_router(_iter7_router, prefix="/api")

# Live chat (REST + WebSocket)
_chat_router = make_chat_router(db, get_current_user)
app.include_router(_chat_router, prefix="/api")

# Iter9 — Agency / Corporate / Chat upload / Provider wiring
_iter9_router = make_agency_corp_router(db, get_current_user, admin_only)
app.include_router(_iter9_router, prefix="/api")

# Iter11 — ICS calendar, CSV exports, AI semantic search
_iter11_router = make_exports_search_router(db, get_current_user, admin_only)
app.include_router(_iter11_router, prefix="/api")

# Iter 82 — Platform Settings + Audit Log (v2 financial-engine foundation).
# GST %, Platform Fee %, Payment Schedule, Payout Mode feature flag,
# Instant Book rules & required KYC docs all live here. Frontend reads
# from /api/settings/public; only admin can write via /api/settings/admin.
from routes.settings import make_settings_router  # noqa: E402
app.include_router(make_settings_router(db, admin_only, get_current_user), prefix="/api")

# Iter 83 — v2 vertical: Financial quote + KYC state machine + T&C +
# agreement PDF. Booking form fields (event_type_other, venue_address,
# number_of_days) still write through the existing booking endpoints;
# see BookBody below for the new optional fields.
from routes.v2_flow import make_v2_router  # noqa: E402
app.include_router(make_v2_router(db, get_current_user, admin_only), prefix="/api")

# Iter 84 — Phases 4-7: CRM (leads + manager assignment) + Payments
# (milestones + reminders) + Payouts (manual + Easebuzz-ready abstraction)
# + Chat (manager-mediated for Service Artists with contact-privacy redaction).
from routes.crm_pay import make_crm_pay_router, payment_reminder_loop  # noqa: E402
app.include_router(make_crm_pay_router(db, get_current_user, admin_only), prefix="/api")

# Iter 85 — At-Risk dashboard + Agency financial view + Admin payout queue
# + WhatsApp channel abstraction (Sec 45-48, 55, 51).
from routes.v2_more import make_v2_more_router  # noqa: E402
app.include_router(make_v2_more_router(db, get_current_user, admin_only), prefix="/api")

# Iter 87 — Admin Reports + Unified Audit Log
from routes.reports import make_reports_router  # noqa: E402
app.include_router(make_reports_router(db, admin_only), prefix="/api")

# Iter 88 — Payout retry queue + Report scheduling + Manager scorecard
from routes.iter88 import make_iter88_router  # noqa: E402
app.include_router(make_iter88_router(db, get_current_user, admin_only), prefix="/api")

# Iter 89 — WA templates DB persistence + team leaderboard + Slack + snapshot history
from routes.iter89 import make_iter89_router  # noqa: E402
app.include_router(make_iter89_router(db, get_current_user, admin_only), prefix="/api")

# Iter 90b — Artist KYC pipeline + Admin agreements + Manager chat threads
from routes.iter90b import make_iter90b_router  # noqa: E402
app.include_router(make_iter90b_router(db, get_current_user, admin_only), prefix="/api")

# Iter 92 — Admin analytics + Public trust stats + Notification preferences
from routes.iter92 import make_iter92_router  # noqa: E402
app.include_router(make_iter92_router(db, get_current_user, admin_only), prefix="/api")

# Analytics Slack alerts — GMV WoW drop + churn thresholds
from routes.analytics_alerts import make_analytics_alerts_router  # noqa: E402
app.include_router(make_analytics_alerts_router(db, admin_only), prefix="/api")

# Feb-2026 requirement batch — Tech Rider + Manager add-customer/on-behalf + advance-pending broadcast
from routes.req_batch import make_req_batch_router  # noqa: E402
app.include_router(make_req_batch_router(db, get_current_user, admin_only), prefix="/api")

# Feb-2026 requirement batch 2 — mutual refunds + presets + timeline + service-artist seeder
from routes.req_batch_2 import make_req_batch_2_router  # noqa: E402
app.include_router(make_req_batch_2_router(db, get_current_user, admin_only), prefix="/api")

# Feb-2026 requirement batch 3 — refund auditor + bulk payout + email timeline helper
from routes.req_batch_3 import make_req_batch_3_router  # noqa: E402
app.include_router(make_req_batch_3_router(db, get_current_user, admin_only), prefix="/api")

# Feb-2026 requirement batch 4 — CSV payout import + refund SLA + preset stats + saved views
from routes.req_batch_4 import make_req_batch_4_router  # noqa: E402
app.include_router(make_req_batch_4_router(db, get_current_user, admin_only), prefix="/api")

# Feb-2026 requirement batch 5 — bank presets + SLA escalation + preset recs + timeline badges + watchlists
from routes.req_batch_5 import make_req_batch_5_router  # noqa: E402
app.include_router(make_req_batch_5_router(db, get_current_user, admin_only), prefix="/api")

# Feb-2026 requirement batch 6 — commercial-deal page + deal snapshot + chat redaction + deal history
from routes.req_batch_6 import make_req_batch_6_router  # noqa: E402
app.include_router(make_req_batch_6_router(db, get_current_user, admin_only), prefix="/api")

# Iter52 — Agency CRM (offline artists/clients/events/staff/finance).
# Note: the persistent Booking Cart shipped in Iter 52 was removed at user
# request in Iter 52.5 — the artist-profile flow is single-artist and
# customer-login-gated as before. Cart router + collection are gone.
from routes.agency_crm import make_agency_crm_router  # noqa: E402
app.include_router(make_agency_crm_router(db, get_current_user), prefix="/api")

# Iter 63 — Agency ↔ Artist roster (invite, accept, referral, release).
from routes.agency_roster import make_roster_router  # noqa: E402
app.include_router(make_roster_router(db, get_current_user), prefix="/api")

# Iter 66 — Artist category-request workflow.
from routes.category_requests import make_category_requests_router  # noqa: E402
app.include_router(
    make_category_requests_router(
        db=db, get_current_user=get_current_user, admin_only=admin_only, new_id=new_id,
    ),
    prefix="/api",
)

# Iter 67 — Artist city-request workflow (mirror of category requests).
from routes.city_requests import make_city_requests_router  # noqa: E402
app.include_router(
    make_city_requests_router(
        db=db, get_current_user=get_current_user, admin_only=admin_only, new_id=new_id,
    ),
    prefix="/api",
)

# Iter13 — server.py modularisation. Domain routers split out for maintainability.
_common_deps = dict(db=db, utcnow=utcnow, new_id=new_id, clean=clean)
app.include_router(
    routes_reviews.make_router(get_current_user=get_current_user, admin_only=admin_only,
                               notify_dispatch=notify_dispatch, **_common_deps),
    prefix="/api",
)
app.include_router(
    routes_coupons.make_router(get_current_user=get_current_user, admin_only=admin_only,
                               validate_coupon=_validate_coupon, **_common_deps),
    prefix="/api",
)
app.include_router(
    routes_blogs.make_router(admin_only=admin_only, **_common_deps),
    prefix="/api",
)
app.include_router(
    routes_disputes.make_router(get_current_user=get_current_user, admin_only=admin_only,
                                **_common_deps),
    prefix="/api",
)
app.include_router(
    routes_kyc.make_router(get_current_user=get_current_user, admin_only=admin_only,
                           notify_dispatch=notify_dispatch, log=log, **_common_deps),
    prefix="/api",
)
# Sprint 2 — chunked / resumable filesystem uploads (up to 5 GB per file)
app.include_router(
    routes_uploads.make_router(
        get_current_user=get_current_user, log=log,
        compress_image=compress_image, make_thumbnail=make_thumbnail,
        **_common_deps,
    ),
    prefix="/api",
)
# Sprint 3 — artist-defined add-ons
app.include_router(
    routes_addons.make_router(get_current_user=get_current_user, **_common_deps),
    prefix="/api",
)
# Sprint 5 — premium subscription plans
_subscriptions_router = routes_subscriptions.make_router(
    get_current_user=get_current_user, admin_only=admin_only, **_common_deps,
)
app.include_router(_subscriptions_router, prefix="/api")
# Sprint 5 — dynamic homepage sections (public)
app.include_router(
    routes_homepage.make_router(get_current_user_optional=get_current_user_optional, **_common_deps),
    prefix="/api",
)
# Elite Concierge Chat (Platinum + Elite gate)
app.include_router(
    routes_concierge.make_router(
        get_current_user=get_current_user, admin_only=admin_only,
        notify_dispatch=notify_dispatch, **_common_deps,
    ),
    prefix="/api",
)
# Booking Insights — artist self-service analytics
app.include_router(
    routes_insights.make_router(get_current_user=get_current_user, **_common_deps),
    prefix="/api",
)

# Iter 63.3 — Easebuzz router mounted here (after subscriptions + iter7 boost)
# so we can inject the activation helpers exposed on those routers.
app.include_router(
    make_easebuzz_router(
        db=db, get_current_user=get_current_user, admin_only=admin_only,
        new_id=new_id, utcnow=utcnow,
        activate_subscription=getattr(_subscriptions_router, "_activate_plan", None),
        activate_boost=getattr(_iter7_router, "_activate_boost", None),
    ),
    prefix="/api",
)
# Iter 64 — Wire refund context so booking action handlers can auto-refund
# via the module-level `auto_refund_bookings` helper.
set_refund_context(db=db, new_id=new_id, utcnow=utcnow)
# City-alias admin management (Iter 35)
app.include_router(
    routes_city_aliases.make_router(admin_only=admin_only, **_common_deps),
    prefix="/api",
)
# Outstation Analytics — Admin report
app.include_router(
    routes_outstation_report.make_router(admin_only=admin_only, **_common_deps),
    prefix="/api",
)
# Iter 39 — CMS pages / Dynamic Menus / FAQ Help Center / Broadcast /
# Sitemap.xml + Robots.txt / Artist slug SEO / Category & City landing.
_cms_seo_router = routes_cms_seo.make_router(
    get_current_user=get_current_user,
    get_current_user_optional=get_current_user_optional,
    admin_only=admin_only,
    **_common_deps,
)
app.include_router(_cms_seo_router, prefix="/api")

# Iter 47 — Dynamic Artist Onboarding Questionnaire (Layer 1 + Layer 2).
app.include_router(
    routes_questionnaire.make_router(
        get_current_user=get_current_user, admin_only=admin_only, **_common_deps
    ),
    prefix="/api",
)

# Iter 46 — AI Event Planner (Claude Sonnet 4.6 via Emergent Universal Key).
from routes import event_planner as routes_event_planner  # noqa: E402
app.include_router(routes_event_planner.router, prefix="/api")

# Iter 48 — Multi-Artist Event recap + summary (extracted from server.py).
from routes import events as routes_events  # noqa: E402
app.include_router(
    routes_events.make_router(db=db, get_current_user=get_current_user, clean=clean),
    prefix="/api",
)

# Iter 50 — Save-a-Watch (filter combos → notification when a new artist matches).
from routes import watches as routes_watches  # noqa: E402
app.include_router(
    routes_watches.make_router(db=db, get_current_user=get_current_user, utcnow=utcnow),
    prefix="/api",
)


@app.on_event("startup")
async def _iter7_startup():
    await _iter7_router.seed()
    await _cms_seo_router.seed()  # Iter 39 seed (CMS pages, artist slugs, featured FAQs)
    # ── One-shot data migrations for the intermediary-marketplace model ──
    # 1. Backfill artist_fee on legacy bookings so admin reports normalise.
    legacy = db.bookings.find({"pricing.artist_fee": {"$exists": False}}, {"id": 1, "pricing": 1})
    migrated = 0
    async for b in legacy:
        p = b.get("pricing", {}) or {}
        artist_fee = float(p.get("package_fee", 0) + p.get("addons_total", 0) - p.get("coupon_discount", 0))
        await db.bookings.update_one(
            {"id": b["id"]},
            {"$set": {"pricing.artist_fee": round(max(0, artist_fee), 2)}},
        )
        migrated += 1
    if migrated:
        log.info("Backfilled artist_fee on %d legacy bookings", migrated)

    # 2. Business-model pivot (Iter 36): BookTalent is a lead-generation
    # marketplace only. Legacy wallet/withdrawal collections are no longer
    # referenced by any code path — no need to drop them on every boot.
    # Iter 99 deployment audit: removed destructive startup drop that would
    # wipe collections on production reboot. If cleanup is ever needed, run
    # it as a one-off migration script, not on startup.

    # 3. Iter 45 — spotlight impression dedup index.
    try:
        await db.spotlight_impressions.create_index("key", unique=True)
    except Exception as _e:
        log.warning("Could not create spotlight_impressions index: %s", _e)


@app.on_event("shutdown")
async def shutdown():
    client.close()
