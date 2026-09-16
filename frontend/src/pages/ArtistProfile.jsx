import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import AvailabilityCalendar from "../components/AvailabilityCalendar";
import TravelRiderCard from "../components/TravelRiderCard";
import api, { fmtINRFull, mediaUrl, thumbUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import LoginGate, { useLoginGate } from "../components/LoginGate";
import { useToast } from "../lib/toast";
import { Heart, MessageCircle } from "lucide-react";

const UUID_RX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function ArtistProfile() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [about, setAbout] = useState(null); // Iter 55 — questionnaire answers
  const [tab, setTab] = useState("about");
  const [selectedPkg, setSelectedPkg] = useState(null);
  const [artistId, setArtistId] = useState(id);
  const [lightbox, setLightbox] = useState(null); // { items: MediaItem[], idx: number }
  // Iter 52.6 — Venue-first booking flow. The customer must type the event
  // city BEFORE the "Book Now" button unlocks. We hit /artists/:id/quote to
  // determine outstation status + adjusted quoted price so the profile shows
  // the correct number and (when outstation) surfaces mandatory terms.
  const [eventCity, setEventCity] = useState("");
  const [quote, setQuote] = useState(null);
  const [quoting, setQuoting] = useState(false);
  const [outstationAck, setOutstationAck] = useState(false);
  const nav = useNavigate();
  const { user } = useAuth();
  const toast = useToast();
  // Iter 70 — Show a friendly guardrail modal when a guest tries to book,
  // instead of instantly redirecting them to /login and losing context.
  const [showLoginGate, setShowLoginGate] = React.useState(false);
  const [loginGateReturnTo, setLoginGateReturnTo] = React.useState(null);
  // Iter 71 — Extended LoginGate coverage to Favorite / Message Artist /
  // Availability calendar picks. Uses the shared `useLoginGate` hook so
  // each guest action gets its own contextual title + message override.
  const secondaryGate = useLoginGate();
  // Favorites are stored locally per-browser as an MVP — swap for a real
  // /api/customer/favorites endpoint when a proper account-scoped list is
  // needed. localStorage keeps the code side-effect-free for logged-out
  // browsing sessions too (their picks travel with them if they sign up).
  const favoritesKey = "bt_favorites";
  const [isFavorite, setIsFavorite] = React.useState(false);
  // Iter 73 — Location popup: instead of a hard alert("enter city first"),
  // opening the Book Now with no city shows a friendly modal that captures
  // it, auto-fills the sidebar city field, then resumes the flow. Declared
  // up here (BEFORE the early returns below) so hook order stays stable.
  const [locationPrompt, setLocationPrompt] = React.useState({ open: false, value: "" });
  React.useEffect(() => {
    try {
      const raw = localStorage.getItem(favoritesKey);
      const list = raw ? JSON.parse(raw) : [];
      setIsFavorite(list.includes(artistId));
    } catch { /* ignore */ }
  }, [artistId]);

  useEffect(() => {
    // Support both /artist/:uuid and SEO-friendly /artist/:slug URLs
    const load = async () => {
      let uid = id;
      if (!UUID_RX.test(id)) {
        try {
          const r = await api.get(`/artists/slug/${id}`);
          uid = r.data.user_id;
        } catch (_) { setData({ notFound: true }); return; }
      }
      setArtistId(uid);
      try {
        const r = await api.get(`/artists/${uid}`);
        setData(r.data);
        const pop = r.data.packages.find((p) => p.is_popular) || r.data.packages[0];
        if (pop) setSelectedPkg(pop);
        // Iter 55 — Pull the artist's questionnaire answers so the About
        // tab can render every declared detail (travel, hospitality,
        // technical rider, availability windows, category-specific
        // preferences…). This endpoint is public — same access rules as
        // the profile itself.
        api.get(`/artists/${uid}/about`).then((ar) => setAbout(ar.data)).catch(() => setAbout(null));
        // Iter 74 — Silently record the view for logged-in customers so
        // their dashboard can surface "Recently Viewed" artists across
        // any device. Failures are non-fatal (401 = guest browsing).
        if (user && (user.role === "customer" || user.role === "corporate")) {
          api.post(`/customer/recent-views/${uid}`).catch(() => {});
        }
      } catch (_) { setData({ notFound: true }); }
    };
    load();
  }, [id]);

  // Debounced quote fetch when the customer types an event city. We wait
  // 400 ms after their last keystroke to avoid firing on every character
  // and only fire when at least 2 chars are present so single-letter typos
  // don't ping the backend.
  useEffect(() => {
    if (!artistId) return;
    const city = (eventCity || "").trim();
    if (city.length < 2) { setQuote(null); return; }
    setQuoting(true);
    const t = setTimeout(() => {
      api.get(`/artists/${artistId}/quote?city=${encodeURIComponent(city)}`)
        .then((r) => setQuote(r.data))
        .catch(() => setQuote(null))
        .finally(() => setQuoting(false));
    }, 400);
    return () => { clearTimeout(t); setQuoting(false); };
  }, [artistId, eventCity]);

  // If the customer switches package after we already quoted, keep the
  // quote — the outstation status doesn't depend on package choice.

  if (data?.notFound) {
    return (
      <div>
        <SEO title="Artist Not Found" noindex path={`/artist/${id}`} />
        <Nav />
        <section className="section container" style={{ minHeight: "50vh", textAlign: "center", paddingTop: 80 }}>
          <div style={{ fontSize: 72 }}>🎤</div>
          <h1>Artist Not Found</h1>
          <Link to="/search" className="btn btn-gold">Browse all artists →</Link>
        </section>
</div>
    );
  }
  if (!data) return (
    <div>
      <Nav />
      <div className="loading"><div className="spinner" /></div>
    </div>
  );

  const { profile, packages, reviews, media, availability } = data;
  const galleryMedia = media.filter((m) => m.type === "gallery");
  const videoMedia = media.filter((m) => m.type === "video" || m.type === "reel");

  const isOutstation = !!quote?.is_outstation;
  const cityTouched = (eventCity || "").trim().length >= 2;
  const bookingBlocked =
    !cityTouched ||
    quoting ||
    !quote ||
    (isOutstation && !outstationAck);

  // Iter 73 — Location popup: instead of a hard alert("enter city first"),
  // opening the Book Now with no city shows a friendly modal that captures
  // it, auto-fills the sidebar city field, then resumes the flow.
  const startBooking = (overrideCity) => {
    const cityValue = (overrideCity ?? eventCity ?? "").trim();
    // Guard #1: venue must be entered — but instead of failing hard, open
    // the Location popup so the customer can supply it in-place.
    if (cityValue.length < 2) {
      setLocationPrompt({ open: true, value: eventCity || "" });
      return;
    }
    if (!quote && !overrideCity) {
      // Only require the pre-fetched quote when the city was already in
      // state (typed by the user). When we're resuming from the popup we
      // pass the new city → let the flow continue and re-quote inside
      // BookingFlow.
      alert("Fetching quote — please wait a moment.");
      return;
    }
    // Guard #2: outstation acknowledgement must be ticked for cross-city.
    if (isOutstation && !outstationAck && !overrideCity) {
      alert("Please accept the Outstation Terms to continue.");
      return;
    }
    // Guard #3: role checks.
    if (user?.role === "artist") { alert("Artists cannot book themselves"); return; }
    if (user?.role === "agency") { alert("Please log in as a Customer to book an artist."); return; }

    // Thread city + outstation-ack + pkg through to the booking flow so the
    // customer never has to re-enter them post-login.
    const qs = new URLSearchParams();
    if (selectedPkg?.id) qs.set("pkg", selectedPkg.id);
    qs.set("city", cityValue);
    if (isOutstation && !overrideCity) qs.set("outstation_ack", "1");
    const back = `/book/${artistId}?${qs.toString()}`;

    if (!user) {
      // Iter 70 — Show contextual login modal instead of jumping straight
      // to /login. Save intent to session storage so we can resume on the
      // same booking flow post-auth.
      try { sessionStorage.setItem("bt_post_login_redirect", back); } catch { /* ignore */ }
      setLoginGateReturnTo(back);
      setShowLoginGate(true);
      return;
    }
    nav(back);
  };

  // Iter 73 — Submit handler for the Location popup.
  const submitLocationPrompt = (e) => {
    e?.preventDefault();
    const city = (locationPrompt.value || "").trim();
    if (city.length < 2) return;
    // Update the sidebar city input so the customer never has to re-type
    // the same location again. useEffect on eventCity re-quotes.
    setEventCity(city);
    setLocationPrompt({ open: false, value: "" });
    // Continue Book Now with the freshly-entered city so guests hit the
    // LoginGate → login → back to /book/{id}?city=... flow immediately.
    // We pass `city` as override so we don't wait for the quote effect.
    setTimeout(() => startBooking(city), 30);
  };

  // Iter 71 — Guest-gated secondary actions.
  const toggleFavorite = secondaryGate.requireAuth(() => {
    try {
      const raw = localStorage.getItem(favoritesKey);
      const list = raw ? JSON.parse(raw) : [];
      const next = list.includes(artistId)
        ? list.filter((id) => id !== artistId)
        : [...list, artistId];
      localStorage.setItem(favoritesKey, JSON.stringify(next));
      setIsFavorite(next.includes(artistId));
      toast(next.includes(artistId) ? "Saved to favorites ★" : "Removed from favorites");
    } catch { /* ignore */ }
  }, {
    title: "Save this artist to your favorites",
    message: "Create a free BookTalent account to save artists you love and revisit them anytime.",
  });

  const messageArtist = secondaryGate.requireAuth(() => {
    // Chat unlocks only after a paid booking (business rule). Nudge the
    // customer to start the booking flow if they want to talk to the
    // artist directly.
    toast("Chat unlocks after you book & pay. Please Book Now to continue.");
  }, {
    title: "Sign in to contact this artist",
    message: "You'll need a free BookTalent account to message artists and confirm your booking.",
  });

  const handleAvailabilityPick = (dateStr) => {
    if (!user) {
      secondaryGate.promptLogin({
        title: "Sign in to check availability",
        message: "Create a free BookTalent account to reserve a date and start your booking.",
      });
      return;
    }
    // Logged-in customers → jump straight to booking flow with the date
    // pre-filled so they don't lose the click.
    if (user.role === "artist" || user.role === "agency") return;
    const qs = new URLSearchParams();
    if (selectedPkg?.id) qs.set("pkg", selectedPkg.id);
    if (eventCity.trim()) qs.set("city", eventCity.trim());
    if (dateStr) qs.set("date", dateStr);
    nav(`/book/${artistId}?${qs.toString()}`);
  };

  // ── SEO JSON-LD (Person + Offer for the cheapest package) ───────────
  const cheapestPkg = (packages || []).slice().sort((a, b) => (a.price || 0) - (b.price || 0))[0];
  const seoImg = profile.profile_image ? mediaUrl(profile.profile_image) : undefined;
  const seoPath = `/artist/${profile.slug || artistId}`;
  const personLd = {
    "@context": "https://schema.org",
    "@type": "Person",
    name: profile.stage_name,
    jobTitle: profile.category,
    address: { "@type": "PostalAddress", addressLocality: profile.city, addressCountry: "IN" },
    image: seoImg,
    url: `https://booktalent.com${seoPath}`,
    aggregateRating: profile.review_count > 0 ? {
      "@type": "AggregateRating",
      ratingValue: (profile.rating_avg || 0).toFixed(1),
      reviewCount: profile.review_count,
    } : undefined,
    ...(cheapestPkg ? { makesOffer: { "@type": "Offer", price: cheapestPkg.price, priceCurrency: "INR", name: cheapestPkg.name } } : {}),
  };

  return (
    <div data-testid="artist-profile-page">
      <SEO
        title={`Book ${profile.stage_name} — ${profile.category} in ${profile.city}`}
        description={`Book ${profile.stage_name}, a verified ${profile.category} from ${profile.city}. ${profile.review_count || 0} reviews · Starting ₹${profile.starting_price || cheapestPkg?.price || ""}. Check availability and packages on BookTalent.`}
        keywords={`book ${profile.stage_name}, ${profile.category} ${profile.city}, hire ${profile.category}, ${profile.category} for wedding`}
        image={seoImg}
        path={seoPath}
        jsonLd={[
          personLd,
          buildBreadcrumb([
            { name: "Home", url: "/" },
            { name: "Artists", url: "/search" },
            { name: profile.category, url: `/search?category=${encodeURIComponent(profile.category)}` },
            { name: profile.stage_name, url: seoPath },
          ]),
        ]}
      />
      <Nav />
      <div className="container" style={{ paddingTop: 24, paddingBottom: 60 }}>
        <div className="text-muted fs-12 mb-16">
          <Link to="/">Home</Link> › <Link to="/search">Artists</Link> › <Link to={`/search?category=${encodeURIComponent(profile.category)}`}>{profile.category}</Link> ›{" "}
          <span style={{ color: "var(--white)" }}>{profile.stage_name}</span>
        </div>

        <div style={{
          height: 280, borderRadius: 18,
          background: profile.cover_image
            ? `linear-gradient(180deg, rgba(9,9,18,0.2), rgba(9,9,18,0.7)), url(${mediaUrl(profile.cover_image)}?v=${profile.updated_at || ""}) center/cover`
            : "linear-gradient(135deg, #1A0B3B, #6D28D9)",
          display: "grid", placeItems: "center",
          fontSize: profile.cover_image ? 0 : 100,
          position: "relative", overflow: "hidden",
        }} data-testid="profile-cover-banner">
          {/* Iter 76.5 — Featured Reel: the artist's hero video plays
              muted + looped over the cover image. Falls back gracefully
              when no reel is set. */}
          {profile.featured_video_id && (
            <video
              data-testid="featured-reel-video"
              src={mediaUrl(profile.featured_video_id)}
              poster={`${api.defaults.baseURL}/media/${profile.featured_video_id}/thumb`}
              autoPlay muted loop playsInline preload="metadata"
              style={{
                position: "absolute", inset: 0, width: "100%", height: "100%",
                objectFit: "cover", zIndex: 0,
              }}
            />
          )}
          {!profile.cover_image && !profile.featured_video_id && (profile.emoji || "🎤")}
          <div style={{ position: "absolute", inset: 0, background: profile.featured_video_id ? "linear-gradient(180deg, rgba(9,9,18,0.15) 40%, rgba(9,9,18,0.75))" : (profile.cover_image ? "transparent" : "linear-gradient(180deg, transparent 40%, rgba(9,9,18,0.8))"), zIndex: 1 }} />
        </div>

        <div className="profile-header-row" data-testid="profile-header">
          <div
            className="avatar avatar-xl profile-header-avatar"
            style={{
              background: profile.profile_image
                ? `url(${mediaUrl(profile.profile_image)}?v=${profile.updated_at || ""}) center/cover`
                : "linear-gradient(135deg, var(--purple), var(--gold))",
              fontSize: profile.profile_image ? 0 : undefined,
            }}
            data-testid="profile-avatar"
          >
            {!profile.profile_image && (profile.emoji || "🎤")}
          </div>
          <div className="profile-header-info">
            <h1 className="font-serif profile-name" data-testid="artist-name">{profile.stage_name}</h1>
            <div
              className="font-serif fw-700"
              style={{
                fontSize: "clamp(22px, 3vw, 34px)",
                background: "linear-gradient(135deg, var(--gold-light, #F1D17A), var(--gold, #D4AF37))",
                WebkitBackgroundClip: "text",
                color: "transparent",
                letterSpacing: 0.3,
                marginTop: 4,
                marginBottom: 8,
                lineHeight: 1.1,
              }}
              data-testid="artist-profession"
            >
              {profile.category}
            </div>
            <div className="flex gap-8 items-center" style={{ flexWrap: "wrap" }}>
              {profile.kyc_status === "approved" && <span className="pill pill-green">✓ KYC Verified</span>}
              <span className="text-muted fs-13">📍 {profile.city}</span>
            </div>
          </div>
          <div className="profile-header-cta">
            <div className="pill pill-amber">⚡ Responds in ~2 hrs</div>
            <div className="text-muted fs-12 mt-8">{profile.profile_views} profile views</div>
          </div>
        </div>

        {/* Trust belt — icon-led, left-aligned stat cards. Each metric gets its
            own accent (gold/emerald/violet/bronze) so the eye can parse them in
            a glance. The rating card gets an extra tier badge when ≥ 4.5. */}
        <div className="artist-trust-belt mb-24" data-testid="artist-trust-belt">
          <div className="ats-card ats-rating" data-testid="stat-rating">
            <div className="ats-star-row" aria-label={`${profile.rating_avg.toFixed(1)} out of 5`}>
              {[0, 1, 2, 3, 4].map((i) => (
                <span key={i} className={`ats-star ${i < Math.round(profile.rating_avg) ? "on" : ""}`}>★</span>
              ))}
            </div>
            <div className="ats-value font-serif" data-testid="stat-rating-value">{profile.rating_avg.toFixed(1)}</div>
            <div className="ats-label">
              Rating
              {profile.rating_avg >= 4.5 && profile.review_count >= 5 && (
                <span className="ats-tier" data-testid="stat-rating-tier">Elite · Top&nbsp;5%</span>
              )}
            </div>
            <span className="ats-shine" aria-hidden />
          </div>

          <div className="ats-card ats-reviews" data-testid="stat-reviews">
            <div className="ats-icon">💬</div>
            <div className="ats-value font-serif">{profile.review_count}</div>
            <div className="ats-label">Verified Reviews</div>
            <span className="ats-shine" aria-hidden />
          </div>

          <div className="ats-card ats-events" data-testid="stat-events">
            <div className="ats-icon">🎉</div>
            <div className="ats-value font-serif">{profile.events_done}</div>
            <div className="ats-label">Events Done</div>
            <span className="ats-shine" aria-hidden />
          </div>

          <div className="ats-card ats-exp" data-testid="stat-experience">
            <div className="ats-icon">🏆</div>
            <div className="ats-value font-serif">
              {profile.experience_years || 8}
              <span className="ats-value-unit">yrs</span>
            </div>
            <div className="ats-label">On&nbsp;Stage</div>
            <span className="ats-shine" aria-hidden />
          </div>
        </div>

        <div className="profile-main-grid">
          <div>
            <div className="tab-bar" data-testid="profile-tabs">
              {["about", "media", "packages", "availability", "reviews"].map((t) => (
                <button key={t} className={`tab-btn ${tab === t ? "active" : ""}`} onClick={() => setTab(t)} data-testid={`tab-${t}`}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>

            {tab === "about" && (
              <div className="card card-pad" data-testid="tab-about-content">
                <h3 className="card-title mb-16">About {profile.stage_name.split(" ")[0]}</h3>
                <p style={{ fontSize: 14, lineHeight: 1.7, color: "var(--white-muted)", marginBottom: 24 }}>
                  {profile.bio || "No bio yet."}
                </p>
                <div className="divider" />
                <div className="grid grid-2 mt-16">
                  <div style={{ background: "var(--glass)", borderRadius: 10, padding: 14 }}>
                    <div className="text-muted fs-11 mb-4">LANGUAGES</div>
                    <div className="fs-13">{(profile.languages || []).join(" · ") || "—"}</div>
                  </div>
                  <div style={{ background: "var(--glass)", borderRadius: 10, padding: 14 }}>
                    <div className="text-muted fs-11 mb-4">GENRES</div>
                    <div className="fs-13">{(profile.genres || []).join(" · ") || "—"}</div>
                  </div>
                  <div style={{ background: "var(--glass)", borderRadius: 10, padding: 14 }}>
                    <div className="text-muted fs-11 mb-4">EVENT TYPES</div>
                    <div className="fs-13">{(profile.event_types || []).join(" · ") || "Weddings · Corporate · Concerts"}</div>
                  </div>
                  <div style={{ background: "var(--glass)", borderRadius: 10, padding: 14 }}>
                    <div className="text-muted fs-11 mb-4">TRAVEL</div>
                    <div className="fs-13">{profile.travel_range || "Pan India"}</div>
                  </div>
                </div>
                {/* Iter 55 — Questionnaire-driven details, grouped by section. */}
                <QuestionnairePanel about={about} onMediaClick={() => setTab("media")} />
              </div>
            )}

            {tab === "media" && (
              <div className="card card-pad" data-testid="tab-media-content">
                <h3 className="card-title mb-16">Performance Gallery</h3>
                {media.length === 0 ? (
                  <div className="empty"><div className="empty-icon">📷</div><div className="empty-title">No media yet</div></div>
                ) : (() => {
                  const viewable = media.filter((m) => m.type !== "kyc");
                  const items = viewable.map((m) => ({
                    id: m.id,
                    src: `${api.defaults.baseURL}/media/${m.id}`,
                    isVideo: m.mime?.startsWith("video/"),
                    title: m.title || "",
                  }));
                  return (
                    <div className="media-grid">
                      {items.map((it, i) => (
                        <button
                          key={it.id}
                          type="button"
                          className="media-tile"
                          data-testid={`media-${it.id}`}
                          onClick={() => setLightbox({ items, idx: i })}
                          aria-label={`Open ${it.isVideo ? "video" : "image"} ${i + 1} of ${items.length}`}
                        >
                          {it.isVideo ? <video src={it.src} muted /> : <img src={it.src} alt={it.title} />}
                          <span className="media-tile-play" aria-hidden>{it.isVideo ? "▶" : "⤢"}</span>
                        </button>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}

            {tab === "packages" && (
              <div className="card card-pad" data-testid="tab-packages-content">
                <h3 className="card-title mb-16">Pricing Packages</h3>
                <div className="grid grid-3">
                  {packages.map((p) => (
                    <div key={p.id} className={`pkg-card ${p.is_popular ? "popular" : ""}`} data-testid={`package-card-${p.id}`}>
                      {p.is_popular && <span className="popular-tag">★ MOST POPULAR</span>}
                      <div className="pkg-name">{p.name}</div>
                      <div className="text-muted fs-12 mb-12">⏱ {p.duration}</div>
                      <div className="pkg-price">{fmtINRFull(p.price)} <span style={{ fontSize: 12, color: "var(--white-muted)", fontWeight: 400 }}>/event</span></div>
                      <ul className="pkg-features">{p.features.map((f, i) => <li key={`${p.id}-f-${i}-${f}`}>{f}</li>)}</ul>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "availability" && (
              <div data-testid="tab-availability-content">
                <div style={{ marginBottom: 12, color: "var(--white-muted)", fontSize: 13 }}>
                  🗓️ Pick a date to check {profile.stage_name.split(" ")[0]}'s live availability. Dates in red are already booked or blocked.
                </div>
                <AvailabilityCalendar artistUserId={profile.user_id} onPick={handleAvailabilityPick} />
              </div>
            )}

            {tab === "reviews" && (
              <div className="card card-pad" data-testid="tab-reviews-content">
                <div className="flex gap-24 mb-24">
                  <div className="text-center">
                    <div className="font-serif" style={{ fontSize: 56, fontWeight: 700, color: "var(--gold-light)", lineHeight: 1 }}>{profile.rating_avg.toFixed(1)}</div>
                    <div className="text-gold mt-8" style={{ letterSpacing: 3 }}>★★★★★</div>
                    <div className="text-muted fs-12 mt-4">{profile.review_count} reviews</div>
                  </div>
                </div>
                {reviews.length === 0 ? (
                  <div className="empty"><div className="empty-icon">⭐</div><div className="empty-title">No reviews yet</div></div>
                ) : reviews.map((r) => (
                  <div key={r.id} style={{ padding: 16, borderBottom: "1px solid var(--glass-border)" }} data-testid={`review-${r.id}`}>
                    <div className="flex items-center gap-12 mb-8">
                      <div className="avatar">{r.customer_name?.[0] || "U"}</div>
                      <div style={{ flex: 1 }}>
                        <div className="fw-600 fs-14">{r.customer_name}</div>
                        <div className="text-muted fs-11">{r.event_type}</div>
                      </div>
                      <div className="text-gold">{"★".repeat(r.rating)}</div>
                    </div>
                    <div className="fs-13" style={{ color: "var(--white-muted)", lineHeight: 1.7 }}>{r.text}</div>
                    {r.reply && (
                      <div style={{ marginTop: 12, padding: 12, background: "rgba(109,40,217,0.08)", borderRadius: 10 }}>
                        <div className="text-muted fs-11 mb-4">Reply from {profile.stage_name}:</div>
                        <div className="fs-13">{r.reply}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div data-testid="booking-sidebar">
            <div className="card card-pad" style={{ position: "sticky", top: 90 }}>
              {selectedPkg && (() => {
                // Resolve the price the customer should see:
                //   • no venue yet → package base price ("Starting price")
                //   • quote in flight OR no quote → still base
                //   • quote arrived → outstation-adjusted `quoted_price` from
                //     the matching package in the /quote response
                const quotedPkg = quote?.packages?.find((p) => p.id === selectedPkg.id);
                const displayPrice = quotedPkg?.quoted_price ?? selectedPkg.price;
                const surcharge = quote?.outstation_surcharge_pct || 0;
                return (
                <>
                  <div className="font-serif" style={{ fontSize: 32, fontWeight: 700, color: "var(--gold-light)" }}>
                    {fmtINRFull(displayPrice)}
                  </div>
                  <div className="text-muted fs-12 mb-16" data-testid="artist-price-label">
                    {isOutstation && surcharge > 0
                      ? <>Outstation quote · {selectedPkg.name} <span className="text-gold">(+{surcharge}%)</span></>
                      : <>Starting price · {selectedPkg.name}</>}
                  </div>

                  {/* Venue-first prompt (Iter 52.6) — must be filled before Book Now */}
                  <div className="field venue-first-field">
                    <div className="field-label">
                      📍 Where's your event?
                      <span className="fs-11 text-muted" style={{ fontWeight: 400, marginLeft: 6 }}>required</span>
                    </div>
                    <input
                      className="field-input"
                      type="text"
                      placeholder="e.g. Mumbai, Delhi, Bengaluru…"
                      value={eventCity}
                      onChange={(e) => setEventCity(e.target.value)}
                      autoComplete="address-level2"
                      data-testid="venue-first-input"
                    />
                    {cityTouched && quoting && (
                      <div className="text-muted fs-11 mt-4">Checking availability & pricing…</div>
                    )}
                    {cityTouched && quote && !quoting && (
                      <div className={`venue-status-chip ${isOutstation ? "outstation" : "local"}`} data-testid="venue-status-chip">
                        {isOutstation
                          ? <>🌍 <span>Outstation booking · Artist based in {quote.artist_city}</span></>
                          : <>🟢 <span>Local booking · Same city as artist</span></>}
                      </div>
                    )}
                  </div>

                  <div className="field">
                    <div className="field-label">Package</div>
                    <select className="field-input" value={selectedPkg.id} onChange={(e) => setSelectedPkg(packages.find(p => p.id === e.target.value))} data-testid="pkg-select">
                      {packages.map((p) => {
                        const qp = quote?.packages?.find((x) => x.id === p.id);
                        const price = qp?.quoted_price ?? p.price;
                        return <option key={p.id} value={p.id}>{p.name} — {fmtINRFull(price)}</option>;
                      })}
                    </select>
                  </div>

                  {/* Outstation Terms — only rendered when the venue quote flags outstation */}
                  {isOutstation && quote?.outstation_notice && (
                    <div className="venue-outstation-card" data-testid="venue-outstation-card">
                      <div className="fw-700 text-gold fs-12 mb-6" style={{ letterSpacing: ".08em", textTransform: "uppercase" }}>
                        📢 Outstation Terms
                      </div>
                      <div className="fs-12 mb-8" style={{ lineHeight: 1.5 }}>{quote.outstation_notice}</div>
                      <label className="flex items-start gap-8" style={{ cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={outstationAck}
                          onChange={(e) => setOutstationAck(e.target.checked)}
                          data-testid="venue-outstation-ack"
                          style={{ marginTop: 3, flex: "none" }}
                        />
                        <span className="fs-12">
                          I understand and agree to arrange all outstation logistics (travel, stay, meals, local transport) directly with the artist.
                        </span>
                      </label>
                    </div>
                  )}

                  {/* Detailed rider — sourced from the artist's onboarding questionnaire.
                      Rendered only for outstation quotes so local bookings aren't cluttered. */}
                  {isOutstation && quote?.rider && (
                    <TravelRiderCard
                      rider={quote.rider}
                      artistCity={quote.artist_city}
                      eventCity={quote.event_city}
                      compact
                    />
                  )}

                  <button
                    className="btn btn-gold btn-block"
                    onClick={() => startBooking()}
                    data-testid="confirm-booking-btn"
                    title={bookingBlocked && cityTouched ? "Fill the fields above to unlock" : undefined}
                  >
                    🔐 Book Now
                  </button>

                  {/* Iter 71 — Secondary actions with LoginGate for guests. */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={toggleFavorite}
                      data-testid="favorite-artist-btn"
                      aria-pressed={isFavorite}
                      style={{
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                        color: isFavorite ? "#ff6b81" : undefined,
                        borderColor: isFavorite ? "rgba(255,107,129,0.5)" : undefined,
                      }}
                    >
                      <Heart size={14} fill={isFavorite ? "#ff6b81" : "none"} />
                      {isFavorite ? "Saved" : "Favorite"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={messageArtist}
                      data-testid="message-artist-btn"
                      style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                    >
                      <MessageCircle size={14} /> Message
                    </button>
                  </div>
                  {!cityTouched && (
                    <div className="text-muted fs-11 mt-8" style={{ textAlign: "center" }}>
                      Enter your event city above to unlock booking
                    </div>
                  )}
                  <div style={{ marginTop: 16, fontSize: 12, color: "var(--white-muted)" }}>
                    <div style={{ padding: "8px 0" }}>✓ Auto-generated legal contract</div>
                    <div style={{ padding: "8px 0" }}>✓ Direct payment to artist as per agreement</div>
                    <div style={{ padding: "8px 0" }}>✓ Free cancellation within 24 hrs</div>
                    <div style={{ padding: "8px 0" }}>✓ GST invoice included</div>
                  </div>
                </>
                );
              })()}
            </div>
          </div>
        </div>
      </div>
      {selectedPkg && (
        <div className="mobile-book-bar" data-testid="mobile-book-bar">
          <div className="mobile-book-bar-price">
            <div className="mobile-book-bar-label">Starting from</div>
            <div className="mobile-book-bar-amount">{fmtINRFull(selectedPkg.price)}</div>
          </div>
          <button
            type="button"
            className="btn btn-gold mobile-book-bar-cta"
            onClick={startBooking}
            data-testid="mobile-book-bar-btn"
          >
            🔐 Book Now
          </button>
        </div>
      )}
      {lightbox && (
        <MediaCarousel lightbox={lightbox} onClose={() => setLightbox(null)} onChange={setLightbox} />
      )}
      <LoginGate
        open={showLoginGate}
        onClose={() => setShowLoginGate(false)}
        title="Login to book this artist"
        message="You'll need a free BookTalent account to check availability and confirm your booking. We'll bring you right back here after."
        returnTo={loginGateReturnTo}
      />
      {/* Iter 71 — Secondary gate for Favorite / Message / Availability picks. */}
      {secondaryGate.gate}
      {/* Iter 73 — Location popup: opens when a guest / customer clicks
          Book Now without a city typed. Filling it here auto-updates the
          sidebar city input AND resumes the Book Now flow immediately. */}
      {locationPrompt.open && (
        <div
          data-testid="location-prompt-backdrop"
          onClick={() => setLocationPrompt({ open: false, value: locationPrompt.value })}
          style={{
            position: "fixed", inset: 0, zIndex: 500,
            background: "rgba(4,6,20,0.72)", backdropFilter: "blur(10px)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 16,
          }}
        >
          <form
            data-testid="location-prompt"
            onClick={(e) => e.stopPropagation()}
            onSubmit={submitLocationPrompt}
            style={{
              width: 440, maxWidth: "100%",
              background: "linear-gradient(180deg, #16172B, #0F0F1B)",
              border: "1px solid rgba(212,175,55,0.35)",
              borderRadius: 20, padding: "26px 24px 22px",
              color: "#F0EEFF",
              boxShadow: "0 24px 64px -12px rgba(0,0,0,0.75)",
            }}
          >
            <div style={{ fontSize: 26, marginBottom: 10 }}>📍</div>
            <h3 style={{
              fontFamily: "'Cormorant Garamond', serif",
              fontSize: 24, fontWeight: 700, margin: "0 0 6px",
            }}>
              Where's your event?
            </h3>
            <p style={{ fontSize: 13, lineHeight: 1.55, color: "rgba(240,238,255,0.7)", margin: "0 0 16px" }}>
              Tell us your event city so we can quote the right price — Mumbai, Delhi, Bengaluru, etc. We'll auto-fill this for you and continue.
            </p>
            <input
              autoFocus
              type="text"
              className="field-input"
              placeholder="e.g. Mumbai, Delhi, Bengaluru…"
              value={locationPrompt.value}
              onChange={(e) => setLocationPrompt((p) => ({ ...p, value: e.target.value }))}
              data-testid="location-prompt-input"
              style={{ width: "100%", marginBottom: 14 }}
            />
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                type="button"
                className="btn btn-ghost"
                data-testid="location-prompt-cancel"
                onClick={() => setLocationPrompt({ open: false, value: "" })}
              >Cancel</button>
              <button
                type="submit"
                className="btn btn-gold"
                data-testid="location-prompt-continue"
                disabled={(locationPrompt.value || "").trim().length < 2}
              >Continue to Book →</button>
            </div>
          </form>
        </div>
      )}
</div>
  );
}


// ─── Swipeable / keyboard-navigable media carousel ─────────────────────
function MediaCarousel({ lightbox, onClose, onChange }) {
  const { items, idx } = lightbox;
  const total = items.length;
  const current = items[idx];
  const touchRef = React.useRef({ x: 0, active: false });

  const goPrev = React.useCallback(() => {
    if (total < 2) return;
    onChange({ items, idx: (idx - 1 + total) % total });
  }, [items, idx, total, onChange]);

  const goNext = React.useCallback(() => {
    if (total < 2) return;
    onChange({ items, idx: (idx + 1) % total });
  }, [items, idx, total, onChange]);

  // Keyboard: ← → for nav, Esc for close
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "ArrowRight") goNext();
      else if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goPrev, goNext, onClose]);

  // Preload neighbours to make swipe feel instant
  React.useEffect(() => {
    if (total < 2) return;
    [1, -1].forEach((d) => {
      const n = items[(idx + d + total) % total];
      if (n && !n.isVideo) { const im = new Image(); im.src = n.src; }
    });
  }, [idx, items, total]);

  const onTouchStart = (e) => { touchRef.current = { x: e.touches[0].clientX, active: true }; };
  const onTouchEnd = (e) => {
    if (!touchRef.current.active) return;
    const dx = (e.changedTouches[0]?.clientX ?? touchRef.current.x) - touchRef.current.x;
    touchRef.current.active = false;
    if (Math.abs(dx) < 40) return;
    if (dx > 0) goPrev(); else goNext();
  };

  return (
    <div
      className="media-lightbox"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      data-testid="media-lightbox"
    >
      <button
        type="button"
        className="media-lightbox-close"
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        aria-label="Close viewer"
        data-testid="media-lightbox-close"
      >×</button>

      {total > 1 && (
        <>
          <button
            type="button"
            className="media-lightbox-nav prev"
            onClick={(e) => { e.stopPropagation(); goPrev(); }}
            aria-label="Previous"
            data-testid="media-lightbox-prev"
          >‹</button>
          <button
            type="button"
            className="media-lightbox-nav next"
            onClick={(e) => { e.stopPropagation(); goNext(); }}
            aria-label="Next"
            data-testid="media-lightbox-next"
          >›</button>
        </>
      )}

      <div
        className="media-lightbox-content"
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        {current.isVideo ? (
          <video
            key={current.id}
            src={current.src}
            controls
            autoPlay
            playsInline
            data-testid="media-lightbox-video"
          />
        ) : (
          <img
            key={current.id}
            src={current.src}
            alt={current.title}
            data-testid="media-lightbox-image"
          />
        )}
        {(current.title || total > 1) && (
          <div className="media-lightbox-title">
            {current.title}
            {total > 1 && <span className="media-lightbox-counter"> · {idx + 1} / {total}</span>}
          </div>
        )}
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────────
// Iter 55 — QuestionnairePanel
// Renders every non-empty answer from the artist's onboarding questionnaire
// in a customer-friendly way, grouped by the "section" hint the question
// declared (Travel, Hospitality, Sound, etc.). Photo / video question
// answers are NOT rendered inline — instead we surface a "See gallery" chip
// that switches to the Media tab, so uploads always live in one place.
// ─────────────────────────────────────────────────────────────────────────
const MEDIA_TYPES = new Set(["photo", "photos", "video", "videos", "media", "attachment", "file", "image"]);

function formatAnswer(a) {
  const v = a.answer;
  if (a.type === "toggle" || typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length === 0 ? "—" : v.join(" · ");
  if (typeof v === "object" && v !== null) {
    return Object.entries(v)
      .filter(([, val]) => val !== null && val !== "" && val !== false)
      .map(([k, val]) => `${k}: ${Array.isArray(val) ? val.join(", ") : val}`)
      .join(" · ");
  }
  return String(v);
}

function QuestionnairePanel({ about, onMediaClick }) {
  if (!about) return null;
  const all = [...(about.universal || []), ...(about.category || [])];
  if (all.length === 0) return null;

  // Split media-type answers so we can point customers to the Media tab.
  const mediaAnswers = all.filter((a) => MEDIA_TYPES.has((a.type || "").toLowerCase()));
  const nonMedia = all.filter((a) => !MEDIA_TYPES.has((a.type || "").toLowerCase()));
  // Iter 56 — Backend attaches the newest matching media asset per media-type
  // answer so we can render thumbnail chips instead of a generic hint.
  const mediaMatches = about.media_matches || [];
  const matchByQid = Object.fromEntries(mediaMatches.map((m) => [m.question_id, m]));

  // Group by section (fall back to "Details").
  const bySection = {};
  for (const a of nonMedia) {
    const s = a.section || "Details";
    (bySection[s] = bySection[s] || []).push(a);
  }
  // Preserve a sensible ordering: Travel, Hospitality, Sound, Technical,
  // Availability, then everything else alphabetically.
  const ORDER = ["Travel", "Hospitality", "Sound", "Technical", "Availability", "Preferences", "Performance", "Details"];
  const sections = Object.keys(bySection).sort((a, b) => {
    const ai = ORDER.indexOf(a), bi = ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  return (
    <div className="qa-panel" data-testid="qa-panel" style={{ marginTop: 26 }}>
      <div className="divider" style={{ margin: "6px 0 20px" }} />
      <h3 className="card-title mb-16" style={{ fontSize: 18 }}>Rider &amp; Preferences</h3>
      <div style={{ fontSize: 12, color: "var(--white-muted)", marginBottom: 14 }}>
        Auto-generated from {about.universal.length + about.category.length} questionnaire answers this artist submitted.
      </div>

      {sections.map((s) => (
        <div key={s} className="qa-section" data-testid={`qa-section-${s.toLowerCase()}`} style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--gold-light)", textTransform: "uppercase", marginBottom: 10 }}>{s}</div>
          <div className="grid grid-2" style={{ gap: 10 }}>
            {bySection[s].map((a) => (
              <div key={a.id} style={{ background: "var(--glass)", borderRadius: 10, padding: "12px 14px", border: "1px solid var(--glass-border)" }} data-testid={`qa-item-${a.id}`}>
                <div className="text-muted fs-11 mb-4">{a.question.toUpperCase()}</div>
                <div className="fs-13" style={{ lineHeight: 1.5 }}>{formatAnswer(a)}</div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {mediaAnswers.length > 0 && (
        <div className="qa-media-section" data-testid="qa-media-section" style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, letterSpacing: ".16em", color: "var(--gold-light)", textTransform: "uppercase", marginBottom: 10 }}>Media Attachments</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
            {mediaAnswers.map((a) => {
              const m = matchByQid[a.id];
              const isMissing = !m;
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={onMediaClick}
                  data-testid={isMissing ? `qa-media-missing-${a.id}` : `qa-media-chip-${a.id}`}
                  className={`qa-media-chip ${isMissing ? "qa-media-chip-missing" : ""}`}
                  title={isMissing ? "Not uploaded — ask the artist to add this to their gallery" : `View ${a.question} in the artist's gallery`}
                  style={{
                    display: "flex", gap: 10, alignItems: "center",
                    background: isMissing ? "rgba(255,255,255,0.02)" : "var(--glass)",
                    border: `1px ${isMissing ? "dashed" : "solid"} ${isMissing ? "rgba(255,255,255,0.15)" : "var(--glass-border)"}`,
                    borderRadius: 10, padding: 8, cursor: "pointer",
                    color: "inherit", textAlign: "left", font: "inherit",
                    transition: "transform 0.15s, border-color 0.2s",
                    opacity: isMissing ? 0.85 : 1,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = isMissing ? "rgba(246,211,102,0.4)" : "rgba(246,211,102,0.5)"; e.currentTarget.style.transform = "translateY(-2px)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = isMissing ? "rgba(255,255,255,0.15)" : "var(--glass-border)"; e.currentTarget.style.transform = "translateY(0)"; }}
                >
                  {m ? (
                    m.mime && m.mime.startsWith("video") ? (
                      <div style={{ width: 56, height: 56, borderRadius: 8, background: "rgba(0,0,0,0.5)", display: "grid", placeItems: "center", flexShrink: 0, fontSize: 22 }}>▶️</div>
                    ) : (
                      <img
                        src={thumbUrl(m.media_id)}
                        alt=""
                        onError={(e) => { e.currentTarget.style.display = "none"; }}
                        style={{ width: 56, height: 56, borderRadius: 8, objectFit: "cover", flexShrink: 0 }}
                      />
                    )
                  ) : (
                    <div style={{
                      width: 56, height: 56, borderRadius: 8,
                      background: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03), rgba(255,255,255,0.03) 4px, rgba(255,255,255,0.06) 4px, rgba(255,255,255,0.06) 8px)",
                      display: "grid", placeItems: "center", flexShrink: 0,
                      fontSize: 22, color: "rgba(255,255,255,0.4)",
                    }}>❓</div>
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="fs-12 fw-600" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.question}</div>
                    <div style={{ marginTop: 2, fontSize: 11, color: isMissing ? "rgba(246,211,102,0.85)" : "var(--white-muted)" }}>
                      {isMissing ? "Ask artist for this →" : "View in gallery →"}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
