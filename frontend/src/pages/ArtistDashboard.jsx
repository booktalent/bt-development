import React, { useEffect, useState, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import Nav from "../components/Nav";
import api, { fmtINRFull, formatApiError, mediaUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { BookingsTable } from "./CustomerDashboard";
import OnboardingWizard from "../components/OnboardingWizard";
import AvailabilityCalendar from "../components/AvailabilityCalendar";
import QuestionnaireWizard from "../components/QuestionnaireWizard";

/**
 * Media thumbnail with a graceful React-state fallback when the thumb URL 404s
 * or the image decode fails. Replaces the earlier `insertAdjacentHTML` hack
 * flagged by the code review — no DOM mutation, no XSS surface.
 */
function MediaThumb({ id, title }) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%", fontSize: 48 }}>📎</div>
    );
  }
  return (
    <img
      src={`${api.defaults.baseURL}/media/${id}/thumb`}
      alt={title}
      onError={() => setBroken(true)}
    />
  );
}

const SIDEBAR = [
  { id: "overview", label: "📊 Overview" },
  { id: "profile", label: "👤 Profile" },
  { id: "questionnaire", label: "📝 Questionnaire" },
  { id: "packages", label: "📦 Packages" },
  { id: "addons", label: "🎁 Add-ons" },
  { id: "media", label: "🎬 Media" },
  { id: "calendar", label: "📅 Availability" },
  { id: "bookings", label: "🎟️ Bookings" },
  { id: "insights", label: "📈 Insights" },
  { id: "reviews", label: "⭐ Reviews" },
  { id: "boost", label: "🚀 Boost Profile" },
  { id: "subscription", label: "💎 Subscription" },
  { id: "concierge", label: "🎩 Concierge", elite: true },
  { id: "kyc", label: "🪪 KYC" },
  { id: "tech_rider", label: "🎛️ Tech Rider" },
];

