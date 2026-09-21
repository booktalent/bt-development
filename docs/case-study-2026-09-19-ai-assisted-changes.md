# BookTalent — 19 September 2026 Change Case Study

## Scope and evidence

This document covers every committed change on `artist_percentage_payment_fix` from the first commit on 19 September 2026 (11:56 IST) through the current HEAD (`49ac2df`, 18:15 IST), plus the uncommitted development proxy change present when this document was written.

The repository attributes all twelve commits to **Aman Rajpoot**. Git records commit authorship, not whether a person, an AI assistant, or both wrote a particular line. Therefore, “AI-assisted work” below means the implementation approaches visible in the diff: the code an AI likely helped construct or explain, rather than an unsupported claim of authorship.

| Time (IST) | Commit | Outcome |
|---|---|---|
| 11:56 | `3b2f97b` | Development environment / MongoDB dump housekeeping |
| 12:10 | `aeca948` | Artist details shown in payout workflow |
| 12:53 | `39bdbc6` | Canonical pricing model and legacy-booking reconciliation |
| 13:33 | `eec193c` | Easebuzz retry handling / payment return resilience |
| 14:35 | `0a48bb7` | GST field compatibility and service-artist visibility |
| 16:15 | `aa4376f` | Non-negative numeric validation across APIs and MongoDB |
| 16:38 | `13b4148` | Only live, unsuspended artists appear on the homepage |
| 17:05 | `dd66492` | KYC DOB validation and actionable go-live progress |
| 17:19 | `79e05f7` | Authenticated in-app KYC document viewer |
| 17:19 | `fdce61b` | Reliable protected agreement download after T&C acceptance |
| 17:26 | `0dc7df8` | Idempotent artist profile-view analytics |
| 18:15 | `49ac2df` | Milestone payments and proportional commission settlement |

## Executive case study

The day’s work moved BookTalent from several loosely connected flows toward a consistent booking lifecycle:

```text
Artist setup/KYC ──> live + unsuspended ──> public discovery
                                      │
Customer quote ──> canonical pricing ──> first payment milestone
                                      │                    │
                                Easebuzz payment <─────────┘
                                      │
                         schedule received amount
                                      │
                   proportional commission / artist accrual
```

The recurring engineering idea was to make one component authoritative for each business fact:

- `financial_engine.compute_price()` owns the price calculation.
- `payment_schedules` owns payment milestones and what has been received.
- KYC/live status owns public listing eligibility.
- An idempotent analytics event owns “one profile visit”.

That is the strongest lesson from the work: do not let every page and endpoint independently reconstruct business state.

## 1. Payout context for administrators — `aeca948`

### Problem

The pending-payout table showed an opaque `artist_id`. A finance/admin user had to leave the task to learn who was being paid.

### Implementation

The backend performs two batched lookups after fetching bookings: profiles by `user_id` and users by `id`. It converts both result sets into dictionaries, then attaches the matching records to each booking.

```python
artist_ids = list({b.get("artist_id") for b in rows if b.get("artist_id")})
profile_rows = await db.artist_profiles.find(
    {"user_id": {"$in": artist_ids}},
    {"_id": 0, "user_id": 1, "stage_name": 1, "category": 1,
     "subcategories": 1, "genres": 1, "city": 1, "email": 1, "phone": 1},
).to_list(len(artist_ids))
profiles = {profile["user_id"]: profile for profile in profile_rows}

for booking in rows:
    booking["artist_profile"] = profiles.get(booking.get("artist_id"))
```

The React `ArtistDetails` component chooses the best available display values, gracefully falls back to the user record, and still renders a useful empty state. It is reused in both the table and the payout modal.

### What the AI-assisted approach did well

- Avoided an N+1 query (one artist query for every booking).
- Kept data shaping at the API boundary, keeping the UI simple.
- Used a small reusable display component instead of duplicating name/email logic.

### Learn from it

When a list needs related data, fetch the unique foreign keys, make one batched query per collection, then create lookup maps. This makes runtime scale with a small constant number of queries rather than the number of rows.

## 2. Canonical price calculation and payment retry — `39bdbc6`, `eec193c`, `0a48bb7`

### Problem

Booking creation, stored booking snapshots, and the gateway could disagree about what the customer owed. Legacy pending bookings also retained the old price shape. In addition, one area used `gst`, while the financial engine emits `gst_amount`.

### Business rule introduced

For a normal artist, the initial gateway payment is BookTalent’s platform fee plus GST; artist performance fees are not collected by the platform at this stage. For a service artist, BookTalent collects the artist fee because the platform fee is waived/managed differently.

