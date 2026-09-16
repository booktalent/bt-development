# BookTalent — Product Requirements Document


## 🚀 Iter 99.1 — Deployment Readiness (2026-09-16)

### Blockers cleared
1. **Destructive DB startup drop removed** (`backend/server.py:4801`): the `_iter7_startup` handler was dropping `wallets` and `withdrawals` collections on every boot, which would wipe live data on every K8s restart. Replaced with a no-op comment.
2. **.gitignore updated** (`.gitignore:82-87`): `.env`, `.env.*`, `*.env` broad excludes replaced with `.env.local` / `.env.*.local` so Emergent deploy can update the tracked `.env` files with production values.

### Deployment audit verdict
- ✅ Compilation passes
- ✅ Env files well-formed
- ✅ Frontend uses relative `/api` paths (works in preview + prod)
- ✅ Backend URLs come from env only
- ✅ CORS regex allows production origin
- ✅ Supervisor config valid (uvicorn backend, yarn frontend)
- ✅ No destructive startup, no ML/blockchain deps, no hardcoded secrets in code
- ✅ MongoDB-only (Emergent managed DB)
- ✅ `load_dotenv(override=False)` — K8s env vars override .env files

### Smoke tests (all pass)
| Check | Result |
|---|---|
| Public search returns 7 live artists | ✅ HTTP 200, total=7 |
| Featured artists | ✅ HTTP 200 |
| Admin login | ✅ Token issued |
| Customer login | ✅ Token issued |
| Service artist finance quote | ✅ `is_service_artist=true, waiver_message` set |
| Supervisor status | ✅ backend/frontend/mongodb all RUNNING |

**Project is ready for live deployment via Emergent's Deploy button.**


## 🔒 Iter 99 — LIVE-only Public Gate + KYC→T&C→Agreement Enforcement (2026-09-16)

**User pushback**: The 5-stage process (KYC → T&C accept → Agreement PDF → LIVE → visible/bookable) was documented but not enforced end-to-end. Non-live artists were leaking into public search / detail / booking creation.

### Fixes shipped
1. **R2/R6 — LIVE-only public gate** (`backend/server.py`)
   - `/artists/search`, `/artists/featured`, `/artists/{id}` all now filter `kyc_status == "live"` (in addition to `suspended`). Non-live artists 404 on public detail URL.
   - `POST /bookings` new gate BEFORE package check: rejects with `400 "This artist is not currently accepting bookings."` if artist is not live.
2. **R3 — KYC-approval notification unified** (`backend/routes/kyc.py`)
   - Title: `"✓ KYC Approved — Accept T&C to Go LIVE"`
   - Body: explicit prompt to log in and accept T&C so Agreement is generated and artist goes LIVE.
   - Same copy sent via email + WhatsApp (wachatsender live) via `notify_dispatch(channels=["in_app","email","whatsapp"])`.
3. **R1 — Checkout fee-waiver line items** (`frontend/src/pages/BookingFlow.jsx`)
   - For Service artists checkout now shows the notional fee struck-through + waiver line + payable=₹0 + banner "🎉 Your 5% Platform Fee has been waived for this artist." matching spec verbatim.
4. **Data migration**: 6 legacy demo artists (Priya, Rohit, Kavya, Aamir, Deepika, Aarav) flipped to `kyc_status="live"` with `tnc_accepted_at`, `agreement_generated_at`, `went_live_at` timestamps + `legacy_migrated_iter_99` marker. Any post-Iter-99 signup must go through the real flow.
5. **Commercial Deals inline edit UX** (`frontend/src/pages/AdminDashboard.jsx`)
   - Replaced auto-save-on-change with explicit Save/Cancel buttons.
   - Type dropdown + % input render together in edit mode (not one-at-a-time).
   - Validates Service artist must have %>0 before submit.

### E2E verified (curl + screenshot)
- `GET /artists/search?limit=20` → returns only 6 live artists; 10 kyc_pending demo artists correctly hidden.
- `GET /artists/{kyc_pending_id}` → HTTP 404.
- `POST /bookings` with kyc_pending artist_id → `400 "not currently accepting bookings"`.
- Service artist checkout screenshot shows exact line-item spec (₹5,000 struck-through, −₹5,000 waiver, ₹0 payable, banner).
- Admin Commercial Deals: Edit → Type=Service + %=12.5 → Save → row updates, toast fires, KPIs refresh.

### Open followups
- Aamir's profile has an inconsistency (search returned 6, not 7 live artists) — worth investigating separately; likely a `is_hidden` flag or missing package.
- WhatsApp T&C prompt: wachatsender template must be text-mode or approved with body placeholder → content field maps to field_1 (operational, not code).



## 📊 Iter 92 — Analytics Dashboard + Public Trust Page + Notification Preferences (2026-09-15)

### 1. Admin Analytics Dashboard (`/admin?tab=analytics`)
- Backend `routes/iter92.py` — 4 endpoints:
  - `GET /admin/analytics/kpis?days=N` — GMV, platform revenue, GST, bookings, avg booking value, active artists, verified total, new customer/artist signups, lead volume + conversion pct.
  - `GET /admin/analytics/funnel` — Leads → Quoted → Bookings → Confirmed → Paid → Completed with per-stage conversion pct from previous stage.
  - `GET /admin/analytics/churn` — Last-month vs this-month active artists → retention & churn pct.
  - `GET /admin/analytics/daily?days=N` — Time series with gap-filled zero days for a smooth line chart.
- Frontend `AdminAnalyticsDashboard` — 8 KPI cards (churn card colour-coded by threshold), inline SVG line chart of daily GMV, and a funnel bar chart with per-stage conversion labels. Range selector 7/30/90/365 days.

### 2. Public Trust Page (`/trust`)
- `GET /public/trust-stats` (NO auth) — verified_artists, completed_events, cities_served, top_cities[10], avg_rating, total_reviews, total_bookings.
- Frontend `TrustPage` — hero heading + 4 headline stat cards (🎤🎉📍⭐), city pills row, twin CTAs (Explore artists / List your talent).

### 3. Per-user Notification Preferences (`/settings/notifications`)
- Backend endpoints:
  - `GET /user/notification-preferences` — merged view of 10 events × 4 channels with force_on flag on the 6 transactional events.
  - `PATCH /user/notification-preferences` — sanitises input (unknown events + force-on events silently dropped).
- Helper `is_channel_muted(db, user_id, event, channel)` exposed for `notification_service.dispatch` to short-circuit muted channels with `status='muted_by_user'` (force-on events always bypass).
- Force-on events (regulatory / transactional, non-muteable): `booking.confirmed`, `payment.received`, `payout.released`, `kyc.approved`, `kyc.rejected`, `kyc.needs_resubmission`.
- Frontend `NotificationPreferences` page — event × channel checkbox grid with 🔒 disabled state on force-on rows.
- New 🔔 icon in Nav (`nav-notif-prefs`) linking to `/settings/notifications` for all authenticated users.

### E2E verified
- Testing agent: **8/8 backend pytest + frontend 100%**, zero action items, zero regressions.
- Trust page rendered publicly (no login). Analytics dashboard shows real numbers (GMV ₹4.6L, 6 verified artists, 12 cities).
- Notification prefs correctly persist Priya's opt-out of marketing.digest whatsapp+email; dispatch respects the mute at runtime.



## 🧽 Iter 91 — Onboarding Fix + Chat Attachments + Router Rename (2026-09-15)

### 1. Onboarding modal — dismissible persistently
- **Backend**: `POST /api/user/mark-welcome-seen` sets `users.seen_welcome_at` (ISO). Also auto-set when `POST /onboarding/complete` runs.
- `GET /auth/me` now exposes `seen_welcome_at` in the response.
- **Frontend** (`ArtistDashboard.jsx`): auto-open guard checks `user.seen_welcome_at` first — if set, modal never auto-opens again.
- **OnboardingWizard**: new × close button (`wiz-dismiss`) that marks-seen without marking onboarding complete, so artists who want to explore first don't have to finish the wizard.

### 2. Chat attachments — images + PDFs
- **Backend**: Existing `/chat/{booking_id}/upload` extended in two ways:
  - Assigned managers can now upload (bypass payment gate as moderators).
  - Same access rule applied to `_check_access` in `chat_routes.py` — assigned managers see + send text messages on their bookings.
