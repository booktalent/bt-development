import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";

/**
 * Dynamic footer — pulls the list of published CMS pages that are tagged
 * `footer_menu` and renders them alongside our static primary links.
 * Admin can add/reorder pages from the Admin Panel without redeploying.
 */
export default function Footer() {
  const [pages, setPages] = useState([]);
  const [cats, setCats] = useState([]);
  const [cities, setCities] = useState([]);

  useEffect(() => {
    api.get("/menu/footer").then((r) => setPages(r.data?.items || [])).catch(() => {});
    api.get("/categories").then((r) => setCats(Array.isArray(r.data) ? r.data : [])).catch(() => setCats([]));
    api.get("/cities").then((r) => {
      const raw = r.data || [];
      setCities(raw.map((c) => (typeof c === "string" ? { slug: c.toLowerCase().replace(/\s+/g, "-"), name: c } : c)));
    }).catch(() => setCities([]));
  }, []);

  return (
    <footer className="site-footer" data-testid="site-footer">
      <div className="footer-inner">
        <div className="footer-col">
          <div className="footer-brand">
            <div className="logo-mark">B</div>
            <span>Book<span className="gold">Talent</span></span>
          </div>
          <p className="footer-tag">India's #1 talent marketplace — a lead-generation platform charging only a 5% Platform Fee + 18% GST.</p>
        </div>

        <div className="footer-col">
          <div className="footer-h">Explore</div>
          <Link to="/search" data-testid="footer-link-search">Discover Artists</Link>
          <Link to="/blog" data-testid="footer-link-blog">Blog</Link>
          <Link to="/help" data-testid="footer-link-help">Help Center</Link>
          <Link to="/signup?role=artist" data-testid="footer-link-become-artist">Become an Artist</Link>
        </div>

        <div className="footer-col">
          <div className="footer-h">Top Categories</div>
          {cats.slice(0, 6).map((c) => (
            <Link key={c.slug} to={`/artists/${c.slug}`} data-testid={`footer-cat-${c.slug}`}>
              {c.name}
            </Link>
          ))}
        </div>

        <div className="footer-col">
          <div className="footer-h">Popular Cities</div>
          {cities.slice(0, 6).map((c) => (
            <Link key={c.slug} to={`/artists/city/${c.slug}`} data-testid={`footer-city-${c.slug}`}>
              Artists in {c.name}
            </Link>
          ))}
        </div>

        <div className="footer-col">
          <div className="footer-h">Company</div>
          {pages.length === 0 && <span className="text-muted fs-12">—</span>}
          {pages.map((p) => (
            <Link key={p.href} to={p.href} data-testid={`footer-cms-${p.href.replace(/\//g, "-")}`}>
              {p.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="footer-bottom">
        <div>© {new Date().getFullYear()} BookTalent · India's Premium Talent Marketplace</div>
        <div className="footer-legal">
          <Link to="/page/privacy" data-testid="footer-bottom-privacy">Privacy</Link>
          <Link to="/page/terms" data-testid="footer-bottom-terms">Terms</Link>
          <Link to="/page/refund-policy" data-testid="footer-bottom-refund">Refund</Link>
          <Link to="/page/contact" data-testid="footer-bottom-contact">Contact</Link>
        </div>
      </div>
    </footer>
  );
}
