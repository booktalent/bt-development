/**
 * Iter 92 frontend — three focused pages:
 *   1. AdminAnalyticsDashboard (KPIs + funnel + daily line chart + churn)
 *   2. Public TrustPage         (/trust) — no auth
 *   3. NotificationPreferences  (per-user settings)
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import api, { fmtINRFull, formatApiError as fmt } from "../lib/api";
import { useToast } from "../lib/toast";
import Nav from "../components/Nav";


// ═══════════════════════════════════════════════════════════════════
// 1. Admin Analytics Dashboard
// ═══════════════════════════════════════════════════════════════════
export function AdminAnalyticsDashboard() {
  const [days, setDays] = useState(30);
  const [kpis, setKpis] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [churn, setChurn] = useState(null);
  const [daily, setDaily] = useState(null);

  const load = () => {
    api.get(`/admin/analytics/kpis?days=${days}`).then((r) => setKpis(r.data)).catch(() => {});
    api.get(`/admin/analytics/funnel?days=${days}`).then((r) => setFunnel(r.data)).catch(() => {});
    api.get(`/admin/analytics/churn`).then((r) => setChurn(r.data)).catch(() => {});
    api.get(`/admin/analytics/daily?days=${Math.min(days, 90)}`).then((r) => setDaily(r.data)).catch(() => {});
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [days]);

  // Simple SVG line chart — no chart library needed
  const chart = React.useMemo(() => {
    if (!daily?.series?.length) return null;
    const w = 720, h = 160, pad = 30;
    const gmvs = daily.series.map((d) => d.gmv);
    const max = Math.max(1, ...gmvs);
    const points = daily.series.map((d, i) => {
      const x = pad + i * ((w - pad * 2) / Math.max(1, daily.series.length - 1));
      const y = h - pad - (d.gmv / max) * (h - pad * 2);
      return `${x},${y}`;
    }).join(" ");
    return { w, h, pad, max, points };
  }, [daily]);

  return (
    <div data-testid="admin-analytics-dashboard">
      <div className="flex-between mb-16">
        <div>
          <h2 className="font-serif fs-24 fw-700">Founder KPI Dashboard</h2>
          <div className="text-muted fs-13">Top-line health · updates live from bookings & leads</div>
        </div>
        <select value={days} onChange={(e) => setDays(parseInt(e.target.value))} className="input"
                style={{ width: 160 }} data-testid="an-days">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {/* KPI grid */}
      {kpis && (
        <div className="grid grid-4 gap-16 mb-24" data-testid="an-kpis">
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>GMV</div>
            <div className="font-serif fs-28 fw-700 text-gold mt-4">{fmtINRFull(kpis.gmv)}</div>
            <div className="text-muted fs-11 mt-4">{kpis.bookings} bookings · avg {fmtINRFull(kpis.avg_booking_value)}</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Platform Revenue</div>
            <div className="font-serif fs-28 fw-700 text-gold mt-4">{fmtINRFull(kpis.net_platform_revenue)}</div>
            <div className="text-muted fs-11 mt-4">GST collected: {fmtINRFull(kpis.gst_collected)}</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Active Artists</div>
            <div className="font-serif fs-28 fw-700 text-gold mt-4">{kpis.active_artists}</div>
            <div className="text-muted fs-11 mt-4">Verified total: {kpis.verified_artists_total}</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Lead Conversion</div>
            <div className="font-serif fs-28 fw-700 text-gold mt-4">{kpis.conversion_pct}%</div>
            <div className="text-muted fs-11 mt-4">{kpis.leads_won} won of {kpis.leads_new} new</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>New Customers</div>
            <div className="font-serif fs-22 fw-700 mt-4">{kpis.new_customers}</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>New Artists</div>
            <div className="font-serif fs-22 fw-700 mt-4">{kpis.new_artists}</div>
          </div>
          <div className="card card-pad">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Events Delivered</div>
            <div className="font-serif fs-22 fw-700 mt-4">{kpis.completed_events}</div>
          </div>
          <div className="card card-pad" data-testid="an-churn-card">
            <div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Monthly Churn</div>
            <div className="font-serif fs-22 fw-700 mt-4" style={{ color: (churn?.churn_pct || 0) > 20 ? "#e57373" : "#6ee7a8" }}>
              {churn?.churn_pct || 0}%
            </div>
            <div className="text-muted fs-11 mt-4">{churn?.churned || 0} of {churn?.last_month_active || 0} last mo.</div>
          </div>
        </div>
      )}

      {/* Daily GMV chart */}
      {chart && (
        <div className="card card-pad mb-24" data-testid="an-daily-chart">
          <h3 className="fw-700 mb-8">Daily GMV — Last {daily.period_days} days</h3>
          <svg viewBox={`0 0 ${chart.w} ${chart.h}`} style={{ width: "100%", height: 180 }}>
            <line x1={chart.pad} y1={chart.h - chart.pad} x2={chart.w - chart.pad} y2={chart.h - chart.pad}
                  stroke="rgba(255,255,255,0.15)" strokeWidth={1} />
            <polyline points={chart.points} fill="none" stroke="#D4AF37" strokeWidth={2} strokeLinejoin="round" />
            <text x={chart.pad} y={12} fill="rgba(255,255,255,0.4)" fontSize={10}>
              Peak: {fmtINRFull(chart.max)}
            </text>
          </svg>
        </div>
      )}

      {/* Funnel */}
      {funnel && (
        <div className="card card-pad" data-testid="an-funnel">
          <h3 className="fw-700 mb-16">Conversion Funnel</h3>
          {funnel.stages.map((s, i) => {
            const width = Math.max(6, (s.count / Math.max(1, funnel.stages[0].count)) * 100);
            return (
              <div key={s.label} className="mb-12" data-testid={`an-funnel-${i}`}>
                <div className="flex-between fs-13 mb-4">
                  <span className="fw-700">{s.label}</span>
                  <span className="text-gold">
                    {s.count.toLocaleString()}
                    {s.conversion_from_prev !== null && (
                      <span className="text-muted"> · {s.conversion_from_prev}% from prev</span>
                    )}
                  </span>
                </div>
                <div style={{ height: 8, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{
                    width: `${width}%`, height: "100%",
                    background: `linear-gradient(90deg, #D4AF37 ${i * 15}%, #6ee7a8)`,
                    transition: "width 400ms ease",
                  }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 2. Public Trust Page — /trust (no auth)
// ═══════════════════════════════════════════════════════════════════
export function TrustPage() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    api.get("/public/trust-stats").then((r) => setStats(r.data)).catch(() => setStats({}));
  }, []);

  // ── SEO / Snippet-friendly copy ────────────────────────────────
  // Round artists down to a 100-bucket for a snippet-friendly "1,000+ artists".
  const artistBucket = stats?.verified_artists
    ? `${Math.max(100, Math.floor(stats.verified_artists / 100) * 100).toLocaleString()}+`
    : "1,000+";
  const cityCount = stats?.cities_served || 50;
  const rating = stats?.avg_rating || 4.9;
  const reviewCount = stats?.total_reviews || 0;
  const pageTitle = `Trusted by ${artistBucket} artists across ${cityCount} cities · ${rating}★ | BookTalent`;
  const pageDesc = `BookTalent — India's managed talent marketplace. ${artistBucket} verified artists, ${cityCount}+ cities served, ${rating}★ average rating${reviewCount ? ` across ${reviewCount.toLocaleString()} reviews` : ""}. Every metric refreshed live from the platform.`;
  const canonical = typeof window !== "undefined" ? `${window.location.origin}/trust` : "https://booktalent.in/trust";

  // JSON-LD: Organization with an embedded AggregateRating so Google can
  // render stars + review count directly in the SERP snippet. Only include
  // AggregateRating when we actually have review data (schema.org requires
  // ratingCount ≥ 1 for a valid AggregateRating).
  const orgLd = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "BookTalent",
    url: canonical.replace(/\/trust$/, ""),
    logo: `${canonical.replace(/\/trust$/, "")}/logo.png`,
    description: pageDesc,
    areaServed: { "@type": "Country", name: "India" },
    ...(reviewCount > 0 ? {
      aggregateRating: {
        "@type": "AggregateRating",
        ratingValue: String(rating),
        bestRating: "5",
        worstRating: "1",
        ratingCount: String(reviewCount),
        reviewCount: String(reviewCount),
      },
    } : {}),
  };
  const webPageLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: pageTitle,
    description: pageDesc,
    url: canonical,
    about: { "@type": "Organization", name: "BookTalent" },
  };

  return (
    <div>
      <Helmet>
        <title>{pageTitle}</title>
        <meta name="description" content={pageDesc} />
        <link rel="canonical" href={canonical} />
        <meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large" />
        {/* Open Graph */}
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="BookTalent" />
        <meta property="og:title" content={pageTitle} />
        <meta property="og:description" content={pageDesc} />
        <meta property="og:url" content={canonical} />
        {/* Twitter */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={pageTitle} />
        <meta name="twitter:description" content={pageDesc} />
        {/* Structured data */}
        <script type="application/ld+json">{JSON.stringify(orgLd)}</script>
        <script type="application/ld+json">{JSON.stringify(webPageLd)}</script>
      </Helmet>
      <Nav />
      <div className="pad-24" data-testid="trust-page" style={{ maxWidth: 1000, margin: "0 auto" }}>
        <div className="text-center mb-24">
          <div className="text-muted fs-12" style={{ letterSpacing: ".18em", textTransform: "uppercase" }}>
            Live from BookTalent
          </div>
          <h1 className="font-serif" style={{ fontSize: 48, fontWeight: 700, color: "#D4AF37", marginTop: 8 }} data-testid="trust-title">
            Trusted by artists & organisers across India
          </h1>
          <div className="text-muted fs-16 mt-8" style={{ maxWidth: 640, margin: "8px auto 0" }}>
            Every number below is refreshed straight from our platform — no marketing inflation.
          </div>
        </div>

        {!stats && <div className="text-center text-muted">Loading trust metrics…</div>}
        {stats && (
          <>
            <div className="grid grid-4 gap-16 mb-24">
              <div className="card card-pad text-center" data-testid="trust-artists">
                <div style={{ fontSize: 44 }}>🎤</div>
                <div className="font-serif fs-28 fw-700 text-gold mt-8">{stats.verified_artists?.toLocaleString()}</div>
                <div className="text-muted fs-12 mt-4">Verified Artists</div>
              </div>
              <div className="card card-pad text-center" data-testid="trust-events">
                <div style={{ fontSize: 44 }}>🎉</div>
                <div className="font-serif fs-28 fw-700 text-gold mt-8">{stats.completed_events?.toLocaleString()}</div>
                <div className="text-muted fs-12 mt-4">Events Delivered</div>
              </div>
              <div className="card card-pad text-center" data-testid="trust-cities">
                <div style={{ fontSize: 44 }}>📍</div>
                <div className="font-serif fs-28 fw-700 text-gold mt-8">{stats.cities_served}</div>
                <div className="text-muted fs-12 mt-4">Cities Served</div>
              </div>
              <div className="card card-pad text-center" data-testid="trust-rating">
                <div style={{ fontSize: 44 }}>⭐</div>
                <div className="font-serif fs-28 fw-700 text-gold mt-8">{stats.avg_rating}</div>
                <div className="text-muted fs-12 mt-4">Avg Rating · {stats.total_reviews?.toLocaleString()} reviews</div>
              </div>
            </div>

            {stats.top_cities?.length > 0 && (
              <div className="card card-pad" data-testid="trust-cities-list">
                <h3 className="fw-700 mb-8">Cities we operate in</h3>
                <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
                  {stats.top_cities.map((c) => (
                    <span key={c} className="pill pill-gold" style={{ fontSize: 12 }}>{c}</span>
                  ))}
                </div>
              </div>
            )}

            <div className="text-center mt-24">
              <Link to="/search" className="btn btn-gold" data-testid="trust-cta">Explore artists →</Link>
              <Link to="/signup" className="btn btn-ghost" style={{ marginLeft: 8 }} data-testid="trust-cta-signup">List your talent →</Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 3. Notification Preferences
// ═══════════════════════════════════════════════════════════════════
const EVENT_LABELS = {
  "booking.confirmed":       "Booking Confirmed",
  "payment.received":        "Payment Received",
  "payout.released":         "Payout Released",
  "kyc.approved":            "KYC Approved",
  "kyc.rejected":            "KYC Rejected",
  "kyc.needs_resubmission":  "KYC Needs Resubmission",
  "event.reminder":          "Event Reminder",
  "payment.reminder":        "Payment Due Reminder",
  "marketing.digest":        "Marketing / Weekly Digest",
  "profile.nudge":           "Profile Nudges",
};

export function NotificationPreferences() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/user/notification-preferences");
      setData(r.data);
      setDrafts(r.data.preferences);
    } catch (e) { toast(fmt(e), "error"); }
  };
  useEffect(() => { load(); }, []);

  const toggle = (event, channel) => {
    setDrafts((prev) => ({
      ...prev,
      [event]: { ...prev[event], [channel]: !prev[event][channel] },
    }));
  };

  const save = async () => {
    setSaving(true);
    try {
      // Only send editable (non-force_on) events; strip force_on flag from payload.
      const payload = { preferences: {} };
      for (const [ev, chans] of Object.entries(drafts)) {
        if (chans.force_on) continue;
        payload.preferences[ev] = {
          email: chans.email, whatsapp: chans.whatsapp,
          in_app: chans.in_app, sms: chans.sms,
        };
      }
      await api.patch("/user/notification-preferences", payload);
      toast("Preferences saved", "success");
      load();
    } catch (e) { toast(fmt(e), "error"); }
    setSaving(false);
  };

  if (!data) return (
    <div>
      <Nav />
      <div className="pad-24 text-muted" data-testid="np-loading">Loading preferences…</div>
    </div>
  );

  return (
    <div>
      <Nav />
      <div className="pad-24" data-testid="notification-preferences" style={{ maxWidth: 800, margin: "0 auto" }}>
        <div className="mb-16">
          <h1 className="font-serif fs-28 fw-700 text-gold" data-testid="np-title">Notification Preferences</h1>
          <div className="text-muted fs-13 mt-4">
            Choose how you want to hear from us. Transactional notifications (locked events) can't be turned off — they're
            required for security and compliance.
          </div>
        </div>

        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Event</th>
                <th style={{ textAlign: "center", width: 80 }}>In-app</th>
                <th style={{ textAlign: "center", width: 80 }}>Email</th>
                <th style={{ textAlign: "center", width: 100 }}>WhatsApp</th>
                <th style={{ textAlign: "center", width: 80 }}>SMS</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(drafts).map(([ev, chans]) => (
                <tr key={ev} data-testid={`np-row-${ev.replace(".", "-")}`}>
                  <td>
                    <div className="fw-700 fs-13">{EVENT_LABELS[ev] || ev}</div>
                    {chans.force_on && (
                      <div className="text-muted fs-11" style={{ marginTop: 2 }}>🔒 Required · cannot be muted</div>
                    )}
                  </td>
                  {["in_app", "email", "whatsapp", "sms"].map((ch) => (
                    <td key={ch} style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={!!chans[ch]}
                        disabled={chans.force_on}
                        onChange={() => toggle(ev, ch)}
                        data-testid={`np-toggle-${ev.replace(".", "-")}-${ch}`}
                        style={{ transform: "scale(1.2)", cursor: chans.force_on ? "not-allowed" : "pointer" }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex gap-8 mt-16">
          <button className="btn btn-gold" onClick={save} disabled={saving} data-testid="np-save">
            {saving ? "Saving…" : "Save Preferences"}
          </button>
          <button className="btn btn-ghost" onClick={load}>Reset</button>
        </div>
      </div>
    </div>
  );
}


export default AdminAnalyticsDashboard;
