import React, { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "../../lib/api";

const WINDOW_OPTIONS = [
  { code: "", label: "All time" },
  { code: "30", label: "Last 30 days" },
  { code: "90", label: "Last 90 days" },
  { code: "180", label: "Last 6 months" },
  { code: "365", label: "Last 12 months" },
];

const fmtINR = (n) => `₹${(Number(n) || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

/**
 * Outstation Analytics — Admin report on cross-city booking demand.
 *
 * Shows totals, top artist→event city routes and volume tables so the
 * business can spot which routes are worth marketing / discounting.
 */
export default function AdminOutstationReport({ toast }) {
  const [data, setData] = useState(null);
  const [days, setDays] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = days ? `?days=${days}` : "";
      const r = await api.get(`/admin/reports/outstation${q}`);
      setData(r.data);
    } catch (e) { toast(formatApiError(e), "error"); }
    setLoading(false);
  }, [days, toast]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="loading"><div className="spinner" /></div>;
  if (!data) return <div className="empty"><div className="empty-icon">📊</div><div className="empty-title">No data</div></div>;

  const t = data.totals || {};
  const maxRoute = Math.max(1, ...(data.top_routes || []).map((r) => r.count));

  return (
    <div data-testid="outstation-report">
      <div className="card-head" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title">📊 Outstation Bookings Report</div>
        <select className="field-input" style={{ maxWidth: 200 }} value={days} onChange={(e) => setDays(e.target.value)} data-testid="outstation-window">
          {WINDOW_OPTIONS.map((w) => <option key={w.code} value={w.code}>{w.label}</option>)}
        </select>
      </div>

      <div className="grid grid-4 gap-12 mb-24" style={{ padding: 16 }}>
        <KpiCard label="Outstation Bookings" value={t.outstation_bookings} icon="📍" sub={`${t.outstation_pct}% of ${t.total_bookings} total`} testid="kpi-out-bookings" />
        <KpiCard label="Outstation GMV" value={fmtINR(t.total_gmv_outstation)} icon="💰" sub="Artist performance fee" testid="kpi-out-gmv" />
        <KpiCard label="Avg Performance Fee" value={fmtINR(t.avg_performance_fee)} icon="⚡" sub="per outstation booking" testid="kpi-out-avg" />
        <KpiCard label="Same-city Bookings" value={(t.total_bookings || 0) - (t.outstation_bookings || 0)} icon="🏠" testid="kpi-samecity" />
      </div>

      <div className="grid grid-2 gap-16" style={{ padding: 16 }}>
        <div className="card card-pad" data-testid="top-routes">
          <div className="fw-700 mb-12">🛫 Top Artist → Event City Routes</div>
          {(data.top_routes || []).length === 0 ? (
            <div className="text-muted fs-13">No outstation bookings yet.</div>
          ) : (data.top_routes.map((r, i) => (
            <div key={`${r.artist_city}-${r.event_city}-${i}`} className="mb-12" data-testid={`route-${i}`}>
              <div className="flex justify-between fs-13 mb-4">
                <span><b>{r.artist_city}</b> → <b>{r.event_city}</b></span>
                <span className="text-gold fw-700">{r.count} · avg {fmtINR(r.avg_fee)}</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
                <div style={{ width: `${(r.count / maxRoute) * 100}%`, height: "100%", background: "linear-gradient(90deg,#a78bfa,#d4af37)" }} />
              </div>
              <div className="text-muted fs-11 mt-4">Total GMV: {fmtINR(r.total_fee)}</div>
            </div>
          )))}
        </div>

        <div className="card card-pad" data-testid="top-cities-block">
          <div className="fw-700 mb-12">📤 Top Artist Home Cities</div>
          {(data.top_artist_cities || []).map((c) => (
            <div key={c.city} className="flex justify-between mb-6 fs-13" data-testid={`src-city-${c.city}`}>
              <span>{c.city}</span>
              <span className="text-muted">{c.count} bookings · {fmtINR(c.total_fee)}</span>
            </div>
          ))}
          <div className="fw-700 mt-16 mb-12">📥 Top Event Cities</div>
          {(data.top_event_cities || []).map((c) => (
            <div key={c.city} className="flex justify-between mb-6 fs-13" data-testid={`dst-city-${c.city}`}>
              <span>{c.city}</span>
              <span className="text-muted">{c.count} bookings · {fmtINR(c.total_fee)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="text-muted text-center fs-11" style={{ padding: 12 }}>
        Updated {new Date(data.generated_at).toLocaleString()}
      </div>
    </div>
  );
}

function KpiCard({ label, value, icon, sub, testid }) {
  return (
    <div className="card card-pad text-center" data-testid={testid}>
      <div style={{ fontSize: 24 }}>{icon}</div>
      <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
      <div className="font-serif fw-700" style={{ fontSize: 22 }}>{value}</div>
      {sub && <div className="text-muted fs-11">{sub}</div>}
    </div>
  );
}
