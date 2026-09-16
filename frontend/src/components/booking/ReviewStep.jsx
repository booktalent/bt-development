import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import TravelRiderCard from "../TravelRiderCard";

/**
 * Iter 50 — ReviewStep, updated in Iter 52.5/52.7:
 *   • Customer-offered Travel Allowance (optional, informational, snapshotted
 *     to the booking + contract PDF so the artist has it in writing).
 *   • Mandatory Terms & Conditions declaration checkbox — required before
 *     "Proceed to Payment" is enabled.
 */
export default function ReviewStep({
  pkg,
  form,
  set,
  isOutstation,
  platformSettings,
  onBack,
  onNext,
  artistId,
}) {
  // Iter 52.7 — pull the artist's Travel & Hospitality rider straight from
  // their onboarding questionnaire so the customer can see everything they'll
  // need to arrange BEFORE hitting Proceed to Payment. No new questions are
  // asked; we just read profile.answers via /artists/{id}/quote?city=…
  const [rider, setRider] = useState(null);
  useEffect(() => {
    if (!isOutstation || !artistId || !form?.city) return;
    api.get(`/artists/${artistId}/quote?city=${encodeURIComponent(form.city)}`)
      .then((r) => setRider(r.data?.rider || null))
      .catch(() => setRider(null));
  }, [isOutstation, artistId, form?.city]);

  const showTravelRider =
    pkg && (pkg.travel_required || pkg.accommodation_required || pkg.local_transport_required || pkg.meals_required || pkg.travel_notes);

  // Proceed-to-Payment gate. T&C is ALWAYS required; travel-ack only when a
  // travel rider is on the package; outstation-ack only for outstation events.
  const nextDisabled =
    !form.tnc_accepted ||
    (showTravelRider && !form.travel_ack) ||
    (isOutstation && !form.outstation_ack);

  const taValue = Number(form.customer_travel_allowance || 0);
  const showTa = showTravelRider || isOutstation; // only shown when travel is a factor

  return (
    <div className="card card-pad" data-testid="step-4">
      <h2 className="font-serif fs-20 fw-700 mb-8">Review & Confirm</h2>
      <p className="text-muted fs-13 mb-20">Double-check details before payment.</p>

      <div className="card card-pad mb-16">
        <h3 className="fw-600 fs-13 mb-12 text-gold" style={{ textTransform: "uppercase" }}>Performance Package</h3>
        <div className="flex justify-between mb-8"><span className="text-muted">Package</span><span>{pkg?.name}</span></div>
        <div className="flex justify-between mb-8"><span className="text-muted">Duration</span><span>{pkg?.duration}</span></div>
        <div className="flex justify-between mb-8"><span className="text-muted">Add-ons</span><span>{form.addons.length || "None"}</span></div>
        {form.addon_selections.length > 0 && (
          <div className="flex justify-between"><span className="text-muted">Artist add-ons</span><span data-testid="review-artist-addons">{form.addon_selections.length}</span></div>
        )}
      </div>

      {showTravelRider && (
        <div className="card card-pad mb-16" data-testid="review-travel-block">
          <h3 className="fw-600 fs-13 mb-12 text-gold" style={{ textTransform: "uppercase" }}>✈️ Travel & Accommodation Rider</h3>
          <div className="text-muted fs-11 mb-12">Borne by you (not billed by BookTalent). Will be captured in the signed agreement.</div>
          {pkg.travel_required && (
            <div className="flex justify-between mb-8"><span className="text-muted">Flight / Travel</span><span>{pkg.flight_class || "economy"} · {pkg.team_size || 1} person(s)</span></div>
          )}
          {pkg.accommodation_required && (
            <div className="flex justify-between mb-8"><span className="text-muted">Accommodation</span><span>{pkg.hotel_category || "3-star"} · {pkg.team_size || 1} person(s)</span></div>
          )}
          {pkg.arrival_buffer_days ? (
            <div className="flex justify-between mb-8"><span className="text-muted">Arrival buffer</span><span>{pkg.arrival_buffer_days} day(s) prior</span></div>
          ) : null}
          {pkg.local_transport_required && <div className="flex justify-between mb-8"><span className="text-muted">Local transport</span><span>Required</span></div>}
          {pkg.meals_required && <div className="flex justify-between mb-8"><span className="text-muted">Meals</span><span>Required during stay</span></div>}
          {pkg.travel_notes && (
            <div className="mt-8">
              <div className="text-muted fs-12 mb-4">Additional notes</div>
              <div className="fs-13">{pkg.travel_notes}</div>
            </div>
          )}
          <label className="flex items-center gap-8 mt-12" data-testid="travel-ack">
            <input type="checkbox" checked={!!form.travel_ack} onChange={(e) => set("travel_ack", e.target.checked)} data-testid="travel-ack-checkbox" />
            <span className="fs-12">I acknowledge and agree to bear these travel & accommodation costs.</span>
          </label>
        </div>
      )}

      <div className="card card-pad mb-16">
        <h3 className="fw-600 fs-13 mb-12 text-gold" style={{ textTransform: "uppercase" }}>Event Details</h3>
        <div className="flex justify-between mb-8"><span className="text-muted">Date</span><span>{form.event_date} · {form.event_time}</span></div>
        <div className="flex justify-between mb-8"><span className="text-muted">Venue</span><span>{form.venue}, {form.city}</span></div>
        <div className="flex justify-between"><span className="text-muted">Type</span><span>{form.event_type}</span></div>
        {(form.special_instructions || "").trim() && (
          <div className="mt-12" data-testid="review-special-instructions">
            <div className="text-muted fs-11 mb-4" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Special Instructions</div>
            <div className="fs-13" style={{ whiteSpace: "pre-line" }}>{form.special_instructions}</div>
          </div>
        )}
      </div>

      {isOutstation && (
        <div className="card card-pad mb-16" style={{ background: "rgba(212,175,55,0.08)", border: "1px solid rgba(212,175,55,0.35)" }} data-testid="review-outstation-notice">
          <div className="fw-700 text-gold fs-13 mb-8" style={{ textTransform: "uppercase", letterSpacing: 1 }}>📢 Outstation Booking</div>
          <div className="fs-13 mb-8" style={{ lineHeight: 1.5, whiteSpace: "pre-line" }}>
            {platformSettings.outstation_notice ||
              "Travel, accommodation, local transportation, meals, hospitality, and any other outstation expenses are NOT included in the Artist Package Fee. Please arrange these directly with the artist."}
          </div>
          <label className="flex items-center gap-8">
            <input type="checkbox" checked={!!form.outstation_ack} onChange={(e) => set("outstation_ack", e.target.checked)} data-testid="outstation-ack" />
            <span className="fs-12">I understand and agree to arrange all outstation logistics directly with the Artist.</span>
          </label>
        </div>
      )}

      {/* Rider block — questionnaire-sourced, only for outstation. Renders
          "empty state" gracefully when the artist hasn't answered yet. */}
      {isOutstation && (
        <div className="mb-16" data-testid="review-rider-block">
          <TravelRiderCard rider={rider} artistCity={undefined} eventCity={form.city} />
        </div>
      )}

      {/* Travel Allowance offered by the customer (informational). Rendered
          only when the booking has a travel/outstation dimension so it stays
          out of the way for local bookings. */}
      {showTa && (
        <div className="card card-pad mb-16" data-testid="review-ta-block">
          <h3 className="fw-600 fs-13 mb-8 text-gold" style={{ textTransform: "uppercase" }}>💸 Travel Allowance Offered (Optional)</h3>
          <div className="text-muted fs-12 mb-10" style={{ lineHeight: 1.5 }}>
            Offering a flat travel allowance? Artists often adjust their package fee when TA is covered up-front. This amount is direct-to-artist — the platform never handles it, but it will be printed on the booking agreement so both sides have it in writing.
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="fs-14 text-muted">₹</span>
            <input
              type="number"
              min="0"
              step="500"
              placeholder="e.g. 5000"
              value={form.customer_travel_allowance}
              onChange={(e) => set("customer_travel_allowance", e.target.value)}
              className="field-input"
              style={{ maxWidth: 180 }}
              data-testid="ta-offered-input"
            />
            {taValue > 0 && (
              <span className="text-gold fs-12 fw-600" data-testid="ta-offered-echo">
                ₹{taValue.toLocaleString("en-IN")} committed to artist
              </span>
            )}
          </div>
        </div>
      )}

      {/* Mandatory Terms & Conditions declaration (Iter 52.5). */}
      <div className="card card-pad mb-16" style={{ borderColor: form.tnc_accepted ? "rgba(110,231,168,0.3)" : "rgba(255,120,120,0.28)" }} data-testid="review-tnc-block">
        <h3 className="fw-600 fs-13 mb-8" style={{ textTransform: "uppercase", color: form.tnc_accepted ? "#6ee7a8" : "#ffd270" }}>
          📜 Declaration
        </h3>
        <label className="flex items-start gap-8" style={{ lineHeight: 1.55 }}>
          <input
            type="checkbox"
            checked={!!form.tnc_accepted}
            onChange={(e) => set("tnc_accepted", e.target.checked)}
            data-testid="tnc-accept-checkbox"
            style={{ marginTop: 3, flex: "none" }}
          />
          <span className="fs-12">
            I confirm that the details above are accurate and I have read and agree to BookTalent's{" "}
            <a href="/terms" target="_blank" rel="noreferrer" className="text-gold" data-testid="tnc-link-terms">Terms & Conditions</a>,{" "}
            <a href="/privacy" target="_blank" rel="noreferrer" className="text-gold" data-testid="tnc-link-privacy">Privacy Policy</a>{" "}
            and{" "}
            <a href="/refund" target="_blank" rel="noreferrer" className="text-gold" data-testid="tnc-link-refund">Cancellation & Refund Policy</a>.
            I acknowledge that BookTalent collects only the 5% Platform Service Fee + 18% GST here — the artist's package fee is paid directly to the artist as per the signed agreement.
          </span>
        </label>
      </div>

      <div className="flex justify-between mt-24">
        <button className="btn btn-ghost" onClick={onBack} data-testid="step4-back">← Back</button>
        <button
          className="btn btn-gold"
          onClick={onNext}
          disabled={nextDisabled}
          data-testid="step4-next"
          title={nextDisabled ? "Please tick the required boxes above" : undefined}
        >
          🔐 Proceed to Payment →
        </button>
      </div>
    </div>
  );
}
