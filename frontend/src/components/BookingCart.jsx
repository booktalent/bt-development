import React from "react";
import { fmtINRFull } from "../lib/api";

/**
 * Iter 45 — BookingCart
 * Renders every artist currently held in the customer's event cart during
 * the primary BookingFlow. The primary artist is always cart[0] with
 * `is_primary: true` and can NOT be removed here (removal = leave the page).
 *
 * Props:
 *   items:  cart items (see AddArtistToCartModal.jsx for the shape)
 *   onRemove(artist_id):  removes an added artist (never called for primary)
 *   pricing: server-computed pricing summary (optional, may fall back)
 */
export default function BookingCart({
  items,
  onRemove,
  pricing,
  compact = false,
  onContinue,
  continueDisabled = false,
  continueLabel = "Continue →",
  continueTestId = "booking-cart-continue",
}) {
  if (!items?.length) return null;

  // Approximate totals client-side. Backend recomputes 5% + 18% GST authoritatively.
  const subtotal = items.reduce((s, i) => s + Number(i.price_subtotal || i.package_price || 0), 0);
  const platform_fee = pricing?.platform_fee ?? Math.round(subtotal * 0.05 * 100) / 100;
  const gst = pricing?.gst ?? Math.round(platform_fee * 0.18 * 100) / 100;
  const token_amount = pricing?.token_amount ?? Math.round((platform_fee + gst) * 100) / 100;
  const multi = items.length > 1;

  return (
    <div className={`booking-cart ${compact ? "compact" : ""}`} data-testid="booking-cart">
      <div className="booking-cart-head">
        <span className="booking-cart-icon">🛒</span>
        <div>
          <div className="booking-cart-title">Your Event Cart</div>
          <div className="booking-cart-sub">{items.length} artist{items.length > 1 ? "s" : ""} · one checkout</div>
        </div>
      </div>

      <div className="booking-cart-items">
        {items.map((it, idx) => (
          <div key={it.artist_id} className="booking-cart-item" data-testid={`cart-item-${it.artist_id}`}>
            <div className="booking-cart-thumb">
              {it.artist_photo ? <img src={it.artist_photo} alt={it.artist_name} onError={(e) => { e.currentTarget.style.display = "none"; }} /> : <span>{it.emoji || "🎤"}</span>}
            </div>
            <div className="booking-cart-body">
              <div className="booking-cart-name">
                {it.artist_name}
                {it.is_primary && <span className="booking-cart-primary-pill">Primary</span>}
              </div>
              <div className="text-muted fs-11">{it.category}{it.city ? ` · ${it.city}` : ""}</div>
              <div className="booking-cart-pkg">
                <span className="fs-11">{it.package_name}</span>
                {it.addon_selections?.length > 0 && (
                  <span className="text-muted fs-11"> · +{it.addon_selections.length} add-on{it.addon_selections.length > 1 ? "s" : ""}</span>
                )}
              </div>
            </div>
            <div className="booking-cart-price">
              <div className="text-gold fw-700 fs-13">{fmtINRFull(it.price_subtotal || it.package_price || 0)}</div>
              {!it.is_primary && (
                <button
                  className="booking-cart-remove"
                  onClick={() => onRemove?.(it.artist_id)}
                  data-testid={`cart-remove-${it.artist_id}`}
                  title="Remove from event"
                >✕</button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="booking-cart-totals">
        <div className="booking-cart-total-row">
          <span className="text-muted">Artists Total (direct-to-artist)</span>
          <span>{fmtINRFull(subtotal)}</span>
        </div>
        <div className="booking-cart-total-row">
          <span className="text-muted">Platform Service Fee (5%)</span>
          <span>{fmtINRFull(platform_fee)}</span>
        </div>
        <div className="booking-cart-total-row">
          <span className="text-muted">GST on Fee (18%)</span>
          <span>{fmtINRFull(gst)}</span>
        </div>
        <div className="booking-cart-divider" />
        <div className="booking-cart-total-row grand">
          <span className="fw-700">You pay BookTalent now</span>
          <span className="text-gold fw-700 fs-16" data-testid="cart-grand-total">{fmtINRFull(token_amount)}</span>
        </div>
        <div className="text-muted fs-11 mt-8" style={{ lineHeight: 1.5 }}>
          Only the Platform Service Fee + GST is collected here — {multi ? "each artist's" : "the artist's"} package fee is paid directly to {multi ? "them" : "the artist"} on the event day.
        </div>
        {onContinue && (
          <button
            className="btn btn-gold btn-block mt-16"
            onClick={onContinue}
            disabled={continueDisabled}
            data-testid={continueTestId}
            style={{ width: "100%" }}
          >
            {continueLabel}
          </button>
        )}
      </div>
    </div>
  );
}
