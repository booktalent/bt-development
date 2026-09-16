/**
 * AdminCategoryRequests — Iter 66
 *
 * Admin queue for artists who requested a category not yet in the master
 * list. For each pending row admin can either:
 *   - Assign an existing master category (dupe-avoidance via the
 *     `/admin/category-requests/similar` helper)
 *   - Create a brand-new master category (auto-adds to the artist listing
 *     system)
 *   - Reject with a required reason
 *
 * Endpoints:
 *   GET  /api/admin/category-requests?status=pending|approved|rejected
 *   GET  /api/admin/category-requests/similar?name=<text>
 *   POST /api/admin/category-requests/{id}/approve  { existing_slug? | new_name?, icon? }
 *   POST /api/admin/category-requests/{id}/reject   { reason }
 */
import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import useHighlightRow from "../../lib/useHighlightRow";

const STATUS_TABS = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "", label: "All" },
];

export default function AdminCategoryRequests({ toast }) {
  const [status, setStatus] = useState("pending");
  const [rows, setRows] = useState([]);
  const [drawer, setDrawer] = useState(null); // active request
  const [similar, setSimilar] = useState([]);
  const [mode, setMode] = useState("new"); // "new" | "reuse" | "reject"
  const [chosenSlug, setChosenSlug] = useState("");
  const [newName, setNewName] = useState("");
  const [icon, setIcon] = useState("🎼");
  const [rejectReason, setRejectReason] = useState("");
  const [busy, setBusy] = useState(false);

  useHighlightRow({ prefix: "cat-req-row", dataKey: rows.length });

  const load = () => {
    const q = status ? `?status=${status}` : "";
    api.get(`/admin/category-requests${q}`)
      .then((r) => setRows(r.data || []))
      .catch(() => setRows([]));
  };
  useEffect(load, [status]);

  const openRow = async (r) => {
    setDrawer(r);
    setMode("new");
    setNewName(r.requested_name || "");
    setIcon("🎼");
    setChosenSlug("");
    setRejectReason("");
    try {
      const s = await api.get(`/admin/category-requests/similar?name=${encodeURIComponent(r.requested_name)}`);
      setSimilar(s.data || []);
    } catch { setSimilar([]); }
  };

  const doApprove = async () => {
    if (!drawer) return;
    if (mode === "reuse" && !chosenSlug) { toast("Pick an existing category to reuse", "error"); return; }
    if (mode === "new" && !newName.trim()) { toast("New category name is required", "error"); return; }
    setBusy(true);
    try {
      const body = mode === "reuse"
        ? { existing_slug: chosenSlug }
        : { new_name: newName.trim(), icon: icon || undefined };
      const r = await api.post(`/admin/category-requests/${drawer.id}/approve`, body);
      toast(`Approved — assigned to "${r.data.assigned_name}"`, "success");
      setDrawer(null);
      load();
    } catch (e) {
      toast(e?.response?.data?.detail || "Approve failed", "error");
    }
    setBusy(false);
  };

  const doReject = async () => {
    if (!drawer) return;
    if (!rejectReason.trim() || rejectReason.trim().length < 3) {
      toast("Please provide a rejection reason", "error"); return;
    }
    setBusy(true);
    try {
      await api.post(`/admin/category-requests/${drawer.id}/reject`, { reason: rejectReason.trim() });
      toast("Rejected — artist notified", "success");
      setDrawer(null);
      load();
    } catch (e) {
      toast(e?.response?.data?.detail || "Reject failed", "error");
    }
    setBusy(false);
  };

  return (
    <div className="card" data-testid="admin-category-requests">
      <div className="card-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div className="card-title">🎼 Artist Category Requests</div>
          <div className="text-muted fs-12">Artists whose desired category isn't in the master list yet. Approve to publish, reject with a reason, or reuse an existing category for near-duplicates.</div>
        </div>
        <div className="flex gap-8">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key || "all"}
              className={`btn btn-ghost btn-sm ${status === t.key ? "btn-purple" : ""}`}
              onClick={() => setStatus(t.key)}
              data-testid={`cat-req-tab-${t.key || "all"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Request ID</th>
              <th>Artist</th>
              <th>Requested Category</th>
              <th>City</th>
              <th>Requested On</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={7} className="empty">No requests to show.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} data-testid={`cat-req-row-${r.id}`}>
                <td><code className="fs-11">{r.id.slice(0, 8)}</code></td>
                <td>
                  <div className="fw-600">{r.artist_name}</div>
                  <div className="text-muted fs-11">{r.artist_email}</div>
                </td>
                <td>
                  <div className="fw-600 text-gold">{r.requested_name}</div>
                  <div className="text-muted fs-11" style={{ maxWidth: 260 }}>
                    {(r.description || "").slice(0, 90)}{(r.description || "").length > 90 ? "…" : ""}
                  </div>
                </td>
                <td className="fs-12">{r.city || "—"}</td>
                <td className="fs-12">{(r.created_at || "").slice(0, 10)}</td>
                <td>
                  <span className={`pill ${r.status === "approved" ? "pill-green" : r.status === "rejected" ? "pill-red" : "pill-amber"}`}>
                    {r.status}
                  </span>
                </td>
                <td>
                  <button className="btn btn-purple btn-xs" onClick={() => openRow(r)} data-testid={`cat-req-open-${r.id}`}>
                    {r.status === "pending" ? "Review" : "View"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {drawer && (
        <div
          onClick={() => setDrawer(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 200, display: "flex", justifyContent: "flex-end" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: 640, maxWidth: "95vw", background: "#0F0F1B", color: "#F0EEFF", padding: 26, overflow: "auto", boxShadow: "-8px 0 32px rgba(0,0,0,0.55)" }}
            data-testid="cat-req-drawer"
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0 }}>Review Request</h3>
                <div className="text-muted fs-12">from {drawer.artist_name} · {drawer.artist_email}</div>
              </div>
              <button className="btn btn-link" onClick={() => setDrawer(null)} data-testid="cat-req-close">✕</button>
            </div>

            <div style={{ padding: 12, borderRadius: 10, background: "rgba(255,255,255,0.04)", marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: "rgba(240,238,255,0.5)" }}>Requested Category</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#F1D17A", marginTop: 4 }}>{drawer.requested_name}</div>
              {drawer.description && <div className="fs-13" style={{ marginTop: 8 }}>{drawer.description}</div>}
              {drawer.example_artists && <div className="text-muted fs-12" style={{ marginTop: 6 }}>Similar artists: {drawer.example_artists}</div>}
              {drawer.portfolio_link && (
                <div className="fs-12" style={{ marginTop: 6 }}>
                  Portfolio: <a href={drawer.portfolio_link} target="_blank" rel="noopener noreferrer" style={{ color: "#F1D17A" }}>{drawer.portfolio_link}</a>
                </div>
              )}
            </div>

            {drawer.status !== "pending" ? (
              <div style={{ padding: 14, borderRadius: 10, background: drawer.status === "approved" ? "rgba(34,197,94,0.10)" : "rgba(239,68,68,0.10)" }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {drawer.status === "approved" ? `Approved — assigned to "${drawer.assigned_name || "—"}"` : "Rejected"}
                </div>
                {drawer.rejection_reason && <div className="fs-13">Reason: {drawer.rejection_reason}</div>}
                {drawer.decided_at && <div className="text-muted fs-11" style={{ marginTop: 6 }}>Decided {drawer.decided_at.slice(0, 16).replace("T", " ")}</div>}
              </div>
            ) : (
              <>
                <div className="flex gap-8" style={{ marginBottom: 14 }}>
                  <button className={`btn btn-sm ${mode === "new" ? "btn-purple" : "btn-ghost"}`} onClick={() => setMode("new")} data-testid="cat-req-mode-new">Create new</button>
                  <button className={`btn btn-sm ${mode === "reuse" ? "btn-purple" : "btn-ghost"}`} onClick={() => setMode("reuse")} data-testid="cat-req-mode-reuse">Reuse existing</button>
                  <button className={`btn btn-sm ${mode === "reject" ? "btn-red" : "btn-ghost"}`} onClick={() => setMode("reject")} data-testid="cat-req-mode-reject">Reject</button>
                </div>

                {similar.length > 0 && mode !== "reject" && (
                  <div style={{ padding: 10, borderRadius: 8, background: "rgba(212,175,55,0.06)", border: "1px solid rgba(212,175,55,0.2)", marginBottom: 14 }} data-testid="cat-req-similar">
                    <div className="text-muted fs-11" style={{ marginBottom: 6 }}>Possibly similar existing categories — pick one to reuse (avoids duplicates):</div>
                    <div className="flex gap-6" style={{ flexWrap: "wrap" }}>
                      {similar.map((s) => (
                        <button
                          key={s.slug}
                          className={`btn btn-xs ${chosenSlug === s.slug ? "btn-gold" : "btn-ghost"}`}
                          onClick={() => { setMode("reuse"); setChosenSlug(s.slug); }}
                          data-testid={`cat-req-similar-${s.slug}`}
                        >
                          {s.icon ? `${s.icon} ` : ""}{s.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {mode === "new" && (
                  <>
                    <div className="field">
                      <div className="field-label">New Category Name</div>
                      <input className="field-input" value={newName} onChange={(e) => setNewName(e.target.value)} data-testid="cat-req-new-name" />
                    </div>
                    <div className="field">
                      <div className="field-label">Icon (emoji)</div>
                      <input className="field-input" value={icon} onChange={(e) => setIcon(e.target.value)} data-testid="cat-req-new-icon" />
                    </div>
                    <button className="btn btn-gold" onClick={doApprove} disabled={busy} data-testid="cat-req-approve-new">
                      {busy ? "Creating…" : "✅ Create Category & Approve"}
                    </button>
                  </>
                )}

                {mode === "reuse" && (
                  <>
                    <div className="text-muted fs-12" style={{ marginBottom: 8 }}>
                      Selected: <b className="text-gold">{chosenSlug || "— none —"}</b>
                    </div>
                    <button className="btn btn-gold" onClick={doApprove} disabled={busy || !chosenSlug} data-testid="cat-req-approve-reuse">
                      {busy ? "Assigning…" : "✅ Assign Existing & Approve"}
                    </button>
                  </>
                )}

                {mode === "reject" && (
                  <>
                    <div className="field">
                      <div className="field-label">Rejection Reason (shown to the artist)</div>
                      <textarea
                        className="field-input"
                        rows={4}
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="e.g. This is a sub-genre of Bollywood Vocalist — please re-list under that category."
                        data-testid="cat-req-reject-reason"
                      />
                    </div>
                    <button className="btn btn-red" onClick={doReject} disabled={busy} data-testid="cat-req-reject-submit">
                      {busy ? "Rejecting…" : "❌ Reject Request"}
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
