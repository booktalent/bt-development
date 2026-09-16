import React, { useEffect, useState } from "react";
import api, { formatApiError as fmt } from "../lib/api";
import { useToast } from "../lib/toast";

/**
 * Iter 85 — Reusable payment/payout widgets (Sec 32-44, 55).
 *
 * Three components exported:
 *   • PaymentTimeline   — a booking's milestone list with pay/mark-paid
 *   • PayoutConsole     — admin console for manual UTR-based payouts
 *   • AtRiskDashboard   — auto-flagged bookings needing attention
 */

const money = (n) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));


// ─── Payment Timeline ─────────────────────────────────────────────
export function PaymentTimeline({ bookingId, canEdit = false }) {
  const toast = useToast();
  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [markingIdx, setMarkingIdx] = useState(null);
  const [markForm, setMarkForm] = useState({ amount: 0, method: "upi", reference: "", paid_on: new Date().toISOString().slice(0, 10) });

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(`/bookings/${bookingId}/schedule`);
      setSchedule(r.data);
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [bookingId]); // eslint-disable-line

  const markPaid = async (idx) => {
    try {
      await api.post(`/bookings/${bookingId}/schedule/mark-paid`, {
        milestone_index: idx,
        amount_received: parseFloat(markForm.amount) || 0,
        method: markForm.method,
        reference: markForm.reference,
        paid_on: markForm.paid_on,
      });
      toast("Marked paid", "success");
      setMarkingIdx(null);
      await load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  if (loading) return <div className="pad-16" data-testid="pt-loading">Loading timeline…</div>;
  if (!schedule) return <div className="pad-16">No schedule</div>;

  const received = schedule.amount_received || 0;
  const total = schedule.total || 0;
  const pct = total > 0 ? Math.round(received / total * 100) : 0;

  return (
    <div className="card card-pad" data-testid="payment-timeline">
      <div className="flex-between mb-8">
        <h3 className="font-serif fw-700">Payment Timeline</h3>
        <div className="text-muted fs-13">₹{money(received)} / ₹{money(total)} <span className="text-gold">({pct}%)</span></div>
      </div>
      <div className="progress-bar mb-16" style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg, #D4AF37, #F1D17A)" }} />
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {(schedule.milestones || []).map((m, i) => (
          <li key={i} className="mb-12" data-testid={`milestone-${i}`}>
            <div className="flex-between">
              <div>
                <div className="fw-700 fs-14">{m.label} · <span className="text-gold">₹{money(m.amount)}</span></div>
                <div className="text-muted fs-12">
                  Due: {m.due_date || "at booking"} ·
                  <span className={`ml-8 pill pill-${statusTint(m.status)}`}>{m.status}</span>
                </div>
              </div>
              {canEdit && m.status !== "paid" && (
                <button className="btn btn-ghost btn-sm" onClick={() => {
                  setMarkingIdx(i);
                  setMarkForm({ ...markForm, amount: m.amount });
                }} data-testid={`mark-paid-btn-${i}`}>Mark Paid</button>
              )}
            </div>
            {markingIdx === i && (
              <div className="card card-pad mt-8" style={{ background: "rgba(212,175,55,0.06)" }}>
                <div className="grid grid-2 gap-8">
                  <input className="field-input" type="number" placeholder="Amount received"
                    value={markForm.amount} onChange={(e) => setMarkForm({ ...markForm, amount: e.target.value })}
                    data-testid={`mark-paid-amount-${i}`} />
                  <select className="field-input" value={markForm.method}
                    onChange={(e) => setMarkForm({ ...markForm, method: e.target.value })}>
                    <option value="upi">UPI</option><option value="neft">NEFT</option>
                    <option value="imps">IMPS</option><option value="cash">Cash</option>
                    <option value="cheque">Cheque</option><option value="other">Other</option>
                  </select>
                  <input className="field-input" placeholder="Reference / UTR"
                    value={markForm.reference} onChange={(e) => setMarkForm({ ...markForm, reference: e.target.value })}
                    data-testid={`mark-paid-ref-${i}`} />
                  <input className="field-input" type="date" value={markForm.paid_on}
                    onChange={(e) => setMarkForm({ ...markForm, paid_on: e.target.value })} />
                </div>
                <div className="flex gap-8 mt-8">
                  <button className="btn btn-gold btn-sm" onClick={() => markPaid(i)}
                    data-testid={`mark-paid-confirm-${i}`}>Confirm Paid</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setMarkingIdx(null)}>Cancel</button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}


function statusTint(status) {
  if (status === "paid") return "green";
  if (status === "overdue") return "red";
  return "gold";
}


// ─── Payout Console (Admin) ───────────────────────────────────────
export function PayoutConsole() {
  const toast = useToast();
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [payoutFor, setPayoutFor] = useState(null);
  const [form, setForm] = useState({ amount: 0, method: "neft", utr: "", bank_reference: "", notes: "", paid_on: new Date().toISOString().slice(0, 10) });

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/admin/payouts/pending");
      setPending(r.data.items || []);
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const recordPayout = async () => {
    if (!form.utr || form.utr.length < 3) return toast("UTR is required", "error");
    if (!(form.amount > 0)) return toast("Amount must be > 0", "error");
    try {
      await api.post(`/bookings/${payoutFor.id}/payout/manual`, form);
      toast("Payout recorded", "success");
      setPayoutFor(null);
      setForm({ amount: 0, method: "neft", utr: "", bank_reference: "", notes: "", paid_on: new Date().toISOString().slice(0, 10) });
      await load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  return (
    <div className="pad-24" data-testid="payout-console">
      <h1 className="font-serif fs-24 fw-700 mb-16">Artist Payout Console</h1>
      <p className="text-muted fs-13 mb-16">
        Manual payouts (current phase). Bookings below have not yet been settled to the artist.
        Automated Easebuzz Payouts are OFF by default — enable in Platform Settings.
      </p>
      {loading ? "Loading…" : (
        <table className="table w-full" data-testid="pending-payouts-table">
          <thead>
            <tr><th>Ref</th><th>Artist</th><th>Event</th><th>Payable</th><th></th></tr>
          </thead>
          <tbody>
            {pending.map((b) => (
              <tr key={b.id} data-testid={`payout-row-${b.id}`}>
                <td><code className="text-gold">{b.ref}</code></td>
                <td>{b.artist_id}</td>
                <td>{b.event_date || "—"}</td>
                <td>₹{money((b.pricing || {}).artist_payable || (b.pricing || {}).artist_fee || 0)}</td>
                <td>
                  <button className="btn btn-gold btn-sm" onClick={() => {
                    setPayoutFor(b);
                    setForm({ ...form, amount: (b.pricing || {}).artist_payable || (b.pricing || {}).artist_fee || 0 });
                  }} data-testid={`start-payout-${b.id}`}>Record Payout</button>
                </td>
              </tr>
            ))}
            {pending.length === 0 && (
              <tr><td colSpan="5" className="text-muted text-center pad-16">All payouts cleared 🎉</td></tr>
            )}
          </tbody>
        </table>
      )}

      {payoutFor && (
        <div className="modal-backdrop" onClick={() => setPayoutFor(null)}>
          <div className="modal card card-pad" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <h3 className="font-serif fw-700 mb-8">Record Payout · {payoutFor.ref}</h3>
            <div className="grid grid-2 gap-8">
              <div>
                <label className="field-label">Amount ₹</label>
                <input className="field-input" type="number" value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  data-testid="payout-amount" />
              </div>
              <div>
                <label className="field-label">Method</label>
                <select className="field-input" value={form.method}
                  onChange={(e) => setForm({ ...form, method: e.target.value })}
                  data-testid="payout-method">
                  <option value="neft">NEFT</option><option value="imps">IMPS</option>
                  <option value="upi">UPI</option><option value="cash">Cash</option>
                  <option value="cheque">Cheque</option><option value="other">Other</option>
                </select>
              </div>
              <div className="col-span-2">
                <label className="field-label">UTR / Transaction ID *</label>
                <input className="field-input" value={form.utr}
                  onChange={(e) => setForm({ ...form, utr: e.target.value })}
                  data-testid="payout-utr" />
              </div>
              <div>
                <label className="field-label">Bank Reference</label>
                <input className="field-input" value={form.bank_reference}
                  onChange={(e) => setForm({ ...form, bank_reference: e.target.value })} />
              </div>
              <div>
                <label className="field-label">Paid On</label>
                <input className="field-input" type="date" value={form.paid_on}
                  onChange={(e) => setForm({ ...form, paid_on: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="field-label">Notes</label>
                <input className="field-input" value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-8 mt-16">
              <button className="btn btn-gold" onClick={recordPayout} data-testid="payout-confirm-btn">Save Payout</button>
              <button className="btn btn-ghost" onClick={() => setPayoutFor(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ─── At-Risk Dashboard ────────────────────────────────────────────
export function AtRiskDashboard() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/admin/at-risk-bookings");
        setData(r.data);
      } catch (e) { toast(fmt(e), "error"); }
      setLoading(false);
    })();
  }, []); // eslint-disable-line

  if (loading) return <div className="pad-24">Scanning…</div>;
  if (!data) return null;

  const buckets = [
    { key: "event_soon_unpaid", title: "⚠ Event in ≤ 3 days · Payment pending",
      rows: data.event_soon_unpaid, cols: [["ref", "Ref"], ["event_date", "Event"], ["customer_name", "Customer"]] },
    { key: "schedules_overdue", title: "🕐 Customer Payment Overdue",
      rows: data.schedules_overdue, cols: [["booking_id", "Booking"], ["total", "Total"], ["amount_received", "Received"]] },
    { key: "payout_pending", title: "💰 Artist Payout Pending (Completed)",
      rows: data.payout_pending, cols: [["ref", "Ref"], ["event_date", "Event"], ["artist_id", "Artist"]] },
    { key: "leads_unassigned", title: "👤 Leads Unassigned (> 24h)",
      rows: data.leads_unassigned, cols: [["customer_name", "Customer"], ["created_at", "Created"], ["event_type", "Event"]] },
    { key: "kyc_stuck", title: "🪪 KYC Stuck (> 7 days)",
      rows: data.kyc_stuck, cols: [["stage_name", "Artist"], ["kyc_status", "Status"], ["kyc_updated_at", "Since"]] },
  ];

  return (
    <div className="pad-24" data-testid="at-risk-dashboard">
      <div className="flex-between mb-16">
        <h1 className="font-serif fs-24 fw-700">At-Risk Bookings</h1>
        <span className="pill pill-red" data-testid="at-risk-total">{data.total} items need attention</span>
      </div>
      {buckets.map((b) => (
        <div key={b.key} className="card card-pad mb-16" data-testid={`bucket-${b.key}`}>
          <h3 className="fw-700 mb-8">{b.title} <span className="text-muted fs-13">({(b.rows || []).length})</span></h3>
          {(b.rows || []).length === 0 ? (
            <div className="text-muted fs-13">All clear</div>
          ) : (
            <table className="table w-full fs-13">
              <thead><tr>{b.cols.map(([k, l]) => <th key={k}>{l}</th>)}</tr></thead>
              <tbody>
                {b.rows.slice(0, 10).map((row, i) => (
                  <tr key={i}>
                    {b.cols.map(([k]) => <td key={k}>{String(row[k] || "—").slice(0, 40)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}
