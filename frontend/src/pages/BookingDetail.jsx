/**
 * BookingDetail — canonical booking detail view (Iter 86, Sec 32/37/40).
 *
 * Anyone with visibility into the booking (customer, artist, assigned
 * manager, agency, admin) can open this page. It shows the header +
 * embedded PaymentTimeline widget with inline "Mark Paid" gated to
 * admin/manager only (canEdit prop on the widget).
 */
import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import Nav from "../components/Nav";
import api, { formatApiError as fmt } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { PaymentTimeline } from "../components/PaymentPayoutWidgets";

const money = (n) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));

const STATUS_TINT = {
  confirmed: "green", completed: "green", reviewed: "green",
  pending_artist: "gold", pending_payment: "gold", started: "gold",
  rejected: "red", cancelled: "red", auto_expired: "red",
};

export default function BookingDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const [booking, setBooking] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [loading, setLoading] = useState(true);

  const canEditPayments = ["admin", "manager"].includes(user?.role);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(`/bookings/${id}`);
      // Different endpoints return {booking:{}} or a raw doc.
      setBooking(r.data.booking || r.data);
      try {
        const p = await api.get(`/bookings/${id}/payouts`);
        setPayouts(p.data.items || []);
      } catch { /* payouts list is optional */ }
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line

  if (loading) {
    return (
      <div>
        <Nav />
        <div className="pad-24" data-testid="bd-loading">Loading booking…</div>
      </div>
    );
  }
  if (!booking) {
    return (
      <div>
        <Nav />
        <div className="pad-24" data-testid="bd-not-found">
          Booking not found or you don't have access.
          <div className="mt-16">
            <Link to="/" className="btn btn-ghost btn-sm">Home</Link>
          </div>
        </div>
      </div>
    );
  }

  const pricing = booking.pricing || {};
  const tint = STATUS_TINT[booking.status] || "gold";

  return (
    <div>
      <Nav />
      <div className="pad-24" data-testid="booking-detail" style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex-between mb-16" style={{ flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="text-muted fs-12" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>
              Booking Reference
            </div>
            <h1 className="font-serif fs-28 fw-700 text-gold" data-testid="bd-ref">
              {booking.ref || booking.id}
            </h1>
            <div className="text-muted fs-13 mt-4">
              {booking.event_type} · {booking.event_date} {booking.event_time && `· ${booking.event_time}`}
            </div>
          </div>
          <div className="flex gap-8" style={{ alignItems: "center" }}>
            <span className={`pill pill-${tint}`} data-testid="bd-status">{booking.status}</span>
            {booking.artist_payout_status && (
              <span
                className={`pill pill-${booking.artist_payout_status === "paid" ? "green" : "gold"}`}
                data-testid="bd-payout-status"
              >
                Payout: {booking.artist_payout_status}
              </span>
            )}
          </div>
        </div>

        {/* ── Summary card ───────────────────────────────────────── */}
        <div className="grid grid-2 gap-16 mb-16">
          <div className="card card-pad" data-testid="bd-summary-card">
            <h3 className="fw-700 mb-8">Event</h3>
            <div className="fs-13 text-muted">Venue</div>
            <div className="mb-8">{booking.venue || "—"}, {booking.city || ""}</div>
            <div className="fs-13 text-muted">Customer</div>
            <div className="mb-8">{booking.customer_name || "—"}</div>
            {booking.customer_email && (
              <>
                <div className="fs-13 text-muted">Email</div>
                <div className="mb-8">{booking.customer_email}</div>
              </>
            )}
            {booking.special_instructions && (
              <>
                <div className="fs-13 text-muted mt-8">Special Instructions</div>
                <div className="fs-13" style={{ whiteSpace: "pre-wrap" }}>
                  {booking.special_instructions}
                </div>
              </>
            )}
          </div>
          <div className="card card-pad" data-testid="bd-pricing-card">
            <h3 className="fw-700 mb-8">Pricing</h3>
            <div className="flex-between fs-13"><span>Package Fee</span><span>₹{money(pricing.package_fee || pricing.base || 0)}</span></div>
            <div className="flex-between fs-13"><span>Add-ons</span><span>₹{money(pricing.addons_total || 0)}</span></div>
            <div className="flex-between fs-13"><span>Platform Fee</span><span>₹{money(pricing.platform_fee || 0)}</span></div>
            <div className="flex-between fs-13"><span>GST</span><span>₹{money(pricing.gst || 0)}</span></div>
            {pricing.coupon_discount ? (
              <div className="flex-between fs-13 text-green">
                <span>Coupon Discount</span><span>−₹{money(pricing.coupon_discount)}</span>
              </div>
            ) : null}
            <div className="flex-between mt-8 fw-700 fs-16" style={{ borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
              <span>Total</span>
              <span className="text-gold" data-testid="bd-total">₹{money(pricing.total)}</span>
            </div>
            {pricing.artist_payable ? (
              <div className="flex-between mt-4 fs-13 text-muted">
                <span>Artist Payable</span><span>₹{money(pricing.artist_payable)}</span>
              </div>
            ) : null}
          </div>
        </div>

        {/* ── Booking Timeline (full lifecycle) ─────────────────── */}
        <BookingTimeline booking={booking} payouts={payouts} />

        {/* ── Mutual Refund Panel — customer or artist can request ── */}
        {(user?.role === "customer" || user?.role === "artist") && (
          <MutualRefundPanel booking={booking} user={user} />
        )}

        {/* ── Payment Timeline ──────────────────────────────────── */}
        <div className="mb-16">
          <PaymentTimeline bookingId={id} canEdit={canEditPayments} />
        </div>

        {/* ── Payout Ledger (admin/manager/agency/artist only) ──── */}
        {payouts.length > 0 && (
          <div className="card card-pad mb-16" data-testid="bd-payout-ledger">
            <h3 className="fw-700 mb-8">Payout Ledger</h3>
            <table className="table w-full fs-13">
              <thead>
                <tr><th>Date</th><th>Amount</th><th>Method</th><th>UTR</th><th>By</th></tr>
              </thead>
              <tbody>
                {payouts.map((p) => (
                  <tr key={p.id} data-testid={`bd-payout-${p.id}`}>
                    <td>{(p.paid_on || p.created_at || "").slice(0, 10)}</td>
                    <td className="text-gold">₹{money(p.amount)}</td>
                    <td>{(p.method || "").toUpperCase()}</td>
                    <td className="font-mono fs-11">{p.utr}</td>
                    <td className="text-muted fs-11">{p.paid_by_email || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex gap-8">
          <Link to={user?.role === "admin" ? "/admin" : user?.role === "manager" ? "/manager" : "/customer"}
                className="btn btn-ghost btn-sm" data-testid="bd-back">← Back to dashboard</Link>
        </div>
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// BookingTimeline — visual audit trail of every important stage.
// Derives its stages from the booking document + payout ledger so it works
// without a dedicated status_history collection.
// ────────────────────────────────────────────────────────────────────────
function BookingTimeline({ booking, payouts }) {
  const [realEvents, setRealEvents] = useState([]);
  useEffect(() => {
    if (!booking?.id) return;
    api.get(`/bookings/${booking.id}/timeline`)
      .then((r) => setRealEvents(r.data?.items || []))
      .catch(() => setRealEvents([]));
  }, [booking?.id]);
  if (!booking) return null;
  const p = booking.pricing || {};
  const total = Number(p.total || 0);
  const paid = Number(booking.paid_amount || 0);
  const totalPayout = (payouts || []).reduce((s, x) => s + Number(x.amount || 0), 0);
  const evtDate = booking.event_date || "";
  const today = new Date().toISOString().slice(0, 10);
  const evtInFuture = evtDate && evtDate >= today;

  const stages = [
    {
      key: "lead_created",
      label: "Lead / Booking Created",
      at: booking.created_at,
      done: !!booking.created_at,
    },
    {
      key: "manager_assigned",
      label: "Manager Assigned",
      at: booking.manager_assigned_at,
      done: !!booking.assigned_manager_id,
      hint: booking.assigned_manager_id ? "Assigned" : "Auto-assigns when a lead qualifies",
    },
    {
      key: "artist_selected",
      label: "Artist Selected",
      at: booking.created_at,
      done: !!booking.artist_id,
    },
    {
      key: "booking_confirmed",
      label: "Booking Confirmed",
      at: booking.confirmed_at,
      done: ["confirmed", "started", "completed", "reviewed"].includes(booking.status),
      hint: booking.status === "pending_artist" ? "Awaiting artist confirmation" : "",
    },
    {
      key: "payment_received",
      label: paid > 0 ? `Payment Received · ₹${money(paid)} of ₹${money(total)}` : "Payment Received",
      at: booking.first_payment_at,
      done: paid > 0,
    },
    {
      key: "artist_payout",
      label: totalPayout > 0
        ? `Artist Payout · ₹${money(totalPayout)}`
        : "Artist Payout",
      at: (payouts && payouts[0]?.paid_on) || null,
      done: totalPayout > 0,
      hint: totalPayout === 0 && paid > 0 ? "Pending — mark paid from payout ledger" : "",
    },
    {
      key: "remaining_payment",
      label: total > paid
        ? `Remaining Payment · ₹${money(total - paid)} due`
        : "Remaining Payment · settled",
      at: booking.remaining_paid_at,
      done: total > 0 && paid >= total,
    },
    {
      key: "event",
      label: `Event${evtDate ? ` · ${evtDate}` : ""}`,
      at: evtDate,
      done: evtDate && !evtInFuture,
      hint: evtInFuture ? "Upcoming" : "",
    },
    {
      key: "final_payment",
      label: "Final Payment / Settlement",
      at: booking.finalized_at,
      done: booking.status === "completed" || booking.status === "reviewed",
    },
    {
      key: "completed",
      label: "Completed",
      at: booking.completed_at,
      done: booking.status === "completed" || booking.status === "reviewed",
    },
  ];

  // Overlay real timestamps from booking_events when present so displayed
  // dates reflect actual DB events rather than derived ones.
  const evByKind = {};
  (realEvents || []).forEach((ev) => {
    // Normalise a couple of aliases from server-side event kinds.
    const map = {
      created: "lead_created",
      manager_assigned: "manager_assigned",
      artist_confirmed: "booking_confirmed",
      payment_received: "payment_received",
      artist_payout: "artist_payout",
      event_completed: "event",
      completed: "completed",
    };
    const k = map[ev.kind] || ev.kind;
    if (!evByKind[k]) evByKind[k] = ev;
  });
  stages.forEach((s) => {
    const ev = evByKind[s.key];
    if (ev && ev.at) {
      s.at = ev.at;
      s.done = true;
    }
  });

  const currentIndex = (() => {
    for (let i = stages.length - 1; i >= 0; i--) {
      if (stages[i].done) return i + 1;
    }
    return 0;
  })();

  return (
    <div className="card card-pad mb-16" data-testid="bd-timeline">
      <div className="flex-between mb-12">
        <h3 className="fw-700">Booking Timeline</h3>
        <span className="text-muted fs-11">{currentIndex} of {stages.length} stages</span>
      </div>
      <div style={{ position: "relative", paddingLeft: 22 }}>
        <div style={{
          position: "absolute", top: 6, bottom: 6, left: 10, width: 2,
          background: "rgba(255,255,255,0.08)",
        }} />
        {stages.map((s, i) => {
          const isCurrent = i === currentIndex - 1;
          return (
            <div
              key={s.key}
              data-testid={`bd-timeline-${s.key}`}
              style={{ position: "relative", marginBottom: 14, minHeight: 22 }}
            >
              <div style={{
                position: "absolute", left: -18, top: 3, width: 18, height: 18,
                borderRadius: "50%",
                background: s.done ? "#6ee7a8" : isCurrent ? "#D4AF37" : "rgba(255,255,255,0.10)",
                color: (s.done || isCurrent) ? "#0F0F1B" : "rgba(255,255,255,0.4)",
                fontSize: 10, fontWeight: 700,
                display: "flex", alignItems: "center", justifyContent: "center",
                border: isCurrent ? "3px solid rgba(212,175,55,0.35)" : "2px solid rgba(255,255,255,0.08)",
              }}>{s.done ? "✓" : ""}</div>
              <div style={{
                fontSize: 13, fontWeight: isCurrent || s.done ? 700 : 500,
                color: s.done ? "rgba(240,238,255,0.9)"
                        : isCurrent ? "#D4AF37"
                        : "rgba(240,238,255,0.4)",
              }}>{s.label}</div>
              {s.at && (
                <div className="text-muted fs-11" style={{ marginTop: 2 }}>
                  {String(s.at).slice(0, 10)}
                </div>
              )}
              {s.hint && (
                <div className="text-muted fs-11" style={{ marginTop: 2, fontStyle: "italic" }}>
                  {s.hint}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// MutualRefundPanel — customer or artist can raise a refund request; the
// other party accepts/rejects. On accept, the booking is flagged and (if
// enabled) the payout provider dispatches the actual refund.
// ────────────────────────────────────────────────────────────────────────
function MutualRefundPanel({ booking, user }) {
  const toast = useToast();
  const [req, setReq] = useState(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const paid = Number(booking.paid_amount || 0);
  const reload = () => api.get(`/bookings/${booking.id}/refund-status`)
    .then((r) => setReq(r.data?.request || null))
    .catch(() => setReq(null));
  useEffect(() => { reload(); }, [booking.id]);

  const submit = async () => {
    const amt = amount ? parseFloat(amount) : paid;
    if (!amt || amt <= 0) { toast("Enter a positive refund amount", "error"); return; }
    setBusy(true);
    try {
      await api.post(`/bookings/${booking.id}/refund-request`, { amount: amt, reason });
      toast("Refund request sent — awaiting counter party's acknowledgement", "success");
      setAmount(""); setReason("");
      reload();
    } catch (e) { toast(fmt(e), "error"); }
    setBusy(false);
  };

  const respond = async (accept) => {
    setBusy(true);
    try {
      await api.post(`/bookings/${booking.id}/refund-${accept ? "accept" : "reject"}`);
      toast(accept ? "Refund accepted — payout in progress" : "Refund request rejected", "success");
      reload();
    } catch (e) { toast(fmt(e), "error"); }
    setBusy(false);
  };

  const iAmCounter = req && req.counter_id === user?.id && req.status === "pending_counter_ack";
  const iAmRequester = req && req.requested_by_id === user?.id;

  return (
    <div className="card card-pad mb-16" data-testid="bd-refund-panel">
      <h3 className="fw-700 mb-8">Mutual Refund</h3>

      {req && req.status === "pending_counter_ack" && (
        <div style={{
          background: "rgba(212,175,55,0.08)", border: "1px solid rgba(212,175,55,0.3)",
          borderRadius: 8, padding: 12, marginBottom: 12,
        }} data-testid="bd-refund-pending">
          <div className="fw-700 fs-14">₹{money(req.amount)} refund awaiting {req.counter_role} acknowledgement</div>
          {req.reason && <div className="text-muted fs-12 mt-4">Reason: {req.reason}</div>}
          {iAmCounter && (
            <div className="flex gap-8 mt-8">
              <button className="btn btn-gold btn-sm" onClick={() => respond(true)} disabled={busy} data-testid="bd-refund-accept">Accept</button>
              <button className="btn btn-ghost btn-sm" onClick={() => respond(false)} disabled={busy} data-testid="bd-refund-reject">Reject</button>
            </div>
          )}
          {iAmRequester && <div className="text-muted fs-12 mt-8">Waiting on the other party…</div>}
        </div>
      )}

      {req && req.status === "accepted" && (
        <div className="text-good fs-13 mb-8" data-testid="bd-refund-accepted">
          ✅ Refund of ₹{money(req.amount)} accepted on {String(req.counter_accepted_at || "").slice(0, 10)}.
        </div>
      )}

      {req && req.status === "rejected" && (
        <div className="fs-13 mb-8" style={{ color: "#e57373" }} data-testid="bd-refund-rejected">
          Refund was rejected. You can raise a new request if circumstances change.
        </div>
      )}

      {(!req || req.status !== "pending_counter_ack") && paid > 0 && (
        <div style={{ display: "grid", gap: 8 }}>
          <div className="text-muted fs-13">
            If both parties agree, either of you can start a mutual refund. The counter party must accept before it's processed.
          </div>
          <div className="grid grid-2 gap-8">
            <input
              type="number"
              className="input"
              placeholder={`Amount (max ₹${money(paid)})`}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              data-testid="bd-refund-amount"
            />
            <input
              className="input"
              placeholder="Reason (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              data-testid="bd-refund-reason"
            />
          </div>
          <div>
            <button className="btn btn-gold btn-sm" onClick={submit} disabled={busy} data-testid="bd-refund-request">
              {busy ? "Sending…" : "Request Refund"}
            </button>
          </div>
        </div>
      )}

      {(!req || req.status !== "pending_counter_ack") && paid === 0 && (
        <div className="text-muted fs-13">
          No payment has been received against this booking yet — refunds unavailable.
        </div>
      )}
    </div>
  );
}

