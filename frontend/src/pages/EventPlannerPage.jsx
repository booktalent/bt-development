import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Nav from "../components/Nav";
import api from "../lib/api";
import { useToast } from "../lib/toast";

/**
 * Iter 46 — AI Event Planner
 * Standalone /planner route. Customer fills a short brief, we hit
 * POST /api/event-planner/suggest (Claude Sonnet 4.6) and render:
 *   • A headline & rationale
 *   • Priority-sorted artist categories (must-have / strong pick / optional)
 *   • Suggested add-ons
 * Each category card has an "Explore Artists →" CTA that deep-links to the
 * Discover Artists page pre-filtered by that category + city + date, so the
 * customer can jump into the multi-artist cart in one hop.
 */
export default function EventPlannerPage() {
  const nav = useNavigate();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [plan, setPlan] = useState(null);
  const [preview, setPreview] = useState(null);       // best-fit resolved artists
  const [previewLoading, setPreviewLoading] = useState(false);
  const [form, setForm] = useState({
    event_type: "Wedding",
    guests: 400,
    budget_min: 400000,
    budget_max: 800000,
    city: "Mumbai",
    event_date: "",
    notes: "",
  });

  useEffect(() => { document.title = "AI Event Planner · BookTalent"; }, []);

  // Iter 48 — Cart Preview + Urgency Badges
  // After a plan renders, resolve LLM categories → concrete artists so we can:
  //  (a) show real "Priya ₹25k · Vortex ₹18k" line-up on the Add-All button
  //  (b) red-badge any category where zero artists are available on the date
  useEffect(() => {
    if (!plan?.categories?.length) { setPreview(null); return; }
    let cancelled = false;
    setPreviewLoading(true);
    api.post("/event-planner/best-fit", {
      categories: plan.categories.map((c) => c.category),
      city: form.city,
      event_date: form.event_date || null,
    }).then((r) => { if (!cancelled) setPreview(r.data || []); })
      .catch(() => { if (!cancelled) setPreview([]); })
      .finally(() => { if (!cancelled) setPreviewLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan]);

  // Look up the resolved artist for a plan category so we can render the
  // urgency badge and per-category name/price directly under each cat card.
  const previewForCategory = (label) => {
    if (!preview) return null;
    return preview.find((x) => x.category === label) || null;
  };
  const matchedPreview = React.useMemo(
    () => (preview || []).filter((x) => x.matched && x.package_id),
    [preview]
  );
  const previewTotal = matchedPreview.reduce((s, x) => s + Number(x.starting_price || 0), 0);
  const previewLabel = matchedPreview.length
    ? matchedPreview.slice(0, 3).map((x) => {
        const first = (x.stage_name || "").split(" ")[0] || "?";
        const price = x.starting_price ? `₹${Math.round(x.starting_price / 1000)}k` : "";
        return price ? `${first} ${price}` : first;
      }).join(" · ") + (matchedPreview.length > 3 ? ` · +${matchedPreview.length - 3}` : "")
    : "";

  const upd = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e?.preventDefault?.();
    setBusy(true);
    setPlan(null);
    try {
      const body = {
        ...form,
        guests: form.guests ? Number(form.guests) : null,
        budget_min: form.budget_min ? Number(form.budget_min) : null,
        budget_max: form.budget_max ? Number(form.budget_max) : null,
      };
      const r = await api.post("/event-planner/suggest", body);
      setPlan(r.data);
    } catch (err) {
      toast(err?.response?.data?.detail || "Could not generate plan — please try again", "error");
    } finally {
      setBusy(false);
    }
  };

  const exploreCategory = (cat) => {
    const p = new URLSearchParams();
    const cleaned = (cat || "").split("/")[0].trim();
    if (cleaned) p.set("category", cleaned);
    if (form.city) p.set("city", form.city);
    if (form.event_date) p.set("date", form.event_date);
    nav(`/discover?${p.toString()}`);
  };

  // Iter 47/48 — One-tap "Add all to cart": uses the preview we already
  // resolved (via useEffect above) so this handler is fast + deterministic.
  const addAllToCart = async () => {
    if (!plan) return;
    setSeeding(true);
    try {
      const matched = matchedPreview;
      if (matched.length === 0) {
        toast("No available artists match your line-up right now — try adjusting date or city", "error");
        return;
      }
      const [primary, ...rest] = matched;
      const secondaries = rest.map((a) => ({
        artist_id: a.user_id,
        artist_name: a.stage_name,
        artist_photo: a.profile_image
          ? (/^https?:\/\//.test(a.profile_image) ? a.profile_image : `${api.defaults.baseURL}/media/${a.profile_image}`)
          : null,
        category: a.category,
        city: a.city,
        emoji: a.emoji || "🎤",
        package_id: a.package_id,
        package_name: "Base Package",
        package_price: a.starting_price || 0,
        addon_selections: [],
        price_subtotal: a.starting_price || 0,
      }));
      try {
        localStorage.setItem(`bt_event_cart_${primary.user_id}`, JSON.stringify({
          items: secondaries,
          saved_at: Date.now(),
          from_planner: true,
        }));
      } catch { /* localStorage disabled */ }
      const qs = new URLSearchParams();
      if (primary.package_id) qs.set("pkg", primary.package_id);
      if (form.event_date) qs.set("date", form.event_date);
      if (form.city) qs.set("city", form.city);
      if (form.event_type) qs.set("event_type", form.event_type);
      toast(`Cart seeded with ${matched.length} artist${matched.length > 1 ? "s" : ""} — one checkout to go!`, "success");
      nav(`/book/${primary.user_id}?${qs.toString()}`);
    } catch (e) {
      toast(e?.response?.data?.detail || "Could not seed your cart — please try again", "error");
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0b0a12" }} data-testid="planner-page">
      <Nav />
      <div className="planner-hero">
        <div className="planner-container">
          <span className="planner-badge">✨ AI Event Planner</span>
          <h1 className="planner-title font-serif">Tell us about your event.<br />We'll design the perfect line-up.</h1>
          <p className="planner-sub">Powered by Claude — get instant artist mix + add-on recommendations tuned to your event type, guest count and budget.</p>
        </div>
      </div>

      <div className="planner-container planner-body">
        <div className="planner-grid">
          {/* ─── Brief form ────────────────────────────────────────────── */}
          <form className="planner-form" onSubmit={submit} data-testid="planner-form">
            <div className="planner-form-title">Event brief</div>

            <label className="planner-field">
              <span>Event Type</span>
              <select value={form.event_type} onChange={upd("event_type")} data-testid="planner-event-type">
                <option>Wedding</option>
                <option>Sangeet</option>
                <option>Reception</option>
                <option>Corporate</option>
                <option>Birthday</option>
                <option>Anniversary</option>
                <option>Festival / Community</option>
                <option>Private Party</option>
              </select>
            </label>

            <div className="planner-row">
              <label className="planner-field">
                <span>Guest Count</span>
                <input type="number" min="1" value={form.guests} onChange={upd("guests")} data-testid="planner-guests" />
              </label>
              <label className="planner-field">
                <span>City</span>
                <input type="text" value={form.city} onChange={upd("city")} data-testid="planner-city" />
              </label>
            </div>

            <label className="planner-field">
              <span>Event Date (optional)</span>
              <input type="date" value={form.event_date} onChange={upd("event_date")} data-testid="planner-date" />
            </label>

            <div className="planner-form-title" style={{ marginTop: 20 }}>Budget (INR)</div>
            <div className="planner-row">
              <label className="planner-field">
                <span>Min</span>
                <input type="number" min="0" step="10000" value={form.budget_min} onChange={upd("budget_min")} data-testid="planner-budget-min" />
              </label>
              <label className="planner-field">
                <span>Max</span>
                <input type="number" min="0" step="10000" value={form.budget_max} onChange={upd("budget_max")} data-testid="planner-budget-max" />
              </label>
            </div>

            <label className="planner-field">
              <span>Vibe / theme <span className="text-muted fs-11">(optional, e.g. "Bollywood + Sufi, 3-day")</span></span>
              <textarea rows={3} value={form.notes} onChange={upd("notes")} data-testid="planner-notes" maxLength={400} />
            </label>

            <button type="submit" className="btn btn-gold btn-lg" disabled={busy} data-testid="planner-submit">
              {busy ? "Curating your line-up…" : "✨ Generate my line-up"}
            </button>
          </form>

          {/* ─── Result panel ─────────────────────────────────────────── */}
          <div className="planner-result">
            {!plan && !busy && (
              <div className="planner-empty">
                <div style={{ fontSize: 56 }}>🎪</div>
                <div className="fw-700 fs-16 mt-12">Ready when you are</div>
                <p className="text-muted fs-13 mt-8">Fill the brief on the left and we'll craft an event line-up in seconds — including must-have artists, strong picks, and add-ons tuned to your budget.</p>
              </div>
            )}
            {busy && (
              <div className="planner-empty">
                <div className="planner-spinner" />
                <div className="fw-700 fs-15 mt-16">Curating your line-up…</div>
                <div className="text-muted fs-12 mt-4">This usually takes 3-5 seconds.</div>
              </div>
            )}
            {plan && (
              <div data-testid="planner-plan">
                <div className="planner-plan-source">
                  {plan.source === "llm" ? "✨ Curated by Claude" : "🧭 Curated by BookTalent"}
                </div>
                <h2 className="planner-plan-headline font-serif" data-testid="planner-headline">{plan.headline}</h2>
                <p className="planner-plan-rationale">{plan.rationale}</p>
                {plan.approx_budget && (
                  <div className="planner-budget-pill">Budget: {plan.approx_budget}</div>
                )}

                <div className="planner-add-all-row" data-testid="planner-add-all-row">
                  <button
                    className="btn btn-gold btn-lg planner-add-all-btn"
                    onClick={addAllToCart}
                    disabled={seeding || previewLoading || matchedPreview.length === 0}
                    data-testid="planner-add-all"
                    title="Auto-fill your event cart with the best available artist for every recommended category, and jump straight to checkout"
                  >
                    {seeding ? "Building your cart…"
                      : previewLoading ? "Checking availability…"
                      : matchedPreview.length === 0
                        ? "No artists available for these categories"
                        : `🛒 Add all ${matchedPreview.length} to cart · ₹${Math.round(previewTotal / 1000)}k`}
                  </button>
                  {previewLabel && (
                    <span className="planner-preview-line" data-testid="planner-preview-line">
                      {previewLabel}
                    </span>
                  )}
                </div>

                <div className="planner-section-title">Recommended Line-up</div>
                <div className="planner-cats" data-testid="planner-categories">
                  {plan.categories.map((c, i) => {
                    const p = previewForCategory(c.category);
                    const soldOut = !previewLoading && preview && (!p || !p.matched);
                    const matched = p?.matched && p?.package_id;
                    // Iter 73 — When we've matched a real artist for this
                    // category, make the ENTIRE card clickable → opens
                    // that artist's profile in a new tab. Non-matched
                    // (sold-out or category-only) cards stay display-only.
                    const openArtist = () => {
                      if (matched && p?.user_id) {
                        window.open(`/artist/${p.user_id}`, "_blank", "noopener,noreferrer");
                      }
                    };
                    return (
                    <div
                      key={`${c.category}-${i}`}
                      className={`planner-cat prio-${c.priority} ${soldOut ? "sold-out" : ""} ${matched ? "clickable" : ""}`}
                      data-testid={`planner-cat-${i}`}
                      onClick={matched ? openArtist : undefined}
                      onKeyDown={matched ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openArtist(); } } : undefined}
                      role={matched ? "link" : undefined}
                      tabIndex={matched ? 0 : undefined}
                      title={matched ? `Open ${p.stage_name}'s profile in a new tab` : undefined}
                    >
                      <div className="planner-cat-head">
                        <span className="planner-cat-name">{c.category}</span>
                        {soldOut ? (
                          <span className="planner-prio planner-soldout-pill" data-testid={`planner-soldout-${i}`}>
                            ⚠ 0 available{form.event_date ? " on this date" : ""}
                          </span>
                        ) : (
                          <span className={`planner-prio prio-${c.priority}`}>
                            {c.priority === 1 ? "Must-have" : c.priority === 2 ? "Strong pick" : "Optional"}
                          </span>
                        )}
                      </div>
                      <p className="planner-cat-reason">{c.reason}</p>
                      {matched && (
                        <div className="planner-cat-match" data-testid={`planner-match-${i}`}>
                          <span className="planner-cat-match-emoji">{p.emoji || "🎤"}</span>
                          <span className="planner-cat-match-name">{p.stage_name}</span>
                          {p.starting_price && (
                            <span className="planner-cat-match-price">from ₹{Math.round(p.starting_price / 1000)}k</span>
                          )}
                        </div>
                      )}
                      <button className="planner-explore-btn" onClick={(e) => { e.stopPropagation(); exploreCategory(c.category); }} data-testid={`planner-explore-${i}`}>
                        Explore {c.category}s →
                      </button>
                    </div>
                  );})}
                </div>

                {plan.addons.length > 0 && (
                  <>
                    <div className="planner-section-title" style={{ marginTop: 24 }}>Smart Add-ons</div>
                    <div className="planner-addons" data-testid="planner-addons">
                      {plan.addons.map((a, i) => (
                        <div key={`${a.name}-${i}`} className="planner-addon" data-testid={`planner-addon-${i}`}>
                          <div className="planner-addon-name">✨ {a.name}</div>
                          <div className="planner-addon-reason">{a.reason}</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
