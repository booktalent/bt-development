import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import api, { thumbUrl, mediaUrl } from "../lib/api";
import { useToast } from "../lib/toast";

/**
 * Public shareable Booking Recap page.
 * Route:  /recap/:event_id     (no auth required)
 *
 * Renders a beautiful, WhatsApp-friendly card with:
 *   • Event date, city, venue, event type
 *   • Grid of every artist booked for this event (name, photo, category)
 *   • "Booked via BookTalent" watermark
 *   • QR code that opens this exact recap page
 *   • Share buttons: WhatsApp · Copy Link · Email
 *
 * Never exposes customer contact or payment amounts — publicly safe.
 */
export default function RecapPage() {
  const { event_id } = useParams();
  const toast = useToast();
  const [recap, setRecap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get(`/events/${event_id}/recap`)
      .then((r) => {
        if (!cancelled) setRecap(r.data);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.status === 404 ? "Event not found" : "Could not load recap");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [event_id]);

  const shareUrl = typeof window !== "undefined" ? window.location.href : "";
  const shareText = recap
    ? `🎉 ${recap.host_first_name} just booked ${recap.artist_count} artist${recap.artist_count > 1 ? "s" : ""} for a ${recap.event_type} on ${fmtDate(recap.event_date)} — via BookTalent`
    : "";

  const doWhatsApp = () => {
    const url = `https://wa.me/?text=${encodeURIComponent(`${shareText}\n\n${shareUrl}`)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };
  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast("Link copied to clipboard", "success");
    } catch {
      toast("Could not copy — long-press the link to copy manually", "error");
    }
  };
  const doEmail = () => {
    const subject = `Event Recap — ${recap?.event_type || "Booking"} on ${fmtDate(recap?.event_date)}`;
    const body = `${shareText}\n\nSee the full recap → ${shareUrl}`;
    window.location.href = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  };

  if (loading) {
    return (
      <div className="recap-page">
        <div className="recap-loading">
          <div className="spinner" />
          <p className="text-muted mt-16">Loading event recap…</p>
        </div>
      </div>
    );
  }
  if (error || !recap) {
    return (
      <div className="recap-page">
        <div className="recap-card recap-empty" data-testid="recap-empty">
          <div style={{ fontSize: 56 }}>😔</div>
          <h1 className="font-serif fs-24 fw-700 mt-12">{error || "Event not found"}</h1>
          <p className="text-muted mt-8">This event may have expired or the link is incorrect.</p>
          <Link to="/" className="btn btn-gold mt-24">Discover Artists →</Link>
        </div>
      </div>
    );
  }

  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(shareUrl)}&size=180x180&margin=8&bgcolor=0f0e17&color=f5d47a`;

  return (
    <div className="recap-page" data-testid="recap-page">
      <Helmet>
        <title>{`${recap.host_first_name}'s Event · Booked via BookTalent`}</title>
        <meta property="og:title" content={`${recap.host_first_name}'s ${recap.event_type} — ${fmtDate(recap.event_date)}`} />
        <meta property="og:description" content={`${recap.artist_count} artist${recap.artist_count > 1 ? "s" : ""} booked via BookTalent`} />
        <meta property="og:type" content="website" />
      </Helmet>

      <div className="recap-card">
        <div className="recap-watermark">Booked via <strong>BookTalent</strong></div>

        <div className="recap-hero">
          <div className="recap-badge">🎉 Event Recap</div>
          <h1 className="recap-title font-serif" data-testid="recap-title">
            {recap.host_first_name}'s {recap.event_type}
          </h1>
          <div className="recap-when">
            <span data-testid="recap-date">📅 {fmtDate(recap.event_date)}</span>
            {recap.event_time && <span> · {recap.event_time}</span>}
          </div>
          <div className="recap-where">
            <span>📍 {recap.venue}{recap.city ? `, ${recap.city}` : ""}</span>
          </div>
        </div>

        <div className="recap-divider" />

        <div className="recap-lineup-head">
          <span className="recap-count-pill" data-testid="recap-count">{recap.artist_count} Artist{recap.artist_count > 1 ? "s" : ""}</span>
          <span className="recap-lineup-label">Line-up</span>
        </div>

        <div className="recap-artist-grid" data-testid="recap-artists">
          {recap.artists.map((a) => {
            const img = a.featured_media_id ? thumbUrl(a.featured_media_id) || mediaUrl(a.featured_media_id) : null;
            return (
              <a
                key={a.user_id}
                href={a.profile_url}
                target="_blank"
                rel="noopener noreferrer"
                className="recap-artist-tile"
                data-testid={`recap-artist-${a.user_id}`}
              >
                <div className="recap-artist-thumb">
                  {img ? (
                    <img src={img} alt={a.stage_name} onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  ) : (
                    <span className="recap-artist-emoji">{a.emoji}</span>
                  )}
                </div>
                <div className="recap-artist-meta">
                  <div className="recap-artist-name">{a.stage_name}</div>
                  <div className="recap-artist-cat text-muted fs-11">{a.category}{a.city ? ` · ${a.city}` : ""}</div>
                </div>
              </a>
            );
          })}
        </div>

        <div className="recap-divider" />

        <div className="recap-footer">
          <div className="recap-qr-block">
            <img src={qrSrc} alt="Scan to view recap" className="recap-qr" />
            <div className="recap-qr-label">Scan to view</div>
          </div>
          <div className="recap-share">
            <div className="recap-share-title">Share this event</div>
            <div className="recap-share-btns">
              <button className="recap-btn recap-btn-wa" onClick={doWhatsApp} data-testid="recap-share-wa">
                <span>💬</span> WhatsApp
              </button>
              <button className="recap-btn recap-btn-copy" onClick={doCopy} data-testid="recap-share-copy">
                <span>🔗</span> Copy Link
              </button>
              <button className="recap-btn recap-btn-email" onClick={doEmail} data-testid="recap-share-email">
                <span>✉️</span> Email
              </button>
            </div>
            <div className="recap-cta">
              <Link to="/" className="recap-brand-link" data-testid="recap-brand-link">
                Book your own event on <strong>BookTalent →</strong>
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function fmtDate(s) {
  if (!s) return "";
  try {
    const d = new Date(s);
    return d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  } catch {
    return s;
  }
}
