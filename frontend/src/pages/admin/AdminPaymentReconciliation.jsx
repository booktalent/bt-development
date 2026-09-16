/**
 * AdminPaymentReconciliation — Iter 62
 *
 * Finance dashboard for auditing every payment attempt across Easebuzz +
 * Razorpay. Two views in one screen:
 *   1. Payments table (aggregated view of `payments` collection)
 *   2. Raw logs viewer (every request / response / callback / hash-mismatch)
 *
 * Endpoints:
 *   GET /api/admin/payments?gateway=&status=&q=&page=&limit=
 *   GET /api/admin/payment-logs?txnid=&kind=&page=&limit=
 *   GET /api/admin/payments/summary
 */
import React, { useEffect, useMemo, useState } from "react";
import api from "../../lib/api";
import useHighlightRow from "../../lib/useHighlightRow";

const STATUS_TONES = {
  completed: { bg: "#dcfce7", fg: "#166534" },
  pending: { bg: "#fef3c7", fg: "#92400e" },
  failed: { bg: "#fee2e2", fg: "#991b1b" },
  refunded: { bg: "#e0e7ff", fg: "#3730a3" },
};

const fmtINR = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }); }
  catch { return String(iso); }
};

export default function AdminPaymentReconciliation({ toast }) {
  const [tab, setTab] = useState("payments");
  const [summary, setSummary] = useState(null);
  const [filters, setFilters] = useState({ gateway: "", status: "", kind: "", q: "" });
  const [logFilters, setLogFilters] = useState({ txnid: "", kind: "" });
  const [payments, setPayments] = useState({ items: [], total: 0, page: 1, limit: 25 });
  const [logs, setLogs] = useState({ items: [], total: 0, page: 1, limit: 50 });
  const [refundFilter, setRefundFilter] = useState("");
  const [refunds, setRefunds] = useState({ items: [], total: 0, page: 1, limit: 25 });
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(null); // txnid opened in drawer

  // Iter 65 — When notification links to /admin (Payment Reconciliation tab)
  // with ?highlight=<payment_id>, scroll & pulse-flash the matching row on
  // whichever inner tab it lives (payments or refunds).
  useHighlightRow({ prefix: "payment-row", enabled: tab === "payments", dataKey: payments.items.length });
  useHighlightRow({ prefix: "refund-row", enabled: tab === "refunds", dataKey: refunds.items.length });

  const loadSummary = () => {
    api.get("/admin/payments/summary")
      .then((r) => setSummary(r.data))
      .catch(() => setSummary(null));
  };

  const loadPayments = (page = 1) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (filters.gateway) p.set("gateway", filters.gateway);
    if (filters.status) p.set("status", filters.status);
    if (filters.kind) p.set("kind", filters.kind);
    if (filters.q) p.set("q", filters.q);
    p.set("page", page);
    p.set("limit", 25);
    api.get(`/admin/payments?${p}`)
      .then((r) => setPayments(r.data))
      .catch(() => toast("Failed to load payments", "error"))
      .finally(() => setLoading(false));
  };

  const loadLogs = (page = 1) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (logFilters.txnid) p.set("txnid", logFilters.txnid);
    if (logFilters.kind) p.set("kind", logFilters.kind);
    p.set("page", page);
    p.set("limit", 50);
    api.get(`/admin/payment-logs?${p}`)
      .then((r) => setLogs(r.data))
      .catch(() => toast("Failed to load logs", "error"))
      .finally(() => setLoading(false));
  };

  const loadRefunds = (page = 1) => {
    setLoading(true);
    const p = new URLSearchParams();
    if (refundFilter) p.set("status", refundFilter);
    p.set("page", page);
    p.set("limit", 25);
    api.get(`/admin/refunds?${p}`)
      .then((r) => setRefunds(r.data))
      .catch(() => toast("Failed to load refunds", "error"))
      .finally(() => setLoading(false));
  };

  const retryRefund = async (payment_id) => {
    if (!window.confirm("Retry Easebuzz refund for this payment?")) return;
    try {
      const r = await api.post(`/admin/refunds/${payment_id}/retry`);
      toast(r.data?.ok ? "Refund succeeded" : (r.data?.reason || "Refund attempt made"), r.data?.ok ? "success" : "warn");
      loadRefunds(refunds.page);
    } catch (e) {
      toast(e?.response?.data?.detail || "Refund retry failed", "error");
    }
  };

  // Iter 65 — respect ?subtab=refunds|payments|logs from notification links so
  // the correct tab auto-activates before `useHighlightRow` fires.
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const st = sp.get("subtab");
    if (st === "refunds" || st === "payments" || st === "logs") {
      setTab(st);
      if (st === "refunds") loadRefunds(1);
      if (st === "logs") loadLogs(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadSummary();
    loadPayments(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totals = useMemo(() => {
    if (!summary) return { count: 0, amount: 0, hash: 0 };
    const items = summary.breakdown || [];
    return {
      count: items.reduce((a, b) => a + b.count, 0),
      amount: items.reduce((a, b) => a + (b.amount || 0), 0),
      completed: items.filter((x) => x._id.status === "completed").reduce((a, b) => a + b.count, 0),
      failed: items.filter((x) => x._id.status === "failed").reduce((a, b) => a + b.count, 0),
      pending: items.filter((x) => x._id.status === "pending").reduce((a, b) => a + b.count, 0),
      hash: summary.hash_mismatches || 0,
    };
  }, [summary]);

  return (
    <div data-testid="admin-payment-reconciliation">
      <div className="dash-head">
        <div>
          <h1>Payment Reconciliation</h1>
          <p>Audit every payment attempt, callback and hash verification across all gateways.</p>
        </div>
      </div>

      {/* Summary strip */}
      <div className="kpi-grid mb-24" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
        <Kpi label="Total Payments" num={totals.count} testId="pr-kpi-total" />
        <Kpi label="Completed" num={totals.completed || 0} tone="success" testId="pr-kpi-completed" />
        <Kpi label="Pending" num={totals.pending || 0} tone="warn" testId="pr-kpi-pending" />
        <Kpi label="Failed" num={totals.failed || 0} tone="danger" testId="pr-kpi-failed" />
        <Kpi label="Hash Mismatches" num={totals.hash} tone={totals.hash ? "danger" : "success"} testId="pr-kpi-hash" />
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <TabBtn active={tab === "payments"} onClick={() => setTab("payments")} testId="tab-payments">Payments</TabBtn>
        <TabBtn active={tab === "refunds"} onClick={() => { setTab("refunds"); if (!refunds.items.length) loadRefunds(1); }} testId="tab-refunds">Refunds</TabBtn>
        <TabBtn active={tab === "logs"} onClick={() => { setTab("logs"); if (!logs.items.length) loadLogs(1); }} testId="tab-logs">Raw Logs</TabBtn>
      </div>

      {tab === "payments" && (
        <>
          {/* Filters */}
          <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label className="stack" style={{ minWidth: 160 }}>
              <span>Gateway</span>
              <select className="input" value={filters.gateway}
                onChange={(e) => setFilters((f) => ({ ...f, gateway: e.target.value }))}
                data-testid="filter-gateway">
                <option value="">All</option>
                <option value="easebuzz">Easebuzz</option>
                <option value="razorpay">Razorpay (Legacy)</option>
                <option value="razorpay_mock">Razorpay (Legacy Mock)</option>
              </select>
            </label>
            <label className="stack" style={{ minWidth: 160 }}>
              <span>Status</span>
              <select className="input" value={filters.status}
                onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
                data-testid="filter-status">
                <option value="">All</option>
                <option value="completed">Completed</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
                <option value="refunded">Refunded</option>
              </select>
            </label>
            <label className="stack" style={{ minWidth: 160 }}>
              <span>Kind</span>
              <select className="input" value={filters.kind}
                onChange={(e) => setFilters((f) => ({ ...f, kind: e.target.value }))}
                data-testid="filter-kind">
                <option value="">All</option>
                <option value="booking">Booking</option>
                <option value="subscription">Subscription</option>
                <option value="boost">Boost</option>
              </select>
            </label>
            <label className="stack" style={{ flex: 1, minWidth: 200 }}>
              <span>Search (txnid / easepayid / booking id)</span>
              <input className="input" value={filters.q}
                onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && loadPayments(1)}
                placeholder="BT260728…" data-testid="filter-q" />
            </label>
            <button className="btn btn-primary" onClick={() => loadPayments(1)} data-testid="btn-apply-filters">Apply</button>
            <button className="btn btn-secondary" onClick={() => { setFilters({ gateway: "", status: "", kind: "", q: "" }); setTimeout(() => loadPayments(1), 0); }} data-testid="btn-clear-filters">Clear</button>
          </div>

          {/* Payments table */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table" style={{ width: "100%" }} data-testid="payments-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Gateway</th>
                  <th>Txn / Order ID</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Bookings</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {payments.items.map((p) => (
                  <tr key={p.id} data-testid={`payment-row-${p.id}`}>
                    <td>{fmtDate(p.created_at)}</td>
                    <td>
                      {p.gateway}
                      {p.environment && <span className="text-muted" style={{ fontSize: 11, marginLeft: 4 }}>({p.environment})</span>}
                    </td>
                    <td><code style={{ fontSize: 12 }}>{p.txnid || p.razorpay_order_id || p.id.slice(0, 12)}</code></td>
                    <td>{fmtINR(p.amount)}</td>
                    <td><StatusPill status={p.status} /></td>
                    <td>
                      {(p.booking_refs || []).slice(0, 2).map((r) => (
                        <code key={r} style={{ display: "inline-block", marginRight: 6, fontSize: 11 }}>{r}</code>
                      ))}
                      {(p.booking_refs || []).length > 2 && <span className="text-muted">+{p.booking_refs.length - 2}</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn btn-link" onClick={() => {
                        setExpanded(p);
                        if (p.txnid) {
                          setLogFilters({ txnid: p.txnid, kind: "" });
                        }
                      }} data-testid={`btn-view-${p.id}`}>View</button>
                    </td>
                  </tr>
                ))}
                {!payments.items.length && !loading && (
                  <tr><td colSpan={7} style={{ textAlign: "center", padding: 32, color: "#6b7280" }}>No payments match your filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <Pagination page={payments.page} total={payments.total} limit={payments.limit} onGo={(p) => loadPayments(p)} />
        </>
      )}

      {tab === "refunds" && (
        <>
          <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label className="stack" style={{ minWidth: 200 }}>
              <span>Refund Status</span>
              <select className="input" value={refundFilter}
                onChange={(e) => setRefundFilter(e.target.value)}
                data-testid="filter-refund-status">
                <option value="">All</option>
                <option value="successful">Successful</option>
                <option value="initiated">Initiated</option>
                <option value="failed">Failed</option>
                <option value="not_applicable">Not applicable (legacy)</option>
              </select>
            </label>
            <button className="btn btn-primary" onClick={() => loadRefunds(1)} data-testid="btn-load-refunds">Apply</button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "auto" }}>
            <table className="table" style={{ width: "100%", minWidth: 1200 }} data-testid="refunds-table">
              <thead>
                <tr>
                  <th>Refund Date</th>
                  <th>Booking</th>
                  <th>Customer</th>
                  <th>Artist</th>
                  <th>Original Paid</th>
                  <th>Refund Amount</th>
                  <th>Reason</th>
                  <th>Status</th>
                  <th>Refund Ref</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {refunds.items.map((r) => (
                  <tr key={r.payment_id} data-testid={`refund-row-${r.payment_id}`}>
                    <td style={{ fontSize: 12 }}>{fmtDate(r.refund_at)}</td>
                    <td>
                      {(r.booking_refs || []).map((br) => (
                        <code key={br} style={{ display: "block", fontSize: 11 }}>{br}</code>
                      ))}
                      <span style={{ fontSize: 10, color: "#9ca3af" }}>{r.event_date || ""}</span>
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {r.customer_name || "—"}
                      <div style={{ fontSize: 10, color: "#9ca3af" }}>{r.customer_email || ""}</div>
                    </td>
                    <td style={{ fontSize: 12 }}>{r.artist_name || "—"}</td>
                    <td>{fmtINR(r.original_amount)}</td>
                    <td>{fmtINR(r.refund_amount)}</td>
                    <td style={{ fontSize: 12, maxWidth: 220 }}>{r.refund_reason || "—"}</td>
                    <td><RefundPill status={r.refund_status} /></td>
                    <td style={{ fontSize: 11 }}>
                      {r.refund_id && <div><code>{r.refund_id}</code></div>}
                      {r.easebuzz_id && <div style={{ color: "#9ca3af" }}><code>{r.easebuzz_id}</code></div>}
                      {r.refund_error && (
                        <div style={{ color: "#f87171", fontSize: 10 }}>{r.refund_error.slice(0, 80)}</div>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {r.refund_status === "failed" && (
                        <button className="btn btn-secondary btn-sm" onClick={() => retryRefund(r.payment_id)}
                          data-testid={`btn-retry-refund-${r.payment_id}`}>Retry</button>
                      )}
                    </td>
                  </tr>
                ))}
                {!refunds.items.length && !loading && (
                  <tr><td colSpan={10} style={{ textAlign: "center", padding: 32, color: "#6b7280" }}>
                    No refunds yet. Refunds are triggered automatically when a booking is rejected, cancelled or expires without artist confirmation.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={refunds.page} total={refunds.total} limit={refunds.limit} onGo={(p) => loadRefunds(p)} />
        </>
      )}

      {tab === "logs" && (
        <>
          <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end" }}>
            <label className="stack" style={{ minWidth: 200 }}>
              <span>Transaction ID</span>
              <input className="input" value={logFilters.txnid}
                onChange={(e) => setLogFilters((f) => ({ ...f, txnid: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && loadLogs(1)}
                placeholder="BT260728…" data-testid="log-filter-txnid" />
            </label>
            <label className="stack" style={{ minWidth: 220 }}>
              <span>Kind (substring)</span>
              <input className="input" value={logFilters.kind}
                onChange={(e) => setLogFilters((f) => ({ ...f, kind: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && loadLogs(1)}
                placeholder="callback / retrieve / hash_mismatch" data-testid="log-filter-kind" />
            </label>
            <button className="btn btn-primary" onClick={() => loadLogs(1)} data-testid="btn-load-logs">Load</button>
            <button className="btn btn-secondary" onClick={() => { setLogFilters({ txnid: "", kind: "" }); setTimeout(() => loadLogs(1), 0); }} data-testid="btn-clear-logs">Clear</button>
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table className="table" style={{ width: "100%" }} data-testid="logs-table">
              <thead>
                <tr><th style={{ width: 200 }}>When</th><th style={{ width: 240 }}>Kind</th><th style={{ width: 200 }}>Txn ID</th><th>Data</th></tr>
              </thead>
              <tbody>
                {logs.items.map((l, idx) => (
                  <tr key={idx} data-testid={`log-row-${idx}`}>
                    <td style={{ fontSize: 12 }}>{fmtDate(l.created_at)}</td>
                    <td><code style={{ fontSize: 11 }}>{l.kind}</code></td>
                    <td><code style={{ fontSize: 11 }}>{l.txnid || "—"}</code></td>
                    <td>
                      <details>
                        <summary style={{ cursor: "pointer", fontSize: 12, color: "#6b7280" }}>Show JSON</summary>
                        <pre style={{ fontSize: 11, background: "#0F0F1B", color: "#F0EEFF", padding: 12, borderRadius: 6, overflow: "auto", maxHeight: 240, marginTop: 8 }}>
{JSON.stringify(l.data, null, 2)}
                        </pre>
                      </details>
                    </td>
                  </tr>
                ))}
                {!logs.items.length && !loading && (
                  <tr><td colSpan={4} style={{ textAlign: "center", padding: 32, color: "#6b7280" }}>No logs yet. Click Load or narrow the filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={logs.page} total={logs.total} limit={logs.limit} onGo={(p) => loadLogs(p)} />
        </>
      )}

      {expanded && (
        <PaymentDrawer p={expanded} onClose={() => setExpanded(null)} onJumpToLogs={() => {
          setExpanded(null);
          setTab("logs");
          setTimeout(() => loadLogs(1), 0);
        }} />
      )}
    </div>
  );
}

const TabBtn = ({ active, onClick, children, testId }) => (
  <button
    onClick={onClick}
    data-testid={testId}
    className={active ? "btn btn-primary" : "btn btn-secondary"}
    style={{ borderRadius: 999 }}
  >
    {children}
  </button>
);

const Kpi = ({ label, num, tone, testId }) => {
  const t = STATUS_TONES[tone === "success" ? "completed" : tone === "warn" ? "pending" : tone === "danger" ? "failed" : "refunded"] || {};
  return (
    <div className="kpi" data-testid={testId} style={{ padding: 16 }}>
      <div className="kpi-num" style={{ color: t.fg || undefined }}>{num}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
};

const StatusPill = ({ status }) => {
  const t = STATUS_TONES[status] || { bg: "#e5e7eb", fg: "#374151" };
  return (
    <span style={{
      padding: "3px 10px", borderRadius: 999, background: t.bg, color: t.fg,
      fontSize: 12, fontWeight: 600, textTransform: "capitalize",
    }} data-testid={`status-${status}`}>{status || "—"}</span>
  );
};

const REFUND_TONES = {
  successful: { bg: "#dcfce7", fg: "#166534" },
  initiated: { bg: "#fef3c7", fg: "#92400e" },
  failed: { bg: "#fee2e2", fg: "#991b1b" },
  not_applicable: { bg: "#e5e7eb", fg: "#4b5563" },
};

const RefundPill = ({ status }) => {
  const t = REFUND_TONES[status] || { bg: "#e5e7eb", fg: "#374151" };
  return (
    <span style={{
      padding: "3px 10px", borderRadius: 999, background: t.bg, color: t.fg,
      fontSize: 12, fontWeight: 600, textTransform: "capitalize",
    }} data-testid={`refund-status-${status}`}>{(status || "—").replace(/_/g, " ")}</span>
  );
};

const Pagination = ({ page, total, limit, onGo }) => {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 8, marginTop: 16 }}>
      <button className="btn btn-secondary" disabled={page <= 1} onClick={() => onGo(page - 1)} data-testid="page-prev">← Prev</button>
      <span className="text-muted">Page {page} of {pages} · {total} rows</span>
      <button className="btn btn-secondary" disabled={page >= pages} onClick={() => onGo(page + 1)} data-testid="page-next">Next →</button>
    </div>
  );
};

const PaymentDrawer = ({ p, onClose, onJumpToLogs }) => (
  <div style={{
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100,
    display: "flex", justifyContent: "flex-end",
  }} onClick={onClose} data-testid="payment-drawer">
    <div onClick={(e) => e.stopPropagation()} style={{
      width: 520, background: "#0F0F1B", color: "#F0EEFF", padding: 28,
      overflow: "auto", boxShadow: "-6px 0 24px rgba(0,0,0,0.4)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>Payment</h2>
        <button className="btn btn-link" onClick={onClose} data-testid="drawer-close">✕</button>
      </div>
      <Row label="Gateway" value={`${p.gateway}${p.environment ? ` (${p.environment})` : ""}`} />
      <Row label="Status" value={<StatusPill status={p.status} />} />
      <Row label="Amount" value={fmtINR(p.amount)} />
      <Row label="Transaction ID" value={<code style={{ fontSize: 12 }}>{p.txnid || "—"}</code>} />
      <Row label="Easepay ID" value={<code style={{ fontSize: 12 }}>{p.easepayid || "—"}</code>} />
      <Row label="Access Key" value={<code style={{ fontSize: 11 }}>{(p.access_key || "").slice(0, 24) || "—"}…</code>} />
      <Row label="Created" value={fmtDate(p.created_at)} />
      <Row label="Verified" value={fmtDate(p.verified_at)} />
      <Row label="Booking Refs" value={(p.booking_refs || []).map((r) => (
        <code key={r} style={{ marginRight: 6, fontSize: 12 }}>{r}</code>
      ))} />
      {p.failure_reason && (
        <Row label="Failure Reason" value={<span style={{ color: "#f87171" }}>{p.failure_reason}</span>} />
      )}
      {p.gateway_response_summary && (
        <div style={{ marginTop: 16 }}>
          <div className="text-muted" style={{ fontSize: 12, marginBottom: 6 }}>Gateway Response Summary</div>
          <pre style={{ fontSize: 11, background: "rgba(255,255,255,0.04)", padding: 12, borderRadius: 6 }}>
{JSON.stringify(p.gateway_response_summary, null, 2)}
          </pre>
        </div>
      )}
      {p.payment_url && (
        <div style={{ marginTop: 16 }}>
          <a href={p.payment_url} target="_blank" rel="noreferrer" className="btn btn-secondary" data-testid="drawer-open-url">Open hosted checkout URL ↗</a>
        </div>
      )}
      <div style={{ marginTop: 24 }}>
        <button className="btn btn-primary" onClick={onJumpToLogs} data-testid="drawer-view-logs">View raw logs for this txn →</button>
      </div>
    </div>
  </div>
);

const Row = ({ label, value }) => (
  <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
    <span style={{ color: "rgba(240,238,255,0.6)", fontSize: 13 }}>{label}</span>
    <span style={{ maxWidth: "60%", textAlign: "right" }}>{value || "—"}</span>
  </div>
);
