import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import SEO from "../components/SEO";
import api, { fmtINRFull, mediaUrl, pickArtistThumb } from "../lib/api";
import ArtistCardThumb from "../components/ArtistCardThumb";

const CATEGORIES = [
  { slug: "all", name: "All", icon: "✨" },
  { slug: "Bollywood Vocalist", name: "Singers", icon: "🎤" },
  { slug: "DJ / Music Producer", name: "DJs", icon: "🎧" },
  { slug: "Stand-up Comedian", name: "Comedians", icon: "🎭" },
  { slug: "Dancer", name: "Dancers", icon: "💃" },
  { slug: "Anchor", name: "Anchors", icon: "🎙️" },
];

const CAT_TILES = [
  { slug: "singer",     icon: "🎤",  name: "Singers & Vocalists",   count: "840" },
  { slug: "dj",         icon: "🎧",  name: "DJs & Music Producers",  count: "620" },
  { slug: "comedian",   icon: "🎭",  name: "Stand-up Comedians",     count: "310" },
  { slug: "anchor",     icon: "🎙️", name: "Anchors & Emcees",       count: "490" },
  { slug: "dancer",     icon: "💃",  name: "Dancers & Troupes",      count: "380" },
  { slug: "magician",   icon: "🪄",  name: "Magicians & Illusionists", count: "120" },
  { slug: "band",       icon: "🎻",  name: "Live Bands & Orchestras", count: "240" },
  { slug: "celebrity",  icon: "🌟",  name: "Celebrity Performers",    count: "95"  },
];

const CITY_TILES = [
  { slug: "mumbai",    icon: "🏙️", name: "Mumbai",       count: "1,200" },
  { slug: "delhi",     icon: "🏛️", name: "Delhi / NCR",  count: "980"   },
  { slug: "bangalore", icon: "🌿",  name: "Bangalore",    count: "740"   },
  { slug: "chennai",   icon: "🌊",  name: "Chennai",      count: "510"   },
  { slug: "hyderabad", icon: "💎",  name: "Hyderabad",    count: "630"   },
  { slug: "kolkata",   icon: "🎨",  name: "Kolkata",      count: "420"   },
];

const TESTIMONIALS = [
  { stars: 5, quote: "Booked a Bollywood singer for our daughter's wedding through BookTalent. The entire process — from discovery to booking to performance — was absolutely flawless. Truly the Airbnb for talent.", name: "Rajesh Khanna", role: "Wedding Planner, Mumbai", initials: "RK", avatarClass: "tav1" },
  { stars: 5, quote: "We've used BookTalent for three corporate annual functions. The quality of artists and transparent 5% platform fee gives us full confidence. Our go-to platform for talent bookings.", name: "Ananya Patel", role: "HR Manager, TechCorp India", initials: "AP", avatarClass: "tav2" },
  { stars: 5, quote: "As an artist, BookTalent changed my life. I went from struggling to find gigs to being fully booked 3 months in advance. Direct settlement with clients keeps things simple.", name: "Siddharth Mehta", role: "DJ & Music Producer, Delhi", initials: "SM", avatarClass: "tav3" },
];

const HOW_STEPS = [
  { num: "01", icon: "🔍", title: "Discover & Filter", desc: "Use AI-powered search or browse by category, city, budget and event type. Compare profiles, videos and reviews." },
  { num: "02", icon: "📅", title: "Check Availability", desc: "View the artist's real-time calendar, select your date and get an instant quote — transparent pricing with no hidden fees." },
  { num: "03", icon: "🤝", title: "Confirm Booking", desc: "Pay just the 5% Platform Service Fee (+ 18% GST) to lock the artist. Artist Performance Fee is settled directly with the artist." },
  { num: "04", icon: "✨", title: "Enjoy the Show", desc: "Artist performs, you approve completion, and reviews go live. Everything is protected by our written booking agreement." },
];

