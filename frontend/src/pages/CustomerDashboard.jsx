import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Nav from "../components/Nav";
import api, { fmtINRFull, formatApiError, API } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import ChatBox from "../components/ChatBox";
import PendingEventCarts from "../components/PendingEventCarts";
import useHighlightRow from "../lib/useHighlightRow";
import CancellationReasonModal from "../components/CancellationReasonModal";

export default function CustomerDashboard() {
  const { user } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [tab, setTab] = useState(() => {
    // Iter 65 — Notification-driven navigation: honour ?tab=bookings so we
    // scroll+flash the row without users having to click the sidebar first.
    const p = new URLSearchParams(window.location.search).get("tab");
    return p || "overview";
  });
  const [bookings, setBookings] = useState([]);
  const [analytics, setAnalytics] = useState({});
  const [reviewModal, setReviewModal] = useState(null);
  // Iter 74 — In-progress booking drafts + Recently Viewed artists.
  const [drafts, setDrafts] = useState([]);
  const [recentViews, setRecentViews] = useState([]);

  useEffect(() => {
    if (!user) { nav("/login"); return; }
    if (user.role === "artist") { nav("/artist"); return; }
    if (user.role === "admin") { nav("/admin"); return; }
    refresh();
    // `refresh` is defined below in the same render — adding it would cause a
    // new closure each render → infinite re-fetch. `nav` from react-router is
    // stable per its own docs. Intentional narrow dep list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const refresh = async () => {
    try {
      const [b, a, d, rv] = await Promise.all([
        api.get("/bookings/mine"),
        api.get("/analytics/me"),
        api.get("/customer/booking-drafts").catch(() => ({ data: [] })),
        api.get("/customer/recent-views").catch(() => ({ data: [] })),
      ]);
      setBookings(b.data);
      setAnalytics(a.data);
      setDrafts(d.data || []);
      setRecentViews(rv.data || []);
    } catch (e) {
      // 401 during a stale-session race is expected — auth.jsx will redirect
      // once /auth/me settles. Anything else, surface it.
      if (e?.response?.status !== 401) toast(formatApiError(e), "error");
    }
  };

  const discardDraft = async (artistId) => {
    try {
      await api.delete(`/customer/booking-drafts/${artistId}`);
      setDrafts((prev) => prev.filter((d) => d.artist_id !== artistId));
      toast("Draft discarded");
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const doAction = async (bid, action, extra = {}) => {
    try {
      await api.post(`/bookings/${bid}/action`, { action, ...extra });
      toast("Booking updated");
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const submitReview = async (booking_id, rating, text, photos = [], videos = []) => {
    try {
      const r = await api.post("/reviews", { booking_id, rating, text, photos, videos });
      toast(r.data.status === "pending" ? "Review submitted — awaiting moderation" : "Review published!");
      setReviewModal(null);
      refresh();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  if (!user) return null;

  return (
    <div className="dash-wrap" data-testid="customer-dashboard">
      <aside className="sidebar">
        <Link to="/" className="logo mb-20" data-testid="dash-logo">
          <div className="logo-mark">B</div>
          <span style={{ fontSize: 18 }}>Book<span className="gold">Talent</span></span>
        </Link>
        <div className="sb-section">Main</div>
        {[
          { id: "overview", label: "📊 Overview" },
          { id: "drafts", label: `💾 Drafts${drafts.length ? ` (${drafts.length})` : ""}` },
          { id: "bookings", label: "🎟️ My Bookings" },
          { id: "events", label: "🎪 My Events" },
          { id: "reviews", label: "⭐ Reviews" },
          { id: "messages", label: "💬 Messages" },
        ].map((x) => (
          <div key={x.id} className={`sb-item ${tab === x.id ? "active" : ""}`} onClick={() => setTab(x.id)} data-testid={`sb-${x.id}`}>
            {x.label}
          </div>
        ))}
        <div className="sb-section">Discover</div>
        <Link to="/search" className="sb-item">🔍 Find Artists</Link>
      </aside>

      <main className="dash-content">
        <Nav />
        <div style={{ marginTop: 18 }}>
          <div className="dash-head">
            <div>
              <h1>Welcome, {user.first_name}</h1>
              <p>Manage your bookings and reviews</p>
            </div>
            <Link to="/search" className="btn btn-gold btn-sm" data-testid="cust-find-artists">+ Book Artist</Link>
          </div>

          <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <Kpi icon="🎟️" cls="kpi-icon-purple" num={analytics.total_bookings || 0} label="Total Bookings" />
            <Kpi icon="✅" cls="kpi-icon-green" num={analytics.completed || 0} label="Completed" />
            <Kpi icon="📅" cls="kpi-icon-amber" num={analytics.upcoming || 0} label="Upcoming" />
          </div>

          {/* Resume-in-progress event carts (Iter 52.5 — user request:
              "I added artists but navigated away by mistake, where is my
              event cart?"). Only renders when at least one is stored. */}
          <PendingEventCarts />

          {tab === "overview" && (
            <>
              <div className="card" data-testid="cust-overview">
                <div className="card-head"><div className="card-title">📋 Recent Bookings</div></div>
                <BookingsTable bookings={bookings.slice(0, 6)} role="customer" onAction={doAction} onReview={setReviewModal} />
              </div>
              {/* Iter 74 — Recently Viewed strip on Overview so customers
                  see the artists they explored and jump back with one tap. */}
              {recentViews.length > 0 && (
                <RecentViewedStrip items={recentViews} />
              )}
              {/* Iter 74 — Drafts teaser on Overview so customers never
                  forget an in-progress booking. */}
              {drafts.length > 0 && (
                <DraftsList
                  drafts={drafts.slice(0, 3)}
                  onDiscard={discardDraft}
                  compact
                  onShowAll={() => setTab("drafts")}
                />
              )}
            </>
          )}

          {tab === "drafts" && (
            <div className="card" data-testid="cust-drafts">
              <div className="card-head"><div className="card-title">💾 In-Progress Bookings</div></div>
              <DraftsList drafts={drafts} onDiscard={discardDraft} />
            </div>
          )}

          {tab === "bookings" && (
            <div className="card" data-testid="cust-bookings">
              <div className="card-head"><div className="card-title">🎟️ All Bookings</div></div>
              <BookingsTable bookings={bookings} role="customer" onAction={doAction} onReview={setReviewModal} />
            </div>
          )}

          {tab === "events" && (
            <div data-testid="cust-events">
              <EventsGrouped bookings={bookings} onAction={doAction} />
            </div>
          )}

          {tab === "reviews" && <CustReviews bookings={bookings.filter(b => b.status === "reviewed")} />}

          {tab === "messages" && <Messages />}
        </div>
      </main>

      {reviewModal && <ReviewModal booking={reviewModal} onSubmit={submitReview} onClose={() => setReviewModal(null)} />}
    </div>
  );
}

const Kpi = ({ icon, cls, num, label, change }) => (
  <div className="kpi" data-testid={`kpi-${label.replace(/\s+/g, "-").toLowerCase()}`}>
    <div className="kpi-top">
      <div className={`kpi-icon ${cls}`}>{icon}</div>
      {change && <span className="kpi-change kpi-change-up">{change}</span>}
    </div>
    <div className="kpi-num">{num}</div>
    <div className="kpi-label">{label}</div>
  </div>
);


// Iter 74 — Renders the in-progress booking drafts list.
const stepLabel = (n) => {
  const map = { 1: "Package", 2: "Schedule", 3: "Details", 4: "Review", 5: "Payment" };
  return map[n] || `Step ${n}`;
};
const relativeTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};
const DraftsList = ({ drafts, onDiscard, compact = false, onShowAll = null }) => (
  <div className={`draft-list${compact ? " draft-list-compact" : ""}`} data-testid="drafts-list" style={{ padding: compact ? "8px 0 0" : 4 }}>
    {compact && (
      <div className="card-head" style={{ padding: "16px 8px 6px" }}>
        <div className="card-title">💾 Continue Where You Left Off</div>
        {onShowAll && drafts.length ? (
          <button className="btn btn-ghost btn-sm" onClick={onShowAll} data-testid="drafts-show-all">See all →</button>
        ) : null}
      </div>
    )}
    {drafts.length === 0 ? (
      <div className="empty" style={{ padding: 32, textAlign: "center" }}>
        <div className="empty-icon">💾</div>
        <div>No in-progress bookings — every completed cart lives under My Bookings.</div>
      </div>
    ) : (
      <div style={{ display: "grid", gap: 10, padding: compact ? "0 8px" : "12px 4px" }}>
        {drafts.map((d) => {
          const s = d.artist_snapshot || {};
          return (
            <div
              key={d.id || d.artist_id}
              className="draft-row"
              data-testid={`draft-${d.artist_id}`}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "12px 14px", borderRadius: 12,
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(212,175,55,0.18)",
              }}
            >
              <div style={{
                width: 44, height: 44, borderRadius: "50%",
                background: s.profile_image
                  ? `url(${API}/media/${s.profile_image}/thumb) center/cover`
                  : "linear-gradient(135deg, #d4af37, #6a3ad4)",
                flexShrink: 0,
              }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {s.stage_name || "Artist"}
                </div>
                <div style={{ fontSize: 12, color: "var(--white-muted, rgba(255,255,255,0.55))" }}>
                  {s.category || "—"}{s.city ? ` · ${s.city}` : ""}
                  {" · "}
                  <span style={{ color: "var(--gold)" }}>{stepLabel(d.step)}</span>
                  {" · "}
                  {relativeTime(d.updated_at)}
                </div>
              </div>
              <Link
                to={`/book/${d.artist_id}`}
                className="btn btn-gold btn-sm"
                data-testid={`draft-continue-${d.artist_id}`}
              >Continue →</Link>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid={`draft-discard-${d.artist_id}`}
                onClick={() => onDiscard(d.artist_id)}
                title="Discard draft"
                aria-label="Discard draft"
              >✕</button>
            </div>
          );
        })}
      </div>
    )}
  </div>
);

// Iter 74 — Horizontal strip of the last 8 artists this customer viewed.
const RecentViewedStrip = ({ items }) => (
  <div className="card" data-testid="recent-viewed-strip" style={{ marginTop: 16 }}>
    <div className="card-head">
      <div className="card-title">👀 Recently Viewed</div>
      <span className="text-muted fs-13">{items.length} artists</span>
    </div>
    <div style={{
      display: "flex", gap: 12, padding: "8px 8px 12px",
      overflowX: "auto", scrollbarWidth: "thin",
    }}>
      {items.map((v) => {
        const s = v.artist_snapshot || {};
        const targetSlug = s.slug || s.user_id || v.artist_id;
        return (
          <Link
            key={v.id || v.artist_id}
            to={`/artist/${targetSlug}`}
            data-testid={`recent-view-${v.artist_id}`}
            style={{
              flexShrink: 0, width: 128,
              textDecoration: "none", color: "inherit",
              padding: 8, borderRadius: 12,
              background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.06)",
              transition: "border-color 200ms ease, transform 200ms ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(212,175,55,0.35)"; e.currentTarget.style.transform = "translateY(-2px)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"; e.currentTarget.style.transform = "none"; }}
          >
            <div style={{
              width: "100%", height: 96, borderRadius: 8,
              background: s.profile_image
                ? `url(${API}/media/${s.profile_image}/thumb) center/cover`
                : "linear-gradient(135deg, #d4af37, #6a3ad4)",
              marginBottom: 8,
            }} />
            <div style={{
              fontSize: 12, fontWeight: 600,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{s.stage_name || "Artist"}</div>
            <div style={{
              fontSize: 10, color: "var(--white-muted, rgba(255,255,255,0.55))",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{s.category || ""}{s.city ? ` · ${s.city}` : ""}</div>
          </Link>
        );
      })}
    </div>
  </div>
);



const STATUS_MAP = {
  pending_payment: ["sp-pending", "Pending payment"],
  pending_artist: ["sp-pending", "Waiting for Artist Confirmation"],
  confirmed: ["sp-confirmed", "Confirmed"],
  started: ["sp-confirmed", "In progress"],
  completed_by_artist: ["sp-pending", "Pending approval"],
  completed: ["sp-completed", "Completed"],
  reviewed: ["sp-completed", "Reviewed"],
  rejected: ["sp-rejected", "Rejected"],
  auto_expired: ["sp-rejected", "Booking request expired"],
  cancelled: ["sp-rejected", "Cancelled"],
};

/** Compact "23h 45m left" chip for pending_artist bookings using expires_at. */
function ExpiryCountdown({ expiresAt, urgent = false }) {
  const [now, setNow] = React.useState(Date.now());
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - now;
  if (diff <= 0) return <span className="expiry-chip expiry-chip-danger" data-testid="expiry-elapsed">Expiring…</span>;
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const label = h > 0 ? `${h}h ${m}m left` : `${m}m left`;
  const cls = diff < 3600000 * 4 ? "expiry-chip-danger" : (diff < 3600000 * 12 ? "expiry-chip-warn" : "");
  return <span className={`expiry-chip ${cls} ${urgent ? "urgent" : ""}`} data-testid="expiry-chip">⏱ {label}</span>;
}

export function BookingsTable({ bookings, role, onAction, onReview }) {
  const [chatBooking, setChatBooking] = useState(null);
  const [badges, setBadges] = useState({});   // { booking_id: {stage,label,tint} }
  // Iter 75.5 — Cancellation-reason modal. Opened by every "Cancel"
  // button (artist OR customer). Reason is passed straight through to
  // `onAction(id, "cancel", { reason })`.
  const [cancelState, setCancelState] = useState(null); // { booking, actorRole }

  const openCancel = (booking, actorRole) => setCancelState({ booking, actorRole });
  const closeCancel = () => setCancelState(null);
  const confirmCancel = async (reason) => {
    if (!cancelState) return;
    await onAction(cancelState.booking.id, "cancel", { reason });
    setCancelState(null);
  };

  // Iter 65 — When a notification links to /customer?highlight=BID (or the
  // equivalent artist/agency/admin routes), scroll to the exact row and
  // pulse a soft gold flash so the operator immediately spots it.
  useHighlightRow({ prefix: "booking-row", dataKey: bookings?.length });

  // Lock body scroll + scroll to top when a chat opens so the modal is always
  // visible (otherwise the modal-bg dim appears but the modal-card lands above
  // the viewport on long lists, which users perceive as "Chat shows an empty
  // faded screen for a long time").
  useEffect(() => {
    if (chatBooking) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      window.scrollTo({ top: 0, behavior: "smooth" });
      return () => { document.body.style.overflow = prev; };
    }
  }, [chatBooking]);

  // Iter 98 — Fetch the compact lifecycle-stage badge for each booking
  // shown here so customers/artists see the current stage at a glance
  // without opening each row.
  useEffect(() => {
    if (!bookings || bookings.length === 0) return;
    if (role !== "customer" && role !== "artist") return;
    api.get("/bookings/mine/badges")
      .then((r) => setBadges(r.data?.items || {}))
      .catch(() => setBadges({}));
  }, [bookings, role]);

  if (bookings.length === 0) {
    return <div className="empty"><div className="empty-icon">📋</div><div className="empty-title">No bookings yet</div></div>;
  }

  const downloadPdf = async (url, filename) => {
    // httpOnly cookie flows automatically thanks to credentials: "include".
    const r = await fetch(`${API}${url}`, { credentials: "include" });
    if (!r.ok) { alert("Download failed"); return; }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div className="table-wrap">
      <table className="table" data-testid="bookings-table">
        <thead>
          <tr>
            <th>Ref</th>
            <th>Event</th>
            <th>Date</th>
            {role === "artist" ? <th>Package</th> : <th>Amount</th>}
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {bookings.map((b) => {
            const [pillCls, label] = STATUS_MAP[b.status] || ["sp-pending", b.status];
            const showContract = b.contract_id && ["confirmed", "started", "completed_by_artist", "completed", "reviewed"].includes(b.status);
            return (
              <tr key={b.id} data-testid={`booking-row-${b.id}`}>
                <td className="font-mono fs-11" style={{ color: "var(--gold-light)" }}>{b.ref}</td>
                <td>
                  <div className="fw-600">{b.event_type}</div>
                  <div className="text-muted fs-11">{b.venue}, {b.city}</div>
                  {(b.special_instructions || "").trim() && (
                    <div className="text-muted fs-11 mt-4" title={b.special_instructions} data-testid={`si-preview-${b.id}`} style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      📝 {b.special_instructions}
                    </div>
                  )}
                </td>
                <td className="fs-12">{b.event_date}<br/><span className="text-muted">{b.event_time}</span></td>
                {role === "artist" ? (
                  <td data-testid={`pkg-cell-${b.id}`}>
                    <div className="fw-600 fs-13">{b.package_name || b.event_type || "Package"}</div>
                    <div className="text-gold font-serif fs-16 fw-700">{fmtINRFull(b.pricing?.package_fee ?? b.pricing?.base ?? b.pricing?.artist_fee ?? 0)}</div>
                  </td>
                ) : (
                  <td className="text-gold font-serif fs-18 fw-700">{fmtINRFull(b.pricing?.total || 0)}</td>
                )}
                <td>
                  <span className={`status-pill ${pillCls}`}>{label}</span>
                  {badges[b.id] && (
                    <div
                      data-testid={`bt-tl-badge-${b.id}`}
                      title="Lifecycle stage — see the booking timeline for details"
                      style={{
                        display: "inline-block", marginTop: 4,
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: {
                          emerald: "rgba(110,231,168,0.14)",
                          gold: "rgba(212,175,55,0.14)",
                          amber: "rgba(255,193,7,0.14)",
                          violet: "rgba(180,148,244,0.14)",
                          blue: "rgba(120,180,255,0.14)",
                        }[badges[b.id].tint] || "rgba(255,255,255,0.06)",
                        color: {
                          emerald: "#6ee7a8",
                          gold: "#D4AF37",
                          amber: "#ffc107",
                          violet: "#B494F4",
                          blue: "#78B4FF",
                        }[badges[b.id].tint] || "rgba(240,238,255,0.7)",
                        border: "1px solid rgba(255,255,255,0.05)",
                      }}>
                      {badges[b.id].label}
                    </div>
                  )}
                  {b.status === "pending_artist" && b.expires_at && (
                    <div className="mt-4">
                      <ExpiryCountdown expiresAt={b.expires_at} urgent={role === "artist"} />
                    </div>
                  )}
                  {/* Iter 75.5 — Show cancellation attribution + reason on any
                      cancelled row so admins / customers / artists can see who
                      pulled the plug and why. */}
                  {b.status === "cancelled" && b.cancel_reason && (
                    <div
                      data-testid={`cancel-info-${b.id}`}
                      className="mt-4 fs-11"
                      style={{ color: "rgba(255,107,129,0.85)", lineHeight: 1.35 }}
                      title={b.cancel_reason}
                    >
                      <span style={{ opacity: 0.75 }}>By {b.cancelled_by || "—"}:</span>{" "}
                      {b.cancel_reason.length > 60 ? b.cancel_reason.slice(0, 57) + "…" : b.cancel_reason}
                    </div>
                  )}
                </td>
                <td>
                  <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
                    <a
                      className="btn btn-ghost btn-xs"
                      href={`/bookings/${b.id}`}
                      data-testid={`view-details-${b.id}`}
                      title="View full booking with payment timeline"
                    >View</a>
                    {role === "artist" && b.status === "pending_artist" && (
                      <>
                        <button className="btn btn-green btn-xs" onClick={() => onAction(b.id, "accept")} data-testid={`accept-${b.id}`}>Accept</button>
                        <button className="btn btn-red btn-xs" onClick={() => onAction(b.id, "reject")} data-testid={`reject-${b.id}`}>Reject</button>
                      </>
                    )}
                    {role === "artist" && b.status === "confirmed" && (
                      <>
                        <button className="btn btn-purple btn-xs" onClick={() => onAction(b.id, "complete")} data-testid={`complete-${b.id}`}>Mark Complete</button>
                        {/* Iter 75.5 — Artist cancellation opens the
                            mandatory reason modal. Refund still fires
                            server-side once the reason is confirmed. */}
                        <button
                          className="btn btn-red btn-xs"
                          data-testid={`artist-cancel-${b.id}`}
                          onClick={() => openCancel(b, "artist")}
                        >Cancel</button>
                      </>
                    )}
                    {role === "customer" && b.status === "completed_by_artist" && (
                      <button className="btn btn-green btn-xs" onClick={() => onAction(b.id, "approve_completion")} data-testid={`approve-${b.id}`}>Approve</button>
                    )}
                    {role === "customer" && b.status === "completed" && (
                      <button className="btn btn-gold btn-xs" onClick={() => onReview(b)} data-testid={`review-${b.id}`}>⭐ Review</button>
                    )}
                    {role === "customer" && ["pending_artist", "confirmed"].includes(b.status) && (
                      /* Iter 75.5 — Customer cancellation also requires a
                         reason. Modal spells out the non-refund policy. */
                      <button
                        className="btn btn-red btn-xs"
                        data-testid={`cancel-${b.id}`}
                        onClick={() => openCancel(b, "customer")}
                      >Cancel</button>
                    )}
                    {showContract && (
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => downloadPdf(`/contracts/${b.contract_id}/pdf`, `contract_${b.ref}.pdf`)}
                        data-testid={`dl-contract-${b.id}`}
                        title="Download Contract PDF"
                      >📄 Contract</button>
                    )}
                    {b.amount_paid > 0 && role !== "artist" && (
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => downloadPdf(`/bookings/${b.id}/invoice`, `invoice_${b.ref}.pdf`)}
                        data-testid={`dl-invoice-${b.id}`}
                        title="Download Invoice PDF"
                      >🧾 Invoice</button>
                    )}
                    {role === "customer" && ["pending_artist", "confirmed", "started", "completed", "reviewed"].includes(b.status) && (
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => window.open(`/recap/${b.event_id || b.id}`, "_blank", "noopener")}
                        data-testid={`share-recap-${b.id}`}
                        title="Share a beautiful recap of this event"
                      >💬 Share Recap</button>
                    )}
                    {(() => {
                      // Chat is locked ONLY for fresh, unpaid booking requests
                      // (status === "pending_payment" + payment_status === "unpaid").
                      // Every booking past that gate (legacy or new) keeps chat open.
                      const ps = b.payment_status;
                      const isPendingPayment = b.status === "pending_payment";
                      const isUnpaid = ps === "unpaid" || ps === undefined && isPendingPayment;
                      const chatUnlocked = !isPendingPayment && !isUnpaid;
                      return (
                        <button
                          className="btn btn-ghost btn-xs"
                          onClick={() => setChatBooking(b)}
                          disabled={!chatUnlocked}
                          data-testid={`chat-${b.id}`}
                          title={chatUnlocked
                            ? "Open chat"
                            : "Chat will be available after successful payment of the Platform Service Fee."}
                          style={!chatUnlocked ? { opacity: 0.55, cursor: "not-allowed" } : undefined}
                        >
                          {chatUnlocked ? "💬 Chat" : "🔒 Pay to Unlock Chat"}
                        </button>
                      );
                    })()}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {chatBooking && (
        <div className="modal-bg" onClick={() => setChatBooking(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640, padding: 0 }}>
            <ChatBox
              bookingId={chatBooking.id}
              otherName={role === "customer" ? (chatBooking.artist_name || "Artist") : (chatBooking.customer_name || "Customer")}
              paymentStatus={chatBooking.payment_status}
              height={520}
            />
            <div style={{ padding: 10, textAlign: "right" }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setChatBooking(null)} data-testid="chat-close">Close</button>
            </div>
          </div>
        </div>
      )}
      {/* Iter 75.5 — Cancellation reason modal shared across artist &
          customer cancellation flows. */}
      <CancellationReasonModal
        open={!!cancelState}
        onClose={closeCancel}
        onConfirm={confirmCancel}
        actorRole={cancelState?.actorRole}
        amountPaid={cancelState?.booking?.amount_paid || 0}
        bookingRef={cancelState?.booking?.ref || ""}
      />
    </div>
  );
}

function ReviewModal({ booking, onSubmit, onClose }) {
  const [rating, setRating] = useState(5);
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState([]);
  const [videos, setVideos] = useState([]);
  const [busy, setBusy] = useState(false);

  const readFile = (f) => new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.readAsDataURL(f);
  });

  const onPhotos = async (e) => {
    const files = Array.from(e.target.files || []).slice(0, 5);
    const oversize = files.find((f) => f.size > 5 * 1024 * 1024);
    if (oversize) { alert("Each photo must be under 5 MB"); return; }
    const urls = await Promise.all(files.map(readFile));
    setPhotos(urls);
  };

  const onVideos = async (e) => {
    const files = Array.from(e.target.files || []).slice(0, 2);
    const oversize = files.find((f) => f.size > 30 * 1024 * 1024);
    if (oversize) { alert("Each video must be under 30 MB"); return; }
    const urls = await Promise.all(files.map(readFile));
    setVideos(urls);
  };

  const submit = async () => {
    setBusy(true);
    try { await onSubmit(booking.id, rating, text, photos, videos); }
    finally { setBusy(false); }
  };

  return (
    <div className="modal-bg" onClick={onClose} data-testid="review-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">Leave a Review</div>
        <div className="modal-sub">{booking.event_type} · {booking.event_date}</div>
        <div className="field">
          <div className="field-label">Your Rating</div>
          <div style={{ display: "flex", gap: 6, fontSize: 32, cursor: "pointer" }} data-testid="rating-stars">
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n} onClick={() => setRating(n)} style={{ color: n <= rating ? "var(--gold)" : "var(--white-dim)" }} data-testid={`star-${n}`}>★</span>
            ))}
          </div>
        </div>
        <div className="field">
          <div className="field-label">Your Review</div>
          <textarea className="field-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Share your experience…" data-testid="review-text" />
        </div>
        <div className="field">
          <div className="field-label">Photos (up to 5, max 5 MB each — will be moderated)</div>
          <input type="file" accept="image/*" multiple onChange={onPhotos} data-testid="review-photos" />
          {photos.length > 0 && <div className="pill pill-green mt-8">✓ {photos.length} photo(s) attached</div>}
        </div>
        <div className="field">
          <div className="field-label">Videos (up to 2, max 30 MB each — will be moderated)</div>
          <input type="file" accept="video/*" multiple onChange={onVideos} data-testid="review-videos" />
          {videos.length > 0 && <div className="pill pill-green mt-8">✓ {videos.length} video(s) attached</div>}
        </div>
        {(photos.length > 0 || videos.length > 0) && (
          <div className="text-muted fs-11 mb-8">Reviews with media go to moderation queue (24-48 h).</div>
        )}
        <div className="flex gap-12 mt-16">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" style={{ flex: 1 }} onClick={submit} disabled={!text || busy} data-testid="submit-review">
            {busy ? "Submitting..." : "Submit Review"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CustReviews() {
  return (
    <div className="card card-pad" data-testid="reviews-tab">
      <div className="empty">
        <div className="empty-icon">⭐</div>
        <div className="empty-title">Your Reviews</div>
        <p>Reviews you've left for completed bookings will appear here.</p>
      </div>
    </div>
  );
}

function Messages() {
  const [convos, setConvos] = useState([]);
  useEffect(() => { api.get("/conversations").then((r) => setConvos(r.data)).catch(() => setConvos([])); }, []);
  return (
    <div className="card" data-testid="messages-tab">
      <div className="card-head"><div className="card-title">💬 Conversations</div></div>
      <div style={{ padding: 14 }}>
        {convos.length === 0 ? <div className="empty"><div className="empty-icon">💬</div><div className="empty-title">No conversations yet</div></div> :
          convos.map((c) => (
            <div key={c.id} className="card card-pad mb-12" data-testid={`convo-${c.id}`}>
              <div className="fw-600">{c.other?.first_name} {c.other?.last_name}</div>
              <div className="text-muted fs-12">{c.last_message}</div>
            </div>
          ))}
      </div>
    </div>
  );
}

/**
 * Iter 45 — EventsGrouped
 * Renders bookings grouped by event_id. Multi-artist events appear as one
 * card with per-artist sub-rows; solo bookings still get their own card.
 */
function EventsGrouped({ bookings, onAction }) {
  const [artistCache, setArtistCache] = useState({});

  const groups = React.useMemo(() => {
    const map = new Map();
    for (const b of bookings) {
      const key = b.event_id || b.id;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(b);
    }
    const arr = Array.from(map.entries()).map(([event_id, items]) => ({
      event_id,
      items: [...items].sort((a, b) => (a.artist_id || "").localeCompare(b.artist_id || "")),
      first: items[0],
    }));
    arr.sort((x, y) => (y.first.event_date || "").localeCompare(x.first.event_date || ""));
    return arr;
  }, [bookings]);

  // Batch-fetch stage_name + category for every unique artist_id shown.
  useEffect(() => {
    const ids = Array.from(new Set(bookings.map((b) => b.artist_id))).filter((id) => id && !artistCache[id]);
    if (!ids.length) return;
    let cancelled = false;
    Promise.all(ids.map((id) => api.get(`/artists/${id}`).catch(() => null))).then((rs) => {
      if (cancelled) return;
      const next = { ...artistCache };
      rs.forEach((r) => {
        if (!r?.data) return;
        // /api/artists/{id} nests everything under `.profile` — read from
        // there first, then fall back to top-level so both shapes work.
        const p = r.data.profile || {};
        const uid = p.user_id || r.data.user_id || r.data.id;
        if (!uid) return;
        next[uid] = {
          stage_name: p.stage_name || r.data.stage_name || "Artist",
          category: p.category || r.data.category,
          emoji: p.emoji || r.data.emoji || "🎤",
        };
      });
      setArtistCache(next);
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookings]);

  if (!groups.length) {
    return (
      <div className="card card-pad text-center">
        <div style={{ fontSize: 44 }}>🎪</div>
        <div className="fw-600 mt-8">No events yet</div>
        <div className="text-muted fs-13 mt-4">Book an artist and this is where all your events will show up.</div>
      </div>
    );
  }

  return (
    <div>
      {groups.map((g) => {
        const evDate = g.first.event_date;
        const evType = g.first.event_type;
        const venue = g.first.venue;
        const city = g.first.city;
        const isMulti = g.items.length > 1;
        return (
          <div key={g.event_id} className="event-group-card" data-testid={`event-group-${g.event_id}`}>
            <div className="event-group-head">
              <div>
                <div className="event-group-title">{evType || "Event"} — {formatDate(evDate)}</div>
                <div className="event-group-sub">{venue}{city ? `, ${city}` : ""} · {g.items.length} artist{isMulti ? "s" : ""}</div>
              </div>
              <div className="event-group-actions">
                <button
                  className="btn btn-ghost btn-xs"
                  onClick={() => window.open(`/recap/${g.event_id}`, "_blank", "noopener")}
                  data-testid={`event-share-${g.event_id}`}
                >💬 Share Recap</button>
              </div>
            </div>
            <div className="event-group-artists">
              {g.items.map((b) => {
                const info = artistCache[b.artist_id] || {};
                return (
                <div key={b.id} className="event-group-artist-row" data-testid={`event-artist-${b.id}`}>
                  <div className="event-group-thumb">
                    <span>{info.emoji || "🎤"}</span>
                  </div>
                  <div>
                    <div className="fw-600 fs-13">{info.stage_name || "Artist"}</div>
                    <div className="text-muted fs-11">{info.category || b.event_type || ""} · {b.ref}</div>
                  </div>
                  <span className={`event-group-status-pill ${statusClass(b.status)}`}>
                    {statusLabel(b.status)}
                  </span>
                  {b.status === "pending_artist" && (
                    <button className="btn btn-ghost btn-xs" onClick={() => onAction(b.id, "cancel")} data-testid={`event-cancel-${b.id}`}>Cancel</button>
                  )}
                </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function statusClass(s) {
  if (["confirmed", "started"].includes(s)) return "confirmed";
  if (["completed", "reviewed"].includes(s)) return "completed";
  if (["cancelled", "rejected", "auto_expired"].includes(s)) return "cancelled";
  return "pending";
}
function statusLabel(s) {
  const map = {
    pending_payment: "Awaiting Payment",
    pending_artist: "Awaiting Artist",
    confirmed: "Confirmed",
    started: "In Progress",
    completed: "Completed",
    reviewed: "Reviewed",
    cancelled: "Cancelled",
    rejected: "Rejected",
    auto_expired: "Expired",
  };
  return map[s] || s;
}
function formatDate(s) {
  if (!s) return "";
  try {
    return new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
  } catch { return s; }
}

