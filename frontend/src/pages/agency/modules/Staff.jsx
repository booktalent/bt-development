import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

const ROLES = [
  { key: "manager", label: "Manager", perms: ["all_read", "all_write", "manage_staff", "finance"] },
  { key: "coordinator", label: "Coordinator", perms: ["events_read", "events_write", "clients_read", "clients_write"] },
  { key: "accountant", label: "Accountant", perms: ["finance", "invoices_read", "invoices_write", "reports_read"] },
  { key: "booking_executive", label: "Booking Executive", perms: ["bookings_read", "bookings_write", "artists_read"] },
];

export default function Staff() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ name: "", email: "", role: "coordinator", permissions: ROLES[1].perms });
  const load = () => api.get("/agency/staff").then((r) => setList(r.data || [])).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const invite = async () => {
    if (!form.name || !form.email) return;
    try {
      await api.post("/agency/staff", form);
      setForm({ name: "", email: "", role: "coordinator", permissions: ROLES[1].perms });
      load();
    } catch (e) { alert(e?.response?.data?.detail || "Failed to invite"); }
  };
  const revoke = async (id) => { if (window.confirm("Revoke access?")) { await api.delete(`/agency/staff/${id}`); load(); } };
  const changeRole = async (id, role) => {
    const perms = ROLES.find((r) => r.key === role)?.perms || [];
    await api.patch(`/agency/staff/${id}`, { role, permissions: perms });
    load();
  };

  const togglePerm = (perm) => {
    const has = form.permissions.includes(perm);
    setForm({ ...form, permissions: has ? form.permissions.filter((p) => p !== perm) : [...form.permissions, perm] });
  };

  const allPerms = Array.from(new Set(ROLES.flatMap((r) => r.perms)));

  return (
    <div data-testid="agency-staff">
      <div className="ag-section-head">
        <div><h2>Staff</h2><div className="fs-13">Invite team members with role-based permissions.</div></div>
      </div>

      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Invite Staff</h4>
        <div className="ag-form-grid">
          <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, permissions: ROLES.find((r) => r.key === e.target.value)?.perms || [] })}>
              {ROLES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
          </label>
          <label style={{ justifyContent: "flex-end" }}><span>&nbsp;</span><button className="btn btn-gold btn-sm" onClick={invite} data-testid="ag-staff-invite">Send Invite</button></label>
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginBottom: 6 }}>Permissions</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {allPerms.map((p) => (
              <button key={p} className={`ag-badge ${form.permissions.includes(p) ? "gold" : ""}`}
                onClick={() => togglePerm(p)} style={{ cursor: "pointer", border: "1px solid rgba(255,255,255,0.1)" }}>
                {p.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="ag-empty"><h3>No staff invited yet</h3><div>Invite your first coordinator, accountant or manager.</div></div>
      ) : (
        <table className="ag-table">
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead>
          <tbody>{list.map((s) => (
            <tr key={s.id}>
              <td><b>{s.name}</b></td><td>{s.email}</td>
              <td>
                <select value={s.role} onChange={(e) => changeRole(s.id, e.target.value)} style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", color: "#fff", padding: "6px 8px", borderRadius: 6 }}>
                  {ROLES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>
              </td>
              <td><span className={`ag-badge ${s.status === "active" ? "ok" : "warn"}`}>{s.status}</span></td>
              <td><button className="btn btn-ghost btn-sm" onClick={() => revoke(s.id)}>Revoke</button></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
