import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

function LineItemsEditor({ lines, setLines }) {
  const add = () => setLines([...lines, { desc: "", qty: 1, unit_price: 0, amount: 0 }]);
  const patch = (i, k, v) => {
    const next = [...lines];
    next[i] = { ...next[i], [k]: v };
    if (k === "qty" || k === "unit_price") {
      next[i].amount = Number(next[i].qty || 0) * Number(next[i].unit_price || 0);
    }
    setLines(next);
  };
  const remove = (i) => setLines(lines.filter((_, j) => j !== i));
  return (
    <div>
      {lines.map((li, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "3fr 1fr 1fr 1fr 30px", gap: 6, marginBottom: 6 }}>
          <input placeholder="Description" value={li.desc} onChange={(e) => patch(i, "desc", e.target.value)}
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", padding: 8, color: "#fff", borderRadius: 6 }} />
          <input type="number" value={li.qty} onChange={(e) => patch(i, "qty", e.target.value)}
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", padding: 8, color: "#fff", borderRadius: 6 }} />
          <input type="number" placeholder="Unit ₹" value={li.unit_price} onChange={(e) => patch(i, "unit_price", e.target.value)}
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", padding: 8, color: "#fff", borderRadius: 6 }} />
          <input readOnly value={li.amount} style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", padding: 8, color: "#f6d366", borderRadius: 6 }} />
          <button onClick={() => remove(i)} style={{ background: "none", border: "1px solid rgba(255,120,120,0.3)", color: "#ff8888", borderRadius: 6, cursor: "pointer" }}>×</button>
        </div>
      ))}
      <button className="btn btn-ghost btn-sm" onClick={add}>+ Add line</button>
    </div>
  );
}