```python
taxable = _q(artist_fee + platform_fee_net)
gst_amount = _q(taxable * gst_pct / 100) if gst_pct > 0 else 0.0

total = _q(
    artist_fee + gst_amount
    if commercial["is_service"]
    else platform_fee_net + gst_amount
)

return {
    # ...
    "total": total,
    "token_amount": total,  # compatibility alias for existing consumers
    "balance_due": 0.0,
}
```

`create_booking` now calls `compute_price`, rather than a separate `calc_booking_pricing`. Before sending an existing unpaid booking to Easebuzz, the gateway endpoint re-runs the canonical calculator when it detects an old pricing shape (`package_fee`), then persists the repaired snapshot.

```python
canonical = await compute_price(
    db,
    artist_id=d.get("artist_id"),
    package_fee=float(old_pricing.get("package_fee") or 0),
    addons_total=float(old_pricing.get("addons_total") or 0),
    coupon_discount=float(old_pricing.get("coupon_discount") or 0),
)
await db.bookings.update_one(
    {"id": d["id"], "status": "pending_payment"},
    {"$set": {"pricing": canonical}},
)
```

The GST rendering was made backward-compatible:

```python
booking["pricing"].get("gst_amount", booking["pricing"].get("gst", 0))
```

The admin artist list now normalizes legacy/current service-artist fields before rendering the type badge.

### What to learn

1. **Use a canonical calculator.** Monetary rules must have one executable source of truth.
2. **Migrate lazily with care.** Reconciling legacy records at a safe workflow boundary is practical, but it should be observable (logs/metrics) and eventually replaced by a one-off migration.
3. **Compatibility aliases are temporary contracts.** `token_amount` prevents breakage, but should have an owner and removal date.
4. **Money deserves tests.** Every branch (normal/service, GST/no GST, coupon, addons, legacy booking) should have exact expected values.

## 3. Positive-number validation at multiple boundaries — `aa4376f`

### Problem

Browser checks alone are bypassable. Negative prices, budgets, discount limits, and counts could enter through direct API calls or old records.

### Implementation

Pydantic request models gained declarative validation:

```python
class PackageBody(BaseModel):
    name: str
    price: float = Field(ge=0)
    team_size: Optional[int] = Field(None, ge=0)

class AddonSelection(BaseModel):
    addon_id: str
    quantity: int = Field(1, ge=1)
```

The same policy was applied to packages, profiles, availability, coupons, admin configuration, agency CRM amounts, event planner budgets, subscriptions, and dispute resolution. Questionnaire answers required extra logic because their fields are dynamic:

```python
def _validate_numeric_answers(answers, questions):
    numeric_ids = {q.get("id") for q in questions if q.get("type") in ("number", "price")}
    for key, value in answers.items():
        if key not in numeric_ids or value in (None, ""):
            continue
        try:
            if float(value) < 0:
                raise HTTPException(422, f"{key} cannot be negative")
        except (TypeError, ValueError):
            raise HTTPException(422, f"{key} must be a number")
```

At startup, `_install_numeric_guards()` also normalizes old negative data to zero and asks MongoDB to enforce JSON Schema minimums.

### What the AI-assisted approach did well

- Protected the UI/API boundary with clear Pydantic constraints.
- Recognized that dynamic questionnaires cannot be covered by static models alone.
- Added a persistence-layer guard, so a future endpoint cannot accidentally bypass the policy.

### Important review notes

- `0` is valid for most fields but not for `quantity`, `per_user_limit`, and `number_of_days`; the code correctly uses `ge=1` there.
- Turning historical negative values into zero silently changes data. For finance-related fields, preserve an audit record or migrate under supervision instead.
- `collMod` can fail where Mongo permissions or collection settings differ; the code logs and continues. That makes API validation essential, not optional.
- Add tests that assert HTTP 422 for a negative value at every high-risk endpoint.

## 4. Public-discovery eligibility is centralized — `13b4148`

### Problem

Search had a visibility rule, but homepage rails could surface incomplete, non-live, or suspended artists. That creates a broken public journey: a customer can see an artist who should not be bookable.

### Implementation

`homepage.py` defines the reusable filter once and spreads it into every discovery query:

```python
public_artist_filter = {"suspended": {"$ne": True}, "kyc_status": "live"}

cur = db.artist_profiles.find({
    **public_artist_filter,
    "$or": [{"is_featured": True}, {"is_boosted": True}],
}).sort("rating_avg", -1).limit(limit)
```

