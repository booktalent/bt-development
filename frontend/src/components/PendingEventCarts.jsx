/**
 * PendingEventCarts — "Resume Booking" cards for the Customer Dashboard.
 *
 * Solves the "I added artists to my event cart, navigated away by mistake,
 * and now can't find my cart" problem (Iter 52.5 user report).
 *
 * The event cart lives in localStorage keyed by the primary artist id
 * (see useEventCart). We scan those keys on mount, render one card per
 * pending cart, and offer Resume (→ /book/:primary_id) or Discard.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const PREFIX = "bt_event_cart_";
const STALE_MS = 30 * 24 * 60 * 60 * 1000; // auto-hide carts older than 30 days

function readAll() {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      try {
        const v = JSON.parse(localStorage.getItem(k));
        if (!v || !Array.isArray(v.items) || v.items.length === 0) continue;
        if (v.saved_at && Date.now() - v.saved_at > STALE_MS) continue;
        out.push({ key: k, primary_id: k.slice(PREFIX.length), ...v });
      } catch { /* skip corrupt entry */ }
    }
  } catch { /* localStorage disabled */ }
  out.sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0));
  return out;
}

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} hr ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export default function PendingEventCarts() {
  const [carts, setCarts] = useState(readAll);

  // Refresh if another tab mutates the cart (StorageEvent fires cross-tab)
  useEffect(() => {
    const onStorage = (e) => { if (e.key && e.key.startsWith(PREFIX)) setCarts(readAll()); };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const discard = (key) => {
    if (!window.confirm("Discard this pending event cart?")) return;
    try { localStorage.removeItem(key); } catch { /* ignore */ }
    setCarts(readAll());
  };

  if (carts.length === 0) return null;

  return (
    <div className="card card-pad mb-24" data-testid="pending-event-carts" style={{ borderColor: "rgba(246,211,102,0.3)" }}>
      <div className="flex items-center justify-between mb-12" style={{ gap: 10, flexWrap: "wrap" }}>
        <div>
          <div className="font-serif fs-18 fw-700">Resume your event booking</div>
          <div className="text-muted fs-12">
            You have {carts.length} unfinished event{carts.length > 1 ? "s" : ""} — pick up right where you left off.
          </div>
        </div>
      </div>

      <div className="pending-carts-grid">
        {carts.map((c) => (
          <div key={c.key} className="pending-cart-card" data-testid={`pending-cart-${c.primary_id}`}>
            <div className="pending-cart-thumb">
              {c.primary_photo
                ? <img src={c.primary_photo} alt={c.primary_name || "Artist"} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                : <span style={{ fontSize: 26 }}>🎤</span>}
            </div>
            <div className="pending-cart-body">
              <div className="fw-700 fs-14">{c.primary_name || "Primary Artist"}</div>
              <div className="text-muted fs-11">
                {c.primary_category || "Performer"}{c.primary_city ? ` · ${c.primary_city}` : ""}
              </div>
              <div className="fs-11 mt-4">
                <span className="text-gold fw-700">+{c.items.length}</span> more artist{c.items.length > 1 ? "s" : ""} in cart
                {c.event_date ? <> · <span className="text-muted">{c.event_date}</span></> : null}
              </div>
              <div className="text-muted fs-11 mt-4">Saved {timeAgo(c.saved_at)}</div>
              <div className="flex" style={{ gap: 8, marginTop: 10 }}>
                <Link
                  to={`/book/${c.primary_id}`}
                  className="btn btn-gold btn-sm"
                  data-testid={`resume-${c.primary_id}`}
                >Resume →</Link>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => discard(c.key)}
                  data-testid={`discard-${c.primary_id}`}
                >Discard</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