export default function Finance() {
  const [summary, setSummary] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [clients, setClients] = useState([]);
  const [platformView, setPlatformView] = useState(null);
  const [tab, setTab] = useState("summary");
  const [showInv, setShowInv] = useState(false);
  const [invForm, setInvForm] = useState({ client_id: "", event_id: "", tax_pct: 18, notes: "", due_date: "" });
  const [lines, setLines] = useState([{ desc: "", qty: 1, unit_price: 0, amount: 0 }]);
  const [expForm, setExpForm] = useState({ category: "", amount: 0, date: new Date().toISOString().slice(0, 10), notes: "" });

  const load = () => {
    api.get("/agency/finance/summary").then((r) => setSummary(r.data)).catch(() => {});
    api.get("/agency/invoices").then((r) => setInvoices(r.data || [])).catch(() => {});
    api.get("/agency/expenses").then((r) => setExpenses(r.data || [])).catch(() => {});
    api.get("/agency/clients").then((r) => setClients(r.data || [])).catch(() => {});
    api.get("/agency/financial-view").then((r) => setPlatformView(r.data)).catch(() => setPlatformView({ artists: [], bookings: [], totals: {} }));
  };
  useEffect(() => { load(); }, []);

  const createInvoice = async () => {
    if (!invForm.client_id) { alert("Pick a client"); return; }
    if (lines.length === 0) return;
    await api.post("/agency/invoices", { ...invForm, tax_pct: Number(invForm.tax_pct), line_items: lines });
    setShowInv(false); setLines([{ desc: "", qty: 1, unit_price: 0, amount: 0 }]);
    setInvForm({ client_id: "", event_id: "", tax_pct: 18, notes: "", due_date: "" });
    load();
  };
  const patchInv = async (id, status) => { await api.patch(`/agency/invoices/${id}`, { status }); load(); };
  const addExp = async () => {
    if (!expForm.category || !expForm.amount) return;
    await api.post("/agency/expenses", { ...expForm, amount: Number(expForm.amount) });
    setExpForm({ category: "", amount: 0, date: new Date().toISOString().slice(0, 10), notes: "" });
    load();
  };

  return (
    <div data-testid="agency-finance">
      <div className="ag-section-head">
        <div><h2>Finance</h2><div className="fs-13">Invoices, expenses, platform commissions — one dashboard.</div></div>
        <button className="btn btn-gold btn-sm" onClick={() => setShowInv(true)} data-testid="ag-new-invoice">+ New Invoice</button>
      </div>

      <div className="ag-tabs">
        <button className={`ag-tab ${tab === "summary" ? "active" : ""}`} onClick={() => setTab("summary")}>Summary</button>
        <button className={`ag-tab ${tab === "invoices" ? "active" : ""}`} onClick={() => setTab("invoices")}>Invoices ({invoices.length})</button>
        <button className={`ag-tab ${tab === "expenses" ? "active" : ""}`} onClick={() => setTab("expenses")}>Expenses ({expenses.length})</button>
        <button className={`ag-tab ${tab === "platform" ? "active" : ""}`} onClick={() => setTab("platform")} data-testid="ag-tab-platform">
          Platform Bookings{platformView ? ` (${(platformView.bookings || []).length})` : ""}
        </button>
      </div>

      {tab === "summary" && summary && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          <div className="ag-card"><div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Offline Revenue</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, marginTop: 6 }}>₹{summary.offline_revenue.toLocaleString("en-IN")}</div></div>
          <div className="ag-card"><div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Outstanding</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, marginTop: 6, color: "#ffd270" }}>₹{summary.offline_outstanding.toLocaleString("en-IN")}</div></div>
          <div className="ag-card"><div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Platform Commission</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, marginTop: 6, color: "#f6d366" }}>₹{summary.platform_commission.toLocaleString("en-IN")}</div></div>
          <div className="ag-card"><div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Net (after expenses)</div><div style={{ fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 700, marginTop: 6, color: "#6ee7a8" }}>₹{summary.net.toLocaleString("en-IN")}</div></div>
        </div>
      )}

      {tab === "invoices" && (
        invoices.length === 0 ? <div className="ag-empty"><h3>No invoices yet</h3><div>Click "+ New Invoice" to create one.</div></div> :
        <table className="ag-table">
          <thead><tr><th>#</th><th>Client</th><th>Date</th><th>Total</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td><b>{inv.number}</b></td>
                <td>{clients.find((c) => c.id === inv.client_id)?.name || "—"}</td>
                <td>{(inv.created_at || "").slice(0, 10)}</td>
                <td>₹{inv.total.toLocaleString("en-IN")}</td>
                <td><span className={`ag-badge ${inv.status === "paid" ? "ok" : inv.status === "partial" ? "warn" : ""}`}>{inv.status}</span></td>
                <td>
                  {inv.status !== "paid" && <button className="btn btn-gold btn-sm" onClick={() => patchInv(inv.id, "paid")}>Mark paid</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "expenses" && (
        <>
          <div className="ag-card" style={{ marginBottom: 12 }}>
            <div className="ag-form-grid">
              <label>Category<input value={expForm.category} onChange={(e) => setExpForm({ ...expForm, category: e.target.value })} placeholder="Travel, Studio, …" /></label>
              <label>Amount ₹<input type="number" value={expForm.amount} onChange={(e) => setExpForm({ ...expForm, amount: e.target.value })} /></label>
              <label>Date<input type="date" value={expForm.date} onChange={(e) => setExpForm({ ...expForm, date: e.target.value })} /></label>
              <label>Notes<input value={expForm.notes} onChange={(e) => setExpForm({ ...expForm, notes: e.target.value })} /></label>
              <label style={{ justifyContent: "flex-end" }}><span>&nbsp;</span><button className="btn btn-gold btn-sm" onClick={addExp}>Log expense</button></label>
            </div>
          </div>
          {expenses.length === 0 ? <div className="ag-empty"><h3>No expenses logged</h3></div> :
            <table className="ag-table"><thead><tr><th>Date</th><th>Category</th><th>Amount</th><th>Notes</th></tr></thead>
              <tbody>{expenses.map((e) => <tr key={e.id}><td>{e.date}</td><td>{e.category}</td><td>₹{e.amount.toLocaleString("en-IN")}</td><td className="text-muted">{e.notes}</td></tr>)}</tbody>
            </table>
          }
        </>
      )}

      {tab === "platform" && (
        <div data-testid="ag-platform-financial-view">
          {!platformView ? (
            <div className="ag-empty"><h3>Loading platform bookings…</h3></div>
          ) : (platformView.bookings || []).length === 0 ? (
            <div className="ag-empty">
              <h3>No platform bookings yet</h3>
              <div>Bookings made through BookTalent for your roster artists will appear here.</div>
            </div>
          ) : (
            <>
              {/* KPI strip */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 14 }}>
                <div className="ag-card">
                  <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Customer Received</div>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 700, marginTop: 6, color: "#6ee7a8" }}>
                    ₹{Number(platformView.totals?.customer_received || 0).toLocaleString("en-IN")}
                  </div>
                </div>
                <div className="ag-card">
                  <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Customer Total</div>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 700, marginTop: 6, color: "#f6d366" }}>
                    ₹{Number(platformView.totals?.customer_total || 0).toLocaleString("en-IN")}
                  </div>
                </div>
                <div className="ag-card">
                  <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Payouts Paid</div>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 700, marginTop: 6, color: "#6ee7a8" }} data-testid="ag-payouts-paid">
                    {platformView.totals?.payout_paid_count || 0}
                  </div>
                </div>
                <div className="ag-card">
                  <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>Payouts Pending</div>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 700, marginTop: 6, color: "#ffd270" }} data-testid="ag-payouts-pending">
                    {platformView.totals?.payout_pending_count || 0}
                  </div>
                </div>
              </div>

              <table className="ag-table" data-testid="ag-platform-bookings-table">
                <thead>
                  <tr>
                    <th>Ref</th><th>Artist</th><th>Event</th>
                    <th>Customer Payment</th><th>Payout</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {(platformView.bookings || []).map((b) => {
                    const payTint = b.customer_payment_status === "fully_paid" ? "ok"
                                    : b.customer_payment_status === "partially_paid" ? "warn" : "";
                    const payoutTint = b.artist_payout_status === "paid" ? "ok" : "warn";
                    return (
                      <tr key={b.id} data-testid={`ag-plat-row-${b.id}`}>
                        <td><b>{b.ref || b.id.slice(0, 8)}</b></td>
                        <td className="fs-13">{b.artist_id?.slice(0, 8)}</td>
                        <td className="fs-13">{b.event_type || "—"}<br/><span className="text-muted fs-11">{b.event_date}</span></td>
                        <td>
                          <div className="fs-13">
                            ₹{Number(b.customer_payment_received || 0).toLocaleString("en-IN")}
                            <span className="text-muted"> / ₹{Number(b.customer_payment_total || 0).toLocaleString("en-IN")}</span>
                          </div>
                          <span className={`ag-badge ${payTint}`}>{b.customer_payment_status}</span>
                        </td>
                        <td><span className={`ag-badge ${payoutTint}`}>{b.artist_payout_status}</span></td>
                        <td>
                          <a href={`/bookings/${b.id}`} className="btn btn-ghost btn-sm" data-testid={`ag-view-${b.id}`}>Details</a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {/* Invoice modal */}
      {showInv && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 200, display: "grid", placeItems: "center", padding: 20 }} onClick={() => setShowInv(false)}>
          <div className="ag-card" style={{ maxWidth: 720, width: "100%" }} onClick={(e) => e.stopPropagation()}>
            <div className="ag-section-head"><h2 style={{ fontSize: 22 }}>New Invoice</h2></div>
            <div className="ag-form-grid">
              <label>Client
                <select value={invForm.client_id} onChange={(e) => setInvForm({ ...invForm, client_id: e.target.value })}>
                  <option value="">— pick —</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label>Due date<input type="date" value={invForm.due_date} onChange={(e) => setInvForm({ ...invForm, due_date: e.target.value })} /></label>
              <label>Tax %<input type="number" value={invForm.tax_pct} onChange={(e) => setInvForm({ ...invForm, tax_pct: e.target.value })} /></label>
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginBottom: 8 }}>Line Items</div>
              <LineItemsEditor lines={lines} setLines={setLines} />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
              <button className="btn btn-ghost" onClick={() => setShowInv(false)}>Cancel</button>
              <button className="btn btn-gold" onClick={createInvoice} data-testid="ag-inv-save">Create Invoice</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
