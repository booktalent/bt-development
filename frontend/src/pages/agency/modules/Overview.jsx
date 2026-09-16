import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../../lib/api";

const QUICK_ACTIONS = [
  {
    to: "/agency/artists",
    icon: "🎤",
    title: "Add Artist",
    body: "Onboard a new artist to your roster — online or offline.",
    accent: "gold",
    testid: "qa-artists",
  },
  {
    to: "/agency/clients",
    icon: "👥",
    title: "Add Client",
    body: "Register a customer, track notes, follow-ups and event history.",
    accent: "violet",
    testid: "qa-clients",
  },
  {
    to: "/agency/events",
    icon: "🎪",
    title: "Create Event",
    body: "Book multi-artist events, attach checklists and quotations.",
    accent: "emerald",
    testid: "qa-events",
  },
  {
    to: "/agency/finance",
    icon: "🧾",
    title: "New Invoice",
    body: "Generate quotations & invoices with line items and GST auto-calc.",
    accent: "amber",
    testid: "qa-finance",
  },
  {
    to: "/agency/documents",
    icon: "📁",
    title: "Upload Document",
    body: "Contracts, riders, IDs — one private vault tagged by client / event.",
    accent: "cyan",
    testid: "qa-documents",
  },
  {
    to: "/agency/staff",
    icon: "🧑‍💼",
    title: "Invite Staff",
    body: "Add coordinators, accountants, and booking executives.",
    accent: "gold",
    testid: "qa-staff",
  },
];

export default function Overview() {
  const [ov, setOv] = useState(null);
  const nav = useNavigate();
  useEffect(() => { api.get("/agency/overview").then((r) => setOv(r.data)).catch(() => {}); }, []);

  const isEmpty = ov && (ov.roster_artists ?? 0) === 0 && (ov.offline_artists ?? 0) === 0 && (ov.clients ?? 0) === 0;

  return (
    <div data-testid="agency-overview">
      <div className="ag-section-head">
        <div>
          <h2>Agency Overview</h2>
          <div className="fs-13">Everything at a glance — roster, pipeline, recent activity.</div>
        </div>
      </div>

      {isEmpty && (
        <div className="ag-card" style={{ marginBottom: 16, borderLeft: "3px solid #f6d366", background: "linear-gradient(90deg, rgba(246,211,102,0.10), transparent)" }} data-testid="agency-onboarding-banner">
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{ fontSize: 28 }}>✨</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Welcome — let's get you set up</div>
              <div className="text-muted fs-13">
                Start by adding your first artist and client. Everything else — events, invoices, documents — flows from there.
              </div>
            </div>
            <button className="btn btn-gold btn-sm" onClick={() => nav("/agency/artists")} data-testid="agency-onboarding-cta">Add First Artist →</button>
          </div>
        </div>
      )}

      <div className="ag-quick-grid" data-testid="agency-quick-actions">
        {QUICK_ACTIONS.map((a) => (
          <button
            key={a.to}
            type="button"
            className={`ag-quick-card ag-quick-${a.accent}`}
            onClick={() => nav(a.to)}
            data-testid={a.testid}
          >
            <div className="ag-quick-icon">{a.icon}</div>
            <div className="ag-quick-body">
              <div className="ag-quick-title">{a.title}</div>
              <div className="ag-quick-desc">{a.body}</div>
            </div>
            <div className="ag-quick-arrow">→</div>
          </button>
        ))}
      </div>

      <div className="ag-card" style={{ marginTop: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Recent Activity</h4>
        {(ov?.recent_activity || []).length === 0 ? (
          <div className="text-muted fs-13">No activity yet. Once you add clients, events, or documents, you'll see updates here.</div>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {(ov.recent_activity || []).map((a) => (
              <li key={a.id} style={{ padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,0.04)", fontSize: 13 }}>
                <span className={`ag-badge ${a.kind === "event_created" ? "gold" : a.kind === "followup" ? "violet" : ""}`} style={{ marginRight: 10 }}>
                  {a.kind}
                </span>
                {a.title}
                <span className="text-muted fs-11" style={{ float: "right" }}>
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
