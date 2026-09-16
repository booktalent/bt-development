import React from "react";
import { fmtINRFull } from "../../lib/api";

/**
 * Iter 64 — PaymentStep (Easebuzz-only)
 * Pure-render component for BookingFlow's Step 5 (Secure Payment).
 *
 * Props:
 *   gatewayInfo — { provider, enabled, environment }
 *   busy        — disables Pay button
 *   token, cartPricing, isMultiEvent, cartItems — pricing display
 *   onBack, onSubmit — nav handlers
 */
export default function PaymentStep({
  gatewayInfo,
  busy,
  token,
  cartPricing,
  isMultiEvent,
  cartItems,
  onBack,
  onSubmit,
}) {
  const amount = isMultiEvent ? cartPricing.token_amount : token;
  const isEasebuzz = gatewayInfo?.enabled && gatewayInfo?.provider === "easebuzz";
  const easebuzzSandbox = isEasebuzz && gatewayInfo?.environment === "sandbox";

  if (!isEasebuzz) {
    return (
      <div className="card card-pad" data-testid="step-5">
        <h2 className="font-serif fs-20 fw-700 mb-8">Secure Payment</h2>
        <div style={{ padding: 20, border: "1px solid rgba(239,68,68,0.35)", borderRadius: 12, background: "rgba(239,68,68,0.1)", color: "#fecaca" }}>
          Payment gateway is currently disabled. Please try again later or contact support.
        </div>
        <div className="flex justify-between mt-24">
          <button className="btn btn-ghost" onClick={onBack} data-testid="step5-back">← Back</button>
        </div>
      </div>
    );
  }

  return (
    <div className="card card-pad" data-testid="step-5">
      <h2 className="font-serif fs-20 fw-700 mb-8">Secure Payment</h2>
      <p className="text-muted fs-13 mb-20">
        Pay your 5% booking token to confirm{isMultiEvent ? ` · ${cartItems.length} artists in this event` : ""}.
      </p>

      <div style={{
        background: "linear-gradient(135deg, rgba(212,175,55,0.06), rgba(212,175,55,0.02))",
        border: "1px solid rgba(212,175,55,0.25)",
        borderRadius: 14, padding: 20, marginBottom: 20,
      }} data-testid="easebuzz-summary">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 22 }}>🔐</span>
          <strong style={{ fontSize: 15 }}>Easebuzz Secure Checkout</strong>
          {easebuzzSandbox && (
            <span style={{
              marginLeft: "auto", padding: "3px 10px", borderRadius: 999,
              background: "rgba(59,130,246,0.15)", color: "#93c5fd", fontSize: 11, fontWeight: 700,
            }} data-testid="easebuzz-sandbox-badge">SANDBOX MODE</span>
          )}
        </div>
        <p className="text-muted fs-13" style={{ margin: 0, lineHeight: 1.6 }}>
          You'll be redirected to Easebuzz's PCI-DSS-secured payment page where you can pay via
          <b> UPI</b>, <b>Cards</b>, <b>Netbanking</b>, <b>Wallets</b> or <b>EMI</b>. We'll bring you
          straight back to BookTalent once payment is confirmed. If a booking is cancelled or the
          artist doesn't accept in time, your amount is automatically refunded to the same source.
        </p>
        {easebuzzSandbox && (
          <p className="text-muted fs-12" style={{ marginTop: 10, marginBottom: 0, color: "#93c5fd" }}>
            Test mode active — use any Easebuzz sandbox test card / UPI to complete a mock transaction.
          </p>
        )}
      </div>

      <div className="flex justify-between mt-24">
        <button className="btn btn-ghost" onClick={onBack} data-testid="step5-back">← Back</button>
        <button className="btn btn-gold btn-lg" disabled={busy} onClick={onSubmit} data-testid="pay-now-btn">
          {busy
            ? "Redirecting to Easebuzz…"
            : `🔐 Continue to Pay ${fmtINRFull(amount)}${isMultiEvent ? ` · ${cartItems.length} artists` : ""}`}
        </button>
      </div>
    </div>
  );
}
