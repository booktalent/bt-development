/**
 * TravelRiderCard — Travel & Hospitality summary distilled from the artist's
 * onboarding questionnaire, surfaced BEFORE the customer confirms a booking.
 *
 * Data source: /api/artists/{id}/quote?city=X → response.rider
 *   Nothing new is asked of the artist here — the fields below are exact
 *   passthroughs from `artist_profiles.answers` populated during onboarding.
 *
 * Rendered:
 *   • Only when quote.is_outstation is true (local bookings don't need this)
 *   • Below the Outstation Terms card on the artist profile
 *   • And on the ReviewStep of the BookingFlow as a final read-only summary
 */
import React from "react";

const ROW = ({ label, value, icon }) => {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return null;
  const display = Array.isArray(value) ? value.join(" · ") : String(value);
  return (
    <div className="rider-row" data-testid={`rider-row-${label.toLowerCase().replace(/\W+/g, "-")}`}>
      <div className="rider-row-label">
        <span aria-hidden style={{ marginRight: 6 }}>{icon}</span>{label}
      </div>
      <div className="rider-row-value">{display}</div>
    </div>
  );
};

export default function TravelRiderCard({ rider, artistCity, eventCity, compact = false }) {
  if (!rider || !rider.has_any) {
    // Graceful empty state — customer still knows travel is out-of-scope.
    return (
      <div className="rider-card rider-card-empty" data-testid="rider-card-empty">
        <div className="rider-head">
          <div className="rider-head-icon">✈️</div>
          <div>
            <div className="rider-head-title">Travel & Hospitality Requirements</div>
            <div className="rider-head-sub">The artist hasn't published a detailed rider yet — please coordinate directly.</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`rider-card ${compact ? "compact" : ""}`} data-testid="travel-rider-card">
      <div className="rider-head">
        <div className="rider-head-icon">✈️</div>
        <div>
          <div className="rider-head-title">Travel & Hospitality Requirements</div>
          <div className="rider-head-sub">
            {artistCity && eventCity
              ? <>Direct-to-artist expenses for this outstation booking · {artistCity} → {eventCity}</>
              : <>Direct-to-artist expenses for this outstation booking</>}
          </div>
        </div>
      </div>

      <div className="rider-grid">
        <ROW icon="✈️" label="Travel mode" value={rider.travel_modes} />
        <ROW icon="💺" label="Flight class" value={rider.flight_class} />
        <ROW icon="🚕" label="Local transport" value={rider.local_transport} />
        <ROW icon="🏨" label="Hotel required" value={rider.hotel_required} />
        <ROW icon="⭐" label="Hotel category" value={rider.hotel_category} />
        <ROW icon="🛏️" label="Rooms required" value={rider.rooms_required} />
        <ROW icon="🍽️" label="Food preference" value={rider.food_preference} />
        <ROW icon="🥂" label="Hospitality" value={rider.hospitality_needs} />
        <ROW icon="🚪" label="Green room" value={rider.green_room_required ? "Required" : null} />
        <ROW icon="🎚️" label="Sound provider" value={rider.sound_provider} />
        <ROW icon="🔊" label="Sound requirements" value={rider.sound_details} />
        <ROW icon="💡" label="Light requirements" value={rider.light_details} />
        <ROW icon="🛠️" label="Technical notes" value={rider.technical_notes} />
        <ROW icon="📝" label="Travel notes" value={rider.travel_notes} />
        <ROW icon="💸" label="Travel cost borne by" value={rider.travel_who_pays} />
        <ROW icon="📌" label="Additional conditions" value={rider.additional_conditions} />
      </div>

      <div className="rider-foot">
        These are the artist's declared requirements — please arrange them directly. Once you confirm the booking, they'll also appear on the signed contract PDF.
      </div>
    </div>
  );
}
