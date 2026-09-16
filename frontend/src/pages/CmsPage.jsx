import React, { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import DOMPurify from "dompurify";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import api from "../lib/api";

/**
 * /page/:slug — Renders any CMS page created from the Admin Panel.
 * SEO: dynamic title/desc/keywords/OG + WebPage & BreadcrumbList JSON-LD.
 */
export default function CmsPage() {
  const { slug } = useParams();
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setPage(null);
    setError(null);
    api.get(`/cms/pages/${slug}`)
      .then((r) => setPage(r.data))
      .catch((e) => setError(e?.response?.status === 404 ? "Not Found" : "Failed to load"));
  }, [slug]);

  const safeHtml = useMemo(() => DOMPurify.sanitize(page?.body_html || ""), [page?.body_html]);

  if (error === "Not Found") {
    return (
      <div>
        <SEO title="Page Not Found" noindex path={`/page/${slug}`} />
        <Nav />
        <section className="section container" style={{ minHeight: "60vh", textAlign: "center", paddingTop: 80 }}>
          <div style={{ fontSize: 72 }}>📄</div>
          <h1 style={{ fontSize: 36 }}>Page Not Found</h1>
          <p className="text-muted mb-20">The page you're looking for doesn't exist or has been unpublished.</p>
          <Link to="/" className="btn btn-gold" data-testid="cms-back-home">← Back to Home</Link>
        </section>
</div>
    );
  }

  const title = page?.seo_title || page?.title || slug;
  const desc = page?.meta_description || page?.title || "";
  let extraLd = null;
  if (page?.schema_json) {
    try { extraLd = JSON.parse(page.schema_json); } catch (_) { extraLd = null; }
  }

  return (
    <div data-testid={`cms-page-${slug}`}>
      <SEO
        title={title}
        description={desc}
        keywords={page?.seo_keywords || ""}
        image={page?.og_image || undefined}
        canonical={page?.canonical || undefined}
        path={`/page/${slug}`}
        jsonLd={[
          {
            "@context": "https://schema.org",
            "@type": "WebPage",
            name: title,
            description: desc,
            url: `https://booktalent.com/page/${slug}`,
          },
          buildBreadcrumb([
            { name: "Home", url: "/" },
            { name: title, url: `/page/${slug}` },
          ]),
          ...(extraLd ? [extraLd] : []),
        ]}
      />
      <Nav />
      <section className="section container" style={{ paddingTop: page?.hero_image || page?.hero_title ? 0 : 60, minHeight: "60vh" }}>
        <div className="cms-content">
          {!page ? (
            <div className="skeleton" style={{ height: 400 }} />
          ) : (
            <>
              {(page.hero_image || page.hero_title) && (
                <div
                  className="page-hero"
                  data-testid="cms-hero"
                  style={{
                    backgroundImage: page.hero_image ? `linear-gradient(180deg, rgba(0,0,0,0.35), rgba(0,0,0,0.6)), url(${page.hero_image})` : undefined,
                  }}
                >
                  <div className="page-hero-inner">
                    <h1 data-testid="cms-hero-title">{page.hero_title || page.title}</h1>
                    {page.hero_subtitle && <p data-testid="cms-hero-subtitle">{page.hero_subtitle}</p>}
                    {page.hero_cta_url && (
                      <a href={page.hero_cta_url} className="btn btn-gold" data-testid="cms-hero-cta">
                        {page.hero_cta_label || "Learn more"} →
                      </a>
                    )}
                  </div>
                </div>
              )}
              {!(page.hero_image || page.hero_title) && (
                <h1 style={{ fontSize: 42, marginBottom: 12 }} data-testid="cms-title">{page.title}</h1>
              )}
              {page.updated_at && (
                <div className="text-muted fs-12 mb-24" data-testid="cms-updated">
                  Last updated: {String(page.updated_at).slice(0, 10)}
                </div>
              )}
              <div
                className="cms-body"
                data-testid="cms-body"
                dangerouslySetInnerHTML={{ __html: safeHtml }}
              />
            </>
          )}
        </div>
      </section>
</div>
  );
}
