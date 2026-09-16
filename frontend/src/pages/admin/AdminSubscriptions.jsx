/**
 * AdminSubscriptions — Iter 52.9
 *
 * A dedicated Subscription Management module for the Admin Panel. Surfaces
 * every artist/agency subscription with filters, KPI tiles, bulk-action
 * controls (extend/upgrade/cancel/reactivate), a manual "grant subscription"
 * modal, and a one-click sweep-expired button.
 *
 * Backend contract (see /app/backend/routes/subscriptions.py):
 *   GET    /api/admin/subscriptions?status=&plan=&role=&q=&page=&limit=
 *   GET    /api/admin/subscriptions/summary
 *   GET    /api/admin/subscriptions/{sid}
 *   PATCH  /api/admin/subscriptions/{sid}
 *   POST   /api/admin/subscriptions            (manual grant)
 *   DELETE /api/admin/subscriptions/{sid}      (cancel/suspend)
 *   POST   /api/admin/subscriptions/sweep-expired
 */
import React, { useEffect, useMemo, useState } from "react";
import api, { fmtINRFull } from "../../lib/api";

const STATUS_BADGE = {
  active: { bg: "rgba(110,231,168,0.14)", fg: "#6ee7a8", label: "Active" },
  expired: { bg: "rgba(255,120,120,0.14)", fg: "#ff8888", label: "Expired" },
  cancelled: { bg: "rgba(255,255,255,0.08)", fg: "#c0c0c0", label: "Cancelled" },
  suspended: { bg: "rgba(255,210,112,0.14)", fg: "#ffd270", label: "Suspended" },
  pending: { bg: "rgba(178,148,255,0.14)", fg: "#b294ff", label: "Pending" },
};

function StatusPill({ status }) {
  const s = STATUS_BADGE[status] || { bg: "rgba(255,255,255,0.08)", fg: "#c0c0c0", label: status };
  return (
    <span style={{
      background: s.bg, color: s.fg,
      padding: "3px 10px", borderRadius: 999,
      fontSize: 11, letterSpacing: ".08em", textTransform: "uppercase",
      fontWeight: 600, whiteSpace: "nowrap",
    }} data-testid={`sub-status-${status}`}>{s.label}</span>
  );
}

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return iso.slice(0, 10); }
}

