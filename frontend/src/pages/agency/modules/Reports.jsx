import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

function Bar({ value, max, color = "#f6d366" }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 4, height: 8, overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 320ms" }} />
    </div>
  );
}

export default function Reports() {
  const [revenue, setRevenue] = useState([]);
  const [perf, setPerf] = useState([]);
  const [tab, setTab] = useState("revenue");

  useEffect(() => {
    api.get("/agency/reports/revenue").then((r) => setRevenue(r.data.by_month || [])).catch(() => {});
    api.get("/agency/reports/artist-performance").then((r) => setPerf(r.data || [])).catch(() => {});
  }, []);

  const maxRev = revenue.reduce((m, r) => Math.max(m, r.total || 0), 0);
  const maxPerf = perf.reduce((m, r) => Math.max(m, r.platform_gross || 0), 0);

  return (
    <div data-testid="agency-reports">
      <div className="ag-section-head">
        <div><h2>Reports & Analytics</h2><div className="fs-13">Revenue trends, artist performance, booking mix.</div></div>
      </div>

      <div className="ag-tabs">
        <button className={`ag-tab ${tab === "revenue" ? "active" : ""}`} onClick={() => setTab("revenue")}>Revenue</button>
        <button className={`ag-tab ${tab === "artists" ? "active" : ""}`} onClick={() => setTab("artists")}>Artist Performance</button>
      </div>

      {tab === "revenue" && (
        revenue.length === 0 ? <div className="ag-empty"><h3>No revenue data yet</h3><div>Mark invoices as paid to see monthly trends.</div></div> :
        <div className="ag-card">
          {revenue.map((r) => (
            <div key={r.month} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span>{r.month}</span>
                <span className="text-gold">₹{r.total.toLocaleString("en-IN")} · {r.invoices} inv</span>
              </div>
              <Bar value={r.total} max={maxRev} />
            </div>
          ))}
        </div>
      )}

      {tab === "artists" && (
        perf.length === 0 ? <div className="ag-empty"><h3>No performance data yet</h3><div>Invite roster artists to start tracking.</div></div> :
        <div className="ag-card">
          {perf.map((p) => (
            <div key={p.artist_id} style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span><b>{p.name}</b> · {p.platform_bookings} bookings</span>
                <span className="text-gold">₹{p.platform_gross.toLocaleString("en-IN")}</span>
              </div>
              <Bar value={p.platform_gross} max={maxPerf} />
              <div className="text-muted fs-11 mt-4">Commission earned: ₹{p.commission_earned.toLocaleString("en-IN")} @ {p.commission_pct}%</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
