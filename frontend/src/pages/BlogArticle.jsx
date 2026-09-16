import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import DOMPurify from "dompurify";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import api from "../lib/api";

/**
 * /blog/:slug — Individual blog article with SEO metadata + Article JSON-LD.
 */
export default function BlogArticle() {
  const { slug } = useParams();
  const [blog, setBlog] = useState(null);
  const [related, setRelated] = useState([]);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setBlog(null); setNotFound(false);
    api.get(`/blogs/${slug}`).then((r) => setBlog(r.data))
      .catch((e) => { if (e?.response?.status === 404) setNotFound(true); });
    api.get("/blogs").then((r) => setRelated((r.data || []).filter(b => b.slug !== slug).slice(0, 3))).catch(() => {});
  }, [slug]);

  const safeContent = useMemo(() => DOMPurify.sanitize(blog?.content || ""), [blog?.content]);

  const share = (network) => {
    const url = encodeURIComponent(window.location.href);
    const title = encodeURIComponent(blog?.title || "");
    const links = {
      twitter: `https://twitter.com/intent/tweet?url=${url}&text=${title}`,
      linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${url}`,
      whatsapp: `https://wa.me/?text=${title}%20${url}`,
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${url}`,
    };
    window.open(links[network], "_blank", "noopener,noreferrer,width=600,height=500");
  };

  if (notFound) {
    return (
      <div>
        <SEO title="Article Not Found" noindex path={`/blog/${slug}`} />
        <Nav />
        <section className="section container" style={{ minHeight: "50vh", textAlign: "center", paddingTop: 80 }}>
          <div style={{ fontSize: 72 }}>📝</div>
          <h1 style={{ fontSize: 36 }}>Article Not Found</h1>
          <Link to="/blog" className="btn btn-gold" data-testid="blog-back">← Back to Blog</Link>
        </section>
</div>
    );
  }

  const desc = blog?.excerpt || (blog?.content ? blog.content.replace(/<[^>]+>/g, "").slice(0, 160) : "");

  const articleLd = blog ? {
    "@context": "https://schema.org", "@type": "Article",
    headline: blog.title,
    description: desc,
    image: blog.cover_image || "https://booktalent.com/og-cover.png",
    author: { "@type": "Person", name: blog.author || "BookTalent Editorial" },
    publisher: { "@type": "Organization", name: "BookTalent", logo: { "@type": "ImageObject", url: "https://booktalent.com/logo.png" } },
    datePublished: blog.created_at,
    dateModified: blog.updated_at || blog.created_at,
    mainEntityOfPage: `https://booktalent.com/blog/${blog.slug}`,
  } : null;

  return (
    <div data-testid={`blog-article-${slug}`}>
      <SEO
        title={blog?.title || "Article"}
        description={desc}
        keywords={(blog?.tags || []).join(", ")}
        image={blog?.cover_image}
        path={`/blog/${slug}`}
        jsonLd={blog ? [articleLd, buildBreadcrumb([
          { name: "Home", url: "/" },
          { name: "Blog", url: "/blog" },
          { name: blog.title, url: `/blog/${slug}` },
        ])] : null}
      />
      <Nav />
      {blog && (blog.hero_image || blog.hero_title) && (
        <div
          className="page-hero"
          data-testid="blog-article-hero"
          style={{
            backgroundImage: blog.hero_image
              ? `linear-gradient(180deg, rgba(0,0,0,0.35), rgba(0,0,0,0.7)), url(${blog.hero_image})`
              : undefined,
          }}
        >
          <div className="page-hero-inner">
            <h1 data-testid="blog-hero-h1">{blog.hero_title || blog.title}</h1>
            {(blog.hero_subtitle || blog.excerpt) && (
              <p data-testid="blog-hero-sub">{blog.hero_subtitle || blog.excerpt}</p>
            )}
            {blog.hero_cta_url && (
              <a href={blog.hero_cta_url} className="btn btn-gold" data-testid="blog-article-hero-cta">
                {blog.hero_cta_label || "Read on"} →
              </a>
            )}
          </div>
        </div>
      )}
      <section className="section container" style={{ paddingTop: blog && (blog.hero_image || blog.hero_title) ? 20 : 60, minHeight: "60vh", maxWidth: 820, margin: "0 auto" }}>
        {!blog && <div className="skeleton" style={{ height: 400 }} />}
        {blog && (
          <>
            {blog.cover_image && !(blog.hero_image || blog.hero_title) && (
              <div style={{ height: 360, background: `url(${blog.cover_image}) center/cover`, borderRadius: 12, marginBottom: 24 }} />
            )}
            {!(blog.hero_image || blog.hero_title) && (
              <h1 style={{ fontSize: 42, marginBottom: 12 }} data-testid="blog-title">{blog.title}</h1>
            )}
            <div className="text-muted fs-13 mb-24" data-testid="blog-meta">
              {blog.author || "BookTalent Editorial"} · {(blog.created_at || "").slice(0, 10)}
            </div>
            {blog.tags?.length > 0 && (
              <div style={{ marginBottom: 20 }}>
                {blog.tags.map(t => <span key={t} className="pill pill-purple" style={{ marginRight: 6 }}>#{t}</span>)}
              </div>
            )}
            <div className="cms-body" data-testid="blog-body" dangerouslySetInnerHTML={{ __html: safeContent }} />

            <div className="share-bar" style={{ marginTop: 32 }}>
              <span className="text-muted fs-13" style={{ marginRight: 12 }}>Share:</span>
              <button className="btn btn-ghost btn-xs" onClick={() => share("twitter")} data-testid="share-twitter">Twitter</button>
              <button className="btn btn-ghost btn-xs" onClick={() => share("linkedin")} data-testid="share-linkedin">LinkedIn</button>
              <button className="btn btn-ghost btn-xs" onClick={() => share("whatsapp")} data-testid="share-whatsapp">WhatsApp</button>
              <button className="btn btn-ghost btn-xs" onClick={() => share("facebook")} data-testid="share-facebook">Facebook</button>
            </div>

            {related.length > 0 && (
              <div style={{ marginTop: 60 }}>
                <h3 style={{ fontSize: 24, marginBottom: 16 }}>Related Articles</h3>
                <div className="grid grid-3">
                  {related.map((r) => (
                    <Link key={r.id} to={`/blog/${r.slug}`} className="artist-card" data-testid={`blog-related-${r.slug}`}>
                      <div className="artist-card-cover" style={{ background: `url(${r.cover_image || ""}) center/cover, linear-gradient(135deg, rgba(212,175,55,0.2), rgba(109,40,217,0.1))` }}>
                        {!r.cover_image && <span style={{ fontSize: 48 }}>📝</span>}
                      </div>
                      <div className="artist-card-body">
                        <div className="artist-card-name" style={{ fontSize: 15 }}>{r.title}</div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>
</div>
  );
}