export default function AdminSubscriptions({ toast }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState(null);
  const [plans, setPlans] = useState([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [plan, setPlan] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(null);
  const [granting, setGranting] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => {
    const qs = new URLSearchParams({ page, limit: 50 });
    if (q) qs.set("q", q);
    if (status) qs.set("status", status);
    if (plan) qs.set("plan", plan);
    if (role) qs.set("role", role);
    api.get(`/admin/subscriptions?${qs.toString()}`).then((r) => { setItems(r.data.items || []); setTotal(r.data.total || 0); }).catch(() => { setItems([]); setTotal(0); });
    api.get("/admin/subscriptions/summary").then((r) => setSummary(r.data)).catch(() => setSummary(null));
  };
  useEffect(() => {
    api.get("/subscriptions/plans").then((r) => setPlans(r.data || [])).catch(() => setPlans([]));
  }, []);
  useEffect(load, [q, status, plan, role, page]); // eslint-disable-line react-hooks/exhaustive-deps

  const kpis = useMemo(() => {
    if (!summary?.breakdown) return null;
    const active = summary.breakdown.filter((b) => b.status === "active").reduce((s, b) => s + b.count, 0);
    const expired = summary.breakdown.filter((b) => b.status === "expired").reduce((s, b) => s + b.count, 0);
    const revenue = summary.breakdown.filter((b) => b.status === "active").reduce((s, b) => s + (b.revenue || 0), 0);
    return { active, expired, revenue, expiring7d: summary.expiring_soon_7d || 0 };
  }, [summary]);

  const sweep = async () => {
    if (!window.confirm("Force sweep — mark all past-due subscriptions as expired?")) return;
    setBusy(true);
    try {
      const r = await api.post("/admin/subscriptions/sweep-expired");
      toast?.(`Swept: ${r.data.expired} expired, ${r.data.warnings} warnings sent`);
      load();
    } catch (e) { toast?.("Sweep failed", "error"); }
    finally { setBusy(false); }
  };

  const remove = async (sub) => {
    if (!window.confirm(`Cancel ${sub.plan_name} for ${sub.subscriber?.name}?`)) return;
    try { await api.delete(`/admin/subscriptions/${sub.id}`); toast?.("Cancelled"); load(); }
    catch { toast?.("Failed", "error"); }
  };

  return (
    <div data-testid="admin-subscriptions">
      <div className="flex justify-between items-center mb-16" style={{ flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 30 }}>Subscription Management</h1>
          <div className="text-muted fs-12 mt-4">All artist & agency subscriptions — status, expiry, revenue.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-ghost" onClick={sweep} disabled={busy} data-testid="sweep-expired-btn">🧹 Sweep Expired</button>
          <button className="btn btn-gold" onClick={() => setGranting(true)} data-testid="grant-sub-btn">+ Grant Subscription</button>
        </div>
      </div>

      {kpis && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
          <div className="card card-pad"><div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Active</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, color: "#6ee7a8", marginTop: 4 }} data-testid="kpi-active">{kpis.active}</div></div>
          <div className="card card-pad"><div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Expiring in 7d</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, color: "#ffd270", marginTop: 4 }} data-testid="kpi-expiring">{kpis.expiring7d}</div></div>
          <div className="card card-pad"><div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Expired</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, color: "#ff8888", marginTop: 4 }} data-testid="kpi-expired">{kpis.expired}</div></div>
          <div className="card card-pad"><div className="text-muted fs-11" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Active MRR</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, color: "#f6d366", marginTop: 4 }} data-testid="kpi-revenue">{fmtINRFull(kpis.revenue)}</div></div>
        </div>
      )}

      {/* Filters */}
      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 10 }}>
          <input
            className="field-input"
            placeholder="Search name, email, phone, company…"
            value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }}
            data-testid="sub-search"
          />
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="field-input" data-testid="sub-filter-status">
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="expired">Expired</option>
            <option value="cancelled">Cancelled</option>
            <option value="suspended">Suspended</option>
            <option value="pending">Pending</option>
          </select>
          <select value={plan} onChange={(e) => { setPlan(e.target.value); setPage(1); }} className="field-input" data-testid="sub-filter-plan">
            <option value="">All plans</option>
            {plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
          </select>
          <select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }} className="field-input" data-testid="sub-filter-role">
            <option value="">All types</option>
            <option value="artist">Artists</option>
            <option value="agency">Agencies</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card card-pad" style={{ padding: 0, overflow: "hidden" }}>
        <table className="ag-table" style={{ borderRadius: 0, border: 0 }}>
          <thead>
            <tr>
              <th>Subscriber</th><th>Plan</th><th>Status</th><th>Started</th><th>Expires</th><th>Days left</th><th>Txn ID</th><th style={{ textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={8} style={{ textAlign: "center", padding: 40, color: "var(--white-muted)" }}>No subscriptions match the filters.</td></tr>
            ) : items.map((s) => (
              <tr key={s.id} data-testid={`sub-row-${s.id}`}>
                <td>
                  <b>{s.subscriber?.name || "—"}</b>
                  <div className="text-muted fs-11">{s.subscriber?.email} · {s.subscriber?.role}{s.subscriber?.company_name ? ` · ${s.subscriber.company_name}` : ""}</div>
                </td>
                <td><b>{s.plan_name}</b><div className="text-muted fs-11">{s.billing_cycle} · {s.price ? fmtINRFull(s.price) : "—"}</div></td>
                <td><StatusPill status={s.status} /></td>
                <td>{fmtDate(s.started_at)}</td>
                <td>{fmtDate(s.expires_at)}</td>
                <td style={{ color: s.days_left != null && s.days_left < 7 ? "#ffd270" : undefined, fontWeight: 600 }} data-testid={`days-left-${s.id}`}>
                  {s.days_left != null ? (s.days_left < 0 ? "expired" : `${s.days_left}d`) : "—"}
                </td>
                <td className="text-muted fs-11" style={{ fontFamily: "monospace" }}>{s.transaction_id || "—"}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn btn-ghost btn-xs" onClick={() => setEditing(s)} data-testid={`edit-${s.id}`}>Manage</button>
                  {s.status === "active" && (
                    <button className="btn btn-red btn-xs" onClick={() => remove(s)} style={{ marginLeft: 6 }} data-testid={`cancel-${s.id}`}>Cancel</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > 50 && (
        <div className="flex justify-center mt-16" style={{ gap: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>‹ Prev</button>
          <span className="fs-12 text-muted" style={{ padding: "8px 12px" }}>Page {page} of {Math.ceil(total / 50)}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => p + 1)} disabled={page >= Math.ceil(total / 50)}>Next ›</button>
        </div>
      )}

      {editing && <EditModal sub={editing} plans={plans} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); toast?.("Updated"); }} toast={toast} />}
      {granting && <GrantModal plans={plans} onClose={() => setGranting(false)} onSaved={() => { setGranting(false); load(); toast?.("Granted"); }} toast={toast} />}
    </div>
  );
}

