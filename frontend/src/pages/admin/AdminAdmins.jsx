import React, { useEffect, useState } from "react";
import api from "../../lib/api";

const PERMISSION_LABELS = {
  "admins.manage": "Manage other admins",
  "users.view": "View users",
  "users.edit": "Edit users",
  "users.suspend": "Suspend / reactivate users",
  "users.delete": "Delete users",
  "artists.moderate": "Feature / verify artists",
  "bookings.view": "View bookings",
  "bookings.override": "Override bookings (extend / force / refund)",
  "payments.view": "View payments",
  "payments.refund": "Issue refunds",
  "cms.manage": "Manage CMS (pages, blogs, FAQs)",
  "settings.manage": "Change platform settings",
  "analytics.view": "View analytics dashboard",
  "notifications.send": "Send broadcast notifications",
  "subscriptions.manage": "Manage subscription plans",
};

const ROLE_LABELS = {
  super_admin: "Super Admin — full access",
  operations: "Operations — user + booking ops",
  finance: "Finance — payments + subs",
  content: "Content — CMS + broadcasts",
  support: "Support — user + booking visibility",
  viewer: "Viewer — read-only",
  custom: "Custom — pick permissions",
};

function CreateAdminModal({ presets, permissions, onClose, onCreated }) {
  const [form, setForm] = useState({
    email: "", password: "", first_name: "", last_name: "",
    admin_role: "viewer", admin_permissions: [],
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const isCustom = form.admin_role === "custom";
  const effectivePerms = isCustom ? form.admin_permissions : (presets[form.admin_role] || []);

  const submit = async () => {
    setErr(null); setBusy(true);
    try {
      const body = { ...form };
      if (!isCustom) delete body.admin_permissions;
      await api.post("/admin/admins", body);
      onCreated();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to create admin");
    } finally { setBusy(false); }
  };

  const togglePerm = (p) => {
    setForm((f) => ({
      ...f,
      admin_permissions: f.admin_permissions.includes(p)
        ? f.admin_permissions.filter((x) => x !== p)
        : [...f.admin_permissions, p],
    }));
  };

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="new-admin-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640, width: "94%" }}>
        <div className="modal-head">
          <h3 style={{ margin: 0 }}>Create New Admin</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body" style={{ display: "grid", gap: 12 }}>
          <div className="row-2">
            <label>First name<input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} data-testid="new-admin-first" /></label>
            <label>Last name<input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} data-testid="new-admin-last" /></label>
          </div>
          <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="new-admin-email" /></label>
          <label>Temporary password<input type="text" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="At least 8 chars" data-testid="new-admin-password" /></label>

          <label>Role
            <select value={form.admin_role} onChange={(e) => setForm({ ...form, admin_role: e.target.value })} data-testid="new-admin-role">
              {Object.entries(ROLE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>

          <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "var(--gold-light)" }}>
              Effective permissions ({effectivePerms.length})
              {isCustom && " — pick below"}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {permissions.map((p) => {
                const on = effectivePerms.includes(p);
                return (
                  <label key={p} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, cursor: isCustom ? "pointer" : "default", opacity: isCustom || on ? 1 : 0.4 }}>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!isCustom}
                      onChange={() => togglePerm(p)}
                      data-testid={`new-admin-perm-${p}`}
                    />
                    <span>{PERMISSION_LABELS[p] || p}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {err && <div style={{ color: "#ff8888", fontSize: 12 }}>{err}</div>}
        </div>

        <div className="modal-foot">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold btn-sm" onClick={submit} disabled={busy} data-testid="new-admin-submit">
            {busy ? "Creating…" : "Create Admin"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditAdminModal({ admin, presets, permissions, onClose, onSaved }) {
  const [role, setRole] = useState(admin.admin_role);
  const [perms, setPerms] = useState(admin.admin_permissions || []);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const isCustom = role === "custom";
  useEffect(() => {
    if (!isCustom && presets[role]) setPerms(presets[role]);
  }, [role, isCustom, presets]);

  const submit = async () => {
    setErr(null); setBusy(true);
    try {
      const body = { admin_role: role };
      if (isCustom) body.admin_permissions = perms;
      if (password) body.password = password;
      await api.patch(`/admin/admins/${admin.id}`, body);
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="edit-admin-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640, width: "94%" }}>
        <div className="modal-head">
          <h3 style={{ margin: 0 }}>Edit {admin.first_name} {admin.last_name}</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 12 }}>
          <div className="text-muted fs-12">{admin.email}</div>
          <label>Role
            <select value={role} onChange={(e) => setRole(e.target.value)} data-testid="edit-admin-role">
              {Object.entries(ROLE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>

          <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "var(--gold-light)" }}>Permissions ({perms.length})</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {permissions.map((p) => {
                const on = perms.includes(p);
                return (
                  <label key={p} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, opacity: isCustom || on ? 1 : 0.4 }}>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!isCustom}
                      onChange={() => setPerms((cur) => cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p])}
                    />
                    <span>{PERMISSION_LABELS[p] || p}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <label>Reset password (optional)
            <input type="text" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Leave blank to keep current" data-testid="edit-admin-password" />
          </label>

          {err && <div style={{ color: "#ff8888", fontSize: 12 }}>{err}</div>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold btn-sm" onClick={submit} disabled={busy} data-testid="edit-admin-submit">
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminAdmins({ toast }) {
  const [subTab, setSubTab] = useState("admins"); // Iter 56 — admins | roles | audit
  const [admins, setAdmins] = useState([]);
  const [presets, setPresets] = useState({});
  const [permissions, setPermissions] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Iter 56 — Role manager + audit log data
  const [roles, setRoles] = useState([]);
  const [auditLog, setAuditLog] = useState([]);
  const [showNewRole, setShowNewRole] = useState(false);
  const [editingRole, setEditingRole] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [rolesR, adminsR] = await Promise.all([
        api.get("/admin/rbac/roles"),
        api.get("/admin/admins"),
      ]);
      setPresets(rolesR.data.role_presets || {});
      setPermissions(rolesR.data.permissions || []);
      setAdmins(adminsR.data || []);
    } catch (e) {
      setError(e?.response?.status === 403
        ? "You need the 'admins.manage' permission to view this section."
        : "Failed to load admin data");
    } finally { setLoading(false); }
  };

  const loadRoles = () =>
    api.get("/admin/roles").then((r) => setRoles(r.data || [])).catch(() => setRoles([]));

  const loadAudit = () =>
    api.get("/admin/audit-log?limit=100").then((r) => setAuditLog(r.data || [])).catch(() => setAuditLog([]));

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (subTab === "roles") loadRoles();
    if (subTab === "audit") loadAudit();
  }, [subTab]);

  const toggleActive = async (a) => {
    try {
      await api.patch(`/admin/admins/${a.id}`, { active: !a.active });
      toast?.(a.active ? "Admin deactivated" : "Admin reactivated");
      load();
    } catch (e) { toast?.(e?.response?.data?.detail || "Failed", "error"); }
  };

  const remove = async (a) => {
    if (!window.confirm(`Delete ${a.email}? This cannot be undone.`)) return;
    try {
      await api.delete(`/admin/admins/${a.id}`);
      toast?.("Admin removed");
      load();
    } catch (e) { toast?.(e?.response?.data?.detail || "Failed", "error"); }
  };

  const deleteRole = async (r) => {
    if (!window.confirm(`Delete role "${r.id}"? Admins holding this role must be reassigned first.`)) return;
    try {
      await api.delete(`/admin/roles/${r.id}`);
      toast?.("Role deleted");
      loadRoles();
      load();
    } catch (e) { toast?.(e?.response?.data?.detail || "Failed", "error"); }
  };

  return (
    <div data-testid="admin-admins">
      <div className="dash-head">
        <div>
          <h1>Admin Team & Permissions</h1>
          <p>Multiple admins, role-based access. The Super Admin can create teammates with scoped permissions.</p>
        </div>
        {subTab === "admins" && <button className="btn btn-gold btn-sm" onClick={() => setShowNew(true)} data-testid="new-admin-btn">+ New Admin</button>}
        {subTab === "roles" && <button className="btn btn-gold btn-sm" onClick={() => setShowNewRole(true)} data-testid="new-role-btn">+ New Role</button>}
      </div>

      <div className="tabs" style={{ display: "flex", gap: 6, marginBottom: 16, borderBottom: "1px solid var(--glass-border)", paddingBottom: 8 }}>
        {[
          { id: "admins", label: "👥 Admins" },
          { id: "roles",  label: "🎭 Role Presets" },
          { id: "audit",  label: "🛡️ Audit Log" },
        ].map((t) => (
          <button
            key={t.id}
            className={`btn btn-xs ${subTab === t.id ? "btn-gold" : "btn-ghost"}`}
            onClick={() => setSubTab(t.id)}
            data-testid={`admin-subtab-${t.id}`}
          >{t.label}</button>
        ))}
      </div>

      {error && <div style={{ padding: 20, background: "rgba(255,120,120,0.08)", borderRadius: 8, border: "1px solid rgba(255,120,120,0.2)" }} data-testid="admin-admins-error">{error}</div>}

      {subTab === "admins" && !error && (
        <>
          {loading ? <div className="text-muted">Loading…</div> :
           admins.length === 0 ? <div className="text-muted">No admins yet</div> : (
            <div className="table-wrap">
              <table className="table" data-testid="admin-admins-table">
                <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Permissions</th><th>Status</th><th></th></tr></thead>
                <tbody>
                  {admins.map((a) => (
                    <tr key={a.id} data-testid={`admin-row-${a.id}`}>
                      <td><b>{a.first_name} {a.last_name}</b></td>
                      <td className="fs-12">{a.email}</td>
                      <td>
                        <span className={`pill ${a.admin_role === "super_admin" ? "gold" : "ghost"}`}>
                          {ROLE_LABELS[a.admin_role]?.split(" — ")[0] || a.admin_role}
                        </span>
                      </td>
                      <td className="fs-12" title={a.admin_permissions.join(", ")}>
                        {a.admin_permissions.length} permission{a.admin_permissions.length === 1 ? "" : "s"}
                      </td>
                      <td>
                        <span className={`pill ${a.active ? "green" : "red"}`}>{a.active ? "Active" : "Suspended"}</span>
                      </td>
                      <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                        <button className="btn btn-ghost btn-xs" onClick={() => setEditing(a)} data-testid={`edit-admin-${a.id}`}>Edit</button>
                        <button className="btn btn-ghost btn-xs" onClick={() => toggleActive(a)} data-testid={`toggle-admin-${a.id}`} style={{ marginLeft: 6 }}>
                          {a.active ? "Suspend" : "Reactivate"}
                        </button>
                        {a.admin_role !== "super_admin" && (
                          <button className="btn btn-red btn-xs" onClick={() => remove(a)} data-testid={`delete-admin-${a.id}`} style={{ marginLeft: 6 }}>Delete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {subTab === "roles" && !error && (
        <div className="table-wrap">
          <table className="table" data-testid="admin-roles-table">
            <thead><tr><th>Role ID</th><th>Permissions</th><th></th></tr></thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.id} data-testid={`role-row-${r.id}`}>
                  <td>
                    <b>{r.id}</b>
                    {r.readonly && <span className="pill gold" style={{ marginLeft: 8 }}>Protected</span>}
                  </td>
                  <td className="fs-12">
                    {r.permissions.length} permission{r.permissions.length === 1 ? "" : "s"}
                    <div className="text-muted fs-11" style={{ marginTop: 4 }}>
                      {r.permissions.slice(0, 6).join(", ")}{r.permissions.length > 6 ? "…" : ""}
                    </div>
                  </td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    {!r.readonly && (
                      <>
                        <button className="btn btn-ghost btn-xs" onClick={() => setEditingRole(r)} data-testid={`edit-role-${r.id}`}>Edit</button>
                        <button className="btn btn-red btn-xs" onClick={() => deleteRole(r)} data-testid={`delete-role-${r.id}`} style={{ marginLeft: 6 }}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {subTab === "audit" && !error && (
        <div className="table-wrap">
          {auditLog.length === 0 ? (
            <div className="text-muted">No audit entries yet.</div>
          ) : (
            <table className="table" data-testid="audit-log-table">
              <thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Target / Details</th></tr></thead>
              <tbody>
                {auditLog.map((e) => (
                  <tr key={e.id} data-testid={`audit-row-${e.id}`}>
                    <td className="fs-12 font-mono" style={{ whiteSpace: "nowrap" }}>{(e.created_at || "").replace("T", " ").slice(0, 19)}</td>
                    <td><span className="pill ghost">{e.action}</span></td>
                    <td className="fs-12">
                      {e.actor_email}
                      <div className="text-muted fs-11">{e.actor_role}</div>
                    </td>
                    <td className="fs-12">
                      {e.target_email || "—"}
                      {e.meta && Object.keys(e.meta).length > 0 && (
                        <div className="text-muted fs-11" style={{ marginTop: 2 }}>
                          {Object.entries(e.meta).map(([k, v]) => (
                            <span key={k} style={{ marginRight: 8 }}>{k}: {Array.isArray(v) ? `${v.length} items` : String(v)}</span>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {showNew && (
        <CreateAdminModal
          presets={presets}
          permissions={permissions}
          onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); toast?.("Admin created"); load(); }}
        />
      )}

      {editing && (
        <EditAdminModal
          admin={editing}
          presets={presets}
          permissions={permissions}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); toast?.("Saved"); load(); }}
        />
      )}

      {showNewRole && (
        <RoleModal
          permissions={permissions}
          onClose={() => setShowNewRole(false)}
          onSaved={() => { setShowNewRole(false); toast?.("Role created"); loadRoles(); load(); }}
        />
      )}
      {editingRole && (
        <RoleModal
          role={editingRole}
          permissions={permissions}
          onClose={() => setEditingRole(null)}
          onSaved={() => { setEditingRole(null); toast?.("Role saved"); loadRoles(); load(); }}
        />
      )}
    </div>
  );
}


// ─── Iter 56 — Role preset create / edit modal ───────────────────────────
function RoleModal({ role, permissions, onClose, onSaved }) {
  const isEdit = !!role;
  const [id, setId] = useState(role?.id || "");
  const [perms, setPerms] = useState(role?.permissions || []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async () => {
    setErr(null); setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/admin/roles/${role.id}`, { id: role.id, permissions: perms });
      } else {
        await api.post("/admin/roles", { id: id.trim().toLowerCase(), permissions: perms });
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="role-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560, width: "94%" }}>
        <div className="modal-head">
          <h3 style={{ margin: 0 }}>{isEdit ? `Edit role "${role.id}"` : "Create New Role"}</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 12 }}>
          {!isEdit && (
            <label>Role id (lowercase, hyphen or underscore only)
              <input value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. marketing" data-testid="role-id-input" />
            </label>
          )}
          <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "var(--gold-light)" }}>Permissions ({perms.length})</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {permissions.map((p) => (
                <label key={p} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={perms.includes(p)}
                    onChange={() => setPerms((cur) => cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p])}
                    data-testid={`role-perm-${p}`}
                  />
                  <span>{PERMISSION_LABELS[p] || p}</span>
                </label>
              ))}
            </div>
          </div>
          {err && <div style={{ color: "#ff8888", fontSize: 12 }}>{err}</div>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold btn-sm" onClick={submit} disabled={busy || (!isEdit && !id.trim())} data-testid="role-submit">
            {busy ? "Saving…" : (isEdit ? "Save Role" : "Create Role")}
          </button>
        </div>
      </div>
    </div>
  );
}
