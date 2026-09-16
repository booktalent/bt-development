/**
 * PaymentReturn — Iter 62 (v2)
 *
 * Landing page after Easebuzz redirects the browser back from the hosted
 * checkout. Polls /api/payments/easebuzz/status/:txnid until the booking is
 * flipped to `token_paid`, then renders the full booking-confirmed
 * experience:
 *   - Celebration + booking ref
 *   - Booking summary card (artist, package, date, venue, fees)
 *   - Share Event Recap · Download Invoice · Dashboard buttons
 *   - "Complete your event" suggestion strip (secondary artists)
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Nav from "../components/Nav";
import api, { fmtINRFull } from "../lib/api";

const MAX_POLL_MS = 30000;
const POLL_INTERVAL_MS = 1500;

export default function PaymentReturn() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const txnid = params.get("txnid") || "";
  const initialStatus = params.get("status") || "pending";
  const [pay, setPay] = useState(null);
  const [waited, setWaited] = useState(0);
  const [suggested, setSuggested] = useState([]);
  const [artistDetails, setArtistDetails] = useState({}); // artist_id -> {stage_name, category, city, profile_image}
  const timer = useRef(null);

  // ── Poll payment status until it's completed or failed ──────────────────
  useEffect(() => {
    if (!txnid) return;
    let cancelled = false;
    const started = Date.now();

    const poll = async () => {
      try {
        const r = await api.get(`/payments/easebuzz/status/${txnid}`);
        if (cancelled) return;
        setPay(r.data);
        if (r.data.status === "completed" || r.data.status === "failed") return;
      } catch { /* keep polling — the payment doc may not exist yet */ }
      const elapsed = Date.now() - started;
      setWaited(elapsed);
      if (!cancelled && elapsed < MAX_POLL_MS) {
        timer.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [txnid]);

  // ── Once completed, hydrate artist details + suggested artists ──────────
  useEffect(() => {
    if (pay?.status !== "completed" || !pay?.bookings?.length) return;
    const primary = pay.bookings[0];
    const artistIds = [...new Set(pay.bookings.map((b) => b.artist_id).filter(Boolean))];
    // Fetch every artist's profile summary (stage name, category, image)
    Promise.all(artistIds.map((aid) =>
      api.get(`/artists/${aid}`).then((r) => ({ id: aid, ...r.data.profile, packages: r.data.packages })).catch(() => null)
    )).then((rows) => {
      const map = {};
      rows.filter(Boolean).forEach((row) => { map[row.id] = row; });
      setArtistDetails(map);
    });
    // Fetch the "complete your event" suggestions
    if (primary?.artist_id) {
      const p = new URLSearchParams();
      if (primary.event_date) p.set("date_str", primary.event_date);
      p.set("limit", "6");
      api.get(`/artists/${primary.artist_id}/suggested?${p}`)
        .then((r) => setSuggested(r.data?.suggested || []))
        .catch(() => setSuggested([]));
    }
  }, [pay]);

  const status = pay?.status || initialStatus;
  const isDone = status === "completed";
  const isFailed = status === "failed";
  const isPending = !isDone && !isFailed;
  const bookings = pay?.bookings || [];
  const primary = bookings[0];
  const primaryArtist = primary ? artistDetails[primary.artist_id] : null;
  const isBatch = pay?.batch || bookings.length > 1;
  const eventId = pay?.event_id || primary?.event_id;

  const downloadInvoice = async () => {
    if (!primary) return;
    try {
      const r = await fetch(`${api.defaults.baseURL}/bookings/${primary.id}/invoice`, { credentials: "include" });
      if (!r.ok) throw new Error("Invoice not ready yet");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = window.URL.createObjectURL(blob);
      a.download = `invoice_${primary.ref}.pdf`;
      a.click();
    } catch (e) {
      // eslint-disable-next-line no-alert
      alert("Invoice will be available shortly — the artist has to accept first.");
    }
  };

  const shareParams = useMemo(() => {
    if (!primary) return "";
    return new URLSearchParams({
      event_id: eventId || "",
      date: primary.event_date || "",
    }).toString();
  }, [primary, eventId]);

  if (!txnid) {
    return (
      <div><Nav />
        <div className="container" style={{ paddingTop: 60, textAlign: "center" }}>
          <h1>Missing Transaction</h1>
          <p>No transaction reference provided. If you just paid, check your bookings.</p>
          <Link to="/customer" className="btn btn-primary" data-testid="return-goto-dashboard">Go to My Bookings</Link>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="payment-return-page">
      <Nav />
      <div className="container" style={{ paddingTop: 40, paddingBottom: 80 }}>
        {isPending && (
          <div style={{ textAlign: "center", maxWidth: 520, margin: "0 auto" }}>
            <div className="spinner" style={{ margin: "0 auto 24px" }} />
            <h1 data-testid="return-pending">Verifying your payment…</h1>
            <p className="text-muted">We're confirming with the payment gateway. This normally takes a few seconds.</p>
            <p className="text-muted" style={{ fontSize: 12 }}>Transaction: <code>{txnid}</code></p>
            {waited > 10000 && (
              <p style={{ marginTop: 20, color: "#92400e" }}>
                Still checking… you can safely close this page and check "My Bookings" in a minute.
              </p>
            )}
          </div>
        )}

        {isDone && (
          <div className="card card-pad text-center" data-testid="return-success" style={{ maxWidth: 720, margin: "0 auto" }}>
            <div style={{ fontSize: 72, marginBottom: 12 }}>✅</div>
            <h2 className="font-serif" style={{ fontSize: 40, fontWeight: 700, marginBottom: 8 }}>Booking Confirmed!</h2>
            <p className="text-muted mb-20">
              {isBatch ? (
                <>Your event with <strong>{bookings.length} artists</strong> is officially booked. All artists have been notified.</>
              ) : (
                <>Your booking with <strong>{primaryArtist?.stage_name || "your artist"}</strong> is officially confirmed. The artist has 24 hours to accept.</>
              )}
            </p>
            <div className="pill pill-gold mb-24" style={{ fontSize: 14, padding: "8px 16px" }} data-testid="return-booking-ref">
              {isBatch ? `Event Refs: ${bookings.map((b) => b.ref).join(" · ")}` : `Booking Ref: ${primary?.ref}`}
            </div>

            {/* Summary card */}
            <div className="card card-pad mb-20" style={{ textAlign: "left", maxWidth: 520, margin: "0 auto 20px" }}>
              <div className="flex justify-between mb-8"><span className="text-muted">Transaction ID</span><code style={{ fontSize: 12 }}>{txnid}</code></div>
              {pay?.easepayid && (
                <div className="flex justify-between mb-8"><span className="text-muted">Gateway Ref</span><code style={{ fontSize: 12 }}>{pay.easepayid}</code></div>
              )}
              <div className="flex justify-between mb-8"><span className="text-muted">Amount Paid</span><span className="text-gold fw-700">{fmtINRFull(pay?.amount || 0)}</span></div>
              {primary?.event_date && (
                <div className="flex justify-between mb-8"><span className="text-muted">Event Date</span><span>{primary.event_date}</span></div>
              )}
              {isBatch ? (
                <div style={{ marginTop: 12 }}>
                  <div className="text-muted mb-8" style={{ fontSize: 13 }}>Artists in this Event</div>
                  {bookings.map((b) => (
                    <div key={b.id} className="flex justify-between fs-12" style={{ padding: "6px 0", borderBottom: "1px dashed rgba(255,255,255,0.06)" }}>
                      <span>{artistDetails[b.artist_id]?.stage_name || b.ref}<span className="text-muted"> · {artistDetails[b.artist_id]?.category || ""}</span></span>
                      <code style={{ fontSize: 11 }}>{b.ref}</code>
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  {primaryArtist?.stage_name && (
                    <div className="flex justify-between mb-8"><span className="text-muted">Artist</span><span>{primaryArtist.stage_name}</span></div>
                  )}
                  <div className="text-muted fs-11 mt-12" style={{ marginTop: 12, lineHeight: 1.4 }}>
                    ℹ️ The Artist Performance Fee will be settled directly with the artist as per your signed agreement.
                  </div>
                </>
              )}
            </div>

            {/* Action row */}
            <div className="flex gap-12 justify-center" style={{ flexWrap: "wrap" }}>
              <button className="btn btn-gold" onClick={() => nav("/customer")} data-testid="return-view-bookings">📊 Go to Dashboard</button>
              {eventId && (
                <button
                  className="btn btn-ghost"
                  onClick={() => window.open(`/recap/${eventId}`, "_blank", "noopener")}
                  data-testid="return-share-recap"
                >💬 Share Event Recap</button>
              )}
              {!isBatch && primary && (
                <button className="btn btn-ghost" onClick={downloadInvoice} data-testid="return-dl-invoice">🧾 Download Invoice</button>
              )}
              <button className="btn btn-ghost" onClick={() => nav("/")} data-testid="return-go-home">🏠 Home</button>
            </div>

            {/* Complete-your-event suggestion strip */}
            {suggested.length > 0 && eventId && primary && (
              <div className="event-strip" data-testid="event-strip" style={{ marginTop: 32 }}>
                <div className="event-strip-head">
                  <div>
                    <div className="event-strip-title">Complete your event 🎉</div>
                    <div className="event-strip-sub">Same date, same city — add another artist and it joins this event automatically.</div>
                  </div>
                </div>
                <div className="event-strip-scroll">
                  {suggested.map((s) => {
                    const qs = new URLSearchParams({
                      event_id: eventId,
                      date: primary.event_date || "",
                    }).toString();
                    return (
                      <a
                        key={s.user_id}
                        href={`/book/${s.user_id}?${qs}`}
                        className="event-strip-card"
                        data-testid={`event-suggest-${s.user_id}`}
                      >
                        <div className="event-strip-thumb"><span>{s.emoji || "🎤"}</span></div>
                        <div className="event-strip-name">{s.stage_name || s.name}</div>
                        <div className="event-strip-cat">{s.category}{s.city ? ` · ${s.city}` : ""}</div>
                        <div className="event-strip-add">+ Add to event</div>
                      </a>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {isFailed && (
          <div className="card card-pad text-center" data-testid="return-failed" style={{ maxWidth: 520, margin: "0 auto" }}>
            <div style={{ fontSize: 72, marginBottom: 12 }}>❌</div>
            <h2 className="font-serif" style={{ fontSize: 32, fontWeight: 700, marginBottom: 8 }}>Payment Failed</h2>
            <p className="text-muted mb-20">
              {pay?.failure_reason
                ? `Reason: ${pay.failure_reason}`
                : "The payment could not be completed. No amount was charged."}
            </p>
            <p className="text-muted" style={{ fontSize: 12, marginBottom: 24 }}>Transaction: <code>{txnid}</code></p>
            <div className="flex gap-12 justify-center" style={{ flexWrap: "wrap" }}>
              <button className="btn btn-gold" onClick={() => nav(-1)} data-testid="return-try-again">Try Again</button>
              <Link to="/customer" className="btn btn-ghost" data-testid="return-view-bookings-failed">My Bookings</Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
