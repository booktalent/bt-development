import React, { useEffect, useMemo, useState } from "react";
import Nav from "../components/Nav";
import SEO, { buildBreadcrumb } from "../components/SEO";
import api from "../lib/api";

/**
 * /help — Public Help Center powered by the same FAQ data that the Admin
 * Panel manages. Search + category tabs + expand/collapse rows.
 */
export default function HelpCenter() {
  const [faqs, setFaqs] = useState([]);
  const [cats, setCats] = useState([]);
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState({});
  const [loading, setLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (cat && cat !== "all") params.set("category", cat);
    if (q) params.set("q", q);
    api.get(`/faqs/search?${params.toString()}`)
      .then((r) => setFaqs(r.data || []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    api.get("/faqs/categories").then((r) => setCats(r.data || []));
  }, []);
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [cat]);

  const submitSearch = (e) => {
    e?.preventDefault?.();
    reload();
  };

  const faqJsonLd = useMemo(() => ({
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: (faqs || []).slice(0, 20).map((f) => ({
      "@type": "Question",
      name: f.question,
      acceptedAnswer: { "@type": "Answer", text: f.answer },
    })),
  }), [faqs]);

  return (
    <div data-testid="help-center-page">
      <SEO
        title="Help Center — Frequently Asked Questions"
        description="Answers to the most common questions about booking artists on BookTalent, payments, cancellations, KYC and more."
        keywords="booktalent help, faq, artist booking help, payment help, cancellation policy"
        path="/help"
        jsonLd={[
          faqJsonLd,
          buildBreadcrumb([{ name: "Home", url: "/" }, { name: "Help Center", url: "/help" }]),
        ]}
      />
      <Nav />

      <section className="section container" style={{ paddingTop: 60, minHeight: "70vh" }}>
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <h1 style={{ fontSize: 42, marginBottom: 10 }}>Help Center</h1>
          <p className="text-muted" style={{ maxWidth: 640, margin: "0 auto" }}>
            Find answers to common questions about booking artists, payments, cancellations, and more.
          </p>
        </div>

        <form onSubmit={submitSearch} className="hero-search" style={{ marginBottom: 24 }} data-testid="help-search-form">
          <input
            type="search"
            placeholder="Search for topics…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            data-testid="help-search-input"
          />
          <button type="submit" className="btn btn-gold" data-testid="help-search-btn">Search →</button>
        </form>

        <div className="cat-strip mb-24" data-testid="help-cat-strip">
          <button className={`cat-chip ${cat === "all" ? "cat-chip-active" : ""}`} onClick={() => setCat("all")} data-testid="help-cat-all">All</button>
          {cats.map((c) => (
            <button key={c} className={`cat-chip ${cat === c ? "cat-chip-active" : ""}`} onClick={() => setCat(c)} data-testid={`help-cat-${c}`}>
              {c.charAt(0).toUpperCase() + c.slice(1)}
            </button>
          ))}
        </div>

        <div className="faq-list">
          {loading && <div className="skeleton" style={{ height: 260 }} />}
          {!loading && faqs.length === 0 && (
            <div className="empty" style={{ textAlign: "center", padding: 40 }}>
              No answers matched your search. Try a different keyword or contact <a href="/page/contact">Support</a>.
            </div>
          )}
          {faqs.map((f) => (
            <div key={f.id} className={`faq-row ${open[f.id] ? "open" : ""}`} data-testid={`faq-row-${f.id}`}>
              <button
                className="faq-q"
                onClick={() => setOpen({ ...open, [f.id]: !open[f.id] })}
                aria-expanded={!!open[f.id]}
                data-testid={`faq-toggle-${f.id}`}
              >
                <span>{f.question}</span>
                <span className="faq-caret">{open[f.id] ? "−" : "+"}</span>
              </button>
              {open[f.id] && (
                <div className="faq-a" data-testid={`faq-answer-${f.id}`}>
                  {f.answer}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
</div>
  );
}