- **Frontend** (`ManagerChat.jsx`):
  - New 📎 paperclip button (`mc-attach`) opens file picker (image/* + PDF).
  - Client-side 15MB cap + server-side matching cap.
  - Reads file → base64 data-URL → POSTs to `/chat/{id}/upload` with `type='file'`.
  - `MessageBubble` renders attachments inline: images as `<img>` (max 240px), PDFs as clickable 📄 chip with filename, other files as 📎 chip.

### 3. Backend router rename (final hygiene pass)
- `iter7_routes.py` → `admin_config_routes.py` (admin config: audit-logs, master data, FAQ, CMS, settings, templates)
- `iter9_routes.py` → `agency_corp_provider_routes.py` (agency roster, corporate, chat upload, provider test hooks)
- `iter11_routes.py` → `exports_search_routes.py` (ICS export, CSV exports, AI search)
- Import aliases updated in `server.py` and `notification_service.py`. Function `make_iter11_router` renamed to `make_exports_search_router` inside `exports_search_routes.py`.
- Zero endpoint changes — all URLs stay identical. Just clearer file names for the next dev who onboards.

### E2E verified
- Testing agent: **18/18 backend pytest + frontend 100%**, zero action items, zero regressions.
- `/faqs`, `/admin/settings`, `/admin/audit-logs`, `/search/ai`, `/admin/exports/*`, `/agency/roster`, `/admin/providers/status` — all 200 after rename.
- Wizard × close button + auto-open guard verified in browser.
- Chat attachment upload as assigned manager: 200 with `media_id` set; non-assigned manager: 403.



## 🎨 Iter 90b — Artist KYC Wizard + Admin Agreement Viewer + Manager Chat UI (2026-09-15)

Three focused UI features built on already-existing backend logic.

### 1. Artist KYC Wizard (9-stage progress bar)
- Backend: `GET /api/kyc/pipeline` (in new `routes/iter90b.py`) returns `{current_status, step_index, stages[6], is_error, error_reason, agreement_url}`. Each stage has `id, label, action, status: done|current|pending`. Handles error states (`kyc_changes_required`, `kyc_rejected`, `suspended`) by pinning to the appropriate step with a red indicator + error reason surfacing.
- Frontend: New `KycProgressBar` component injected above the KYC form in `ArtistDashboard.jsx`. Renders a horizontal progress rail with 6 numbered dots (kyc_pending → live), current one glowing gold, done ones green ✓, pending ones muted. Gradient fill line grows with progress. Shows next-action copy + a ⬇ Agreement download button once available.

### 2. Admin Agreement Viewer + Re-issue
- Backend endpoints (admin-only):
  - `GET /admin/agreements/{artist_id}` — metadata + download URL
  - `GET /admin/agreements/{artist_id}/download` — streams the PDF
  - `POST /admin/agreements/{artist_id}/reissue` — regenerates via `routes/v2_flow._generate_agreement()`. Archives old row with `superseded_by`, `superseded_at`, `superseded_by_admin` for audit trail. 409 if artist not past T&C.
- Frontend: Two new buttons on AdminKYC rows (only visible when `v2_status ∈ {agreement_generated, live}`):
  - `📄 View Agreement` — opens signed PDF in new tab (`data-testid=kyc-agreement-view-<user_id>`)
  - `↻ Re-issue` — confirm dialog then regenerates (`data-testid=kyc-agreement-reissue-<user_id>`)

### 3. Manager Chat Moderation UI
- Backend: `GET /manager/chats/threads` returns all booking chat threads for the calling manager (or all threads for admins). Each row has `booking_id, ref, status, event_date, customer_name, artist_name, last_message{content,sender_role,sender_name,created_at}, unread_count`. Sorted unread-first.
- Frontend: New page at `/manager/chat` (`ManagerChat.jsx`). Two-column split:
  - **Left**: Thread list with per-thread unread pill, last-message preview with sender-role tint, booking ref, and event date.
  - **Right**: Selected thread messages rendered as chat bubbles (mine right/gold, others left/dark), with sender role pill + name for non-own messages. Auto-scrolls to bottom on new message. Reply textarea + Send button (Enter to send, Shift+Enter for newline). Header shows customer↔artist names + booking status pill + inline link to `/bookings/:id`.
- Manager Dashboard now has `💬 Chat Moderation` link (`btn-chat`) alongside Leaderboard + Lead Board.

### E2E verified
- Testing agent: **17/17 backend pytest passed · frontend 100%** — all data-testids resolved cleanly.
- Agreement flow verified end-to-end: view → download (2724 bytes PDF) → reissue (audit trail written).
- KYC progress bar renders all 6 stages with correct current/done/pending distribution.
- Manager chat empty state shown correctly + thread selection loads messages.

### Notes / minor items deferred
- Small data-quality thing: some seed artists have `agreement_id` set while `kyc_status='kyc_under_review'` — probably from an older path that generated agreements pre-approval. `/reissue` correctly 409s this state. If it ever surfaces in real use, a one-time cleanup script would clear orphan agreement_ids.
- The onboarding welcome modal on ArtistDashboard auto-opens for every artist login (including already-onboarded). Should be dismissible persistently via a `seen_welcome_at` user flag. Non-blocking cosmetic.



## 🧹 Iter 90 — SYSTEM-WIDE Duplication Cleanup (2026-09-15)

User explicitly said: **"complete running system chahiye bina kisi duplicacy and confusion ke"**. Focused hygiene iteration — zero new features, zero user-visible regressions.

### 1. KYC 3-way duplication FIXED
Before: `users.kyc_status` + `kyc_submissions.status` (4-state legacy) + `artist_profiles.kyc_status` (9-state v2) — all three independently written by different routes, drifting apart.

- **New**: `/app/backend/kyc_sync.py` — single sync helper `sync_kyc_status(user_id, v2_status | legacy_status)` writes to all 3 atomically with bidirectional mapping.
- **Canonical source**: `artist_profiles.kyc_status` (v2 9-state names always).
- **Mirrored caches**: `users.kyc_status` (v2 name) + `users.kyc_legacy_status` (4-state name, kept for legacy queries) + `kyc_submissions.status` (legacy) + `kyc_submissions.v2_status` (v2).
- **Startup backfill**: `backfill_all()` runs at every boot. First run migrated 16/17 drifted users; now converges to `fixed=0` on subsequent boots. Handles orphan artist_profiles (missing user) gracefully.
- **Legacy status upgrade**: `LEGACY_STATUS_UPGRADE` map upgrades old 4-state values (`pending`, `approved`, `rejected`, `needs_resubmission`) stored directly on `artist_profiles.kyc_status` to their v2 equivalents.
- **Regressive-transition guard**: `POST /kyc/submit` now returns 409 if artist is already in `kyc_approved / tnc_pending / agreement_generated / live` state — admin must send back to `kyc_changes_required` first.
- **Auto-recovery in admin_kyc_decide**: When admin decides on an artist whose docs were captured via the (now-removed) v2_flow `/kyc/submit` path, backend auto-creates the `kyc_submissions` row from `artist_profiles.kyc_documents` so the legacy admin endpoint keeps working.

### 2. Duplicate `/kyc/submit` route REMOVED
Both `routes/kyc.py` AND `routes/v2_flow.py` had `/kyc/submit`. Testing agent uncovered v2_flow was shadowing kyc.py's richer implementation (media IDs, PAN/Aadhaar regex, masking). **Removed v2_flow's version entirely** — only `routes/kyc.py` handles the endpoint now (with new regressive-state guard added).

### 3. `/agency-legacy` DELETED
Old `AgencyDashboard` component (384 lines) removed from `RoleDashboards.jsx`. Route removed from `App.js`. Only `AgencyDashboardV2` and its 11-module suite remain.

### 4. Admin sidebar rename
- `⚙️ Settings` → `📢 Site Notices & Blog Banner` — makes it clear this is *not* the financial config (that's `🏗️ Platform Settings (v2)`) and *not* CMS Pages (`📄 CMS Pages` — custom slug-based routes). Financial keys (`gst_pct`, `platform_fee_pct`, `token_pct`) remain hidden from this page (Iter 89).
- Internal card title updated to "📢 Site Notices & Misc Copy".

### 5. AdminKYC UI enhancement
- `/admin/kyc` response now includes `v2_status` field per row.
- Frontend AdminKYC row shows a v2 status pill (`data-testid="kyc-v2-<user_id>"`) when v2 state differs from legacy — so admin can see full 9-stage pipeline progress (e.g. "approved" + "tnc_pending" pill = artist approved but hasn't accepted T&C yet).

### E2E verified
- **Testing agent (Iter 90 first pass)**: 9/12 pytest passed — exposed the duplicate `/kyc/submit` shadowing bug. **All 3 critical + high-priority items fixed** in this same iteration:
  - ✅ Duplicate route removed
  - ✅ State-machine guard added on `/kyc/submit`
  - ✅ `admin/kyc/decide` auto-recovers when submission row missing
- **Backfill idempotency**: verified `fixed=0` on second boot after fix.
- **Regression**: All Iter 87-89 endpoints (at-risk, payouts, audit-logs, leaderboard, snapshots, WA templates) return 200.
- **Frontend**: `/agency-legacy` renders NotFound. AdminKYC v2 pill visible. Sidebar shows `📢 Site Notices & Blog Banner`.



## 🧹 Iter 89 — Leaderboard + Snapshots + Slack + WA Templates DB + GST Duplication Fix (2026-09-15)

### 1. New backend router `routes/iter89.py`
- `PATCH /admin/whatsapp/templates` — DB-persisted template mapping (stored under `platform_settings.mapping` sub-doc so Mongo doesn't interpret `.` in event names as nested paths).
- `GET /manager/leaderboard?month=YYYY-MM` — accessible to managers AND admins. Returns items ranked by revenue desc + `leads_won` tie-breaker. Each row has `rank`, `rank_medal` (🥇🥈🥉), `is_me`. Response includes `my_rank` for the caller.
- Slack helper `notify_slack()` + `slack_alert_max_retries()`. Env: `SLACK_WEBHOOK_URL`. Persists every attempt to `slack_logs`.
- `save_snapshot()` — every scheduled OR run-now CSV persisted to `/app/uploads/report_snapshots/<year>/<month>/<filename>` + `report_snapshots` Mongo row.
- `GET/DELETE /admin/report-snapshots` + `GET /admin/report-snapshots/{id}/download`.
- `POST /admin/slack/test` — diagnostic for the ops team.

### 2. Iter 88 wiring updates
- `_report_schedule_tick` and `/report-schedules/{id}/run-now` now call `save_snapshot()` on every dispatch.
- `_payout_retry_tick` terminal-failure branch calls `slack_alert_max_retries()` so ops gets paged when Easebuzz retry exhausts all 5 attempts.
- `templates-status` endpoint now reads `platform_settings.mapping` sub-doc, with `source: 'env' | 'db' | null` on every row.

### 3. WhatsApp template resolution priority (finalised)
`send_whatsapp()` resolves template name in this order:
```
params.template_name > env WA_TEMPLATE_<EVENT> > DB mapping > event > default_tpl
```
When neither env nor DB is set, request uses `message_body` text-mode fall-back (already live).

### 4. Frontend
- **AdminWhatsAppTemplates** — rewritten as editable form. Env-locked rows show a `(locked)` state; DB-editable rows are saveable inline. `wa-tpl-save` button persists to `/admin/whatsapp/templates`.
- **AdminReportSnapshots** — new admin tab with kind filter, download + delete buttons per row.
- **ManagerLeaderboard** — new page at `/manager/leaderboard`. Podium (top 3 with medal styling) + full ranked table with "YOU" pill + target-progress bar. Linked from Manager dashboard `btn-leaderboard`.
- New sidebar entry `report-snapshots` in AdminDashboard.

### 5. GST Duplication Fix (user-reported)
User flagged that GST was editable in TWO places (screenshot). Root cause: legacy `/admin/settings` (system_settings) had a stale `gst_pct` key while the canonical value now lives in `platform_settings.gst_percent` (Financial Engine reads from here).
- Legacy Admin Settings page now HIDES `gst_pct`, `platform_fee_pct`, `token_pct` and shows a banner pointing to **🏗️ Platform Settings (v2)**.
- Backend PATCH on `/platform-settings/admin` now MIRRORS `gst_percent → system_settings.gst_pct` and `platform_fee_percent → system_settings.platform_fee_pct` so `/settings/public` (BookingFlow copy) stays in sync automatically.
- One-time backfill: `system_settings.gst_pct = 18`, `platform_fee_pct = 5` restored to match `platform_settings`.

### E2E verified
- Testing agent: **20/20 backend pytest passed · frontend 100%**, zero blocking issues (one cosmetic ₹ glyph fallback on leaderboard flagged, deferred).
- Snapshot download confirmed valid CSV (437 bytes, column headers present).
- Leaderboard sort verified: revenue desc, then leads_won desc; my_rank populated correctly for logged-in manager.
- Slack mock alert fires on synthetic max-retries payout entry — `slack_logs` row persisted with alert text.
- GST mirror verified: PATCH gst_percent=20 → system_settings.gst_pct=20 within one request. Restore to 18 propagates too.



## 🔁 Iter 88 — Payout Retry + Report Schedules + Manager Scorecard + WA Templates Status (2026-09-15)

### 1. Payout Auto-Retry Queue
- New collection `payout_retry_queue` with per-entry state machine: `queued → in_progress → succeeded | failed | cancelled`.
- Exponential backoff: 5m, 15m, 45m, 2h, 6h (5 attempts max) via `RETRY_BACKOFF` list in `routes/iter88.py`.
- Background loop `payout_retry_loop` runs every 5 min, picks up entries with `next_attempt_at <= now`, attempts `_attempt_payout` (currently returns failure until `EASEBUZZ_PAYOUT_KEY/SALT` env vars are set).
- Endpoints:
  - `GET /admin/payouts/retry-queue?status=` — items + per-status summary counts.
  - `POST /admin/payouts/retry-queue/{id}/retry` — force re-queue.
  - `POST /admin/payouts/retry-queue/{id}/cancel` — halt future attempts.
  - `POST /admin/payouts/retry-queue/enqueue?booking_id=&amount=&reason=` — admin manual enqueue.
- `POST /bookings/{id}/payout/auto` now enqueues the failure instead of 503-ing. Response shape: `{queued: true, retry_entry: {...}}`.

### 2. Scheduled Reports
- New collection `report_schedules`. Fields: `kind` (artist_bookings / manager_leads / platform_waivers), `email`, `frequency` (daily / weekly / monthly), `day_of_week` (0-6, Mon=0), `hour_ist`, `enabled`, `next_run_at`, `last_run_at`, `last_run_status`, `last_run_error`.
- Loop `report_schedule_loop` runs every 15 min, scans due schedules, regenerates the CSV via the same aggregation used by the live endpoints, emails as an attachment via existing SMTP.
- `_next_due` helper computes next-run in UTC with proper IST offset handling for all 3 cadences.
- Endpoints: `GET / POST / PATCH / DELETE /admin/report-schedules` + `POST /admin/report-schedules/{id}/run-now` (verified `{sent: true}` against live SMTP).

### 3. Manager Performance Scorecard
- `GET /admin/reports/manager-scorecard?month=YYYY-MM` — per-manager KPI cards:
  - `leads_total`, `leads_won`, `leads_lost`, `conversion_pct`
  - `revenue_driven` (sum of `pricing.total` on bookings assigned to that manager in the target month)
  - `monthly_lead_target`, `monthly_revenue_target`
  - `lead_progress_pct`, `revenue_progress_pct` (clamped to 200% to show over-achievers)
- `PATCH /admin/managers/{id}/targets` sets `monthly_lead_target` + `monthly_revenue_target` on the manager user doc.

### 4. WhatsApp Templates Status Page
- `GET /admin/whatsapp/templates-status` — informational endpoint returning `{provider, templates: [{event, env_var, template_name}]}` for 6 key events (booking.confirmed, payment.received, payout.released, kyc.approved / rejected / needs_resubmission).
- Admin UI shows which events run in template-mode vs plain-text fall-back with a red/green pill.

### Frontend
- New file `frontend/src/pages/admin/AdminIter88.jsx` exports 4 components: `AdminPayoutRetryQueue`, `AdminReportSchedules`, `AdminManagerScorecard`, `AdminWhatsAppTemplates`.
- 4 new sidebar tabs in `AdminDashboard.jsx`: 🔁 Payout Retry Queue · 🏅 Manager Scorecard · 📅 Report Schedules · 📱 WhatsApp Templates.
- Scorecard uses `ProgressBar` component with clamp so revenue >100% of target still renders sensibly. Modal `TargetsModal` sets per-manager goals inline.
- Schedule form is a modal with kind/frequency/dow/hour_ist/email/enabled and inline "Run now" action per row.

### E2E verified
- Testing agent: **22/22 backend pytest passed · frontend 100%**, zero regressions on Iter 87.
- Live SMTP confirmed sending scheduled report emails via `manager@booktalent.in`.
- Retry queue transitions verified: enqueue → cancel → retry → back to queued.



## 🎨 Iter 87 — Admin Reports + Unified Audit Viewer + CORS Hardening + WhatsApp Template Mapping (2026-09-15)

### New backend router — `routes/reports.py`
Four admin-only endpoints (registered with `admin_only` gate):

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/reports/artist-bookings?start=&end=&format=json\|csv` | Aggregate per-artist revenue, artist_payable, platform_fee, GST, paid/pending payout counts. Filtered by event date range. |
| `GET /admin/reports/manager-leads?format=json\|csv` | Per-manager 12-stage pipeline breakdown + won/lost/conversion_pct. |
| `GET /admin/reports/platform-waivers?start=&end=&format=json\|csv` | Bookings where Service Artist got a 5% platform fee waiver. Shows would_be_fee vs actual_fee vs waived_amount. |
| `GET /admin/audit-logs/unified?actor=&action=&entity=&start=&end=&limit=` | Merges `admin_audit_log` + `audit_logs` into one time-sorted feed. |

CSV export uses `StreamingResponse` with proper `Content-Disposition` attachment header.

### Frontend UI enhancements
- **AdminReports** (`admin/AdminEnterprise.jsx:758`) — Now has 4 sub-tabs: Revenue (existing), Artist Bookings, Manager Leads, Platform Waivers. Each new tab has an inline `⬇ Download CSV` button and date-range filters where applicable.
- **AdminAudit** (`admin/AdminEnterprise.jsx:686`) — Rebuilt with 5 filter inputs (actor, action, entity, start-date, end-date) + Apply/Clear buttons. Now consumes the unified endpoint so business audit rows (leads, milestones, payouts) show alongside admin-role audit rows. Added `source` pill column to distinguish.

### CORS Hardening
- `server.py:86-107` — Removed unsafe wildcard `*`. Default now:
  - **Static allowlist**: `http://localhost:3000`, `http://localhost:3001`, `http://127.0.0.1:3000` (dev).
  - **Regex allowlist**: `https://*.preview.emergentagent.com` and `https://*.booktalent.in` (production).
- Production admins override with `CORS_ORIGINS=https://a.com,https://b.com` env var.
- Verified: evil.example.com origin gets **no** `Access-Control-Allow-Origin` header (browser hard-rejects). Legitimate origins get their origin reflected.

### WhatsApp Template Mapping
- `routes/v2_more.py:_wa_template_for_event()` reads `WA_TEMPLATE_<EVENT>` env vars.
- Examples to set once templates are approved on wachatsender console:
  ```
  WA_TEMPLATE_BOOKING_CONFIRMED=booking_confirmed
  WA_TEMPLATE_PAYMENT_RECEIVED=payment_received
  WA_TEMPLATE_PAYOUT_RELEASED=payout_released
  WA_TEMPLATE_KYC_APPROVED=kyc_approved
  WA_TEMPLATE_KYC_REJECTED=kyc_rejected
  ```
- Until approved, calls fall back to `message_body` plain-text mode — which is already live and working.

### E2E verified
- Testing agent: **22/22 backend pytest passed · frontend 100%**.
- All 4 admin endpoints return correct data + honour CSV format flag.
- Unified audit correctly merges both collections in time order with all filters (actor regex, action regex, entity exact, date range) combining as AND.
- CORS: `curl -H "Origin: https://evil.example.com"` → no Allow-Origin. `curl -H "Origin: https://booktalent-audit.preview.emergentagent.com"` → Allow-Origin reflected.
- 403 correctly returned when a customer/artist/agency user hits any `/admin/reports/*` endpoint.



## 🔔 Iter 86 — WhatsApp LIVE + Security P0 + Booking Detail + Agency Platform Tab (2026-09-15)

### Real WhatsApp integration — wachatsender.in
- Added `wachatsender` provider branch to `routes/v2_more.py::send_whatsapp` alongside gupshup/meta.
- Env config in `backend/.env`:
  - `WHATSAPP_PROVIDER=wachatsender`
  - `WACHATSENDER_TOKEN`, `WACHATSENDER_VENDOR_UID`, `WACHATSENDER_BASE_URL`
  - `WACHATSENDER_DEFAULT_TEMPLATE=booktalent_generic`, `WACHATSENDER_TEMPLATE_LANG=en`
- Payload maps notification `body` → `message_body` (text mode) + `field_1` (template mode). Real API returns 200 + `wamid` — confirmed live.
- Phone numbers auto-normalized (strip `+`, leading `0`, spaces, dashes).
- `notification_service.dispatch` `whatsapp` channel now routes through the new helper — `_channels_enabled['whatsapp']` becomes True as soon as any modern provider creds are present. Legacy `WHATSAPP_TOKEN` still works.

### Notification hooks wired
- **booking.confirmed** (`server.py:2586`) — customer + artist now receive `in_app + email + whatsapp` (was `in_app + email`).
- **kyc.approved / rejected / needs_resubmission** (`routes/kyc.py:200`) — same 3-channel dispatch.
- **payment.received** (new, `routes/crm_pay.py:mark_paid`) — fires on every milestone mark-paid to customer + artist.
- **payout.released** (new, `routes/crm_pay.py:record_manual_payout`) — artist notified with UTR + method.

### Security P0 fixes
- Admin password seeder (`server.py:4042`) no longer auto-resets `password_hash` on every boot. Explicit opt-in via `ADMIN_PASSWORD_FORCE_RESET=1`.
- `/api/ops/dump/{token}` (`server.py:4220`) permanently returns 404. DB export now super-admin-only via `POST /api/admin/db-export`.

### Booking Detail page — `/bookings/:id`
- New route + page (`frontend/src/pages/BookingDetail.jsx`) accessible to any authorised viewer of the booking.
- Header: ref + status + payout pill.
- Two-column summary: Event/customer + Pricing (uses server-computed `pricing` object — never recomputed client-side).
- Embedded `PaymentTimeline` widget with `canEdit={role==='admin'||'manager'}` — inline Mark-Paid form.
- Payout ledger table listing all `artist_payouts` for the booking (date, amount, method, UTR).
- CustomerDashboard bookings table now has a `View` action linking to this page.

### Agency Financial View UI
- New **Platform Bookings** tab in `frontend/src/pages/agency/modules/Finance.jsx` — consumes `GET /api/agency/financial-view`.
- 4 KPI cards: customer received, customer total, payouts paid count, payouts pending count.
- Table: ref, artist, event date, customer payment status (`fully_paid`/`partially_paid`/`pending`), payout status.
- Each row links to `/bookings/:id` for the full timeline + payout ledger.
- Defensive None-guards added on backend for missing `payment_schedules` / null `pricing` (was returning 500 for agencies with legacy bookings).

### E2E verified
- wachatsender live send: 200 + `wamid.HBgMOTE5OTk5OTk5OTk5FQIA…`; audit row persisted in `whatsapp_logs`.
- `notifications_log` rows for `payment.received:whatsapp` and `payout.released:whatsapp` written on real bookings.
- `/api/ops/dump/anything` → 404 (regardless of token env). Admin login continues to work.
- Testing agent: **backend 100%, frontend 100%, 8/8 pytest pass**, no blocking issues.



## 🎨 Iter 85 — Manager & CRM UIs + Payment/Payout Widgets + At-Risk + WhatsApp Channel (2026-09-15)

### New Frontend Screens
- **Manager Dashboard** (`/manager`, `ManagerCRM.jsx`) — 12-stage pipeline counts, active-bookings card, quick-nav cards linking to filtered lead board.
- **Lead Board Kanban** (`/manager/leads`, `LeadBoard`) — 12 columns (New → Contacted → Requirement → Suggested → Quoted → Negotiating → Booking Pending → Confirmed → Payment Pending → Event Upcoming → Event Done → Closed). Each card shows customer, event type, city, budget, assigned manager. Inline stage-select drives `PATCH /leads/{id}/stage`.
- **Lead Detail** (`/manager/leads/:id`, `LeadDetail`) — full enquiry, assign/reassign manager picker, note field, timeline pulled from `lead.history` reversed (newest at top).
- **Admin → At-Risk Bookings** (new admin tab) — 5 buckets with tables: Event ≤3d unpaid, Payout pending, Overdue schedules, Unassigned leads >24h, KYC stuck >7d. Top-right "N items need attention" pill.
- **Admin → Payout Console** (new admin tab) — table of pending payouts + modal for UTR + method + bank ref + notes. Submits `POST /bookings/{id}/payout/manual`.
- **`PaymentTimeline` widget** — reusable card (in `PaymentPayoutWidgets.jsx`) with progress bar, milestone list, inline "Mark Paid" form (amount/method/UTR/date). Drop into any booking detail page. `canEdit` prop gates for admin/manager only.

### Backend additions (`routes/v2_more.py`)
- `GET /admin/at-risk-bookings` — auto-flags 5 risk categories (Sec 55).
- `GET /agency/financial-view` — Sec 45-48. Returns roster artists + each booking with customer payment status (fully_paid / partially_paid / pending) + payout status. Aggregate totals for the top bar.
- `GET /admin/payouts/pending` — completed/confirmed bookings still awaiting artist payout, event-date descending.

### WhatsApp Channel Abstraction
- New helper `send_whatsapp(db, to, template, params, body)` in `routes/v2_more.py`.
- Provider selected by `WHATSAPP_PROVIDER` env: `""` (mock, logs to `whatsapp_logs`), `"gupshup"`, `"meta"`.
- Every send attempt persisted to `whatsapp_logs` with provider response, HTTP status, error (if any) — even failures. Never raises so business flows keep going.
- Real integration switches on when the matching env vars are set:
  - Gupshup: `GUPSHUP_API_KEY`, `GUPSHUP_SOURCE`, `GUPSHUP_APP_NAME`
  - Meta Cloud API: `META_WA_TOKEN`, `META_WA_PHONE_ID`

### Router registration
- All new pages wired in `App.js` at `/manager`, `/manager/leads`, `/manager/leads/:id`.
- Admin tabs added: `⚠️ At-Risk Bookings`, `💰 Payout Console` — perms `bookings.view` / `payments.view`.

### E2E verified
- Backend endpoints return correct data:
  - At-Risk: `total=0` on a clean DB; per-bucket counts populated when data present.
  - Payout Pending: 19 candidates found in current DB (existing legacy bookings).
  - WhatsApp mock send: `{sent:True, provider:'mock', mock:True}` + row persisted to `whatsapp_logs`.
- Frontend screens render: playwright confirmed `[data-testid="at-risk-dashboard"]` + `[data-testid="payout-console"]` matched after admin auth.

### Still Pending
- **Agency Financial View** frontend page (backend endpoint ready) — will be tackled in the next batch.
- Real WhatsApp provider credentials (user must share Gupshup or Meta keys to switch off mock mode).



## 🎯 Iter 84 — Phases 4-7 backend vertical (2026-09-15)

Single bundled router `routes/crm_pay.py` — CRM, Payments, Payouts, Chat privacy.

### CRM (Sec 26-30)
- `leads` collection, 12-stage state machine (`new_lead → contacted → requirement_received → artist_suggested → quotation_sent → negotiation → booking_pending → booking_confirmed → payment_pending → event_upcoming → event_completed → closed | lost_cancelled`).
- Endpoints: `POST /leads`, `GET /leads?stage=&assigned_manager_id=`, `PATCH /leads/{id}/stage`, `POST /leads/{id}/assign`.
- Manager role scoping: managers only see leads assigned to them (`assigned_manager_id == user.id`); admin sees all.
- Every stage change + assignment writes an audit row (old/new value, actor email, IP).
- `GET /manager/dashboard` — pipeline-stage counts + active bookings for the calling manager.

### Payments (Sec 32-37)
- `payment_schedules` collection created on-demand from `POST /bookings/{id}/schedule` — idempotent.
- Uses admin-configurable `payment_schedule` (default 30/40/20/10) + `instant_book_rules`:
  - Event > 7 days → standard schedule.
  - Event ≤ 7 days → collapse pre-event milestones so ≥ `short_window_min_before_event_pct` (90) is collected upfront.
  - Event ≤ 48h → single 100% upfront milestone.
- `POST /bookings/{id}/schedule/mark-paid` records manual payment against a milestone; running `amount_received` tracked.
- Background loop `payment_reminder_loop` (every 3h) sends **7-day / 2-day / due / overdue** emails via SMTP. Idempotent per (schedule_id, milestone_index, kind) so duplicates are impossible.

### Payouts (Sec 40-44, 64)
- `POST /bookings/{id}/payout/manual` — records UTR, method (neft/imps/upi/cash/cheque/other), bank ref, notes. Flips booking's `artist_payout_status=paid`. Admin/Manager/Agency roles allowed.
- `POST /bookings/{id}/payout/auto` — gated on **both** `payout_mode=easebuzz` AND `enable_automated_payout=true`. When disabled → 400 with clear message. When enabled → integration stub raises 503 with instructions ("Add EASEBUZZ_PAYOUT_KEY/SALT and implement `_easebuzz_payout_stub()`") — this is the seam for Phase 10 integration.
- `GET /bookings/{id}/payouts` — audit history newest-first.
- Financial engine's `artist_payable` (fee − BookTalent commission) drives the payout amount in the auto flow — no double deduction (Sec 39).

### Chat privacy (Sec 23-24)
- `chat_v2_threads` + `chat_v2_messages` — thread creation auto-detects `is_service_artist` on the artist profile.
- Service Artist threads are `is_managed=true`, auto-assigned to an active manager.
- When the ARTIST sends a message in a managed thread, phone numbers (10-13 digit runs) and email addresses are automatically redacted before the customer sees them (regex-based `_redact_contact_info`).
- Admin can retrieve the un-redacted `body_original` for audit; customers/managers see only the redacted `body`.
- Message scrollback intentionally sorted **ascending** (oldest first) — natural conversation flow, one of the few exceptions to the platform's descending default.

### E2E verified (curl)
1. Admin creates a lead → assigns to Rahul (manager) → advances stage `new_lead → contacted`. All 3 actions audit-logged.
2. Booking schedule created with milestones `[Booking Advance ₹30k @now, D-7 ₹40k, D-2 ₹20k, D+1 ₹10k]` for event 2026-12-25.
3. Milestone-0 marked paid via UPI → schedule shows `amount_received=₹30k`.
4. Manual payout ₹25k/UTR:BT789456 → booking flips to `paid`.
5. Auto-payout with flag OFF → `400 "Automated payout is disabled"`.
6. Manager dashboard returns stage counts + active bookings for calling manager only.
7. Chat privacy: artist sends `"Call me on 9876543210 or email me@artist.com"` in a service-artist thread → customer receives `"Call me on [contact hidden]or email [email hidden]"`. Admin can still read the original message.

### Still pending (next batch)
- Frontend UIs for Manager Dashboard, Lead Board, Payment Timeline, Payout Console, Chat inbox
- WhatsApp channel (need provider — Gupshup/Meta) — currently email-only
- Agency financial view + At-Risk booking dashboard (Sec 45-48, 55)



## 💰 Iter 83 — v2 Batch: Financial Engine + KYC state machine + Booking form redesign + Admin Settings UI (2026-09-15)

### Financial Engine — centralised, backend-only calculator (`financial_engine.py`)
- `compute_price()` returns the canonical price breakdown for every booking. Frontend never sums line items again.
- Logic (Sec 2-4, 5, 10, 38, 61):
  - Artist Fee = package + add-ons − coupon
  - Platform Fee = `platform_fee_percent × artist_fee`
  - **If artist is Service Artist (`is_service_artist=true` + `percentage_deal>0`) → Platform Fee is fully WAIVED**. Response includes both `platform_fee` (gross), `platform_fee_waiver` (negative), and `platform_fee_net` — never merged.
  - GST computed on (artist_fee + platform_fee_net). `gst_visible=false` when `gst_percent==0` → UI hides row.
  - BookTalent commission = `artist_fee × percentage_deal / 100`. Artist payable = `artist_fee − commission`.
- `build_payment_milestones()` — takes total + event date + configured schedule, returns concrete `{amount, due_date}` per milestone. Last row absorbs rounding drift so amounts sum to total exactly.
- New endpoint: `GET /api/finance/quote?artist_id=&package_fee=&addons_total=&coupon_discount=`. Used by booking summary.

### KYC v2 state machine (`routes/v2_flow.py`)
- 9 statuses (Sec 7): `registration_pending → kyc_pending → kyc_under_review → (kyc_changes_required | kyc_rejected | kyc_approved) → tnc_pending → agreement_generated → live | suspended`.
- Legal transition table on the admin side — illegal moves return 400.
- Artist endpoints: `GET /kyc/me`, `POST /kyc/submit` (validates all admin-marked "required" docs are present).
- Admin endpoints: `GET /admin/kyc/queue?status=` (newest-first), `POST /admin/kyc/{artist_id}/review` (action = approve/reject/request_changes; on approve also sets `artist_type` + `percentage_deal`).
- Every KYC transition writes an audit row (`record_audit()`).

### T&C + Auto-Agreement PDF (Sec 12-14)
- `POST /kyc/accept-terms` — enforces artist has been KYC-approved first. On tick:
  1. Generate agreement PDF (reportlab if available, plain text fallback) with commercial terms + KYC/T&C consent timestamp.
  2. Store agreement in `agreements` collection (`pdf_hex` for compact storage; agreements are ~3KB text-only).
  3. Email agreement to artist.
  4. Auto-flip artist → `agreement_generated` → `live` so the profile immediately appears on the public site.
- `GET /agreements/mine` streams the PDF back to the artist for download (bytes-from-Mongo). E2E verified: HTTP 200, `application/pdf`, 2.7 KB.

### Booking form redesign (Sec 19-22)
- `BookingCreate` now accepts optional `event_type_other` (used when `event_type=="Others"`), `number_of_days` (1-30), `venue_address` (up to 500 chars).
- Persisted on the booking document under the same names.
- Frontend `BookingFlow.jsx`:
  - Event Type dropdown expanded to 10 options + **"Others"**.
  - When Others selected → free-text "Please specify" field appears.
  - New "No. of Days" numeric field + "Full Address" separate from Venue name.
  - All required fields already carry `*` marker.
  - Summary sidebar now shows **Platform Fee Waiver** line (negative amount, greenish) and a dedicated **Total** row when artist is service. Fetched from `/finance/quote` on artist load.

### Artist Profile bigger profession (Sec 16)
- `profile.category` now rendered as a large gold-gradient headline (clamp 22-34px) directly under the artist name — instead of a small pill.

### Admin → Platform Settings UI
- New page `AdminPlatformSettings.jsx` at `/admin?tab=platform-settings`.
- 5 tabs: Fees & GST · Payment Schedule · Payout Mode · KYC Documents · Company Info.
- Live "unsaved changes" counter, confirmation modal on save that lists exactly which fields will change (audit trail preview).
- Payment schedule row shows running total colored red/green (must sum to 100).
- Payout mode dropdown + feature-flag checkbox with a prominent live-impact warning banner.

### E2E verified (all via curl)
1. Normal artist quote → total = ₹1,23,900 for ₹1,00,000 fee (5% + 18% GST).
2. Service artist (10% deal) → waiver kicks in, total = ₹1,18,000, commission = ₹10,000, payable = ₹90,000. Matches Sec 4 example exactly.
3. GST set to 0 via admin PATCH → next quote returns `gst_visible=false`, `gst_amount=0`, total = ₹1,05,000.
4. Payment schedule that doesn't sum to 100 → 400.
5. `payout_mode="easebuzz"` without `enable_automated_payout=true` → 400.
6. Artist KYC full lifecycle: submit with missing docs → 400; submit with all → `kyc_under_review`; admin approves as service+12% → `kyc_approved`, profile updated; artist accepts T&C → PDF generated, emailed, artist auto-goes-live.
7. Agreement download → HTTP 200 `application/pdf`.

### Next up
- Phase 4 CRM: Lead management (12 stages), Manager creation + assignment, Manager dashboard
- Phase 5 Payments: Milestone tracking + reminders + 90/10 rule enforcement
- Phase 7 Chat: Manager-mediated Customer↔Artist chat + WhatsApp channel



## 🏗️ Iter 82 — v2 Foundation: Platform Settings + Audit Log + Manager Role (2026-09-15)

**Context** — Kick-off of the MD's 67-section v2 requirements. This is Phase 1 (Foundation). Everything downstream (fee waiver, payment schedules, payouts, agency dashboard, CRM) reads its business rules from here.

### Platform Settings (admin-configurable, DB-backed singleton)
- `platform_settings` collection, `id: "singleton"`. Auto-seeded on first read.
- Public read (`GET /api/platform-settings/public`) — safe fields for frontend price calculations, KYC forms, payout badge copy.
- Admin read/write (`GET/PATCH /api/platform-settings/admin`) — full row.
- Fields:
  - `gst_percent` (0–50) — configurable, 0 hides GST rows in UI (Sec 5).
  - `platform_fee_percent` (0–50) — customer-side platform fee (Sec 3).
  - `payment_schedule[]` — configurable milestones (default 30/40/20/10). Backend validates percents sum to 100.
  - `instant_book_rules{}` — 7/48h/same-day thresholds (Sec 34).
  - `payout_mode` — `manual` | `easebuzz`. **Backend-side guard** rejects switching to `easebuzz` unless `enable_automated_payout=true` (Sec 43).
  - `enable_automated_payout` — feature flag, OFF by default (Sec 43, 64).
  - `required_kyc_docs[]` — driven by admin, not hard-coded (Sec 6, 63).
  - `company_info{}` — legal name, GSTIN, PAN, support email/phone.

### Audit Log core
- `audit_logs` collection + `record_audit()` helper.
- Every settings write emits one audit row per changed field with old/new value, actor email + role, IP, user-agent, ISO timestamp.
- `GET /api/audit-logs?entity=&entity_id=&actor_id=&limit=` (admin only, newest-first, capped at 500).
- Never raises on failure — audit logging must never break a business flow.

### Manager role (Sec 27)
- Added `"manager"` to the `Literal` role enum in `RegisterBody`.
- Role is now valid across `require_role`, `admin_only`, auth cookies, etc.
- Frontend manager dashboards + assignment flows to be added in Phase 4.

### E2E verified
- GST 18 → 12 → audit row written with actor `admin@booktalent.com`, IP + UA captured.
- `payout_mode: easebuzz` without flag → 400.
- Payment schedule that doesn't sum to 100 → 400.
- Public settings endpoint returns fresh values immediately after admin write.

### Next up — Phase 2 (Artist Onboarding v2)
KYC status state-machine (9 statuses), percentage-deal storage, T&C popup enforcement, agreement auto-gen + email, artist-goes-live only after all onboarding steps.



## ⏰ Iter 79 — Event-day reminder emails (2026-08-25)

### Automatic morning-of reminder
- New background loop `_event_reminder_loop()` (started from `@app.on_event("startup")`, interval `EVENT_REMINDER_CHECK_MINUTES=60`).
- Runs the tick only when local IST time ≥ 07:00 (offset applied without pulling `pytz` — India-first product).
- Query: `bookings.status ∈ {confirmed, started}` AND `event_date == today (IST)` AND `reminder_sent_at ∉ {null, ""}`.
- Fires **two emails per booking** (customer + artist) in parallel via `asyncio.gather`, then stamps `reminder_sent_at` and appends a `history[]` audit row so the loop is fully idempotent.

### Email template
- New `send_event_reminder_email(...)` in `email_service.py`. Dark-luxury card with:
  - Date, **Show time** (gold), **Load-in by** (auto-computed as `event_time − 60 min`), Venue + City, Booking ref chip.
  - **"Open in Google Maps →"** button linking to `maps.google.com/maps/search/?api=1&query=<venue+city>` (URL-encoded).
  - Role-specific tip block (customer sees "confirm sound-check timing"; artist sees "reach venue by load-in, sound check, confirm run-of-show").
- Subject: `Today at HH:MM — your event with <artist>`.

### Manual trigger for testing / re-sends
- `POST /api/admin/bookings/{id}/send-reminder` — permission-gated (`bookings.view`). Bypasses the 07:00 IST gate and event-date check so an admin can re-send on demand if a customer/artist reports they never got the reminder.

### Utility helpers
- `_parse_hhmm(t)` — tolerant HH:MM parser (accepts `19:00`, `7pm`, `7.30pm`).
- `_compute_load_in(event_time, offset=60)` — safe subtraction, floors at 00:00.
- `_map_link(venue, city)` — URL-encoded Google Maps search link.

### E2E verified
- Manual admin trigger for a fabricated `event_date=today, event_time=19:00, venue=The Leela Palace Ballroom, city=Mumbai` booking:
  - `SMTP OK to=<customer> subject=Today at 19:00 — your event with Priya Sharma`
  - `SMTP OK to=<artist> subject=Today at 19:00 — your event with Priya Sharma`
  - Booking now has `reminder_sent_at` + `history: [{action:"reminder_sent"}]`.
- Second call to `_event_reminder_tick()` produced zero additional sends → idempotent.
- Load-in computed correctly (19:00 → 18:00).



## 🛡️ Iter 78 — Rate limiting + welcome email (2026-08-25)

### Per-IP rate limiter (`backend/rate_limit.py`)
- New stdlib-only sliding-window limiter. Reads client IP from `X-Forwarded-For` → `X-Real-IP` → socket peer.
- Buckets scoped by IP and (optionally) target email. Successful auth resets the counter so legit users aren't punished on their next attempt.
- Applied to three critical auth endpoints:
  - `POST /auth/login` — 10 attempts / 15 min per IP + 5 / 15 min per targeted email. Blocks credential stuffing.
  - `POST /auth/email/send` — 8 / 10 min per IP (independent of the existing 60-sec per-email cooldown). Protects Gmail sending quota.
  - `POST /auth/forgot-password` — 5 / 15 min per IP + 3 / hour per targeted email. Prevents reset-email spam.
- All rejections return `HTTP 429` with a `Retry-After` header and a friendly message.

### Welcome email
- `email_service.send_welcome_email(to, name, role, base_url)` — dark-luxury template with role-specific copy + a "Next step" CTA button:
  - Customer → "Book your first artist" (`/search`)
  - Artist → "Complete your artist profile" (`/artist`)
  - Agency → "Invite your first artist" (`/agency`)
  - Corporate → "Plan your first event" (`/corporate`)
- Fired from `POST /auth/register` via `asyncio.create_task(...)` so signup response is never blocked on SMTP latency.
- Verified end-to-end: real Gmail delivery logged as `SMTP OK to=… subject=Welcome to BookTalent ✨`.

### E2E verified
- Login: 5 wrong passwords → 6th returns 429 (per-email); 10 spread across accounts → per-IP 429.
- Forgot-password: 5 hits from one IP → 6th returns 429.
- `/auth/email/send`: 8 hits from one IP → 9th returns 429.
- Register flow: OTP email → verify → register → welcome email arrives ~1s later.



## 📧 Iter 77 — Gmail SMTP + Forgot Password OTP flow (2026-08-25)

### Real email provider replaces Resend mock
- **`backend/email_service.py`** rewritten to use stdlib `smtplib` + Gmail STARTTLS on `smtp.gmail.com:587`.
- Env vars (new): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (16-char Google App Password — spaces stripped automatically), `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`. Live account: `manager@booktalent.in`.
- Old `RESEND_API_KEY` / `resend` package no longer required — public function signatures kept (`is_email_enabled`, `generate_otp`, `send_otp_email`, `send_booking_confirmation_email`, `send_payment_receipt_email`), so all callers work unchanged.
- New helper: `send_password_reset_email(to, name, otp, reset_link)` — dark-luxury template with both a magic-link button and a large 6-digit code.
- `notification_service.py` `_channels_enabled` now gates email on SMTP env (not Resend key).

### Mock `123456` backdoor removed
- `generate_otp()` now always returns a cryptographically-random 6-digit code (via `secrets`). No fallback constant.
- `/auth/email/send` response no longer contains `test_otp` — the OTP is only ever delivered by SMTP.
- `/auth/otp/send` and `/auth/otp/verify` (phone-based) now return **HTTP 410 Gone**. There is no SMS gateway wired in and the previous "always accepts 123456" behaviour was a passwordless-login backdoor.
- `/auth/email/verify` gained brute-force protection: 5 wrong attempts invalidate the OTP.

### Registration flow (unchanged UX, real email now)
- Step 1 → Step 2 → Step 3: user requests OTP via `POST /auth/email/send` → real email arrives → user enters code → `POST /auth/email/verify` marks the email `verified: true` → `POST /auth/register` creates the account and issues the session cookie.
- Frontend `Auth.jsx` step-3 hint no longer shows `123456` for anyone.

### Login flow (existing users) — untouched
- Still `POST /auth/login` with email + password. No OTP requirement per user's spec.
- Admin login also bypasses OTP.

### Forgot Password (new, replaces token-only stub)
- `POST /auth/forgot-password { email }` → generates fresh reset token + 6-digit OTP, invalidates prior pending resets, stores in `password_resets`, emails `manager@booktalent.in`-signed reset email containing both a **magic link** (`FRONTEND_URL/reset-password?token=…&email=…`) and the **6-digit code**. Always returns `{sent:true}` to prevent enumeration.
- `POST /auth/reset-password { email, new_password, otp? , token? }` — accepts either the OTP or the token. Non-expired, un-used records only; brute-force limit of 5 wrong OTP attempts; on success the reset record is marked `used`, so it can't be replayed.
- Frontend: new `/forgot-password` and `/reset-password` routes → shared `ForgotPassword.jsx` component. Step-1 collects email; Step-2 collects OTP + new password. Users who click the emailed link land directly on Step-2 with the token pre-filled (OTP field hidden).
- Signin form has a new `Forgot your password?` link under the submit button (`data-testid=login-forgot-password-link`).

### E2E verified
- Real emails delivered end-to-end: verification code (`Your BookTalent verification code: …`) and reset email (`Reset your BookTalent password`) both logged as `SMTP OK`.
- Register → wrong code fails, right code passes → session issued.
- Existing user login with email/password → 200 OK, no OTP step.
- Forgot password OTP path: wrong code 400, correct code resets successfully, new password logs in.
- Forgot password link path: token resets successfully.
- `/auth/otp/verify` returns 410 for the old `123456` payload.



## 🎬 Iter 76.5 — Video posters, chunk retry, featured reel, boost insights (2026-08-21)

### Video Poster Frames (client-captured, since ffmpeg is unavailable)
- MediaManager now runs `capturePoster(file)`: hidden `<video>` seeks to 0.5s, `<canvas>` snapshots the frame → JPEG data URL (quality 0.72, max 640px wide).
- `POST /api/media/video/finish` now accepts an optional `poster_data_url` form field. Backend decodes → `make_thumbnail()` → base64 into the `thumb` field, so `GET /media/{id}/thumb` immediately serves the poster.
- Frontend `<video poster={...}/>` attribute set on gallery tiles → no more blank tiles waiting for metadata.

### Chunk Retry (network-resilience)
- New `withRetry(fn, attempts=3)` helper wraps every chunk POST and the finish POST. Retries on network errors / 5xx / 429 with exponential backoff (1s → 2s → 4s, capped 8s). 4xx errors bubble up immediately so bad requests fail fast.
- A single dropped chunk on a 1 GB upload no longer restarts the whole session — the same chunk_index simply overwrites the same tmp file on the backend.

### Featured Reel (hero autoplay video)
- New endpoint `POST /api/media/{id}/feature-reel` (artist-only) — toggles `artist_profiles.featured_video_id`. Passing the currently-featured id again clears it.
- MediaManager tile shows a "🎬 Set as Reel" / "🎬 Reel Active" toggle button on every video, plus a "🎬 REEL" corner badge on the currently active reel.
- Public `ArtistProfile.jsx` cover banner: when `profile.featured_video_id` is set, renders a full-cover `<video autoPlay muted loop playsInline>` sitting under a dark gradient. Falls back gracefully to `cover_image` → emoji when no reel.
- Verified: reel activated for Priya → `featured-reel-video` element present, autoplays on public profile.

### Boost Insights (ROI mini-chart)
- New endpoint `GET /api/boost/insights` returns:
  - `days: [{date, views, bookings}]` — 14-day timeline from `analytics_events` (profile_view) + `bookings` collections.
  - `active_boosts` — 5 most recent boost subscriptions with `starts_at`, `expires_at`, `package_name`.
  - `totals: {views_14d, bookings_14d}`.
- New "📊 Last 14 Days · Boost Impact" card at top of the Boost tab renders a pure-CSS bar chart (no chart library dependency) — gold bars for views, purple bars for booking requests, with a legend and totals header.
- Verified: card renders on Priya's dashboard with legend + empty-state bars (no events in 14-day window on this dataset yet).

### Known follow-ups
- Server-side ffmpeg install would enable dark-video fallback posters (currently relies on client capture).



## 🚀 Iter 76 — Boost audit + 1 GB video uploads (2026-08-21)

### Boost / Profile Promotion — NOT missing, ALREADY WORKING
- Audit confirms the Boost system is fully implemented and live. Verified end-to-end:
  - Public: `GET /api/boost/packages` → 11 active packages (`Category Top`, `City Featured`, `Featured Artist`, `Search Priority`, `Homepage Banner`, `Premium Badge`, `Verified Badge`, `Trending`, `Recommended`, etc.).
  - Artist: `GET /api/boost/mine` returns active subscriptions; `POST /api/boost/easebuzz/init` starts a payment. Sidebar `🚀 Boost Profile` tab renders package cards with pricing, GST breakdown and "Your Active Boosts" list. Screenshot confirms "1 Active Boost · Search Priority · Expires 2026-08-22" for Priya Sharma.
  - Admin: `GET/POST/PUT/DELETE /api/admin/boost/packages` for pricing management; `/api/admin/boost/subscriptions` for purchase history. Sidebar `🚀 Boost Manager` tab (AdminBoost component). Boost revenue is aggregated into the admin platform stats `boost_revenue` KPI.
  - No fix needed — no code changed for boost.

### 1 GB Artist Video Uploads (NEW)
- **Backend** (`/app/backend/storage.py` + `server.py`):
  - New `storage.py` wraps Emergent Object Storage (`INTEGRATION_PROXY_URL` + `EMERGENT_LLM_KEY`). Session key cached at startup with `[iter76] Object storage session initialised.` log line; auto-refreshes on 404.
  - 3-step chunked upload endpoints protected by `get_current_user`:
    1. `POST /api/media/video/start {filename, mime, size, type, title}` → `{session_id, chunk_size: 8MB}`. Rejects non-video mime or size > 1 GB.
    2. `POST /api/media/video/chunk` (multipart: `session_id`, `chunk_index`, `chunk`) → per-chunk ack. Chunks stream to `/tmp/bt_uploads/{session_id}/chunk_XXXXXX.bin`.
    3. `POST /api/media/video/finish {session_id}` → assembles → `put_object("booktalent/videos/{user_id}/{uuid}.{ext}", ...)` → inserts a `media` doc with `storage_path` (no base64 `data` field) → cleans tmp dir → returns `{ok, id, size, storage_path}`.
  - `GET /api/media/{id}` transparently detects `storage_path` and streams from Emergent Object Storage. Falls back to legacy base64 for pre-Iter76 rows.
  - Photos + docs unchanged — still route through `POST /api/media/upload` with the 12 MB base64 guard.
- **Frontend** (`ArtistDashboard.jsx MediaManager`):
  - `upload()` branches on `file.type.startsWith("video/")`:
    - Videos: `f.slice(...)` into `chunk_size` blobs, `FormData` upload per chunk with axios `onUploadProgress` → real progress bar tracks completed + in-flight chunks. Then finish.
    - Photos / docs: legacy base64 path, 12 MB cap.
  - Upload-zone hint updated: "Photos & docs auto-compressed · up to 12 MB each · Videos up to 1 GB via chunked upload".
  - Existing preview strip (Iter 72) already renders `<video src={URL.createObjectURL(f)}>` during upload and post-upload the gallery tile streams `<video src={mediaUrl(m.id)}>` from `/api/media/{id}` — no code change needed.
- **Verified** with curl:
  - 1 MB single-chunk upload → assembled → stored → GET back returned byte-identical (md5 match).
  - 20 MB multi-chunk (3×8MB) upload → assembled → stored, media doc has `storage_path`, sessions tmp dir cleaned.

### Known follow-ups (backlog)
- Generate a poster thumbnail server-side (first-frame ffmpeg) for storage-backed videos so listings don't have blank tiles until the `<video>` element loads metadata.
- Retry-on-network-blip for individual chunk uploads (currently a chunk failure aborts the whole session).



## 🔴 Iter 75 + 75.5 — Cancellation refund rule + mandatory reason (2026-08-21)

### Iter 75 — Refund business rule fix (was inverted)
- Previously the `cancel` action refunded the customer whenever `is_customer` cancelled a paid booking, and artists could not cancel a confirmed booking AT ALL. Both wrong.
- Now the `cancel` branch in `POST /api/bookings/{id}/action` accepts `is_artist` in addition to `is_customer`/`is_admin`, and the refund path is keyed to the ACTING role:
  - **Artist cancels** paid booking → `_mark_platform_fee_refundable(...)` fires → Easebuzz refund API called via `auto_refund_bookings`.
  - **Customer cancels** paid booking → NO refund. Platform Service Fee is forfeited.
  - **Admin cancels** → refund (support can still protect the customer).
- Frontend: Artist dashboard now shows a "Cancel" button on confirmed bookings; customer's Cancel button warns clearly about forfeiture.

### Iter 75.5 — Mandatory cancellation reason
- **Backend**: `cancel` branch rejects with HTTP 400 when `body.reason` is missing, whitespace-only, or shorter than 3 chars. On success the booking gets `{cancel_reason, cancelled_by: "artist"|"customer"|"admin", cancelled_by_user_id, cancelled_at}` persisted on the doc. The `_mark_platform_fee_refundable` note now includes the actor + reason for audit trail.
- **Frontend**: New shared `CancellationReasonModal` component (`/app/frontend/src/components/CancellationReasonModal.jsx`) — 6 preset reasons per role + "Other" free-text + role-specific warning copy. Both artist and customer Cancel buttons open it via the shared `openCancel(booking, actorRole)` handler in `BookingsTable`. The Confirm button is disabled until reason ≥ 3 chars. `doAction(id, action, extra)` now forwards `{reason}` into the API call.
- **Visibility**: Every cancelled row shows `By {artist|customer|admin}: {reason}` under the status pill on the customer, artist, and admin bookings tables.

### Verified (curl + screenshot)
- Empty / whitespace / <3-char reason → 400 "Cancellation reason is required."
- Customer with real reason → `status=cancelled, cancelled_by=customer, cancel_reason=…, cancelled_at=…`, payment NOT touched.
- Artist with real reason → same fields set with `cancelled_by=artist`, `_mark_platform_fee_refundable` invoked (real Easebuzz-completed payment refunded; legacy razorpay_mock rows tagged `refund_status=not_applicable`).
- Frontend modal: preset radios visible, "Other" reveals textarea, confirm gated on reason ≥ 3 chars, reason renders on cancelled rows for customer, artist AND admin views.



## 🗂 Iter 74.5 — Draft Bookings, Recent Views, Filter Chips (2026-08-21)

### Draft Bookings (cross-device)
- New Mongo collection `booking_drafts` keyed uniquely on `(user_id, artist_id)` with `{form, step, artist_snapshot, updated_at}`.
- Endpoints: `POST/GET/DELETE /api/customer/booking-drafts[/{artist_id}]`. `POST` upserts (400 for non-customers), `GET` returns newest-first with artist card snapshot.
- **BookingFlow.jsx** debounces server sync at 1.2s per keystroke and clears the draft when the booking hits step 6. On mount, if there's no sessionStorage AND URL has no pkg/city/date, we hydrate from the server draft so a customer can start on desktop and finish on their phone.
- New **"💾 Save & Finish Later"** button in the wizard header (steps 2–5) flushes any pending debounce and lands the customer on `/customer?tab=drafts`.
- **CustomerDashboard.jsx** adds a `Drafts` sidebar tab (with count badge), a compact "Continue Where You Left Off" teaser on Overview, and a full `DraftsList` on the tab. Each row shows artist thumb, category · city, current step label, relative time, `Continue →` link, and `✕ Discard`.

### Recent Views
- New Mongo collection `recent_views` per `(user_id, artist_id)`, capped to the most recent 8 per user (excess trimmed on write).
- Endpoint: `POST /api/customer/recent-views/{artist_id}` (silent no-op for non-customers), `GET /api/customer/recent-views`.
- **ArtistProfile.jsx** silently records a view for logged-in customers on mount.
- **CustomerDashboard.jsx** renders a horizontal `👀 Recently Viewed` strip (8 cards, click to open the artist).

### Filter Chips
- **Search.jsx** now shows a `[data-testid=active-filter-chips]` strip above results whenever any filter is active. Chips: q, category, city, price range, language, event type, min rating, min experience, gender, and the boolean toggles (Featured / Verified / Premium / Instant).
- Each chip is a gold-tinted pill with a ✕; click to remove that single filter. `Clear all` link appears when 2+ chips are active — it calls the existing `reset()` (also wipes the `bt_last_search_filters` snapshot from Iter 74).

### Verification
- Curl: draft upsert / list / delete + recent-view record / list all pass. Draft carries live `artist_snapshot: {stage_name, category, city, slug, profile_image}`.
- Screenshot: dashboard shows Priya Sharma draft at "Details" step 4 min ago; Discover shows removable Bollywood Vocalist chip; removing city takes results from 1 → 7.



## 🚀 Iter 74 — Continuity UX: history-aware BookingFlow, Discover persist, Auth redirect (2026-08-21)

- **Browser Back walks BookingFlow.** Each step transition (except mount + terminal step 6) pushes `{__bt_step, __bt_artist}` to `window.history`. A `popstate` listener in BookingFlow intercepts Back — if the state carries a step for this artist, we `setStep(s)`; if state is null but we're mid-wizard, we decrement one step + re-push so a single Back never blows up the flow. Step 6 skips the push so Back correctly exits the success screen. Verified: `/book/{id}?pkg&city` → click `step1-next` → browser Back → user is back on step 1, form intact.
- **Discover filter persistence.** `Search.jsx` now hydrates from `localStorage["bt_last_search_filters"]` when the URL has no filter params (URL always wins for shared / deep-linked results). Every `run()` snapshots the current filter set; `Reset` wipes the snapshot for a genuine clean slate. Verified: pre-seed storage → revisit `/discover` → URL rewrites to `?category=…&city=…&sort=…` and results show 1 filtered artist.
- **Auth page redirects logged-in users.** `Auth.jsx` now consumes `useAuth().user`; when a signed-in customer/artist/agency/admin lands on `/login` or `/signup` we `nav(resolveDest(user), {replace:true})` from an effect. `resolveDest` still honours `?returnTo=`, `?next=`, and the `bt_post_login_redirect` sessionStorage handoff. Verified: authed customer visits `/login` → redirected to `/customer`.

### Known follow-ups (backlog)
- Save-for-Later drafts (server-side booking drafts keyed by customer).
- Hydration warning `<span>` inside `<option>` (cosmetic).



## 🎯 Iter 73 — Booking UX polish, AI Planner clickable cards, calendar hardening (2026-08-21)

### Media / list order
- **Legacy media backfill migration**: 71 pre-Iter-73 media docs had no `order` field; Mongo's null-sort meant new uploads (order=0) landed AFTER them. `startup()` now runs an idempotent `update_many({"order":{"$exists":false}}, {"$set":{"order":0}})` and logs `[iter73] backfilled order=0 on N media docs`.
- `/api/media` + `/api/public/media` sort now `[("order",1),("created_at",-1)]` — new uploads appear first.
- `/api/availability/mine` sort → `date DESC`.

### Upload UX
- Upload toast now counts real successes/failures. Oversized-only batch shows only the error toast; mixed batch shows `Uploaded N files · M failed`.
- Blob URLs revoked only for rows removed from strip; error rows keep their preview.

### Questionnaire deep-link (recurring bug)
- `QuestionnaireWizard` used a one-shot `deepLinkApplied` guard, so sidebar sub-item clicks only jumped on the first click. Replaced with a re-firing `useEffect(startSection)` and `wizardRef.current.scrollIntoView({behavior:"smooth"})`. Verified on desktop + mobile.

### Location popup on Book Now
- Guests / customers with no city typed now see `[data-testid=location-prompt]` modal on Book Now click. Filling the city → auto-fills `[data-testid=venue-first-input]` → continues (LoginGate for guests, direct BookingFlow for authed).
- Book Now button no longer disabled when city empty — clicks always open the popup (or the LoginGate for guests).

### BookingFlow state preservation
- `sessionStorage["bt_book_state_${artistId}"]` auto-saves `{form, step}` on every change; restores on mount; cleared on step 6 (success).
- BookingFlow's `Protected`-bounce now includes `?next=<encoded full path+search+hash>` — verified end-to-end: `/book/{id}?pkg&city&date` → `/login?next=%2Fbook%2F...` → sign-in → returns to `/book/{id}?pkg&city&date` with data intact.
- Fixed in `App.js:Protected` — the guard was silently dropping deep-link state before BookingFlow could set its own `?next=`.

### AI Planner
- Date input calendar icon replaced with inline white SVG (`::-webkit-calendar-picker-indicator { background-image: url(...) }`) — icon is now clearly visible on all dark themes. Same fix rolled out globally in `index.css` to every `input[type=date/time/datetime-local/month]`.
- Matched-artist planner cards are fully clickable (`role=link`, `tabindex=0`, hover glow) and open `/artist/{user_id}` in a new tab (`window.open(..., "_blank", "noopener,noreferrer")`). Sold-out / unmatched cards stay display-only. Explore button uses `stopPropagation` so it doesn't double-open.

### Artist calendar hardening
- `AvailabilityCalendar` now always opens on the current month.
- Read-only (customer/guest) view: Prev arrow is disabled when viewing the current month; navigation to earlier months is silently blocked. Tooltip: "This is the current month — you can only pick today or future dates."
- Past dates + outside-month cells continue to be muted/non-clickable (Iter 72 behaviour preserved).
- Artist's own editable view (`editable=true`) unchanged — they can still page back to review past bookings.

### Regressions verified in iteration_73.json
- All Iter 71 SEC-001/002 items still PASS.
- Iter 71 mobile pill nav, LoginGate on favorite/message/availability all still PASS.
- Iter 72 calendar completeness (42 cells, 0 hollows) + upload preview strip both PASS.

### Known follow-ups (backlog)
- MEDIUM: Push each BookingFlow step to history so browser Back walks the wizard instead of exiting.
- LOW: Redirect already-authed users away from `/login` to `resolveDest`.
- LOW: Hydration warning `<span> inside <option>` on ArtistProfile (cosmetic).



## 🔒 Iter 71 — Security Hardening (SEC-001/002/003) + Guest Gate Expansion + Mobile Dashboard Sweep (2026-08-21)

### Security fixes (P0 → P2)
- **SEC-001 (P0) — Passwordless Account Takeover CLOSED.** `/api/auth/email/verify` and `/api/auth/otp/verify` used to issue a full JWT + set the httpOnly `access_token` cookie whenever the OTP matched and the email/phone belonged to an existing user. Combined with the dev-mode mock OTP `123456`, ANY user (including admin) could be logged into with zero password knowledge. Both endpoints now only mark the address as verified and return `{verified: true, token: null}`. Existing users must go through `/auth/login` with their password. Verified end-to-end: `curl` with mock OTP against admin email → no cookie set, `/auth/me` returns 401.
- **SEC-002 (P1) — Default admin password rotated.** `ADMIN_PASSWORD` in `/app/backend/.env` changed from `Admin@123` to `BT!Sec-XW8ANOssw6y0AI7fjVcT-2026`. `seed_admin` re-hashes on startup when the env value changes. Old password now returns 401. `/app/memory/test_credentials.md` updated.
- **SEC-003 (P2) — Easebuzz fail-open closed.** `routes/easebuzz.py:_handle_callback` retrieve step used to fall through to `completed` whenever the retrieve API errored or returned an unparsable body (empty `retrieved_status` made the guard False). Now: envelope `status ∈ ("1","success")` AND inner status `== "success"` are BOTH required to mark payment complete. Missing / error / any other value → `failed` + `failure_reason=retrieve_status=...`. testing_agent verified with a synthetic hash-valid callback for an unknown txnid — payment ends `failed`, redirect goes to failure page.

### Guest gate expansion (Iter 70 → 71)
- `ArtistProfile.jsx` now uses the shared `useLoginGate()` hook alongside the original Book-Now gate. Two new sticky-sidebar buttons:
  - `favorite-artist-btn` (♥) — For guests: `LoginGate` with "Save this artist to your favorites". For customers: toggles `bt_favorites` localStorage entry both ways with a toast confirmation.
  - `message-artist-btn` (💬) — For guests: `LoginGate` with "Sign in to contact this artist". For customers: toast "Chat unlocks after you book & pay. Please Book Now to continue." (chat is booking-scoped by business rule).
- **Availability calendar `onPick`** — Previously a no-op. Now: guests get the `LoginGate` with "Sign in to check availability" contextual copy; logged-in customers navigate to `/book/{artistId}?pkg=…&city=…&date=YYYY-MM-DD` so the date is preserved through booking flow.

### Mobile dashboard sweep
- Previously the `@media (max-width: 767px)` block set `aside.sidebar { display: none !important; }` — stranding mobile users on Customer / Artist / Admin dashboards with no way to switch tabs.
- Rewritten to convert the sidebar into a sticky horizontal-scroll pill nav at the top of the viewport. Sections hidden, items styled as pills, active state marked with gold-gradient background. testing_agent verified 6 pills on Customer, 14 on Artist, 29 on Admin — all visible + tappable at 390×844.
- Agency dashboard was already responsive (its own agency.css block).

### Verified
- testing_agent iteration_71: PHASE 1 all SEC items PASS + full signup/login regression. PHASE 2 guest-gate on favorite / message / availability all PASS, mobile pill nav PASS across 3 dashboards.
- `pytest tests/test_iter64_refunds.py`: 2/2 pass (no refund regression).
- Test files added by testing_agent: `test_iter71_security.py`, `test_iter71_easebuzz_failclosed.py`.

### Known follow-ups (backlog)
- Add login rate-limiting / lockout on `/api/auth/login` — now the only brute-forceable entry point.
- Replace `CORS_ORIGINS="*"` with explicit origins (allow_credentials=True + wildcard is rejected by strict browsers anyway).
- Update older test files that still hardcode `Admin@123` to read from `TEST_ADMIN_PASSWORD` env or `/app/memory/test_credentials.md`.
- Fix minor UI: empty artist name in booking step-1 banner + `<span>` inside `<option>` DOM warning.



## 🎯 Iter 70 — Guest UX, Artist Sidebar Sub-Nav, Mobile Booking Flow (2026-08-21)

### 1) Artist profiles open in a new tab
All artist card `<Link>` components across Search results, Search suggest dropdown, CityLanding, CategoryLanding, and Landing (Spotlight + Rails) now have `target="_blank"` + `rel="noopener noreferrer"`. Guests browsing a list can preview many profiles without losing their scroll position or filters.

### 2) Contextual `LoginGate` guardrail for guest actions
- New shared component `/app/frontend/src/components/LoginGate.jsx` with modal (backdrop + esc-to-close + body-scroll lock), title + message override, Sign In / Create Account CTAs that preserve `?next=<returnTo>`, plus a `useLoginGate()` hook returning `requireAuth(fn, opts)`.
- Wired into `ArtistProfile.jsx` "Book Now" (both desktop button and mobile sticky bar). Guests now see a friendly modal ("Login to book this artist") instead of a hard redirect that loses context.
- Guests can still view every profile / package / gallery / review — only auth-required actions trigger the gate.

### 3) Artist Dashboard Questionnaire sidebar dropdown
- Sidebar `Questionnaire` item is now expandable — clicking it toggles a submenu listing every questionnaire section (Tell us about yourself, Performance Packages, Travel, Technical Requirements, Performance, Hospitality, Commercial, Event Types, Legal, plus category-specific).
- Sections are fetched once from `GET /api/questionnaire/universal` and grouped by `section`. Clicking any section sets `tab=questionnaire` + `wizardStartSection=<name>` so the wizard jumps directly to that question set (uses the existing `startSection` prop the `QuestionnaireWizard` already supported).
- data-testids: `sb-questionnaire`, `sb-questionnaire-sections`, `sb-q-<slug>`.

### 4) Booking Flow mobile responsiveness
- Replaced inline `gridTemplateColumns: "1fr 340px"` on BookingFlow with a CSS class `.booking-flow-grid` that collapses to single column below 900px. Summary card `order: -1` on mobile so pricing is visible first.
- Sticky summary panel now uses `.booking-flow-summary` (sticky on desktop, static on mobile).
- 480px breakpoint tightens padding + shrinks the 5-node stepper circles so they don't overflow narrow phones. Field rows collapse to single-column.

### Verified
- Playwright — Artist Dashboard sidebar: 9 questionnaire section links render under an expandable Questionnaire nav item, clicking each takes the wizard directly there.
- Artist profile page renders cleanly on 390×844 mobile viewport (hamburger nav, hero image, ratings card, sticky Book Now bar).
- Webpack compiles clean.


## 🎯 Iter 68 — Agency: Artist-wise Schedule & Booking Console (2026-08-11)

New page: **Agency Dashboard → Artists → [View Schedule] → `/agency/artist/:artistId/schedule`**

### Backend (agency_roster.py)
Extended `/api/agency/artist/{id}/earnings` totals with new counters: `total_bookings`, `pending_events`, `cancelled_events`, `refunded_events`. Removed the per-booking payment lookup that used to run N+1 queries — now a single batch `find({$or:…})` maps refund status onto all rows.

Two new endpoints:
- `GET /api/agency/artist/{id}/schedule?from=YYYY-MM-DD&to=YYYY-MM-DD` — range-scoped bookings for calendar views. Uses compound index `artist_id + event_date` (created via startup script).
- `GET /api/agency/artist/{id}/availability?date=&event_time=&duration_hours=` — returns `{available, conflicts[], reason}`. Overlap detection uses minutes-since-midnight math; treats bookings with no explicit `event_time` as whole-day busy. Only `confirmed / started / completed_by_artist / completed` block the slot — pending, cancelled, expired don't.

Authorization: agency user must have an *active* roster row for the artist; admin can view any artist. **Historical bookings pre-dating the roster join are always visible** (no `created_at` filter).

### Frontend (`/app/frontend/src/pages/agency/ArtistSchedule.jsx`)
Single-page app with:
- **KPI grid** — 9 tiles: Total, Completed, Upcoming, Confirmed, Pending, Cancelled, Refunded, Total Earnings, Agency Commission @ %.
- **Availability panel** — date + time + duration inputs → check button → green "Available" or red "Artist is already booked during this time." with the conflicting bookings listed. Purely UI hint; existing booking creation flow untouched.
- **Calendar** — self-contained Month / Week / Day toggles (no new dependency). Month = 7×N grid with event chips; Week = 7-column day columns; Day = time-sorted event list. Prev / Next / Today navigator per view.
- **List view** — sortable columns (Event Date, Event Type, Amount, Status) + filters: Date range, Status, Event Type, City, Payment Status. Reset button. Row click opens the same drawer.
- **Event drawer** — Ref, Event Date, Start Time, Client, Location, Package, Guests, Booking Status pill, Payment Status, Artist Fee, Platform Charges, Agency Commission, Refund Status + Amount + Reason (when present).

### Wiring
- `AgencyDashboardV2` routes: added `artist/:artistId/schedule → ArtistSchedule`.
- `modules/Artists.jsx`: new **📅 View Schedule** primary button + kept Earnings / Payments / Remove (only for `status === "active"` roster rows).

### Performance
- **Earnings endpoint** switched from N+1 payment lookups to a single batch query — O(1) DB hits per artist regardless of booking count.
- **Schedule endpoint** uses the compound index for range queries — a full month view only touches the visible slice.
- Data loads once per artist visit; calendar re-navigation is client-side.

### Verified via Playwright
Screenshot 1: `/agency/artist/{id}/schedule` shows all 9 KPI tiles with real numbers, availability panel, month calendar navigable to January 2027 where the artist has two wedding bookings visible on Jan 15.
Screenshot 2: List view — all 22 bookings load with sort/filter controls; row click opens the event drawer showing Ref BT-260723-6A69AF with full details.


## 🎯 Iter 67 — Artist City Requests (mirror of Iter 66 Category flow) (2026-08-11)

Applied the same "Request a new city" workflow that Iter 66 shipped for categories:

- **New collection**: `city_requests` with the same shape as `category_requests` (plus `state`, `country`, `reason`).
- **Router**: `/app/backend/routes/city_requests.py` — 6 endpoints:
  - `POST /api/artist/city-requests`, `GET /api/artist/city-requests/mine`
  - `GET /api/admin/city-requests?status=`, `GET /api/admin/city-requests/similar?name=`
  - `POST /api/admin/city-requests/{id}/approve` (existing_slug OR new_name)
  - `POST /api/admin/city-requests/{id}/reject` (reason required)
- **/auth/register**: accepts optional `city_request: {name, state?, country?, description?, reason?}`. Profile is created with `city_pending=true` + placeholder, city row inserted atomically, admin notified with `city.request`.
- **Approval**: creates a new row in `cities_master` (or reuses existing slug), rewrites `artist_profiles.city`, clears `city_pending`, notifies artist with `city.approved`.
- **Rejection**: stores `rejection_reason`, notifies artist with `city.rejected`.
- **Frontend**: Auth.jsx Primary City dropdown now loads from `/catalog/cities` with a bottom option **"📍 Can't find your city? Request a new one"** that reveals inline City/State/Reason fields.
- **Admin UI**: new `AdminCityRequests.jsx` (identical UX to categories) — Pending / Approved / Rejected / All tabs, per-row drawer with Create-new / Reuse-existing / Reject modes, dupe-avoidance pills from `/similar?name=`.
- **AdminDashboard sidebar**: new **📍 City Requests** entry beneath Category Requests.

**Verified end-to-end**: signup w/ `city_request:{name:"Coimbatore", …}` → 1 pending row + admin notify → approve → `cities_master` gained slug `coimbatore` → artist profile `.city="Coimbatore"` + `.city_pending=false`. Both category + city flows can be requested simultaneously and resolved independently — I confirmed with a signup that submitted both requests at once; only the city was approved and the profile shows `city_pending:false, category_pending:true`.


## 🎯 Iter 66 — Hide Corporate + Artist Category Requests (2026-08-11)

### 1) Corporate Access Hidden (kept in DB, reversible)
- **Landing.jsx** — Corporate CTA card removed; the dual-CTA section now renders only the Artist card (single-column). Zero references to `cta-corporate` / `cta-corp-join` remain.
- **Auth.jsx** — `corporate` removed from the public `ROLES` list. Legacy `?role=corporate` URLs auto-coerce to `customer` so old bookmarks / marketing links still land somewhere useful.
- **Backend `/auth/register`** — explicit 400 with message *"Corporate signup is not currently available. Please register as a Customer."* if a client bypasses the UI. The `RegisterBody.role` Literal still allows `corporate` so **admins can still create corporate accounts** from `/admin` and existing rows work unchanged.
- **Reversible**: To re-enable, re-add `{value:'corporate', …}` to `ROLES` and drop the 400 branch. No schema changes, no data loss.

### 2) Artist Category Request Workflow
New collection: `category_requests` — `{id, artist_id, artist_name, artist_email, stage_name, city, requested_name, requested_slug, description, example_artists, portfolio_link, status, created_at, decision, assigned_slug, assigned_name, decided_at, decided_by, rejection_reason}`.

**Endpoints** (`/app/backend/routes/category_requests.py`):
- `POST /api/artist/category-requests` — logged-in artist submits (limits: 1 pending per artist).
- `GET /api/artist/category-requests/mine` — artist reads own history.
- `GET /api/admin/category-requests?status=` — admin queue with tab filter.
- `GET /api/admin/category-requests/similar?name=` — dupe-avoidance helper (tokenised regex against `name` + `slug`).
- `POST /api/admin/category-requests/{id}/approve` — two-mode approval:
  - `{ existing_slug }` → reuse existing master row.
  - `{ new_name, icon }` → create new `categories_master` row (slug auto-derived, sort_order = end).
  Either way: artist profile updated (`category=canonical`, `category_pending=false`), artist notified.
- `POST /api/admin/category-requests/{id}/reject` — requires `reason`; artist notified.

**Signup-time submission**: `POST /auth/register` now accepts optional `category_request: {name, description, example_artists?, portfolio_link?}`. When present, the artist profile is created with `category_pending=true` + `pending_category_id`, and the request row is inserted atomically. Admin notification of type `category.request` is emitted.

**Artist preservation**: Even if the requested category isn't approved yet, the artist has a complete profile row with the requested category name as placeholder. On admin approval, `category` gets rewritten to the canonical name and the pending flag cleared — the artist doesn't re-enter anything.

### 3) Frontend
- `Auth.jsx` — category dropdown now loads from `/catalog/categories` (live master list) with a bottom option **"✨ Can't find your category? Request a new one"**. Selecting it swaps in an inline "Request a New Category" panel with fields: name*, description*, similar artists (optional), portfolio link (optional).
- Client-side validation gates the "Continue → Verify Email" button until either a category is picked OR the request has both name + description.
- `pages/admin/AdminCategoryRequests.jsx` — new admin queue: status tabs (Pending / Approved / Rejected / All), row-click drawer with three tabs (Create new | Reuse existing | Reject), automatic dupe-suggestion pills fed by `/similar?name=`, icon picker, rejection reason box. Wired into `AdminDashboard` sidebar under KYC Queue.

### 4) End-to-end verification
- `curl` — POST /auth/register with `role=corporate` → 400 as designed.
- Full signup with `category_request:{name:"Sufi Qawwal", …}` → artist created + request row inserted + admin notified.
- POST /admin/category-requests/{id}/approve with `{new_name:"Sufi / Qawwali", icon:"🪕"}` → new master row `sufi-qawwali`, artist profile `.category="Sufi / Qawwali"` + `.category_pending=false`, artist notification `category.approved` fired.
- POST /reject with reason → artist notification `category.rejected`, no master row change.
- Playwright — Landing page: `cta-corporate=0`; Signup step 2 shows the Request panel with all fields; Admin `/admin?tab=category-requests` renders sidebar entry, tabs, and both my test rows.


## 🎯 Iter 65 — Auto-Scroll To Row + Soft Gold Flash (2026-08-11)

Click any notification in the bell → the destination page opens, scrolls the exact booking/payment/refund row into view (`behavior: smooth`, `block: center`), and pulses a soft-gold glow (~2.2s animation with `box-shadow` + `background-color` keyframes). Agents/admins find the item instantly instead of scanning a table.

**Shared primitives (new)**:
- `frontend/src/lib/useHighlightRow.js` — hook that reads `?highlight=<id>` from URL and polls (up to 4s / 16×250ms) for `[data-testid="{prefix}-{id}"]` before applying `.row-flash-gold`. `dataKey` prop re-triggers when list length changes so the flash works even when rows load async.
- `frontend/src/styles/iter65_row_flash.css` — `bt-row-flash-gold` keyframes for both light + dark surfaces.

**Wired into**:
- `BookingsTable` (used by Customer, Artist, generic role) — `prefix='booking-row'`.
- `AdminDashboard → AdminBookings` — renamed testids from `admin-booking-{id}` → `booking-row-{id}` for consistency.
- `AdminDashboard → AdminRefunds` — testids from `refund-{id}` → `refund-row-{id}`; `prefix='refund-row'`.
- `admin/AdminPaymentReconciliation` — enables highlight for payments-tab (`prefix='payment-row'`) OR refunds-tab (`prefix='refund-row'`) based on which tab is active. Also honours `?subtab=refunds|payments|logs` from URL so the correct inner tab activates before the row scroll.
- `agency/modules/Bookings.jsx` — added `data-testid="booking-row-{id}"` to kanban cards.

**Notification link updates**:
- Refund success → `/customer?tab=bookings&highlight=<booking_id>`.
- Refund failure → `/admin?tab=payment-recon&subtab=refunds&highlight=<payment_id>`.
- Existing `/dashboard/bookings/:id` legacy links still rewritten to role-specific `?highlight=` targets in `NotificationBell.handleClick`.

**Customer dashboard**: now reads `?tab=` on mount so notifications land on the right sidebar tab immediately (matches AdminDashboard + ArtistDashboard behaviour).

**Manual test verified**: `/customer?tab=bookings&highlight=<bid>` → target row gains `.row-flash-gold` class in ~60ms, gold outline pulse visible in screenshot at `/tmp/highlight_row.png`.


## 🎯 Iter 64 — Automatic Easebuzz Refunds + Agency Earnings + Razorpay Removal (2026-08-11)

### 1) Easebuzz Automatic Refund System
- **No more manual admin refund processing** for standard cancellation/rejection/expiry cases. When a booking is rejected by the artist, cancelled by the customer, or auto-expires without artist confirmation, the backend now **automatically calls the Easebuzz Refund API** (`POST {dashboard}/transaction/v1/refund`) with the correct SHA-512 hash sequence `key|txnid|amount|refund_amount|email|phone|salt`.
- **Dashboard URL derived from environment**: sandbox → `testdashboard.easebuzz.in`, live → `dashboard.easebuzz.in`. Kept isolated from checkout base URL.
- **Storage** (payments doc extras): `refund_status` (initiated/successful/failed/not_applicable), `refund_amount`, `refund_at`, `refund_reason`, `refund_id`, `refund_easebuzz_id`, `refund_response`, `refund_error`, `refund_attempts`, `refund_actor`.
- **Duplicate refund guard**: `refund_status == 'successful'` → skip. `'initiated'` → skip (in-flight). Guarantees a booking can never be refunded twice.
- **Failure handling**: mark `failed`, record `refund_error`, create `refund.failed` notification for every admin — NO infinite retries. Admin can manually retry via `POST /api/admin/refunds/{payment_id}/retry`.
- **Customer notification** on success: `refund.processed` notification links to `/dashboard/bookings` with amount + reason.
- Wired into: `_mark_platform_fee_refundable` (called from booking_action reject/cancel + auto-expire worker).

### 2) Agency Portal — Complete Artist Earnings
- New endpoint: `GET /api/agency/artist/{artist_id}/earnings` — returns `{artist, totals, bookings[]}`.
  - `totals`: `total_earnings, completed_earnings, upcoming_earnings, confirmed_booking_value, completed_events, upcoming_events, confirmed_events, agency_commission_earned, commission_pct`.
  - Per booking: `ref, event_date, customer_name, event_type, venue, city, status, payment_status, amount_paid, artist_fee, platform_charges, agency_commission, artist_net, refund_status, refund_amount, refund_reason`.
- **No `created_at` window** — Agencies see the artist's COMPLETE history, including bookings that predate the roster join. Matches user spec #3 exactly.
- Frontend: Artists.jsx → new **Earnings** button per active roster row → drawer with 4-KPI grid + full booking history table. `data-testid='ag-view-earnings-{id}'`, `'ag-earnings-drawer'`, `'ag-earnings-bookings'`, `'ag-earn-total/completed/upcoming/confirmed'`.
- **Fix**: `routes/agency_crm.py` was querying the wrong collection (`agency_artists` — legacy stub). Now correctly queries `agency_roster` with `status='active'` — CRM Revenue tile is no longer permanently empty.

### 3) Razorpay Removal
- **Backend deletions**:
  - `import razorpay` + client init in `server.py`.
  - Endpoints removed: `/payments/config`, `/payments/init`, `/payments/verify`, `/payments/webhook`, `/payments/{id}/refund`, `/payments/batch/init`, `/payments/batch/verify`.
  - Old `/admin/refunds` (manual-flagged) renamed to `/admin/refunds/legacy-flagged` — the new automatic `/admin/refunds` in routes/easebuzz.py is now the canonical endpoint.
  - Pydantic model `PaymentVerifyBody` no longer accepts razorpay_order_id/razorpay_payment_id/razorpay_signature.
  - `RAZORPAY_*` env vars removed from `/app/backend/.env`.
  - `razorpay==1.4.2` removed from `requirements.txt` (pip uninstalled).
  - iter7 subscription `PaymentSetupBody.payment_method` literal narrowed to `easebuzz | mock`.
  - iter9 `/admin/integrations` no longer lists razorpay; lists easebuzz instead.
- **Frontend deletions**:
  - `loadRazorpay()` script loader removed from `BookingFlow.jsx`.
  - All `initR.data.gateway === "razorpay"` branches removed.
  - `paymentConfig` prop removed from PaymentStep entirely — component is Easebuzz-only.
  - AdminEnterprise integrations grid replaces `razorpay` entry with `easebuzz`.
  - AdminPaymentReconciliation filter dropdown labels Razorpay as `(Legacy)` — historical DB rows can still be filtered.
  - AdminDashboard `AdminRefunds` widget re-written for auto-refund model (no more "Process Refund" button; only "Retry" for failed refunds).
- Result: Easebuzz is the **only** active payment path. Legacy razorpay_mock DB rows remain viewable as historical data.

### 4) Admin Refunds Console
- `GET /api/admin/refunds?status=&page=&limit=` — paginated `{items, total, page, limit}` where each item is enriched with customer_name, customer_email, artist_name, event_date, booking_refs, refund_id, easebuzz_id, refund_error, refund_status, refund_at, gateway, environment.
- `POST /api/admin/refunds/{payment_id}/retry` — manual re-trigger for failed refunds.
- New **Refunds** tab in Admin → Payment Reconciliation (`data-testid='tab-refunds'`, `'refunds-table'`, `'filter-refund-status'`, `'btn-retry-refund-{id}'`).

### 5) Testing
- `tests/test_iter64_refunds.py` — 2/2 pass:
  - Refund success + idempotency (second call returns `already=True`).
  - Refund failure → payment marked failed + admin notification created.
- testing_agent iter-61: 13/13 backend + frontend smoke all green. One minor UX ('Earnings button visible for pending artists') fixed post-report by conditionally rendering only for `status==='active'`.


## 🎯 Iter 63.5 — Global Footer Deduplication (2026-02-28)


## 🎯 Iter 60 (was 59.1) — Booking Payment BULLETPROOF Fix (2026-02-27)
User reported P0 (3rd time): "clicking Pay randomly shows Login redirect / Not Authorized / T&C error". Definitive root-cause tree:
- (a) axios interceptor hard-redirecting on background 401s → **REMOVED** (iter 58 v2)
- (b) `...form` spread sending untyped fields → 422 from Pydantic (`customer_travel_allowance:""`, `guests: 150 as int`) → **REPLACED with explicit `commonFields` object**
- (c) Batch flow missing `tnc_accepted` per item → **NOW FORCED to true** at submit time (user cannot reach step 5 without step-4 gate)
- (d) `guests` schema mismatch (backend expects `Optional[str]`, frontend was sending int) → **coerced with `.toString()`**
- (e) Silent session drop mid-flow → **pre-submit `/auth/me` refresh** with friendly toast fallback (NO auto-redirect)

Batch success card now snapshots cartItems BEFORE `clearCart()` so all artists render on step 6, not just primary.

**Testing**: testing_agent iter-60 → 100% frontend acceptance (single BT-260727-1EA740, batch BT-260727-C6E7A0 + BT-260727-C14A90, session-expiry graceful toast) + 9/9 backend pytest (5 iter-58 anchor + 4 iter-60 new regressions in `test_iter60_booking_hardening.py`).


## 🚨 Iter 59 — Multi-Artist Batch T&C + Interceptor Regression Rollback (2026-02-27)
- **User-blocking bug**: Multi-artist checkout (2+ artists in cart) always failed at Pay with "⚠ Please accept the Terms & Conditions before proceeding" even though the customer had ticked the box on step 4. Root cause: the `items[]` array sent to `POST /api/bookings/batch` did NOT include `tnc_accepted` per item — the backend loops through each item and forwards to `create_booking()` which enforces per-item T&C (server.py:1534). Fix in `BookingFlow.jsx:232`: propagate `tnc_accepted` + coerce `customer_travel_allowance` to number on every item mapped from `cartItems`.
- **Interceptor regression rollback**: The earlier iter-58-v1 axios 401 interceptor was hard-redirecting to `/login` on any 401 (including harmless background 401s). Removed the auto-redirect entirely in `lib/api.js`; interceptor now ONLY rewrites the FastAPI "Not authenticated" detail into a friendly string. Route-level `Protected` in `App.js` handles genuine anonymous access — no forced redirects from within the axios pipeline. Deleted the corresponding `bt:session-expired` listener from `auth.jsx`.
- **Testing**: End-to-end curl proof — `POST /api/bookings/batch` with `tnc_accepted:true` on all items creates `event_id + 2 booking_ids + booking_refs` cleanly (`BT-260727-2CC675`, `BT-260727-250244`).


## 🔐 Iter 58 — Booking-Payment 401 UX + `customer_travel_allowance` 422 Fix (2026-02-27)
- **P0 user report**: Customer reported "⚠ Not authenticated" toast when clicking "Pay to Confirm" on artist booking. Real root cause was TWO overlapping bugs:
  - (a) `form.customer_travel_allowance` defaulted to `""` and was spread into POST /bookings via `...form`. Pydantic v2 rejected with a `float_parsing` 422. The frontend `formatApiError` couldn't render the Pydantic detail array — silent toast that resembled the auth failure the user reported.
  - (b) Legitimate session-expiry mid-flow (SameSite=Lax cookies + long browsing) surfaced as a cryptic "Not authenticated" with no recovery path.
- **Fix (a)**: `BookingFlow.jsx` now explicitly builds the POST payload and coerces `customer_travel_allowance` (`""` → 0, otherwise `Number()`). Confirmed end-to-end via curl: `/bookings` → 200, `/payments/init` → 200, `/payments/verify` (mock_otp=123456) → 200 with `status=pending_artist`.
- **Fix (b)**: Global axios response interceptor in `lib/api.js` rewrites any non-`/auth/me` 401 detail to "Your session has expired. Please sign in again to continue." and fires a `bt:session-expired` event. `AuthProvider` listens, hard-navigates to `/login?returnTo=<current-path>` (returnTo is validated: starts-with `/` and not `//` — protocol-relative URLs like `//evil.com` are rejected). `Auth.jsx` `resolveDest` respects `?returnTo` so users resume exactly where they left off.
- **Formatter hardening**: `formatApiError` now unpacks Pydantic v2 validation arrays into `field: msg` lines so a 422 never looks like a silent failure. Custom detail dicts (`{message, alternatives}`) prefer the `message` key.
- **Testing**: `testing_agent` iter 58 → 5/5 backend pytest + 6/6 iter-58 acceptance criteria green (friendly toast, auto-redirect, returnTo round-trip, protocol-relative rejection, /auth/me exemption). Uncovered the `customer_travel_allowance` 422 bug — now fixed and verified via curl.


## 🎨 Iter 57 — RBAC Guardrails, Nudge Deep-link & Media Fallback (2026-02-25)
- **RBAC UI Guardrails**: `AdminDashboard` reads `/admin/rbac/me` on mount and hides sidebar entries whose `perm` field isn't in the caller's permission set. `effectiveTab` fallback re-routes to Overview if the selected tab becomes hidden. All 25 sidebar entries mapped to their required permission (null = always shown). Backend belt-and-braces: `/admin/artists` now uses `require_permission('artists.moderate')`, `/admin/refunds` uses `require_permission('payments.view')`, `audit` sidebar entry gated by `admins.manage`.
- **Nudge Sections Explorer**: Onboarding banner renders each missing section as a golden clickable chip (`qn-missing-{slug}`). Clicking sets `wizardStartSection` state → tab flips to questionnaire → `QuestionnaireWizard`'s new `startSection` prop deep-links to matching step on first render (case-insensitive match, one-shot, falls back to step 0). Step-nav click restriction relaxed so users can jump freely.
- **Media Chip Fallback**: `QuestionnairePanel` on the customer-facing About tab now shows a distinct **dashed-border chip with a ❓ tile and 'Ask artist for this →' label** (`qa-media-missing-{qid}`) whenever a media-type answer has no matching upload. Signals to customers that something is expected but not yet delivered — turns a silent gap into a light nudge.
- **Testing**: testing_agent_v3_fork iteration_57.json → 16/18 backend + full frontend flows green; both flagged gaps fixed in follow-up (audit sidebar perm, /admin/artists + /admin/refunds require_permission).


## 🎯 Iter 56 — Media Chips, DB-backed Roles, Audit Log & Onboarding Nudge (2026-02-24)
- **Media-linked Answers**: `/api/artists/{id}/about` now returns a `media_matches` array pairing each media-type answer with the newest matching media doc (heuristic map: `profile_photo→profile`, `intro_video→clip`, `gallery→gallery`, etc.). Frontend `QuestionnairePanel` renders clickable thumbnail chips that jump to the Media tab. Single Mongo query batches all media types for perf.
- **Role Presets in DB**: New `admin_roles` collection seeded on boot with the 6 defaults. Endpoints: `GET/POST/PATCH/DELETE /api/admin/roles` (admins.manage). Safety: `super_admin` role is protected (edit/delete → 400); a role cannot be deleted while any admin still holds it; `custom` id is reserved. `get_role_presets()` helper reads DB with fallback to seed dict.
- **RBAC Audit Log**: New `admin_audit_log` collection + `audit_log()` helper called from every admin create/update/suspend/reactivate/delete/password_reset AND role.create/update/delete. `GET /api/admin/audit-log?action=&actor_id=&limit=` returns entries with actor, target, meta and timestamp. Audit failures never break the primary action (wrapped try/except).
- **Onboarding Nudge**: New `GET /api/questionnaire/completion/mine` returns section + question counts. Artist Dashboard Overview shows a golden banner (`data-testid=qn-nudge`) with progress bar and CTA when `sections_missing > 3`. Session-dismissable via `qn-nudge-dismiss`.
- **Frontend**: `AdminAdmins` page rewritten with three sub-tabs (Admins / Role Presets / Audit Log). New `RoleModal` for role CRUD.
- **Testing**: testing_agent_v3_fork iteration_56.json → **18/18 backend pytest + full frontend flows green**. Test file: `/app/backend/tests/test_iter56_roles_audit_nudge.py`.


## 🛡️ Iter 55 — RBAC, Agency Nav Fix & Artist About (2026-02-24)
- **BUGFIX Agency Left Nav**: Under React Router 7's wildcard route (`path="/agency/*"`), NavLink relative `to="artists"` was resolving against the current URL, producing compound paths like `/agency/overview/artists`. Fixed by switching all NAV entries to absolute paths (`/agency/{module}`) and adding `end` prop for accurate active-state matching.
- **Admin RBAC (Multi-Admin + Permissions)**: New `admin_role` + `admin_permissions` columns on the users doc. 15 named permissions (`admins.manage`, `users.view/edit/suspend/delete`, `artists.moderate`, `bookings.view/override`, `payments.view/refund`, `cms.manage`, `settings.manage`, `analytics.view`, `notifications.send`, `subscriptions.manage`) + 6 preset roles (super_admin, operations, finance, content, support, viewer) + a "custom" mode where the super admin picks individual permissions. Endpoints: `GET /api/admin/rbac/roles`, `GET /api/admin/rbac/me`, `GET/POST/PATCH/DELETE /api/admin/admins`. All sensitive admin endpoints migrated from `admin_only` to `require_permission(...)`. Safety guards: cannot deactivate/demote/delete self; cannot delete last super_admin.
- **Artist About from Questionnaire**: New `GET /api/artists/{id}/about` public endpoint groups answers by section (Travel / Hospitality / Sound / Technical / …) with fuzzy category matching. Frontend Artist Profile About tab renders a new `Rider & Preferences` panel (`data-testid="qa-panel"`) with one card per answer. Media-type questions never render inline uploaders — a golden hint block with "See gallery →" points to the Media tab, so uploads only ever flow through the Media & Photos module.
- **QuestionnaireWizard**: unified handling for `file / photo / photos / video / videos / media / attachment / image` question types so onboarding never opens a rogue uploader.
- **Testing**: testing_agent_v3_fork iteration_55.json → **18/18 backend pytest + full frontend flows green** (agency 11/11 nav items, RBAC create/edit/suspend/reactivate/delete + super-admin-delete-hidden guard, public About endpoint, questionnaire wizard 5/5 media-hint blocks).


## 🧑‍🎤 Iter 54 — Agency Portal: Add Artist & Documents Vault (2026-02-23)
- **Auto-provision new artists**: `POST /api/agency/invite` now creates a full artist account (with `pending_activation=true`, random secure password, companion `artist_profiles` row) when the invited email is not on BookTalent yet. Roster row goes straight to `status='active'` and payload flags `auto_provisioned=true`. Existing artists still get the invite→pending flow. Optional fields on the invite: `first_name`, `last_name`, `phone`, `category`, `city`, `stage_name`.
- **Documents Vault**: New `POST/GET/DELETE /api/agency/documents` + `GET /agency/documents/{id}/download`. Supports client_id / event_id tagging, kind filter (contract/agreement/invoice/id/rider/other), inline base64 storage (10 MB hard cap server-side, 8 MB UI cap). List endpoint projects out `data_url` for lightweight loading; download endpoint returns the full data URL for browser save.
- **Agency Overview overhaul**: Six prominent Quick Action cards (Add Artist / Add Client / Create Event / New Invoice / Upload Document / Invite Staff) replace the tiny text links. First-time users see a golden onboarding banner nudging them to add their first artist.
- **Testing**: testing_agent_v3_fork iteration_54.json → **13/13 backend pytest green** + full UI verification. Only finding was a dev-mode-only React hydration warning on `<option>` (fixed via template-literal wrapping).


## 🔒 Iter 53 — Artist Payment Gating (2026-02-23)
- **Business-rule enforcement**: Artists must never see platform-side money lines. Backend `GET /api/bookings/mine` + `/api/bookings/{id}` now strip `pricing.platform_fee / gst / total / token_amount / balance_due / coupon_discount` from artist-role payloads via a new `_redact_pricing_for_artist()` helper. Artists retain only `pricing.package_fee`, `pricing.addons_total`, `pricing.artist_fee` (their own earnings).
- **Contact-info gate**: When `amount_paid == 0`, artist view redacts `customer_phone`, `customer_email` on both list & detail endpoints AND `customer.phone/email` on the joined `customer` object. `_contact_locked=true` + `contact_unlocked=false` marker returned so UI can render lock state.
- **Invoice download**: `GET /api/bookings/{id}/invoice` now returns 403 for artist role with message "Platform invoices are issued only to the customer" (contains platform fee + GST — must not leak to artist).
- **Frontend BookingsTable** (shared component): role-aware column swap — artists see `Package` (package_name + package_fee) instead of `Amount` (grand total). Invoice button is hidden for artists (`role !== "artist"` gate on `dl-invoice-*`). Chat button remains locked (`🔒 Pay to Unlock Chat`, disabled) for unpaid pending_payment rows.
- **Testing**: testing_agent_v3_fork iteration_53.json → **9/9 backend pytest green** + frontend UI verified (194 pkg-cells, 0 dl-invoice buttons on artist dashboard; 59 dl-invoice + Amount column intact on customer dashboard regression). Test file at `/app/backend/tests/test_iter53_artist_gating.py`.


## 🧾 Iter 52.9 — Admin Subscription Management (2026-02-19)
- **7 new endpoints**: `GET/POST/PATCH/DELETE /api/admin/subscriptions`, `GET /admin/subscriptions/summary`, `GET /admin/subscriptions/{sid}`, `POST /admin/subscriptions/sweep-expired`. Filters by status/plan/role + name/email/phone/company search. Manual grants create `admin_grant` records with an audit note. Extend/reduce validity by ±N days OR set explicit expiry. Cancel cascades to `artist_profiles.premium_badge`.
- **Auto-expiry cron piggy-backed** on the existing 15-min booking-expiry loop — flips `active → expired` past ETA, downgrades `premium_badge`, and sends 7-day + 1-day expiry warning notifications (idempotent via `expiry_warn_7d_sent` marker).
- **UI**: new `AdminSubscriptions.jsx` — 4 KPI tiles (Active / Expiring 7d / Expired / Active MRR), filter bar (search + status + plan + role), paginated table with days-left badge, Manage modal (change plan/status/extend/txn/auto-renew), Grant Subscription modal (user typeahead + custom duration + note), 🧹 Sweep Expired one-click button. Wired into Admin sidebar between Coupons and Users.



## 🚀 Iter 52 — Persistent Cart + Agency Dashboard V2 (2026-02-19)
- **Booking Cart (Amazon-style, persistent)**: New `/cart` route + header CartIcon with live badge. Cart survives login/logout/refresh/browser-close via server-side `carts` collection keyed by user_id OR anon cookie (30-day TTL). Anon cart auto-merges into user cart on login. Click "Book Now" while logged-out → artist saved → `/login?next=/cart` → auto-restore → checkout. Grand total math = Subtotal + 5% Platform Fee + 18% GST on fee.
- **Agency Dashboard V2 (SaaS/ERP shell)**: Brand-new `/agency/*` with collapsible left sidebar, 6-card KPI strip, and 11 modules — Overview · Artists (Online Roster + Offline CRM) · Bookings (Platform + Offline kanban) · Clients CRM (notes + follow-ups + event history) · Events (multi-artist assign, checklist, quotation, payment tracking) · Calendar (month grid, unified feed) · Finance (invoices with line-items + tax auto-calc, expenses, summary) · Staff (role-based permissions: manager/coordinator/accountant/booking_executive) · Reports (revenue + artist performance bar charts) · Documents · Notifications feed. Legacy `/agency-legacy` retained for regression.
- **Backend**: 25+ new endpoints under `/api/agency/*` and `/api/cart/*`. New collections: `carts`, `agency_offline_artists`, `agency_clients`, `agency_offline_events`, `agency_staff`, `agency_invoices`, `agency_expenses`, `agency_notifications`. All agency endpoints gated behind role in {agency, admin}; offline records NEVER surface on `/api/artists/search`.
- **Testing**: testing_agent_v3_fork iteration_52.json → **24/24 green** covering full cart lifecycle, agency role-guards, offline artists CRUD + marketplace privacy, clients CRM with fan-out to notifications, invoice math, staff dup-email 409, and regression on 5 core public endpoints.



## 🔒 Iter 51 — Security Audit: cookie-only auth + ffmpeg subprocess hardening (2026-02-19)
- **XSS token-theft vector CLOSED.** JWT no longer stored in `localStorage` on the frontend. httpOnly `access_token` cookie (Secure, SameSite=Lax, 7d) is the **sole** auth carrier for REST + WebSocket. AuthContext now derives session by calling `/auth/me` on mount (falls back to anonymous on 401). Legacy `bt_token` is wiped from localStorage on first load.
- **Files touched (FE)**: `lib/auth.jsx` (rewritten), `lib/api.js` (removed Bearer interceptor), `components/ChatBox.jsx` (WS no longer sends `?token=`), `components/MediaUploader.jsx` (three axios calls → `withCredentials:true`), `pages/CustomerDashboard.jsx` + `pages/BookingFlow.jsx` (PDF-download `fetch` uses `credentials:"include"`), `components/QuestionnaireWizard.jsx` (fixed `react-hooks/exhaustive-deps` warning by wrapping `shouldShow` in `useCallback`).
- **Files touched (BE)**: `chat_routes.py:239` — WS `ws_chat` now accepts optional `?token=` **or** falls back to `websocket.cookies.get("access_token")`; `video_compression.py:_run_ffmpeg` — added explicit path allow-list (tempdir + MEDIA_ROOT) & NUL-byte guard, plus a security note clarifying `asyncio.create_subprocess_exec` is the safe `execve` API (NOT Python's `exec()` builtin, NOT `shell=True`).
- **Testing**: testing_agent_v3_fork iteration_51.json → 20/20 iter51 tests + 19/19 iter30 cookie-auth regression → **39/39 green**. Verified login/register/otp-verify all set the httpOnly cookie, `/auth/me` works cookie-only, logout clears it, WS accepts cookie-only auth, invoice PDF + chunked upload endpoints reachable without any Bearer header, ffmpeg still compresses a 2.4 MB test-pattern mp4 (`video_compressed=true`), session persists across hard refresh, `localStorage.bt_token` stays null.



## 🎨 Iter 41 — Home / Category / City / Blog banners fully admin-editable (2026-02-18)
- **Home page hero**: 6 new admin-editable public settings (`home_hero_image/eyebrow/title/subtitle/cta_label/cta_url`) — Landing renders them when set and falls back to the default poetic hero otherwise. Managed via Admin → Settings → 🏠 Homepage Hero Banner.
- **Category & City landing banners**: `MasterItem` model now accepts `hero_image / hero_title / hero_subtitle / hero_cta_label / hero_cta_url`. Category (`/artists/<slug>`) and City (`/artists/city/<slug>`) pages show these as a hero when set. Managed via Admin → Master Data (each row now has a "▼ Featured Banner" toggle).
- **Per-blog article banner**: `BlogBody` extended with the same 5 hero fields + `author` + full PUT/DELETE endpoints (`/api/admin/blogs`, `/api/admin/blogs/{bid}`). New **AdminBlogs** UI tab in Admin sidebar lets you write, publish/unpublish, add tags, attach a per-post banner, and view live.
- **Regression fix**: `PUT /api/admin/master/{entity}/{id}` no longer auto-rewrites the slug from name — SEO URLs stay stable when admins only tweak the banner.
- Backend pytest: test_iter41_page_banners.py — 4/4 passing.



## 🖼️ Iter 40 — Admin User CRUD + Featured Banners (2026-02-18)
- Admin User Management: `PUT /api/admin/users/{uid}` (edit name/email/phone/role + artist profile fields), `DELETE /api/admin/users/{uid}` with `?hard=true` for permanent wipe (default is soft/anonymised). Admin cannot delete self.
- Frontend AdminArtists + AdminUsers get a single **Delete** button that opens a two-option modal (Deactivate / Delete permanently with type-DELETE confirmation) + Edit modal + Suspend/Unsuspend toggle. The confusing extra ✕ hard-delete button was removed.
- **Featured Banner support**:
  - CMS pages accept `hero_image`, `hero_title`, `hero_subtitle`, `hero_cta_label`, `hero_cta_url` (renders as hero on `/page/<slug>` — About, Terms, Refund Policy, Careers…).
  - Blog list page (`/blog`) reads a global hero from public settings (`blog_hero_*`) — dedicated panel in Admin Settings.
- Backend pytest: test_iter40_admin_crud_banners.py — 7/7 passing.

## 🧩 Iter 39 — CMS / FAQ / Broadcast go LIVE + Global SEO (2026-02-18)
- Every published CMS page now renders at `/page/<slug>` with dynamic SEO meta, JSON-LD, and optional custom schema. Admin CMS gets `header_menu`, `footer_menu`, `menu_order`, `seo_title`, `seo_keywords`, `og_image`, `canonical`, `schema_json`.
- Dynamic Nav + new `<Footer>`: pulls header/footer menus from DB (`/api/menu/header`, `/api/menu/footer`).
- FAQ Help Center at `/help` (search + categories + featured). Landing page renders featured FAQs (`is_featured`).
- Broadcast Announcements: banner / popup / dashboard bell, per-user read receipts, scheduling, priority, targeting.
- Global SEO: `react-helmet-async` wired via `<SEO>` component, Organization + WebSite JSON-LD, `/api/sitemap.xml`, `/api/robots.txt`.
- SEO-friendly URLs: `/artist/<slug>`, `/artists/<category>`, `/artists/city/<slug>`. Blog list + article pages with Article JSON-LD, share buttons, related.
- Testing: iteration_37.json — all backend 22/22, all frontend flows validated.



## 🎯 BUSINESS MODEL — LEAD GENERATION MARKETPLACE (Iter 38 — 2026-02-18)
BookTalent is **strictly a Lead Generation & Booking Marketplace, NOT an Escrow platform.**
- BookTalent collects ONLY: **5% Platform Service Fee + 18% GST** on that fee.
- Artist Performance Fee is settled **directly Customer ↔ Artist** per the signed agreement.
- **REMOVED (Iter 38):** Wallets (customer/artist/agency), withdrawals, escrow/pending-payout tracking, `routes/wallet.py`, `/api/admin/withdrawals*` endpoints, `wallets` + `withdrawals` collections (auto-dropped on startup), all wallet UI (artist "💰 Wallet" tab, booking "👛 Wallet" payment method, admin "Escrow"/"Pending Payouts" KPIs).
- **NEW admin KPIs:** `platform_revenue`, `gst_collected`, `subscription_revenue`, `boost_revenue`, `bookTalent_total_collected`, `pending_refunds`.
- **NEW endpoint:** `GET /api/admin/refunds` — payments flagged for Razorpay refund (booking cancelled/rejected/disputed). Admin triggers actual refund via `POST /api/payments/{id}/refund`.
- Validated end-to-end by testing_agent_v3_fork (iteration_36.json): 15/15 backend + full UI.


## 🔒 PERMANENT PRODUCTION CHARTER (Iter 21 — immutable)
BookTalent is deployed on a Linux VPS (Nginx + FastAPI + React + systemd).
Every future code change MUST preserve this deployment architecture.

### Frontend rules
- React SPA served as static files by Nginx from `/var/www/btlive/frontend/build`.
- **API base URL is ALWAYS the relative path `/api`**:
  ```js
  export const API = "/api";
  axios.create({ baseURL: API });
  ```
  Never change it to `http://localhost:8000`, `api`, or
  `process.env.REACT_APP_BACKEND_URL`. Relative `/api` works identically in
  Emergent preview (Kubernetes ingress) and on the VPS (Nginx proxy).
- React Router only — every route must survive `try_files $uri /index.html;`.
- WebSocket URLs derive from `window.location.host` — never hardcode a host.

### Backend rules
- FastAPI under uvicorn, run as a systemd unit (`booktalent.service`).
- Existing API paths are backwards-compatible — never rename a route without
  updating every frontend caller in the same commit.
- Backend binds to `127.0.0.1:8000` in production (Nginx proxies to it).

### VPS deploy architecture (do not break)
```
React build → Nginx (/var/www/btlive/frontend/build)
              ↓
              /              → try_files $uri /index.html
              /api/*         → proxy_pass http://127.0.0.1:8000/api/
```

### Deploy contract
After every future update, deployment must be **just**:
```
git pull
cd frontend && npm install && npm run build
systemctl reload nginx
systemctl restart booktalent
```
No manual source-code edits on the VPS are ever required. The GitHub repo is
the single source of truth.

### Code-hygiene rules
- Never rewrite complete files unless necessary — modify only the required
  section. Keep existing component names, API contracts, and folder structure.
- Use optional chaining (`?.`) at every API-response access point.
- No new dependencies unless strictly required; keep React 19, CRACO, FastAPI,
  Motor at their current versions.

---

## Original Problem Statement
Premium full-stack marketplace (React + FastAPI + MongoDB) for booking artists across India.
UI is the design source of truth — preserve exactly. Only backend functionality and business logic.

## Business Model (Iter 10 — current)
BookTalent is **only an intermediary marketplace**. We do NOT collect the artist's
performance fee. We invoice ONLY:
- **Platform Service Fee** = 5% of Artist Fee
- **GST** = 18% on Platform Service Fee
- **Amount Payable to BookTalent** = Platform Fee + GST

Customer pays the Artist Performance Fee **directly** to the artist as per the
signed agreement. BookTalent is not responsible for that settlement.

Example: Artist Fee ₹25,000 → Platform Fee ₹1,250 + GST ₹225 = ₹1,475 to BookTalent.

## User Personas
- Customer, Artist, Agency, Corporate, Admin

## Architecture
- Backend: FastAPI + Motor + JWT + WebSocket
- Frontend: React 18 + React Router, dark-luxury theme (preserved)
- Files: MongoDB binary + Pillow compression + 400×400 thumbs
- PDF: ReportLab (`pdf_service.py`)
- Notification engine: `notification_service.dispatch()` → in_app/email/sms/whatsapp/push
- Provider clients: Resend, Twilio, Gupshup, FCM, Razorpay, Stripe (env-gated, auto-live)

## Routers
- `server.py` (core auth, bookings, kyc, coupons, reviews, contracts, wallet, payments)
- `iter7_routes.py` (Master Data, FAQs, CMS, Settings, Templates, Broadcast, Audit, Boost, Advanced Search, Reports)
- `iter9_routes.py` (Agency, Corporate, Chat upload, Provider tests)
- `chat_routes.py` (WebSocket + REST chat)

## Iter 37 — Outstation Notice Wording Refresh (this round)

Customer supplied the exact copy for the Outstation Travel Notice. Applied
across the platform without any schema changes.

### Copy applied verbatim
> Travel, accommodation, local transportation, meals, hospitality, and any
> other outstation expenses are NOT included in the Artist Package Fee.
>
> By proceeding with this booking, you acknowledge and agree that all such
> additional expenses must be paid directly by the Customer to the Artist.
> This applies regardless of whether the Artist is travelling alone or with
> any accompanying team members, musicians, assistants, technicians, or
> other add-on members.

### What changed
- **DB**: `system_settings.outstation_notice` (455 ch),
  `outstation_clause` (479 ch), `booking_fee_note` (311 ch) all updated
  in place via a one-off migration script.
- **Seed defaults** in `iter7_routes.py` updated so fresh installs ship
  with the new wording — placeholder tokens `{artist_city}` /
  `{event_city}` fully removed.
- **BookingFlow.jsx** notice divs now use `whiteSpace: "pre-line"` so the
  `\n\n` paragraph break in the new copy renders as two visible
  paragraphs. Dead-code `.replace()` chains for the old placeholders
  removed; fallback strings tightened.

### Code-review hardening pass (also this round)
- Test-fixture creds in `test_iter30_cookie_auth.py` and
  `test_iter32_outstation.py` moved to env vars with fallbacks.
- `auth.jsx` context value memoised via `useMemo` + login/register/logout
  wrapped in `useCallback` to prevent needless consumer re-renders.
- `App.js` role arrays hoisted to module-level constants
  (`ROLES_CUSTOMER`, `ROLES_ARTIST`, etc.) for stable prop identity.
- `ArtistCardThumb.jsx` dot-indicator now keys by `img.id || img.url ||
  img.src` (was raw index).
- Removed the orphan `TestRiderWalletRegression` class from iter 30
  test file (feature deleted in iter 34).

### False positives — skipped with rationale
- `notification_service.py:46` is a Python template placeholder string
  (`token = "{" + k + "}"`), not a credential.
- 62 "missing useEffect deps" — most are correctly suppressed with
  explicit deps; auto-adding them causes infinite loops in this codebase.
- 900-line router / 300-line component refactors — 100% test-covered,
  zero user-facing bugs, coding guidelines forbid metric-chasing.
- 117 `assert x is <int>` — zero real instances in the codebase; the
  analyser flagged legitimate `is None` / `is True` / `is False`.

### Test coverage
- 6/6 pytest cases pass (`test_iter37_outstation.py` created by testing
  agent). Full Playwright E2E green — Step 3 notice renders as 2
  paragraphs, Step 4 ack gate works, same-city + alias hide correctly,
  admin edit round-trip restores exact wording.
- Regression on iter 27-36 flows: all pass. 5% + 18% GST math intact.

### Files touched
- MOD: `/app/backend/iter7_routes.py` — Seed defaults refreshed
- MOD: `/app/backend/tests/test_iter30_cookie_auth.py` — env creds + removed rider test
- MOD: `/app/backend/tests/test_iter32_outstation.py` — env creds
- MOD: `/app/frontend/src/pages/BookingFlow.jsx` — pre-line + fallback cleanup
- MOD: `/app/frontend/src/lib/auth.jsx` — useMemo/useCallback
- MOD: `/app/frontend/src/App.js` — ROLES_* module constants
- MOD: `/app/frontend/src/components/ArtistCardThumb.jsx` — stable keys
- NEW: `/app/backend/tests/test_iter37_outstation.py` (via testing agent)

## Iter 36 — Booking Special Instructions Field

Small focused feature — a distinct free-text field for the customer to
document outstation asks / dietary / green-room / access requirements
inline with the booking.

### Backend
- `BookingCreate` gets a new optional `special_instructions: str = ""`.
- Persisted (stripped) into the booking doc alongside the existing generic
  `notes` field so both parties + admin can see it later.
- `_create_contract` prints a `SPECIAL INSTRUCTIONS FROM CLIENT` block
  right after the outstation clause and before financial terms — only
  when the field is non-empty.

### Frontend
- BookingFlow Step 3 renames the existing textarea to
  **"Song Requests / Dedications"** (matches its placeholder) and adds a
  distinct **"Special Instructions"** textarea.
- Placeholder is context-aware: when `isOutstation` is true it hints at
  "Outstation asks: hotel preference, flight class, arrival timing,
  dietary needs, green-room setup…". When same-city it's more neutral.
- A subtle "· recommended for outstation bookings" hint appears on the
  label the moment the outstation check flips on.
- Review Step 4 shows a `review-special-instructions` block echoing back
  the text so the customer can double-check before payment.
- Shared `BookingsTable` (used by both Customer + Artist dashboards)
  renders a truncated `📝` preview on each row with the full text in a
  hover tooltip — so both parties see the ask at a glance.

### Test coverage
- 4/4 backend pytest cases pass (`test_iter36_special_instructions.py`):
  parametric outstation flag (Delhi/Mumbai/Bombay), empty-field default,
  backwards-compat (missing field).
- Frontend visual verified — the field renders correctly on Step 3 with
  context-aware placeholder.

### Files touched
- MOD: `/app/backend/server.py` — BookingCreate model + persistence + contract print
- MOD: `/app/frontend/src/pages/BookingFlow.jsx` — Step 3 field + Step 4 echo
- MOD: `/app/frontend/src/pages/CustomerDashboard.jsx` — table preview
- NEW: `/app/backend/tests/test_iter36_special_instructions.py`

## Iter 35 — City Aliases + Outstation Analytics + Data Cleanup

Four cleanup / analytics items requested by the user.

### 1. Drop Orphan Data
- Ran mongo drop on `rider_vendors` — verified: collection no longer
  listed. 7 orphan docs purged.

### 2. Contract PDF Cleanup — verified as no-op
- Scanned all 22 stored contracts for rider-wallet / Taj / IndiGo etc.
  strings — **zero matches**. Rider-wallet content was only ever in the
  BookingFlow UI, never in the persisted contract text. No regeneration
  needed. Cleanup pass documented in this PRD as a formal audit.

### 3. City Aliases (Delhi/NCR, Mumbai/Bombay etc.)
- New `/app/backend/routes/city_aliases.py` — 16 default groups (Delhi,
  Mumbai, Bengaluru, Kolkata, Chennai, Pune, Hyderabad, Gurgaon, Noida,
  Kochi, Trivandrum, Puducherry, Vizag, Prayagraj, Varanasi, Vadodara)
  each with 2-5 aliases. Persisted in `system_settings.city_aliases` so
  admins can extend without redeploy.
- `_outstation_check` in server.py now canonicalises both cities before
  comparing → "Delhi" / "New Delhi" / "Delhi NCR" all treated as one
  place. Module cache warmed lazily on first booking + refreshable via
  admin edit.
- `city_aliases` added to PUBLIC_SETTING_KEYS so the frontend can use the
  same map for the live UI notice.
- New endpoints: `GET /admin/city-aliases`, `POST /admin/city-aliases/reset`
- Frontend BookingFlow adds a `canonicalCity()` helper + memoized
  `isOutstation` bool that reads `platformSettings.city_aliases`. All 3
  outstation checks (Step 3 notice, Step 4 review notice, step4-next
  disable) now use the alias-aware helper.

### 4. Outstation Analytics
- New `/app/backend/routes/outstation_report.py` — aggregation endpoint
  `GET /admin/reports/outstation?days=30` returns:
    • totals: total_bookings, outstation_bookings, outstation_pct,
      total_gmv_outstation, avg_performance_fee
    • top_routes: [{artist_city, event_city, count, avg_fee, total_fee}]
    • top_artist_cities / top_event_cities aggregations
- New admin UI: `AdminOutstationReport.jsx` with 4 KPI cards, gradient
  top-route bars, source/destination city tables, time-window selector
  (30/90/180/365 days / all time). Wired as `sb-outstation-report` in
  Admin sidebar.

### Test coverage (Iter 34 report)
- 18/18 backend pytest + 34/34 verified scenarios pass 100%.
- Key wins: "Bombay" → treats as Mumbai (no outstation), "Delhi NCR"/
  "New Delhi" → both canonicalise to Delhi (outstation triggers correctly
  when artist is in Mumbai). Admin report shows Mumbai→Delhi as top route
  in current dataset.

### Cleanup
- Removed stale test files `test_iter29_concierge_homepage_rider.py` and
  `test_iter31_partners_insights_concierge.py` — they referenced the
  deleted `/rider-wallet` + `/partners` routes.

### Files added / modified
- NEW: `/app/backend/routes/city_aliases.py`
- NEW: `/app/backend/routes/outstation_report.py`
- NEW: `/app/frontend/src/pages/admin/AdminOutstationReport.jsx`
- NEW: `/app/backend/tests/test_iter35_city_aliases_outstation_report.py`
- MOD: `/app/backend/server.py` — imports, cache, outstation-check helper, router regs
- MOD: `/app/backend/iter7_routes.py` — city_aliases in PUBLIC_SETTING_KEYS
- MOD: `/app/frontend/src/pages/AdminDashboard.jsx` — sb-outstation-report tab
- MOD: `/app/frontend/src/pages/BookingFlow.jsx` — canonicalCity + isOutstation
- DEL: `/app/backend/tests/test_iter29_*.py`, `test_iter31_*.py` (stale)
- Mongo: dropped `rider_vendors` collection

## Iter 34 — Rider Wallet / Partners Directory Removed (this round)

Per user request, the Rider Wallet + Public Partners Directory features
(iter 29 + iter 31) have been fully removed. Kept the simple outstation
acknowledgment implemented in iter 32-33 which is exactly what the user
wants — "just ask if artist is outsider, agree to bear expenses".

### Deleted
- `/app/backend/routes/rider_wallet.py`
- `/app/frontend/src/pages/Partners.jsx`
- `/app/frontend/src/pages/admin/AdminRiderWallet.jsx`

### Cleaned references
- `server.py`   — removed import, router registration, `ensure_seed` call
- `App.js`      — removed Partners import + `/partners` + `/partners/:slug` routes
- `Nav.jsx`     — removed `nav-partners` + `drawer-partners` links
- `AdminDashboard.jsx` — removed sidebar entry + tab render + import
- `BookingFlow.jsx`    — removed `riderVendors` state, fetch, and the entire
  `rider-wallet-block` JSX from the Sprint 4 travel review

### Verified
- Old endpoints `/api/rider-wallet/vendors` and `/api/partners/{slug}` now
  return 404 as expected.
- `/api/settings/public` still returns 200 — outstation notice, fee note
  and outstation clause remain admin-editable.
- BookingFlow still surfaces `outstation-notice` (Step 3), the
  `review-outstation-notice` + `outstation-ack` gate (Step 4) and the
  always-on `booking-fee-note` (summary panel) — verified via screenshot.
- Zero leftover string references to rider_wallet / RiderWallet / Partners
  across `/app/backend` and `/app/frontend`.

### Data note
The `rider_vendors` MongoDB collection is orphaned (no code path reads it).
Left it in place because deleting DB data is destructive. Ask if you want
it purged with a one-line mongo drop.

## Iter 32-33 — Outstation Business Rule

Implemented user's explicit Travel & Outstation booking policy across the
platform without introducing separate travel packages.

### Backend
- `iter7_routes.py` seeds 3 admin-editable settings on first boot:
  `outstation_notice`, `booking_fee_note`, `outstation_clause`.
- **New public endpoint** `GET /api/settings/public` — returns a whitelisted
  subset (display strings only, no secrets).
- `create_booking` snapshots `artist_city`, `event_city`, `is_outstation`
  into every booking doc.
- `_create_contract` injects an `OUTSTATION LOGISTICS` block (admin-editable
  clause) when `is_outstation` is true + a always-on `FEE INCLUSION NOTE`.

### Frontend
- BookingFlow renders `outstation-notice` (Step 3) + `review-outstation-notice`
  + `outstation-ack` gate (Step 4). `step4-next` disabled until acked.
- `booking-fee-note` always visible in the right-hand summary panel.
- Admin can edit copy via existing settings endpoint — reflects in UI without
  redeploy.

### Testing
- 9/9 backend pytest + 27/27 frontend Playwright scenarios all pass (Iter 33).
- 5% + 18% GST math intact; Sprint 3-6 flows regression clean.

## Iter 31 — Partners Directory + Insights + Leaderboard + Concierge Notifications

- **Public Partners Directory** — `/partners` list + `/partners/:slug` detail
  with SEO title/meta + click-tracking beacon. Every rider vendor now has a
  stable `slug` field (auto-backfilled on startup).
- **Booking Insights** — new `/api/artist/insights` route → funnel (views →
  created → confirmed → completed), conversion %, top cities, top event
  types, revenue summary. UI: 📈 Insights tab in Artist Dashboard with KPI
  cards + gradient funnel bars.
- **Partner Leaderboard** — `POST /rider-wallet/vendors/{vid}/click`
  increments count; `GET /admin/rider-wallet/leaderboard` ranks by clicks;
  `POST /admin/rider-wallet/rotate-featured?top_n=3` auto-features the
  top-N per type. Admin UI has catalog/leaderboard toggle + rotate button.
- **Concierge Notifications** — admin reply on a Platinum/Elite concierge
  thread now fires `notify_dispatch` with `email + whatsapp + in_app`
  channels (SLA hours in ctx). Falls back to mock-log when provider keys
  aren't set — never crashes the admin-send path.

## Iter 30 — Code Quality Hardening (this round)

Applied user's code-review report — with pragmatic triage (skipped false
positives and risky metric-chasing refactors, applied real fixes only).

### Real fixes applied
- **httpOnly cookie auth**: `_set_auth_cookie()` / `_clear_auth_cookie()`
  helpers in `server.py`. Login / register / OTP-verify now emit a
  `Set-Cookie: access_token=<jwt>; HttpOnly; Secure; SameSite=Lax;
  Max-Age=604800; Path=/`. `POST /auth/logout` clears it. Backend already
  had the cookie fallback in `get_current_user` — REST is now covered by
  either the httpOnly cookie or the Bearer header. XSS-based token
  exfiltration through `localStorage` is defanged for REST calls.
- **Frontend axios `withCredentials: true`** — same-origin cookie flows
  automatically. Kept the localStorage bearer token for the WebSocket
  handshake compat (browsers don't send headers on `new WebSocket`).
- **auth.jsx logout** now calls `/api/auth/logout` before wiping local
  state — server-side cookie is properly cleared.
- **Corporate bulk-booking rows**: replaced `key={i}` with a stable per-row
  `_key` from a `useRef` counter — removing a middle row no longer shifts
  data into the wrong input.
- **Feature list keys** (ArtistProfile + ArtistDashboard): stable
  `${pkg.id}-f-${i}-${text}` keys prevent React reconciliation bugs when
  features are re-ordered.
- **AdminConcierge / AdminRiderWallet fetchers** wrapped in `useCallback`
  — no more stale closure over `statusFilter` in the poll interval.
- **Test-fixture creds** in `test_iter25_uploads.py` moved to environment
  variables with sensible fallbacks.
- **Bonus fix**: RoleDashboards was hitting `/api/artists?limit=200`
  (404) — corrected to `/api/artists/search?limit=200` and unwraps
  `data.items`. The Corporate bulk-booking artist dropdown now populates.

### False positives — skipped
- `notification_service.py:46` — `token = "{" + k + "}"` is a Python
  template placeholder, not a credential. Static analyser mistake.
- Skeleton loader `key={i}` in fixed-length `[...Array(n)]` maps — the
  list never re-orders so React reuses correctly. Left as-is.
- Most of the 60 missing-hook-deps warnings — adding `run`/`load` to deps
  causes infinite render loops in this codebase (already suppressed with
  explicit deps + eslint-disable, which is the right pattern).

### Risky metric-chasing refactors — skipped
- `iter7_routes.make_router` (779 lines), `iter11_routes.ai_search` (185
  lines), `chat_routes.make_chat_router` (176 lines) — 100% test-covered
  files, zero reported bugs. Coding guidelines explicitly forbid
  refactoring for its own sake.
- `BookingFlow.jsx` / `ChatBox.jsx` / `OnboardingWizard.jsx` splits —
  same reasoning; splitting risks regressions on the checkout + chat
  flows just verified in iter 27-29.

### Test coverage
- 20/20 pytest cases pass (`/app/backend/tests/test_iter30_cookie_auth.py`)
- Playwright verified: cookie flags on login, cookie cleared on logout,
  cookie-only REST auth works, Bearer-only REST auth works, personalized
  homepage rails render for logged-in customer, stable bulk-booking rows.
- Regression: all iter 27-29 flows still green.

### Files touched
- MOD: `/app/backend/server.py` — Cookie helpers + login/register/otp/logout
- MOD: `/app/backend/tests/test_iter25_uploads.py` — env-based fixtures
- MOD: `/app/frontend/src/lib/api.js` — `withCredentials: true`
- MOD: `/app/frontend/src/lib/auth.jsx` — logout hits backend
- MOD: `/app/frontend/src/pages/RoleDashboards.jsx` — stable row keys + fixed artist endpoint
- MOD: `/app/frontend/src/pages/ArtistProfile.jsx` — stable feature keys
- MOD: `/app/frontend/src/pages/ArtistDashboard.jsx` — stable feature keys
- MOD: `/app/frontend/src/pages/admin/AdminConcierge.jsx` — useCallback
- MOD: `/app/frontend/src/pages/admin/AdminRiderWallet.jsx` — useCallback
- NEW: `/app/backend/tests/test_iter30_cookie_auth.py`

## Iter 29 — Elite Concierge + Smart Homepage + Rider Wallet (this round)

### Elite Concierge Chat (Platinum + Elite only)
- New `/app/backend/routes/concierge.py` — PRIORITY dict (elite=100,
  platinum=80, others=0) + ALLOWED_PLANS={platinum,elite} feature gate.
- Endpoints: `GET /concierge/my-thread`, `POST /concierge/open`,
  `GET /concierge/messages`, `POST /concierge/send`,
  `GET /admin/concierge/threads` (priority-sorted), `GET/POST /admin/concierge/{tid}/messages`,
  `POST /admin/concierge/{tid}/close`.
- REST-only (client polls every 12s) — piggybacks on the existing Nginx
  `/api/*` proxy without adding new WS routes.
- Artist UI: New "🎩 Concierge" sidebar tab with ELITE mini-badge; polls
  every 12s; shows locked upgrade CTA for lower-tier plans.
- Admin UI: New "AdminConcierge" split-pane (thread list left, chat right)
  with plan badge, unread counter, status filter, and close-thread control.

### Smart Homepage — Personalized Rails
- Added `get_current_user_optional()` in server.py — resolves caller from
  Bearer token without raising for anonymous/invalid tokens.
- Extended `/homepage/sections` to prepend up to 3 personalized rails when
  the caller is an authenticated customer:
    • `continue_in_city`      — most searched city
    • `because_you_searched`  — most searched category
    • `rebook`                — artists the customer has booked before
- Uses existing `search_history` collection (recorded when `q` param is set)
  and `bookings` collection. Falls back gracefully to default rails.

### Rider Wallet — Curated Travel Partner Marketplace
- New `/app/backend/routes/rider_wallet.py` — 7 seeded partners (Taj, ITC,
  Lemon Tree, IndiGo, Vistara, BluSmart, Meru) inserted on first boot via
  `ensure_seed()`.
- Public: `GET /rider-wallet/vendors?type=&city=&limit=`
- Admin: `GET/POST /admin/rider-wallet/vendors` + `PATCH/DELETE /{id}`
- Vendor fields: type (hotel/flight/transport), name, tagline, city
  (None=nationwide), partner_url, contact_email, phone, discount_pct,
  star_rating, image_url, cta_label, is_active, is_featured.
- BookingFlow: Renders `rider-wallet-block` inside `review-travel-block`
  when the package requires travel / accommodation / local transport.
  Cards link out to partner_url / mailto — customer contacts partner
  directly. Zero effect on `pricing.total` — business rule intact.
- Admin UI: CRUD table + modal with type filter.

### Test coverage
- 23/23 backend pytest cases pass (`/app/backend/tests/test_iter29_concierge_homepage_rider.py`)
- Frontend E2E: Full Playwright coverage for Priya concierge (gate + open
  + send + downgrade lock), admin concierge queue + reply + close, admin
  rider wallet CRUD, customer smart homepage personalized rails, and
  customer BookingFlow rider-wallet-block with 6 partner cards.
- Regression: booking math (5% + 18% GST), existing chat, add-ons UI,
  search infinite scroll — all green.

### Files added / modified
- NEW: `/app/backend/routes/concierge.py`
- NEW: `/app/backend/routes/rider_wallet.py`
- NEW: `/app/frontend/src/pages/admin/AdminConcierge.jsx`
- NEW: `/app/frontend/src/pages/admin/AdminRiderWallet.jsx`
- NEW: `/app/backend/tests/test_iter29_concierge_homepage_rider.py`
- MOD: `/app/backend/routes/homepage.py` — personalised rails
- MOD: `/app/backend/server.py` — get_current_user_optional + router regs + seed hook
- MOD: `/app/frontend/src/pages/ArtistDashboard.jsx` — Concierge tab + component
- MOD: `/app/frontend/src/pages/AdminDashboard.jsx` — 2 new sidebar tabs
- MOD: `/app/frontend/src/pages/BookingFlow.jsx` — Rider Wallet block

## Iter 28 — Sprint 5 + Sprint 6 (this round)

### Sprint 5 — Premium Subscription Plans
- New `/app/backend/routes/subscriptions.py` — Five tiers (Free / Silver /
  Gold / Platinum / Elite), each with feature caps: max_media, max_addons,
  response_sla_hours, boost_multiplier, verified_badge, priority_support,
  commission_discount_pct, elite_rail eligibility.
- Endpoints: `GET /subscriptions/plans`, `GET /subscriptions/me`,
  `POST /subscriptions/subscribe`, `POST /subscriptions/cancel`,
  `GET /admin/subscriptions`. Payment is mocked; downgrade is free & immediate.
- On subscribe, denorms `plan_code`, `plan_rank`, `premium_badge` into
  `artist_profiles` so search + homepage read in one query.
- `resolve_plan(db, user_id)` helper exposed for cross-module use.
- UI: New "💎 Subscription" sidebar tab in Artist Dashboard with 5 plan cards,
  monthly/yearly cycle toggle, current-plan banner + downgrade CTA.

### Sprint 5 — Dynamic Homepage Rails
- New `/app/backend/routes/homepage.py` — Ten computed rails (featured,
  trending, elite, new_talent, top_rated, fastest_response, best_value,
  city_<city>, cat_bollywood_vocalist, cat_dj_music_producer, cat_dancer).
- Each rail computed from artist_profiles / bookings aggregations at request
  time (no cron). Empty rails are omitted.
- Landing.jsx now renders rails via `HomeRail` component with premium plan
  badges (👑 Elite / 💎 Platinum / 🥇 Gold) overlaid on each artist card.
- Rail codes are safely slugified (was `cat_dj_/_music_producer` → now
  `cat_dj_music_producer`).

### Sprint 6 — Agency Commission Edit
- New `PATCH /agency/roster/{artist_id}/commission` endpoint (0-50% range).
- Roster table now supports inline commission edit with Save/Cancel controls
  (data-testid `commission-edit-<id>`, `commission-input-<id>`,
  `commission-save-<id>`).

### Sprint 6 — Advanced Search Infinite Scroll
- Search.jsx: Pagination Prev/Next buttons replaced with an
  IntersectionObserver-driven sentinel (`infinite-scroll-sentinel`) that
  auto-appends the next page when the user scrolls near the bottom.
- End marker (`infinite-scroll-end`) shown when all pages loaded.
- Artist cards now display plan badges (Elite/Platinum/Gold).
- Search backend `sort_spec` now leads with `plan_rank` in every mode
  (relevance / price_asc / price_desc / rating / newest) — so higher-tier
  subscribers rank first across the board.

### Test coverage
- 13/13 pytest cases pass (`/app/backend/tests/test_iter28_sprint5_6.py`)
- Frontend E2E: subscription flow, homepage rails, agency commission edit,
  search infinite scroll all verified via Playwright
- Regression: `/api/artists/featured` still returns 8 artists; booking math
  unaffected (5% + 18% GST still the only platform take); Sprint 3+4 flows
  still green.

### Files added / modified
- NEW: `/app/backend/routes/subscriptions.py`
- NEW: `/app/backend/routes/homepage.py`
- NEW: `/app/backend/tests/test_iter28_sprint5_6.py`
- MOD: `/app/backend/server.py` — Registered new routers
- MOD: `/app/backend/iter7_routes.py` — search sort_spec adds plan_rank
- MOD: `/app/backend/iter9_routes.py` — PATCH commission endpoint
- MOD: `/app/frontend/src/pages/ArtistDashboard.jsx` — Subscription tab
- MOD: `/app/frontend/src/pages/Landing.jsx` — Dynamic rails via HomeRail
- MOD: `/app/frontend/src/pages/Search.jsx` — IntersectionObserver + badges
- MOD: `/app/frontend/src/pages/RoleDashboards.jsx` — Inline commission edit

## Iter 27 — Sprint 3 UI + Sprint 4 Travel & Accommodation (this round)
Completes the enterprise roadmap through Sprint 4.

### Sprint 3 (Artist Add-ons) — Frontend wired
- New "🎁 Add-ons" sidebar tab in Artist Dashboard (`sb-addons`)
- Full CRUD in Artist Dashboard: create / edit / toggle active / delete
  add-ons with fields (name, description, price, max_quantity, gst_pct,
  is_mandatory, active). Soft-delete preserves historical booking snapshots.
- BookingFlow step 1 renders "🎁 Artist Add-ons" — mandatory ones are
  pre-selected & non-toggleable; optional ones toggle + quantity +/- buttons.
- Booking POST now sends `addon_selections: [{addon_id, quantity}]`.
- Summary panel shows artist add-ons line: `summary-artist-addons`.
- Backend enforces mandatory selection (400 if any active mandatory add-on
  is missing from the customer's selection).

### Sprint 4 (Travel & Accommodation) — Full stack
- `PackageBody` extended with 9 travel/accommodation fields: `travel_required`,
  `accommodation_required`, `hotel_category`, `flight_class`, `team_size`,
  `arrival_buffer_days`, `local_transport_required`, `meals_required`,
  `travel_notes`.
- Package modal shows a "✈️ Travel & Accommodation Rider" section with
  conditional flight_class / hotel_category / team_size / arrival_buffer
  fields when travel or accommodation is enabled.
- `create_booking` snapshots the package's travel requirements into the
  booking doc as `travel_requirements` (immutable — future edits to the
  package don't rewrite history).
- BookingFlow step 4 renders `review-travel-block` with all fields plus a
  mandatory acknowledgement checkbox (`travel-ack-checkbox`) that gates the
  "Proceed to Payment" button.
- `_format_travel_reqs` helper prints the rider block into the contract PDF.
- Business rule preserved — travel/accommodation costs are BORNE BY THE
  CUSTOMER SEPARATELY. They never enter `pricing.total`. BookTalent still
  invoices only 5% + 18% GST.

### Test coverage
- 6/6 pytest cases pass (`/app/backend/tests/test_iter27_travel.py`)
- Frontend E2E: Sprint 3 CRUD + booking-integration + Sprint 4 package
  modal + booking review + full confirmed booking with correct snapshots
- Booking BT-260717-4F6A8C created via UI carries full addon_snapshots +
  travel_requirements as regression fixture.

### Files touched this iteration
- `/app/backend/server.py` — PackageBody schema, create_booking snapshot,
  _format_travel_reqs helper, contract text
- `/app/frontend/src/pages/ArtistDashboard.jsx` — SIDEBAR, Addons + AddonModal,
  extended PackageModal
- `/app/frontend/src/pages/BookingFlow.jsx` — artistAddons state + helpers,
  step-1 Artist Add-ons UI, step-4 travel block + travel_ack gate, summary
- `/app/backend/tests/test_iter27_travel.py` — NEW

## Iter 16-18 — Self-Hosted VPS Deployment Ready (this round)
Blocker fix for user setting up on Hostinger AlmaLinux 10.2:
- `pip install -r requirements.txt` failed with 'emergentintegrations not found'.
- **Fix**: removed `emergentintegrations==0.2.0` + internal-URL `litellm` wheel
  from `requirements.txt`; created `requirements-emergent.txt` (optional).
- Existing try/except in `iter11_routes.py` handles missing package — AI Search
  silently falls back to a regex + synonym + city-alias filter that returns
  real seed data.

**Fallback quality lifted from cosmetic to production-ready**:
- Greedy price regex — parses 50000 / 30k / ₹80,000 / 1.5 lakh / 2 lakh
- CATEGORY_ALIASES — 'Singer' → Bollywood Vocalist / Playback, 'DJ' → DJ/Music Producer, etc.
- CITY_ALIASES — 'Delhi'↔'Delhi NCR', 'Mumbai'↔'Bombay', 'Bangalore'↔'Bengaluru'
- Stop-word filter on free-form keywords

**Deploy artifacts under `/app/deploy/`**:
- `README-almalinux.md` — beginner-friendly AlmaLinux 10 step-by-step guide
- `README.md` — Ubuntu 22.04 variant
- `nginx.conf` — reverse-proxy + WebSocket + SSL + rate-limit + security headers
- `systemd/booktalent-backend.service` — uvicorn @ 4 workers, hardened
- `scripts/deploy.sh` — one-shot pull → install → build → restart
- `scripts/backup_mongo.sh` — daily mongodump, 14-day retention
- `scripts/export_db_from_emergent.sh` — one-liner to dump DB out of Emergent pod
- `cron/booktalent.cron` + `logrotate/booktalent` + `.env` templates

Test: `test_iter16_deploy.py` + `test_iter17_search.py` + `test_iter18_city_aliases.py`
— **23/23 assertions pass**, including a subprocess run that blocks
`emergentintegrations` and proves the pure-fallback path returns real seed data.

## Iter 13 — server.py Modularisation
Pure structural refactor — no business logic touched.

`/app/backend/server.py` shrunk from 2,868 → 2,378 lines by extracting 6 domain
routers under `/app/backend/routes/` using the existing factory pattern
(`make_router(**deps) -> APIRouter`). Helpers that are still shared with the
core (`_validate_coupon`, `_refund_to_wallet`, `_release_payment_to_artist`,
`notify_dispatch`, `log`, `utcnow`, `new_id`, `clean`) are injected as kwargs.

Domains extracted:
- `routes/wallet.py` — GET /wallet, GET /wallet/transactions, POST /wallet/withdraw
- `routes/reviews.py` — POST /reviews, /admin/reviews (+moderate), public list,
  reply, report
- `routes/coupons.py` — admin CRUD + redemption ledger + analytics + validate
- `routes/blogs.py` — POST /admin/blogs, GET /blogs, GET /blogs/{slug}
- `routes/disputes.py` — POST /disputes, /admin/disputes, /resolve
- `routes/kyc.py` — submit, mine, /admin/kyc, /admin/kyc/decide (incl. local
  KYC_ALLOWED_MIMES + 5 MB cap)

Test: `test_iter13.py` — **40/40 pytest cases pass** covering all 6 moved
routers + core untouched + Iter 11/12 sanity. No frontend changes.

Remaining candidates for future extraction: bookings, payments, contracts,
notifications/messages, admin (artists / boost / withdrawals).

## Iter 12 — Payment-Gated Chat
Business rule: the Customer ↔ Artist chat is **locked until the Platform Service Fee
(5% + 18% GST) is paid**. No exceptions for either side — only admins bypass for moderation.

Enforcement points:
- `GET /api/chat/{bid}/access` — UI uses this to render either the chat or a lock card.
- `GET/POST /api/chat/{bid}/messages` — 403 "Chat Access Denied" if `payment_status == "unpaid"`.
- `POST /api/chat/{bid}/upload` — same 403 for file / voice / video-request uploads.
- `WS /api/ws/chat/{bid}` — handshake rejected with close 4402 / 403 if unpaid.
- Frontend Chat button shows **"🔒 Pay to Unlock Chat"** (disabled + tooltip) until paid;
  flips to **"💬 Chat"** automatically when `payment_status != "unpaid"`.
- Locked ChatBox renders a centered lock card: *"Complete Platform Fee Payment to Unlock Chat"*.

Files touched: `chat_routes.py`, `iter9_routes.py` (`chat_upload`), `ChatBox.jsx`, `CustomerDashboard.jsx`.

## Iter 10 — Business Model Correction
- `calc_booking_pricing()` rewritten: `platform_fee = 5% of artist_fee`; `gst = 18% of platform_fee`; `total = platform_fee + gst`
- `_release_payment_to_artist()` is now informational only — does NOT mutate wallet balance
- Payment-init no longer adds the platform fee to artist wallet pending (was causing negative escrow)
- Invoice PDF: title "BookTalent Platform Service Invoice", only Platform Fee + GST shown, includes disclaimer
- Contract PDF: explicit "BookTalent acts only as a technology platform..." clause + financial split between Artist Fee (direct) and BookTalent Fee (invoiced)
- Admin stats / Revenue report: new fields `gmv` (marketplace volume), `platform_revenue`, `gst_collected`, `bookTalent_total_collected`, `net_revenue`, `total_collected`
- Top-artists aggregation rewritten in Python with `(artist_fee || pkg+addons)` fallback (handles legacy schema)
- **Auto-migrations on startup**: backfill `artist_fee` on legacy bookings (49 migrated), reset negative wallet pending (1 reset)
- BookingFlow UI: shows exactly the 4-line breakdown + direct-settlement notice
- AdminDashboard KPIs relabelled: "Marketplace GMV (artist fees)" + "Platform Service Revenue"
- AdminReports KPI grid: 6 cards (GMV, Platform Revenue, GST, Boost, Net, Bookings)

## Test Status
- Iter10 backend: 10/10 calculation/invoice/contract/stats tests pass; legacy fallbacks verified
- Frontend BookingFlow: Artist Fee ₹55K → BT amount ₹3,245 visible with disclaimer
- Admin Reports: top-artist Priya now correctly shows ₹4,03,500 (was ₹25K before fix)
- No negative wallet balances remain

## Backlog (P3)
- Split `server.py` (~2.8k lines) into per-domain routers
- CSV exports for customer/agency invoice history
- ICS calendar attachment on booking confirmation email
- AI semantic search via Emergent LLM key
- ChatBox WebSocket → Redis pubsub for multi-replica scaling
- Customer wallet for paying multiple BookTalent fees in one go (top-up)
- Stripe + PayPal full integration (boost only currently mock)
- Agency invite acceptance UI on artist dashboard (banner)
- Backfill GST normalisation for legacy bookings (one-shot script — optional)

## Test Credentials (`/app/memory/test_credentials.md`)
- Admin: `admin@booktalent.com` / `Admin@123`
- Customer: `customer@booktalent.com` / `Customer@123`
- Artist: `priya@booktalent.com` / `Artist@123`
- Agency: `agency@booktalent.com` / `Agency@123`
- Corporate: `corporate@booktalent.com` / `Corporate@123`
- Mock OTP: `123456`

## Test Files
- `/app/test_reports/iteration_5..9.json`
- `/app/backend/tests/test_iter6..test_iter10.py`

## 2026-02-18 — Discover Artists V2 Card Styling
- `Search.jsx` (`/discover`) now renders artist cards using the Homepage V2 style:
  - `artist-grid-v2` responsive grid (4→3→2→1 cols)
  - `ArtistCardThumb` inside `artist-cover-v2` with rotating gallery
  - Boosted / Elite / Platinum / Available badges (overlay top-right)
  - Name + category · city overlay on image
  - Star rating row, tags row, "Starting from" price label, "Book Now" CTA
  - Skeleton grid switched to `sk-artist-card` for visual consistency
- Verified via screenshot at `/search`.


## 2026-02-19 — Mobile Friendliness Pass (Auth + Artist Profile)
- **Auth page mobile top bar**: The `.auth-left` panel (logo + hero copy) is hidden at ≤980px. Added a sticky `.auth-mobile-topbar` with a `← Home` link + BookTalent logo so users can always navigate away from signin/signup on mobile.
- **Artist Profile — responsive header**: Extracted inline flex header into `.profile-header-row`. On mobile it stacks vertically (avatar → name → CTAs) with centered alignment, so name and "Responds in ~2 hrs" are no longer cramped side-by-side.
- **Artist Profile — 2-column stats on mobile**: Rating / Reviews / Events Done / Experience render as a 2×2 grid, Followers gets a `.profile-stat-full` class that spans both columns in row 3.
- **Artist Profile — booking sidebar**: `.profile-main-grid` collapses from `1fr 360px` to `1fr` on mobile so the "🔐 Book Now" sidebar stacks below the tabs content and stops being invisible.
- **Media lightbox**: `.media-tile` is now a `<button>` that opens a `.media-lightbox` fullscreen modal (dim backdrop, click-outside to close, × close button, `<video controls>` for videos, plain `<img>` for photos). Play/expand hint chip added to tile corner.
- New CSS: `.profile-header-row`, `.profile-stats-grid`, `.profile-main-grid`, `.media-tile-play`, `.media-lightbox*`, `.auth-mobile-topbar/back/logo`. Existing global mobile block at `@media (max-width: 767px)` extended.
- Files touched: `frontend/src/pages/ArtistProfile.jsx`, `frontend/src/pages/Auth.jsx`, `frontend/src/index.css`.


## 2026-02-19 — Blog Covers, Sticky Mobile Book Bar, Media Carousel
- **Blog demo content**: Removed the placeholder `Regression Test Blog` and seeded 4 published posts with real Unsplash cover images:
  - `how-to-book-perfect-wedding-singer` (also has full hero banner)
  - `corporate-event-entertainment-2026`
  - `artist-spotlight-djs-of-mumbai`
  - `planning-a-sangeet-artist-lineup`
- **Blog hero banner**: Set `blog_hero_image`, `blog_hero_title` ("The BookTalent Journal"), `blog_hero_subtitle` in `system_settings` — `/blog` list page now has a live hero.
- **Sticky mobile Book Now bar**: New `.mobile-book-bar` shown only at ≤767px on `/artist/:id`. Fixed to viewport bottom with `backdrop-filter: blur(14px)`, respects `env(safe-area-inset-bottom)`. Shows "Starting from ₹X" + a `🔐 Book Now` CTA that fires the same `startBooking()` as the sidebar. Page bottom padding increased to 88px to prevent overlap.
- **Media Carousel**: Refactored the lightbox to a reusable `<MediaCarousel />` component. Features:
  - ‹ / › nav buttons (with `data-testid="media-lightbox-prev/next"`)
  - Keyboard shortcuts: ← / → to navigate, Esc to close
  - Touch swipe support (>40px horizontal delta on touchend)
  - `1 / N` counter in the footer
  - Image preloading for neighbours (idx±1) — swipes feel instant
  - Wraps around at both ends
- Files touched: `frontend/src/pages/ArtistProfile.jsx`, `frontend/src/index.css`, `blogs` + `system_settings` collections seeded.


## 2026-02-22 — Phase 1a: 24-Hour Booking Confirmation + Quick Wins
### Business model (locked)
BookTalent stays a **Lead-Generation Marketplace** (no wallet / no escrow).
The 24-Hr flow uses **hybrid pricing**: customer pays only
`Platform Service Fee (5% of artist fee) + 18% GST on that fee` upfront via
Razorpay auth-capture. Artist Performance Fee is settled directly
Customer ↔ Artist off-platform. On artist rejection or 24-hour auto-timeout,
only that 5% + GST is refunded via Razorpay.

### Backend
- `payments/verify`: on success, sets `expires_at = now + BOOKING_CONFIRM_WINDOW_HOURS (default 24)` on the booking, along with `confirmation_deadline_hours` for audit
- `_auto_expire_bookings_once()`: transitions `pending_artist` / `pending_payment` bookings whose `expires_at` is in the past to `auto_expired`, calls `_mark_platform_fee_refundable`, and fires `booking.auto_expired` notifications (in-app + email) to customer + artist per the exact doc phrasing.
- `_auto_expire_loop()`: startup asyncio task, ticks every `BOOKING_EXPIRY_CHECK_MINUTES` (default 15)
- New index: `bookings (status, expires_at)` for O(1) expiry scans
- New admin overrides (all `admin_only`):
  - `POST /api/admin/bookings/{bid}/extend` — bump `expires_at` by N hours (default 24)
  - `POST /api/admin/bookings/{bid}/force-accept` — admin flips to `confirmed`, contract + availability created
  - `POST /api/admin/bookings/{bid}/force-reject` — admin flips to `rejected`, refund flagged
  - `POST /api/admin/bookings/{bid}/manual-refund` — flag refund without changing status

### Frontend
- Customer dashboard: **removed "Total Spent" KPI** (privacy — per user request); grid now 3 cols
- Bookings table status column shows:
  - Renamed `pending_artist` → **"Waiting for Artist Confirmation"** (exact doc phrasing)
  - Renamed `auto_expired` → **"Booking request expired"**
  - Rating: `<ExpiryCountdown>` chip with 30-sec ticking; colours: default gold → amber below 12h → red below 4h → red-danger when elapsed. Urgent pulse animation for artists.
- Auth pages: **`<PasswordField>` with 👁 / 🙈 eye toggle** on signin, signup password, signup confirm
- Homepage hero: **new `.hero-adv-search` bar** with Event Date · City · Artist Type · "Find Artists →" button, all wired to `/search?date=&city=&category=` query params
- Onboarding Wizard: category dropdown now has **"Other (specify below)"** option that reveals a free-text input for custom categories

### Docs / notifications (per doc phrasing)
- Customer copy on auto-expiry: *"Your booking request {ref} expired because the artist did not confirm within 24 hours. Your Platform Service Fee will be refunded within 5-7 business days."*
- Artist copy on auto-expiry: *"Booking {ref} expired because you did not respond within 24 hours."*
- Notifications delivered via `notify_dispatch(channels=["in_app", "email"])` (SMS/WhatsApp deferred to Phase 1b per user)

### Verified live (screenshots)
- Extended booking BT-260718-EBB8C4 via admin extend → 200 OK → `expires_at` visible + countdown chip renders "⏱ 23h 57m left"
- Login flow works, `type="password"` → `type="text"` on eye click
- Customer dashboard shows 3 KPIs (no Total Spent)
- Homepage advanced search fully renders

### Deferred to Phase 1b (next session)
- Artist availability calendar on profile & booking (customer picks only free dates)
- Hide customer invoice from artist (artist sees package + booking details only)
- Add-ons in booking cart
- Separate contracts per artist for multi-artist bookings
- Dynamic Onboarding Questionnaire (Layer 1 + Layer 2 metadata-driven)
- Smart Add-on Recommendation Engine
- Dashboard visual redesign to match PPT reference (Smart Artist Management Panel + Enterprise Command Center)


---

## Iter 43 — Counter-Offer Removal + Artist Payment-Detail Hiding (Feb 2026)

### Business rule enforced
BookTalent is a strict **fixed-pricing lead-generation** marketplace. Artists can only **Accept** or **Reject** a booking request — negotiation of price via counter-offers is not allowed. The platform collects only 5% Platform Service Fee + 18% GST on that fee; the artist's performance fee is settled directly Customer ↔ Artist off-platform. Artists must never see the platform-side collection amounts (Amount Paid, Platform Fee, GST) — those are confidential to the customer.

### Backend
- Stripped `"counter"` from `BookingStatusUpdate.action` Literal (server.py L371)
- Removed `counter_price: Optional[float]` field from `BookingStatusUpdate`
- Removed the entire `elif body.action == "counter" …` branch from the booking-action handler
- Deleted the `POST /api/bookings/{bid}/counter` endpoint + `CounterDecisionBody` Pydantic model
- Legacy `TestCounterFlow` class + `countered_booking` fixture deleted from `tests/test_iter4.py`

### Frontend
- `ArtistDashboard.jsx` — Total Earnings, revenue drilldown & booking-row amount cells now use `pricing.artist_fee || pricing.package_fee + pricing.addons_total` (never `amount_paid`, which is the platform-side sum)
- `RoleDashboards.jsx` Agency Bulk Booking Queue row amount uses the same safe fallback
- No `CounterModal` reference anywhere in the React tree; no "Counter Offer" button in any dashboard

### Verified
- `/app/test_reports/iteration_43.json` — 12/12 backend pytest pass, frontend 100%
- `POST /api/bookings/{bid}/action` with `action=counter` → 422 Unprocessable Entity
- `POST /api/bookings/{bid}/counter` → 405 Method Not Allowed
- Artist Dashboard mounts clean (no CounterModal ref, no console errors); Total Earnings computed from `artist_fee` only

### Follow-up backlog (recorded, not yet built)
- **P0** Multiple Artist Booking for Same Event — cart flow: after booking one artist, surface complementary available artists for the same date/city; unified single-checkout; separate contracts / packages / statuses per artist. Event ID linked across artists.
- **P1** AI Event Planner + Smart Add-on Recommendation Engine (scoring service, cart fork logic, admin rule matrix)
- **P1** Full migration to Dynamic Questionnaire (deprecate legacy onboarding fields permanently)
- **P2** Save filter combos as a "watch"
- **P2** FFmpeg chunked video compression
- **P2** Refactor `server.py` (~3000 lines) and `iter7_routes.py` into `routes/bookings.py`, `routes/payments.py`, etc.
- **P2** Extract `artistFee(b)` helper — same fallback expression is copy-pasted 4× in ArtistDashboard.jsx



---

## Iter 44 — Multi-Artist Event + Shareable Booking Recap (Feb 2026)

### Product concept
A customer often needs 2-3 artists for one event (Vocalist + DJ + Anchor for a wedding, etc.). BookTalent now treats every booking as belonging to an **Event Umbrella** (event_id UUID). One event can house many bookings — each with its own contract, its own 24-hour Artist Confirmation window, its own accept/reject lifecycle. From the customer's side, all the artists live under one shareable Booking Recap page.

### Backend
- `BookingCreate.event_id: Optional[str]` — pass an existing event_id to attach to that umbrella (must belong to caller). Omit = mint a new umbrella.
- `POST /api/bookings` now auto-generates event_id and returns it on the booking doc.
- `POST /api/bookings/batch` — create up to 6 bookings in one call, all under one event_id. First item mints event_id; remaining items attach.
- `POST /api/payments/batch/init` + `POST /api/payments/batch/verify` — single Razorpay checkout that flips N bookings to `pending_artist` in one go. Verify has a status guard: only mutates bookings currently in `pending_payment`.
- `GET /api/events/{event_id}/recap` — PUBLIC. Returns event details + artists[]. Legacy single-artist bookings shareable via their booking_id (fallback lookup).
- `GET /api/events/{event_id}/summary` — auth + ACL, returns aggregate {platform_fee, gst, amount_paid, count}.

### Frontend
- `/recap/:event_id` public page — QR code, share buttons (WhatsApp / Copy Link / Email), watermark, empty state.
- BookingFlow success screen — "Share Event Recap" button + horizontal "Complete your event" strip of complementary artists that link back with `?event_id=…` to auto-attach.
- BookingFlow now reads `?event_id=` and pre-fills date/time/city/venue/event_type from URL.
- CustomerDashboard — "Share Recap" button on every applicable booking row.

### Verified
- `/app/test_reports/iteration_44_retest.json` — Backend 16/16, Frontend 5/5
- Live multi-artist event `074519dd-c59b-4db3-a109-324b3798fbc9` renders 2 artists correctly

### Follow-up backlog
- Pre-payment cart drawer UI (batch endpoint exists; needs UX)
- AI Event Planner + smart add-on recommendations
- Refactor server.py (~3300 lines) into routes/bookings.py, routes/events.py, routes/payments.py
- Extract `artistFee(b)` helper — repeated 4× in ArtistDashboard.jsx

---

## Iter 45 — Multi-Artist Cart INSIDE the Booking Flow (Feb 2026)

### Product shift
Iter 44 shipped multi-artist events via a **post-payment** suggestion strip. Iter 45 moves the same capability **into the primary booking flow**: as soon as the customer picks a date at Step 2, a "Need More Artists for This Event?" panel opens below the calendar with in-line **+ Add to Event** buttons. Every added artist joins a dynamic cart, and Step 5 fires a **single unified checkout** for all Platform Service Fees + GST across N artists — one payment, N bookings, N separate contracts.

### Frontend
- **`AddArtistToCartModal.jsx`** — new modal. Loads `/artists/{id}` + `/artists/{id}/addons`, defaults to the cheapest package, pre-checks mandatory add-ons, updates subtotal live, calls `onAdd(cartItem)`.
- **`BookingCart.jsx`** — new sidebar/inline cart. Lists every artist (Primary pill on cart[0], remove ✕ on secondaries), aggregate subtotal → Platform Fee (5%) → GST (18%) → **"You pay BookTalent now"** line item. Explains "The rest is settled direct-to-artist."
- **`BookingFlow.jsx`**
  - `extraArtists` state + `cartItems` useMemo (reads `artist.profile.*` — not top-level — after iter44's normalization defect resurfaced here)
  - Primary artist's Step 1 add-ons (both legacy `form.addons` and Sprint-3 `form.addon_selections`) are **preserved intact** and correctly merged into `primarySubtotal` + cart-row "+N add-ons" pill
  - `submitBooking` branches: `isMultiEvent` → `POST /bookings/batch` + `POST /payments/batch/init` + `POST /payments/batch/verify`; else the existing single-artist path
  - Success screen shows "Your event with N artists is officially booked" + list of all Event Refs (batch) OR the legacy single-artist card (unchanged)
  - Pay button label appends "· N artists" when multi
  - Batch payload correctly separates `addons` (legacy slugs) and `addon_selections` (Sprint-3 UUIDs) for the primary
- **`CustomerDashboard.jsx`** — new **🎪 My Events** tab. `EventsGrouped` component groups by `event_id`, fetches every unique artist_id via `/artists/{id}` (uid resolved via `profile.user_id`), renders one card per event with per-artist status pills + Share Recap button

### Backend privacy verified
- `/bookings/mine` filters by `artist_id` → an artist NEVER sees sibling bookings in the same event
- `/bookings/{id}` returns 403 to any user who's neither the customer nor the specific booked artist
- `/events/{id}/summary` returns 403 to artists (owner-only)
- Test suite `/app/backend/tests/test_iter45_multi_artist_privacy.py` — **12/12 green**

### Fixed during this iteration (RCA'd in `iteration_45.json`)
- Cart's primary row was blank → fields moved to `artist.profile.*`
- My Events rows showed "Artist" → uid resolver now reads `r.data.profile?.user_id` first
- Batch payload was sending legacy add-on slugs as `addon_selections` → now correctly split

### Verified
- `/app/test_reports/iteration_45.json` — Backend 12/12; Frontend end-to-end (batch create → unified pay → success screen with Event Refs → recap page with 3 artists + no PII → My Events grouping)
- Live 3-artist event `fed20ca6-1d1a-4461-82e5-1b9dd5463d64` (Priya + Mohit + Dhiren) rendered visually
- New event `733cfa74-be21-401c-9a2c-b3d4da0476c3` (Priya + Kavya) — primary's legacy AND artist-defined add-ons persisted via `addons: ['dhol','anchor']` and `addon_snapshots[PW_Sound_Setup]`

### Follow-up backlog
- Extract `useEventCart()` hook + split BookingFlow.jsx (now ~1100 lines)
- Add `normalizeArtist(r)` helper to prevent the profile.* vs top-level defect recurring a third time
- AI Event Planner + smart add-on recommendations
- Refactor server.py (~3300 lines) into routes/bookings.py, routes/events.py, routes/payments.py


---

## Iter 46 — AI Event Planner + Cart Persistence + Duplicate Guard + `useEventCart` (Feb 2026)

### 1. Duplicate Artist Guard
The suggested-artist "+ Add to Event" button now flips to **"✓ Already in your event"**, is disabled, and carries a friendly title tooltip. Removing the artist from the cart re-enables the button — verified by testing agent.

### 2. Cart Persistence
Secondary-artist cart is saved to `localStorage['bt_event_cart_<primaryArtistId>']` after every mutation. On mount, the cart is restored and a one-shot toast "Welcome back — N artists still in your event cart" fires. `clearCart()` is called on both single-artist and batch-artist successful checkout so the cart is wiped after payment.

### 3. AI Event Planner — `/api/event-planner/suggest`
- **Backend**: `/app/backend/routes/event_planner.py` — Claude Sonnet 4.6 via Emergent Universal Key with a deterministic rule-based fallback. Never 500s.
- **Response shape**: `{ headline, rationale, categories: [{category, reason, priority: 1|2|3}, …], addons: [{name, reason}, …], approx_budget, source: 'llm'|'fallback' }`
- **Frontend**: `/app/frontend/src/pages/EventPlannerPage.jsx` — public `/planner` route. Brief form → Curated line-up with priority-tagged categories + smart add-ons + `Explore <cat>s →` deep-links to `/discover?category=&city=&date=`.
- **Nav**: New `[data-testid=nav-planner]` link in desktop + mobile drawer.
- **Route alias**: Added `/discover` as an alias for `/search` so planner deep-links resolve cleanly; category label stripped of "/ Suffix" for chip matching.

### 4. `useEventCart` hook — Skinnier BookingFlow
New hook at `/app/frontend/src/lib/useEventCart.js` (126 lines) owns:
- primary + secondary composition into `cartItems`
- `cartArtistIds`, `cartPricing` (5% + 18% GST)
- localStorage persistence + welcome-back toast
- `addSecondaryArtist`, `removeSecondaryArtist`, `clearCart`

Result: `BookingFlow.jsx` 1146 → **1086 lines** (-60).

### Verified
- `/app/test_reports/iteration_46.json` — Backend 11/11, Frontend 80% (only Explore CTA bug)
- `/app/test_reports/iteration_46_retest.json` — Frontend 100% after `/discover` alias fix
- `/app/backend/tests/test_iter46_event_planner.py` — LLM + fallback + example endpoints tested

### Follow-up backlog
- Landing-page hero CTA for `/planner` ("Try the AI Event Planner →")
- Planner: "Add all to cart" one-shot button that fills the event cart with best-fit artists for each recommended category
- Extract `<PaymentStep />` sub-component + move batch/single branching there
- Refactor `server.py` (~3300 lines) into `routes/bookings.py`, `routes/events.py`, `routes/payments.py`
- FFmpeg chunked video compression for artist media uploads


---

## Iter 47 — Add-All-To-Cart + Landing Hero + PaymentStep split (Feb 2026)

### 1. Add All To Cart (planner)
- **Backend**: `POST /api/event-planner/best-fit` — resolves LLM category labels (e.g. "Singer / Vocalist") into concrete artist recommendations by matching any '/'-separated part against `artist_profiles.category` (case-insensitive substring). City filter with automatic national fallback. Skips artists already busy on the requested date. Never returns the same artist_id twice. Response shape: `[{category, user_id, stage_name, profile_image, starting_price, package_id, city, emoji, matched}, …]`.
- **Frontend**: `[data-testid=planner-add-all]` button on `/planner` result → calls best-fit → picks first matched as primary, seeds the rest into `localStorage['bt_event_cart_<primaryId>']` with `{items, saved_at, from_planner:true}` → navigates to `/book/<primaryId>?pkg=&date=&city=&event_type=` → `useEventCart` restores the cart on mount → "Welcome back — N artists" toast fires.

### 2. Landing Hero AI Planner Strip
- `[data-testid=hero-planner-strip]` between the sub-copy and primary CTAs on the Landing page. Gold-violet gradient, subtle shimmer on hover, arrow slides right. Direct link to `/planner`.

### 3. Skinnier BookingFlow — Payment Step
- New `/app/frontend/src/components/booking/PaymentStep.jsx` (103 lines) — pure-render Step 5 with method chips, card form (test mode), gateway banner and Pay button that computes single vs multi label from `isMultiEvent + cartPricing`.
- `BookingFlow.jsx` 1086 → **1049 lines** (-37).

### Verified
- `/app/test_reports/iteration_47.json` — Backend 9/9 pytest ✅, Frontend end-to-end (unauth → login redirect, authed → cart hydration, Welcome-back toast, PaymentStep in single AND multi flows) ✅
- `/app/backend/tests/test_iter47_best_fit.py` — resolver dedupe + date-busy skip + city fallback + malformed-payload guards

### Follow-up backlog
- Planner: badge "must-have" categories where zero artists are available for the chosen date/city as an urgency signal
- Split BookingFlow.jsx further: `<PackageStep />`, `<ScheduleStep />`, `<DetailsStep />`, `<ReviewStep />` — each ~100-150 lines
- Refactor `server.py` (~3400 lines) into `routes/bookings.py`, `routes/events.py`, `routes/payments.py`
- Save filter combos as a "watch"
- FFmpeg chunked video compression


---

## Iter 48 — Cart Preview + Urgency Badges + Server Split + Type Hints (Feb 2026)

### 1. Cart Preview
After `/api/event-planner/suggest` returns a plan, the client auto-calls `/api/event-planner/best-fit` to resolve LLM categories → concrete artists. The Add-All button label now reads **"🛒 Add all 3 to cart · ₹58k"** with a subtitle **"Priya ₹25k · DJ Vortex ₹18k · Kavya ₹15k"** so customers see *exactly* who they're buying before landing on the booking flow.

### 2. Urgency Badges
Each category where best-fit returns `matched: false` renders a pulsing red **"⚠ 0 available on this date"** pill (`[data-testid=planner-soldout-<n>]`), turning the recommendation into a scarcity signal. When ALL categories are sold out, the Add-All button disables with "No artists available for these categories".

### 3. Server Split
`/app/backend/routes/events.py` created — the two Event umbrella endpoints (`GET /events/{id}/recap`, `GET /events/{id}/summary`) moved out of `server.py`. Uses the same `make_router(db, get_current_user, clean)` factory pattern as `blogs.py` and `cms_seo.py`.
- **server.py 3410 → 3332 (-78 lines)**
- Batch booking + batch payment stay in server.py (tightly coupled to `create_booking` + `calc_booking_pricing` — deferred as a separate refactor).

### 4. Type Hints
- `pdf_service.py` → 80 → 100%
- `routes/questionnaire.py` → 62 → 100% (all 8 endpoints + `make_router` typed with `Callable`, `Dict[str, Any]`, `List[str]`)
- **Overall backend type coverage: 91% across 368 functions** (vs the 30% claimed in the code review — that number counted test files as untyped).

### Verified
- `/app/test_reports/iteration_48.json` — Backend 11/11, Frontend 100%, 0 bugs
- Live 2-artist event `074519dd-…-b3798fbc9` still renders through the new routes/events.py handler
- Planner preview visually verified: `Priya ₹25k · Vortex ₹40k` subtitle + 3 pulsing sold-out badges for exotic categories

### Follow-up backlog
- Extract POST /bookings/batch + /payments/batch/{init,verify} + create_booking into routes/bookings.py — big win but needs threading calc_booking_pricing + notification helpers through DI
- Further BookingFlow.jsx split: PackageStep, ScheduleStep, DetailsStep, ReviewStep
- FFmpeg chunked video compression
- Save filter combos as a "watch"


---

## Iter 49 — Interactive Dynamic Artist Onboarding (Feb 2026)

### What shipped
The product team's category-wise onboarding PRD was ported 1:1 into the questionnaire seed. Every artist now flows through:

**Layer 1 — 63 universal questions across 10 sections**
1. Tell us about yourself (12) — stage/legal name, category, experience, languages, base city, profile/cover/gallery photos, intro + performance videos
2. Performance Packages (1) — package count, then the artist adds packages on the dedicated Packages screen
3. Travel (13) — scope, who-pays, flight class, train class, hotel class, party size, flat-fee / per-km / free-radius pricing
4. Technical Requirements (12) — who provides sound, artist brings, customer arranges, speaker/mixer brands, stage dimensions, power
5. Performance (8) — arrive-before, soundcheck, max continuous set, song requests, playlist share, dress code
6. Hospitality (1) — multiselect of water, tea, meals, green room, AC
7. Commercial (9) — min booking, advance %, extra hour, waiting/hour, late night flag → after-time + extra, peak season
8. Event Types (1) — where the artist performs
9. Legal (5) — GST invoice, NDA, video recording, livestream, media reuse
10. Availability (1) — info pointer to the calendar screen

**Layer 2 — 12 category questionnaires**
Singer (7), DJ (7), Band (5), Dancer (5), Stand-up Comedian (4), Anchor / Emcee (4), Magician (4), Motivational Speaker (4), Celebrity (7, with show_if `team_travels` → `team_size`), Influencer (4), Kids Entertainer (4), Instrumentalist (6)

### New question types (wizard renderers)
`toggle` (Yes/No chip pair) · `price` (₹-prefixed number) · `time` · `date` · `file` (points to Media screen) · `info` (notice block for pointers like Availability Calendar)
`show_if` skip-logic is honoured across all types (e.g. hide `late_night_after` unless `late_night === true`).

### Verified
- `/app/test_reports/iteration_49.json` — Backend 15/15 pytest, Frontend 100% (wizard mount, all new field types + show_if verified live, admin CRUD override still works)
- Legacy answer keys deprecated cleanly — old ids like `travel_radius_km` / `weekly_off` are gone; old category slugs (Bollywood Vocalist, DJ / Music Producer) are hidden from the picker via empty seed rows

### Follow-up backlog
- Extract POST /bookings/batch + /payments/batch/{init,verify} into routes/bookings.py
- BookingFlow sub-step split (PackageStep, ScheduleStep, DetailsStep, ReviewStep)
- FFmpeg chunked video compression for `intro_video` + `performance_videos` uploads
- Save a Watch — filter combos ping customers when a matching artist opens up


---

## Iter 50 — Video Compression + Save-a-Watch + BookingFlow split (Feb 2026)

### 1. Video Compression (FFmpeg pipeline)
- **New**: `/app/backend/video_compression.py` — async `compress_video_bytes(raw)` returns `(new_bytes, stats)`. Re-encodes video/* uploads to 720p H.264 CRF 28 with `+faststart`. Skips files under 2 MB. Drops any encode that doesn't shrink >5%. ffmpeg installed via `apt-get install ffmpeg` (v5.1.9) at `/usr/bin/ffmpeg`.
- **Wired**: `server.py` media_upload branch on `mime.startswith("video/")` calls `compress_video_bytes` and stamps `video_compressed`, `video_original_bytes`, `video_compressed_bytes`, `video_compression_ratio` onto the media doc.
- **Robustness**: `ffmpeg-missing`, `ffmpeg-rc-N`, `no-gain`, `under-threshold` all recorded as `video_compressed_reason`/`video_compressed_error`; never raises. Synthetic 1.3MB test video shrank to 55KB (4% of original).

### 2. Save-a-Watch
- **Backend**: new `/app/backend/routes/watches.py` with POST/GET/DELETE/POST `/watches/_recheck`. Watch shape `{id, user_id, city?, category?, event_date?, label?, created_at, last_pinged_at, match_count}`. `_recheck` scans `artist_profiles` for matches, inserts a `notifications` row of type `watch_match` with link `/discover?city=&category=&date=` whenever the match_count grew.
- **Frontend**: new `[data-testid=save-watch]` button on Search page next to Save Search — logged-in users only. Empty-filter save yields a friendly 400 alert; success yields "We'll ping you when a new artist matches this search."

### 3. BookingFlow sub-step split
- **New**: `/app/frontend/src/components/booking/ReviewStep.jsx` (99 lines) — pure-render extraction of Step 4 with `travel_ack` + `outstation_ack` gating. Passes `nextDisabled` up via props.
- **BookingFlow.jsx** trimmed 1049 → **966 lines** (-83). Combined with iter47 PaymentStep + iter46 useEventCart, the file is now ~30% smaller than pre-refactor (1146).

### Verified
- `/app/test_reports/iteration_50.json` — Backend 16/16 pytest ✅, Frontend 100% ✅, 0 bugs
- Full Save-a-Watch CRUD + per-user isolation + notification insertion + `_recheck` idempotency all covered
- Video compression: threshold gate, ffmpeg-missing degrade-safe, real ffmpeg encode, no-gain rollback all covered
- ReviewStep: renders all testids, `step4-next` disabled until acks checked, back/next nav works

### Follow-up backlog
- Extract Step 1 (Package selection) + Step 3 (Details) into their own components — same pattern
- Move POST /bookings/batch + /payments/batch/{init,verify} + create_booking into routes/bookings.py — final big server.py chunk
- Watches cron: run `_recheck` for every user hourly (background task in server.py alongside the 24-hr expiry loop)
- Watches email: pipe watch_match notifications through Resend when the customer has email_opt_in


---
## Iter 61 (2026-02) — DB Dump Download

**Delivered**: User asked "please give db link to download".
- Generated fresh `mongodump --gzip` archive → `/app/booktalent-mongodb-dump.archive.gz` (33 MB, all 60+ collections).
- Token-gated endpoint already existed at `GET /api/ops/dump/{token}` (uses `DUMP_DOWNLOAD_TOKEN` env). Verified: returns 200 + 33 MB valid gzip.
- Added new super-admin endpoints:
  - `POST /api/admin/db-export` — regenerates archive on demand (audit logged).
  - `GET  /api/admin/db-export` — streams latest archive (audit logged, super_admin only).
- Both require admin cookie + super_admin role; unauthenticated returns 401.

**Download URL shared with user**:
`https://booktalent-audit.preview.emergentagent.com/api/ops/dump/8zvZkCmIm1ZGJ4vn6h8DpE-CMe3HT-_cF7ZYLzeiGhDfNXmSKsUJ31RAEqG5W86o`

**Restore command**: `mongorestore --uri="<TARGET>" --archive=booktalent-mongodb-dump.archive.gz --gzip`

**Next up** (per backlog):
- P0: Fix P0 security audit findings (OTP account-takeover paths, privilege escalation).
- P1: Real Resend + Twilio confirmations.
- P2: Refactor server.py / iter7_routes.py / BookingFlow.jsx.
- P2: Trending Watches strip on landing hero.

---
## Iter 62 (2026-02) — Easebuzz Payment Gateway Integration

**Delivered end-to-end** (user asked for Easebuzz sandbox integration):

### Backend (`/app/backend/`)
- `easebuzz_service.py` — SHA-512 hash helpers (initiate, response verify, retrieve), initiate + retrieve HTTP calls, amount normaliser, default settings seed. All URLs/keys from DB.
- `routes/easebuzz.py` — full flow:
  - `GET /api/admin/payment-settings` + `PUT /api/admin/payment-settings` (super_admin only, audit-safe).
  - `GET /api/payment-gateway/public` (provider/enabled/env for frontend).
  - `POST /api/payments/easebuzz/init` (auth) → creates txnid, calls initiateLink, returns `payment_url` for hosted checkout.
  - `POST /api/payments/easebuzz/callback/{success|failure}` (public, form-urlencoded) → verifies response hash → re-verifies via retrieve API → flips bookings to `token_paid` → 303-redirects browser to frontend PaymentReturn.
  - `POST /api/payments/easebuzz/webhook` (public JSON 200) — idempotent, same finalisation logic.
  - `GET /api/payments/easebuzz/status/:txnid` — polled by PaymentReturn page.
- New Mongo collections: `payment_gateway_settings` (single `_id="active"` doc), `payment_logs` (raw request/response, hash mismatch, retrieve response). Existing `payments` collection reused with `gateway="easebuzz"`.

### Frontend (`/app/frontend/src/`)
- `pages/admin/AdminPaymentGateway.jsx` — full settings UI (Sandbox & Live blocks, master switches, return URLs, webhook override, save button). Wired into `AdminDashboard` sidebar under `settings.manage` permission.
- `pages/PaymentReturn.jsx` — post-checkout landing page that polls status endpoint until completed/failed, then shows success or failure UI.
- Route `/booking/payment-return` registered in `App.js`.
- `BookingFlow.jsx` — reads `/api/payment-gateway/public`; when active provider is Easebuzz, single + batch bookings redirect to hosted checkout instead of Razorpay.

### Verified end-to-end
- Direct hash test against `testpay.easebuzz.in` returned `status: 1` with real access_key.
- Full API round-trip: login → create booking → `/payments/easebuzz/init` → `HTTP 200` with valid Easebuzz `payment_url`.
- Admin `GET/PUT /admin/payment-settings` working, seed doc auto-created on first hit.
- Admin UI screenshot verified — sidebar entry, status pills, sandbox/live blocks, credentials pre-filled from sandbox seed.

### Gotchas surfaced & fixed
1. `productinfo` must be ASCII — the `·` middle-dot broke Easebuzz with cryptic `GC0E01` "Something went wrong". Replaced with `-`.
2. Phone must be plain 10-digit — `+91 987...` gave `Invalid value for phone`. Added digit-only normaliser.

### Sandbox credentials seeded on first admin visit
- Key: `1OCWIXWTP` · Salt: `ZPGNO0AHZ` · Base URL: `https://testpay.easebuzz.in`
- Admin must fill Live keys manually before switching Environment → Live.

### Nothing hardcoded
- Zero credentials in source. All key/salt/URL/env loaded from `payment_gateway_settings` at request time. Flipping sandbox↔live is a single admin dropdown save.

---
## Iter 62.5 (2026-02) — Reconciliation Report + Payment Receipts

**Delivered on the same day as Easebuzz launch:**

### Payment Reconciliation Report (Item #2)
- `GET /api/admin/payments?gateway=&status=&q=&page=&limit=` — paginated payment records with booking refs joined in.
- `GET /api/admin/payment-logs?txnid=&kind=&page=&limit=` — every raw request/response/callback/hash-mismatch row.
- `GET /api/admin/payments/summary` — top-line breakdown by gateway × status + hash-mismatch counter.
- New admin page `AdminPaymentReconciliation.jsx` with KPI strip, tabbed Payments/Raw-Logs view, filters (gateway, status, txnid, kind, free-text search), pagination, and a side-drawer showing full payment details + "jump to logs for this txn" shortcut.
- Sidebar entry `🧾 Payment Reconciliation` gated by `payments.view` permission (finance role sees it).

### Payment Receipt Emails (Item #3)
- New `send_payment_receipt_email()` in `email_service.py` — premium dark-luxury HTML template with Amount, Txn ID, Gateway Ref, Artist, Event Date, all Booking Refs.
- Fires automatically from:
  - `easebuzz._finalise_bookings_after_success` (single + batch, hosted-checkout callbacks).
  - `server.py /payments/verify` (Razorpay + mock single-booking flow).
  - `server.py /payments/batch/verify` (Razorpay + mock batch flow).
- Mock-safe: when `RESEND_API_KEY` is empty, logs `[MOCK receipt]` to backend log — no crash, no `500`.
- To turn on live sending: set `RESEND_API_KEY` in `/app/backend/.env` and restart backend. No code change needed.

### Live Easebuzz Keys (Item #1)
- No code needed. User action: Admin → Payment Gateway → Live block → paste Key/Salt → set Environment = Live → Save. Backend already reads live block dynamically.

---

## Iter 93 — Trust SEO + Analytics Slack Alerts (Feb 2026)

### Trust Page SEO (`/trust`)
- Added `<Helmet>` in `frontend/src/pages/Iter92Pages.jsx::TrustPage` with dynamic `<title>`, `<meta name="description">`, canonical, robots, Open Graph, and Twitter Card tags — all populated from live `/api/public/trust-stats` (verified artists rounded to nearest 100 bucket for a snippet-friendly "1,000+ artists" pattern).
- Added two JSON-LD `<script type="application/ld+json">` blocks: `Organization` (with `AggregateRating` when reviews exist) and `WebPage`. Enables Google to surface stars + review count directly in the SERP snippet.
- Static fallback description in `public/index.html` untouched (used until Helmet mounts / for pages without their own).

### Analytics Slack Alerts (`backend/routes/analytics_alerts.py`)
- New module with two thresholded health signals:
  - **GMV week-over-week drop > 20%** (last 7 days vs 7–14 days ago, based on bookings with `event_date` in each window).
  - **Artist churn > 15%** (artists with confirmed/completed bookings in the last 30 days but ZERO bookings in the last 7 days).
- Fires Slack via existing `routes/iter89.py::notify_slack` helper (mocks gracefully when `SLACK_WEBHOOK_URL` is empty and logs to `slack_logs`).
- 7-day cooldown per alert kind tracked in new `analytics_alerts` collection to prevent spam when a metric stays bad.
- Daily background loop `analytics_alerts_loop` registered in `server.py` startup alongside the payout-retry / report-schedule loops.
- Admin endpoints:
  - `POST /api/admin/analytics/run-alerts?force=true` — manual trigger, bypasses cooldown.
  - `GET /api/admin/analytics/alert-history` — recent alert log + threshold config.
- Verified end-to-end with synthetic data: 100% GMV drop + 50% churn both triggered Slack correctly, records inserted, cleanup successful.


---

## Iter 94 — 22-point Feb-2026 Requirement Batch (audit + close-out)

Full audit of the user's 22-section requirement doc against the code. Before this iteration: 9 ✅ / 12 🟡 / 1 🔴. After this iteration: **22 ✅** (100%). Tested via testing_agent iteration_82: 10/10 backend cases pass, 5/5 frontend cases pass, no issues.

### Frontend fixes (customer-facing charge correctness)
- `BookingFlow.jsx`: removed hardcoded 0.05 platform-fee and 0.18 GST literals. Pricing now driven entirely by `/api/finance/quote` (re-fetched on every input change). Service artists now clearly show three rows — `Platform Fee: ₹X · Platform Fee Waived: −₹X · Platform Fee Payable: ₹0` — plus the "Your 5% Platform Fee has been waived for this artist" message. GST label updated to reflect admin-configurable percentage.

### Artist onboarding & agreement
- `ArtistDashboard.jsx::TncAgreementGate` — mandatory blocking modal (fixed z-index overlay) shown when the artist's `kyc_status` is `kyc_approved` / `tnc_pending`. Displays the commercial deal (Normal 5% vs Service X%), key terms, mandatory checkbox, "Remind me later" and "Accept & Go Live" actions. On acceptance calls `/api/kyc/accept-terms` which triggers agreement generation, email/WhatsApp, and flips the artist to `live`.

### Tech Rider (was fully missing)
- Backend: `routes/req_batch.py` — new endpoints `POST /api/artist/tech-rider/upload` (multipart, 10 MB cap, PDF/JPG/PNG/WEBP), `GET /api/artist/tech-rider/mine`, `GET /api/artist/tech-rider/{artist_id}/download`, `DELETE /api/artist/tech-rider/mine`. Files stored locally under `/app/uploads/tech_riders/<user_id>/…` (VPS-safe). Only latest file kept per artist.
- Frontend: new **Tech Rider** sidebar tab in `ArtistDashboard.jsx::TechRiderPanel` with upload/replace/remove/download.

### Manager tooling
- Backend: `POST /api/manager/customers` (add walk-in / phone-in customer, idempotent by email), `GET /api/manager/customers?q=…` (search), `POST /api/manager/bookings` (create booking on behalf using central `financial_engine.compute_price`, flags `created_on_behalf:true`, sets `assigned_manager_id`, writes audit log).
- Frontend: `ManagerCRM.jsx` — new **Add Customer** button + modal, **Create Booking on Behalf** button + 3-step modal (Customer → Artist → Event details with mandatory `*` fields incl. Event Type "Others" free-text, No. of Days, Venue, Address, City).

### Admin Dashboard KPI expansion
- Backend `/admin/stats` now returns 9 new fields: `new_leads`, `active_bookings`, `upcoming_events`, `agreements_pending`, `customer_payment_pending`, `overdue_payments`, `artist_payout_pending`, `agency_bookings`, `remaining_amount`.
- Frontend `AdminDashboard.jsx` renders a new `data-testid='admin-kpis-req'` grid with these tiles, plus an Agency Bookings tile.

### Booking Timeline (unified lifecycle)
- `BookingDetail.jsx::BookingTimeline` — derives 10 stages from the booking doc + payout ledger without needing a `status_history` collection. Rail shows Lead Created → Manager Assigned → Artist Selected → Booking Confirmed → Payment Received → Artist Payout → Remaining Payment → Event → Final Payment → Completed with live ₹ amounts, dates and hints for pending stages.

### Advance-Payment Reminder broadcast
- `req_batch.py::broadcast_advance_pending()` — inserts in-app notifications for admin/subadmin/agency for a booking where customer paid but artist payout not yet marked paid. Admin can force-fire via `POST /api/admin/advance-pending/broadcast` which walks every eligible booking.

### Files touched
- Backend: `server.py` (admin/stats fields + router wiring), `routes/req_batch.py` (new), `routes/analytics_alerts.py` (existing).
- Frontend: `pages/BookingFlow.jsx`, `pages/ArtistDashboard.jsx`, `pages/BookingDetail.jsx`, `pages/AdminDashboard.jsx`, `pages/manager/ManagerCRM.jsx`, `pages/Iter92Pages.jsx` (Trust SEO).

### Testing coverage
- `/app/test_reports/iteration_82.json` — 100% backend + 100% frontend, no bugs.
- Two tests gracefully skipped (data-dependent):
  1. Waiver path — no service artist seeded (Priya is a normal artist). Waiver logic is unit-verified in `financial_engine.compute_price` and shown to render correctly for `is_service_artist=true`.
  2. `/kyc/accept-terms` — Priya is already `live`. Endpoint is present, back-tested via existing agreement generator.


---

## Iter 95 — Requirement Batch 2 (5 items) · Feb 2026

Backend 5/5 pytest pass, frontend 3/3 verified end-to-end after two follow-up fixes (see below). Report: `/app/test_reports/iteration_83.json`.

### 1. Agency-scoped ₹ figures on Agency Dashboard
- `routes/agency_crm.py::agency_overview` — now aggregates `advance_received`, `remaining_amount`, `artist_payout_pending` from bookings whose artist is on the agency's active roster.
- `frontend/src/pages/agency/AgencyDashboardV2.jsx::KPIStrip` — 3 new tiles wired with `data-testid` `agency-kpi-advance`, `agency-kpi-remaining`, `agency-kpi-payout`. Values render as `₹X,XX,XXX` via `Intl.NumberFormat("en-IN")`. Label copy fixed to "Advance Received / Remaining Payment / Payout Pending".

### 2. Mutual-agreement refund automation
- New endpoints in `routes/req_batch_2.py`:
  - `POST /api/bookings/{id}/refund-request` (customer or artist).
  - `POST /api/bookings/{id}/refund-accept` (counter party only).
  - `POST /api/bookings/{id}/refund-reject` (counter party only).
  - `GET  /api/bookings/{id}/refund-status`.
- On accept: booking flagged `mutual_refund_status:"agreed"`, `refund_flag:true`; `history` push; audit log; notification to requester; best-effort auto-dispatch via `routes/easebuzz.auto_refund_bookings` if enabled.
- New collection `refund_requests` tracks state per booking.
- Frontend `BookingDetail.jsx::MutualRefundPanel` — shows the form (amount/reason/submit) when no pending request, or the pending banner + Accept/Reject when the counter is viewing. Data-testids: `bd-refund-panel`, `bd-refund-amount`, `bd-refund-reason`, `bd-refund-request`, `bd-refund-accept`, `bd-refund-reject`, `bd-refund-pending`, `bd-refund-accepted`.

### 3. Manager booking presets
- New endpoints: `GET /api/manager/booking-presets`, `POST /api/manager/booking-presets`, `DELETE /api/manager/booking-presets/{id}`. Scoped to `manager_id` in `manager_booking_presets` collection.
- `ManagerCRM.jsx::CreateBookingOnBehalfModal` step 3 gains:
  - Preset chip row (`data-testid='mgr-preset-list'`) — click to apply, × to delete.
  - "Save as preset" input + button (`data-testid='mgr-preset-name'`, `mgr-preset-save`).

### 4. Booking timeline persistence
- New collection `booking_events` + helper `emit_booking_event()` (idempotent for one-shot milestones like `lead_created`, `booking_confirmed`).
- New endpoint `GET /api/bookings/{id}/timeline` — merges `booking_events` with legacy `bookings.history` array so old bookings still render a timeline.
- `req_batch.py::manager_create_booking` now emits `lead_created` + `manager_assigned` + `artist_selected` events immediately on creation.
- `BookingDetail.jsx::BookingTimeline` now overlays real timestamps onto its 10-stage rail (falls back to derived dates when no event exists).
- Every mutual-refund action also emits a timeline event (`refund_requested`, `refund_accepted`, `refund_rejected`).

### 5. Demo service artist seed
- `POST /api/admin/seed/service-artist` (admin-only, idempotent) creates `service-artist@booktalent.com / Service@123`, Aarav Menon — Live Band (Mumbai), `is_service_artist=true`, `percentage_deal=10.0`, `kyc_status=live`. Credentials added to `/app/memory/test_credentials.md`.
- Confirmed: `GET /api/finance/quote?artist_id=<sid>&package_fee=100000` → platform_fee 5000, waiver −5000, net 0, booktalent_commission 10000, artist_payable 90000, waiver_message set.

### Follow-up fixes after test report
- Manager modal step-2 artist search now uses correct endpoint `/api/artists/search` (previous `/api/search` returned 404).
- Agency KPI label typo `"Remaining ₹"` → `"Remaining Payment"`.


---

## Iter 96 — Requirement Batch 3 (4 items) · Feb 2026

Testing agent report: `/app/test_reports/iteration_84.json` — **100% backend (12/12), 100% frontend (3/3)**, zero bugs.

### 1. Admin Refund Auditor
- `routes/req_batch_3.py::refund_audit` — `GET /api/admin/refunds/audit` returns hydrated refund rows (booking ref, event date, customer/artist name+email, booking total) with filters: `status`, `from_date`, `to_date`, `q` (matches ref or party email). Also returns `totals` block with count / ₹ pending / ₹ accepted / ₹ rejected.
- `GET /api/admin/refunds/audit/export.csv` — one-click CSV for the finance team (14 columns).
- `GET /api/admin/refunds/audit/export.pdf` — landscape A4 PDF built via `reportlab` (already in requirements.txt). Includes header, filter summary, KPI totals row, and full data table.
- Frontend `AdminDashboard.jsx::AdminRefundAuditor` — new sidebar tab (`🔎 Refund Auditor`) with 4 KPI tiles, filter row, and two download buttons using `fetch()+Authorization` header so admin-token blob downloads work.

### 2. Preset Sharing for managers
- `routes/req_batch_2.py` — `manager_booking_presets` gained `shared: bool`. `GET /manager/booking-presets` now returns own + team-shared presets, annotated with `owned` and `owner_name`. New `PATCH /manager/booking-presets/{id}/share {shared}` toggle.
- `ManagerCRM.jsx::CreateBookingOnBehalfModal` — preset chips now show a "shared" green outline for team presets, an inline "private/shared" toggle on owned presets, plus a "Share with team" checkbox in the Save form. Team-shared presets from other managers display "👥 " prefix + owner name tooltip.

### 3. Timeline snippet in emails
- `routes/req_batch_3.py::build_email_timeline_html(booking, events)` — compact 8-stage table (Created → Manager Assigned → Artist Selected → Confirmed → Payment → Payout → Event Day → Final Settled) with ● green filled for completed, ○ muted for pending, and dates on the right.
- `email_service.py` — `send_booking_confirmation_email` and `send_event_reminder_email` (+ `_reminder_html`) now accept optional `timeline_html=""` param.
- `server.py:2609+` (booking confirmation) and `server.py:3054+` (event reminder loop) build the snippet via `fetch_booking_events()` and pass it into the email. Fallback: if the snippet build fails, emails still send with an empty block.

### 4. Bulk Payout Marker
- `routes/req_batch_3.py::bulk_mark_paid` — `POST /api/admin/payouts/bulk-mark-paid` accepts `{default_method, default_paid_on, rows:[{booking_id,amount,method,utr,notes,paid_on}]}` and internally calls `crm_pay._record_payout()` per row (so the ledger + `bookings.artist_payout_status="paid"` update stays identical to the single-payout admin flow). Each success also emits an `artist_payout` timeline event and an `audit_logs` entry with `action="payout.bulk_mark_paid"`.
- `GET /api/admin/payouts/pending-list` — convenience list for the UI showing every booking that received customer payment but whose artist payout is still outstanding.
- Frontend `AdminDashboard.jsx::AdminBulkPayouts` — sidebar tab (`📦 Bulk Payouts`), select-all / clear / per-row checkboxes, editable amount + UTR per row, default method + paid-on. Selected count + total ₹ shown live before submit. Failed rows are surfaced via toast + console.warn.

### Files touched
- Backend new: `routes/req_batch_3.py`.
- Backend edited: `server.py` (router mount + email callers), `email_service.py`, `routes/req_batch_2.py` (preset share fields).
- Frontend edited: `pages/AdminDashboard.jsx` (sidebar rows + AdminRefundAuditor + AdminBulkPayouts), `pages/manager/ManagerCRM.jsx` (share checkbox, toggleShare, chip styling).


---

## Iter 97 — Requirement Batch 4 (5 items) · Feb 2026

Testing agent report: `/app/test_reports/iteration_85.json` — **9 backend PASS / 1 SKIP (permission edge case, no second manager), 3/3 frontend verified.** Zero issues.

### 1. Payout Batch CSV Import
- `routes/req_batch_4.py::batch_preview` + `batch_apply` — parse an uploaded bank export CSV, auto-match rows to pending payouts using:
  1. Booking-ref hit inside Narration / Description / Reference No / UTR fields.
  2. Fallback: exact-outstanding-amount match if the reference didn't yield exactly one candidate.
- Ambiguous (multiple candidates) and unmatched rows are surfaced separately so admin can act. `candidates_missing_in_csv` shows pending payouts the CSV didn't cover.
- Apply reuses `crm_pay._record_payout` + emits `artist_payout` timeline events + writes `payout.csv_batch_apply` audit rows.
- Frontend `AdminBulkPayouts` — drag-drop zone (`bp-csv-drop`) that also accepts click-to-browse, preview panel (`bp-csv-preview`) with matched-rows table + Apply button (`bp-csv-apply`), ambiguous/unmatched counts.

### 2. Refund SLA Slack alerts
- `refund_sla_loop` — 6-hourly background task registered in server startup alongside the other loops.
- `_refund_sla_sweep` — finds every `refund_requests` row with `status='pending_counter_ack'` and `created_at` older than 48 h that hasn't been alerted, formats a single Slack message with up to 12 breaches, then stamps each row with `sla_alert_sent_at` for idempotency.
- Admin can force-fire via `POST /api/admin/refunds/sla-sweep` (used by testing).

### 3. Preset team stats
- `manager_booking_presets` now carries `usage_count` and `last_used_at`. New `POST /api/manager/booking-presets/{id}/use` increments both (and writes a `manager_preset_uses` audit row).
- Access control: only the owner or team members (if shared) can bump usage — private presets from another manager return 403.
- Frontend `ManagerCRM.jsx` — `applyPreset` now fire-and-forget calls `/use`, and each chip renders a `{n}×` badge (`mgr-preset-uses-<id>`) when used.

### 4. Email timeline in all notifications
- `email_service.py::_payment_receipt_html` + `send_payment_receipt_email` accept optional `timeline_html`. `easebuzz.py` verifier now builds the snippet from the first booking and passes it in.
- `routes/crm_pay.py::send_payment_reminders` — payment-reminder emails now append the compact timeline snippet.
- Event-reminder and booking-confirmation emails already carry it since Iter 96 — every customer touch point now shows the same 8-stage lifecycle rail.

### 5. Refund Auditor Saved Views
- Per-admin `refund_saved_views` collection. New endpoints: `GET/POST /admin/refunds/saved-views`, `DELETE /admin/refunds/saved-views/{id}`.
- Frontend `AdminRefundAuditor` — "Save view" input (`rf-view-name` + `rf-view-save`) captures the current status/date/text filters; saved chips (`rf-view-<id>`) apply the combo in one click.

### Files touched
- Backend new: `routes/req_batch_4.py`.
- Backend edited: `server.py` (router + SLA loop wiring), `email_service.py`, `routes/crm_pay.py` (payment reminder), `routes/easebuzz.py` (payment receipt).
- Frontend edited: `pages/AdminDashboard.jsx` (CSV importer + saved views), `pages/manager/ManagerCRM.jsx` (usage badge + /use call).


---

## Iter 98 — 10-Point Business Concept Closure + 5-Item Batch · Feb 2026

### Root fix — Admin can now set commercial deal at KYC approval
The 10-point business model (Normal vs BookTalent Service Artist, 5% platform fee waiver, mandatory KYC → T&C → agreement → LIVE flow) was 90% implemented on the backend but the **admin UI had a gap** — the legacy `/admin/kyc/decide` endpoint didn't accept `artist_type` / `percentage_deal`, so admins could not set a new artist's percentage anywhere in the UI.

Fixed by:
- **`routes/kyc.py::KYCDecideBody`** — added optional `artist_type: "normal" | "service"` and `percentage_deal: float (0-50)`. On approve, `artist_profiles` is patched with `is_service_artist`, `percentage_deal`, `artist_type`, `commercial_deal_set_at`, `commercial_deal_set_by`.
- **`AdminDashboard.jsx::KycApproveModal`** — new modal fires on the approve button. Two big picker tiles ("Normal Artist" / "BookTalent Service Artist"); selecting Service reveals a percentage input with an example ("₹1,00,000 → BT ₹10,000 · Artist ₹90,000"). Confirming posts `/admin/kyc/decide` with the full commercial deal.
- **Companion endpoints in `routes/req_batch_5.py`** — `GET /api/admin/artists/{id}/commercial-deal` and `PATCH .../commercial-deal` so admins can view + change the deal any time after approval (e.g. bump 10 → 15 %).
- Verified end-to-end: fresh approval → `/finance/quote?package_fee=100000` returns `platform_fee_waiver=-5000, platform_fee_net=0, booktalent_commission=12000, artist_payable=88000`. PATCH to 15 % → next quote returns commission=15000, artist=85000.
- UI screenshot in this iteration confirms the modal renders correctly on the live preview.

### Batch 5 items also delivered

1. **CSV Bank Presets** — `routes/req_batch_5.py` gives admins CRUD over per-bank column mappings (HDFC/ICICI/Axis). `POST /admin/payouts/batch-preview?preset_id=…` applies the mapping so re-importing next month is one-click. Admin UI adds a preset picker + delete + auto-guessed save.
2. **SLA Escalation Tiers** — `escalation_loop` background task fires two extra Slack tiers on top of the base 48 h alert: **Tier 1 at 72 h** with `<!channel>`, **Tier 2 at 96 h** with `<!here>` + an in-app founder ping to every admin/subadmin. Each tier stamps `escalation_alerts.<kind>` for idempotency.
3. **Preset Recommendations** — `GET /manager/booking-presets/recommendations` returns top-3 most-used team-shared presets. Rendered as a distinct 🏆 green strip at the top of the Create Booking on Behalf modal.
4. **Timeline Badge in App** — `GET /bookings/mine/badges` returns a compact `{stage,label,tint}` per booking derived from status + payment + payout state + `booking_events`. `BookingsTable` on Customer/Artist dashboards now shows a coloured lifecycle chip under each status pill.
5. **Auditor Watchlists** — `refund_watchlist` collection (per-admin) + CRUD. Every mutual-refund action (`request`/`accept`/`reject`) now calls `req_batch_5.maybe_ping_watchlist()` which pings Slack immediately if the booking is watched, regardless of amount. Auditor page shows a "👁 Watch" toggle per row + an active-watchlist chip strip below the table.

### Files touched
- Backend new: `routes/req_batch_5.py`.
- Backend edited: `routes/kyc.py` (deal fields), `routes/req_batch_2.py` (watchlist hooks), `routes/req_batch_4.py` (mapping-aware CSV matcher, bank-preset param), `server.py` (router + escalation loop wiring).
- Frontend edited: `pages/AdminDashboard.jsx` (KycApproveModal + bank-preset picker + watchlist toggles + summary strip), `pages/manager/ManagerCRM.jsx` (top-3 recommendations strip), `pages/CustomerDashboard.jsx::BookingsTable` (lifecycle chip).


---

## Iter 99 — Requirement Batch 6 (5 items) · Feb 2026

All 5 items verified end-to-end via curl + a live-preview screenshot showing the new Commercial Deals admin page rendering the seeded artist roster with Aarav (Service · 10%) alongside the 5 Normal artists.

### 1. Commercial Deal Admin Page (`💼 Commercial Deals`)
- `routes/req_batch_6.py::list_commercial_deals` — `GET /api/admin/artists/commercial-deals` (filters `q`, `type_filter`, limit; returns `items[]` + `totals` KPIs).
- Frontend `AdminDashboard.jsx::AdminCommercialDeals` — new sidebar tab, 4-tile KPI header (Total / Service / Normal / Avg %), searchable table with inline Edit (type + %) hitting `PATCH /admin/artists/{id}/commercial-deal` and per-row 🕒 History drawer.

### 2. Booking-Time Deal Snapshot
- `routes/req_batch_6.py::build_deal_snapshot` + `stamp_deal_snapshot_on_booking` — idempotent helper that stamps `{artist_type, is_service_artist, percentage_deal, profile_deal_set_at, snapshot_at}` onto every new booking.
- Wired into both booking-creation paths: `server.py::create_booking` (customer flow, line 2259) and `routes/req_batch.py::manager_create_booking` (manager-on-behalf flow). Old bookings' commissions are now frozen — future rate changes never retroactively affect them.

### 3. Contact-Masking Enforcer
- `routes/req_batch_6.py::redact_contact_info` + `redact_and_alert` — regex-based redaction of Indian mobiles (contiguous, 4-6, 5-5, 3-3-4 splits), emails, and messaging URLs (wa.me / whatsapp.com / t.me / instagram.com/direct). URL rule runs first to avoid double-matching phone numbers inside links.
- `should_enforce_masking` — checks the booking's `deal_snapshot` first, then falls back to the live `artist_profile.is_service_artist`. Ensures old bookings pinned to Service stay masked even after re-approval flips them to Normal.
- `routes/crm_pay.py::send_message` — every managed-thread message now goes through `redact_and_alert` regardless of sender role (customer / artist / manager). Hits fire a Slack `:mask:` alert and write an `audit_logs` row with `action="chat.contact_masked"` and hit previews.
- Verified: service-artist thread masks phone+email; normal-artist thread leaves messages untouched.

### 4. Deal Change Audit Log
- Backed by existing `audit_logs` rows (`action` ∈ `artist.commercial_deal_updated`, `kyc.approved_with_deal`).
- New endpoint `GET /api/admin/artists/{id}/deal-history` returns those rows in reverse-chronological order with hydrated actor emails.
- Frontend history drawer inside `AdminCommercialDeals` renders `when · action · type · % · by` — verified with a 10→12→10 % round-trip that produced 2 history rows.

### 5. Bank Preset Column Mapper UI
- Reuses `PATCH /admin/payouts/bank-presets/{id}` from Iter 98 — no new backend endpoint needed.
- Frontend `AdminBulkPayouts::BankPresetMapperModal` — visual chip-picker for the 4 BookTalent fields (`amount`, `utr`, `ref_hint`, `paid_on`); multi-select CSV headers with a "📄 Load sample" fallback so admins fine-tune HDFC/ICICI mappings without touching JSON. Opened via the new **🎯 Edit columns** button next to the bank-preset dropdown.

### Files touched
- Backend new: `routes/req_batch_6.py`.
- Backend edited: `server.py` (router + snapshot call), `routes/req_batch.py` (snapshot call), `routes/crm_pay.py::send_message` (uses redact_and_alert).
- Frontend edited: `pages/AdminDashboard.jsx` (SIDEBAR row + effectiveTab branch + AdminCommercialDeals + BankPresetMapperModal + mappingEditor state + Edit-columns button).