It was applied to personalized city/category rails, rebooking, featured, trending, plans, new talent, ratings, city results, category rails, spotlight, fallbacks, and category counts.

### Learn from it

Visibility is a domain rule, not a page rule. A next improvement would be a shared repository/helper used by search and homepage, so two files cannot drift apart again.

## 5. KYC correctness, go-live UX, and secure documents — `dd66492`, `79e05f7`, `fdce61b`

### KYC date of birth

The client constrains the date picker to `1900-01-01..today`; the server validates the actual submitted string too. This is the right defense-in-depth shape.

```python
if not _DOB_RX.match(dob):
    raise HTTPException(400, "Date of birth must use YYYY-MM-DD with a 4-digit year")
try:
    parsed_dob = date.fromisoformat(dob)
except ValueError:
    raise HTTPException(400, "Date of birth is not a valid calendar date")
if parsed_dob > date.today():
    raise HTTPException(400, "Date of birth cannot be in the future")
```

### Go-live progress

The new `/onboarding/live-progress` endpoint computes eight milestones: basic profile, branding, media, packages, availability, KYC submitted, KYC approved, and T&C/live. The dashboard consumes this authoritative response rather than attempting to infer readiness across multiple endpoints.

```python
is_live = kyc_status == "live" and not profile.get("suspended")
completed = sum(1 for step in steps if step["complete"])
next_step = next((step for step in steps if not step["complete"]), None)
```

The `GoLiveProgress` React component displays a percentage, next action, progress bar, and each individual milestone. On accepting T&C, the dashboard refreshes its progress so the UI does not remain stale.

### KYC document viewer and agreement fallback

Protected media must be fetched through Axios so the authenticated cookie is sent. The media backend now accepts either a Bearer token or its configured auth cookie. The admin viewer retrieves the binary as a blob, creates a temporary object URL, supports PDF/image display, provides a download link, and revokes the URL during cleanup.

```javascript
api.get("/media/" + document.id, { responseType: "blob" })
  .then((response) => {
    objectUrl = URL.createObjectURL(response.data);
    setAsset({ url: objectUrl, mime: response.headers["content-type"] || response.data.type || "" });
  });

return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
```

For artists, `openMyAgreement()` opens a blank tab synchronously (avoiding popup blockers), fetches `/agreements/mine` with credentials, then navigates the new tab to the blob URL. If download fails after successful T&C acceptance, the artist remains live and can retry in KYC.

### Learn from it

- The server must always validate security-sensitive input; an HTML `max` date is only usability help.
- A workflow-progress endpoint is a useful domain projection: it translates raw database state into the exact task model needed by the UI.
- For protected files, a direct `<a href>` often loses the authorization model. Fetching a blob lets the application preserve credentials and control UX.
- Object URLs consume browser resources; always revoke them.

## 6. Correct profile analytics under React Strict Mode — `0dc7df8`

### Problem

The profile GET endpoint incremented views. React Strict Mode, retrying, prefetching, or any non-user GET could inflate the metric. Analytics used `user_id` in one location and then wrote events keyed by `artist_id`, so the dashboard query did not necessarily find the events.

### Implementation

The public profile GET becomes read-only. A separate POST receives one per-artist SPA visit token. The token is stored in a module-level map, allowing Strict Mode effect replay to use the same token while a refresh creates a new visit.

```javascript
const profileViewTokens = new Map();

function profileViewToken(artistId) {
  if (!profileViewTokens.has(artistId)) {
    const token = globalThis.crypto?.randomUUID?.()
      || String(Date.now()) + "-" + Math.random().toString(36).slice(2);
    profileViewTokens.set(artistId, token);
  }
  return profileViewTokens.get(artistId);
}
```

The backend uses the artist and token as a deterministic event `_id`. MongoDB’s upsert gives the endpoint its idempotency property: only an insertion increments the profile counter.

```python
event_id = "profile_view:" + user_id + ":" + view_token
result = await db.analytics_events.update_one(
    {"_id": event_id},
    {"$setOnInsert": {"artist_id": user_id, "event": "profile_view", "created_at": utcnow()}},
    upsert=True,
)
if result.upserted_id is not None:
    await db.artist_profiles.update_one({"user_id": user_id}, {"$inc": {"profile_views": 1}})
```

The analytics reader was corrected to query `artist_id`.

### Learn from it

