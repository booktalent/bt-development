/**
 * AgencyDashboardV2 — SaaS-style Agency Management System (Iter 52).
 *
 * Layout: collapsible left sidebar (module list) + top KPI strip + content area.
 * All 11 modules from the spec are wired here; each renders its own component
 * from ./modules/*.
 */
import React, { useEffect, useState } from "react";
import { NavLink, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Nav from "../../components/Nav";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import "./agency.css";

import Overview from "./modules/Overview";
import Artists from "./modules/Artists";
import ArtistSchedule from "./ArtistSchedule";
import Bookings from "./modules/Bookings";
import Clients from "./modules/Clients";
import Events from "./modules/Events";
import Finance from "./modules/Finance";
import Staff from "./modules/Staff";
import Reports from "./modules/Reports";
import CalendarView from "./modules/CalendarView";
import Documents from "./modules/Documents";
import NotificationsView from "./modules/NotificationsView";

const NAV = [
  { to: "/agency/overview",     label: "Overview",       icon: "M3 12h4l3-9 4 18 3-9h4" },
  { to: "/agency/artists",      label: "Artists",        icon: "M12 2 15 8l6 1-4.5 4 1 6L12 16l-5.5 3 1-6L3 9l6-1z" },
  { to: "/agency/bookings",     label: "Bookings",       icon: "M4 4h16v16H4zM4 10h16" },
  { to: "/agency/clients",      label: "Clients (CRM)",  icon: "M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" },
  { to: "/agency/events",       label: "Events",         icon: "M8 2v4M16 2v4M3 10h18M5 6h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z" },
  { to: "/agency/calendar",     label: "Calendar",       icon: "M8 2v4M16 2v4M3 10h18M5 6h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z" },
  { to: "/agency/finance",      label: "Finance",        icon: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" },
  { to: "/agency/staff",        label: "Staff",          icon: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" },
  { to: "/agency/reports",      label: "Reports",        icon: "M3 3v18h18M7 15l3-4 4 3 5-6" },
  { to: "/agency/documents",    label: "Documents",      icon: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M12 18v-6M9 15h6" },
  { to: "/agency/notifications",label: "Notifications",  icon: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" },
];

function KPIStrip() {
  const [ov, setOv] = useState(null);
  useEffect(() => {
    api.get("/agency/overview").then((r) => setOv(r.data)).catch(() => setOv(null));
  }, []);
  const fmtInr = (v) => (v == null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
  const cards = [
    { label: "Roster Artists", value: ov?.roster_artists ?? "—", accent: "gold" },
    { label: "Offline Artists", value: ov?.offline_artists ?? "—", accent: "violet" },
    { label: "Clients", value: ov?.clients ?? "—", accent: "emerald" },
    { label: "Pending Confirms", value: ov?.pending_bookings ?? "—", accent: "amber" },
    { label: "Upcoming Events", value: ov?.upcoming_offline_events ?? "—", accent: "cyan" },
    { label: "Upcoming Platform", value: ov?.upcoming_platform_bookings ?? "—", accent: "gold" },
    // Feb-2026 requirement — agency-scoped financial figures
    { label: "Advance Received", value: fmtInr(ov?.advance_received), accent: "emerald", testid: "agency-kpi-advance" },
    { label: "Remaining Payment", value: fmtInr(ov?.remaining_amount), accent: "amber", testid: "agency-kpi-remaining" },
    { label: "Payout Pending", value: fmtInr(ov?.artist_payout_pending), accent: "violet", testid: "agency-kpi-payout" },
  ];
  return (
    <div className="ag-kpi-strip" data-testid="agency-kpi-strip">
      {cards.map((c) => (
        <div key={c.label} className={`ag-kpi ag-kpi-${c.accent}`} data-testid={c.testid}>
          <div className="ag-kpi-value">{c.value}</div>
          <div className="ag-kpi-label">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

export default function AgencyDashboardV2() {
  const { user } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="ag-shell" data-testid="agency-dashboard-v2">
      <Nav />
      <div className={`ag-body ${collapsed ? "collapsed" : ""}`}>
        {/* ── Sidebar ─────────────────────────────────────────────── */}
        <aside className="ag-sidebar" data-testid="agency-sidebar">
          <div className="ag-sidebar-head">
            <div className="ag-brand">
              <div className="ag-brand-mark">A</div>
              {!collapsed && <div className="ag-brand-text">
                <div className="ag-brand-name">{user?.company_name || "Agency"}</div>
                <div className="ag-brand-sub">Management Suite</div>
              </div>}
            </div>
            <button
              className="ag-collapse-btn"
              onClick={() => setCollapsed((v) => !v)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              data-testid="agency-sidebar-toggle"
            >
              {collapsed ? "›" : "‹"}
            </button>
          </div>

          <nav className="ag-nav">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end
                className={({ isActive }) => `ag-nav-item ${isActive ? "active" : ""}`}
                data-testid={`agency-nav-${n.to.split('/').pop()}`}
                title={collapsed ? n.label : undefined}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <path d={n.icon} />
                </svg>
                {!collapsed && <span>{n.label}</span>}
              </NavLink>
            ))}
          </nav>

          {!collapsed && (
            <div className="ag-sidebar-foot text-muted fs-11">
              Logged in as<br /><b>{user?.first_name} {user?.last_name}</b>
              <div className="mt-4">{user?.email}</div>
            </div>
          )}
        </aside>

        {/* ── Main content ────────────────────────────────────────── */}
        <main className="ag-main">
          <KPIStrip />
          <div className="ag-content" data-testid="agency-content">
            <Routes>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<Overview />} />
              <Route path="artists/*" element={<Artists />} />
              <Route path="artist/:artistId/schedule" element={<ArtistSchedule />} />
              <Route path="bookings" element={<Bookings />} />
              <Route path="clients/*" element={<Clients />} />
              <Route path="events/*" element={<Events />} />
              <Route path="calendar" element={<CalendarView />} />
              <Route path="finance" element={<Finance />} />
              <Route path="staff" element={<Staff />} />
              <Route path="reports" element={<Reports />} />
              <Route path="documents" element={<Documents />} />
              <Route path="notifications" element={<NotificationsView />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
}
