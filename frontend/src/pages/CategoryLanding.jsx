import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import ArtistCardThumb from "../components/ArtistCardThumb";
import api, { fmtINRFull } from "../lib/api";

/**
 * /artists/:slug  → Category landing page (e.g. /artists/singer)
 * SEO-optimised H1, meta, ItemList JSON-LD.
 */
export default function CategoryLanding() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setData(null); setNotFound(false);
    api.get(`/seo/category/${slug}`)
      .then((r) => setData(r.data))
      .catch((e) => { if (e?.response?.status === 404) setNotFound(true); });
  }, [slug]);

  if (notFound) {
    return (
      <div>
        <SEO title="Category not found" noindex path={`/artists/${slug}`} />
        <Nav />
        <section className="section container" style={{ minHeight: "50vh", textAlign: "center", paddingTop: 80 }}>
          <div style={{ fontSize: 72 }}>🎭</div>
          <h1 style={{ fontSize: 36 }}>Category not found</h1>
          <Link to="/search" className="btn btn-gold" data-testid="cat-back-search">Browse all artists →</Link>
        </section>
</div>
    );
  }

  const cat = data?.category;
  const artists = data?.artists || [];
  const title = cat ? `${cat.name} — Book verified ${cat.name.toLowerCase()} in India` : "Loading…";
  const description = cat
    ? `Book verified ${cat.name.toLowerCase()} on BookTalent. Compare packages, ratings and prices from ${data?.total || 0}+ professionals across India.`
    : "";

  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: artists.slice(0, 20).map((a, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `https://booktalent.com/artist/${a.slug || a.user_id}`,
      name: a.stage_name,
    })),
  };

  return (
    <div data-testid={`category-landing-${slug}`}>
      <SEO
        title={cat ? `${cat.name} in India` : "Artist category"}
        description={description}
        keywords={cat ? `book ${cat.name}, hire ${cat.name}, ${cat.name} for wedding, ${cat.name} for corporate event` : ""}
        path={`/artists/${slug}`}
        jsonLd={cat ? [itemListLd, buildBreadcrumb([
          { name: "Home", url: "/" },
          { name: "Artists", url: "/search" },
          { name: cat.name, url: `/artists/${slug}` },
        ])] : null}
      />
      <Nav />
      <section className="section container" style={{ paddingTop: 60 }}>
        {!data && <div className="skeleton" style={{ height: 300 }} />}
        {data && cat && (
          <>
            {(cat.hero_image || cat.hero_title) ? (
              <div
                className="page-hero"
                data-testid="cat-hero"
                style={{
                  backgroundImage: cat.hero_image
                    ? `linear-gradient(180deg, rgba(0,0,0,0.4), rgba(0,0,0,0.65)), url(${cat.hero_image})`
                    : undefined,
                }}
              >
                <div className="page-hero-inner">
                  <h1 data-testid="cat-h1">{cat.hero_title || title}</h1>
                  <p data-testid="cat-hero-sub">{cat.hero_subtitle || description}</p>
                  {cat.hero_cta_url && (
                    <a href={cat.hero_cta_url} className="btn btn-gold" data-testid="cat-hero-cta">
                      {cat.hero_cta_label || "Explore"} →
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="landing-hero" style={{ marginBottom: 32 }}>
                <div style={{ fontSize: 64, marginBottom: 8 }}>{cat.icon || "🎤"}</div>
                <h1 style={{ fontSize: 42 }} data-testid="cat-h1">{title}</h1>
                <p className="text-muted" style={{ maxWidth: 720 }}>{description}</p>
              </div>
            )}
            {artists.length === 0 ? (
              <div className="empty" style={{ padding: 40 }}>No {cat.name.toLowerCase()} listed yet — check back soon or <Link to="/search">browse all artists</Link>.</div>
            ) : (
              <div className="grid grid-4">
                {artists.map((a) => (
                  <Link to={`/artist/${a.slug || a.user_id}`} key={a.user_id} className="artist-card" data-testid={`cat-card-${a.user_id}`} target="_blank" rel="noopener noreferrer">
                    <ArtistCardThumb artist={a} className="artist-card-cover" placeholder={<span style={{ fontSize: "inherit" }}>{a.emoji || "🎤"}</span>} />
                    <div className="artist-card-body">
                      <div className="artist-card-name">{a.stage_name}</div>
                      <div className="artist-card-meta">{a.category} · 📍 {a.city}</div>
                      <div className="artist-card-foot">
                        <span className="artist-card-rating">★ {(a.rating_avg || 0).toFixed(1)}</span>
                        <span className="artist-card-price">{a.starting_price ? fmtINRFull(a.starting_price) : "—"}<small>/event</small></span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </>
        )}
      </section>
</div>
  );
}
