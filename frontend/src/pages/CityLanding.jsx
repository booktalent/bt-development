import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import ArtistCardThumb from "../components/ArtistCardThumb";
import api, { fmtINRFull } from "../lib/api";

/**
 * /artists/city/:slug — SEO-optimised city landing page.
 */
export default function CityLanding() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setData(null); setNotFound(false);
    api.get(`/seo/city/${slug}`).then((r) => setData(r.data))
      .catch((e) => { if (e?.response?.status === 404) setNotFound(true); });
  }, [slug]);

  if (notFound) {
    return (
      <div>
        <SEO title="City not found" noindex path={`/artists/city/${slug}`} />
        <Nav />
        <section className="section container" style={{ minHeight: "50vh", textAlign: "center", paddingTop: 80 }}>
          <div style={{ fontSize: 72 }}>📍</div>
          <h1 style={{ fontSize: 36 }}>City not found</h1>
          <Link to="/search" className="btn btn-gold" data-testid="city-back-search">Browse all artists →</Link>
        </section>
</div>
    );
  }

  const city = data?.city;
  const artists = data?.artists || [];
  const title = city ? `Book verified artists in ${city.name}` : "Loading…";
  const description = city
    ? `${data?.total || 0}+ verified artists available in ${city.name} — singers, DJs, comedians, dancers, anchors and more. Book for weddings, corporate events, birthdays and private parties.`
    : "";

  const itemListLd = {
    "@context": "https://schema.org", "@type": "ItemList",
    itemListElement: artists.slice(0, 20).map((a, i) => ({
      "@type": "ListItem", position: i + 1,
      url: `https://booktalent.com/artist/${a.slug || a.user_id}`, name: a.stage_name,
    })),
  };

  return (
    <div data-testid={`city-landing-${slug}`}>
      <SEO
        title={city ? `Book Artists in ${city.name}` : "City"}
        description={description}
        keywords={city ? `artists in ${city.name}, book singer in ${city.name}, DJ ${city.name}, event artists ${city.name}` : ""}
        path={`/artists/city/${slug}`}
        jsonLd={city ? [itemListLd, buildBreadcrumb([
          { name: "Home", url: "/" },
          { name: "Cities", url: "/search" },
          { name: city.name, url: `/artists/city/${slug}` },
        ])] : null}
      />
      <Nav />
      <section className="section container" style={{ paddingTop: 60 }}>
        {!data && <div className="skeleton" style={{ height: 300 }} />}
        {data && city && (
          <>
            {(city.hero_image || city.hero_title) ? (
              <div
                className="page-hero"
                data-testid="city-hero"
                style={{
                  backgroundImage: city.hero_image
                    ? `linear-gradient(180deg, rgba(0,0,0,0.4), rgba(0,0,0,0.65)), url(${city.hero_image})`
                    : undefined,
                }}
              >
                <div className="page-hero-inner">
                  <h1 data-testid="city-h1">{city.hero_title || title}</h1>
                  <p data-testid="city-hero-sub">{city.hero_subtitle || description}</p>
                  {city.hero_cta_url && (
                    <a href={city.hero_cta_url} className="btn btn-gold" data-testid="city-hero-cta">
                      {city.hero_cta_label || "Explore"} →
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="landing-hero" style={{ marginBottom: 32 }}>
                <div style={{ fontSize: 64, marginBottom: 8 }}>📍</div>
                <h1 style={{ fontSize: 42 }} data-testid="city-h1">{title}</h1>
                <p className="text-muted" style={{ maxWidth: 720 }}>{description}</p>
              </div>
            )}
            {artists.length === 0 ? (
              <div className="empty" style={{ padding: 40 }}>No artists listed for {city.name} yet — check back soon or <Link to="/search">browse all cities</Link>.</div>
            ) : (
              <div className="grid grid-4">
                {artists.map((a) => (
                  <Link to={`/artist/${a.slug || a.user_id}`} key={a.user_id} className="artist-card" data-testid={`city-card-${a.user_id}`} target="_blank" rel="noopener noreferrer">
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