function EditModal({ sub, plans, onClose, onSaved, toast }) {
  const [body, setBody] = useState({ plan: sub.plan, status: sub.status, auto_renew: !!sub.auto_renew, extend_days: 0, transaction_id: sub.transaction_id || "" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const patch = {};
      if (body.plan !== sub.plan) patch.plan = body.plan;
      if (body.status !== sub.status) patch.status = body.status;
      if (body.auto_renew !== sub.auto_renew) patch.auto_renew = body.auto_renew;
      if (Number(body.extend_days) !== 0) patch.extend_days = Number(body.extend_days);
      if (body.transaction_id !== (sub.transaction_id || "")) patch.transaction_id = body.transaction_id;
      if (Object.keys(patch).length === 0) { toast?.("Nothing to save"); onClose(); return; }
      await api.patch(`/admin/subscriptions/${sub.id}`, patch);
      onSaved();
    } catch (e) { toast?.(e?.response?.data?.detail || "Update failed", "error"); }
    finally { setSaving(false); }
  };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 300, display: "grid", placeItems: "center", padding: 20 }} onClick={onClose}>
      <div className="card card-pad" style={{ maxWidth: 520, width: "100%" }} onClick={(e) => e.stopPropagation()} data-testid="sub-edit-modal">
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 22, margin: 0 }}>Manage Subscription</h2>
        <div className="text-muted fs-12 mb-16">{sub.subscriber?.name} · Current: <b>{sub.plan_name}</b> ({sub.status})</div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <label><div className="field-label">Plan</div>
            <select className="field-input" value={body.plan} onChange={(e) => setBody({ ...body, plan: e.target.value })} data-testid="edit-plan">
              {plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </select>
          </label>
          <label><div className="field-label">Status</div>
            <select className="field-input" value={body.status} onChange={(e) => setBody({ ...body, status: e.target.value })} data-testid="edit-status">
              {["active", "pending", "expired", "suspended", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label style={{ gridColumn: "1 / -1" }}><div className="field-label">Extend / reduce validity (days) — negative to reduce</div>
            <input type="number" className="field-input" value={body.extend_days} onChange={(e) => setBody({ ...body, extend_days: e.target.value })} data-testid="edit-extend" />
          </label>
          <label style={{ gridColumn: "1 / -1" }}><div className="field-label">Transaction / Payment reference</div>
            <input className="field-input" value={body.transaction_id} onChange={(e) => setBody({ ...body, transaction_id: e.target.value })} placeholder="e.g. pay_abc123" data-testid="edit-txn" />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, gridColumn: "1 / -1", marginTop: 4 }}>
            <input type="checkbox" checked={body.auto_renew} onChange={(e) => setBody({ ...body, auto_renew: e.target.checked })} /> Auto-renew
          </label>
        </div>

        <div className="flex justify-end mt-16" style={{ gap: 8 }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" onClick={save} disabled={saving} data-testid="edit-save">{saving ? "Saving…" : "Save"}</button>
        </div>
      </div>
    </div>
  );
}