export default function ArtistDashboard() {
  const { user, refreshMe } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [tab, setTab] = useState(() => {
    // Iter 63.5 — read ?tab= from URL so notification click-through lands on the right tab.
    const p = new URLSearchParams(window.location.search).get("tab");
    return p || "overview";
  });
  const [subHighlight, setSubHighlight] = useState(null); // Iter 63.1 — from concierge upgrade CTA
  const [data, setData] = useState({ bookings: [], packages: [], media: [], analytics: {}, reviews: [] });
  const [showWizard, setShowWizard] = useState(false);
  const [completion, setCompletion] = useState(null); // Iter 56 — onboarding nudge
  const [wizardStartSection, setWizardStartSection] = useState(null);
  // Iter 70 — Questionnaire sections listed in the sidebar as a dropdown.
  // We fetch layer-1 questions once and group them so the artist can jump
  // directly into any section (e.g. "Basics", "Style", "Performance"…).
  const [qSections, setQSections] = useState([]);
  const [qSidebarOpen, setQSidebarOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.get("/questionnaire/universal")
      .then((r) => {
        if (cancelled) return;
        const secs = [];
        const seen = new Set();
        for (const q of r.data || []) {
          const s = q.section || "Other";
          if (!seen.has(s)) { seen.add(s); secs.push(s); }
        }
        setQSections(secs);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []); // Iter 57 — deep-link
  const [agencyInvites, setAgencyInvites] = useState([]); // Iter 63 — roster invites
  const [managingAgency, setManagingAgency] = useState(null); // Iter 63 — current agency

  // Iter 63 — Roster invites (agency wants to manage this artist)
  useEffect(() => {
    if (!user || user.role !== "artist") return;
    api.get("/agency/invites").then((r) => setAgencyInvites(r.data || [])).catch(() => {});
    api.get("/roster/my-agency").then((r) => setManagingAgency(r.data?.active ? r.data : null)).catch(() => {});
  }, [user]);

  const handleInvite = async (inviteId, action) => {
    try {
      await api.post(`/agency/invite/${inviteId}/respond`, { accept: action === "accept" });
      toast(action === "accept" ? "Invite accepted — the agency now manages your bookings." : "Invite declined", "success");
      const [inv, agy] = await Promise.all([
        api.get("/agency/invites").catch(() => ({ data: [] })),
        api.get("/roster/my-agency").catch(() => ({ data: {} })),
      ]);
      setAgencyInvites(inv.data || []);
      setManagingAgency(agy.data?.active ? agy.data : null);
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  // Iter 56 — Pull questionnaire completion so we can show a nudge banner
  // when the artist is missing more than 3 sections of their rider.
  useEffect(() => {
    if (!user || user.role !== "artist") return;
    api.get("/questionnaire/completion/mine")
      .then((r) => setCompletion(r.data))
      .catch(() => setCompletion(null));
  }, [user, showWizard]);

  // Auto-show wizard if onboarding required (test-unblocking scaffold)
  // Iter 91 — Respect seen_welcome_at so already-onboarded artists don't
  // get the modal on every login.
  useEffect(() => {
    if (!user || user.role !== "artist") return;
    if (user.seen_welcome_at) return;   // dismissed persistently earlier
    api.get("/onboarding/me").then((r) => {
      if (r.data?.required && !r.data?.completed) setShowWizard(true);
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!user) { nav("/login"); return; }
    if (user.role !== "artist") { nav(user.role === "admin" ? "/admin" : "/customer"); return; }
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const refresh = async () => {
    const [b, p, m, a, r] = await Promise.all([
      api.get("/bookings/mine"),
      api.get("/packages/mine"),
      api.get("/media"),
      api.get("/analytics/me"),
      api.get(`/reviews/artist/${user.id}`),
    ]);
    setData({ bookings: b.data, packages: p.data, media: m.data, analytics: a.data, reviews: r.data });
  };

  const doAction = async (bid, action, extra = {}) => {
    try {
      await api.post(`/bookings/${bid}/action`, { action, ...extra });
      toast("Booking updated");
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  if (!user) return null;

  return (
    <div className="dash-wrap" data-testid="artist-dashboard">
      <aside className="sidebar">
        <Link to="/" className="logo mb-20" data-testid="dash-logo">
          <div className="logo-mark">B</div>
          <span style={{ fontSize: 18 }}>Book<span className="gold">Talent</span></span>
        </Link>
        <div className="sb-section">Artist Hub</div>
        {SIDEBAR.map((x) => {
          // Iter 70 — Special-case Questionnaire so we can render its
          // sections as an expandable submenu. Clicking a section jumps
          // straight to that question set inside the wizard.
          if (x.id === "questionnaire") {
            const isActive = tab === "questionnaire";
            return (
              <div key={x.id}>
                <div
                  className={`sb-item ${isActive ? "active" : ""}`}
                  onClick={() => { setTab("questionnaire"); setQSidebarOpen((o) => !o); }}
                  data-testid={`sb-${x.id}`}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
                >
                  <span>{x.label}</span>
                  {qSections.length > 0 && (
                    <span style={{ fontSize: 10, color: "rgba(240,238,255,0.5)" }}>
                      {qSidebarOpen ? "▼" : "▶"}
                    </span>
                  )}
                </div>
                {qSidebarOpen && qSections.length > 0 && (
                  <div data-testid="sb-questionnaire-sections" style={{ padding: "4px 0 6px 14px", borderLeft: "1px solid rgba(212,175,55,0.15)", marginLeft: 12 }}>
                    {qSections.map((s) => (
                      <div
                        key={s}
                        className={`sb-sub-item ${isActive && wizardStartSection === s ? "active" : ""}`}
                        onClick={() => { setWizardStartSection(s); setTab("questionnaire"); }}
                        data-testid={`sb-q-${s.toLowerCase().replace(/\s+/g, "-")}`}
                        style={{
                          padding: "6px 10px", fontSize: 12,
                          color: (isActive && wizardStartSection === s) ? "#F1D17A" : "rgba(240,238,255,0.65)",
                          cursor: "pointer", borderRadius: 6, margin: "2px 0",
                          background: (isActive && wizardStartSection === s) ? "rgba(212,175,55,0.10)" : "transparent",
                        }}
                      >
                        • {s}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          }
          return (
            <div key={x.id} className={`sb-item ${tab === x.id ? "active" : ""}`} onClick={() => setTab(x.id)} data-testid={`sb-${x.id}`}>
              {x.label}
              {x.elite && <span style={{ marginLeft: 6, fontSize: 9, background: "linear-gradient(135deg,#f472b6,#d4af37)", color: "#0b0616", padding: "2px 6px", borderRadius: 6, fontWeight: 700 }}>ELITE</span>}
            </div>
          );
        })}
      </aside>

      <main className="dash-content">
        <Nav />
        <div style={{ marginTop: 18 }}>
          <div className="dash-head">
            <div>
              <h1>Welcome, {user.first_name} ✨</h1>
              <p>{data.bookings.filter(b => b.status === "pending_artist").length} new requests · {data.analytics.profile_views || 0} profile views</p>
            </div>
          </div>

          {/* Iter 63 — Agency invite banner (accept / decline). Sits at the
              top so artists notice immediately on next login. */}
          {agencyInvites.length > 0 && agencyInvites.map((inv) => (
            <div
              key={inv.id}
              data-testid={`agency-invite-${inv.id}`}
              style={{
                background: "linear-gradient(135deg, rgba(212,175,55,0.14), rgba(124,58,237,0.14))",
                border: "1px solid rgba(212,175,55,0.35)",
                borderRadius: 14, padding: "16px 20px", marginBottom: 16,
                display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap",
              }}
            >
              <div style={{ fontSize: 30 }}>🎭</div>
              <div style={{ flex: 1, minWidth: 240 }}>
                <div style={{ fontWeight: 700, fontSize: 15 }}>
                  Agency Roster Invite — {inv.agency?.first_name || "An agency"}
                </div>
                <div className="text-muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Wants to manage your bookings, calendar and payouts.
                  Commission: <strong>{inv.commission_pct}%</strong>.
                  {inv.note && <span> "{inv.note}"</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="btn btn-gold"
                  onClick={() => handleInvite(inv.id, "accept")}
                  data-testid={`accept-invite-${inv.id}`}
                >Accept</button>
                <button
                  className="btn btn-ghost"
                  onClick={() => handleInvite(inv.id, "decline")}
                  data-testid={`decline-invite-${inv.id}`}
                >Decline</button>
              </div>
            </div>
          ))}

          {/* Iter 63 — Current agency badge (shown when managed). */}
          {managingAgency && (
            <div
              data-testid="current-agency-badge"
              style={{
                background: "rgba(124,58,237,0.10)",
                border: "1px solid rgba(124,58,237,0.30)",
                borderRadius: 14, padding: "12px 18px", marginBottom: 16,
                display: "flex", gap: 12, alignItems: "center", fontSize: 13,
              }}
            >
              <span style={{ fontSize: 20 }}>🤝</span>
              <span>
                Managed by <strong>{managingAgency.agency?.first_name || "your agency"}</strong>
                {" · "}Commission {managingAgency.commission_pct}%
              </span>
              <span className="text-muted" style={{ marginLeft: "auto", fontSize: 12 }}>
                Only your agency can release this link.
              </span>
            </div>
          )}

          {(() => {
            const liveEarnings = (data.bookings || [])
              .filter((b) => ["confirmed", "started", "completed", "reviewed"].includes(b.status))
              .reduce((s, b) => s + Number(b.pricing?.artist_fee || (b.pricing?.package_fee || 0) + (b.pricing?.addons_total || 0) || 0), 0);
            return (
              <div className="kpi-grid">
                <Kpi icon="💰" cls="kpi-icon-gold" num={fmtINRFull(liveEarnings)} label="Total Earnings" />
                <Kpi icon="📋" cls="kpi-icon-purple" num={data.analytics.total_bookings || 0} label="Total Bookings" />
                <Kpi icon="⏳" cls="kpi-icon-amber" num={data.analytics.pending_requests || 0} label="Pending Requests" />
                <Kpi icon="👁️" cls="kpi-icon-blue" num={data.analytics.profile_views || 0} label="Profile Views" />
              </div>
            );
          })()}

          {tab === "overview" && (
            <>
              <QuestionnaireNudge
                completion={completion}
                onOpen={(section) => {
                  if (section) setWizardStartSection(section);
                  setTab("questionnaire");
                }}
              />
              <Overview data={data} doAction={doAction} refresh={refresh} setTab={setTab} />
            </>
          )}
          {tab === "profile" && <ProfileEditor user={user} refreshMe={refreshMe} toast={toast} />}
          {tab === "questionnaire" && (
            <QuestionnaireWizard
              /* Iter 76.6 — /auth/me returns the full artist_profile with
                 `category`; the local `data` object never held it, so the
                 wizard used to boot with an empty category and skipped
                 the Layer 2 fetch entirely. This fixes the "only Layer 1
                 shows" bug the artist reported. */
              category={user?.artist_profile?.category || data.profile?.category}
              startSection={wizardStartSection}
              onComplete={() => { toast("Questionnaire saved 🎉"); setWizardStartSection(null); refresh(); }}
            />
          )}
          {tab === "packages" && <Packages data={data} refresh={refresh} toast={toast} />}
          {tab === "addons" && <Addons toast={toast} />}
          {tab === "media" && <MediaManager data={data} refresh={refresh} toast={toast} />}
          {tab === "calendar" && <Availability refresh={refresh} toast={toast} />}
          {tab === "bookings" && <ArtistBookings data={data} doAction={doAction} />}
          {tab === "insights" && <Insights toast={toast} />}
          {tab === "reviews" && <Reviews data={data} refresh={refresh} toast={toast} />}
          {tab === "boost" && <Boost refresh={refresh} toast={toast} />}
          {tab === "subscription" && <Subscription toast={toast} highlight={subHighlight} onHighlightConsumed={() => setSubHighlight(null)} />}
          {tab === "concierge" && <Concierge toast={toast} setTab={setTab} setSubHighlight={setSubHighlight} />}
          {tab === "kyc" && <KYC toast={toast} refresh={refresh} />}
          {tab === "tech_rider" && <TechRiderPanel toast={toast} />}
        </div>
      </main>
      {/* Mandatory T&C modal — fires when KYC is approved but T&C not yet accepted */}
      <TncAgreementGate toast={toast} onDone={() => refreshMe && refreshMe()} />
      {showWizard && <OnboardingWizard
        user={user}
        onComplete={async () => {
          setShowWizard(false);
          // Iter 91 — mark this artist as having seen the welcome
          // wizard so it doesn't auto-open on subsequent logins.
          try { await api.post("/user/mark-welcome-seen"); } catch {}
          refresh(); refreshMe();
        }}
        onClose={async () => {
          setShowWizard(false);
          try { await api.post("/user/mark-welcome-seen"); } catch {}
        }}
      />}
    </div>
  );
}

const Kpi = ({ icon, cls, num, label }) => (
  <div className="kpi" data-testid={`kpi-${label.replace(/\s+/g, "-").toLowerCase()}`}>
    <div className="kpi-top"><div className={`kpi-icon ${cls}`}>{icon}</div></div>
    <div className="kpi-num">{num}</div>
    <div className="kpi-label">{label}</div>
  </div>
);

function DateEditPopover({ open, date, current, onClose, onSave }) {
  const [mode, setMode] = React.useState(current?.isBlocked ? "blocked" : current?.isPremium ? "premium" : "available");
  const [mult, setMult] = React.useState(current?.premium?.multiplier || 1.5);
  const [label, setLabel] = React.useState(current?.premium?.label || "Weekend");
  React.useEffect(() => {
    setMode(current?.isBlocked ? "blocked" : current?.isPremium ? "premium" : "available");
    setMult(current?.premium?.multiplier || 1.5);
    setLabel(current?.premium?.label || "Weekend");
  }, [date, current]);
  if (!open) return null;
  return (
    <div className="date-edit-backdrop" onClick={onClose} data-testid="date-edit-modal">
      <div className="card card-pad date-edit" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif fs-16 fw-700 mb-4">Edit {date}</h3>
        <p className="text-muted fs-11 mb-16">Set this date as available, blocked, or premium-priced.</p>
        <div className="date-edit-modes">
          {[
            { id: "available", label: "🟢 Available", desc: "Bookable at base price" },
            { id: "premium",  label: "💎 Premium",   desc: "Weekend / festival rate" },
            { id: "blocked",  label: "🔴 Blocked",   desc: "Not bookable this date" },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              className={`date-edit-mode ${mode === m.id ? "active" : ""}`}
              onClick={() => setMode(m.id)}
              data-testid={`date-edit-mode-${m.id}`}
            >
              <div className="fw-600 fs-13">{m.label}</div>
              <div className="text-muted fs-11">{m.desc}</div>
            </button>
          ))}
        </div>

        {mode === "premium" && (
          <div className="date-edit-premium mt-16">
            <div className="field">
              <div className="field-label">Multiplier</div>
              <div className="date-edit-mult-row">
                {[1.25, 1.5, 1.75, 2, 2.5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={`mult-chip ${Number(mult) === n ? "active" : ""}`}
                    onClick={() => setMult(n)}
                    data-testid={`mult-${n}`}
                  >
                    {n}×
                  </button>
                ))}
                <input
                  type="number" min="1" max="10" step="0.1"
                  value={mult}
                  onChange={(e) => setMult(parseFloat(e.target.value) || 1)}
                  className="field-input mult-custom"
                />
              </div>
            </div>
            <div className="field">
              <div className="field-label">Label</div>
              <input
                type="text" className="field-input" value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Weekend, Diwali, New Year Eve..."
                data-testid="premium-label"
              />
            </div>
          </div>
        )}

        <div className="flex justify-between mt-20 gap-8">
          <button className="btn btn-ghost" onClick={onClose} data-testid="date-edit-cancel">Cancel</button>
          <button
            className="btn btn-gold"
            onClick={() => onSave({ mode, multiplier: mult, label })}
            data-testid="date-edit-save"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function RevenueSparkline({ series = [], onMonthClick = null }) {
  // Tiny inline SVG sparkline — no chart lib needed.
  if (!series.length) return <div className="spark-empty">No revenue data yet</div>;
  const max = Math.max(1, ...series.map((p) => p.amount));
  const min = Math.min(...series.map((p) => p.amount));
  const w = 320, h = 90, pad = 6;
  const pts = series.map((p, i) => {
    const x = pad + (i * (w - pad * 2)) / Math.max(1, series.length - 1);
    const y = h - pad - ((p.amount - min) / Math.max(1, max - min)) * (h - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  const area = `${pad},${h - pad} ${pts} ${w - pad},${h - pad}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="spark-svg" aria-label="Revenue trend">
      <defs>
        <linearGradient id="sparkGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(212,175,55,0.55)" />
          <stop offset="100%" stopColor="rgba(212,175,55,0.02)" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#sparkGradient)" />
      <polyline points={pts} fill="none" stroke="#d4af37" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {series.map((p, i) => {
        const x = pad + (i * (w - pad * 2)) / Math.max(1, series.length - 1);
        const y = h - pad - ((p.amount - min) / Math.max(1, max - min)) * (h - pad * 2);
        return (
          <circle
            key={p.key}
            cx={x} cy={y} r={onMonthClick ? 5 : 3}
            fill="#d4af37"
            stroke="#0a0a12" strokeWidth="2"
            style={onMonthClick ? { cursor: "pointer" } : undefined}
            onClick={onMonthClick ? () => onMonthClick(p) : undefined}
            data-testid={`spark-pt-${p.key}`}
          >
            <title>{p.label}: {p.amount.toLocaleString("en-IN")}</title>
          </circle>
        );
      })}
    </svg>
  );
}

function Overview({ data, doAction, refresh, setTab }) {
  const pending = data.bookings.filter(b => b.status === "pending_artist");
  const confirmed = data.bookings.filter(b => ["confirmed", "started", "completed", "reviewed"].includes(b.status));
  const [editing, setEditing] = React.useState(null); // {date, current}
  const [drilldown, setDrilldown] = React.useState(null); // month key
  const [calBump, setCalBump] = React.useState(0); // increment to force calendar re-fetch
  const { user } = useAuth();

  // Build a 6-month revenue series from confirmed bookings' event_date month bucket
  const revenueSeries = React.useMemo(() => {
    const buckets = {};
    const now = new Date();
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = d.toISOString().slice(0, 7);
      buckets[key] = { key, amount: 0, label: d.toLocaleString("en-IN", { month: "short" }) };
    }
    confirmed.forEach((b) => {
      const key = (b.event_date || "").slice(0, 7);
      if (buckets[key]) buckets[key].amount += Number(b.pricing?.artist_fee || (b.pricing?.package_fee || 0) + (b.pricing?.addons_total || 0) || 0);
    });
    return Object.values(buckets);
  }, [confirmed]);
  const monthRevenue = revenueSeries[revenueSeries.length - 1]?.amount || 0;
  const prevMonthRevenue = revenueSeries[revenueSeries.length - 2]?.amount || 0;
  const growth = prevMonthRevenue > 0 ? Math.round(((monthRevenue - prevMonthRevenue) / prevMonthRevenue) * 100) : 0;
  const drilldownBookings = drilldown ? confirmed.filter(b => (b.event_date || "").startsWith(drilldown)) : [];

  const saveDate = async ({ mode, multiplier, label }) => {
    if (!editing) return;
    try {
      if (mode === "available") {
        await api.delete(`/availability/${editing.date}`);
      } else if (mode === "blocked") {
        await api.post("/availability", { date: editing.date, status: "blocked" });
      } else {
        await api.post("/availability", {
          date: editing.date, status: "premium",
          premium_multiplier: Number(multiplier),
          premium_label: label || "Premium",
        });
      }
    } catch (e) { /* toast handled by parent */ }
    setEditing(null);
    setCalBump((n) => n + 1);
    if (refresh) refresh();
  };

  return (
    <div data-testid="overview-tab">
      {(() => {
        const answers = data.profile?.answers || {};
        const filled = Object.values(answers).filter((v) => v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)).length;
        if (filled >= 8) return null; // Already made real progress
        return (
          <div className="questionnaire-banner" data-testid="questionnaire-banner">
            <div className="questionnaire-banner-icon">📝</div>
            <div className="questionnaire-banner-body">
              <div className="questionnaire-banner-title">
                {filled === 0 ? "Complete your artist profile" : `You're ${filled} of 30+ questions in`}
              </div>
              <div className="questionnaire-banner-sub">
                {filled === 0
                  ? "Answer a few questions so customers can find you faster and book you with confidence."
                  : "Finish the guided onboarding to unlock full visibility on the marketplace."}
              </div>
            </div>
            <button
              type="button"
              className="btn btn-gold"
              onClick={() => setTab && setTab("questionnaire")}
              data-testid="questionnaire-banner-cta"
            >
              {filled === 0 ? "Start" : "Continue"} →
            </button>
          </div>
        );
      })()}
      <div className="smart-panel-grid mb-24">
        <div className="card card-pad smart-panel-cell" data-testid="smart-calendar">
          <div className="smart-panel-head">
            <span className="smart-panel-icon">📅</span>
            <div>
              <div className="smart-panel-title">Booking Calendar</div>
              <div className="smart-panel-sub">Tap any date to block it or set a premium (weekend / festival) rate</div>
            </div>
          </div>
          {user?.id && (
            <AvailabilityCalendar
              key={calBump}
              artistUserId={user.id}
              editable
              onEdit={(date, current) => setEditing({ date, current })}
              onWeekendPreset={async () => {
                const inp = window.prompt("Weekend multiplier for next 3 months?", "1.5");
                if (!inp) return;
                const mult = parseFloat(inp) || 1.5;
                const dates = [];
                const cur = new Date();
                const end = new Date();
                end.setMonth(end.getMonth() + 3);
                while (cur <= end) {
                  const dow = cur.getDay();
                  if (dow === 0 || dow === 6) {
                    dates.push(cur.toISOString().split("T")[0]);
                  }
                  cur.setDate(cur.getDate() + 1);
                }
                if (!window.confirm(`Apply ${mult}× premium to ${dates.length} weekend dates?`)) return;
                try {
                  for (const d of dates) {
                    await api.post("/availability", {
                      date: d, status: "premium",
                      premium_multiplier: mult, premium_label: "Weekend",
                    });
                  }
                  setCalBump((n) => n + 1);
                  if (refresh) refresh();
                } catch (_) {}
              }}
              onBulkEdit={async (dates, mode) => {
                let multiplier = 1.5, label = "Weekend";
                if (mode === "premium") {
                  const input = window.prompt("Premium multiplier (e.g. 1.5)?", "1.5");
                  if (!input) return;
                  multiplier = parseFloat(input) || 1.5;
                  const lbl = window.prompt("Label for these dates?", "Weekend");
                  if (lbl) label = lbl;
                }
                try {
                  for (const d of dates) {
                    if (mode === "available") {
                      await api.delete(`/availability/${d}`);
                    } else if (mode === "blocked") {
                      await api.post("/availability", { date: d, status: "blocked" });
                    } else {
                      await api.post("/availability", { date: d, status: "premium", premium_multiplier: multiplier, premium_label: label });
                    }
                  }
                  setCalBump((n) => n + 1);
                  if (refresh) refresh();
                } catch (_) {}
              }}
            />
          )}
        </div>

        <div className="smart-panel-cell-col">
          <div className="card card-pad" data-testid="smart-revenue">
            <div className="smart-panel-head">
              <span className="smart-panel-icon" style={{ background: "linear-gradient(135deg, #10b981, #059669)" }}>💰</span>
              <div>
                <div className="smart-panel-title">Revenue (6 mo)</div>
                <div className="smart-panel-sub">Tap a dot to see the bookings behind that month</div>
              </div>
            </div>
            <div className="smart-revenue-num">
              +{fmtINRFull(monthRevenue)}
              {growth !== 0 && (
                <span className={`smart-revenue-delta ${growth > 0 ? "up" : "down"}`}>
                  {growth > 0 ? "▲" : "▼"} {Math.abs(growth)}%
                </span>
              )}
            </div>
            <RevenueSparkline series={revenueSeries} onMonthClick={(p) => setDrilldown(p.key)} />
            <div className="smart-revenue-legend">
              {revenueSeries.map((p) => <span key={p.key}>{p.label}</span>)}
            </div>
          </div>

          <div className="card card-pad" data-testid="smart-pending">
            <div className="smart-panel-head">
              <span className="smart-panel-icon" style={{ background: "linear-gradient(135deg, #f59e0b, #d97706)" }}>🔔</span>
              <div>
                <div className="smart-panel-title">Pending Requests</div>
                <div className="smart-panel-sub">Respond within 24 hours to lock in the booking</div>
              </div>
            </div>
            {pending.length === 0 ? (
              <div className="empty" style={{ padding: 18 }}><div className="empty-icon">✨</div><div className="empty-title">No pending requests</div></div>
            ) : (
              <div className="smart-pending-list">
                {pending.slice(0, 4).map((b) => (
                  <div key={b.id} className="smart-pending-row" data-testid={`smart-pending-${b.id}`}>
                    <div className="smart-pending-info">
                      <div className="fw-600 fs-13">{b.customer_name || "Customer"}</div>
                      <div className="text-muted fs-11">{b.event_type} · {b.event_date}</div>
                    </div>
                    <div className="smart-pending-actions">
                      <button className="btn btn-green btn-xs" onClick={() => doAction(b.id, "accept")} data-testid={`smart-accept-${b.id}`}>Accept</button>
                      <button className="btn btn-red btn-xs" onClick={() => doAction(b.id, "reject")} data-testid={`smart-reject-${b.id}`}>Reject</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <DateEditPopover
        open={!!editing}
        date={editing?.date}
        current={editing?.current}
        onClose={() => setEditing(null)}
        onSave={saveDate}
      />

      {drilldown && (
        <div className="date-edit-backdrop" onClick={() => setDrilldown(null)} data-testid="revenue-drilldown">
          <div className="card card-pad date-edit" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
            <h3 className="font-serif fs-18 fw-700 mb-4">Bookings in {revenueSeries.find(p => p.key === drilldown)?.label} {drilldown.slice(0,4)}</h3>
            <p className="text-muted fs-12 mb-16">{drilldownBookings.length} confirmed booking(s) · Total {fmtINRFull(drilldownBookings.reduce((s, b) => s + Number(b.pricing?.artist_fee || (b.pricing?.package_fee || 0) + (b.pricing?.addons_total || 0) || 0), 0))}</p>
            {drilldownBookings.length === 0 ? (
              <div className="empty" style={{ padding: 18 }}><div className="empty-icon">📭</div><div className="empty-title">No bookings in this month yet</div></div>
            ) : (
              <div className="drilldown-list" style={{ maxHeight: 380, overflowY: "auto" }}>
                {drilldownBookings.map((b) => (
                  <div key={b.id} className="smart-pending-row" data-testid={`drilldown-row-${b.id}`}>
                    <div className="smart-pending-info">
                      <div className="fw-600 fs-13">{b.customer_name || "Customer"} · {b.ref}</div>
                      <div className="text-muted fs-11">{b.event_type} · {b.event_date} · {b.status}</div>
                    </div>
                    <div className="text-gold fw-600">{fmtINRFull(b.pricing?.artist_fee || (b.pricing?.package_fee || 0) + (b.pricing?.addons_total || 0) || 0)}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="flex justify-end mt-16">
              <button className="btn btn-ghost" onClick={() => setDrilldown(null)} data-testid="drilldown-close">Close</button>
            </div>
          </div>
        </div>
      )}

      <div className="card mb-16">
        <div className="card-head"><div className="card-title">📬 All Booking Requests</div></div>
        <BookingsTable bookings={pending} role="artist" onAction={doAction} />
      </div>
      <div className="card">
        <div className="card-head"><div className="card-title">⭐ Recent Reviews</div></div>
        <div style={{ padding: 14 }}>
          {data.reviews.length === 0 ? <div className="empty"><div className="empty-icon">⭐</div><div className="empty-title">No reviews yet</div></div> :
            data.reviews.slice(0, 3).map((r) => (
              <div key={r.id} className="card card-pad mb-12">
                <div className="flex justify-between mb-8">
                  <div className="fw-600">{r.customer_name}</div>
                  <div className="text-gold">{"★".repeat(r.rating)}</div>
                </div>
                <div className="fs-13 text-muted">{r.text}</div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

function ProfileEditor({ user, refreshMe, toast }) {
  const [form, setForm] = useState({
    bio: "", tagline: "", city: "", languages: "", genres: "", event_types: "",
    awards: "", certifications: "", youtube_url: "", instagram_url: "", spotify_url: "",
  });
  const [loaded, setLoaded] = useState(false);
  const [profile, setProfile] = useState({});
  const [uploading, setUploading] = useState({ profile: false, cover: false });
  const [progress, setProgress] = useState({ profile: 0, cover: 0 });
  const profileRef = useRef();
  const coverRef = useRef();
  const [cacheBust, setCacheBust] = useState(Date.now());

  const reload = async () => {
    const r = await api.get("/auth/me");
    const p = r.data.artist_profile || {};
    setProfile(p);
    setForm({
      bio: p.bio || "", tagline: p.tagline || "", city: p.city || "",
      languages: (p.languages || []).join(", "),
      genres: (p.genres || []).join(", "),
      event_types: (p.event_types || []).join(", "),
      awards: (p.awards || []).join("\n"),
      certifications: (p.certifications || []).join("\n"),
      youtube_url: p.youtube_url || "",
      instagram_url: p.instagram_url || "",
      spotify_url: p.spotify_url || "",
    });
    setCacheBust(Date.now());
    setLoaded(true);
  };

  useEffect(() => { reload(); }, []);

  const uploadImage = async (file, type) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast("Please pick an image", "error"); return; }
    if (file.size > 12 * 1024 * 1024) { toast("Image too large (max 12 MB)", "error"); return; }
    setUploading((u) => ({ ...u, [type]: true }));
    setProgress((p) => ({ ...p, [type]: 0 }));
    try {
      const dataUrl = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result); r.onerror = rej;
        r.readAsDataURL(file);
      });
      // Delete previous image of this type to avoid orphans
      const existing = profile[type === "profile" ? "profile_image" : "cover_image"];
      if (existing) {
        try {
          await api.delete(`/media/${existing}`);
        } catch (delErr) {
          // Non-fatal — orphaned media will be cleaned up by the nightly job.
          // Log so we can spot patterns instead of silently swallowing.
          if (typeof console !== "undefined") console.warn("orphan-media delete failed:", delErr?.message || delErr);
        }
      }
      await api.post("/media/upload", { type, data_url: dataUrl, title: `${type}-${file.name}` }, {
        onUploadProgress: (e) => {
          if (e.total) setProgress((p) => ({ ...p, [type]: Math.round((e.loaded / e.total) * 100) }));
        },
      });
      toast(`${type === "profile" ? "Profile picture" : "Cover banner"} updated`);
      await reload();
      refreshMe();
    } catch (e) { toast(formatApiError(e), "error"); }
    setUploading((u) => ({ ...u, [type]: false }));
    setProgress((p) => ({ ...p, [type]: 0 }));
    // reset the input so the same file can be reselected
    if (type === "profile" && profileRef.current) profileRef.current.value = "";
    if (type === "cover" && coverRef.current) coverRef.current.value = "";
  };

  const save = async () => {
    try {
      await api.put("/users/me", {
        bio: form.bio, tagline: form.tagline, city: form.city,
        languages: form.languages.split(",").map(s => s.trim()).filter(Boolean),
        genres: form.genres.split(",").map(s => s.trim()).filter(Boolean),
        event_types: form.event_types.split(",").map(s => s.trim()).filter(Boolean),
        awards: form.awards.split("\n").map(s => s.trim()).filter(Boolean),
        certifications: form.certifications.split("\n").map(s => s.trim()).filter(Boolean),
        youtube_url: form.youtube_url,
        instagram_url: form.instagram_url,
        spotify_url: form.spotify_url,
      });
      toast("Profile saved");
      refreshMe();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  if (!loaded) return <div className="loading"><div className="spinner" /></div>;

  return (
    <div className="card card-pad" data-testid="profile-editor">
      <h2 className="font-serif fs-20 fw-700 mb-16">Artist Profile</h2>

      {/* Cover Banner */}
      <div className="field">
        <div className="field-label">Cover Banner</div>
        <div
          onClick={() => coverRef.current?.click()}
          style={{
            height: 160, borderRadius: 12, cursor: "pointer", position: "relative",
            border: "2px dashed var(--glass-border)",
            background: profile.cover_image
              ? `linear-gradient(180deg, rgba(0,0,0,0.2), rgba(0,0,0,0.5)), url(${mediaUrl(profile.cover_image)}?v=${cacheBust}) center/cover`
              : "linear-gradient(135deg, var(--bg3), var(--purple))",
            display: "grid", placeItems: "center",
          }}
          data-testid="cover-upload-zone"
        >
          <input ref={coverRef} type="file" accept="image/*" style={{ display: "none" }}
                 onChange={(e) => uploadImage(e.target.files[0], "cover")} />
          {uploading.cover ? (
            <div className="text-center">
              <div className="spinner" style={{ margin: "0 auto 8px" }} />
              <div className="fs-12 fw-600">Uploading… {progress.cover}%</div>
            </div>
          ) : (
            <div className="text-center">
              <div className="fs-22 mb-4">🖼️</div>
              <div className="fs-13 fw-600">{profile.cover_image ? "Click to replace" : "Click to upload cover banner"}</div>
              <div className="fs-11 text-muted mt-4">Recommended 1600 × 480 · Max 12 MB</div>
            </div>
          )}
        </div>
      </div>

      {/* Profile Picture */}
      <div className="field">
        <div className="field-label">Profile Picture</div>
        <div className="flex items-center gap-16">
          <div
            onClick={() => profileRef.current?.click()}
            className="avatar avatar-lg"
            style={{
              cursor: "pointer", position: "relative",
              width: 96, height: 96,
              background: profile.profile_image
                ? `url(${mediaUrl(profile.profile_image)}?v=${cacheBust}) center/cover`
                : "linear-gradient(135deg, var(--purple), var(--gold))",
              fontSize: profile.profile_image ? 0 : 36,
              border: "2px solid var(--gold-border)",
            }}
            data-testid="profile-upload-zone"
          >
            <input ref={profileRef} type="file" accept="image/*" style={{ display: "none" }}
                   onChange={(e) => uploadImage(e.target.files[0], "profile")} />
            {!profile.profile_image && (profile.emoji || "🎤")}
            {uploading.profile && (
              <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.7)", display: "grid", placeItems: "center", borderRadius: "50%" }}>
                <div className="fs-11 fw-700 text-gold">{progress.profile}%</div>
              </div>
            )}
          </div>
          <div>
            <button className="btn btn-ghost btn-sm" onClick={() => profileRef.current?.click()} disabled={uploading.profile} data-testid="pick-profile-btn">
              {uploading.profile ? "Uploading…" : profile.profile_image ? "Change Photo" : "Upload Photo"}
            </button>
            <div className="text-muted fs-11 mt-4">Square format · Max 12 MB</div>
          </div>
        </div>
      </div>

      <div className="divider" />

      <div className="field">
        <div className="field-label">Tagline</div>
        <input className="field-input" value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })} data-testid="prof-tagline" />
      </div>
      <div className="field">
        <div className="field-label">Bio</div>
        <textarea className="field-input" rows={5} value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} data-testid="prof-bio" />
      </div>
      <div className="field-row">
        <div className="field">
          <div className="field-label">City</div>
          <input className="field-input" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} data-testid="prof-city" />
        </div>
        <div className="field">
          <div className="field-label">Languages (comma-separated)</div>
          <input className="field-input" value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} data-testid="prof-languages" />
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <div className="field-label">Genres</div>
          <input className="field-input" value={form.genres} onChange={(e) => setForm({ ...form, genres: e.target.value })} data-testid="prof-genres" />
        </div>
        <div className="field">
          <div className="field-label">Event Types</div>
          <input className="field-input" value={form.event_types} onChange={(e) => setForm({ ...form, event_types: e.target.value })} data-testid="prof-event-types" />
        </div>
      </div>
      <div className="field">
        <div className="field-label">Awards (one per line)</div>
        <textarea className="field-input" rows={3} value={form.awards} onChange={(e) => setForm({ ...form, awards: e.target.value })} placeholder="MTV India Music Award 2023" data-testid="prof-awards" />
      </div>
      <div className="field">
        <div className="field-label">Certifications (one per line)</div>
        <textarea className="field-input" rows={3} value={form.certifications} onChange={(e) => setForm({ ...form, certifications: e.target.value })} placeholder="Trinity College London - Grade 8 Vocals" data-testid="prof-certifications" />
      </div>
      <h3 className="fs-13 fw-600 mb-12 mt-16 text-muted" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Social Links</h3>
      <div className="field-row">
        <div className="field">
          <div className="field-label">YouTube</div>
          <input className="field-input" value={form.youtube_url} onChange={(e) => setForm({ ...form, youtube_url: e.target.value })} placeholder="https://youtube.com/@you" data-testid="prof-youtube" />
        </div>
        <div className="field">
          <div className="field-label">Instagram</div>
          <input className="field-input" value={form.instagram_url} onChange={(e) => setForm({ ...form, instagram_url: e.target.value })} placeholder="https://instagram.com/you" data-testid="prof-instagram" />
        </div>
      </div>
      <div className="field">
        <div className="field-label">Spotify (optional)</div>
        <input className="field-input" value={form.spotify_url} onChange={(e) => setForm({ ...form, spotify_url: e.target.value })} placeholder="https://spotify.com/artist/..." data-testid="prof-spotify" />
      </div>
      <button className="btn btn-gold" onClick={save} data-testid="prof-save">Save Changes</button>
    </div>
  );
}

function Packages({ data, refresh, toast }) {
  const [modal, setModal] = useState(null);

  const save = async (pkg) => {
    try {
      if (pkg.id) await api.put(`/packages/${pkg.id}`, pkg);
      else await api.post("/packages", pkg);
      toast("Package saved");
      setModal(null);
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };
  const del = async (id) => {
    if (!window.confirm("Delete this package?")) return;
    await api.delete(`/packages/${id}`);
    toast("Deleted");
    refresh();
  };

  return (
    <div data-testid="packages-tab">
      <div className="flex justify-between mb-16">
        <h2 className="font-serif fs-20 fw-700">Pricing Packages</h2>
        <button className="btn btn-gold btn-sm" onClick={() => setModal({ name: "", price: 0, duration: "", features: [], is_popular: false })} data-testid="add-package-btn">+ New Package</button>
      </div>
      <div className="grid grid-3">
        {data.packages.length === 0 && <div className="empty" style={{ gridColumn: "1/-1" }}><div className="empty-icon">📦</div><div className="empty-title">No packages yet</div></div>}
        {data.packages.map((p) => (
          <div key={p.id} className={`pkg-card ${p.is_popular ? "popular" : ""}`} data-testid={`pkg-${p.id}`}>
            <div className="pkg-name">{p.name}</div>
            <div className="text-muted fs-12 mb-12">⏱ {p.duration}</div>
            <div className="pkg-price">{fmtINRFull(p.price)}</div>
            <ul className="pkg-features">{(p.features || []).map((f, i) => <li key={`${p.id || "new"}-f-${i}-${f}`}>{f}</li>)}</ul>
            <div className="flex gap-8 mt-16">
              <button className="btn btn-ghost btn-xs" onClick={() => setModal(p)} data-testid={`edit-pkg-${p.id}`}>Edit</button>
              <button className="btn btn-red btn-xs" onClick={() => del(p.id)} data-testid={`del-pkg-${p.id}`}>Delete</button>
            </div>
          </div>
        ))}
      </div>
      {modal && <PackageModal pkg={modal} onSave={save} onClose={() => setModal(null)} />}
    </div>
  );
}

function PackageModal({ pkg, onSave, onClose }) {
  const [p, setP] = useState({
    travel_required: false,
    accommodation_required: false,
    hotel_category: "",
    flight_class: "",
    team_size: "",
    arrival_buffer_days: "",
    local_transport_required: false,
    meals_required: false,
    travel_notes: "",
    ...pkg,
    features: Array.isArray(pkg.features) ? pkg.features.join("\n") : "",
  });
  return (
    <div className="modal-bg" onClick={onClose} data-testid="pkg-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxHeight: "90vh", overflowY: "auto" }}>
        <div className="modal-title">{pkg.id ? "Edit" : "New"} Package</div>
        <div className="field"><div className="field-label">Name</div>
          <input className="field-input" value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} data-testid="pkg-name" /></div>
        <div className="field-row">
          <div className="field"><div className="field-label">Price (₹)</div>
            <input className="field-input" type="number" value={p.price} onChange={(e) => setP({ ...p, price: Number(e.target.value) })} data-testid="pkg-price" /></div>
          <div className="field"><div className="field-label">Duration</div>
            <input className="field-input" value={p.duration} onChange={(e) => setP({ ...p, duration: e.target.value })} placeholder="3 hours" data-testid="pkg-duration" /></div>
        </div>
        <div className="field"><div className="field-label">Features (one per line)</div>
          <textarea className="field-input" rows={5} value={p.features} onChange={(e) => setP({ ...p, features: e.target.value })} data-testid="pkg-features" /></div>
        <label className="flex items-center gap-8 mb-16">
          <input type="checkbox" checked={p.is_popular} onChange={(e) => setP({ ...p, is_popular: e.target.checked })} data-testid="pkg-popular" />
          <span>Mark as Most Popular</span>
        </label>

        {/* Sprint 4 — Travel & Accommodation Requirements */}
        <div className="divider" style={{ margin: "16px 0" }} />
        <div className="fw-700 fs-13 mb-8 text-gold" style={{ textTransform: "uppercase", letterSpacing: 1 }}>✈️ Travel & Accommodation Rider</div>
        <div className="text-muted fs-11 mb-12">These requirements are borne by the customer directly (not billed by BookTalent). They will be included in the booking agreement.</div>

        <div className="field-row">
          <label className="flex items-center gap-8">
            <input type="checkbox" checked={!!p.travel_required} onChange={(e) => setP({ ...p, travel_required: e.target.checked })} data-testid="pkg-travel-required" />
            <span>Travel required</span>
          </label>
          <label className="flex items-center gap-8">
            <input type="checkbox" checked={!!p.accommodation_required} onChange={(e) => setP({ ...p, accommodation_required: e.target.checked })} data-testid="pkg-accommodation-required" />
            <span>Accommodation required</span>
          </label>
        </div>

        {(p.travel_required || p.accommodation_required) && (
          <>
            <div className="field-row">
              <div className="field">
                <div className="field-label">Flight class</div>
                <select className="field-input" value={p.flight_class || ""} onChange={(e) => setP({ ...p, flight_class: e.target.value })} data-testid="pkg-flight-class">
                  <option value="">—</option>
                  <option value="economy">Economy</option>
                  <option value="premium-economy">Premium Economy</option>
                  <option value="business">Business</option>
                  <option value="first">First</option>
                </select>
              </div>
              <div className="field">
                <div className="field-label">Hotel category</div>
                <select className="field-input" value={p.hotel_category || ""} onChange={(e) => setP({ ...p, hotel_category: e.target.value })} data-testid="pkg-hotel-category">
                  <option value="">—</option>
                  <option value="3-star">3-Star</option>
                  <option value="4-star">4-Star</option>
                  <option value="5-star">5-Star</option>
                  <option value="luxury">Luxury / Boutique</option>
                </select>
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <div className="field-label">Team size (people)</div>
                <input className="field-input" type="number" min="1" value={p.team_size || ""} onChange={(e) => setP({ ...p, team_size: Number(e.target.value) || "" })} data-testid="pkg-team-size" />
              </div>
              <div className="field">
                <div className="field-label">Arrival buffer (days before event)</div>
                <input className="field-input" type="number" min="0" value={p.arrival_buffer_days || ""} onChange={(e) => setP({ ...p, arrival_buffer_days: Number(e.target.value) || "" })} data-testid="pkg-arrival-buffer" />
              </div>
            </div>
          </>
        )}

        <div className="field-row">
          <label className="flex items-center gap-8">
            <input type="checkbox" checked={!!p.local_transport_required} onChange={(e) => setP({ ...p, local_transport_required: e.target.checked })} data-testid="pkg-local-transport" />
            <span>Local transport required</span>
          </label>
          <label className="flex items-center gap-8">
            <input type="checkbox" checked={!!p.meals_required} onChange={(e) => setP({ ...p, meals_required: e.target.checked })} data-testid="pkg-meals" />
            <span>Meals during stay</span>
          </label>
        </div>

        <div className="field">
          <div className="field-label">Additional rider notes</div>
          <textarea className="field-input" rows={3} value={p.travel_notes || ""} onChange={(e) => setP({ ...p, travel_notes: e.target.value })} placeholder="e.g. vegetarian meals, specific hotel brand preference, green room requirements…" data-testid="pkg-travel-notes" />
        </div>

        <div className="flex gap-12">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" style={{ flex: 1 }} onClick={() => onSave({
            ...p,
            features: p.features.split("\n").map(s => s.trim()).filter(Boolean),
            team_size: p.team_size ? Number(p.team_size) : null,
            arrival_buffer_days: p.arrival_buffer_days !== "" ? Number(p.arrival_buffer_days) : null,
          })} data-testid="pkg-save">Save</button>
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Sprint 3 — Artist-defined Add-ons management (CRUD + toggle active)
// ────────────────────────────────────────────────────────────────────────
function Addons({ toast }) {
  const [items, setItems] = useState([]);
  const [modal, setModal] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const r = await api.get("/artist/addons");
      setItems(r.data);
    } catch (e) { toast(formatApiError(e), "error"); }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []); // eslint-disable-line

  const save = async (a) => {
    try {
      if (a.id) {
        const { id, artist_id, created_at, updated_at, deleted, ...patch } = a;
        await api.patch(`/artist/addons/${id}`, patch);
      } else {
        await api.post("/artist/addons", a);
      }
      toast("Add-on saved");
      setModal(null);
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const toggleActive = async (a) => {
    try {
      await api.patch(`/artist/addons/${a.id}`, { active: !a.active });
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const del = async (id) => {
    if (!window.confirm("Delete this add-on? Historical bookings will keep their snapshot.")) return;
    try {
      await api.delete(`/artist/addons/${id}`);
      toast("Add-on deleted");
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  return (
    <div data-testid="addons-tab">
      <div className="flex justify-between mb-16">
        <div>
          <h2 className="font-serif fs-20 fw-700">Booking Add-ons</h2>
          <p className="text-muted fs-13">Extras customers can pick when they book you (extra hour, sound system, extra performer, etc.).</p>
        </div>
        <button className="btn btn-gold btn-sm" onClick={() => setModal({ name: "", description: "", price: 0, is_mandatory: false, max_quantity: 1, gst_pct: 0, active: true })} data-testid="add-addon-btn">+ New Add-on</button>
      </div>
      {loading ? (
        <div className="loading"><div className="spinner" /></div>
      ) : items.length === 0 ? (
        <div className="empty"><div className="empty-icon">🎁</div><div className="empty-title">No add-ons yet</div><p className="fs-13 text-muted">Add extras to boost your booking value.</p></div>
      ) : (
        <div className="grid grid-3">
          {items.map((a) => (
            <div key={a.id} className={`pkg-card ${a.is_mandatory ? "popular" : ""}`} data-testid={`addon-item-${a.id}`}>
              {a.is_mandatory && <span className="popular-tag">★ Mandatory</span>}
              <div className="pkg-name" style={{ marginTop: a.is_mandatory ? 12 : 0 }}>{a.name}</div>
              {a.description && <div className="text-muted fs-12 mb-8">{a.description}</div>}
              <div className="pkg-price">{fmtINRFull(a.price)}</div>
              <div className="text-muted fs-11">Up to {a.max_quantity} · {a.gst_pct}% GST</div>
              <div className="flex gap-8 mt-16 items-center">
                <label className="flex items-center gap-8 fs-12" style={{ marginRight: "auto" }}>
                  <input type="checkbox" checked={!!a.active} onChange={() => toggleActive(a)} data-testid={`addon-toggle-${a.id}`} />
                  <span>{a.active ? "Active" : "Inactive"}</span>
                </label>
                <button className="btn btn-ghost btn-xs" onClick={() => setModal(a)} data-testid={`edit-addon-${a.id}`}>Edit</button>
                <button className="btn btn-red btn-xs" onClick={() => del(a.id)} data-testid={`del-addon-${a.id}`}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {modal && <AddonModal item={modal} onSave={save} onClose={() => setModal(null)} />}
    </div>
  );
}

function AddonModal({ item, onSave, onClose }) {
  const [a, setA] = useState(item);
  return (
    <div className="modal-bg" onClick={onClose} data-testid="addon-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxHeight: "90vh", overflowY: "auto" }}>
        <div className="modal-title">{item.id ? "Edit" : "New"} Add-on</div>
        <div className="field"><div className="field-label">Name *</div>
          <input className="field-input" value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} placeholder="e.g. Extra Hour of Performance" data-testid="addon-name" /></div>
        <div className="field"><div className="field-label">Description</div>
          <textarea className="field-input" rows={2} value={a.description || ""} onChange={(e) => setA({ ...a, description: e.target.value })} placeholder="Short pitch for the customer" data-testid="addon-desc" /></div>
        <div className="field-row">
          <div className="field"><div className="field-label">Price (₹) *</div>
            <input className="field-input" type="number" min="0" value={a.price} onChange={(e) => setA({ ...a, price: Number(e.target.value) })} data-testid="addon-price" /></div>
          <div className="field"><div className="field-label">Max Quantity</div>
            <input className="field-input" type="number" min="1" max="100" value={a.max_quantity} onChange={(e) => setA({ ...a, max_quantity: Number(e.target.value) })} data-testid="addon-maxq" /></div>
        </div>
        <div className="field-row">
          <div className="field"><div className="field-label">GST % (on add-on)</div>
            <input className="field-input" type="number" min="0" max="28" value={a.gst_pct} onChange={(e) => setA({ ...a, gst_pct: Number(e.target.value) })} data-testid="addon-gst" /></div>
          <div className="field" style={{ display: "flex", alignItems: "flex-end", paddingBottom: 8 }}>
            <label className="flex items-center gap-8">
              <input type="checkbox" checked={!!a.is_mandatory} onChange={(e) => setA({ ...a, is_mandatory: e.target.checked })} data-testid="addon-mandatory" />
              <span>Mandatory (customer must select)</span>
            </label>
          </div>
        </div>
        <label className="flex items-center gap-8 mb-16">
          <input type="checkbox" checked={!!a.active} onChange={(e) => setA({ ...a, active: e.target.checked })} data-testid="addon-active" />
          <span>Active (visible to customers)</span>
        </label>
        <div className="flex gap-12">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" style={{ flex: 1 }} disabled={!a.name || a.price < 0} onClick={() => onSave(a)} data-testid="addon-save">Save Add-on</button>
        </div>
      </div>
    </div>
  );
}

function MediaManager({ data, refresh, toast }) {
  const inputRef = useRef();
  const replaceRefs = useRef({});
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  // Iter 72 — Per-file upload feedback. Each entry:
  //   { name, size, mime, previewUrl, status: 'uploading'|'done'|'error', error? }
  // Rendered as a preview strip so artists can immediately see WHAT
  // they uploaded and each item's live status, instead of a single
  // ambiguous "Uploading… 42%" line.
  const [pending, setPending] = useState([]);

  const fileToDataUrl = (f) => new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result); r.onerror = rej;
    r.readAsDataURL(f);
  });

  // Iter 76.5 — Capture the first frame of an uploaded video in a hidden
  // <canvas>. Returned as a small JPEG data URL that the finish() call
  // uploads as a server-side poster so gallery tiles have an instant
  // preview instead of waiting for the browser to load metadata.
  const capturePoster = (file) => new Promise((resolve) => {
    try {
      const url = URL.createObjectURL(file);
      const video = document.createElement("video");
      video.src = url;
      video.crossOrigin = "anonymous";
      video.muted = true;
      video.playsInline = true;
      video.preload = "metadata";
      const cleanup = () => { try { URL.revokeObjectURL(url); } catch {} };
      const timer = setTimeout(() => { cleanup(); resolve(null); }, 8000);
      video.onloadedmetadata = () => {
        // Seek 0.5s in — first frame is often black on many codecs.
        video.currentTime = Math.min(0.5, (video.duration || 1) / 3);
      };
      video.onseeked = () => {
        try {
          const canvas = document.createElement("canvas");
          const w = Math.min(video.videoWidth || 640, 640);
          const h = Math.round(w * (video.videoHeight / video.videoWidth) || 360);
          canvas.width = w; canvas.height = h;
          canvas.getContext("2d").drawImage(video, 0, 0, w, h);
          clearTimeout(timer);
          resolve(canvas.toDataURL("image/jpeg", 0.72));
        } catch { clearTimeout(timer); resolve(null); }
        cleanup();
      };
      video.onerror = () => { clearTimeout(timer); cleanup(); resolve(null); };
    } catch { resolve(null); }
  });

  // Iter 76.5 — Wrap any promise-returning fn in exponential-backoff
  // retries so a single chunk network blip doesn't nuke a multi-GB
  // upload. Retries only on network errors / 5xx / 429; user errors
  // (4xx) bubble up immediately.
  const withRetry = async (fn, attempts = 3) => {
    let lastErr;
    for (let i = 0; i < attempts; i++) {
      try {
        return await fn();
      } catch (e) {
        const s = e?.response?.status;
        const retryable = !s || s >= 500 || s === 429;
        if (!retryable || i === attempts - 1) throw e;
        lastErr = e;
        await new Promise((r) => setTimeout(r, Math.min(1000 * (2 ** i), 8000)));
      }
    }
    throw lastErr;
  };

  const upload = async (files, type) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setProgress(0);
    const list = Array.from(files);
    // Seed pending entries with client-side previews so the strip is
    // visible instantly — long before the base64 upload finishes.
    const seeded = list.map((f) => ({
      name: f.name,
      size: f.size,
      mime: f.type || "application/octet-stream",
      previewUrl: (f.type.startsWith("image/") || f.type.startsWith("video/"))
        ? URL.createObjectURL(f) : null,
      status: "uploading",
    }));
    setPending(seeded);
    // Iter 73 — track per-file outcomes locally so the summary toast
    // reflects reality (previously we always shouted "Uploaded N files"
    // even when the client-side 12MB guard rejected every one of them).
    let ok = 0, failed = 0;
    try {
      for (let i = 0; i < list.length; i++) {
        const f = list[i];
        const isVideo = (f.type || "").startsWith("video/");
        // Iter 76 — Videos: allow up to 1 GB and route through the
        // chunked endpoints. Photos & other files stick with the
        // legacy 12 MB base64 flow.
        const sizeLimit = isVideo ? 1024 * 1024 * 1024 : 12 * 1024 * 1024;
        const sizeLabel = isVideo ? "1 GB" : "12MB";
        if (f.size > sizeLimit) {
          toast(`${f.name} too large (max ${sizeLabel})`, "error");
          setPending((prev) => prev.map((p, idx) => idx === i ? { ...p, status: "error", error: `Too large (max ${sizeLabel})` } : p));
          failed++;
          continue;
        }
        try {
          if (isVideo) {
            // ── Chunked upload path ────────────────────────────────
            // Capture the first-frame poster BEFORE we start chunking
            // so it's ready to include in the finish() call.
            const posterPromise = capturePoster(f);
            const start = await api.post("/media/video/start", {
              filename: f.name, mime: f.type || "video/mp4",
              size: f.size, type, title: f.name,
            });
            const sessionId = start.data.session_id;
            const chunkSize = start.data.chunk_size || (8 * 1024 * 1024);
            const totalChunks = Math.ceil(f.size / chunkSize);
            for (let ci = 0; ci < totalChunks; ci++) {
              const slice = f.slice(ci * chunkSize, (ci + 1) * chunkSize);
              // Iter 76.5 — Retry each chunk up to 3× on transient
              // network / 5xx errors so a phone losing signal for a
              // second doesn't torpedo a 1 GB upload.
              await withRetry(() => {
                const fd = new FormData();
                fd.append("session_id", sessionId);
                fd.append("chunk_index", String(ci));
                fd.append("chunk", slice, `${f.name}.part${ci}`);
                return api.post("/media/video/chunk", fd, {
                  headers: { "Content-Type": "multipart/form-data" },
                  onUploadProgress: (e) => {
                    const chunkProg = e.total ? (e.loaded / e.total) : 0;
                    const fileProg = (ci + chunkProg) / totalChunks;
                    setProgress(Math.round(((i + fileProg) / list.length) * 100));
                  },
                });
              });
            }
            const posterUrl = await posterPromise;
            const fin = new FormData();
            fin.append("session_id", sessionId);
            if (posterUrl) fin.append("poster_data_url", posterUrl);
            await withRetry(() => api.post("/media/video/finish", fin, {
              headers: { "Content-Type": "multipart/form-data" },
            }));
          } else {
            // ── Legacy small-file base64 path (unchanged) ─────────
            const dataUrl = await fileToDataUrl(f);
            await api.post("/media/upload", { type, data_url: dataUrl, title: f.name }, {
              onUploadProgress: (e) => {
                const fileProg = e.total ? (e.loaded / e.total) : 0;
                setProgress(Math.round(((i + fileProg) / list.length) * 100));
              },
            });
          }
          setPending((prev) => prev.map((p, idx) => idx === i ? { ...p, status: "done" } : p));
          ok++;
        } catch (err) {
          setPending((prev) => prev.map((p, idx) => idx === i ? { ...p, status: "error", error: formatApiError(err) } : p));
          failed++;
        }
      }
      if (ok > 0) toast(`Uploaded ${ok} file${ok > 1 ? "s" : ""}${failed ? ` · ${failed} failed` : ""}`);
      else if (failed > 0) toast(`Upload failed · ${failed} file${failed > 1 ? "s" : ""} rejected`, "error");
      await refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
    setProgress(0);
    if (inputRef.current) inputRef.current.value = "";
    // Iter 73 — Auto-fade success rows after 4s. Only revoke the blob
    // URLs for the rows we're actually removing (leaving error rows
    // intact so the artist can still see the thumbnail and act on it).
    setTimeout(() => {
      setPending((prev) => {
        prev.forEach((p) => {
          if (p.status !== "error" && p.previewUrl) URL.revokeObjectURL(p.previewUrl);
        });
        return prev.filter((p) => p.status === "error");
      });
    }, 4000);
  };

  const replace = async (mediaId, file) => {
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) { toast("File too large (max 12MB)", "error"); return; }
    try {
      const dataUrl = await fileToDataUrl(file);
      await api.put(`/media/${mediaId}`, { type: "gallery", data_url: dataUrl, title: file.name });
      toast("Replaced");
      await refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
    if (replaceRefs.current[mediaId]) replaceRefs.current[mediaId].value = "";
  };

  const del = async (id) => {
    if (!window.confirm("Delete this media?")) return;
    await api.delete(`/media/${id}`);
    await refresh();
    toast("Deleted");
  };

  const toggleFeatured = async (id) => {
    await api.post(`/media/${id}/feature`);
    await refresh();
  };

  const move = async (idx, dir) => {
    const items = data.media.filter((m) => !["kyc", "profile", "cover"].includes(m.type));
    const j = idx + dir;
    if (j < 0 || j >= items.length) return;
    const swap = [...items];
    [swap[idx], swap[j]] = [swap[j], swap[idx]];
    await api.post("/media/reorder", { ids: swap.map(x => x.id) });
    await refresh();
  };

  const onDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files) upload(e.dataTransfer.files, "gallery");
  };

  const galleryItems = data.media.filter((m) => !["kyc", "profile", "cover"].includes(m.type));

  return (
    <div data-testid="media-tab">
      <div className="flex justify-between mb-16">
        <h2 className="font-serif fs-20 fw-700">Media Manager</h2>
        <div className="text-muted fs-12">{galleryItems.length} item{galleryItems.length !== 1 ? "s" : ""}</div>
      </div>
      <div
        className="upload-zone mb-20"
        data-testid="upload-zone"
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef} type="file" multiple
          accept="image/*,video/*,audio/*,application/pdf"
          onChange={(e) => upload(e.target.files, "gallery")}
          style={{ display: "none" }}
        />
        <div className="upload-zone-icon">📁</div>
        <div className="fs-14 fw-600 mb-4">{busy ? `Uploading… ${progress}%` : "Drop files here or click to browse"}</div>
        <div className="text-muted fs-12">Photos & docs auto-compressed · up to 12&nbsp;MB each · Videos up to 1&nbsp;GB via chunked upload</div>
        {busy && (
          <div style={{ width: "60%", margin: "12px auto 0", height: 6, background: "var(--glass)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${progress}%`, height: "100%", background: "linear-gradient(90deg, var(--gold), var(--purple))", transition: "width 0.2s" }} />
          </div>
        )}
      </div>
      {/* Iter 72 — Live per-file upload preview strip. */}
      {pending.length > 0 && (
        <div className="upload-preview-strip" data-testid="upload-preview-strip">
          {pending.map((p, i) => (
            <div key={i} className={`upload-preview-item upload-${p.status}`} data-testid={`upload-preview-${i}`}>
              <div className="upload-preview-thumb">
                {p.previewUrl && p.mime.startsWith("image/") ? (
                  <img src={p.previewUrl} alt={p.name} />
                ) : p.previewUrl && p.mime.startsWith("video/") ? (
                  <video src={p.previewUrl} muted />
                ) : p.mime === "application/pdf" ? (
                  <div className="upload-preview-icon">📄</div>
                ) : p.mime.startsWith("audio/") ? (
                  <div className="upload-preview-icon">🎵</div>
                ) : (
                  <div className="upload-preview-icon">📎</div>
                )}
                <div className={`upload-preview-badge upload-preview-${p.status}`}>
                  {p.status === "uploading" && <span className="spinner-sm" />}
                  {p.status === "done" && "✓"}
                  {p.status === "error" && "✕"}
                </div>
              </div>
              <div className="upload-preview-meta">
                <div className="upload-preview-name" title={p.name}>{p.name}</div>
                <div className="upload-preview-sub">
                  {(p.size / 1024).toFixed(1)} KB · {
                    p.status === "uploading" ? "Uploading…" :
                    p.status === "done" ? "Uploaded ✓" :
                    p.error || "Failed"
                  }
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="media-grid">
        {galleryItems.map((m, idx) => {
          const isVideo = (m.mime || "").startsWith("video/");
          const isReel = data?.profile?.featured_video_id === m.id;
          return (
          <div key={m.id} className="media-tile" data-testid={`media-tile-${m.id}`}>
            {isVideo ? (
              /* Iter 76.5 — Server-supplied poster (client-captured
                 first frame) shows instantly instead of a black tile. */
              <video src={mediaUrl(m.id)} poster={m.thumb ? `${api.defaults.baseURL}/media/${m.id}/thumb` : undefined} muted preload="metadata" />
            ) : m.mime?.startsWith("audio/") ? (
              <div style={{ display: "grid", placeItems: "center", height: "100%", fontSize: 48 }}>🎵</div>
            ) : m.mime === "application/pdf" ? (
              <div style={{ display: "grid", placeItems: "center", height: "100%", fontSize: 48 }}>📄</div>
            ) : m.mime?.startsWith("image/") ? (
              <MediaThumb id={m.id} title={m.title || ""} />
            ) : (
              <div style={{ display: "grid", placeItems: "center", height: "100%", fontSize: 48 }}>📎</div>
            )}
            {m.is_featured && (
              <div style={{ position: "absolute", top: 6, left: 6, padding: "2px 7px", background: "var(--gold)", color: "#000", fontSize: 10, fontWeight: 700, borderRadius: 5 }}>★ FEATURED</div>
            )}
            {isReel && (
              /* Iter 76.5 — Featured Reel badge (hero autoplay video). */
              <div data-testid={`reel-badge-${m.id}`} style={{ position: "absolute", top: 6, right: 6, padding: "2px 7px", background: "linear-gradient(135deg,#6a3ad4,#d4af37)", color: "#fff", fontSize: 10, fontWeight: 700, borderRadius: 5 }}>🎬 REEL</div>
            )}
            <div className="media-tile-overlay" style={{ opacity: 1, background: "linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent 60%)", padding: 6, flexDirection: "column", gap: 4 }}>
              <div className="flex gap-4" style={{ width: "100%", justifyContent: "space-between" }}>
                <button className="btn btn-ghost btn-xs" onClick={(e) => { e.stopPropagation(); move(idx, -1); }} title="Move left" data-testid={`move-left-${m.id}`} disabled={idx === 0}>←</button>
                <button className="btn btn-ghost btn-xs" onClick={(e) => { e.stopPropagation(); move(idx, 1); }} title="Move right" data-testid={`move-right-${m.id}`} disabled={idx === galleryItems.length - 1}>→</button>
              </div>
              <div className="flex gap-4" style={{ width: "100%" }}>
                <button
                  className={`btn btn-xs ${m.is_featured ? "btn-gold" : "btn-ghost"}`}
                  onClick={(e) => { e.stopPropagation(); toggleFeatured(m.id); }}
                  data-testid={`feature-${m.id}`}
                  title={m.is_featured ? "Unfeature" : "Set as featured"}
                  style={{ flex: 1 }}
                >★</button>
                <button
                  className="btn btn-ghost btn-xs"
                  onClick={(e) => { e.stopPropagation(); replaceRefs.current[m.id]?.click(); }}
                  data-testid={`replace-${m.id}`}
                  title="Replace"
                  style={{ flex: 1 }}
                >↻</button>
                <input
                  ref={(el) => { if (el) replaceRefs.current[m.id] = el; }}
                  type="file" accept="image/*,video/*,audio/*,application/pdf"
                  style={{ display: "none" }}
                  onChange={(e) => replace(m.id, e.target.files[0])}
                />
                <button className="btn btn-red btn-xs" onClick={(e) => { e.stopPropagation(); del(m.id); }} data-testid={`del-media-${m.id}`} title="Delete" style={{ flex: 1 }}>✕</button>
              </div>
              {/* Iter 76.5 — Featured Reel toggle (videos only). */}
              {isVideo && (
                <button
                  className={`btn btn-xs ${isReel ? "btn-gold" : "btn-ghost"}`}
                  style={{ width: "100%" }}
                  data-testid={`reel-toggle-${m.id}`}
                  onClick={async (e) => {
                    e.stopPropagation();
                    try {
                      const r = await api.post(`/media/${m.id}/feature-reel`);
                      toast(r.data.featured_video_id ? "Set as Featured Reel 🎬" : "Removed from Reel");
                      await refresh();
                    } catch (err) { toast(formatApiError(err), "error"); }
                  }}
                  title="Featured Reel autoplays muted at the top of your public profile"
                >{isReel ? "🎬 Reel Active" : "🎬 Set as Reel"}</button>
              )}
            </div>
          </div>
        );})}
      </div>
    </div>
  );
}

function Availability({ refresh, toast }) {
  const [dates, setDates] = useState([]);
  const [date, setDate] = useState("");
  const [status, setStatus] = useState("blocked");
  useEffect(() => { api.get("/availability/mine").then((r) => setDates(r.data)); }, []);
  const save = async () => {
    if (!date) return;
    await api.post("/availability", { date, status });
    toast("Updated");
    api.get("/availability/mine").then((r) => setDates(r.data));
  };
  return (
    <div className="card card-pad" data-testid="availability-tab">
      <h2 className="font-serif fs-20 fw-700 mb-16">Block / Free Dates</h2>
      <div className="flex gap-12 mb-16" style={{ alignItems: "end" }}>
        <div className="field" style={{ marginBottom: 0, flex: 1 }}>
          <div className="field-label">Date</div>
          <input type="date" className="field-input" value={date} onChange={(e) => setDate(e.target.value)} data-testid="avail-date" />
        </div>
        <div className="field" style={{ marginBottom: 0, flex: 1 }}>
          <div className="field-label">Status</div>
          <select className="field-input" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="avail-status">
            <option value="available">Available</option>
            <option value="blocked">Blocked</option>
          </select>
        </div>
        <button className="btn btn-gold" onClick={save} data-testid="avail-save">Save</button>
      </div>
      <h3 className="fs-13 fw-600 mb-12 text-muted">Existing Entries</h3>
      <div className="grid grid-4">
        {dates.map((d) => (
          <div key={d.id} className="card card-pad text-center" data-testid={`avail-${d.date}`}>
            <div className="fw-600">{d.date}</div>
            <div className={`pill ${d.status === "available" ? "pill-green" : d.status === "blocked" ? "pill-red" : "pill-amber"} mt-8`}>{d.status}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ArtistBookings({ data, doAction }) {
  const [filter, setFilter] = useState("all");
  const list = filter === "all" ? data.bookings : data.bookings.filter(b => {
    if (filter === "pending") return b.status === "pending_artist";
    if (filter === "confirmed") return ["confirmed", "started"].includes(b.status);
    if (filter === "completed") return ["completed", "reviewed", "completed_by_artist"].includes(b.status);
    return b.status === filter;
  });
  return (
    <div data-testid="bookings-tab">
      <div className="tab-bar mb-16">
        {["all", "pending", "confirmed", "completed"].map(f => (
          <button key={f} className={`tab-btn ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)} data-testid={`booking-filter-${f}`}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>
      <div className="card">
        <BookingsTable bookings={list} role="artist" onAction={doAction} />
      </div>
    </div>
  );
}

function Reviews({ data, refresh, toast }) {
  const [reply, setReply] = useState({});
  const sendReply = async (rid) => {
    try {
      await api.post(`/reviews/${rid}/reply`, { reply: reply[rid] });
      toast("Reply sent");
      setReply({});
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };
  return (
    <div className="card card-pad" data-testid="reviews-tab">
      <h2 className="font-serif fs-20 fw-700 mb-16">Client Reviews</h2>
      {data.reviews.length === 0 && <div className="empty"><div className="empty-icon">⭐</div><div className="empty-title">No reviews yet</div></div>}
      {data.reviews.map((r) => (
        <div key={r.id} className="card card-pad mb-12" data-testid={`review-${r.id}`}>
          <div className="flex justify-between mb-8">
            <div>
              <div className="fw-600">{r.customer_name}</div>
              <div className="text-muted fs-11">{r.event_type} · {r.created_at?.slice(0, 10)}</div>
            </div>
            <div className="text-gold">{"★".repeat(r.rating)}</div>
          </div>
          <div className="fs-13 mb-12">{r.text}</div>
          {r.reply ? (
            <div style={{ padding: 12, background: "rgba(109,40,217,0.08)", borderRadius: 10 }}>
              <div className="text-muted fs-11 mb-4">Your reply:</div>
              <div className="fs-13">{r.reply}</div>
            </div>
          ) : (
            <div className="flex gap-8">
              <input className="field-input" placeholder="Reply to this review…" value={reply[r.id] || ""} onChange={(e) => setReply({ ...reply, [r.id]: e.target.value })} data-testid={`reply-${r.id}`} />
              <button className="btn btn-gold btn-sm" onClick={() => sendReply(r.id)} disabled={!reply[r.id]}>Reply</button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Boost({ refresh, toast }) {
  const [packages, setPackages] = useState([]);
  const [mine, setMine] = useState([]);
  const [busy, setBusy] = useState(null);
  const [filter, setFilter] = useState("all");
  // Iter 76.5 — Boost insights: 14-day views & bookings + active windows.
  const [insights, setInsights] = useState(null);

  const load = async () => {
    const [p, m, ins] = await Promise.all([
      api.get("/boost/packages"),
      api.get("/boost/mine"),
      api.get("/boost/insights").catch(() => ({ data: null })),
    ]);
    setPackages(p.data);
    setMine(m.data);
    setInsights(ins.data);
  };
  useEffect(() => { load(); }, []);

  const purchase = async (pkg) => {
    const total = (pkg.price * (1 + (pkg.gst_pct || 18) / 100)).toFixed(2);
    if (!window.confirm(`Continue to secure payment for ${pkg.name} — ₹${total} (incl. GST)?`)) return;
    setBusy(pkg.id);
    try {
      const r = await api.post("/boost/easebuzz/init", { package_id: pkg.id });
      if (r.data?.payment_url) {
        window.location.href = r.data.payment_url;
        return;
      }
      toast("Could not start payment. Please try again.", "error");
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(null);
  };

  const TYPE_LABELS = {
    featured_artist: "⭐ Featured Artist",
    homepage_banner: "🏆 Homepage Banner",
    category_top: "👑 Category Top",
    search_priority: "🚀 Search Priority",
    premium_badge: "💎 Premium Badge",
    verified_badge: "✓ Verified Badge",
    city_featured: "🏙️ City Featured",
    trending: "🔥 Trending",
    recommended: "👍 Recommended",
  };

  const types = ["all", ...Object.keys(TYPE_LABELS)];
  const filtered = filter === "all" ? packages : packages.filter((p) => p.type === filter);
  const activeSubs = mine.filter((s) => s.status === "active");

  return (
    <div data-testid="boost-tab">
      <div className="flex items-center" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 className="font-serif fs-20 fw-700">Boost Your Profile</h2>
          <p className="text-muted fs-13">Premium promotion packages — pay once, get visibility for days.</p>
        </div>
        {activeSubs.length > 0 && (
          <div className="pill pill-gold" data-testid="active-boost-count">{activeSubs.length} Active Boost{activeSubs.length > 1 ? "s" : ""}</div>
        )}
      </div>

      {activeSubs.length > 0 && (
        <div className="card card-pad mb-16" data-testid="active-boosts">
          <div className="fw-700 mb-8">Your Active Boosts</div>
          <div className="grid grid-3 gap-12">
            {activeSubs.map((s) => (
              <div key={s.id} className="card card-pad" style={{ background: "var(--glass)" }}>
                <div className="text-gold fw-700">{TYPE_LABELS[s.type] || s.type}</div>
                <div className="fs-12">{s.package_snapshot?.name}</div>
                <div className="text-muted fs-11 mt-4">Expires {s.expires_at?.slice(0, 10)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Iter 76.5 — Boost Insights: 14-day mini bar-chart of profile
          views + booking requests so artists see the ROI of their
          active promotions. Renders as pure CSS bars — no charting
          library dependency. */}
      {insights && insights.days && insights.days.length > 0 && (
        <div className="card card-pad mb-16" data-testid="boost-insights">
          <div className="flex justify-between items-center mb-8">
            <div className="fw-700">📊 Last 14 Days · Boost Impact</div>
            <div className="fs-12 text-muted">
              <span data-testid="insight-views-14d">{insights.totals?.views_14d ?? 0}</span> views ·{" "}
              <span data-testid="insight-bookings-14d">{insights.totals?.bookings_14d ?? 0}</span> booking requests
            </div>
          </div>
          {(() => {
            const maxV = Math.max(1, ...insights.days.map((d) => d.views));
            const maxB = Math.max(1, ...insights.days.map((d) => d.bookings));
            return (
              <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 96, marginTop: 6 }} data-testid="insights-chart">
                {insights.days.map((d) => (
                  <div key={d.date} title={`${d.date} · ${d.views} views · ${d.bookings} bookings`}
                    style={{ flex: 1, display: "flex", flexDirection: "column-reverse", alignItems: "stretch", gap: 2, minWidth: 12 }}>
                    <div style={{ height: `${(d.views / maxV) * 66}px`, background: "linear-gradient(180deg,#d4af37,rgba(212,175,55,0.35))", borderRadius: "3px 3px 0 0", minHeight: d.views ? 2 : 0 }} />
                    <div style={{ height: `${(d.bookings / maxB) * 26}px`, background: "linear-gradient(180deg,#6a3ad4,rgba(106,58,212,0.45))", borderRadius: "3px 3px 0 0", minHeight: d.bookings ? 2 : 0 }} />
                  </div>
                ))}
              </div>
            );
          })()}
          <div style={{ display: "flex", gap: 12, marginTop: 10, fontSize: 11, color: "var(--white-muted, rgba(255,255,255,0.6))" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 10, height: 10, background: "#d4af37", borderRadius: 2 }} /> Profile Views
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 10, height: 10, background: "#6a3ad4", borderRadius: 2 }} /> Booking Requests
            </span>
          </div>
        </div>
      )}

      <div className="flex gap-8 mb-16" style={{ flexWrap: "wrap", marginBottom: 16 }}>
        {types.map((t) => (
          <button key={t} className={`btn btn-xs ${filter === t ? "btn-gold" : "btn-ghost"}`} onClick={() => setFilter(t)} data-testid={`boost-filter-${t}`}>
            {t === "all" ? "All" : TYPE_LABELS[t]}
          </button>
        ))}
      </div>

      <div className="grid grid-3 gap-16">
        {filtered.length === 0 && <div className="text-muted">No packages available.</div>}
        {filtered.map((p) => {
          const total = (p.price + p.price * p.gst_pct / 100).toFixed(0);
          return (
            <div key={p.id} className="pkg-card" data-testid={`pkg-${p.id}`}>
              <div className="text-muted fs-11 mb-4" style={{ marginBottom: 4 }}>{TYPE_LABELS[p.type] || p.type}</div>
              <div className="pkg-name">{p.name}</div>
              <div className="pkg-price">{fmtINRFull(p.price)}</div>
              <div className="text-muted fs-12 mb-12">+ {p.gst_pct}% GST = {fmtINRFull(total)}</div>
              <div className="fs-12 mb-8" style={{ marginBottom: 8 }}>⏱️ {p.duration_days} days</div>
              {p.description && <div className="text-muted fs-12 mb-12">{p.description}</div>}
              {p.type === "homepage_banner" && (
                <div className="text-muted fs-11" style={{ marginBottom: 10, padding: 8, background: "rgba(212,175,55,0.08)", borderRadius: 8, borderLeft: "2px solid var(--gold)" }}>
                  🏆 Your profile card will appear in the <b>hero spotlight on the homepage</b> — right next to the "Book India's Finest Talent" headline.
                </div>
              )}
              <button className="btn btn-gold btn-block mt-16" onClick={() => purchase(p)} disabled={busy === p.id} data-testid={`purchase-${p.id}`}>
                {busy === p.id ? "Activating..." : "Activate"}
              </button>
            </div>
          );
        })}
      </div>

      {mine.length > activeSubs.length && (
        <div className="card card-pad mt-24" style={{ marginTop: 24 }}>
          <div className="fw-700 mb-12">Past Subscriptions</div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Package</th><th>Started</th><th>Expired</th><th>Status</th></tr></thead>
              <tbody>
                {mine.filter((s) => s.status !== "active").map((s) => (
                  <tr key={s.id}>
                    <td>{s.package_snapshot?.name}</td>
                    <td className="fs-12">{s.starts_at?.slice(0, 10)}</td>
                    <td className="fs-12">{s.expires_at?.slice(0, 10)}</td>
                    <td><span className="pill pill-amber">{s.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function KycProgressBar() {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get("/kyc/pipeline").then((r) => setData(r.data)).catch(() => setData(null));
  }, []);
  if (!data) return null;

  return (
    <div className="card card-pad mb-16" data-testid="kyc-progress">
      <div className="flex-between mb-12">
        <div>
          <h3 className="font-serif fw-700 mb-4">Your artist onboarding journey</h3>
          <div className="text-muted fs-13">
            {data.is_error ? (
              <span className="text-red">⚠ {data.error_reason}</span>
            ) : (
              (data.stages.find((s) => s.status === "current") || {}).action
              || "Getting you live on BookTalent."
            )}
          </div>
        </div>
        {data.agreement_url && (
          <a className="btn btn-ghost btn-sm" href={data.agreement_url} target="_blank" rel="noopener noreferrer" data-testid="kyc-agreement-dl">
            ⬇ Agreement
          </a>
        )}
      </div>

      {/* Progress rail */}
      <div style={{ position: "relative", padding: "8px 0" }}>
        {/* Base line */}
        <div style={{
          position: "absolute", top: 21, left: 12, right: 12, height: 3,
          background: "rgba(255,255,255,0.08)", borderRadius: 2, zIndex: 0,
        }} />
        {/* Fill line — up to current step */}
        <div style={{
          position: "absolute", top: 21, left: 12,
          width: `calc((100% - 24px) * ${data.step_index / Math.max(1, data.stages.length - 1)})`,
          height: 3,
          background: data.is_error
            ? "linear-gradient(90deg,#D4AF37,#e57373)"
            : "linear-gradient(90deg,#D4AF37,#6ee7a8)",
          borderRadius: 2, zIndex: 1, transition: "width 500ms ease",
        }} />
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${data.stages.length}, 1fr)`, gap: 4, position: "relative", zIndex: 2 }}>
          {data.stages.map((s, i) => {
            const isDone = s.status === "done";
            const isCurrent = s.status === "current";
            const isPending = s.status === "pending";
            const err = data.is_error && isCurrent;
            return (
              <div key={s.id} className="text-center" data-testid={`kyc-stage-${s.id}`}>
                {/* Dot */}
                <div style={{
                  width: 42, height: 42, borderRadius: "50%",
                  background: err ? "#e57373"
                              : isDone ? "#6ee7a8"
                              : isCurrent ? "#D4AF37"
                              : "rgba(255,255,255,0.05)",
                  color: (isDone || isCurrent || err) ? "#0F0F1B" : "rgba(255,255,255,0.35)",
                  border: isCurrent ? "3px solid rgba(212,175,55,0.35)" : "2px solid rgba(255,255,255,0.08)",
                  boxShadow: isCurrent ? "0 0 0 4px rgba(212,175,55,0.12)" : "none",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 16, fontWeight: 700, margin: "0 auto",
                  transition: "all 300ms ease",
                }}>
                  {isDone ? "✓" : err ? "!" : i + 1}
                </div>
                {/* Label */}
                <div style={{
                  marginTop: 8, fontSize: 11, fontWeight: isCurrent ? 700 : 500,
                  color: isCurrent ? "#D4AF37"
                          : isDone ? "rgba(255,255,255,0.85)"
                          : "rgba(255,255,255,0.4)",
                  textTransform: isPending ? "none" : "uppercase",
                  letterSpacing: isCurrent ? ".08em" : "0",
                  lineHeight: 1.3,
                }}>
                  {s.label}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}


function KYC({ toast, refresh }) {
  const [aadhaarFile, setAadhaarFile] = useState("");
  const [panFile, setPanFile] = useState("");
  const [bankFile, setBankFile] = useState("");
  const [selfieFile, setSelfieFile] = useState("");
  const [aadhaarNo, setAadhaarNo] = useState("");
  const [panNo, setPanNo] = useState("");
  const [fullName, setFullName] = useState("");
  const [dob, setDob] = useState("");
  const [kyc, setKyc] = useState(null);
  const [busy, setBusy] = useState(false);

  const reload = () => api.get("/kyc/mine").then((r) => setKyc(r.data));
  useEffect(() => { reload(); }, []);

  const upload = async (file, setter) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast("File too large (max 5 MB)", "error"); return; }
    const allowed = ["image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"];
    if (!allowed.includes(file.type)) { toast("Only JPG / PNG / WEBP / PDF allowed", "error"); return; }
    const r = new FileReader();
    r.onload = () => setter(r.result);
    r.readAsDataURL(file);
  };

  const validate = () => {
    if (!aadhaarFile && !panFile) return "Upload at least one identity document (Aadhaar or PAN)";
    const aaNum = aadhaarNo.replace(/\s/g, "");
    if (aadhaarFile && !/^\d{12}$/.test(aaNum)) return "Aadhaar number must be exactly 12 digits";
    if (panFile && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(panNo.toUpperCase())) return "PAN must be in format ABCDE1234F";
    return null;
  };

  const submit = async () => {
    const err = validate();
    if (err) { toast(err, "error"); return; }
    setBusy(true);
    try {
      await api.post("/kyc/submit", {
        full_name: fullName, dob,
        aadhaar_number: aadhaarNo.replace(/\s/g, ""), pan_number: panNo.toUpperCase(),
        aadhaar: aadhaarFile, pan: panFile,
        bank_proof: bankFile, selfie: selfieFile,
      });
      toast("KYC submitted for review");
      reload();
      refresh && refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const status = kyc?.status;
  const isLocked = status === "pending" || status === "approved";

  return (
    <div className="card card-pad" data-testid="kyc-tab">
      {/* Iter 90b — full 9-stage progress bar so artists see where they are */}
      <KycProgressBar />

      <h2 className="font-serif fs-20 fw-700 mb-8">KYC Verification</h2>
      <p className="text-muted fs-13 mb-20">Verify your identity to unlock payouts, the Verified Badge, and premium features.</p>

      {status && (
        <div className="mb-16">
          <div className={`pill ${status === "approved" ? "pill-green" : status === "rejected" ? "pill-red" : status === "needs_resubmission" ? "pill-amber" : "pill-purple"}`} data-testid="kyc-status">
            Status: {status.replace(/_/g, " ")}
          </div>
          {kyc.reason && (status === "rejected" || status === "needs_resubmission") && (
            <div className="text-muted fs-13 mt-8" data-testid="kyc-reason">Reason: {kyc.reason}</div>
          )}
          {status === "approved" && <div className="text-muted fs-13 mt-8">✓ Verified Badge active on your profile</div>}
        </div>
      )}

      {isLocked ? (
        <div className="empty">
          <div className="empty-title">{status === "approved" ? "You're verified!" : "Review in progress"}</div>
          <p className="text-muted">{status === "approved" ? "Your KYC has been approved." : "Our team will review your submission within 24-48 hours."}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-2 gap-12 mb-12" style={{ marginBottom: 12 }}>
            <div className="field">
              <div className="field-label">Full Name (as per Aadhaar)</div>
              <input className="field-input" placeholder="e.g. Priya Sharma" value={fullName} onChange={(e) => setFullName(e.target.value)} data-testid="kyc-name" />
            </div>
            <div className="field">
              <div className="field-label">Date of Birth</div>
              <input type="date" className="field-input" value={dob} onChange={(e) => setDob(e.target.value)} data-testid="kyc-dob" />
            </div>
          </div>

          <div className="field">
            <div className="field-label">Aadhaar Number (12 digits)</div>
            <input className="field-input" placeholder="1234 5678 9012" maxLength={14} value={aadhaarNo} onChange={(e) => setAadhaarNo(e.target.value)} data-testid="kyc-aadhaar-no" />
          </div>
          <div className="field">
            <div className="field-label">Aadhaar Document (JPG/PNG/PDF, max 5 MB)</div>
            <input type="file" accept="image/*,application/pdf" onChange={(e) => upload(e.target.files[0], setAadhaarFile)} data-testid="kyc-aadhaar" />
            {aadhaarFile && <div className="pill pill-green mt-8" style={{ marginTop: 8 }}>✓ Aadhaar file selected</div>}
          </div>

          <div className="field">
            <div className="field-label">PAN Number</div>
            <input className="field-input" placeholder="ABCDE1234F" maxLength={10} value={panNo} onChange={(e) => setPanNo(e.target.value.toUpperCase())} data-testid="kyc-pan-no" />
          </div>
          <div className="field">
            <div className="field-label">PAN Document</div>
            <input type="file" accept="image/*,application/pdf" onChange={(e) => upload(e.target.files[0], setPanFile)} data-testid="kyc-pan" />
            {panFile && <div className="pill pill-green mt-8" style={{ marginTop: 8 }}>✓ PAN file selected</div>}
          </div>

          <div className="field">
            <div className="field-label">Bank Proof — Cancelled Cheque / Passbook (optional)</div>
            <input type="file" accept="image/*,application/pdf" onChange={(e) => upload(e.target.files[0], setBankFile)} data-testid="kyc-bank" />
            {bankFile && <div className="pill pill-green mt-8" style={{ marginTop: 8 }}>✓ Bank proof selected</div>}
          </div>

          <div className="field">
            <div className="field-label">Live Selfie (optional but recommended)</div>
            <input type="file" accept="image/*" capture="user" onChange={(e) => upload(e.target.files[0], setSelfieFile)} data-testid="kyc-selfie" />
            {selfieFile && <div className="pill pill-green mt-8" style={{ marginTop: 8 }}>✓ Selfie selected</div>}
          </div>

          <button className="btn btn-gold" disabled={busy} onClick={submit} data-testid="kyc-submit">
            {busy ? "Submitting..." : status === "needs_resubmission" ? "Resubmit for Review" : "Submit for Review"}
          </button>
        </>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Sprint 5 — Premium Subscription (Free / Silver / Gold / Platinum / Elite)
// ────────────────────────────────────────────────────────────────────────
const PLAN_STYLE = {
  free:     { bg: "linear-gradient(135deg, #64748b, #475569)", accent: "#94a3b8", icon: "🎫" },
  silver:   { bg: "linear-gradient(135deg, #cbd5e1, #94a3b8)", accent: "#e2e8f0", icon: "🥈" },
  gold:     { bg: "linear-gradient(135deg, #fbbf24, #d4af37)", accent: "#fde68a", icon: "🥇" },
  platinum: { bg: "linear-gradient(135deg, #a78bfa, #7c3aed)", accent: "#c4b5fd", icon: "💎" },
  elite:    { bg: "linear-gradient(135deg, #f472b6, #d4af37)", accent: "#fbcfe8", icon: "👑" },
};

function Subscription({ toast, highlight, onHighlightConsumed }) {
  const [plans, setPlans] = useState([]);
  const [current, setCurrent] = useState(null);
  const [cycle, setCycle] = useState("monthly");
  const [busy, setBusy] = useState(false);
  const highlightRef = useRef(null);

  const refresh = async () => {
    try {
      const [p, me] = await Promise.all([api.get("/subscriptions/plans"), api.get("/subscriptions/me")]);
      setPlans(p.data);
      setCurrent(me.data);
    } catch (e) { toast(formatApiError(e), "error"); }
  };
  useEffect(() => { refresh(); }, []); // eslint-disable-line

  // Iter 63.1 — When the user arrives from the Concierge paywall we scroll to
  // the highlighted plan card so the value is obvious with zero extra clicks.
  useEffect(() => {
    if (!highlight || !plans.length) return;
    const t = setTimeout(() => {
      highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      if (onHighlightConsumed) setTimeout(() => onHighlightConsumed(), 3200);
    }, 250);
    return () => clearTimeout(t);
  }, [highlight, plans.length]); // eslint-disable-line

  const subscribe = async (planCode) => {
    if (busy) return;
    if (planCode === current?.plan?.code) return;
    setBusy(true);
    try {
      if (planCode === "free") {
        // Direct downgrade — no payment involved.
        if (!window.confirm("Downgrade to Free plan?")) { setBusy(false); return; }
        await api.post("/subscriptions/subscribe", { plan: "free" });
        toast("Downgraded to Free");
        refresh();
      } else {
        // Iter 63.3 — Paid plans route through Easebuzz hosted checkout.
        if (!window.confirm(`Continue to secure payment for ${planCode.toUpperCase()} (${cycle})?`)) {
          setBusy(false); return;
        }
        const r = await api.post("/subscriptions/easebuzz/init", { plan: planCode, billing_cycle: cycle });
        if (r.data?.payment_url) {
          window.location.href = r.data.payment_url;
          return;
        }
        toast("Could not start payment. Please try again.", "error");
      }
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const currentCode = current?.plan?.code || "free";

  return (
    <div data-testid="subscription-tab">
      <div className="flex justify-between mb-16" style={{ flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 className="font-serif fs-20 fw-700">💎 Premium Subscription</h2>
          <p className="text-muted fs-13">Unlock premium visibility, higher search ranking, priority support and richer profile perks.</p>
        </div>
        <div className="flex items-center gap-8" data-testid="billing-cycle-toggle">
          <button className={`btn btn-xs ${cycle === "monthly" ? "btn-gold" : "btn-ghost"}`} onClick={() => setCycle("monthly")} data-testid="cycle-monthly">Monthly</button>
          <button className={`btn btn-xs ${cycle === "yearly" ? "btn-gold" : "btn-ghost"}`} onClick={() => setCycle("yearly")} data-testid="cycle-yearly">Yearly (save ~17%)</button>
        </div>
      </div>

      {current?.subscription && (
        <div className="card card-pad mb-24" style={{ background: PLAN_STYLE[currentCode]?.bg, color: "#0b0616" }} data-testid="current-plan-banner">
          <div className="flex justify-between items-center" style={{ flexWrap: "wrap" }}>
            <div>
              <div className="fs-13" style={{ opacity: 0.85 }}>Currently on</div>
              <div className="font-serif fs-24 fw-700">{PLAN_STYLE[currentCode]?.icon} {current.plan.name}</div>
              {current.subscription.expires_at && <div className="fs-12">Renews on {current.subscription.expires_at.slice(0, 10)}</div>}
            </div>
            {currentCode !== "free" && (
              <button className="btn btn-ghost btn-sm" style={{ background: "rgba(0,0,0,0.15)" }} onClick={() => subscribe("free")} data-testid="cancel-plan-btn">Downgrade to Free</button>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-3 gap-16">
        {plans.map((p) => {
          const style = PLAN_STYLE[p.code] || PLAN_STYLE.free;
          const isCurrent = p.code === currentCode;
          const price = cycle === "yearly" ? p.price_yearly : p.price_monthly;
          const isHighlighted = highlight === p.code;
          return (
            <div
              key={p.code}
              ref={isHighlighted ? highlightRef : null}
              className={`pkg-card ${isCurrent ? "selected" : ""} ${isHighlighted ? "concierge-highlight" : ""}`}
              data-testid={`plan-card-${p.code}`}
              style={isHighlighted ? {
                position: "relative",
                border: "2px solid #D4AF37",
                boxShadow: "0 0 0 3px rgba(212,175,55,0.18), 0 24px 60px rgba(212,175,55,0.35)",
                animation: "conciergePulse 2s ease-in-out infinite",
              } : undefined}
            >
              {isHighlighted && (
                <div style={{
                  position: "absolute", top: -14, left: 12,
                  background: "linear-gradient(135deg,#D4AF37,#F1D17A)",
                  color: "#0b0616", padding: "4px 12px", borderRadius: 999,
                  fontSize: 11, fontWeight: 800, letterSpacing: 0.4,
                  boxShadow: "0 6px 16px rgba(212,175,55,0.4)",
                }}>
                  ✨ RECOMMENDED FOR CONCIERGE
                </div>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: style.bg, display: "grid", placeItems: "center", fontSize: 22 }}>{style.icon}</div>
                <div>
                  <div className="fw-700 font-serif fs-18">{p.name}</div>
                  {p.badge && <div className="text-muted fs-11">{p.badge} badge</div>}
                </div>
              </div>
              <div className="pkg-price" style={{ fontSize: 28 }}>{price === 0 ? "Free" : fmtINRFull(price)}</div>
              <div className="text-muted fs-11 mb-12">{price === 0 ? "forever" : `per ${cycle === "yearly" ? "year" : "month"}`}</div>
              <ul className="pkg-features">
                <li>Up to {p.features.max_media} media uploads</li>
                <li>Up to {p.features.max_addons} add-ons</li>
                <li>{p.features.response_sla_hours}h response SLA</li>
                <li>{Math.round(p.features.boost_multiplier * 100)}% search-rank boost</li>
                {p.features.verified_badge && <li>✓ Verified badge</li>}
                {p.features.priority_support && <li>⚡ Priority support</li>}
                {p.features.elite_rail && <li>💎 Elite homepage rail</li>}
                {p.features.commission_discount_pct > 0 && <li>{p.features.commission_discount_pct}% commission discount</li>}
              </ul>
              <button
                className={`btn ${isCurrent ? "btn-ghost" : "btn-gold"} btn-block mt-16`}
                disabled={isCurrent || busy}
                onClick={() => subscribe(p.code)}
                data-testid={`subscribe-${p.code}`}
              >
                {isCurrent ? "✓ Current Plan" : p.code === "free" ? "Downgrade" : `Upgrade to ${p.name}`}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// Elite Concierge Chat — Platinum + Elite priority support channel
// ────────────────────────────────────────────────────────────────────────
function Concierge({ toast, setTab, setSubHighlight }) {
  const [thread, setThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [locked, setLocked] = useState(false);
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("General");
  const [firstMessage, setFirstMessage] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  const refresh = async () => {
    try {
      const r = await api.get("/concierge/messages");
      setThread(r.data.thread);
      setMessages(r.data.messages || []);
      setLocked(false);
      setTimeout(() => {
        if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
      }, 50);
    } catch (e) {
      if (e.response?.status === 403) {
        setLocked(true);
      } else {
        toast(formatApiError(e), "error");
      }
    }
  };

  useEffect(() => {
    refresh();
    // Poll every 12s for new admin replies
    const iv = setInterval(() => { if (!locked) refresh(); }, 12000);
    return () => clearInterval(iv);
    // eslint-disable-next-line
  }, [locked]);

  const openThread = async () => {
    if (!firstMessage.trim()) return;
    setSending(true);
    try {
      await api.post("/concierge/open", { subject, first_message: firstMessage });
      setFirstMessage("");
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
    setSending(false);
  };

  const send = async () => {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      await api.post("/concierge/send", { body: text });
      setText("");
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
    setSending(false);
  };

  if (locked) {
    return (
      <div className="card card-pad text-center" data-testid="concierge-locked" style={{ padding: 40 }}>
        <div style={{ fontSize: 42, marginBottom: 12 }}>🎩</div>
        <h2 className="font-serif fs-24 fw-700 mb-8">Elite Concierge</h2>
        <p className="text-muted mb-16">Priority support with a 2-6 hour SLA is a benefit reserved for <b>Platinum</b> and <b>Elite</b> plans.</p>

        <button
          className="btn btn-gold"
          onClick={() => {
            if (setSubHighlight) setSubHighlight("elite");
            if (setTab) setTab("subscription");
          }}
          data-testid="concierge-upgrade-cta"
        >
          Upgrade to Unlock 🚀
        </button>
      </div>
    );
  }

  return (
    <div data-testid="concierge-tab">
      <div className="mb-16">
        <h2 className="font-serif fs-20 fw-700">🎩 Elite Concierge</h2>
        <p className="text-muted fs-13">Direct line to our support team — replies within your plan SLA.</p>
      </div>

      {!thread ? (
        <div className="card card-pad" data-testid="concierge-open-form">
          <h3 className="fw-600 mb-12">Start a new conversation</h3>
          <div className="field"><div className="field-label">Subject</div>
            <select className="field-input" value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="concierge-subject">
              <option>General</option>
              <option>Payout question</option>
              <option>Booking dispute</option>
              <option>Profile / KYC help</option>
              <option>Feature request</option>
              <option>Report a bug</option>
            </select>
          </div>
          <div className="field"><div className="field-label">Message</div>
            <textarea className="field-input" rows={4} value={firstMessage} onChange={(e) => setFirstMessage(e.target.value)} placeholder="Tell us how we can help…" data-testid="concierge-first-msg" />
          </div>
          <button className="btn btn-gold" disabled={!firstMessage.trim() || sending} onClick={openThread} data-testid="concierge-open-btn">Open Conversation</button>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, display: "flex", flexDirection: "column", height: "60vh", minHeight: 480 }} data-testid="concierge-chat">
          <div style={{ padding: 14, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="flex justify-between items-center">
              <div>
                <div className="fw-700">{thread.subject}</div>
                <div className="text-muted fs-12">Priority: <span className="text-gold fw-600">{thread.plan.toUpperCase()}</span> · {thread.status === "open" ? "🟢 Open" : "⚪ Closed"}</div>
              </div>
            </div>
          </div>
          <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: 14 }} data-testid="concierge-messages">
            {messages.length === 0 ? (
              <div className="text-muted text-center" style={{ marginTop: 40 }}>Waiting for a reply…</div>
            ) : messages.map((m) => (
              <div key={m.id} style={{
                marginBottom: 12,
                display: "flex",
                justifyContent: m.sender_role === "artist" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: "72%",
                  padding: "10px 14px",
                  borderRadius: 14,
                  background: m.sender_role === "artist" ? "linear-gradient(135deg,#d4af37,#fbbf24)" : "rgba(255,255,255,0.08)",
                  color: m.sender_role === "artist" ? "#0b0616" : "#fff",
                }} data-testid={`concierge-msg-${m.id}`}>
                  <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.7, marginBottom: 4 }}>
                    {m.sender_role === "admin" ? "🎩 BookTalent Support" : "You"}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>
                  <div style={{ fontSize: 9, opacity: 0.6, marginTop: 4, textAlign: "right" }}>{new Date(m.created_at).toLocaleString()}</div>
                </div>
              </div>
            ))}
          </div>
          {thread.status === "open" ? (
            <div style={{ padding: 12, borderTop: "1px solid rgba(255,255,255,0.06)", display: "flex", gap: 8 }}>
              <textarea
                className="field-input"
                style={{ flex: 1, minHeight: 44, maxHeight: 120, resize: "vertical" }}
                placeholder="Type a message…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                data-testid="concierge-input"
              />
              <button className="btn btn-gold" onClick={send} disabled={!text.trim() || sending} data-testid="concierge-send">Send</button>
            </div>
          ) : (
            <div className="text-muted text-center" style={{ padding: 16 }}>This conversation is closed. Start a new one from the Overview tab.</div>
          )}
        </div>
      )}
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// 📈 Insights — Artist self-service analytics dashboard
// ────────────────────────────────────────────────────────────────────────
function Insights({ toast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [spotStats, setSpotStats] = useState(null);
  const { user } = useAuth();

  useEffect(() => {
    api.get("/artist/insights").then((r) => setData(r.data)).catch((e) => toast(formatApiError(e), "error")).finally(() => setLoading(false));
    if (user?.id) {
      api.get(`/artist/analytics/spotlight/${user.id}`).then((r) => setSpotStats(r.data)).catch(() => {});
    }
  }, []); // eslint-disable-line

  if (loading) return <div className="loading"><div className="spinner" /></div>;
  if (!data) return <div className="empty"><div className="empty-icon">📈</div><div className="empty-title">Insights unavailable</div></div>;

  const f = data.funnel || {};
  const rev = data.revenue || {};
  const maxCity = Math.max(1, ...(data.top_cities || []).map((c) => c.count));
  const maxEt = Math.max(1, ...(data.top_event_types || []).map((c) => c.count));

  return (
    <div data-testid="insights-tab">
      <div className="mb-16">
        <h2 className="font-serif fs-20 fw-700">📈 Insights</h2>
        <p className="text-muted fs-13">See where demand is coming from, and how well your profile converts.</p>
      </div>

      {/* Iter 45 — Homepage Banner spotlight ROI card */}
      {spotStats && (spotStats.total_impressions > 0 || spotStats.last_7d > 0) && (
        <div className="card card-pad mb-24" data-testid="spotlight-stats" style={{ background: "linear-gradient(135deg, rgba(212,175,55,0.08), rgba(109,40,217,0.05))" }}>
          <div className="fw-700 mb-8">🏆 Homepage Banner Performance</div>
          <div className="grid grid-3 gap-12">
            <div>
              <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>All-time impressions</div>
              <div className="font-serif" style={{ fontSize: 32, fontWeight: 700, color: "var(--gold-light)" }} data-testid="spot-total">{spotStats.total_impressions.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Last 7 days</div>
              <div className="font-serif" style={{ fontSize: 32, fontWeight: 700 }} data-testid="spot-7d">{spotStats.last_7d.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Daily trend</div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 44, marginTop: 6 }}>
                {(spotStats.series || []).slice(-14).map((s, i) => {
                  const max = Math.max(1, ...spotStats.series.map((x) => x.count));
                  return <div key={s.day || `bar-${i}`} title={`${s.day}: ${s.count}`} style={{ flex: 1, background: "var(--gold)", opacity: 0.55 + 0.45 * (s.count / max), height: `${20 + 80 * (s.count / max)}%`, borderRadius: 2, minWidth: 4 }} />;
                })}
                {(!spotStats.series || spotStats.series.length === 0) && <div className="text-muted fs-11">Waiting for impressions…</div>}
              </div>
            </div>
          </div>
          <div className="text-muted fs-11" style={{ marginTop: 10 }}>Each unique visitor per day counts once. Impressions grow while your Homepage Banner boost is active.</div>
        </div>
      )}

      {/* Funnel KPIs */}
      <div className="grid grid-4 gap-12 mb-24">
        <KpiCard label="Profile Views" value={f.profile_views} icon="👀" testid="kpi-views" />
        <KpiCard label="Bookings Created" value={f.bookings_created} icon="🎟️" testid="kpi-created" />
        <KpiCard label="Conversion Rate" value={`${f.conversion_pct || 0}%`} icon="⚡" testid="kpi-conv" sub={`${f.bookings_created} of ${f.profile_views} views`} />
        <KpiCard label="Total Earnings" value={fmtINRFull(rev.total_earnings || 0)} icon="💰" testid="kpi-earn" sub={`avg ${fmtINRFull(rev.avg_ticket || 0)}/booking`} />
      </div>

      {/* Funnel bar */}
      <div className="card card-pad mb-24" data-testid="funnel-bar">
        <div className="fw-700 mb-12">Booking Funnel</div>
        <FunnelStep label="Views" value={f.profile_views} max={Math.max(1, f.profile_views)} />
        <FunnelStep label="Bookings Created" value={f.bookings_created} max={Math.max(1, f.profile_views)} />
        <FunnelStep label="Confirmed / Paid" value={f.bookings_confirmed} max={Math.max(1, f.profile_views)} />
        <FunnelStep label="Completed" value={f.bookings_completed} max={Math.max(1, f.profile_views)} highlight />
        {f.completion_pct > 0 && (
          <div className="text-muted fs-12 mt-8" data-testid="completion-rate">✅ {f.completion_pct}% of created bookings reach completion</div>
        )}
      </div>

      <div className="grid grid-2 gap-16">
        {/* Top cities */}
        <div className="card card-pad" data-testid="top-cities">
          <div className="fw-700 mb-12">📍 Where Your Customers Are</div>
          {(data.top_cities || []).length === 0 ? (
            <div className="text-muted fs-13">No bookings yet.</div>
          ) : (data.top_cities.map((c) => (
            <BarRow key={c.city} label={c.city} value={c.count} max={maxCity} />
          )))}
          {data.top_searched_cities?.length > 0 && (
            <div className="mt-16">
              <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Most Searched Cities on BookTalent</div>
              <div className="flex gap-6 mt-8" style={{ flexWrap: "wrap" }}>
                {data.top_searched_cities.map((c) => (
                  <span key={c.city} className="pill" style={{ background: "rgba(212,175,55,0.15)", color: "var(--gold)", fontSize: 11 }} data-testid={`searched-city-${c.city}`}>{c.city} · {c.count}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Top event types */}
        <div className="card card-pad" data-testid="top-event-types">
          <div className="fw-700 mb-12">🎪 Top Event Types</div>
          {(data.top_event_types || []).length === 0 ? (
            <div className="text-muted fs-13">No bookings yet.</div>
          ) : (data.top_event_types.map((c) => (
            <BarRow key={c.event_type} label={c.event_type} value={c.count} max={maxEt} />
          )))}
        </div>
      </div>

      <div className="text-muted text-center fs-11 mt-24">
        Updated {new Date(data.generated_at).toLocaleString()}
      </div>
    </div>
  );
}

function KpiCard({ label, value, icon, sub, testid }) {
  return (
    <div className="card card-pad text-center" data-testid={testid}>
      <div style={{ fontSize: 28 }}>{icon}</div>
      <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
      <div className="font-serif fw-700" style={{ fontSize: 24 }}>{value}</div>
      {sub && <div className="text-muted fs-11">{sub}</div>}
    </div>
  );
}

function FunnelStep({ label, value, max, highlight }) {
  const pct = max ? Math.round((value / max) * 100) : 0;
  return (
    <div className="mb-8">
      <div className="flex justify-between mb-4"><span className="fs-13">{label}</span><span className="fs-13 fw-700">{value}</span></div>
      <div style={{ height: 8, borderRadius: 4, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: highlight ? "linear-gradient(90deg,#34d399,#059669)" : "linear-gradient(90deg,#d4af37,#fbbf24)", transition: "width .6s ease" }} />
      </div>
    </div>
  );
}

function BarRow({ label, value, max }) {
  const pct = max ? Math.round((value / max) * 100) : 0;
  return (
    <div className="mb-8">
      <div className="flex justify-between mb-4"><span className="fs-12">{label}</span><span className="fs-12 fw-700">{value}</span></div>
      <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg,#a78bfa,#d4af37)" }} />
      </div>
    </div>
  );
}



// ─────────────────────────────────────────────────────────────────────────
// Iter 56 — QuestionnaireNudge
// Persuasive banner shown on the Overview tab when the artist is missing
// more than 3 of the questionnaire sections. Hides when they finish, and
// can be dismissed for the session so it doesn't nag over one visit.
// ─────────────────────────────────────────────────────────────────────────
function QuestionnaireNudge({ completion, onOpen }) {
  const [dismissed, setDismissed] = useState(false);
  if (!completion || dismissed) return null;
  const missingArr = completion.sections_missing || [];
  const missing = missingArr.length;
  if (missing <= 3) return null;

  const pct = completion.questions_total
    ? Math.round((completion.questions_answered / completion.questions_total) * 100)
    : 0;

  return (
    <div className="qn-nudge" data-testid="qn-nudge" style={{
      position: "relative",
      marginBottom: 20,
      padding: "18px 22px",
      borderRadius: 14,
      background: "linear-gradient(115deg, rgba(246,211,102,0.14), rgba(178,132,255,0.08))",
      border: "1px solid rgba(246,211,102,0.28)",
      display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap",
    }}>
      <div style={{ fontSize: 32, lineHeight: 1 }}>🎯</div>
      <div style={{ flex: 1, minWidth: 240 }}>
        <div style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 700, marginBottom: 4 }}>
          Complete your rider so customers book with confidence
        </div>
        <div style={{ fontSize: 13, color: "var(--white-muted)" }}>
          You've answered {completion.questions_answered} of {completion.questions_total} questions ({pct}%).
        </div>
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span className="text-muted fs-12" style={{ marginRight: 4 }}>Still missing:</span>
          {missingArr.map((sec) => (
            <button
              key={sec}
              type="button"
              onClick={() => onOpen?.(sec)}
              data-testid={`qn-missing-${sec.toLowerCase().replace(/\s+/g,'-')}`}
              className="qn-missing-chip"
              style={{
                background: "rgba(246,211,102,0.12)",
                border: "1px solid rgba(246,211,102,0.3)",
                color: "#f6d366",
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 11.5,
                fontWeight: 500,
                cursor: "pointer",
                transition: "background 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(246,211,102,0.24)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(246,211,102,0.12)"; }}
              title={`Jump to ${sec}`}
            >
              {sec} →
            </button>
          ))}
        </div>
        <div style={{ marginTop: 10, height: 6, borderRadius: 3, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
          <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg, #f6d366, #b284ff)", transition: "width 0.4s ease" }} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn btn-gold btn-sm" onClick={() => onOpen?.()} data-testid="qn-nudge-cta">
          Finish Questionnaire →
        </button>
        <button
          className="btn btn-ghost btn-xs"
          onClick={() => setDismissed(true)}
          title="Hide for now"
          data-testid="qn-nudge-dismiss"
          style={{ padding: "4px 8px" }}
        >
          ✕
        </button>
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// T&C Agreement Gate — mandatory modal shown when KYC is approved but the
// artist has not yet accepted terms. On acceptance, backend generates the
// signed agreement and flips the artist to LIVE.
// ────────────────────────────────────────────────────────────────────────
function TncAgreementGate({ toast, onDone }) {
  const [needs, setNeeds] = useState(false);
  const [kyc, setKyc] = useState(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.get("/kyc/me")
      .then((r) => {
        setKyc(r.data);
        // Show only when KYC is approved but T&C acceptance still pending.
        setNeeds(r.data?.kyc_status === "kyc_approved" || r.data?.kyc_status === "tnc_pending");
      })
      .catch(() => setNeeds(false));
  }, []);

  const accept = async () => {
    if (!checked) { toast("Please tick the checkbox to accept the Terms & Conditions", "error"); return; }
    setBusy(true);
    try {
      const r = await api.post("/kyc/accept-terms", { accepted: true });
      toast("🎉 Terms accepted — your agreement is ready and you're now live!", "success");
      setNeeds(false);
      if (r.data?.agreement_url) {
        window.open(r.data.agreement_url, "_blank", "noopener,noreferrer");
      }
      onDone && onDone();
    } catch (e) {
      toast(formatApiError(e), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!needs || dismissed) return null;
  const pctText = kyc?.is_service_artist && kyc?.percentage_deal
    ? `BookTalent Service Artist · Commission ${kyc.percentage_deal}%`
    : "Normal Artist · Platform Fee 5% (charged to customer only)";

  return (
    <div
      data-testid="tnc-gate"
      style={{
        position: "fixed", inset: 0, background: "rgba(6,4,20,0.82)",
        display: "grid", placeItems: "center", zIndex: 999, padding: 16,
        backdropFilter: "blur(6px)",
      }}
    >
      <div
        className="card card-pad"
        style={{ maxWidth: 560, width: "100%", background: "#0F0F1B", border: "1px solid rgba(212,175,55,0.35)" }}
      >
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
          <div style={{ fontSize: 30 }}>📜</div>
          <div>
            <h2 className="font-serif fw-700" style={{ fontSize: 22, color: "#D4AF37", marginBottom: 4 }}>
              Accept the BookTalent Artist Agreement
            </h2>
            <div className="text-muted fs-13">
              KYC approved 🎉. To go live and start accepting bookings, please review and accept the terms below.
            </div>
          </div>
        </div>
        <div
          style={{
            background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 10, padding: 14, marginBottom: 12, fontSize: 13, lineHeight: 1.55,
          }}
        >
          <div className="fw-700 mb-4">Commercial deal (set at KYC)</div>
          <div className="text-muted mb-8">{pctText}</div>
          <div className="fw-700 mb-4">Key terms</div>
          <ul style={{ margin: 0, paddingLeft: 18, color: "rgba(240,238,255,0.75)" }}>
            <li>You agree to keep availability, packages and profile info accurate.</li>
            <li>All customer communication for BookTalent-Service bookings flows through the assigned Manager.</li>
            <li>Payouts follow BookTalent's milestone schedule after each successful event.</li>
            <li>Cancellation and dispute policies apply as per platform rules.</li>
          </ul>
        </div>
        <label
          data-testid="tnc-checkbox-wrap"
          style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer", marginBottom: 14 }}
        >
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            data-testid="tnc-checkbox"
            style={{ marginTop: 3, transform: "scale(1.2)" }}
          />
          <span style={{ fontSize: 13 }}>
            I have read and agree to the BookTalent Artist Terms & Conditions. I understand a signed agreement
            will be generated and emailed to me on acceptance.
          </span>
        </label>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            className="btn btn-ghost"
            onClick={() => setDismissed(true)}
            data-testid="tnc-remind-later"
          >Remind me later</button>
          <button
            className="btn btn-gold"
            disabled={busy || !checked}
            onClick={accept}
            data-testid="tnc-accept"
          >{busy ? "Generating agreement…" : "Accept & Go Live"}</button>
        </div>
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// Tech Rider Panel — artist uploads/updates/downloads their tech rider.
// ────────────────────────────────────────────────────────────────────────
function TechRiderPanel({ toast }) {
  const [rider, setRider] = useState(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState(null);

  const reload = () => api.get("/artist/tech-rider/mine").then((r) => setRider(r.data)).catch(() => setRider(null));
  useEffect(() => { reload(); }, []);

  const upload = async () => {
    if (!file) { toast("Please choose a file first", "error"); return; }
    if (file.size > 10 * 1024 * 1024) { toast("File exceeds 10 MB limit", "error"); return; }
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      await api.post("/artist/tech-rider/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast("Tech Rider uploaded successfully", "success");
      setFile(null);
      reload();
    } catch (e) {
      toast(formatApiError(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove your uploaded Tech Rider?")) return;
    setBusy(true);
    try {
      await api.delete("/artist/tech-rider/mine");
      toast("Tech Rider removed");
      reload();
    } catch (e) {
      toast(formatApiError(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const current = rider?.file;

  return (
    <div className="card card-pad" data-testid="tech-rider-panel">
      <h2 className="font-serif fs-20 fw-700 mb-8">Tech Rider</h2>
      <p className="text-muted fs-13 mb-16">
        Upload your Tech Rider (PDF or image) so organisers and their production team know exactly what you need on stage.
        Max 10 MB. Replacing the file overrides the previous one.
      </p>

      {current ? (
        <div
          className="card card-pad mb-16"
          data-testid="tech-rider-current"
          style={{ background: "rgba(212,175,55,0.06)", border: "1px solid rgba(212,175,55,0.25)" }}
        >
          <div className="flex-between mb-8" style={{ gap: 12, flexWrap: "wrap" }}>
            <div>
              <div className="fw-700 fs-14">📎 {current.filename}</div>
              <div className="text-muted fs-11 mt-4">
                {(current.size / 1024).toFixed(1)} KB · uploaded {(current.uploaded_at || "").slice(0, 10)}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <a
                className="btn btn-ghost btn-sm"
                href={`${api.defaults.baseURL}${current.url}`}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="tech-rider-download"
              >⬇ Download</a>
              <button
                className="btn btn-ghost btn-sm"
                onClick={remove}
                disabled={busy}
                data-testid="tech-rider-remove"
                style={{ color: "#e57373" }}
              >Remove</button>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-muted fs-13 mb-16">No Tech Rider uploaded yet.</div>
      )}

      <div className="field">
        <div className="field-label">{current ? "Replace file" : "Upload file"} (PDF / JPG / PNG / WEBP, max 10 MB)</div>
        <input
          type="file"
          accept="application/pdf,image/*"
          onChange={(e) => setFile(e.target.files && e.target.files[0])}
          data-testid="tech-rider-file-input"
        />
      </div>
      <button
        className="btn btn-gold"
        onClick={upload}
        disabled={busy || !file}
        data-testid="tech-rider-upload"
      >{busy ? "Uploading…" : current ? "Replace Tech Rider" : "Upload Tech Rider"}</button>
    </div>
  );
}
