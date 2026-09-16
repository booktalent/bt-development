import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import api from "../lib/api";

/**
 * /blog — SEO-optimised blog index. Pulls from GET /api/blogs.
 */
export default function BlogList() {
  const [blogs, setBlogs] = useState(null);
  const [settings, setSettings] = useState({});
  useEffect(() => {
    api.get("/blogs").then((r) => setBlogs(r.data || [])).catch(() => setBlogs([]));
    api.get("/settings/public").then((r) => setSettings(r.data || {})).catch(() => {});
  }, []);

  const heroImg = settings.blog_hero_image;
  const heroTitle = settings.blog_hero_title || "The BookTalent Blog";
  const heroSubtitle = settings.blog_hero_subtitle || "Guides, artist spotlights and industry news to help you plan the perfect event.";
  const heroCtaLabel = settings.blog_hero_cta_label;
  const heroCtaUrl = settings.blog_hero_cta_url;

  return (
    <div data-testid="blog-list-page">
      <SEO
        title="BookTalent Blog — Tips, News & Guides"
        description="Read expert guides on booking artists, planning weddings, corporate events and private parties. Stay updated with BookTalent."
        keywords="booktalent blog, event planning, wedding artists, corporate events"
        path="/blog"
        jsonLd={buildBreadcrumb([{ name: "Home", url: "/" }, { name: "Blog", url: "/blog" }])}
      />
      <Nav />
      <div
        className="page-hero"
        data-testid="blog-hero"
        style={{
          backgroundImage: heroImg
            ? `linear-gradient(180deg, rgba(0,0,0,0.35), rgba(0,0,0,0.65)), url(${heroImg})`
            : undefined,
        }}
      >
        <div className="page-hero-inner">
          <h1 data-testid="blog-hero-title">{heroTitle}</h1>
          <p data-testid="blog-hero-subtitle">{heroSubtitle}</p>
          {heroCtaUrl && (
            <a href={heroCtaUrl} className="btn btn-gold" data-testid="blog-hero-cta">
              {heroCtaLabel || "Explore"} →
            </a>
          )}
        </div>
      </div>
      <section className="section container" style={{ paddingTop: 40, minHeight: "40vh" }}>
        {!blogs && <div className="skeleton" style={{ height: 300 }} />}
        {blogs?.length === 0 && (
          <div className="empty" style={{ padding: 40, textAlign: "center" }}>
            No articles yet — check back soon.
          </div>
        )}
        <div className="grid grid-3">
          {(blogs || []).map((b) => (
            <Link key={b.id} to={`/blog/${b.slug}`} className="artist-card" data-testid={`blog-card-${b.slug}`}>
              <div className="artist-card-cover" style={{ background: `url(${b.cover_image || ""}) center/cover, linear-gradient(135deg, rgba(212,175,55,0.2), rgba(109,40,217,0.1))` }}>
                {!b.cover_image && <span style={{ fontSize: 64 }}>📝</span>}
              </div>
              <div className="artist-card-body">
                <div className="artist-card-name">{b.title}</div>
                {b.excerpt && <div className="artist-card-meta" style={{ marginTop: 4 }}>{b.excerpt.slice(0, 120)}</div>}
                <div className="artist-card-foot" style={{ marginTop: 8 }}>
                  <span className="text-muted fs-12">
                    {b.author || "BookTalent Editorial"} · {(b.created_at || "").slice(0, 10)}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>
</div>
  );
}
