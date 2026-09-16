import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Nav from "../components/Nav";
import api, { fmtINRFull, formatApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import useHighlightRow from "../lib/useHighlightRow";
import {
  AdminMaster, AdminBoost, AdminTemplates, AdminFAQs,
  AdminCMS, AdminBroadcast, AdminSettings, AdminAudit, AdminReports,
  AdminReviewsModeration, AdminProviders, AdminBlogs,
} from "./admin/AdminEnterprise";
import AdminConcierge from "./admin/AdminConcierge";
import AdminOutstationReport from "./admin/AdminOutstationReport";
import AdminQuestionEditor from "./admin/AdminQuestionEditor";
import AdminSubscriptions from "./admin/AdminSubscriptions";
import AdminCategoryRequests from "./admin/AdminCategoryRequests";
import AdminCityRequests from "./admin/AdminCityRequests";
import AdminAdmins from "./admin/AdminAdmins";
import AdminPaymentGateway from "./admin/AdminPaymentGateway";
import AdminPaymentReconciliation from "./admin/AdminPaymentReconciliation";
import AdminPlatformSettings from "./admin/AdminPlatformSettings";
import { PayoutConsole, AtRiskDashboard } from "../components/PaymentPayoutWidgets";
import {
  AdminPayoutRetryQueue, AdminReportSchedules, AdminManagerScorecard,
  AdminWhatsAppTemplates, AdminReportSnapshots,
} from "./admin/AdminIter88";
import { AdminAnalyticsDashboard } from "./Iter92Pages";

// Iter 57 — Sidebar → required permission. If the current admin lacks the
// permission, the item is hidden from the sidebar entirely. `null` means
// "any admin can see this" (overview is always shown as an empty state).
const SIDEBAR = [
  { id: "overview",         label: "📊 Overview",              perm: null },
  { id: "artists",          label: "🎤 Artists",               perm: "artists.moderate" },
  { id: "bookings",         label: "📋 Bookings",              perm: "bookings.view" },
  { id: "concierge",        label: "🎩 Concierge",             perm: "bookings.view" },
  { id: "kyc",              label: "🪪 KYC Queue",             perm: "artists.moderate" },
  { id: "category-requests", label: "🎼 Category Requests",     perm: "artists.moderate" },
  { id: "city-requests",    label: "📍 City Requests",         perm: "artists.moderate" },
  { id: "refunds",          label: "↩️ Refunds",               perm: "payments.refund" },
  { id: "refund-audit",     label: "🔎 Refund Auditor",         perm: "payments.refund" },
  { id: "bulk-payouts",     label: "📦 Bulk Payouts",           perm: "payments.view" },
  { id: "commercial-deals", label: "💼 Commercial Deals",       perm: "payments.refund" },
  { id: "coupons",          label: "🎫 Coupons",               perm: "cms.manage" },
  { id: "subscriptions",    label: "💳 Subscriptions",         perm: "subscriptions.manage" },
  { id: "users",            label: "👥 Users",                 perm: "users.view" },
  { id: "disputes",         label: "⚖️ Disputes",              perm: "bookings.override" },
  { id: "master",           label: "🗂️ Master Data",           perm: "settings.manage" },
  { id: "questionnaire",    label: "📝 Questionnaire",         perm: "cms.manage" },
  { id: "boost",            label: "🚀 Boost Manager",         perm: "artists.moderate" },
  { id: "outstation-report",label: "📍 Outstation Report",     perm: "analytics.view" },
  { id: "templates",        label: "📧 Templates",             perm: "cms.manage" },
  { id: "faqs",             label: "❓ FAQs",                  perm: "cms.manage" },
  { id: "cms",              label: "📄 CMS Pages",             perm: "cms.manage" },
  { id: "blogs",            label: "📝 Blogs",                 perm: "cms.manage" },
  { id: "broadcast",        label: "📢 Broadcast",             perm: "notifications.send" },
  { id: "reports",          label: "📈 Reports",               perm: "analytics.view" },
  { id: "reviews-mod",      label: "🛡️ Reviews Moderation",    perm: "artists.moderate" },
  { id: "providers",        label: "🔌 Providers",             perm: "settings.manage" },
  { id: "payment-gateway",  label: "💳 Payment Gateway",       perm: "settings.manage" },
  { id: "payment-recon",    label: "🧾 Payment Reconciliation", perm: "payments.view" },
  { id: "analytics",        label: "📊 Founder KPIs",           perm: "analytics.view" },
  { id: "payout-console",   label: "💰 Payout Console",         perm: "payments.view" },
  { id: "payout-retry",     label: "🔁 Payout Retry Queue",     perm: "payments.view" },
  { id: "manager-scorecard", label: "🏅 Manager Scorecard",     perm: "analytics.view" },
  { id: "report-schedules", label: "📅 Report Schedules",       perm: "analytics.view" },
  { id: "report-snapshots", label: "🗂️ Snapshot History",       perm: "analytics.view" },
  { id: "wa-templates",     label: "📱 WhatsApp Templates",     perm: "settings.manage" },
  { id: "at-risk",          label: "⚠️ At-Risk Bookings",       perm: "bookings.view" },
  { id: "platform-settings", label: "🏗️ Platform Settings (v2)", perm: "settings.manage" },
  { id: "settings",         label: "📢 Site Notices", perm: "settings.manage" },
  { id: "admins",           label: "🛡️ Admin Team",           perm: "admins.manage" },
  { id: "audit", label: "🛡️ Audit Logs", perm: "admins.manage" },
];

export default function AdminDashboard() {
  const { user } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [tab, setTab] = useState(() => {
    // Iter 63.5 — read ?tab= from URL so notification click-through lands on the right tab.
    const p = new URLSearchParams(window.location.search).get("tab");
    return p || "overview";
  });
  const [stats, setStats] = useState({});
  // Iter 57 — Read the caller's RBAC permissions so we can HIDE sidebar
  // modules they lack the permission for. Backend still enforces access —
  // this is a UX polish so admins don't stare at empty error states for
  // sections they can't touch. `null` while loading = show nothing to be safe.
  const [myPerms, setMyPerms] = useState(null);

  useEffect(() => {
    if (!user) { nav("/login"); return; }
    if (user.role !== "admin") { nav("/"); return; }
    // Stats endpoint requires analytics.view — silently fall back to {} if 403.
    api.get("/admin/stats").then(r => setStats(r.data)).catch(() => {});
    api.get("/admin/rbac/me")
      .then((r) => setMyPerms(new Set(r.data.admin_permissions || [])))
      .catch(() => setMyPerms(new Set()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  if (!user || user.role !== "admin") return null;

  const visibleSidebar = SIDEBAR.filter((x) => !x.perm || (myPerms && myPerms.has(x.perm)));
  const canSee = (perm) => !perm || (myPerms && myPerms.has(perm));

  // If the currently-selected tab isn't visible anymore (e.g. permissions
  // narrowed since login), fall back to Overview so we don't render a
  // hidden section's content.
  const effectiveTab = visibleSidebar.some((x) => x.id === tab) ? tab : "overview";

  return (
    <div className="dash-wrap" data-testid="admin-dashboard">
      <aside className="sidebar">
        <Link to="/" className="logo mb-20"><div className="logo-mark">B</div><span style={{ fontSize: 18 }}>Book<span className="gold">Talent</span></span></Link>
        <div className="sb-section">Admin Panel</div>
        {visibleSidebar.map((x) => (
          <div key={x.id} className={`sb-item ${effectiveTab === x.id ? "active" : ""}`} onClick={() => setTab(x.id)} data-testid={`sb-${x.id}`}>
            {x.label}
          </div>
        ))}
      </aside>

      <main className="dash-content">
        <Nav />
        <div style={{ marginTop: 18 }}>
          {effectiveTab === "overview" && (
            <>
              <div className="dash-head">
                <div><h1>Platform Overview</h1><p>All systems operational</p></div>
              </div>

              <div className="kpi-grid">
                <Kpi icon="💰" cls="kpi-icon-gold" num={fmtINRFull(stats.gmv || 0)} label="Marketplace GMV (artist fees)" />
                <Kpi icon="📋" cls="kpi-icon-purple" num={stats.total_bookings || 0} label="Bookings" />
                <Kpi icon="👥" cls="kpi-icon-green" num={stats.total_users || 0} label="Users" />
                <Kpi icon="🏦" cls="kpi-icon-blue" num={fmtINRFull(stats.bookTalent_total_collected || 0)} label="BookTalent Total Collected" />
              </div>

              <div className="kpi-grid mb-24">
                <Kpi icon="🧾" cls="kpi-icon-gold" num={fmtINRFull(stats.platform_revenue || 0)} label="Platform Service Fee (5%)" />
                <Kpi icon="🇮🇳" cls="kpi-icon-amber" num={fmtINRFull(stats.gst_collected || 0)} label="GST Collected (18%)" />
                <Kpi icon="💎" cls="kpi-icon-purple" num={fmtINRFull(stats.subscription_revenue || 0)} label="Subscription Revenue" />
                <Kpi icon="🚀" cls="kpi-icon-blue" num={fmtINRFull(stats.boost_revenue || 0)} label="Boost Revenue" />
              </div>

              <div className="kpi-grid mb-24">
                <Kpi icon="↩️" cls="kpi-icon-amber" num={stats.pending_refunds || 0} label="Refunds Pending" />
                <Kpi icon="🪪" cls="kpi-icon-blue" num={stats.pending_kyc || 0} label="KYC Pending" />
                <Kpi icon="⚠️" cls="kpi-icon-red" num={stats.open_disputes || 0} label="Open Disputes" />
                <Kpi icon="⭐" cls="kpi-icon-gold" num={stats.avg_rating || 0} label="Avg. Artist Rating" />
              </div>

              {/* Feb-2026 requirement KPIs — funnel & operational health */}
              <div className="kpi-grid mb-24" data-testid="admin-kpis-req">
                <Kpi icon="🎯" cls="kpi-icon-purple" num={stats.new_leads || 0} label="New Leads" />
                <Kpi icon="✅" cls="kpi-icon-green" num={stats.active_bookings || 0} label="Active Bookings" />
                <Kpi icon="📆" cls="kpi-icon-blue" num={stats.upcoming_events || 0} label="Upcoming Events" />
                <Kpi icon="📜" cls="kpi-icon-amber" num={stats.agreements_pending || 0} label="Agreements Pending" />
              </div>
              <div className="kpi-grid mb-24">
                <Kpi icon="💳" cls="kpi-icon-amber" num={stats.customer_payment_pending || 0} label="Customer Payments Pending" />
                <Kpi icon="⏰" cls="kpi-icon-red" num={stats.overdue_payments || 0} label="Overdue Payments" />
                <Kpi icon="💸" cls="kpi-icon-purple" num={stats.artist_payout_pending || 0} label="Artist Payouts Pending" />
                <Kpi icon="💰" cls="kpi-icon-gold" num={fmtINRFull(stats.remaining_amount || 0)} label="Remaining ₹ Across Bookings" />
              </div>
              <div className="kpi-grid mb-24">
                <Kpi icon="🎭" cls="kpi-icon-purple" num={stats.agency_bookings || 0} label="Agency Bookings" />
              </div>
            </>
          )}

          {effectiveTab === "overview" && <OverviewAdmin stats={stats} />}
          {effectiveTab === "artists" && <AdminArtists toast={toast} />}
          {effectiveTab === "bookings" && <AdminBookings />}
          {effectiveTab === "concierge" && <AdminConcierge toast={toast} />}
          {effectiveTab === "outstation-report" && <AdminOutstationReport toast={toast} />}
          {effectiveTab === "kyc" && <AdminKYC toast={toast} />}
          {effectiveTab === "category-requests" && <AdminCategoryRequests toast={toast} />}
          {effectiveTab === "city-requests" && <AdminCityRequests toast={toast} />}
          {effectiveTab === "refunds" && <AdminRefunds toast={toast} />}
          {effectiveTab === "refund-audit" && <AdminRefundAuditor toast={toast} />}
          {effectiveTab === "bulk-payouts" && <AdminBulkPayouts toast={toast} />}
          {effectiveTab === "commercial-deals" && <AdminCommercialDeals toast={toast} />}
          {effectiveTab === "coupons" && <AdminCoupons toast={toast} />}
          {effectiveTab === "subscriptions" && <AdminSubscriptions toast={toast} />}
          {effectiveTab === "admins" && <AdminAdmins toast={toast} />}
          {effectiveTab === "users" && <AdminUsers toast={toast} />}
          {effectiveTab === "disputes" && <AdminDisputes toast={toast} />}
          {effectiveTab === "master" && <AdminMaster toast={toast} />}
          {effectiveTab === "questionnaire" && <AdminQuestionEditor />}
          {effectiveTab === "boost" && <AdminBoost toast={toast} />}
          {effectiveTab === "templates" && <AdminTemplates toast={toast} />}
          {effectiveTab === "faqs" && <AdminFAQs toast={toast} />}
          {effectiveTab === "cms" && <AdminCMS toast={toast} />}
          {effectiveTab === "blogs" && <AdminBlogs toast={toast} />}
          {effectiveTab === "broadcast" && <AdminBroadcast toast={toast} />}
          {effectiveTab === "reports" && <AdminReports />}
          {effectiveTab === "reviews-mod" && <AdminReviewsModeration toast={toast} />}
          {effectiveTab === "providers" && <AdminProviders toast={toast} />}
          {effectiveTab === "payment-gateway" && <AdminPaymentGateway toast={toast} />}
          {effectiveTab === "payment-recon" && <AdminPaymentReconciliation toast={toast} />}
          {effectiveTab === "platform-settings" && <AdminPlatformSettings />}
          {effectiveTab === "at-risk" && <AtRiskDashboard />}
          {effectiveTab === "analytics" && <AdminAnalyticsDashboard />}
          {effectiveTab === "payout-console" && <PayoutConsole />}
          {effectiveTab === "payout-retry" && <AdminPayoutRetryQueue />}
          {effectiveTab === "manager-scorecard" && <AdminManagerScorecard />}
          {effectiveTab === "report-schedules" && <AdminReportSchedules />}
          {effectiveTab === "report-snapshots" && <AdminReportSnapshots />}
          {effectiveTab === "wa-templates" && <AdminWhatsAppTemplates />}
          {effectiveTab === "settings" && <AdminSettings toast={toast} />}
          {effectiveTab === "audit" && <AdminAudit />}
        </div>
      </main>
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

function OverviewAdmin({ stats }) {
  return (
    <div className="card card-pad" data-testid="admin-overview">
      <h3 className="font-serif fs-20 fw-700 mb-16">Quick Stats</h3>
      <div className="grid grid-3">
        <div className="card card-pad" data-testid="stat-total-artists"><div className="text-muted fs-11">Total Artists</div><div className="fs-20 fw-700">{stats.total_artists ?? 0}</div></div>
        <div className="card card-pad" data-testid="stat-total-customers"><div className="text-muted fs-11">Total Customers</div><div className="fs-20 fw-700">{stats.total_customers ?? 0}</div></div>
        <div className="card card-pad" data-testid="stat-avg-rating"><div className="text-muted fs-11">Avg Rating</div><div className="fs-20 fw-700 text-gold">★ {stats.avg_rating ?? 0}</div></div>
        <div className="card card-pad" data-testid="stat-bookings-today"><div className="text-muted fs-11">Bookings Today</div><div className="fs-20 fw-700">{stats.bookings_today ?? 0}</div></div>
        <div className="card card-pad" data-testid="stat-pending-bookings"><div className="text-muted fs-11">Pending Bookings</div><div className="fs-20 fw-700">{stats.pending_bookings ?? 0}</div></div>
      </div>
    </div>
  );
}

function AdminArtists({ toast }) {
  const [list, setList] = useState([]);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const reload = () => api.get("/admin/artists").then((r) => setList(r.data)).catch(() => setList([]));
  useEffect(() => { reload(); }, []);
  const feature = async (uid) => { await api.post(`/admin/artists/${uid}/feature`); toast("Feature toggled"); reload(); };
  const suspend = async (uid) => {
    const r = await api.post(`/admin/artists/${uid}/suspend`);
    toast(r.data.suspended ? "Suspended" : "Unsuspended");
    reload();
  };
  return (
    <div className="card" data-testid="admin-artists">
      <div className="card-head"><div className="card-title">🎤 Artists ({list.length})</div></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Artist</th><th>Category</th><th>City</th><th>Rating</th><th>Events</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {list.map((a) => (
              <tr key={a.id} data-testid={`artist-row-${a.user_id}`}>
                <td><div className="fw-600">{a.stage_name}</div><div className="text-muted fs-11">{a.user?.email}</div></td>
                <td>{a.category}</td>
                <td>{a.city}</td>
                <td className="text-gold">★ {a.rating_avg?.toFixed(1)}</td>
                <td>{a.events_done}</td>
                <td>
                  {a.kyc_status === "approved" && <span className="pill pill-green">Verified</span>}
                  {a.kyc_status === "pending" && <span className="pill pill-amber">Pending</span>}
                  {a.is_featured && <span className="pill pill-gold ml-8" style={{ marginLeft: 4 }}>Featured</span>}
                  {a.user?.suspended && <span className="pill pill-red" style={{ marginLeft: 4 }}>Suspended</span>}
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button className="btn btn-ghost btn-xs" onClick={() => setEditing(a)} data-testid={`edit-${a.user_id}`}>Edit</button>
                    <button className="btn btn-ghost btn-xs" onClick={() => feature(a.user_id)} data-testid={`feature-${a.user_id}`}>{a.is_featured ? "Unfeature" : "Feature"}</button>
                    <button className={`btn btn-xs ${a.user?.suspended ? "btn-green" : "btn-amber"}`} onClick={() => suspend(a.user_id)} data-testid={`suspend-${a.user_id}`}>
                      {a.user?.suspended ? "Unsuspend" : "Suspend"}
                    </button>
                    <button className="btn btn-red btn-xs" onClick={() => setDeleting({ id: a.user_id, label: a.stage_name })} data-testid={`delete-${a.user_id}`}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <UserEditModal
          user={editing.user}
          profile={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); toast("Saved"); }}
          toast={toast}
        />
      )}
      {deleting && (
        <UserDeleteModal
          target={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => { setDeleting(null); reload(); }}
          toast={toast}
        />
      )}
    </div>
  );
}

function AdminBookings() {
  const [list, setList] = useState([]);
  useEffect(() => { api.get("/admin/bookings").then(r => setList(r.data)).catch(() => setList([])); }, []);
  // Iter 65 — booking notification click → highlight the correct row.
  useHighlightRow({ prefix: "booking-row", dataKey: list.length });
  return (
    <div className="card" data-testid="admin-bookings">
      <div className="card-head"><div className="card-title">📋 All Bookings ({list.length})</div></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Ref</th><th>Customer</th><th>Event</th><th>Date</th><th>Amount</th><th>Status</th></tr></thead>
          <tbody>
            {list.map((b) => (
              <tr key={b.id} data-testid={`booking-row-${b.id}`}>
                <td className="font-mono text-gold fs-11">{b.ref}</td>
                <td>{b.customer_name}</td>
                <td>{b.event_type}<br/><span className="text-muted fs-11">{b.venue}, {b.city}</span></td>
                <td className="fs-12">{b.event_date}</td>
                <td className="text-gold font-serif fs-16 fw-700">{fmtINRFull(b.pricing?.total || 0)}</td>
                <td>
                  <span className="pill pill-purple">{b.status}</span>
                  {/* Iter 75.5 — Show cancellation attribution + reason so
                      admins can audit every cancelled booking at a glance. */}
                  {b.status === "cancelled" && b.cancel_reason && (
                    <div
                      data-testid={`admin-cancel-info-${b.id}`}
                      className="fs-11 mt-4"
                      style={{ color: "rgba(255,107,129,0.85)", lineHeight: 1.35, maxWidth: 260 }}
                      title={b.cancel_reason}
                    >
                      <span style={{ opacity: 0.75 }}>By {b.cancelled_by || "—"}:</span>{" "}
                      {b.cancel_reason.length > 60 ? b.cancel_reason.slice(0, 57) + "…" : b.cancel_reason}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminKYC({ toast }) {
  const [list, setList] = useState([]);
  const [status, setStatus] = useState("pending");
  const [expanded, setExpanded] = useState(null);
  const [approveState, setApproveState] = useState(null); // { artist_id, name }
  const reload = () => api.get(`/admin/kyc?status=${status}`).then((r) => setList(r.data)).catch(() => setList([]));
  // `reload` is a new closure every render — including it triggers infinite fetch.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [status]);

  const decide = async (artist_id, decision, extra = {}) => {
    // Iter 98 — Approve now routes through a modal that captures
    // artist_type + percentage_deal so the commercial deal is set at
    // the moment of approval (matching Sec 4 of the business concept).
    if (decision === "approve" && !extra._skipModal) {
      const row = list.find((k) => k.user_id === artist_id);
      setApproveState({
        artist_id,
        name: `${row?.user?.first_name || ""} ${row?.user?.last_name || ""}`.trim() || "Artist",
      });
      return;
    }
    let reason = "";
    if (decision === "reject" || decision === "request_resubmission") {
      reason = window.prompt(`Reason for ${decision === "reject" ? "rejection" : "resubmission"}:`, "") || "";
      if (!reason.trim()) { toast("Reason is required", "error"); return; }
    }
    try {
      await api.post("/admin/kyc/decide", { artist_id, decision, reason, ...extra });
      toast(`KYC ${decision === "approve" ? "approved" : decision === "reject" ? "rejected" : "resubmission requested"}`);
      reload();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  return (
    <div className="card" data-testid="admin-kyc">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center" }}>
        <div className="card-title">🪪 KYC Queue ({list.length})</div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="input" style={{ width: 200 }} data-testid="kyc-status-filter">
          <option value="pending">Pending</option>
          <option value="needs_resubmission">Needs Resubmission</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>
      <div style={{ padding: 14 }}>
        {list.length === 0 && <div className="empty"><div className="empty-icon">🪪</div><div className="empty-title">No KYC records</div></div>}
        {list.map((k) => {
          const isOpen = expanded === k.user_id;
          return (
            <div key={k.user_id} className="card card-pad mb-12" data-testid={`kyc-row-${k.user_id}`} style={{ marginBottom: 12 }}>
              <div className="flex items-center gap-16">
                <div className="avatar">{k.user?.first_name?.[0]}</div>
                <div style={{ flex: 1 }}>
                  <div className="fw-600">
                    {k.user?.first_name} {k.user?.last_name}
                    {k.artist_profile?.stage_name && <span className="text-muted fs-12" style={{ marginLeft: 8 }}>· {k.artist_profile.stage_name}</span>}
                  </div>
                  <div className="text-muted fs-12">
                    {k.user?.email} · Submitted {k.submitted_at?.slice(0, 10)} ·{" "}
                    <span className={`pill pill-${k.status === "approved" ? "green" : k.status === "rejected" ? "red" : "amber"}`}>{k.status}</span>
                    {/* Iter 90 — v2 state visibility */}
                    {k.v2_status && k.v2_status !== k.status && (
                      <span className="pill pill-gold" style={{ marginLeft: 4, fontSize: 10 }} title="Post-approval v2 state" data-testid={`kyc-v2-${k.user_id}`}>
                        {k.v2_status}
                      </span>
                    )}
                  </div>
                  <div className="text-muted fs-11 mt-4">Docs: {Object.keys(k.documents || {}).join(", ") || "—"}{k.pan_number && ` · PAN ${k.pan_number}`}{k.aadhaar_number_masked && ` · Aadhaar ${k.aadhaar_number_masked}`}</div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(isOpen ? null : k.user_id)} data-testid={`kyc-view-${k.user_id}`}>{isOpen ? "Hide" : "View"}</button>
                {k.status === "pending" || k.status === "needs_resubmission" ? (
                  <>
                    <button className="btn btn-green btn-sm" onClick={() => decide(k.user_id, "approve")} data-testid={`kyc-approve-${k.user_id}`}>✓ Approve</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => decide(k.user_id, "request_resubmission")} data-testid={`kyc-resub-${k.user_id}`}>↻ Resubmit</button>
                    <button className="btn btn-red btn-sm" onClick={() => decide(k.user_id, "reject")} data-testid={`kyc-reject-${k.user_id}`}>✕ Reject</button>
                  </>
                ) : null}
                {/* Iter 90b — Agreement viewer for artists past T&C acceptance */}
                {["agreement_generated", "live"].includes(k.v2_status) && (
                  <>
                    <a
                      className="btn btn-ghost btn-sm"
                      href={`${api.defaults.baseURL}/admin/agreements/${k.user_id}/download`}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid={`kyc-agreement-view-${k.user_id}`}
                      title="Open signed agreement PDF"
                    >📄 View Agreement</a>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        if (!window.confirm("Re-issue agreement? Old one will be archived with audit trail.")) return;
                        try {
                          await api.post(`/admin/agreements/${k.user_id}/reissue`);
                          toast("Agreement re-issued successfully", "success");
                          reload();
                        } catch (e) { toast(formatApiError(e), "error"); }
                      }}
                      data-testid={`kyc-agreement-reissue-${k.user_id}`}
                      title="Regenerate PDF (e.g. after commission change)"
                    >↻ Re-issue</button>
                  </>
                )}
              </div>
              {isOpen && k.documents && (
                <div className="grid grid-3 gap-12 mt-12" style={{ marginTop: 12 }} data-testid={`kyc-docs-${k.user_id}`}>
                  {Object.entries(k.documents).map(([field, mid]) => (
                    <div key={field} className="card card-pad" style={{ textAlign: "center" }}>
                      <div className="text-muted fs-11 mb-4" style={{ marginBottom: 4 }}>{field.toUpperCase()}</div>
                      <a href={`${api.defaults.baseURL}/media/${mid}`} target="_blank" rel="noreferrer" data-testid={`kyc-doc-${k.user_id}-${field}`}>
                        <img src={`${api.defaults.baseURL}/media/${mid}/thumb`} alt={field} style={{ maxWidth: "100%", borderRadius: 8 }} onError={(e) => { e.target.style.display = "none"; e.target.parentElement.innerHTML += '<div style="font-size:48px">📄</div>'; }} />
                      </a>
                    </div>
                  ))}
                </div>
              )}
              {k.reason && (k.status === "rejected" || k.status === "needs_resubmission") && (
                <div className="text-muted fs-12 mt-8" style={{ marginTop: 8 }}>Reason: {k.reason}</div>
              )}
            </div>
          );
        })}
      </div>
      {approveState && (
        <KycApproveModal
          artist={approveState}
          onCancel={() => setApproveState(null)}
          onConfirm={async ({ artist_type, percentage_deal }) => {
            setApproveState(null);
            await decide(approveState.artist_id, "approve", {
              _skipModal: true, artist_type, percentage_deal,
            });
          }}
        />
      )}
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// KycApproveModal — captures artist_type ("normal" / "service") and, if
// service, the percentage_deal. Submitted as part of /admin/kyc/decide
// so the artist's commercial terms are locked at approval time.
// ────────────────────────────────────────────────────────────────────────
function KycApproveModal({ artist, onCancel, onConfirm }) {
  const [type, setType] = useState("normal");
  const [pct, setPct] = useState(10);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (type === "service" && (!pct || pct <= 0 || pct > 50)) {
      alert("Enter a BookTalent commission percentage between 1 and 50.");
      return;
    }
    setBusy(true);
    await onConfirm({
      artist_type: type,
      percentage_deal: type === "service" ? Number(pct) : 0,
    });
    setBusy(false);
  };

  return (
    <div
      data-testid="kyc-approve-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(6,4,20,0.82)",
        display: "grid", placeItems: "center", zIndex: 900, padding: 16,
        backdropFilter: "blur(6px)",
      }}
      onClick={onCancel}>
      <div className="card card-pad"
        style={{ maxWidth: 480, width: "100%", background: "#0F0F1B" }}
        onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif fw-700 fs-18 mb-4">Approve KYC · {artist.name}</h3>
        <p className="text-muted fs-12 mb-12">
          Set the commercial deal now. This is what the customer sees on every future checkout.
        </p>

        <div className="field-label mb-4">Artist type</div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <label
            data-testid="kyc-type-normal"
            onClick={() => setType("normal")}
            style={{
              flex: 1, padding: 12, borderRadius: 10, cursor: "pointer",
              border: type === "normal" ? "1.5px solid #D4AF37" : "1.5px solid rgba(255,255,255,0.1)",
              background: type === "normal" ? "rgba(212,175,55,0.08)" : "rgba(255,255,255,0.03)",
            }}>
            <div className="fw-700 fs-13">Normal Artist</div>
            <div className="text-muted fs-11 mt-4">
              Customer pays a 5% Platform Fee. No commission from artist.
            </div>
          </label>
          <label
            data-testid="kyc-type-service"
            onClick={() => setType("service")}
            style={{
              flex: 1, padding: 12, borderRadius: 10, cursor: "pointer",
              border: type === "service" ? "1.5px solid #6ee7a8" : "1.5px solid rgba(255,255,255,0.1)",
              background: type === "service" ? "rgba(110,231,168,0.08)" : "rgba(255,255,255,0.03)",
            }}>
            <div className="fw-700 fs-13">BookTalent Service Artist</div>
            <div className="text-muted fs-11 mt-4">
              Customer's 5% Platform Fee waived. Artist gives BookTalent a % commission.
            </div>
          </label>
        </div>

        {type === "service" && (
          <div className="mb-12" data-testid="kyc-service-pct-wrap">
            <div className="field-label mb-4">BookTalent Commission (%)</div>
            <input
              type="number"
              min={1}
              max={50}
              step={0.5}
              className="input"
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              data-testid="kyc-service-pct"
              placeholder="10"
            />
            <div className="text-muted fs-11 mt-4">
              e.g. 10 → on a ₹1,00,000 booking, BookTalent = ₹10,000 · Artist = ₹90,000.
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn btn-ghost btn-sm" onClick={onCancel} data-testid="kyc-approve-cancel">Cancel</button>
          <button className="btn btn-green btn-sm" onClick={submit} disabled={busy} data-testid="kyc-approve-confirm">
            {busy ? "Approving…" : "✓ Approve & Set Deal"}
          </button>
        </div>
      </div>
    </div>
  );
}


function AdminRefunds({ toast }) {
  const [list, setList] = useState({ items: [] });
  const [busy, setBusy] = useState(null);
  const reload = () => api.get("/admin/refunds")
    .then(r => setList(r.data || { items: [] }))
    .catch(() => setList({ items: [] }));
  useEffect(() => { reload(); }, []);
  // Iter 65 — support ?highlight=<payment_id> from refund notifications.
  const items = list.items || [];
  useHighlightRow({ prefix: "refund-row", dataKey: items.length });
  const retryRefund = async (paymentId) => {
    if (!window.confirm("Retry Easebuzz refund for this payment?")) return;
    setBusy(paymentId);
    try {
      const r = await api.post(`/admin/refunds/${paymentId}/retry`);
      toast(r.data?.ok ? "Refund succeeded" : (r.data?.reason || "Attempt made"),
            r.data?.ok ? "success" : "warn");
      reload();
    } catch (e) { toast(e?.response?.data?.detail || "Refund retry failed", "error"); }
    setBusy(null);
  };
  return (
    <div className="card" data-testid="admin-refunds">
      <div className="card-head">
        <div className="card-title">↩️ Automatic Refunds ({items.length})</div>
        <div className="text-muted fs-12">Refunds are triggered automatically via Easebuzz when bookings are rejected, cancelled or expire. No manual processing needed.</div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>When</th><th>Customer</th><th>Artist</th><th>Amount</th><th>Reason</th><th>Status</th><th>Ref</th><th></th></tr></thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={8} className="empty">No refunds yet</td></tr>}
            {items.map((w) => (
              <tr key={w.payment_id} data-testid={`refund-row-${w.payment_id}`}>
                <td className="text-muted fs-12">{(w.refund_at || "").slice(0, 16).replace("T", " ")}</td>
                <td>{w.customer_name || "—"}<div className="text-muted fs-11">{w.customer_email || ""}</div></td>
                <td className="fs-12">{w.artist_name || "—"}</td>
                <td className="text-gold font-serif fs-14 fw-700">{fmtINRFull(w.refund_amount || 0)}</td>
                <td className="fs-11">{w.refund_reason || "—"}</td>
                <td className="fs-12" style={{ textTransform: "capitalize" }}>{(w.refund_status || "—").replace(/_/g, " ")}</td>
                <td><code className="fs-11">{w.refund_id || w.easebuzz_id || "—"}</code></td>
                <td>
                  {w.refund_status === "failed" && (
                    <button className="btn btn-green btn-xs" disabled={busy === w.payment_id}
                      onClick={() => retryRefund(w.payment_id)}
                      data-testid={`process-refund-${w.payment_id}`}>
                      {busy === w.payment_id ? "Processing…" : "Retry"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminCoupons({ toast }) {
  const [analytics, setAnalytics] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [drillIn, setDrillIn] = useState(null);
  const [ledger, setLedger] = useState([]);
  const [form, setForm] = useState({ code: "", description: "", discount_type: "percent", discount_value: 10, max_uses: 100, per_user_limit: 1, expires_at: "2026-12-31", min_order: 0, applies_to: "all", active: true });
  const reload = () => api.get("/admin/coupons/analytics").then(r => setAnalytics(r.data)).catch(() => setAnalytics({}));
  useEffect(() => { reload(); }, []);
  const create = async () => {
    try { await api.post("/admin/coupons", form); toast("Created"); setShowAdd(false); reload(); }
    catch (e) { toast(formatApiError(e), "error"); }
  };
  const del = async (id) => { if (!window.confirm("Delete coupon?")) return; await api.delete(`/admin/coupons/${id}`); reload(); };
  const drill = async (c) => {
    setDrillIn(c);
    const r = await api.get(`/admin/coupons/${c.id}/redemptions`);
    setLedger(r.data);
  };

  return (
    <div className="card" data-testid="admin-coupons">
      <div className="card-head">
        <div className="card-title">🎫 Coupons & Analytics ({analytics.length})</div>
        <button className="btn btn-gold btn-sm" onClick={() => setShowAdd(true)} data-testid="add-coupon-btn">+ New Coupon</button>
      </div>

      <div className="kpi-grid" style={{ padding: "12px 14px 0" }}>
        <div className="kpi" data-testid="coupon-kpi-uses"><div className="kpi-num">{analytics.reduce((s, c) => s + c.uses, 0)}</div><div className="kpi-label">Total Redemptions</div></div>
        <div className="kpi" data-testid="coupon-kpi-discount"><div className="kpi-num text-gold">{fmtINRFull(analytics.reduce((s, c) => s + c.total_discount, 0))}</div><div className="kpi-label">Total Discount Given</div></div>
        <div className="kpi" data-testid="coupon-kpi-gmv"><div className="kpi-num text-gold">{fmtINRFull(analytics.reduce((s, c) => s + c.total_gmv, 0))}</div><div className="kpi-label">Coupon-Driven GMV</div></div>
        <div className="kpi" data-testid="coupon-kpi-active"><div className="kpi-num">{analytics.filter(c => c.active).length}</div><div className="kpi-label">Active Coupons</div></div>
      </div>

      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Code</th><th>Discount</th><th>Uses</th><th>Discount Given</th><th>GMV Driven</th><th>Expires</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {analytics.map((c) => (
              <tr key={c.id} data-testid={`coupon-${c.code}`}>
                <td><code style={{ color: "var(--gold-light)", background: "var(--gold-dim)", padding: "3px 8px", borderRadius: 5 }}>{c.code}</code></td>
                <td>{c.discount_type === "percent" ? `${c.discount_value}%` : fmtINRFull(c.discount_value)}</td>
                <td>{c.uses} / {c.max_uses}</td>
                <td className="text-gold">{fmtINRFull(c.total_discount)}</td>
                <td className="text-gold">{fmtINRFull(c.total_gmv)}</td>
                <td className="fs-12 text-muted">{c.expires_at}</td>
                <td><span className={`pill ${c.active ? "pill-green" : "pill-red"}`}>{c.active ? "Active" : "Inactive"}</span></td>
                <td>
                  <button className="btn btn-ghost btn-xs" onClick={() => drill(c)} data-testid={`drill-coupon-${c.id}`}>Ledger</button>
                  <button className="btn btn-red btn-xs" onClick={() => del(c.id)} style={{ marginLeft: 6 }} data-testid={`del-coupon-${c.id}`}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <div className="modal-bg" onClick={() => setShowAdd(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">New Coupon</div>
            <div className="field"><div className="field-label">Code</div><input className="field-input" value={form.code} onChange={(e) => setForm({...form, code: e.target.value.toUpperCase()})} data-testid="coupon-code" /></div>
            <div className="field"><div className="field-label">Description</div><input className="field-input" value={form.description} onChange={(e) => setForm({...form, description: e.target.value})} /></div>
            <div className="field-row">
              <div className="field"><div className="field-label">Type</div>
                <select className="field-input" value={form.discount_type} onChange={(e) => setForm({...form, discount_type: e.target.value})}>
                  <option value="percent">Percent</option><option value="flat">Flat ₹</option>
                </select>
              </div>
              <div className="field"><div className="field-label">Value</div><input type="number" className="field-input" value={form.discount_value} onChange={(e) => setForm({...form, discount_value: Number(e.target.value)})} data-testid="coupon-value" /></div>
            </div>
            <div className="field-row">
              <div className="field"><div className="field-label">Max Uses (total)</div><input type="number" className="field-input" value={form.max_uses} onChange={(e) => setForm({...form, max_uses: Number(e.target.value)})} /></div>
              <div className="field"><div className="field-label">Per User Limit</div><input type="number" className="field-input" value={form.per_user_limit} onChange={(e) => setForm({...form, per_user_limit: Number(e.target.value)})} /></div>
            </div>
            <div className="field-row">
              <div className="field"><div className="field-label">Min Order ₹</div><input type="number" className="field-input" value={form.min_order} onChange={(e) => setForm({...form, min_order: Number(e.target.value)})} /></div>
              <div className="field"><div className="field-label">Expires</div><input type="date" className="field-input" value={form.expires_at} onChange={(e) => setForm({...form, expires_at: e.target.value})} /></div>
            </div>
            <div className="field"><div className="field-label">Applies To</div>
              <select className="field-input" value={form.applies_to} onChange={(e) => setForm({...form, applies_to: e.target.value})}>
                <option value="all">All bookings</option>
                <option value="wedding">Weddings only</option>
                <option value="corporate">Corporate only</option>
                <option value="birthday">Birthdays only</option>
              </select>
            </div>
            <div className="flex gap-12">
              <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
              <button className="btn btn-gold" style={{ flex: 1 }} onClick={create} data-testid="save-coupon">Create</button>
            </div>
          </div>
        </div>
      )}

      {drillIn && (
        <div className="modal-bg" onClick={() => setDrillIn(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 720 }}>
            <div className="modal-title">Redemption Ledger — <code style={{ color: "var(--gold)" }}>{drillIn.code}</code></div>
            <p className="text-muted fs-13 mb-12">{ledger.length} redemptions · ₹{drillIn.total_discount.toLocaleString("en-IN")} discount given</p>
            <div className="table-wrap" style={{ maxHeight: 400, overflow: "auto" }}>
              <table className="table">
                <thead><tr><th>When</th><th>User</th><th>Booking</th><th>Discount</th><th>Total</th></tr></thead>
                <tbody>
                  {ledger.map((r) => (
                    <tr key={r.id} data-testid={`ledger-${r.id}`}>
                      <td className="fs-11 text-muted">{r.created_at?.slice(0, 19).replace("T", " ")}</td>
                      <td>{r.user?.email || r.user_id?.slice(0, 8)}</td>
                      <td><code className="fs-11">{r.booking?.ref || r.booking_id?.slice(0, 8)}</code></td>
                      <td className="text-gold">{fmtINRFull(r.discount_amount)}</td>
                      <td>{fmtINRFull(r.booking_total || 0)}</td>
                    </tr>
                  ))}
                  {ledger.length === 0 && <tr><td colSpan={5} className="text-muted" style={{ textAlign: "center", padding: 20 }}>No redemptions yet</td></tr>}
                </tbody>
              </table>
            </div>
            <button className="btn btn-ghost mt-12" onClick={() => setDrillIn(null)} style={{ marginTop: 12 }}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

function AdminUsers({ toast }) {
  const [list, setList] = useState([]);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const reload = () => api.get(`/admin/users${filter ? `?role=${filter}` : ""}`).then((r) => setList(r.data)).catch(() => setList([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [filter]);
  const suspend = async (uid) => {
    const r = await api.post(`/admin/artists/${uid}/suspend`);
    toast?.(r.data.suspended ? "Suspended" : "Unsuspended");
    reload();
  };

  return (
    <div className="card" data-testid="admin-users">
      <div className="card-head">
        <div className="card-title">👥 Users ({list.length})</div>
        <select className="field-input" style={{ maxWidth: 200 }} value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="user-role-filter">
          <option value="">All Roles</option>
          <option value="customer">Customers</option>
          <option value="artist">Artists</option>
          <option value="agency">Agencies</option>
          <option value="corporate">Corporate</option>
        </select>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Phone</th><th>Joined</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.id} data-testid={`user-${u.id}`}>
                <td>{u.first_name} {u.last_name}</td>
                <td className="text-muted">{u.email}</td>
                <td><span className="pill pill-purple">{u.role}</span></td>
                <td>{u.phone || "—"}</td>
                <td className="fs-12 text-muted">{u.created_at?.slice(0, 10)}</td>
                <td>
                  {u.suspended ? <span className="pill pill-red">Suspended</span> : <span className="pill pill-green">Active</span>}
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button className="btn btn-ghost btn-xs" onClick={() => setEditing(u)} data-testid={`user-edit-${u.id}`}>Edit</button>
                    <button className={`btn btn-xs ${u.suspended ? "btn-green" : "btn-amber"}`} onClick={() => suspend(u.id)} data-testid={`user-suspend-${u.id}`}>
                      {u.suspended ? "Unsuspend" : "Suspend"}
                    </button>
                    <button className="btn btn-red btn-xs" onClick={() => setDeleting({ id: u.id, label: `${u.first_name} ${u.last_name}`.trim() || u.email })} data-testid={`user-delete-${u.id}`}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <UserEditModal
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); toast?.("Saved"); }}
          toast={toast}
        />
      )}
      {deleting && (
        <UserDeleteModal
          target={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => { setDeleting(null); reload(); }}
          toast={toast}
        />
      )}
    </div>
  );
}

function UserDeleteModal({ target, onClose, onDone, toast }) {
  const [mode, setMode] = useState("soft");   // "soft" | "hard"
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const needConfirm = mode === "hard";
  const canDelete = !needConfirm || confirmText === "DELETE";
  const submit = async () => {
    setBusy(true);
    try {
      await api.delete(`/admin/users/${target.id}${mode === "hard" ? "?hard=true" : ""}`);
      toast?.(mode === "hard" ? "Permanently deleted" : "Deactivated");
      onDone();
    } catch (e) {
      toast?.(e?.response?.data?.detail || "Delete failed", "error");
      setBusy(false);
    }
  };
  return (
    <div className="popup-scrim" onClick={onClose} data-testid="user-delete-modal">
      <div className="popup-card" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
        <button className="popup-close" onClick={onClose} aria-label="Close">×</button>
        <h3 style={{ marginTop: 0 }}>Delete {target.label}</h3>
        <p className="text-muted fs-13" style={{ marginBottom: 16 }}>
          Pick how you want to remove this account. Deactivation is fully reversible; permanent deletion is not.
        </p>

        <label
          className="delete-mode-card"
          style={{
            display: "block", padding: 14, borderRadius: 10, marginBottom: 10,
            border: `1px solid ${mode === "soft" ? "var(--gold)" : "var(--glass-border)"}`,
            background: mode === "soft" ? "rgba(212,175,55,0.08)" : "transparent",
            cursor: "pointer",
          }}
          data-testid="delete-mode-soft"
        >
          <input type="radio" checked={mode === "soft"} onChange={() => setMode("soft")} style={{ marginRight: 8 }} />
          <span style={{ fontWeight: 700 }}>Deactivate (recommended)</span>
          <div className="text-muted fs-12" style={{ marginTop: 4, marginLeft: 22 }}>
            Suspends the login, anonymises the email. Bookings & financial history are preserved. Reversible.
          </div>
        </label>

        <label
          className="delete-mode-card"
          style={{
            display: "block", padding: 14, borderRadius: 10, marginBottom: 14,
            border: `1px solid ${mode === "hard" ? "#dc2626" : "var(--glass-border)"}`,
            background: mode === "hard" ? "rgba(220,38,38,0.08)" : "transparent",
            cursor: "pointer",
          }}
          data-testid="delete-mode-hard"
        >
          <input type="radio" checked={mode === "hard"} onChange={() => setMode("hard")} style={{ marginRight: 8 }} />
          <span style={{ fontWeight: 700, color: "#f87171" }}>Delete permanently</span>
          <div className="text-muted fs-12" style={{ marginTop: 4, marginLeft: 22 }}>
            Wipes the account, profile, packages, media & reviews. Bookings remain (by ID) so financials stay intact. This cannot be undone.
          </div>
        </label>

        {needConfirm && (
          <div className="field" style={{ marginBottom: 14 }}>
            <div className="field-label" style={{ color: "#f87171" }}>Type <b>DELETE</b> to confirm permanent removal</div>
            <input className="field-input" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} data-testid="delete-confirm-input" placeholder="DELETE" />
          </div>
        )}

        <div className="flex gap-8" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose} data-testid="delete-cancel">Cancel</button>
          <button
            className="btn btn-red"
            onClick={submit}
            disabled={busy || !canDelete}
            data-testid="delete-confirm"
          >
            {busy ? "Working…" : mode === "hard" ? "Delete permanently" : "Deactivate"}
          </button>
        </div>
      </div>
    </div>
  );
}

function UserEditModal({ user, profile, onClose, onSaved, toast }) {
  const [form, setForm] = useState({
    first_name: user?.first_name || "",
    last_name: user?.last_name || "",
    email: user?.email || "",
    phone: user?.phone || "",
    role: user?.role || "customer",
    stage_name: profile?.stage_name || "",
    category: profile?.category || "",
    city: profile?.city || "",
    starting_price: profile?.starting_price || 0,
    bio: profile?.bio || "",
  });
  const [saving, setSaving] = useState(false);
  const isArtist = form.role === "artist";
  const save = async () => {
    setSaving(true);
    try {
      const body = { ...form };
      if (!isArtist) {
        delete body.stage_name; delete body.category; delete body.city;
        delete body.starting_price; delete body.bio;
      }
      await api.put(`/admin/users/${user.id}`, body);
      onSaved();
    } catch (e) {
      toast?.(e?.response?.data?.detail || "Save failed", "error");
      setSaving(false);
    }
  };
  return (
    <div className="popup-scrim" onClick={onClose} data-testid="user-edit-modal">
      <div className="popup-card" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <button className="popup-close" onClick={onClose} aria-label="Close">×</button>
        <h3 style={{ marginTop: 0 }}>Edit User</h3>
        <div className="grid grid-2 gap-12">
          <div>
            <div className="field-label">First name</div>
            <input className="field-input" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} data-testid="edit-first-name" />
          </div>
          <div>
            <div className="field-label">Last name</div>
            <input className="field-input" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} data-testid="edit-last-name" />
          </div>
        </div>
        <div className="field">
          <div className="field-label">Email</div>
          <input className="field-input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="edit-email" />
        </div>
        <div className="grid grid-2 gap-12">
          <div>
            <div className="field-label">Phone</div>
            <input className="field-input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="edit-phone" />
          </div>
          <div>
            <div className="field-label">Role</div>
            <select className="field-input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} data-testid="edit-role">
              {["customer", "artist", "agency", "corporate", "admin"].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        </div>
        {isArtist && (
          <>
            <div className="field-label" style={{ marginTop: 12, opacity: 0.6, fontSize: 11 }}>ARTIST PROFILE</div>
            <div className="grid grid-2 gap-12">
              <div>
                <div className="field-label">Stage name</div>
                <input className="field-input" value={form.stage_name} onChange={(e) => setForm({ ...form, stage_name: e.target.value })} data-testid="edit-stage-name" />
              </div>
              <div>
                <div className="field-label">Category</div>
                <input className="field-input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="edit-category" />
              </div>
            </div>
            <div className="grid grid-2 gap-12">
              <div>
                <div className="field-label">City</div>
                <input className="field-input" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} data-testid="edit-city" />
              </div>
              <div>
                <div className="field-label">Starting price (₹)</div>
                <input type="number" className="field-input" value={form.starting_price} onChange={(e) => setForm({ ...form, starting_price: parseFloat(e.target.value) || 0 })} data-testid="edit-starting-price" />
              </div>
            </div>
            <div className="field">
              <div className="field-label">Bio</div>
              <textarea className="field-input" rows={3} value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} data-testid="edit-bio" />
            </div>
          </>
        )}
        <div className="flex gap-8" style={{ marginTop: 16, justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose} data-testid="edit-cancel">Cancel</button>
          <button className="btn btn-gold" onClick={save} disabled={saving} data-testid="edit-save">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminDisputes({ toast }) {
  const [list, setList] = useState([]);
  useEffect(() => { api.get("/admin/disputes").then(r => setList(r.data)).catch(() => setList([])); }, []);
  const resolve = async (did, decision) => {
    await api.post(`/admin/disputes/${did}/resolve`, { decision });
    toast("Resolved");
    api.get("/admin/disputes").then(r => setList(r.data)).catch(() => setList([]));
  };
  return (
    <div className="card" data-testid="admin-disputes">
      <div className="card-head"><div className="card-title">⚖️ Disputes ({list.length})</div></div>
      <div style={{ padding: 14 }}>
        {list.length === 0 && <div className="empty"><div className="empty-icon">⚖️</div><div className="empty-title">No disputes</div></div>}
        {list.map((d) => (
          <div key={d.id} className="card card-pad mb-12" data-testid={`dispute-${d.id}`}>
            <div className="fw-600 mb-4">{d.reason}</div>
            <div className="text-muted fs-12 mb-8">{d.description}</div>
            <div className="flex gap-8">
              <button className="btn btn-green btn-xs" onClick={() => resolve(d.id, "release")}>Release to Artist</button>
              <button className="btn btn-red btn-xs" onClick={() => resolve(d.id, "refund")}>Refund Customer</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// Refund Auditor — lists every mutual-refund row with filters + one-click
// CSV / PDF export for finance / audit.
// ────────────────────────────────────────────────────────────────────────
function AdminRefundAuditor({ toast }) {
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({});
  const [loading, setLoading] = useState(false);
  const [views, setViews] = useState([]);
  const [viewName, setViewName] = useState("");
  const [watches, setWatches] = useState([]);
  const watchIds = new Set(watches.map((w) => w.booking_id));

  const loadWatches = () => api.get("/admin/refunds/watchlist")
    .then((r) => setWatches(r.data?.items || []))
    .catch(() => setWatches([]));
  useEffect(() => { loadWatches(); }, []);

  const addWatch = async (bid) => {
    try {
      await api.post("/admin/refunds/watchlist", { booking_id: bid, note: "" });
      loadWatches();
      toast("Added to watchlist — Slack will ping on any refund activity", "success");
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const removeWatch = async (bid) => {
    const w = watches.find((x) => x.booking_id === bid);
    if (!w) return;
    try {
      await api.delete(`/admin/refunds/watchlist/${w.id}`);
      loadWatches();
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const qs = () => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (from) p.set("from_date", from);
    if (to) p.set("to_date", to);
    if (q) p.set("q", q);
    return p.toString();
  };

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(`/admin/refunds/audit?${qs()}`);
      setItems(r.data?.items || []);
      setTotals(r.data?.totals || {});
    } catch (e) { toast(formatApiError(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const loadViews = () =>
    api.get("/admin/refunds/saved-views").then((r) => setViews(r.data?.items || [])).catch(() => setViews([]));
  useEffect(() => { loadViews(); }, []);

  const saveView = async () => {
    if (!viewName.trim()) { toast("Give the view a name first", "error"); return; }
    try {
      const r = await api.post("/admin/refunds/saved-views", {
        name: viewName.trim(),
        filters: { status, from_date: from, to_date: to, q },
      });
      setViews((v) => [r.data.view, ...v]);
      setViewName("");
      toast("View saved ✓", "success");
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const applyView = (v) => {
    const f = v.filters || {};
    setStatus(f.status || "");
    setFrom(f.from_date || "");
    setTo(f.to_date || "");
    setQ(f.q || "");
    // trigger load with the new filter values
    setTimeout(load, 20);
  };

  const removeView = async (id) => {
    if (!window.confirm("Delete this saved view?")) return;
    try {
      await api.delete(`/admin/refunds/saved-views/${id}`);
      setViews((v) => v.filter((x) => x.id !== id));
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const dl = (kind) => {
    const url = `${api.defaults.baseURL}/admin/refunds/audit/export.${kind}?${qs()}`;
    const token = localStorage.getItem("token") || "";
    // Use fetch to attach the Authorization header and then trigger a download.
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `refund-audit.${kind}`;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch((e) => toast(`Export failed: ${e.message}`, "error"));
  };

  return (
    <div className="card" data-testid="admin-refund-auditor">
      <div className="card-head">
        <div className="card-title">🔎 Refund Auditor ({items.length})</div>
        <div className="text-muted fs-12">Every customer/artist mutual-refund request. Filter, then export CSV/PDF for finance.</div>
      </div>

      {/* Totals summary */}
      <div className="kpi-grid" style={{ padding: "10px 14px" }}>
        <Kpi icon="🧾" cls="kpi-icon-blue" num={totals.count || 0} label="Total Rows" />
        <Kpi icon="⏳" cls="kpi-icon-amber" num={fmtINRFull(totals.amount_pending || 0)} label="₹ Pending" />
        <Kpi icon="✅" cls="kpi-icon-green" num={fmtINRFull(totals.amount_accepted || 0)} label="₹ Accepted" />
        <Kpi icon="✋" cls="kpi-icon-red" num={fmtINRFull(totals.amount_rejected || 0)} label="₹ Rejected" />
      </div>

      {/* Saved views */}
      <div style={{ padding: "0 14px 8px" }} data-testid="rf-saved-views">
        <div className="flex-between mb-4" style={{ flexWrap: "wrap", gap: 8 }}>
          <div className="text-muted fs-11">
            Saved views — one-click filter combos for month-end audits
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              className="input"
              style={{ width: 180 }}
              placeholder="Name current filters…"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              data-testid="rf-view-name"
            />
            <button className="btn btn-ghost btn-sm" onClick={saveView} disabled={!viewName.trim()} data-testid="rf-view-save">
              💾 Save view
            </button>
          </div>
        </div>
        {views.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {views.map((v) => (
              <span key={v.id}
                style={{
                  display: "inline-flex", gap: 6, alignItems: "center",
                  border: "1px solid rgba(212,175,55,0.35)", borderRadius: 999,
                  padding: "3px 10px", fontSize: 11, background: "rgba(212,175,55,0.06)",
                }}
                data-testid={`rf-view-${v.id}`}>
                <span style={{ cursor: "pointer" }} onClick={() => applyView(v)}>{v.name}</span>
                <span style={{ cursor: "pointer", color: "#e57373" }} onClick={() => removeView(v.id)}>×</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Filters */}
      <div style={{ padding: "8px 14px 14px", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <div>
          <div className="field-label">Status</div>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="rf-status">
            <option value="">All</option>
            <option value="pending_counter_ack">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div><div className="field-label">From</div><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="rf-from" /></div>
        <div><div className="field-label">To</div><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} data-testid="rf-to" /></div>
        <div style={{ flex: 1, minWidth: 200 }}><div className="field-label">Search (ref / email)</div><input className="input" value={q} onChange={(e) => setQ(e.target.value)} data-testid="rf-q" /></div>
        <button className="btn btn-gold btn-sm" onClick={load} disabled={loading} data-testid="rf-apply">{loading ? "Loading…" : "Apply"}</button>
        <button className="btn btn-ghost btn-sm" onClick={() => dl("csv")} data-testid="rf-csv">⬇ CSV</button>
        <button className="btn btn-ghost btn-sm" onClick={() => dl("pdf")} data-testid="rf-pdf">📄 PDF</button>
      </div>

      <table className="tbl">
        <thead>
          <tr>
            <th>Booking</th><th>Event</th><th>Amount</th><th>Status</th>
            <th>Requested By</th><th>Customer</th><th>Artist</th><th>Created</th><th>Watch</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && <tr><td colSpan={9} className="empty">No refund requests match your filters</td></tr>}
          {items.map((h) => {
            const isWatched = watchIds.has(h.booking_id);
            return (
              <tr key={h.id} data-testid={`rf-row-${h.id}`}>
                <td><Link to={`/bookings/${h.booking_id}`}>{h.booking_ref}</Link></td>
                <td>{h.event_date || "—"}</td>
                <td>{fmtINRFull(h.amount)}</td>
                <td><span className={`pill pill-${h.status === "accepted" ? "green" : h.status === "rejected" ? "red" : "gold"}`}>{h.status}</span></td>
                <td>{h.requested_by_role}</td>
                <td title={h.customer_email}>{h.customer_name || h.customer_email}</td>
                <td title={h.artist_email}>{h.artist_name || h.artist_email}</td>
                <td>{(h.created_at || "").slice(0, 10)}</td>
                <td>
                  <button
                    className={`btn btn-sm ${isWatched ? "btn-gold" : "btn-ghost"}`}
                    onClick={() => (isWatched ? removeWatch(h.booking_id) : addWatch(h.booking_id))}
                    title={isWatched ? "Watching — click to unwatch" : "Watch this booking for future refund activity"}
                    data-testid={`rf-watch-${h.booking_id}`}
                    style={{ fontSize: 12 }}>
                    {isWatched ? "👁 Watching" : "👁 Watch"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {watches.length > 0 && (
        <div style={{ padding: "10px 14px 18px" }} data-testid="rf-watchlist-summary">
          <div className="text-muted fs-11 mb-4">Active watchlist ({watches.length}) — Slack pings on any refund activity here</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {watches.map((w) => (
              <span key={w.id}
                style={{
                  display: "inline-flex", gap: 6, alignItems: "center",
                  border: "1px solid rgba(212,175,55,0.35)", borderRadius: 999,
                  padding: "3px 10px", fontSize: 11, background: "rgba(212,175,55,0.06)",
                }}
                data-testid={`rf-watch-chip-${w.id}`}>
                <Link to={`/bookings/${w.booking_id}`} style={{ textDecoration: "none" }}>
                  {w.booking_ref}
                </Link>
                {w.trigger_count > 0 && (
                  <span style={{ fontSize: 10, opacity: 0.7 }} title={`${w.trigger_count} alert(s) fired`}>· {w.trigger_count}×</span>
                )}
                <span style={{ cursor: "pointer", color: "#e57373" }} onClick={() => removeWatch(w.booking_id)}>×</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// Bulk Payout Marker — select multiple pending payouts, enter UTRs, mark
// all as paid in a single call.
// ────────────────────────────────────────────────────────────────────────
function AdminBulkPayouts({ toast }) {
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState({});
  const [defaultMethod, setDefaultMethod] = useState("neft");
  const [defaultPaidOn, setDefaultPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [csvPreview, setCsvPreview] = useState(null);   // { matched, ambiguous, unmatched }
  const [csvBusy, setCsvBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [bankPresets, setBankPresets] = useState([]);
  const [activePresetId, setActivePresetId] = useState("");
  const [presetPickerName, setPresetPickerName] = useState("");
  const [mappingEditor, setMappingEditor] = useState(null); // {id, bank_name, mapping, headers}

  const load = async () => {
    try {
      const r = await api.get("/admin/payouts/pending-list?limit=200");
      setRows(r.data?.items || []);
      setSelected({});
    } catch (e) { toast(formatApiError(e), "error"); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const toggle = (id) => setSelected((s) => ({ ...s, [id]: !s[id] }));
  const selectAll = () => {
    const all = {};
    rows.forEach((r) => { all[r.booking_id] = true; });
    setSelected(all);
  };
  const clearAll = () => setSelected({});

  const updateRow = (bid, patch) => setRows((rs) => rs.map((r) => r.booking_id === bid ? { ...r, ...patch } : r));

  const submit = async () => {
    const chosen = rows.filter((r) => selected[r.booking_id]);
    if (chosen.length === 0) { toast("Select at least one row", "error"); return; }
    const payload = {
      default_method: defaultMethod,
      default_paid_on: defaultPaidOn,
      rows: chosen.map((r) => ({
        booking_id: r.booking_id,
        amount: parseFloat(r.pay_amount || r.outstanding),
        method: r.pay_method || defaultMethod,
        utr: r.pay_utr || "",
        notes: r.pay_notes || "",
        paid_on: r.pay_paid_on || defaultPaidOn,
      })),
    };
    if (!window.confirm(`Mark ${chosen.length} payout(s) as paid — total ₹${payload.rows.reduce((s, r) => s + r.amount, 0).toLocaleString("en-IN")}?`)) return;
    setBusy(true);
    try {
      const r = await api.post("/admin/payouts/bulk-mark-paid", payload);
      const failed = (r.data?.results || []).filter((x) => !x.ok);
      if (failed.length) {
        toast(`Marked ${r.data.succeeded}/${r.data.processed}. ${failed.length} failed — check console`, "warning");
        console.warn("bulk payout failures", failed);
      } else {
        toast(`✅ Marked ${r.data.succeeded} payouts paid · ₹${(r.data.total_amount || 0).toLocaleString("en-IN")}`, "success");
      }
      load();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const chosenCount = Object.values(selected).filter(Boolean).length;
  const chosenTotal = rows.filter((r) => selected[r.booking_id])
    .reduce((s, r) => s + parseFloat(r.pay_amount || r.outstanding || 0), 0);

  // ── CSV import handlers ──────────────────────────────────────────
  const loadBankPresets = () => api.get("/admin/payouts/bank-presets")
    .then((r) => setBankPresets(r.data?.items || []))
    .catch(() => setBankPresets([]));
  useEffect(() => { loadBankPresets(); }, []);

  const uploadCsv = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const url = activePresetId
      ? `/admin/payouts/batch-preview?preset_id=${encodeURIComponent(activePresetId)}`
      : "/admin/payouts/batch-preview";
    setCsvBusy(true);
    try {
      const r = await api.post(url, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setCsvPreview(r.data);
      const withPreset = r.data.preset ? ` · using ${r.data.preset.bank_name}` : "";
      toast(`Parsed ${r.data.parsed_rows} rows · ${r.data.matched.length} auto-matched${withPreset}`, "success");
      if (activePresetId) loadBankPresets(); // refresh usage counter
    } catch (e) { toast(formatApiError(e), "error"); }
    setCsvBusy(false);
  };

  const saveBankPreset = async () => {
    if (!presetPickerName.trim()) { toast("Enter the bank name first", "error"); return; }
    // Extract the header names from the last parsed CSV as a starter mapping.
    // If nothing parsed yet, save an empty mapping the admin can fill later.
    const headers = csvPreview?.parsed_rows ? Object.keys((csvPreview.matched[0]?.raw || csvPreview.unmatched[0]?.raw || {})) : [];
    // Auto-detect columns using simple contains rules so the first import is not a chore.
    const guess = (needles) => headers.filter((h) => needles.some((n) => h.toLowerCase().includes(n)));
    const mapping = {
      amount: guess(["amount", "debit", "credit"]),
      utr: guess(["utr", "ref", "txn", "transaction"]),
      ref_hint: guess(["narration", "description", "remark", "particular"]),
      paid_on: guess(["date"]),
    };
    try {
      const r = await api.post("/admin/payouts/bank-presets", {
        bank_name: presetPickerName.trim(),
        mapping,
      });
      setBankPresets((bs) => [r.data.preset, ...bs]);
      setPresetPickerName("");
      toast(`Saved bank preset "${r.data.preset.bank_name}"`, "success");
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const deleteBankPreset = async (id) => {
    if (!window.confirm("Delete this bank preset?")) return;
    try {
      await api.delete(`/admin/payouts/bank-presets/${id}`);
      setBankPresets((bs) => bs.filter((b) => b.id !== id));
      if (activePresetId === id) setActivePresetId("");
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const applyCsvMatched = async () => {
    if (!csvPreview?.matched?.length) return;
    if (!window.confirm(`Mark ${csvPreview.matched.length} auto-matched payouts as paid?`)) return;
    setCsvBusy(true);
    try {
      const payload = {
        default_method: defaultMethod,
        default_paid_on: defaultPaidOn,
        rows: csvPreview.matched.map((m) => ({
          booking_id: m.booking_id,
          amount: m.amount,
          utr: m.utr || "",
          method: defaultMethod,
          paid_on: m.paid_on || defaultPaidOn,
          notes: `CSV batch · ${m.match_reason}`,
        })),
      };
      const r = await api.post("/admin/payouts/batch-apply", payload);
      toast(
        `✅ Marked ${r.data.succeeded}/${r.data.processed} paid · ₹${(r.data.total_amount || 0).toLocaleString("en-IN")}`,
        r.data.failed ? "warning" : "success",
      );
      setCsvPreview(null);
      load();
    } catch (e) { toast(formatApiError(e), "error"); }
    setCsvBusy(false);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) uploadCsv(f);
  };

  return (
    <div className="card" data-testid="admin-bulk-payouts">
      <div className="card-head">
        <div className="card-title">📦 Bulk Payout Marker ({rows.length} pending)</div>
        <div className="text-muted fs-12">
          Pick payouts you've settled through your bank portal, drop in a UTR, and mark them all paid at once.
        </div>
      </div>

      <div style={{ padding: "8px 14px 12px", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <div>
          <div className="field-label">Default Method</div>
          <select className="input" value={defaultMethod} onChange={(e) => setDefaultMethod(e.target.value)} data-testid="bp-method">
            <option value="neft">NEFT</option>
            <option value="imps">IMPS</option>
            <option value="upi">UPI</option>
            <option value="cash">Cash</option>
            <option value="cheque">Cheque</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <div className="field-label">Default Paid On</div>
          <input type="date" className="input" value={defaultPaidOn} onChange={(e) => setDefaultPaidOn(e.target.value)} data-testid="bp-paidon" />
        </div>
        <button className="btn btn-ghost btn-sm" onClick={selectAll} data-testid="bp-select-all">Select All</button>
        <button className="btn btn-ghost btn-sm" onClick={clearAll} data-testid="bp-clear">Clear</button>
        <div style={{ flex: 1 }} />
        <div className="text-muted fs-12">Selected: <b className="text-good">{chosenCount}</b> · ₹{chosenTotal.toLocaleString("en-IN")}</div>
        <button className="btn btn-gold btn-sm" onClick={submit} disabled={busy || chosenCount === 0} data-testid="bp-submit">
          {busy ? "Processing…" : `Mark ${chosenCount || ""} Paid`}
        </button>
      </div>

      {/* CSV drag-drop importer */}
      <div style={{ padding: "0 14px 12px" }}>
        {/* Bank preset picker */}
        <div className="flex-between mb-8" style={{ flexWrap: "wrap", gap: 8 }} data-testid="bp-bank-presets">
          <div className="text-muted fs-11">
            Bank preset (column mapping) — pick one to auto-recognise headers
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <select
              className="input"
              value={activePresetId}
              onChange={(e) => setActivePresetId(e.target.value)}
              style={{ minWidth: 160 }}
              data-testid="bp-bank-preset-select">
              <option value="">Auto-detect (default)</option>
              {bankPresets.map((b) => (
                <option key={b.id} value={b.id}>{b.bank_name}{b.usage_count ? ` · ${b.usage_count}×` : ""}</option>
              ))}
            </select>
            {activePresetId && (
              <>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    const p = bankPresets.find((b) => b.id === activePresetId);
                    if (p) setMappingEditor({ ...p, mapping: p.mapping || {}, headers: [] });
                  }}
                  data-testid="bp-bank-preset-edit-mapping">
                  🎯 Edit columns
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => deleteBankPreset(activePresetId)} data-testid="bp-bank-preset-delete">
                  🗑 Delete
                </button>
              </>
            )}
            <input
              className="input" style={{ width: 140 }}
              placeholder="New bank name…"
              value={presetPickerName}
              onChange={(e) => setPresetPickerName(e.target.value)}
              data-testid="bp-bank-preset-name" />
            <button
              className="btn btn-ghost btn-sm"
              onClick={saveBankPreset}
              disabled={!presetPickerName.trim()}
              data-testid="bp-bank-preset-save">
              💾 Save as bank preset
            </button>
          </div>
        </div>

        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => document.getElementById("bp-csv-input")?.click()}
          data-testid="bp-csv-drop"
          style={{
            border: `1.5px dashed ${dragOver ? "#D4AF37" : "rgba(255,255,255,0.18)"}`,
            background: dragOver ? "rgba(212,175,55,0.06)" : "rgba(255,255,255,0.02)",
            borderRadius: 10, padding: 18, textAlign: "center", cursor: "pointer",
            transition: "all 0.15s ease",
          }}
        >
          <div className="fs-14 fw-700 mb-4">📥 Drag & drop bank export CSV</div>
          <div className="text-muted fs-12">
            or click to browse · UTRs auto-match to pending payouts by amount and booking reference
          </div>
          <input
            id="bp-csv-input"
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            onChange={(e) => uploadCsv(e.target.files?.[0])}
            data-testid="bp-csv-input"
          />
        </div>

        {csvBusy && <div className="text-muted fs-12 mt-8">Working on it…</div>}

        {csvPreview && (
          <div className="card card-pad mt-8" data-testid="bp-csv-preview"
                style={{ background: "rgba(255,255,255,0.02)" }}>
            <div className="flex-between mb-8">
              <div>
                <b>{csvPreview.matched.length}</b> matched ·
                <b className="text-warn">{" "}{csvPreview.ambiguous.length}</b> ambiguous ·
                <b style={{ color: "#e57373" }}>{" "}{csvPreview.unmatched.length}</b> unmatched
                {" · "}
                <span className="text-muted fs-12">
                  {csvPreview.candidates_missing_in_csv} pending payout(s) not covered
                </span>
              </div>
              <div className="flex gap-8">
                <button className="btn btn-ghost btn-sm" onClick={() => setCsvPreview(null)}>Cancel</button>
                <button className="btn btn-gold btn-sm"
                        onClick={applyCsvMatched}
                        disabled={csvBusy || !csvPreview.matched.length}
                        data-testid="bp-csv-apply">
                  ✅ Apply {csvPreview.matched.length} matched
                </button>
              </div>
            </div>
            {csvPreview.matched.length > 0 && (
              <table className="tbl">
                <thead><tr><th>Booking</th><th>Match</th><th>Amount</th><th>Outstanding</th><th>UTR</th></tr></thead>
                <tbody>
                  {csvPreview.matched.slice(0, 10).map((m) => (
                    <tr key={m.booking_id + m.row} data-testid={`bp-csv-m-${m.booking_id}`}>
                      <td>{m.booking_ref}</td>
                      <td><span className="pill pill-green">{m.match_reason}</span></td>
                      <td>{fmtINRFull(m.amount)}</td>
                      <td>{fmtINRFull(m.outstanding)}</td>
                      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{m.utr || "—"}</td>
                    </tr>
                  ))}
                  {csvPreview.matched.length > 10 && (
                    <tr><td colSpan={5} className="text-muted fs-11">…and {csvPreview.matched.length - 10} more matched rows</td></tr>
                  )}
                </tbody>
              </table>
            )}
            {csvPreview.ambiguous.length > 0 && (
              <div className="text-muted fs-11 mt-4">
                ⚠️ {csvPreview.ambiguous.length} row(s) match multiple candidates — resolve manually below.
              </div>
            )}
            {csvPreview.unmatched.length > 0 && (
              <div className="text-muted fs-11 mt-4">
                🔎 {csvPreview.unmatched.length} row(s) had no match — likely non-payout entries or missing bookings.
              </div>
            )}
          </div>
        )}
      </div>

      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 30 }}></th>
            <th>Booking</th><th>Event</th><th>Artist</th>
            <th>Outstanding</th><th>Amount</th><th>UTR / Ref</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={7} className="empty">No pending payouts — everyone's been paid ✨</td></tr>}
          {rows.map((r) => (
            <tr key={r.booking_id} data-testid={`bp-row-${r.booking_id}`}>
              <td><input type="checkbox" checked={!!selected[r.booking_id]} onChange={() => toggle(r.booking_id)} data-testid={`bp-check-${r.booking_id}`} /></td>
              <td><Link to={`/bookings/${r.booking_id}`}>{r.booking_ref}</Link></td>
              <td>{r.event_date || "—"}</td>
              <td title={r.artist_email}>{r.artist_name || r.artist_email}</td>
              <td>{fmtINRFull(r.outstanding)}</td>
              <td>
                <input
                  type="number"
                  className="input"
                  style={{ width: 110 }}
                  placeholder={String(r.outstanding)}
                  value={r.pay_amount ?? ""}
                  onChange={(e) => updateRow(r.booking_id, { pay_amount: e.target.value })}
                  data-testid={`bp-amt-${r.booking_id}`}
                />
              </td>
              <td>
                <input
                  className="input"
                  style={{ width: 160 }}
                  placeholder="UTR / txn id"
                  value={r.pay_utr ?? ""}
                  onChange={(e) => updateRow(r.booking_id, { pay_utr: e.target.value })}
                  data-testid={`bp-utr-${r.booking_id}`}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {mappingEditor && (
        <BankPresetMapperModal
          preset={mappingEditor}
          existingHeaders={csvPreview ? Object.keys(
            (csvPreview.matched[0]?.raw)
            || (csvPreview.unmatched[0]?.raw)
            || (csvPreview.ambiguous[0]?.raw)
            || {}
          ) : []}
          onCancel={() => setMappingEditor(null)}
          onSave={async (nextMapping) => {
            try {
              await api.patch(`/admin/payouts/bank-presets/${mappingEditor.id}`, {
                bank_name: mappingEditor.bank_name,
                mapping: nextMapping,
              });
              toast(`Updated columns for ${mappingEditor.bank_name}`, "success");
              setMappingEditor(null);
              loadBankPresets();
            } catch (e) { toast(formatApiError(e), "error"); }
          }}
        />
      )}
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// BankPresetMapperModal — visual CSV-header ↔ BookTalent-field mapper.
// ────────────────────────────────────────────────────────────────────────
function BankPresetMapperModal({ preset, existingHeaders = [], onCancel, onSave }) {
  const FIELDS = [
    { key: "amount",   label: "Amount",       hint: "e.g. Debit, Credit, Amount" },
    { key: "utr",      label: "UTR / Ref no", hint: "e.g. UTR, Reference No, Txn ID" },
    { key: "ref_hint", label: "Reference hint", hint: "Free-text field that contains the booking ref — e.g. Narration, Description" },
    { key: "paid_on",  label: "Paid on",      hint: "Date column — e.g. Value Date, Txn Date" },
  ];
  const [mapping, setMapping] = useState(() => {
    const m = {};
    FIELDS.forEach((f) => { m[f.key] = (preset.mapping || {})[f.key] || []; });
    return m;
  });
  const [headers, setHeaders] = useState(existingHeaders);

  const parseHeaders = (file) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const line = String(e.target.result || "").split(/\r?\n/)[0] || "";
      setHeaders(line.split(",").map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean));
    };
    reader.readAsText(file);
  };

  const toggle = (field, header) => {
    setMapping((m) => {
      const cur = new Set(m[field]);
      if (cur.has(header)) cur.delete(header);
      else cur.add(header);
      return { ...m, [field]: Array.from(cur) };
    });
  };

  return (
    <div
      data-testid="bp-mapper-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(6,4,20,0.82)",
        display: "grid", placeItems: "center", zIndex: 900, padding: 16,
        backdropFilter: "blur(6px)",
      }}
      onClick={onCancel}>
      <div className="card card-pad" style={{ maxWidth: 720, width: "100%", background: "#0F0F1B", maxHeight: "88vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif fw-700 fs-18 mb-4">🎯 Column mapping — {preset.bank_name}</h3>
        <p className="text-muted fs-12 mb-12">
          Tick which CSV headers hold each BookTalent field. Multi-select is fine — the parser tries them in order.
        </p>

        <div className="field-label mb-4">CSV headers</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          {headers.length === 0 && <span className="text-muted fs-11">No headers loaded yet — pick a sample CSV to detect them</span>}
          {headers.map((h) => (
            <span key={h} style={{
              fontSize: 11, padding: "3px 10px", borderRadius: 999,
              background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
            }}>{h}</span>
          ))}
          <label className="btn btn-ghost btn-sm" style={{ cursor: "pointer" }}>
            📄 Load sample
            <input type="file" accept=".csv" style={{ display: "none" }}
              onChange={(e) => e.target.files?.[0] && parseHeaders(e.target.files[0])}
              data-testid="bp-mapper-sample" />
          </label>
        </div>

        {FIELDS.map((f) => (
          <div key={f.key} className="mb-12" data-testid={`bp-mapper-field-${f.key}`}>
            <div className="fw-700 fs-13">{f.label}</div>
            <div className="text-muted fs-11 mb-4">{f.hint}</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {headers.length === 0 && (mapping[f.key] || []).map((h) => (
                <span key={h} className="pill pill-gold" style={{ fontSize: 11 }}>{h} ✓</span>
              ))}
              {headers.map((h) => {
                const on = (mapping[f.key] || []).includes(h);
                return (
                  <span key={h}
                    onClick={() => toggle(f.key, h)}
                    style={{
                      cursor: "pointer",
                      fontSize: 11, padding: "3px 10px", borderRadius: 999,
                      border: `1px solid ${on ? "rgba(212,175,55,0.6)" : "rgba(255,255,255,0.12)"}`,
                      background: on ? "rgba(212,175,55,0.14)" : "rgba(255,255,255,0.03)",
                      fontWeight: on ? 700 : 400,
                    }}
                    data-testid={`bp-mapper-${f.key}-${h}`}>
                    {on ? "✓ " : ""}{h}
                  </span>
                );
              })}
            </div>
          </div>
        ))}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn btn-ghost btn-sm" onClick={onCancel} data-testid="bp-mapper-cancel">Cancel</button>
          <button className="btn btn-gold btn-sm" onClick={() => onSave(mapping)} data-testid="bp-mapper-save">Save mapping</button>
        </div>
      </div>
    </div>
  );
}



// ────────────────────────────────────────────────────────────────────────
// Admin Commercial Deals page — every artist's Normal/Service + % status
// with inline edit and per-artist deal-change history drawer.
// ────────────────────────────────────────────────────────────────────────
function AdminCommercialDeals({ toast }) {
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({});
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);      // artist_id being edited
  const [draft, setDraft] = useState({ artist_type: "normal", percentage_deal: 0 });
  const [saving, setSaving] = useState(false);
  const [historyFor, setHistoryFor] = useState(null); // {artist_id, name}
  const [historyRows, setHistoryRows] = useState([]);

  const load = async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (typeFilter) params.set("type_filter", typeFilter);
      const r = await api.get(`/admin/artists/commercial-deals?${params.toString()}`);
      setItems(r.data?.items || []);
      setTotals(r.data?.totals || {});
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [typeFilter]);

  const openHistory = async (artist) => {
    setHistoryFor(artist);
    try {
      const r = await api.get(`/admin/artists/${artist.artist_id}/deal-history`);
      setHistoryRows(r.data?.items || []);
    } catch (e) { toast(formatApiError(e), "error"); setHistoryRows([]); }
  };

  const startEdit = (row) => {
    setEditing(row.artist_id);
    setDraft({
      artist_type: row.artist_type || (row.is_service_artist ? "service" : "normal"),
      percentage_deal: Number(row.percentage_deal) || 0,
    });
  };

  const cancelEdit = () => { setEditing(null); setDraft({ artist_type: "normal", percentage_deal: 0 }); };

  const saveDeal = async (row) => {
    // Validate before hitting API
    if (draft.artist_type === "service" && (!draft.percentage_deal || draft.percentage_deal <= 0)) {
      toast("Service artists ke liye Commission % 0 se zyada hona chahiye", "error");
      return;
    }
    setSaving(true);
    try {
      const body = {
        artist_type: draft.artist_type,
        percentage_deal: draft.artist_type === "service" ? Number(draft.percentage_deal) : 0,
      };
      await api.patch(`/admin/artists/${row.artist_id}/commercial-deal`, body);
      toast(`Updated deal for ${row.name}`, "success");
      cancelEdit();
      load();
    } catch (e) { toast(formatApiError(e), "error"); }
    setSaving(false);
  };

  return (
    <div className="card" data-testid="admin-commercial-deals">
      <div className="card-head">
        <div className="card-title">💼 Commercial Deals ({items.length})</div>
        <div className="text-muted fs-12">
          Every live artist's commercial terms. Edit inline for audit-safe adjustments.
        </div>
      </div>

      <div className="kpi-grid" style={{ padding: "10px 14px" }}>
        <Kpi icon="🎭" cls="kpi-icon-blue" num={totals.count || 0} label="Total Artists" />
        <Kpi icon="⭐" cls="kpi-icon-gold" num={totals.service_count || 0} label="Service Artists" />
        <Kpi icon="👤" cls="kpi-icon-violet" num={totals.normal_count || 0} label="Normal Artists" />
        <Kpi icon="📈" cls="kpi-icon-green" num={`${totals.avg_service_pct || 0}%`} label="Avg. Service %" />
      </div>

      <div style={{ padding: "8px 14px 14px", display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          className="input"
          placeholder="Search name / email / city"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          data-testid="cd-q"
          style={{ minWidth: 220 }}
        />
        <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} data-testid="cd-type">
          <option value="">All types</option>
          <option value="service">BookTalent Service only</option>
          <option value="normal">Normal only</option>
        </select>
        <button className="btn btn-gold btn-sm" onClick={load} disabled={busy} data-testid="cd-apply">
          {busy ? "Loading…" : "Apply"}
        </button>
      </div>

      <table className="tbl">
        <thead>
          <tr>
            <th>Artist</th><th>City</th><th>Type</th><th>Commission %</th>
            <th>KYC</th><th>Set On</th><th>By</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && <tr><td colSpan={8} className="empty">No artists match</td></tr>}
          {items.map((row) => {
            const isEditing = editing === row.artist_id;
            return (
              <tr key={row.artist_id} data-testid={`cd-row-${row.artist_id}`}>
                <td>
                  <div className="fw-700 fs-13">{row.name}</div>
                  <div className="text-muted fs-11">{row.email}</div>
                </td>
                <td>{row.city || "—"}</td>
                <td>
                  {isEditing ? (
                    <select
                      value={draft.artist_type}
                      onChange={(e) => setDraft({ ...draft, artist_type: e.target.value, percentage_deal: e.target.value === "normal" ? 0 : draft.percentage_deal })}
                      data-testid={`cd-type-${row.artist_id}`}
                      className="input" style={{ padding: "3px 6px" }}>
                      <option value="normal">Normal</option>
                      <option value="service">Service</option>
                    </select>
                  ) : (
                    <span className={`pill ${row.is_service_artist ? "pill-green" : "pill-violet"}`}>
                      {row.is_service_artist ? "Service" : "Normal"}
                    </span>
                  )}
                </td>
                <td>
                  {isEditing ? (
                    draft.artist_type === "service" ? (
                      <input
                        type="number" min="0.5" max="50" step="0.5"
                        value={draft.percentage_deal}
                        onChange={(e) => setDraft({ ...draft, percentage_deal: e.target.value })}
                        data-testid={`cd-pct-${row.artist_id}`}
                        className="input" style={{ width: 80, padding: "3px 6px" }}
                        placeholder="e.g. 10"
                      />
                    ) : (
                      <span className="text-muted fs-11">N/A (Normal)</span>
                    )
                  ) : (
                    row.is_service_artist ? <b>{row.percentage_deal}%</b> : "—"
                  )}
                </td>
                <td><span className="pill pill-blue">{row.kyc_status}</span></td>
                <td className="fs-11">{(row.commercial_deal_set_at || "").slice(0, 10) || "—"}</td>
                <td className="fs-11 text-muted">{row.commercial_deal_set_by || "—"}</td>
                <td>
                  {isEditing ? (
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="btn btn-gold btn-sm" onClick={() => saveDeal(row)} disabled={saving} data-testid={`cd-save-${row.artist_id}`}>
                        {saving ? "Saving…" : "💾 Save"}
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={cancelEdit} disabled={saving} data-testid={`cd-cancel-${row.artist_id}`}>Cancel</button>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="btn btn-gold btn-sm" onClick={() => startEdit(row)} data-testid={`cd-edit-${row.artist_id}`}>✎ Edit</button>
                      <button className="btn btn-ghost btn-sm" onClick={() => openHistory(row)} data-testid={`cd-hist-${row.artist_id}`}>🕒 History</button>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {historyFor && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(6,4,20,0.8)",
          display: "grid", placeItems: "center", zIndex: 900, padding: 16,
        }} onClick={() => setHistoryFor(null)} data-testid="cd-history-modal">
          <div className="card card-pad" style={{ maxWidth: 640, width: "100%", maxHeight: "80vh", overflow: "auto", background: "#0F0F1B" }} onClick={(e) => e.stopPropagation()}>
            <h3 className="font-serif fw-700 fs-18 mb-4">📜 Deal history — {historyFor.name}</h3>
            <p className="text-muted fs-12 mb-12">Every change to this artist's commercial deal.</p>
            {historyRows.length === 0 ? (
              <div className="text-muted fs-13">No historical changes recorded — deal was set once during KYC approval.</div>
            ) : (
              <table className="tbl">
                <thead><tr><th>When</th><th>Action</th><th>Type</th><th>%</th><th>By</th></tr></thead>
                <tbody>
                  {historyRows.map((h) => (
                    <tr key={h.id} data-testid={`cd-hist-row-${h.id}`}>
                      <td>{(h.created_at || "").slice(0, 19).replace("T", " ")}</td>
                      <td className="fs-11 text-muted">{h.action}</td>
                      <td>{h.metadata?.artist_type || "—"}</td>
                      <td>{h.metadata?.percentage_deal ?? "—"}</td>
                      <td className="fs-11">{h.actor_email || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div style={{ textAlign: "right", marginTop: 12 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setHistoryFor(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

