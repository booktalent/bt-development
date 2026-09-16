import React from "react";
import { Helmet } from "react-helmet-async";

/**
 * <SEO>  — Iter 39
 * Reusable head-meta helper. Every public route should render one to make
 * BookTalent search-engine friendly. Falls back to sensible defaults so
 * unrouted pages never leak an empty <title> or missing OG image.
 */
const SITE_NAME = "BookTalent";
const SITE_URL = "https://booktalent.com";
const DEFAULT_TITLE = "BookTalent — Book India's Finest Talent";
const DEFAULT_DESC =
  "BookTalent — India's #1 talent marketplace. Book verified singers, DJs, comedians, dancers and anchors for weddings, corporate events, concerts and private parties.";
const DEFAULT_IMAGE = `${SITE_URL}/og-cover.png`;

export default function SEO({
  title,
  description,
  keywords,
  image,
  canonical,
  path,           // path relative to site root, e.g. "/artist/priya-sharma-…"
  noindex = false,
  jsonLd,         // object or array of JSON-LD objects
}) {
  const fullTitle = title
    ? `${title} · ${SITE_NAME}`
    : DEFAULT_TITLE;
  const desc = description || DEFAULT_DESC;
  const img = image || DEFAULT_IMAGE;
  // For dev previews we can't reliably know the public host — construct a
  // sensible canonical from the current location when we're not given one.
  const url =
    canonical ||
    (path
      ? `${SITE_URL}${path}`
      : typeof window !== "undefined"
      ? window.location.origin + window.location.pathname
      : SITE_URL);
  const ldItems = Array.isArray(jsonLd) ? jsonLd : jsonLd ? [jsonLd] : [];

  return (
    <Helmet>
      <title>{fullTitle}</title>
      <meta name="description" content={desc} />
      {keywords && <meta name="keywords" content={keywords} />}
      <link rel="canonical" href={url} />
      {noindex && <meta name="robots" content="noindex, nofollow" />}

      {/* Open Graph */}
      <meta property="og:site_name" content={SITE_NAME} />
      <meta property="og:type" content="website" />
      <meta property="og:title" content={fullTitle} />
      <meta property="og:description" content={desc} />
      <meta property="og:url" content={url} />
      <meta property="og:image" content={img} />

      {/* Twitter */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={fullTitle} />
      <meta name="twitter:description" content={desc} />
      <meta name="twitter:image" content={img} />

      {/* Organization JSON-LD (repeated on every page for consistent E-E-A-T) */}
      <script type="application/ld+json">
        {JSON.stringify({
          "@context": "https://schema.org",
          "@type": "Organization",
          name: SITE_NAME,
          url: SITE_URL,
          logo: `${SITE_URL}/logo.png`,
          sameAs: [
            "https://www.instagram.com/booktalent",
            "https://www.linkedin.com/company/booktalent",
          ],
        })}
      </script>

      {ldItems.map((obj, i) => (
        <script key={`ld-${obj?.["@type"] || "obj"}-${i}`} type="application/ld+json">
          {JSON.stringify(obj)}
        </script>
      ))}
    </Helmet>
  );
}

/**
 * BreadcrumbList helper. Pass an array of `{name, url}` items — first should
 * always be Home.
 */
export function buildBreadcrumb(items) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, idx) => ({
      "@type": "ListItem",
      position: idx + 1,
      name: it.name,
      item: it.url.startsWith("http") ? it.url : `${SITE_URL}${it.url}`,
    })),
  };
}
