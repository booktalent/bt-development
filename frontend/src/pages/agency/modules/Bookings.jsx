import React, { useEffect, useMemo, useState } from "react";
import api from "../../../lib/api";
import useHighlightRow from "../../../lib/useHighlightRow";

const COLS = [
  { key: "pending_confirmation", label: "Pending", badge: "warn" },
  { key: "confirmed", label: "Confirmed", badge: "ok" },
  { key: "completed", label: "Completed", badge: "" },
  { key: "cancelled", label: "Cancelled", badge: "err" },
];

const OFFLINE_COLS = [
  { key: "scheduled", label: "Scheduled" },
  { key: "in_progress", label: "In progress" },
  { key: "completed", label: "Completed" },
  { key: "cancelled", label: "Cancelled" },
];

export default function Bookings() {
  const [tab, setTab] = useState("platform");
  const [reportData, setReportData] = useState({ platform: [], offline: [] });
  useEffect(() => { api.get("/agency/reports/bookings").then((r) => setReportData(r.data || { platform: [], offline: [] })).catch(() => {}); }, []);

  // Iter 65 — notification click → highlight the booking row.
  const totalCount = (reportData.platform?.length || 0) + (reportData.offline?.length || 0);
  useHighlightRow({ prefix: "booking-row", dataKey: totalCount });

  const groupedPlatform = useMemo(() => {
    const map = Object.fromEntries(COLS.map((c) => [c.key, []]));
    (reportData.platform || []).forEach((b) => {
      const s = b.status || "pending_confirmation";
      (map[s] ||= []).push(b);
    });
    return map;
  }, [reportData.platform]);

  const groupedOffline = useMemo(() => {
    const map = Object.fromEntries(OFFLINE_COLS.map((c) => [c.key, []]));
    (reportData.offline || []).forEach((e) => {
      const s = e.status || "scheduled";
      (map[s] ||= []).push(e);
    });
    return map;
  }, [reportData.offline]);

  return (
    <div data-testid="agency-bookings">
      <div className="ag-section-head">
        <div>
          <h2>Bookings</h2>
          <div className="fs-13">Platform bookings from BookTalent + offline events managed by you, side-by-side.</div>
        </div>
      </div>

      <div className="ag-tabs">
        <button className={`ag-tab ${tab === "platform" ? "active" : ""}`} onClick={() => setTab("platform")} data-testid="ag-bookings-tab-platform">
          Platform ({reportData.platform?.length || 0})
        </button>
        <button className={`ag-tab ${tab === "offline" ? "active" : ""}`} onClick={() => setTab("offline")} data-testid="ag-bookings-tab-offline">
          Offline ({reportData.offline?.length || 0})
        </button>
      </div>

      {tab === "platform" ? (
        <div className="ag-kanban" data-testid="ag-bookings-kanban">
          {COLS.map((c) => (
            <div key={c.key} className="ag-kanban-col">
              <h4>{c.label}<span className={`ag-badge ${c.badge}`}>{(groupedPlatform[c.key] || []).length}</span></h4>
              {(groupedPlatform[c.key] || []).map((b) => (
                <div key={b.id} className="ag-kanban-item" data-testid={`booking-row-${b.id}`}>
                  <div style={{ fontWeight: 600 }}>{b.event_type || "Booking"}</div>
                  <div className="text-muted fs-11 mt-4">{b.event_date} · {b.city || ""}</div>
                  <div className="fs-11 mt-4">₹{(b.amount_paid || 0).toLocaleString("en-IN")}</div>
                </div>
              ))}
              {(groupedPlatform[c.key] || []).length === 0 && (
                <div className="text-muted fs-11" style={{ padding: 10 }}>Nothing here.</div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="ag-kanban" data-testid="ag-offline-kanban">
          {OFFLINE_COLS.map((c) => (
            <div key={c.key} className="ag-kanban-col">
              <h4>{c.label}<span className="ag-badge">{(groupedOffline[c.key] || []).length}</span></h4>
              {(groupedOffline[c.key] || []).map((e) => (
                <div key={e.id} className="ag-kanban-item">
                  <div style={{ fontWeight: 600 }}>{e.title}</div>
                  <div className="text-muted fs-11 mt-4">{e.event_date} · {e.city || ""}</div>
                  <div className="fs-11 mt-4">Payment: {e.payment_status || "unpaid"}</div>
                </div>
              ))}
              {(groupedOffline[c.key] || []).length === 0 && (
                <div className="text-muted fs-11" style={{ padding: 10 }}>Nothing here.</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