export default function Landing() {
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [rails, setRails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cities, setCities] = useState([]);
  const [featuredFaqs, setFeaturedFaqs] = useState([]);
  const [openFaq, setOpenFaq] = useState({});
  const [spotlight, setSpotlight] = useState({ cards: [], latest_booking: null });
  const [spotIdx, setSpotIdx] = useState(0);
  const [myCity, setMyCity] = useState("");
  const [catStats, setCatStats] = useState({});
  // Iter 46 — homepage advanced search (date + city + category)
  const [advDate, setAdvDate] = useState("");
  const [advCategory, setAdvCategory] = useState("");

  useEffect(() => {
    // Sprint 5 — dynamic homepage rails
    const geo = localStorage.getItem("bt_city") || "";
    if (geo) setMyCity(geo);
    api.get(`/homepage/sections?limit=8${geo ? `&city=${encodeURIComponent(geo)}` : ""}`).then((r) => {
      setRails(r.data || []);
    }).catch(() => setRails([])).finally(() => setLoading(false));
    api.get("/cities").then(r => setCities(r.data));
    api.get("/faqs/search?featured=true").then(r => setFeaturedFaqs(r.data || [])).catch(() => {});
    api.get("/homepage/spotlight").then(r => setSpotlight(r.data || { cards: [] })).catch(() => {});
    // Iter 45 — city-scoped category counts (for "local hot" highlight)
    api.get(`/homepage/category-stats${geo ? `?city=${encodeURIComponent(geo)}` : ""}`)
      .then(r => setCatStats(r.data?.counts || {})).catch(() => {});
    // Iter 44 — auto-detect visitor's city (best-effort, browser timezone)
    if (!geo) {
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
        const guess = tz.split("/").pop() || "";
        if (guess) setMyCity(guess.replace(/_/g, " "));
      } catch (_) { /* noop */ }
    }
  }, []);

  // Iter 45 — send an impression for each spotlight card shown (deduped by
  // per-session key + per-day on the backend, so rotation doesn't inflate).
  useEffect(() => {
    if (!spotlight.cards || spotlight.cards.length === 0) return;
    let sess = localStorage.getItem("bt_session");
    if (!sess) {
      sess = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem("bt_session", sess);
    }
    spotlight.cards.forEach((c) => {
      if (c.user_id) {
        api.post("/homepage/spotlight/impression", { user_id: c.user_id, session: sess })
          .catch(() => {});
      }
    });
  }, [spotlight.cards]);

  // Auto-rotate the hero spotlight cards every 8s.
  useEffect(() => {
    if (!spotlight.cards || spotlight.cards.length <= 3) return;
    const t = setInterval(() => {
      setSpotIdx((i) => (i + 1) % spotlight.cards.length);
    }, 5000);
    return () => clearInterval(t);
  }, [spotlight.cards]);

  // 3 rotating cards derived from the spotlight pool.
  const visibleSpotlight = (() => {
    const arr = spotlight.cards || [];
    if (arr.length <= 3) return arr;
    return [arr[spotIdx % arr.length], arr[(spotIdx + 1) % arr.length], arr[(spotIdx + 2) % arr.length]];
  })();

  const search = (e) => {
    e?.preventDefault();
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (city) {
      p.set("city", city);
      localStorage.setItem("bt_city", city);
    }
    if (advDate) p.set("date", advDate);
    if (advCategory) p.set("category", advCategory);
    window.location.href = `/search?${p.toString()}`;
  };

  return (
    <div data-testid="landing-page">
      <SEO
        title="Book India's Finest Talent, On Demand"
        description="Book verified singers, DJs, comedians, dancers and anchors for weddings, corporate events, birthdays and private parties. Transparent 5% platform fee, direct settlement with your artist."
        keywords="book artists india, book singer, book DJ, book comedian, wedding entertainment, corporate event artists, book anchor, book dancer"
        path="/"
        jsonLd={{
          "@context": "https://schema.org",
          "@type": "WebSite",
          name: "BookTalent",
          url: "https://booktalent.com",
          potentialAction: {
            "@type": "SearchAction",
            target: "https://booktalent.com/search?q={search_term_string}",
            "query-input": "required name=search_term_string",
          },
        }}
      />
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="orb orb-3" />
      <Nav />

      <section className="hero hero-split" data-testid="hero-split">
        <div className="hero-left">
          <div className="hero-tag">✦ India's #1 Premium Talent Marketplace</div>
          <h1>
            India's<br/>
            <span className="gold-grad">Finest Talent,</span><br/>
            <span className="italic">On Demand</span>
          </h1>
          <p className="hero-sub" style={{ maxWidth: 520 }}>
            Discover, compare and instantly book singers, DJs, comedians, anchors and 5000+ verified artists for weddings, corporate events, concerts and private shows.
          </p>
          <Link to="/planner" className="hero-planner-strip" data-testid="hero-planner-strip">
            <span className="hero-planner-emoji">✨</span>
            <span className="hero-planner-body">
              <span className="hero-planner-title">Try the AI Event Planner</span>
              <span className="hero-planner-sub">Get a curated artist line-up in seconds, then add all to cart in one tap</span>
            </span>
            <span className="hero-planner-arrow">→</span>
          </Link>
          <div className="hero-cta-row" data-testid="hero-cta-row">
            <Link to="/search" className="btn btn-gold btn-lg" data-testid="hero-cta-browse">
              ✦ Browse Artists
            </Link>
            <Link to="/signup?role=artist" className="btn btn-ghost btn-lg" data-testid="hero-cta-list">
              List as Artist
            </Link>
          </div>
          <div className="hero-adv-search" data-testid="hero-adv-search">
            <div className="hero-adv-field">
              <label htmlFor="hero-adv-date">Event Date</label>
              <input
                id="hero-adv-date"
                type="date"
                value={advDate}
                onChange={(e) => setAdvDate(e.target.value)}
                min={new Date().toISOString().split("T")[0]}
                data-testid="hero-adv-date"
              />
            </div>
            <div className="hero-adv-field">
              <label htmlFor="hero-adv-city">City</label>
              <input
                id="hero-adv-city"
                type="text"
                list="hero-city-list"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="Any city"
                autoComplete="off"
                data-testid="hero-adv-city"
              />
              <datalist id="hero-city-list">
                {cities.map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div className="hero-adv-field">
              <label htmlFor="hero-adv-category">Artist Type</label>
              <input
                id="hero-adv-category"
                type="text"
                list="hero-cat-list"
                value={advCategory}
                onChange={(e) => setAdvCategory(e.target.value)}
                placeholder="Any category"
                autoComplete="off"
                data-testid="hero-adv-category"
              />
              <datalist id="hero-cat-list">
                {CATEGORIES.filter((c) => c.slug !== "all").map((c) => (
                  <option key={c.slug} value={c.slug}>{c.name}</option>
                ))}
              </datalist>
            </div>
            <button
              type="button"
              className="btn btn-gold hero-adv-btn"
              onClick={search}
              data-testid="hero-adv-search-btn"
            >
              Find Artists →
            </button>
          </div>
          <div className="hero-stats">
            <div>
              <div className="hero-stat-num">5,200+</div>
              <div className="hero-stat-label">Verified Artists</div>
            </div>
            <div>
              <div className="hero-stat-num">48K+</div>
              <div className="hero-stat-label">Events Booked</div>
            </div>
            <div>
              <div className="hero-stat-num">32</div>
              <div className="hero-stat-label">Cities Covered</div>
            </div>
          </div>
        </div>

        <div className="hero-right" data-testid="hero-spotlight">
          {(spotlight.cards || []).length === 0 && (
            <>
              <div className="sk sk-spotlight-card sk-spot-1" data-testid="sk-spot-1" />
              <div className="sk sk-spotlight-card sk-spot-2" data-testid="sk-spot-2" />
              <div className="sk sk-spotlight-card sk-spot-3" data-testid="sk-spot-3" />
            </>
          )}
          {visibleSpotlight.slice(0, 3).map((c, i) => {
            // Featured artists pay for hero placement — show their actual photo.
            // Priority: profile_image → cover_image → first gallery thumb → emoji fallback.
            const thumbs = c.gallery_thumbs || [];
            const featuredThumb = thumbs.find((t) => t.is_featured) || thumbs[0];
            const heroImg = c.profile_image
              ? mediaUrl(c.profile_image)
              : c.cover_image
                ? mediaUrl(c.cover_image)
                : (featuredThumb ? mediaUrl(featuredThumb.id) : null);
            return (
            <Link
              key={`${c.user_id}-${spotIdx}`}
              to={`/artist/${c.slug || c.user_id}`}
              className={`spotlight-card spotlight-card-${i + 1}`}
              data-testid={`spotlight-card-${i}`}
              target="_blank"
              rel="noopener noreferrer"
              {...(heroImg ? {
                style: {
                  background: `linear-gradient(180deg, rgba(0,0,0,0.15) 0%, rgba(0,0,0,0.55) 55%, rgba(0,0,0,0.85) 100%), url(${heroImg}) center/cover no-repeat`,
                },
              } : {})}
            >
              {!heroImg && (
                <div className="spotlight-emoji" aria-hidden>
                  {c.emoji || (c.category?.toLowerCase().includes("dj") ? "🎧" : c.category?.toLowerCase().includes("com") ? "🎭" : "🎤")}
                </div>
              )}
              <div className="spotlight-body">
                {c.kyc_status === "approved" && <span className="spotlight-badge">✓ Verified Artist</span>}
                <div className="spotlight-name">{c.stage_name}</div>
                <div className="spotlight-cat">{c.category}</div>
                <div className="spotlight-foot">
                  <span className="spotlight-rating">
                    {"★".repeat(Math.round(c.rating_avg || 0)) || "★"} ({c.review_count || 0})
                  </span>
                  {c.starting_price && <span className="spotlight-price">{fmtINRFull(c.starting_price).replace("₹", "₹")}</span>}
                </div>
              </div>
            </Link>
          );})}
          {spotlight.latest_booking && (
            <div className="spotlight-toast" data-testid="spotlight-toast">
              <div className="spotlight-toast-icon">📅</div>
              <div>
                <div className="spotlight-toast-title">New booking confirmed</div>
                <div className="spotlight-toast-sub">
                  {spotlight.latest_booking.venue} · {spotlight.latest_booking.event_date}
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── Marquee strip (Iter 43) ────────────────────────────────────── */}
      <div className="marquee-section" data-testid="landing-marquee">
        <div className="marquee-track">
          {[
            "Weddings & Receptions", "Corporate Events", "Birthday Parties", "College Fests",
            "Brand Activations", "Private Concerts", "Club Nights", "Hotel Shows", "Virtual Events",
            "Weddings & Receptions", "Corporate Events", "Birthday Parties", "College Fests",
            "Brand Activations", "Private Concerts", "Club Nights", "Hotel Shows", "Virtual Events",
          ].map((label, i) => (
            <div className="marquee-item" key={`${label}-${i}`}>
              <span className="marquee-dot" /> {label}
            </div>
          ))}
        </div>
      </div>

      {/* ── Categories grid ───────────────────────────────────────────── */}
      <section className="lp-section" data-testid="landing-categories">
        <div className="section-header">
          <div>
            <div className="section-tag">Browse by Category</div>
            <h2 className="section-title">Every kind of<br /><span className="accent">talent</span> you need</h2>
          </div>
          <Link to="/search" className="btn btn-ghost" data-testid="categories-view-all">View All →</Link>
        </div>
        <div className="cat-grid">
          {(() => {
            // Fuzzy-match tile slugs to actual category names in the DB.
            // e.g. "singer" tile → any category that starts with or contains
            // "singer" / "vocalist"; "dj" → contains "dj"; "comedian" → contains
            // "comed"; "dancer" → contains "danc" and so on.
            const KEYWORDS = {
              singer: ["singer", "vocalist"], dj: ["dj"], comedian: ["comed"],
              anchor: ["anchor", "emcee"], dancer: ["danc"],
              magician: ["magic"], band: ["band", "orchestra"],
              celebrity: ["celebrity", "influencer"],
            };
            const withCounts = CAT_TILES.map((c) => {
              let localCount = 0;
              const kws = KEYWORDS[c.slug] || [c.slug];
              for (const [k, v] of Object.entries(catStats)) {
                if (kws.some((kw) => k.includes(kw))) localCount += v;
              }
              return { ...c, localCount };
            });
            withCounts.sort((a, b) => b.localCount - a.localCount);
            const hottestSlug = myCity && withCounts[0]?.localCount > 0 ? withCounts[0].slug : null;
            return withCounts.map((c) => (
              <Link
                key={c.slug}
                to={`/artists/${c.slug}`}
                className={`cat-card ${c.slug === hottestSlug ? "cat-card-local" : ""}`}
                data-testid={`cat-tile-${c.slug}`}
              >
                {c.slug === hottestSlug && (
                  <span className="cat-local-flag" data-testid={`cat-hot-${c.slug}`}>Hot in {myCity}</span>
                )}
                <span className="cat-icon">{c.icon}</span>
                <div className="cat-name">{c.name}</div>
                <div className="cat-count">
                  {c.localCount > 0 && myCity
                    ? <>{c.localCount}+ in <span className="cat-local-count">{myCity}</span> · {c.count}+ nationwide</>
                    : <>{c.count}+ Artists</>}
                </div>
                <span className="cat-arrow">↗</span>
              </Link>
            ));
          })()}
        </div>
      </section>

      <section className="section">
        <div className="container">
          {loading ? (
            <div>
              <div className="section-head" style={{ marginBottom: 20 }}>
                <div>
                  <div className="sk sk-line" style={{ width: 180, height: 24, marginBottom: 8 }} />
                  <div className="sk sk-line" style={{ width: 260, height: 14 }} />
                </div>
              </div>
              <div className="artist-grid-v2">
                {[...Array(4)].map((_, i) => (
                  <div key={`sk-rail-${i}`} className="sk-artist-card" data-testid={`sk-rail-${i}`}>
                    <div className="sk sk-cover" />
                    <div className="sk-body">
                      <div className="sk sk-line mid" />
                      <div className="sk sk-line short" />
                      <div className="sk sk-line short" style={{ marginTop: 12 }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            rails.map((rail) => (
              <HomeRail key={rail.code} rail={rail} />
            ))
          )}
        </div>
      </section>

      {/* ── How it Works ─────────────────────────────────────────────── */}
      <section className="lp-section" style={{ textAlign: "center", paddingTop: 0 }} data-testid="landing-how-it-works">
        <div className="section-tag" style={{ margin: "0 auto 16px" }}>Simple. Transparent. Instant.</div>
        <h2 className="section-title" style={{ margin: "0 auto 12px", maxWidth: 780 }}>
          Book your dream artist<br />in <span className="accent">4 easy steps</span>
        </h2>
        <div className="steps-grid">
          {HOW_STEPS.map((s) => (
            <div className="step-card" key={s.num} data-testid={`step-${s.num}`}>
              <div className="step-num-wrap"><div className="step-num">{s.num}</div></div>
              <span className="step-icon">{s.icon}</span>
              <div className="step-title">{s.title}</div>
              <div className="step-desc">{s.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Cities grid ──────────────────────────────────────────────── */}
      <section className="lp-section" style={{ textAlign: "center", paddingTop: 0 }} data-testid="landing-cities">
        <div className="section-tag" style={{ margin: "0 auto 16px" }}>Pan-India Presence</div>
        <h2 className="section-title" style={{ margin: "0 auto 40px", maxWidth: 620 }}>
          Artists in your <span className="accent">city</span>
        </h2>
        <div className="cities-grid">
          {(() => {
            const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, "");
            const my = norm(myCity);
            const ordered = [...CITY_TILES].sort((a, b) => {
              const am = my && (norm(a.name) === my || norm(a.slug) === my) ? -1 : 0;
              const bm = my && (norm(b.name) === my || norm(b.slug) === my) ? -1 : 0;
              return am - bm;
            });
            return ordered.map((c) => {
              const isMine = my && (norm(c.name) === my || norm(c.slug) === my);
              return (
                <Link
                  key={c.slug}
                  to={`/artists/city/${c.slug}`}
                  className={`city-card ${isMine ? "city-card-mine" : ""}`}
                  data-testid={`city-tile-${c.slug}`}
                >
                  {isMine && <span className="city-mine-badge">📍 Your city</span>}
                  <div className="city-icon">{c.icon}</div>
                  <div className="city-name">{c.name}</div>
                  <div className="city-count">{c.count}+ artists</div>
                </Link>
              );
            });
          })()}
        </div>
      </section>

      {/* ── Testimonials ─────────────────────────────────────────────── */}
      <section className="lp-section" style={{ textAlign: "center", paddingTop: 0 }} data-testid="landing-testimonials">
        <div className="section-tag" style={{ margin: "0 auto 16px" }}>48,000+ Happy Clients</div>
        <h2 className="section-title" style={{ margin: "0 auto 40px", maxWidth: 680 }}>
          Loved by <span className="italic">event planners</span><br />across India
        </h2>
        <div className="testi-grid" style={{ textAlign: "left" }}>
          {TESTIMONIALS.map((t, i) => (
            <div className="testi-card" key={t.name} data-testid={`testi-${i}`}>
              <div className="testi-stars">{"★".repeat(t.stars)}</div>
              <div className="testi-quote">"{t.quote}"</div>
              <div className="testi-person">
                <div className={`testi-avatar ${t.avatarClass}`}>{t.initials}</div>
                <div>
                  <div className="testi-name">{t.name}</div>
                  <div className="testi-role">{t.role}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Artist Join CTA ─────────────────────────────────────────── */}
      <section className="lp-section" style={{ paddingTop: 0 }} data-testid="landing-dual-cta">
        <div className="dual-cta" style={{ gridTemplateColumns: "1fr" }}>
          <div className="cta-box" data-testid="cta-artist">
            <div className="cta-box-glow cta-glow-purple" />
            <span className="cta-box-icon">🎤</span>
            <div className="cta-box-title">Are you an Artist?</div>
            <div className="cta-box-desc">
              Join 5,200+ verified performers on India's premium marketplace. Manage your profile, calendar, packages and bookings — all from one clean dashboard.
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <Link to="/signup?role=artist" className="btn btn-purple" data-testid="cta-artist-join">Join as Artist →</Link>
              <Link to="/page/artist-guidelines" className="btn btn-ghost" data-testid="cta-artist-learn">Learn more</Link>
            </div>
          </div>
        </div>
      </section>

      {featuredFaqs.length > 0 && (
        <section className="faq-hero" data-testid="landing-faq-section">
          <div className="faq-hero-head">
            <h2 style={{ fontFamily: "var(--font-serif)" }}>Frequently Asked <span className="gold-grad">Questions</span></h2>
            <p className="text-muted">Everything you need to know before booking your next event.</p>
          </div>
          <div className="faq-list">
            {featuredFaqs.map((f) => (
              <div key={f.id} className={`faq-row ${openFaq[f.id] ? "open" : ""}`} data-testid={`landing-faq-${f.id}`}>
                <button
                  className="faq-q"
                  onClick={() => setOpenFaq({ ...openFaq, [f.id]: !openFaq[f.id] })}
                  aria-expanded={!!openFaq[f.id]}
                  data-testid={`landing-faq-toggle-${f.id}`}
                >
                  <span>{f.question}</span>
                  <span className="faq-caret">{openFaq[f.id] ? "−" : "+"}</span>
                </button>
                {openFaq[f.id] && <div className="faq-a">{f.answer}</div>}
              </div>
            ))}
          </div>
          <div style={{ textAlign: "center", marginTop: 24 }}>
            <Link to="/help" className="btn btn-ghost" data-testid="landing-faq-view-all">
              View all answers in Help Center →
            </Link>
          </div>
        </section>
      )}

      <Footer />
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// Sprint 5 — Dynamic homepage rail. Horizontal-scrolling artist row.
// ────────────────────────────────────────────────────────────────────────
function HomeRail({ rail }) {
  // Iter 45 — inline filter chips (category / city / price band)
  const [fCat, setFCat] = React.useState("all");
  const [fCity, setFCity] = React.useState("all");
  const [fPrice, setFPrice] = React.useState("all");
  const [showFilters, setShowFilters] = React.useState(false);

  if (!rail?.items?.length) return null;
  // Dedupe by user_id to guard against duplicate-key warnings
  const seen = new Set();
  const items = rail.items.filter((a) => {
    if (!a?.user_id || seen.has(a.user_id)) return false;
    seen.add(a.user_id);
    return true;
  });

  const cats = ["all", ...Array.from(new Set(items.map((a) => a.category).filter(Boolean))).slice(0, 5)];
  const cities = ["all", ...Array.from(new Set(items.map((a) => a.city).filter(Boolean))).slice(0, 5)];
  const PRICE_BANDS = [
    { id: "all",   label: "Any price", test: () => true },
    { id: "low",   label: "Under ₹25k",  test: (p) => p && p < 25000 },
    { id: "mid",   label: "₹25k – ₹75k", test: (p) => p && p >= 25000 && p < 75000 },
    { id: "high",  label: "₹75k – ₹2L",  test: (p) => p && p >= 75000 && p < 200000 },
    { id: "elite", label: "₹2L+",         test: (p) => p && p >= 200000 },
  ];

  const filtered = items.filter((a) => {
    if (fCat !== "all" && a.category !== fCat) return false;
    if (fCity !== "all" && a.city !== fCity) return false;
    const band = PRICE_BANDS.find((b) => b.id === fPrice);
    if (band && !band.test(a.starting_price)) return false;
    return true;
  });
  const anyActive = fCat !== "all" || fCity !== "all" || fPrice !== "all";
  const activeCount = [fCat, fCity, fPrice].filter((v) => v !== "all").length;
  const hasFilterableFacets = cats.length > 2 || cities.length > 2;
  return (
    <div className="mb-32" data-testid={`rail-${rail.code}`} style={{ marginBottom: 40 }}>
      <div className="section-head">
        <div>
          <h2 className="section-title" style={{ fontSize: 24 }}>{rail.title}</h2>
          <p className="section-sub">{rail.subtitle}</p>
        </div>
        <div className="section-head-actions">
          {hasFilterableFacets && (
            <button
              type="button"
              className={`btn btn-ghost btn-sm rail-filter-toggle ${showFilters ? "active" : ""}`}
              onClick={() => setShowFilters((s) => !s)}
              data-testid={`rail-filter-toggle-${rail.code}`}
              aria-expanded={showFilters}
            >
              {showFilters ? "▲" : "▼"} Filter{activeCount > 0 && <span className="rail-filter-count">{activeCount}</span>}
            </button>
          )}
          <Link to={`/search?section=${encodeURIComponent(rail.code)}`} className="btn btn-ghost btn-sm" data-testid={`rail-more-${rail.code}`}>View All →</Link>
        </div>
      </div>

      {hasFilterableFacets && showFilters && (
        <div className="rail-filters" data-testid={`rail-filters-${rail.code}`}>
          {cats.length > 2 && (<>
            <span className="rail-filter-label">Type</span>
            {cats.map((c) => (
              <button key={c} className={`rail-chip ${fCat === c ? "active" : ""}`} onClick={() => setFCat(c)} data-testid={`rail-cat-${rail.code}-${c}`}>
                {c === "all" ? "All" : c}
              </button>
            ))}
          </>)}
          {cities.length > 2 && (<>
            <span className="rail-filter-label" style={{ marginLeft: 8 }}>City</span>
            {cities.map((c) => (
              <button key={c} className={`rail-chip ${fCity === c ? "active" : ""}`} onClick={() => setFCity(c)} data-testid={`rail-city-${rail.code}-${c}`}>
                {c === "all" ? "All" : c}
              </button>
            ))}
          </>)}
          <span className="rail-filter-label" style={{ marginLeft: 8 }}>Price</span>
          {PRICE_BANDS.map((b) => (
            <button key={b.id} className={`rail-chip ${fPrice === b.id ? "active" : ""}`} onClick={() => setFPrice(b.id)} data-testid={`rail-price-${rail.code}-${b.id}`}>
              {b.label}
            </button>
          ))}
          {anyActive && (
            <button className="rail-chip" onClick={() => { setFCat("all"); setFCity("all"); setFPrice("all"); }} data-testid={`rail-clear-${rail.code}`} style={{ color: "var(--gold-light)" }}>
              ✕ Clear
            </button>
          )}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="rail-empty" data-testid={`rail-empty-${rail.code}`}>
          No matches — try relaxing the filters.
        </div>
      ) : (
      <div className="artist-grid-v2">
        {filtered.map((a) => {
          const cityLine = [a.category, a.city].filter(Boolean).join(" · ");
          const tags = (a.tags || a.genres || []).slice(0, 4);
          return (
            <Link to={`/artist/${a.slug || a.user_id}`} key={a.user_id} className="artist-card-v2" data-testid={`rail-card-${rail.code}-${a.user_id}`} target="_blank" rel="noopener noreferrer">
              <div className="artist-img-wrap">
                <ArtistCardThumb
                  artist={a}
                  className="artist-cover-v2"
                  placeholder={<span style={{ fontSize: 64 }}>{a.emoji || "🎤"}</span>}
                />
                <div className="artist-overlay" />
                {a.is_boosted ? (
                  <div className="artist-badge boosted"><span>★</span> Boosted</div>
                ) : a.plan_code === "elite" ? (
                  <div className="artist-badge elite">👑 Elite</div>
                ) : a.plan_code === "platinum" ? (
                  <div className="artist-badge platinum">💎 Platinum</div>
                ) : (
                  <div className="artist-badge available"><span className="badge-dot" /> Available</div>
                )}
                <div className="artist-img-info">
                  <div className="artist-name-big">
                    {a.stage_name}
                    {a.verified_badge && <span style={{ color: "var(--gold)", marginLeft: 6 }}>✓</span>}
                  </div>
                  <div className="artist-type-tag">{cityLine}</div>
                </div>
              </div>
              <div className="artist-body-v2">
                <div className="artist-rating-row">
                  <span className="stars">{"★".repeat(Math.max(1, Math.round(a.rating_avg || 0)))}</span>
                  <span className="artist-rating-val">{(a.rating_avg || 0).toFixed(1)}</span>
                  <span className="artist-reviews">({a.review_count || 0} reviews)</span>
                </div>
                {tags.length > 0 && (
                  <div className="artist-tags">
                    {tags.map((t) => <span className="atag" key={t}>{t}</span>)}
                  </div>
                )}
                <div className="artist-footer">
                  <div>
                    <div className="artist-price-label">Starting from</div>
                    <div className="artist-price">{a.starting_price ? fmtINRFull(a.starting_price) : "—"} <span>/ event</span></div>
                  </div>
                  <span className="btn btn-gold btn-sm">Book Now</span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
      )}
    </div>
  );
}
