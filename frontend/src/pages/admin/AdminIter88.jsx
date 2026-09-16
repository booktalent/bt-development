/**
 * Iter 88 — Admin panels for Payout Retry Queue, Report Schedules, and
 * Manager Scorecard. Each is a focused, self-contained component that
 * plugs directly into the AdminDashboard tab switcher.
 */
import React, { useEffect, useState } from "react";
import api, { fmtINRFull, formatApiError as fmt } from "../../lib/api";
import { useToast } from "../../lib/toast";


// ─── shared ─────────────────────────────────────────────────────────
const STATUS_TINT = {
  queued: "gold", in_progress: "gold",
  succeeded: "green", failed: "red", cancelled: "red",
};
const fmtDate = (iso) => (iso || "").slice(0, 19).replace("T", " ");


// ═══════════════════════════════════════════════════════════════════
// 1. Payout Retry Queue
// ═══════════════════════════════════════════════════════════════════
export function AdminPayoutRetryQueue() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const qs = status ? `?status=${status}` : "";
      const r = await api.get(`/admin/payouts/retry-queue${qs}`);
      setData(r.data);
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [status]);

  const action = async (id, verb) => {
    try {
      await api.post(`/admin/payouts/retry-queue/${id}/${verb}`);
      toast(verb === "retry" ? "Re-queued" : "Cancelled", "success");
      load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  const summary = data?.summary || {};
  return (
    <div className="card" data-testid="admin-payout-retry-queue">
      <div className="card-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title">🔁 Payout Retry Queue</div>
        <div className="flex gap-8" style={{ flexWrap: "wrap", alignItems: "center" }}>
          {["queued", "in_progress", "succeeded", "failed", "cancelled"].map((s) => (
            <span key={s} className={`pill pill-${STATUS_TINT[s] || "gold"}`}
              style={{ cursor: "pointer", opacity: status === s ? 1 : 0.6 }}
              onClick={() => setStatus(status === s ? "" : s)}
              data-testid={`prq-filter-${s}`}
              title={`Filter by ${s}`}>
              {s}: {summary[s] || 0}
            </span>
          ))}
          <button className="btn btn-ghost btn-sm" onClick={load} data-testid="prq-refresh">↻ Refresh</button>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Booking</th><th>Amount</th><th>Status</th>
              <th>Attempts</th><th>Next Attempt</th><th>Last Error</th><th></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="7" className="text-muted text-center pad-16">Loading…</td></tr>}
            {!loading && data && data.items.length === 0 && (
              <tr><td colSpan="7" className="text-muted text-center pad-16">
                No entries. Automated payouts are healthy 🎉
              </td></tr>
            )}
            {data && data.items.map((e) => (
              <tr key={e.id} data-testid={`prq-row-${e.id}`}>
                <td className="font-mono fs-11">{(e.booking_id || "").slice(0, 12)}</td>
                <td className="text-gold font-serif fw-700">{fmtINRFull(e.amount || 0)}</td>
                <td><span className={`pill pill-${STATUS_TINT[e.status] || "gold"}`}>{e.status}</span></td>
                <td>{e.attempts}/{e.max_attempts}</td>
                <td className="fs-11 text-muted">{fmtDate(e.next_attempt_at)}</td>
                <td className="fs-11 text-muted" title={e.last_error} style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.last_error || "—"}
                </td>
                <td>
                  <div className="flex gap-4">
                    {(e.status === "failed" || e.status === "cancelled") && (
                      <button className="btn btn-gold btn-xs" data-testid={`prq-retry-${e.id}`}
                        onClick={() => action(e.id, "retry")}>Retry</button>
                    )}
                    {e.status === "queued" && (
                      <button className="btn btn-ghost btn-xs" data-testid={`prq-cancel-${e.id}`}
                        onClick={() => action(e.id, "cancel")}>Cancel</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 2. Report Schedules
// ═══════════════════════════════════════════════════════════════════
const REPORT_LABEL = {
  artist_bookings: "Artist Bookings",
  manager_leads: "Manager Leads",
  platform_waivers: "Platform Waivers",
};
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function AdminReportSchedules() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const empty = { kind: "artist_bookings", email: "", frequency: "weekly", day_of_week: 0, hour_ist: 8, enabled: true };
  const [form, setForm] = useState(empty);

  const load = async () => {
    try { const r = await api.get("/admin/report-schedules"); setItems(r.data.items || []); }
    catch (e) { toast(fmt(e), "error"); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!form.email.includes("@")) return toast("Valid email required", "error");
    try {
      if (editing) {
        await api.patch(`/admin/report-schedules/${editing.id}`, form);
        toast("Schedule updated", "success");
      } else {
        await api.post("/admin/report-schedules", form);
        toast("Schedule created", "success");
      }
      setShowForm(false); setEditing(null); setForm(empty);
      load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this schedule?")) return;
    try { await api.delete(`/admin/report-schedules/${id}`); load(); }
    catch (e) { toast(fmt(e), "error"); }
  };

  const runNow = async (id) => {
    try {
      const r = await api.post(`/admin/report-schedules/${id}/run-now`);
      toast(r.data?.sent ? "Sent!" : `Failed: ${r.data?.reason || "unknown"}`, r.data?.sent ? "success" : "error");
      load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  const startEdit = (s) => {
    setEditing(s);
    setForm({ kind: s.kind, email: s.email, frequency: s.frequency,
              day_of_week: s.day_of_week ?? 0, hour_ist: s.hour_ist, enabled: s.enabled });
    setShowForm(true);
  };

  return (
    <div className="card" data-testid="admin-report-schedules">
      <div className="card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div className="card-title">📅 Scheduled Reports</div>
          <div className="text-muted fs-12 mt-4">Automatically email CSV reports on your schedule (IST).</div>
        </div>
        <button className="btn btn-gold btn-sm" data-testid="rs-new"
          onClick={() => { setEditing(null); setForm(empty); setShowForm(true); }}>+ New Schedule</button>
      </div>

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Report</th><th>Email</th><th>Cadence</th>
              <th>Next Run</th><th>Last Run</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan="7" className="text-muted text-center pad-16">
                No schedules yet. Click "+ New Schedule" to have a CSV land in your inbox weekly.
              </td></tr>
            )}
            {items.map((s) => (
              <tr key={s.id} data-testid={`rs-row-${s.id}`}>
                <td className="fw-700">{REPORT_LABEL[s.kind] || s.kind}</td>
                <td className="fs-12">{s.email}</td>
                <td className="fs-12">
                  {s.frequency === "daily" && `Daily @ ${s.hour_ist}:00 IST`}
                  {s.frequency === "weekly" && `Weekly · ${DOW[s.day_of_week] || "Mon"} @ ${s.hour_ist}:00 IST`}
                  {s.frequency === "monthly" && `Monthly · 1st @ ${s.hour_ist}:00 IST`}
                </td>
                <td className="fs-11 text-muted">{fmtDate(s.next_run_at)}</td>
                <td className="fs-11 text-muted">{fmtDate(s.last_run_at) || "—"}</td>
                <td>
                  {!s.enabled && <span className="pill pill-red">disabled</span>}
                  {s.enabled && s.last_run_status === "sent" && <span className="pill pill-green">sent</span>}
                  {s.enabled && s.last_run_status === "failed" && <span className="pill pill-red" title={s.last_run_error}>failed</span>}
                  {s.enabled && !s.last_run_status && <span className="pill pill-gold">pending</span>}
                </td>
                <td>
                  <div className="flex gap-4">
                    <button className="btn btn-ghost btn-xs" data-testid={`rs-run-${s.id}`} onClick={() => runNow(s.id)}>Run now</button>
                    <button className="btn btn-ghost btn-xs" data-testid={`rs-edit-${s.id}`} onClick={() => startEdit(s)}>Edit</button>
                    <button className="btn btn-ghost btn-xs" data-testid={`rs-delete-${s.id}`} onClick={() => remove(s.id)}>×</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal card card-pad" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }} data-testid="rs-form">
            <h3 className="font-serif fw-700 mb-8">{editing ? "Edit Schedule" : "New Report Schedule"}</h3>
            <div className="grid grid-2 gap-8">
              <div>
                <label className="field-label">Report</label>
                <select className="field-input" value={form.kind}
                  onChange={(e) => setForm({ ...form, kind: e.target.value })} data-testid="rs-form-kind">
                  {Object.entries(REPORT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <div>
                <label className="field-label">Cadence</label>
                <select className="field-input" value={form.frequency}
                  onChange={(e) => setForm({ ...form, frequency: e.target.value })} data-testid="rs-form-freq">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly (1st of month)</option>
                </select>
              </div>
              {form.frequency === "weekly" && (
                <div>
                  <label className="field-label">Day of Week</label>
                  <select className="field-input" value={form.day_of_week}
                    onChange={(e) => setForm({ ...form, day_of_week: parseInt(e.target.value) })} data-testid="rs-form-dow">
                    {DOW.map((d, i) => <option key={i} value={i}>{d}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="field-label">Hour (IST, 0-23)</label>
                <input className="field-input" type="number" min="0" max="23" value={form.hour_ist}
                  onChange={(e) => setForm({ ...form, hour_ist: parseInt(e.target.value) || 0 })} data-testid="rs-form-hour" />
              </div>
              <div className="col-span-2">
                <label className="field-label">Email</label>
                <input className="field-input" type="email" value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="you@company.com" data-testid="rs-form-email" />
              </div>
              <div className="col-span-2">
                <label className="flex gap-8" style={{ alignItems: "center" }}>
                  <input type="checkbox" checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    data-testid="rs-form-enabled" />
                  <span>Enabled</span>
                </label>
              </div>
            </div>
            <div className="flex gap-8 mt-16">
              <button className="btn btn-gold" onClick={save} data-testid="rs-form-save">
                {editing ? "Save Changes" : "Create Schedule"}
              </button>
              <button className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 3. Manager Performance Scorecard
// ═══════════════════════════════════════════════════════════════════
function ProgressBar({ pct, colorHigh = "#6ee7a8", colorLow = "#f6d366" }) {
  const clamped = Math.max(0, Math.min(200, pct || 0));
  const displayPct = Math.min(100, clamped); // bar visually caps at 100%
  return (
    <div style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden", position: "relative" }}>
      <div style={{
        width: `${displayPct}%`, height: "100%",
        background: `linear-gradient(90deg, ${colorLow}, ${colorHigh})`,
        transition: "width 400ms ease",
      }} />
    </div>
  );
}

function TargetsModal({ mgr, onClose, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState({
    monthly_lead_target: mgr.monthly_lead_target || 0,
    monthly_revenue_target: mgr.monthly_revenue_target || 0,
  });
  const save = async () => {
    try {
      await api.patch(`/admin/managers/${mgr.manager_id}/targets`, {
        monthly_lead_target: parseInt(form.monthly_lead_target) || 0,
        monthly_revenue_target: parseFloat(form.monthly_revenue_target) || 0,
      });
      toast("Targets updated", "success");
      onSaved();
    } catch (e) { toast(fmt(e), "error"); }
  };
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card card-pad" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }} data-testid="mgr-targets-modal">
        <h3 className="font-serif fw-700 mb-8">Set Targets · {mgr.manager_name}</h3>
        <div className="text-muted fs-13 mb-16">Monthly goals used to compute progress on the scorecard.</div>
        <div className="grid grid-2 gap-8">
          <div>
            <label className="field-label">Won Leads / month</label>
            <input className="field-input" type="number" min="0" value={form.monthly_lead_target}
              onChange={(e) => setForm({ ...form, monthly_lead_target: e.target.value })}
              data-testid="mgr-target-leads" />
          </div>
          <div>
            <label className="field-label">Revenue ₹ / month</label>
            <input className="field-input" type="number" min="0" value={form.monthly_revenue_target}
              onChange={(e) => setForm({ ...form, monthly_revenue_target: e.target.value })}
              data-testid="mgr-target-revenue" />
          </div>
        </div>
        <div className="flex gap-8 mt-16">
          <button className="btn btn-gold" onClick={save} data-testid="mgr-target-save">Save</button>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export function AdminManagerScorecard() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const r = await api.get(`/admin/reports/manager-scorecard?month=${month}`);
      setData(r.data);
    } catch (e) { toast(fmt(e), "error"); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [month]);

  return (
    <div data-testid="admin-manager-scorecard">
      <div className="flex-between pad-16" style={{ flexWrap: "wrap", gap: 8 }}>
        <div>
          <h2 className="font-serif fs-22 fw-700">Manager Scorecard</h2>
          <div className="text-muted fs-13">Monthly performance vs targets. Click "Targets" to configure goals.</div>
        </div>
        <input className="input" type="month" value={month}
          onChange={(e) => setMonth(e.target.value)}
          data-testid="mgr-scorecard-month" style={{ width: 180 }} />
      </div>

      {!data && <div className="pad-24 text-muted">Loading…</div>}
      {data && data.items.length === 0 && (
        <div className="pad-24 text-muted text-center" data-testid="mgr-scorecard-empty">
          No managers configured yet.
        </div>
      )}
      {data && (
        <div className="grid grid-3 gap-16 pad-16">
          {data.items.map((m) => (
            <div key={m.manager_id} className="card card-pad" data-testid={`mgr-card-${m.manager_id}`}>
              <div className="flex-between mb-8">
                <div>
                  <div className="fw-700 fs-16">{m.manager_name || m.manager_email.split("@")[0]}</div>
                  <div className="text-muted fs-11">{m.manager_email}</div>
                </div>
                <button className="btn btn-ghost btn-xs" data-testid={`mgr-targets-btn-${m.manager_id}`}
                  onClick={() => setEditing(m)}>Targets</button>
              </div>

              {/* Leads progress */}
              <div className="mb-12">
                <div className="flex-between fs-12 mb-4">
                  <span>Won Leads</span>
                  <span className="text-gold">{m.leads_won} / {m.monthly_lead_target || "—"}
                    {m.monthly_lead_target > 0 && <span className="text-muted"> ({m.lead_progress_pct}%)</span>}
                  </span>
                </div>
                <ProgressBar pct={m.lead_progress_pct} />
              </div>

              {/* Revenue progress */}
              <div className="mb-12">
                <div className="flex-between fs-12 mb-4">
                  <span>Revenue</span>
                  <span className="text-gold">{fmtINRFull(m.revenue_driven)}
                    {m.monthly_revenue_target > 0 && <span className="text-muted"> / {fmtINRFull(m.monthly_revenue_target)} ({m.revenue_progress_pct}%)</span>}
                  </span>
                </div>
                <ProgressBar pct={m.revenue_progress_pct} />
              </div>

              {/* Quick stats */}
              <div className="grid grid-3 gap-8 fs-12 mt-8" style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 8 }}>
                <div>
                  <div className="text-muted fs-10">Total</div>
                  <div className="fw-700">{m.leads_total}</div>
                </div>
                <div>
                  <div className="text-muted fs-10">Lost</div>
                  <div className="fw-700 text-red">{m.leads_lost}</div>
                </div>
                <div>
                  <div className="text-muted fs-10">Conv</div>
                  <div className="fw-700 text-green">{m.conversion_pct}%</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <TargetsModal
          mgr={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 4. WhatsApp Templates Config (editable — DB-backed)
// ═══════════════════════════════════════════════════════════════════
export function AdminWhatsAppTemplates() {
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(false);

  const load = () => {
    api.get("/admin/whatsapp/templates-status")
       .then((r) => {
         setStatus(r.data);
         const initial = {};
         (r.data.templates || []).forEach((t) => { initial[t.event] = t.template_name || ""; });
         setEdits(initial);
       })
       .catch(() => setStatus({ provider: "unknown", templates: [] }));
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      // Only send events where the source is NOT 'env' — env wins anyway,
      // no point overwriting user's env vars via UI.
      const payload = { templates: {} };
      (status?.templates || []).forEach((t) => {
        if (t.source !== "env") {
          payload.templates[t.event] = edits[t.event] || "";
        }
      });
      await api.patch("/admin/whatsapp/templates", payload);
      toast("Saved template names", "success");
      load();
    } catch (e) { toast(fmt(e), "error"); }
    setSaving(false);
  };

  if (!status) return <div className="pad-16 text-muted">Loading…</div>;

  return (
    <div className="card card-pad" data-testid="admin-wa-templates">
      <div className="flex-between mb-8">
        <div>
          <h3 className="font-serif fw-700 mb-4">WhatsApp Templates</h3>
          <div className="text-muted fs-12">
            Approve template names on the <b>wachatsender console</b>, then paste them below or set
            <code style={{ padding: "0 4px" }}>WA_TEMPLATE_*</code> env vars.
            Env wins over DB. Blank = plain-text fall-back.
          </div>
        </div>
        <span className="pill pill-gold">Provider: {status.provider}</span>
      </div>

      <table className="table">
        <thead><tr><th>Event</th><th>Approved Template Name</th><th>Source</th><th>Status</th></tr></thead>
        <tbody>
          {(status.templates || []).map((t) => (
            <tr key={t.event} data-testid={`wa-tpl-${t.event}`}>
              <td className="fw-700 fs-13">{t.event}</td>
              <td>
                <input
                  className="input"
                  value={edits[t.event] || ""}
                  onChange={(e) => setEdits({ ...edits, [t.event]: e.target.value })}
                  disabled={t.source === "env"}
                  placeholder={t.source === "env" ? "(locked — set via env var)" : "e.g. booking_confirmed"}
                  data-testid={`wa-tpl-input-${t.event}`}
                  style={{ width: "100%" }}
                />
                {t.source === "env" && (
                  <div className="text-muted fs-11 mt-4">
                    Locked by env var <code>{t.env_var}</code>. Remove the env var to edit from UI.
                  </div>
                )}
              </td>
              <td className="fs-12 text-muted">{t.source || "—"}</td>
              <td>
                {t.template_name
                  ? <span className="pill pill-green">approved</span>
                  : <span className="pill pill-gold">fallback</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-16 flex gap-8">
        <button className="btn btn-gold" onClick={save} disabled={saving} data-testid="wa-tpl-save">
          {saving ? "Saving…" : "Save Templates"}
        </button>
        <button className="btn btn-ghost" onClick={load}>Reset</button>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 5. Report Snapshot History (Iter 89)
// ═══════════════════════════════════════════════════════════════════
export function AdminReportSnapshots() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("");

  const load = async () => {
    try {
      const qs = kind ? `?kind=${kind}` : "";
      const r = await api.get(`/admin/report-snapshots${qs}`);
      setItems(r.data.items || []);
    } catch (e) { toast(fmt(e), "error"); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [kind]);

  const download = async (snap) => {
    try {
      const r = await api.get(`/admin/report-snapshots/${snap.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url; a.download = snap.filename; a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) { toast(fmt(e), "error"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this snapshot?")) return;
    try { await api.delete(`/admin/report-snapshots/${id}`); load(); }
    catch (e) { toast(fmt(e), "error"); }
  };

  return (
    <div className="card" data-testid="admin-report-snapshots">
      <div className="card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div className="card-title">🗂️ Report Snapshot History</div>
          <div className="text-muted fs-12 mt-4">Every scheduled CSV is persisted to disk for re-download.</div>
        </div>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}
          data-testid="snap-filter-kind" style={{ width: 200 }}>
          <option value="">All reports</option>
          <option value="artist_bookings">Artist Bookings</option>
          <option value="manager_leads">Manager Leads</option>
          <option value="platform_waivers">Platform Waivers</option>
        </select>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>When</th><th>Kind</th><th>Filename</th><th>Size</th><th>Trigger</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan="7" className="text-muted text-center pad-16">
                No snapshots yet. Every scheduled CSV run will land here for re-download.
              </td></tr>
            )}
            {items.map((s) => (
              <tr key={s.id} data-testid={`snap-row-${s.id}`}>
                <td className="fs-11 text-muted">{fmtDate(s.created_at)}</td>
                <td>{REPORT_LABEL[s.kind] || s.kind}</td>
                <td className="font-mono fs-11">{s.filename}</td>
                <td className="fs-12">{(s.size / 1024).toFixed(1)} KB</td>
                <td className="fs-12">{s.trigger}</td>
                <td>
                  {s.status === "sent"
                    ? <span className="pill pill-green">sent</span>
                    : <span className="pill pill-red" title={s.error}>failed</span>}
                </td>
                <td>
                  <div className="flex gap-4">
                    <button className="btn btn-gold btn-xs" data-testid={`snap-dl-${s.id}`}
                      onClick={() => download(s)}>⬇ Download</button>
                    <button className="btn btn-ghost btn-xs" data-testid={`snap-del-${s.id}`}
                      onClick={() => remove(s.id)}>×</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
