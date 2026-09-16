/**
 * EventCartIndicator — top-nav pill that surfaces any unfinished event cart
 * for a logged-in customer (Iter 52.5 UX request).
 *
 * Design decisions:
 * - Renders NOTHING when there is no pending cart, so the nav stays clean.
 * - Only shown to role='customer' (agencies/artists don't book).
 * - Click opens a small popover with resume shortcuts. If only one cart is
 *   pending we still open the popover so the user sees context before jumping.
 * - Auto-refreshes on `storage` events (cross-tab) AND on a custom
 *   `bt-event-cart-changed` event dispatched by useEventCart on mutation.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";

const PREFIX = "bt_event_cart_";
const STALE_MS = 30 * 24 * 60 * 60 * 1000;

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
      } catch { /* skip corrupt */ }
    }
  } catch { /* ignore */ }
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

export default function EventCartIndicator() {
  const { user } = useAuth();
  const [carts, setCarts] = useState(readAll);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  const refresh = useCallback(() => setCarts(readAll()), []);
  useEffect(() => {
    const onStorage = (e) => { if (!e.key || e.key.startsWith(PREFIX)) refresh(); };
    const onCustom = () => refresh();
    window.addEventListener("storage", onStorage);
    window.addEventListener("bt-event-cart-changed", onCustom);
    // Also re-scan every 30s in case a stale card should hide (30-day TTL).
    const t = setInterval(refresh, 30000);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("bt-event-cart-changed", onCustom);
      clearInterval(t);
    };
  }, [refresh]);

  // Outside-click close
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Gate: only for logged-in customers with at least one pending cart.
  if (!user || user.role !== "customer") return null;
  if (carts.length === 0) return null;

  const totalArtists = carts.reduce((s, c) => s + (c.items?.length || 0), 0);

  const discard = (key) => {
    if (!window.confirm("Discard this pending event cart?")) return;
    try { localStorage.removeItem(key); } catch { /* ignore */ }
    window.dispatchEvent(new Event("bt-event-cart-changed"));
    refresh();
  };

  return (
    <div className="ecart-indicator" ref={wrapRef} data-testid="event-cart-indicator">
      <button
        className={`ecart-pill ${open ? "open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={`Resume booking — ${carts.length} pending`}
        data-testid="event-cart-pill"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
          <line x1="3" y1="6" x2="21" y2="6" />
          <path d="M16 10a4 4 0 0 1-8 0" />
        </svg>
        <span className="ecart-label">Resume Booking</span>
        <span className="ecart-count" data-testid="event-cart-count">{carts.length}</span>
      </button>

      {open && (
        <div className="ecart-popover" data-testid="event-cart-popover" role="dialog">
          <div className="ecart-popover-head">
            <div>
              <div className="fw-700">Continue where you left off</div>
              <div className="text-muted fs-11">
                {carts.length} unfinished event{carts.length > 1 ? "s" : ""} · {totalArtists} added artist{totalArtists > 1 ? "s" : ""}
              </div>
            </div>
            <button className="ecart-close" onClick={() => setOpen(false)} aria-label="Close">✕</button>
          </div>

          <div className="ecart-list">
            {carts.map((c) => (
              <div key={c.key} className="ecart-item" data-testid={`event-cart-item-${c.primary_id}`}>
                <div className="ecart-thumb">
                  {c.primary_photo
                    ? <img src={c.primary_photo} alt={c.primary_name || "Artist"} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                    : <span style={{ fontSize: 20 }}>🎤</span>}
                </div>
                <div className="ecart-body">
                  <div className="fw-700 fs-13" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {c.primary_name || "Primary artist"}
                  </div>
                  <div className="text-muted fs-11">
                    <span className="text-gold fw-700">+{c.items.length}</span> more artist{c.items.length > 1 ? "s" : ""}
                    {c.event_date ? ` · ${c.event_date}` : ""}
                  </div>
                  <div className="text-muted fs-11">Saved {timeAgo(c.saved_at)}</div>
                </div>
                <div className="ecart-actions">
                  <Link
                    to={`/book/${c.primary_id}`}
                    className="btn btn-gold btn-sm"
                    onClick={() => setOpen(false)}
                    data-testid={`event-cart-resume-${c.primary_id}`}
                  >Resume</Link>
                  <button className="ecart-discard" onClick={() => discard(c.key)} data-testid={`event-cart-discard-${c.primary_id}`}>Discard</button>
                </div>
              </div>
            ))}
          </div>

          <div className="ecart-popover-foot">
            <Link to="/customer" className="fs-12" onClick={() => setOpen(false)}>Manage all →</Link>
          </div>
        </div>
      )}
    </div>
  );
}