This is a durable pattern for webhooks, payments, emails, analytics, and any retryable command: pick a client/request idempotency key, enforce uniqueness at persistence, and only perform the side effect after a successful first insert.

## 7. Payment milestones and proportional settlement — `49ac2df`

### Problem

Checkout took a full amount, although the business now needs an advance followed by scheduled installments. Commission and artist payable amounts also need to reflect money actually received, not merely the total contract value.

### Customer-facing flow

The booking UI fetches public payment settings and calculates an advance percentage from the configured schedule. Short-notice rules can override the percentage. It displays the due-now advance and the scheduled remainder.

```javascript
const bookingAdvance = paymentSchedule.find((row) => row.offset_days == null) || paymentSchedule[0];
let paymentDuePercent = Number(bookingAdvance?.percent ?? 30);

if (hoursToEvent != null && hoursToEvent <= Number(instantRules.very_short_window_hours ?? 48)) {
  paymentDuePercent = Number(instantRules.very_short_window_min_pct ?? 100);
}
const paymentDue = Math.round(bookingTotal * paymentDuePercent) / 100;
```

The server remains authoritative: Easebuzz gets only the first unpaid milestone from `_create_or_get_schedule`, records a `milestone_allocations` audit trail in the payment record, and on success marks that exact milestone paid.

### Settlement calculation

`sync_booking_settlement` derives the share from the received amount and applies it proportionally to commission and artist payable totals.

```python
total = float(schedule.get("total") or pricing.get("total") or 0)
received = float(schedule.get("amount_received") or 0)
share = min(1.0, received / total) if total > 0 else 0.0

commission_credited = round(commission_total * share, 2)
artist_payable_accrued = round(artist_payable_total * share, 2)
```

It persists the settlement snapshot on the schedule and useful summary fields on the booking. `PaymentTimeline` then displays commission credited, artist payable accrued, and the remaining artist payable.

### Why this is useful

It separates three concepts that must not be conflated:

| Concept | Meaning |
|---|---|
| Customer receipt | Amount actually paid by the customer |
| Commission accrual | BookTalent revenue earned in proportion to receipt |
| Artist payout | Money released to an artist; separately tracked from accrual |

### High-priority tests and review items

1. Test 30%, 90%, and 100% milestone payment paths; include multiple bookings in a single gateway batch.
2. Ensure configured milestone percentages add to 100 and values are non-negative.
3. Test repeated gateway callbacks: a paid milestone must not add `amount_received` twice.
4. Use `Decimal` (or integer paise) for future financial work. `float` plus `round` is workable but can produce rounding edge cases.
5. Confirm the schedule `total` uses the same business amount as the commission basis. The code intentionally uses schedule total first, so that relationship needs a business test.

## Current uncommitted working tree state

At documentation time, these changes are not committed and are therefore not part of the twelve-commit case study:

- `frontend/package.json`: adds `"proxy": "http://127.0.0.1:8001"`. This lets the CRA/CRACO development server proxy API requests to the local backend, which is particularly relevant to cookie-authenticated media/agreement requests.
- `docs/BookTalent changes and Requirement 12 Sep26.pdf`: deleted locally.
- `docs/BookTalent_BRD.pdf`: present as a new, untracked local file.

The documentation intentionally does not alter or restore those files.

## Suggested verification checklist

Run these tests before treating the day’s work as production-ready:

1. Price-quote unit tests for normal/service artists, GST/no GST, coupons, and legacy pending bookings.
2. API tests proving every protected numeric field rejects negative input with 422.
3. Homepage API tests proving `kyc_status != live` and `suspended == true` never appear in any rail or category count.
4. KYC tests for invalid dates, future DOBs, authenticated media blob access, and unauthenticated media rejection.
5. Browser test under React Strict Mode showing one page visit creates one `analytics_events` document and one counter increment.
6. Easebuzz callback tests for the first installment, retry/callback replay, partial commission accrual, and multi-booking allocations.
7. Manual test of a popup-blocking browser and production cookie settings for agreement download.

## Reusable lessons for future AI-assisted coding

- Ask the AI to identify the **source of truth** before asking it to patch a feature.
- Give it real invariants: “only live unsuspended artists can be public”, “one visit counts once”, and “commission follows money received”. Those lead to testable code.
- Ask for backward compatibility explicitly when stored documents have older shapes.
- Treat generated code as a first implementation, then review permissions, duplicate callbacks, financial precision, migrations, and tests yourself.
- Keep commits narrow and name them by the user-visible/business outcome, as this history generally does. It makes later investigation and documentation much easier.
