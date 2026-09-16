import React, { useState } from "react";

/**
 * Iter 75.5 — Mandatory cancellation-reason capture.
 *
 * Used by both artist AND customer cancel flows. The parent supplies:
 *   - open           : boolean
 *   - onClose        : () => void
 *   - onConfirm      : (reason: string) => void
 *   - actorRole      : "artist" | "customer" (drives copy)
 *   - amountPaid     : number  (0 for unpaid) — governs the warning line
 *   - bookingRef     : optional booking ref for context
 *
 * The confirm button stays disabled until a preset is picked OR a
 * non-empty custom reason (>= 3 chars) is typed. Backend also enforces
 * this — see `/api/bookings/{id}/action` cancel branch.
 */

const ARTIST_REASONS = [
  "Personal emergency / illness",
  "Schedule conflict with another confirmed event",
  "Unable to travel to the venue on this date",
  "Technical / equipment issue on my side",
  "Customer requirements changed and no longer viable",
  "Health & safety concern",
];

const CUSTOMER_REASONS = [
  "Event is postponed",
  "Event is cancelled entirely",
  "Booked wrong artist / package by mistake",
  "Change of budget",
  "Change of venue or city",
  "Found a different artist",
];

export default function CancellationReasonModal({
  open,
  onClose,
  onConfirm,
  actorRole = "customer",
  amountPaid = 0,
  bookingRef = "",
}) {
  const [selected, setSelected] = useState("");
  const [custom, setCustom] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const isArtist = actorRole === "artist";
  const presets = isArtist ? ARTIST_REASONS : CUSTOMER_REASONS;

  const reason = (selected === "__other__" ? custom : selected).trim();
  const canSubmit = reason.length >= 3 && !submitting;

  const submit = async (e) => {
    e?.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onConfirm(reason);
    } finally {
      setSubmitting(false);
      setSelected("");
      setCustom("");
    }
  };

  const paid = Number(amountPaid || 0) > 0;

  return (
    <div
      data-testid="cancel-reason-backdrop"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 550,
        background: "rgba(4,6,20,0.75)", backdropFilter: "blur(10px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
    >
      <form
        data-testid="cancel-reason-modal"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        style={{
          width: 500, maxWidth: "100%", maxHeight: "88vh", overflow: "auto",
          background: "linear-gradient(180deg, #16172B, #0F0F1B)",
          border: "1px solid rgba(255,107,129,0.35)",
          borderRadius: 20, padding: "22px 22px 18px",
          color: "#F0EEFF",
          boxShadow: "0 24px 64px -12px rgba(0,0,0,0.75)",
        }}
      >
        <div style={{ fontSize: 22, marginBottom: 6 }}>❌</div>
        <h3 style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: 22, fontWeight: 700, margin: "0 0 4px",
        }}>
          Cancel booking{bookingRef ? ` ${bookingRef}` : ""}
        </h3>
        <p style={{
          fontSize: 13, lineHeight: 1.55,
          color: "rgba(240,238,255,0.7)", margin: "0 0 14px",
        }}>
          {isArtist && paid && (
            <>The customer's Platform Service Fee will be <strong>auto-refunded via Easebuzz</strong>. This may impact your artist rating. Please tell us why.</>
          )}
          {isArtist && !paid && (
            <>Please tell us why you're cancelling — it helps the customer and our team.</>
          )}
          {!isArtist && paid && (
            <>Your Platform Service Fee of <strong>₹{Number(amountPaid).toLocaleString("en-IN")}</strong> is <strong>non-refundable</strong> for customer-initiated cancellations. If you want a refund, please ask the artist to cancel instead.</>
          )}
          {!isArtist && !paid && (
            <>Please tell us why you're cancelling so the artist knows what happened.</>
          )}
        </p>

        <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
          {presets.map((r) => (
            <label
              key={r}
              data-testid={`cancel-reason-${r.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                background: selected === r ? "rgba(212,175,55,0.12)" : "rgba(255,255,255,0.03)",
                border: `1px solid ${selected === r ? "rgba(212,175,55,0.4)" : "rgba(255,255,255,0.08)"}`,
                fontSize: 13,
              }}
            >
              <input
                type="radio" name="cancel-reason" value={r}
                checked={selected === r}
                onChange={(e) => setSelected(e.target.value)}
                style={{ accentColor: "#d4af37" }}
              />
              {r}
            </label>
          ))}
          <label
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 10px", borderRadius: 8, cursor: "pointer",
              background: selected === "__other__" ? "rgba(212,175,55,0.12)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${selected === "__other__" ? "rgba(212,175,55,0.4)" : "rgba(255,255,255,0.08)"}`,
              fontSize: 13,
            }}
          >
            <input
              type="radio" name="cancel-reason" value="__other__"
              checked={selected === "__other__"}
              onChange={(e) => setSelected(e.target.value)}
              style={{ accentColor: "#d4af37" }}
            />
            Other (please specify)
          </label>
          {selected === "__other__" && (
            <textarea
              autoFocus
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="Type your reason (min 3 chars)…"
              rows={3}
              maxLength={500}
              className="field-input"
              data-testid="cancel-reason-other-input"
              style={{ width: "100%", resize: "vertical" }}
            />
          )}
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 8 }}>
          <button
            type="button"
            className="btn btn-ghost"
            data-testid="cancel-reason-back"
            onClick={onClose}
            disabled={submitting}
          >Keep booking</button>
          <button
            type="submit"
            className="btn btn-red"
            data-testid="cancel-reason-confirm"
            disabled={!canSubmit}
          >
            {submitting ? "Cancelling…" : "Confirm cancellation"}
          </button>
        </div>
      </form>
    </div>
  );
}
