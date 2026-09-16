import React, { useEffect, useState, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Nav from "../components/Nav";
import api, { fmtINRFull, pickArtistThumb } from "../lib/api";
import ArtistCardThumb from "../components/ArtistCardThumb";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";

export default function Search() {
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [cities, setCities] = useState([]);
  const [categories, setCategories] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [eventTypes, setEventTypes] = useState([]);
  const [popular, setPopular] = useState([]);
  const [saved, setSaved] = useState([]);
  const [suggestions, setSuggestions] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const sugRef = useRef(null);

  // Iter 74 — Persist search filters so revisiting /discover lands on the
  // last known filter set instead of a blank slate. URL params always win
  // (deep links / shared URLs), then localStorage, then empty defaults.
  const savedFiltersKey = "bt_last_search_filters";
  const savedFilters = React.useMemo(() => {
    try {
      // Skip restore when the URL already carries any filter param — a
      // shared / bookmarked link must remain authoritative.
      const hasUrlFilters = ["q","category","city","min_price","max_price",
        "language","event_type","min_rating","min_experience","gender","sort"]
        .some((k) => params.get(k));
      if (hasUrlFilters) return null;
      const raw = localStorage.getItem(savedFiltersKey);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Filters
  const [q, setQ] = useState(params.get("q") || savedFilters?.q || "");
  const [category, setCategory] = useState(params.get("category") || savedFilters?.category || "");
  const [city, setCity] = useState(params.get("city") || savedFilters?.city || "");
  const [minPrice, setMinPrice] = useState(params.get("min_price") || savedFilters?.minPrice || "");
  const [maxPrice, setMaxPrice] = useState(params.get("max_price") || savedFilters?.maxPrice || "");
  const [language, setLanguage] = useState(params.get("language") || savedFilters?.language || "");
  const [eventType, setEventType] = useState(params.get("event_type") || savedFilters?.eventType || "");
  const [minRating, setMinRating] = useState(params.get("min_rating") || savedFilters?.minRating || "");
  const [minExperience, setMinExperience] = useState(params.get("min_experience") || savedFilters?.minExperience || "");
  const [gender, setGender] = useState(params.get("gender") || savedFilters?.gender || "");
  const [featuredOnly, setFeaturedOnly] = useState(!!savedFilters?.featuredOnly);
  const [verifiedOnly, setVerifiedOnly] = useState(!!savedFilters?.verifiedOnly);
  const [premiumOnly, setPremiumOnly] = useState(!!savedFilters?.premiumOnly);
  const [instantOnly, setInstantOnly] = useState(!!savedFilters?.instantOnly);
  const [sort, setSort] = useState(savedFilters?.sort || "relevance");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get("/catalog/cities").then((r) => setCities(r.data.map((c) => c.name)));
    api.get("/catalog/categories").then((r) => setCategories(r.data));
    api.get("/catalog/languages").then((r) => setLanguages(r.data.map((c) => c.name)));
    api.get("/catalog/event-types").then((r) => setEventTypes(r.data.map((c) => c.name)));
    api.get("/search/popular").then((r) => setPopular(r.data || [])).catch(() => {});
    if (user) api.get("/search/saved").then((r) => setSaved(r.data)).catch(() => {});
  }, [user]);

  const run = async (pg = 1, append = false) => {
    if (append) setLoadingMore(true); else setLoading(true);
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (category) p.set("category", category);
    if (city) p.set("city", city);
    if (minPrice) p.set("min_price", minPrice);
    if (maxPrice) p.set("max_price", maxPrice);
    if (language) p.set("language", language);
    if (eventType) p.set("event_type", eventType);
    if (minRating) p.set("min_rating", minRating);
    if (minExperience) p.set("min_experience", minExperience);
    if (gender) p.set("gender", gender);
    if (featuredOnly) p.set("featured_only", "true");
    if (verifiedOnly) p.set("verified_only", "true");
    if (premiumOnly) p.set("premium_only", "true");
    if (instantOnly) p.set("instant_available", "true");
    p.set("sort", sort);
    p.set("page", pg);
    p.set("limit", "24");
    // Preserve URL only for the base page (not the infinite append calls)
    if (!append) setParams(p);
    setPage(pg);
    // Iter 74 — Persist current filter snapshot so the next visit to
    // /discover starts on this filter set. Only for base fetches — we
    // don't rewrite storage on infinite scroll.
    if (!append) {
      try {
        localStorage.setItem(savedFiltersKey, JSON.stringify({
          q, category, city, minPrice, maxPrice, language, eventType,
          minRating, minExperience, gender,
          featuredOnly, verifiedOnly, premiumOnly, instantOnly, sort,
        }));
      } catch { /* private-mode / quota */ }
    }
    try {
      const r = await api.get(`/search/artists?${p.toString()}`);
      setItems(append ? [...items, ...r.data.items] : r.data.items);
      setTotal(r.data.total);
      setPages(r.data.pages);
      setHasMore(pg < r.data.pages);
    } finally {
      if (append) setLoadingMore(false); else setLoading(false);
    }
  };

  // Filters trigger a fresh page-1 fetch. `run` is redefined every render so
  // including it would loop; it closes over the current filter state, so we
  // list all filter deps explicitly instead.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(1); }, [category, city, sort, language, eventType, minRating, minExperience, gender, featuredOnly, verifiedOnly, premiumOnly, instantOnly, minPrice, maxPrice]);

  // Sprint 6 — Infinite scroll via IntersectionObserver on a sentinel element
  const sentinelRef = useRef(null);
  useEffect(() => {
    if (!sentinelRef.current || !hasMore) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !loadingMore && !loading && hasMore) {
        run(page + 1, true);
      }
    }, { rootMargin: "400px" });
    io.observe(sentinelRef.current);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMore, page, loadingMore, loading]);

  // Live suggestions
  useEffect(() => {
    if (!q || q.length < 2) { setSuggestions(null); return; }
    const t = setTimeout(() => {
      api.get(`/search/suggestions?q=${encodeURIComponent(q)}`).then((r) => setSuggestions(r.data)).catch(() => setSuggestions(null));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const saveCurrent = async () => {
    if (!user) return toast("Login to save searches");
    const name = window.prompt("Name this search:");
    if (!name) return;
    await api.post("/search/saved", { name, query: q, filters: { category, city, min_price: minPrice, max_price: maxPrice, language, event_type: eventType } });
    toast("Search saved ✓");
    api.get("/search/saved").then((r) => setSaved(r.data));
  };

  const loadSaved = (s) => {
    setQ(s.query || "");
    setCategory(s.filters?.category || "");
    setCity(s.filters?.city || "");
    setMinPrice(s.filters?.min_price || "");
    setMaxPrice(s.filters?.max_price || "");
    setLanguage(s.filters?.language || "");
    setEventType(s.filters?.event_type || "");
    setTimeout(() => run(1), 50);
  };

  const reset = () => {
    setQ(""); setCategory(""); setCity(""); setMinPrice(""); setMaxPrice("");
    setLanguage(""); setEventType(""); setMinRating(""); setMinExperience("");
    setGender(""); setFeaturedOnly(false); setVerifiedOnly(false);
    setPremiumOnly(false); setInstantOnly(false); setSort("relevance");
    // Iter 74 — Explicit reset wipes the persisted snapshot so a next
    // visit is truly a clean slate.
    try { localStorage.removeItem(savedFiltersKey); } catch { /* ignore */ }
    setTimeout(() => run(1), 50);
  };

  return (
    <div data-testid="search-page">
      <div className="orb orb-1" />
      <Nav />
      <div className="container" style={{ paddingTop: 40, paddingBottom: 60 }}>
        <h1 className="font-serif" style={{ fontSize: 36, fontWeight: 700, marginBottom: 4 }}>
          Discover <span style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Artists</span>
        </h1>
        <p className="text-muted mb-24">Browse {total} verified artists across India</p>

        <form
          onSubmit={(e) => { e.preventDefault(); run(1); }}
          style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr auto", gap: 10, marginBottom: 14 }}
          data-testid="search-filters"
        >
          <div style={{ position: "relative" }} ref={sugRef}>
            <input
              className="field-input" placeholder="Search by name, genre, vibe…"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="filter-q"
              style={{ width: "100%" }}
            />
            {suggestions && (suggestions.artists?.length || suggestions.categories?.length || suggestions.cities?.length) > 0 && (
              <div className="card" style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, marginTop: 4, maxHeight: 320, overflow: "auto", padding: 6 }} data-testid="search-suggestions">
                {suggestions.artists?.map((a) => (
                  <Link key={a.id} to={`/artist/${a.id}`} className="sb-item" style={{ padding: "6px 10px", display: "block" }} target="_blank" rel="noopener noreferrer">
                    <div className="fw-600">{a.label}</div>
                    <div className="text-muted fs-11">{a.sub}</div>
                  </Link>
                ))}
                {suggestions.categories?.map((c) => (
                  <div key={c.slug} className="sb-item" style={{ padding: "6px 10px", cursor: "pointer" }} onClick={() => { setCategory(c.label); setSuggestions(null); }}>
                    🗂️ {c.label}
                  </div>
                ))}
                {suggestions.cities?.map((c) => (
                  <div key={c.slug} className="sb-item" style={{ padding: "6px 10px", cursor: "pointer" }} onClick={() => { setCity(c.label); setSuggestions(null); }}>
                    📍 {c.label}
                  </div>
                ))}
              </div>
            )}
          </div>
          <select className="field-input" value={category} onChange={(e) => setCategory(e.target.value)} data-testid="filter-category">
            <option value="">All Categories</option>
            {categories.map((c) => <option key={c.slug} value={c.name}>{c.name}</option>)}
          </select>
          <select className="field-input" value={city} onChange={(e) => setCity(e.target.value)} data-testid="filter-city">
            <option value="">All Cities</option>
            {cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select className="field-input" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} data-testid="filter-budget">
            <option value="">Any Budget</option>
            <option value="25000">Up to ₹25K</option>
            <option value="50000">Up to ₹50K</option>
            <option value="100000">Up to ₹1L</option>
            <option value="200000">Up to ₹2L</option>
          </select>
          <button className="btn btn-gold" type="submit" data-testid="filter-apply">Search</button>
        </form>

        <div className="flex gap-8 mb-12" style={{ flexWrap: "wrap", marginBottom: 12 }}>
          <button className="btn btn-ghost btn-xs" onClick={() => setShowAdvanced(!showAdvanced)} data-testid="toggle-advanced">
            {showAdvanced ? "▲ Hide" : "▼ Show"} Advanced Filters
          </button>
          <button className="btn btn-ghost btn-xs" onClick={reset} data-testid="filter-reset">Reset</button>
          {user && <button className="btn btn-ghost btn-xs" onClick={saveCurrent} data-testid="save-search">⭐ Save Search</button>}
          {user && <button
            className="btn btn-ghost btn-xs"
            onClick={async () => {
              try {
                await (await import("../lib/api")).default.post("/watches", {
                  city: city || null,
                  category: category || null,
                  label: [category, city].filter(Boolean).join(" · ") || null,
                });
                alert("🔔 We'll ping you when a new artist matches this search.");
              } catch (e) {
                alert(e?.response?.data?.detail || "Could not save watch — set at least a city or category first.");
              }
            }}
            data-testid="save-watch"
            title="Get notified when a new artist matches these filters"
          >🔔 Notify Me</button>}
          {popular.slice(0, 5).map((p) => (
            <button key={p.query} className="btn btn-ghost btn-xs" onClick={() => { setQ(p.query); setTimeout(() => run(1), 50); }} data-testid={`pop-${p.query}`}>
              🔥 {p.query} ({p.count})
            </button>
          ))}
        </div>

        {/* Iter 74 — Active filter chips. Each active filter renders as a
            removable pill so customers see exactly what's narrowing the
            results and can dismiss individual filters with one tap. */}
        {(() => {
          const chips = [];
          if (q) chips.push({ key: "q", label: `“${q}”`, clear: () => setQ("") });
          if (category) chips.push({ key: "category", label: `🎭 ${category}`, clear: () => setCategory("") });
          if (city) chips.push({ key: "city", label: `📍 ${city}`, clear: () => setCity("") });
          if (minPrice || maxPrice) chips.push({
            key: "price",
            label: `₹ ${minPrice ? Number(minPrice).toLocaleString("en-IN") : "0"}${maxPrice ? "–" + Number(maxPrice).toLocaleString("en-IN") : "+"}`,
            clear: () => { setMinPrice(""); setMaxPrice(""); },
          });
          if (language) chips.push({ key: "language", label: `🗣 ${language}`, clear: () => setLanguage("") });
          if (eventType) chips.push({ key: "eventType", label: `🎪 ${eventType}`, clear: () => setEventType("") });
          if (minRating) chips.push({ key: "minRating", label: `⭐ ${minRating}+`, clear: () => setMinRating("") });
          if (minExperience) chips.push({ key: "minExperience", label: `📅 ${minExperience}+ yrs`, clear: () => setMinExperience("") });
          if (gender) chips.push({ key: "gender", label: `👤 ${gender[0].toUpperCase()}${gender.slice(1)}`, clear: () => setGender("") });
          if (featuredOnly) chips.push({ key: "featured", label: "⭐ Featured", clear: () => setFeaturedOnly(false) });
          if (verifiedOnly) chips.push({ key: "verified", label: "✓ Verified KYC", clear: () => setVerifiedOnly(false) });
          if (premiumOnly) chips.push({ key: "premium", label: "💎 Premium", clear: () => setPremiumOnly(false) });
          if (instantOnly) chips.push({ key: "instant", label: "⚡ Instant", clear: () => setInstantOnly(false) });
          if (chips.length === 0) return null;
          return (
            <div
              data-testid="active-filter-chips"
              style={{
                display: "flex", flexWrap: "wrap", gap: 8,
                marginBottom: 14, padding: "10px 12px",
                borderRadius: 12,
                background: "rgba(212,175,55,0.05)",
                border: "1px solid rgba(212,175,55,0.15)",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--white-muted, rgba(255,255,255,0.55))", alignSelf: "center", marginRight: 4 }}>
                Filters:
              </span>
              {chips.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  data-testid={`filter-chip-${c.key}`}
                  onClick={c.clear}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "5px 10px 5px 12px",
                    borderRadius: 999,
                    background: "rgba(212,175,55,0.12)",
                    color: "var(--gold-light, #f5d47a)",
                    border: "1px solid rgba(212,175,55,0.3)",
                    fontSize: 12, fontWeight: 600,
                    cursor: "pointer",
                    transition: "background 150ms ease, border-color 150ms ease",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(212,175,55,0.22)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(212,175,55,0.12)"; }}
                  title="Remove this filter"
                  aria-label={`Remove ${c.label}`}
                >
                  {c.label}
                  <span style={{ marginLeft: 2, opacity: 0.75, fontSize: 13, lineHeight: 1 }}>✕</span>
                </button>
              ))}
              {chips.length > 1 && (
                <button
                  type="button"
                  data-testid="filter-chip-clear-all"
                  onClick={reset}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 999,
                    background: "transparent",
                    color: "var(--white-muted, rgba(255,255,255,0.7))",
                    border: "1px dashed rgba(255,255,255,0.2)",
                    fontSize: 11, cursor: "pointer",
                  }}
                >Clear all</button>
              )}
            </div>
          );
        })()}



        {showAdvanced && (
          <div className="card card-pad mb-16" data-testid="advanced-filters">
            <div className="grid grid-4 gap-12">
              <select className="field-input" value={language} onChange={(e) => setLanguage(e.target.value)} data-testid="filter-language">
                <option value="">Any Language</option>
                {languages.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
              <select className="field-input" value={eventType} onChange={(e) => setEventType(e.target.value)} data-testid="filter-event-type">
                <option value="">Any Event Type</option>
                {eventTypes.map((e) => <option key={e} value={e}>{e}</option>)}
              </select>
              <select className="field-input" value={minRating} onChange={(e) => setMinRating(e.target.value)} data-testid="filter-min-rating">
                <option value="">Any Rating</option>
                <option value="3">3★+</option>
                <option value="4">4★+</option>
                <option value="4.5">4.5★+</option>
              </select>
              <select className="field-input" value={minExperience} onChange={(e) => setMinExperience(e.target.value)} data-testid="filter-experience">
                <option value="">Any Experience</option>
                <option value="2">2+ years</option>
                <option value="5">5+ years</option>
                <option value="10">10+ years</option>
              </select>
              <select className="field-input" value={gender} onChange={(e) => setGender(e.target.value)} data-testid="filter-gender">
                <option value="">Any Gender</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
              <input className="field-input" type="number" placeholder="Min price ₹" value={minPrice} onChange={(e) => setMinPrice(e.target.value)} data-testid="filter-min-price" />
              <div className="flex gap-8 items-center" style={{ gridColumn: "span 2", flexWrap: "wrap" }}>
                <label className="flex items-center gap-4 fs-12"><input type="checkbox" checked={featuredOnly} onChange={(e) => setFeaturedOnly(e.target.checked)} data-testid="filter-featured" /> Featured</label>
                <label className="flex items-center gap-4 fs-12"><input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} data-testid="filter-verified" /> Verified KYC</label>
                <label className="flex items-center gap-4 fs-12"><input type="checkbox" checked={premiumOnly} onChange={(e) => setPremiumOnly(e.target.checked)} data-testid="filter-premium" /> Premium</label>
                <label className="flex items-center gap-4 fs-12"><input type="checkbox" checked={instantOnly} onChange={(e) => setInstantOnly(e.target.checked)} data-testid="filter-instant" /> Instant Available</label>
              </div>
            </div>
            {saved.length > 0 && (
              <div className="mt-12" style={{ marginTop: 12 }}>
                <div className="fs-12 text-muted mb-4">Saved Searches:</div>
                <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
                  {saved.map((s) => (
                    <button key={s.id} className="btn btn-ghost btn-xs" onClick={() => loadSaved(s)} data-testid={`saved-${s.id}`}>⭐ {s.name}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-between items-center mb-16">
          <div className="text-muted fs-13">{total} artists found</div>
          <select className="field-input" style={{ width: 200 }} value={sort} onChange={(e) => setSort(e.target.value)} data-testid="filter-sort">
            <option value="relevance">Most Relevant</option>
            <option value="rating">Highest Rated</option>
            <option value="price_asc">Price: Low to High</option>
            <option value="price_desc">Price: High to Low</option>
            <option value="newest">Newest</option>
          </select>
        </div>

        {loading ? (
          <div className="artist-grid-v2">
            {[...Array(8)].map((_, i) => <div key={`sk-search-${i}`} className="sk-artist-card" data-testid={`sk-search-${i}`} />)}
          </div>
        ) : items.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">🔍</div>
            <div className="empty-title">No artists found</div>
            <p>Try adjusting your filters</p>
          </div>
        ) : (
          <>
            <div className="artist-grid-v2">
              {items.map((a) => {
                const cityLine = [a.category, a.city].filter(Boolean).join(" · ");
                const tags = (a.tags || a.genres || []).slice(0, 4);
                return (
                  <Link to={`/artist/${a.slug || a.user_id}`} key={a.user_id} className="artist-card-v2" data-testid={`artist-card-${a.user_id}`} target="_blank" rel="noopener noreferrer">
                    <div className="artist-img-wrap">
                      <ArtistCardThumb
                        artist={a}
                        className="artist-cover-v2"
                        placeholder={<span style={{ fontSize: 64 }}>{a.emoji || "🎤"}</span>}
                      />
                      <div className="artist-overlay" />
                      {a.is_boosted || a.is_featured ? (
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
                          <div className="artist-price">{a.starting_price || a.base_price ? fmtINRFull(a.starting_price || a.base_price) : "—"} <span>/ event</span></div>
                        </div>
                        <span className="btn btn-gold btn-sm">Book Now</span>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>

            {pages > 1 && hasMore && (
              <div ref={sentinelRef} style={{ padding: 32, textAlign: "center" }} data-testid="infinite-scroll-sentinel">
                {loadingMore ? (
                  <div className="artist-grid-v2" style={{ marginTop: 12 }}>
                    {[...Array(4)].map((_, i) => <div key={`m${i}`} className="sk-artist-card" />)}
                  </div>
                ) : (
                  <div className="text-muted fs-13">Scroll to load more…</div>
                )}
              </div>
            )}
            {pages > 1 && !hasMore && (
              <div className="text-muted text-center fs-13" style={{ padding: 24 }} data-testid="infinite-scroll-end">
                — End of results —
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
