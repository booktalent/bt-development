import React from "react";
import { Link } from "react-router-dom";

/**
 * 404 catch-all page. Wired as the last <Route> in App.js so React Router
 * survives Nginx's `try_files $uri /index.html;` on unknown paths.
 * Keeps the same dark-luxury aesthetic — no new colours, no new fonts.
 */
export default function NotFound() {
  return (
    <div className="center-viewport" data-testid="notfound-page" style={{ padding: "0 20px" }}>
      <div style={{ maxWidth: 520 }}>
        <div className="font-serif" style={{ fontSize: 96, fontWeight: 300, letterSpacing: 4, color: "var(--gold)", lineHeight: 1 }}>
          404
        </div>
        <h2 style={{ marginTop: 12, marginBottom: 8 }}>Page not found</h2>
        <p style={{ color: "var(--text-muted)", marginBottom: 24, fontSize: 14 }}>
          The page you're looking for either moved or never existed. Head back and
          find your next great artist.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
          <Link to="/" className="btn btn-gold" data-testid="notfound-home">Back to Home</Link>
          <Link to="/search" className="btn btn-ghost" data-testid="notfound-search">Discover Artists</Link>
        </div>
      </div>
    </div>
  );
}