function GrantModal({ plans, onClose, onSaved, toast }) {
  const [target, setTarget] = useState(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [body, setBody] = useState({ plan: (plans[0]?.code || "pro"), billing_cycle: "monthly", duration_days: "", transaction_id: "", note: "" });

  useEffect(() => {
    if (!q || q.length < 2) { setResults([]); return; }
    api.get(`/admin/users?role=artist&q=${encodeURIComponent(q)}`).then((r) => setResults(r.data || [])).catch(() => setResults([]));
  }, [q]);

  const save = async () => {
    if (!target) { toast?.("Pick a user first"); return; }
    try {
      await api.post("/admin/subscriptions", {
        artist_id: target.id,
        plan: body.plan,
        billing_cycle: body.billing_cycle,
        duration_days: body.duration_days ? Number(body.duration_days) : null,
        transaction_id: body.transaction_id || undefined,
        note: body.note || undefined,
      });
      onSaved();
    } catch (e) { toast?.(e?.response?.data?.detail || "Grant failed", "error"); }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 300, display: "grid", placeItems: "center", padding: 20 }} onClick={onClose}>
      <div className="card card-pad" style={{ maxWidth: 560, width: "100%" }} onClick={(e) => e.stopPropagation()} data-testid="grant-modal">
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 22, margin: 0 }}>Grant Subscription</h2>
        <div className="text-muted fs-12 mb-16">Assign a plan to an artist / agency — bypasses billing (audit-logged).</div>

        <div className="field-label">Search artist / agency</div>
        <input className="field-input" placeholder="Name, email, phone…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="grant-search" />
        {results.length > 0 && !target && (
          <div style={{ maxHeight: 160, overflowY: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, marginTop: 6 }}>
            {results.map((u) => (
              <div key={u.id} onClick={() => setTarget(u)} style={{ padding: 8, cursor: "pointer", fontSize: 13 }} className="user-result">
                <b>{u.first_name} {u.last_name}</b> <span className="text-muted fs-11">· {u.email} · {u.role}</span>
              </div>
            ))}
          </div>
        )}
        {target && (
          <div className="mt-8" style={{ padding: 10, background: "rgba(246,211,102,0.06)", border: "1px solid rgba(246,211,102,0.25)", borderRadius: 8 }}>
            <b>{target.first_name} {target.last_name}</b> <span className="text-muted fs-11">· {target.email}</span>
            <button className="btn btn-ghost btn-xs" onClick={() => setTarget(null)} style={{ marginLeft: 10 }}>Change</button>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          <label><div className="field-label">Plan</div>
            <select className="field-input" value={body.plan} onChange={(e) => setBody({ ...body, plan: e.target.value })} data-testid="grant-plan">
              {plans.filter((p) => p.code !== "free").map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </select>
          </label>
          <label><div className="field-label">Billing cycle</div>
            <select className="field-input" value={body.billing_cycle} onChange={(e) => setBody({ ...body, billing_cycle: e.target.value })}>
              <option value="monthly">Monthly</option><option value="yearly">Yearly</option>
            </select>
          </label>
          <label><div className="field-label">Custom duration (days, optional)</div>
            <input className="field-input" type="number" placeholder="e.g. 60" value={body.duration_days} onChange={(e) => setBody({ ...body, duration_days: e.target.value })} data-testid="grant-days" />
          </label>
          <label><div className="field-label">Transaction / reference</div>
            <input className="field-input" value={body.transaction_id} onChange={(e) => setBody({ ...body, transaction_id: e.target.value })} placeholder="Manual grant ref" />
          </label>
          <label style={{ gridColumn: "1 / -1" }}><div className="field-label">Note (audit)</div>
            <input className="field-input" value={body.note} onChange={(e) => setBody({ ...body, note: e.target.value })} placeholder="Why is this being granted?" />
          </label>
        </div>

        <div className="flex justify-end mt-16" style={{ gap: 8 }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" onClick={save} disabled={!target} data-testid="grant-save">Grant</button>
        </div>
      </div>
    </div>
  );
}
