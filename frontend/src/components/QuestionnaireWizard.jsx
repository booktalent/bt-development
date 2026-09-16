import React, { useCallback, useEffect, useMemo, useState } from "react";
import api from "../lib/api";

/**
 * Guided step-by-step onboarding wizard driven entirely by the
 * /questionnaire/universal + /questionnaire/category/{slug} metadata.
 *
 * Saves after every section so the artist never loses progress.
 * Emits `onComplete(answers)` when the last section is submitted.
 */
export default function QuestionnaireWizard({ category, onComplete, initialAnswers = null, startSection = null }) {
  const [layer1, setLayer1] = useState([]);
  const [layer2, setLayer2] = useState([]);
  const [answers, setAnswers] = useState(initialAnswers || {});
  const [stepIdx, setStepIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  // Iter 73 — Sidebar dropdown items must be able to jump to ANY section
  // repeatedly (not just once), so we drive deep-linking from `startSection`
  // directly. The previous `deepLinkApplied` boolean guard swallowed every
  // click after the first — this bug is what the artist reported.
  const wizardRef = React.useRef(null);

  // Live category — starts from prop, follows the answer if the user picks one
  const liveCategory = answers.category || category;

  // Fetch Layer 1 + existing answers on mount
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get("/questionnaire/universal"),
      initialAnswers ? Promise.resolve({ data: initialAnswers }) : api.get("/questionnaire/answers/mine").catch(() => ({ data: {} })),
    ]).then(([u, mine]) => {
      if (cancelled) return;
      setLayer1(u.data || []);
      setAnswers({ ...(mine.data || {}), ...(initialAnswers || {}) });
      setLoading(false);
    }).catch((e) => {
      if (!cancelled) { setErr(e); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [initialAnswers]);

  // Re-fetch Layer 2 whenever the live category changes (either from prop or from
  // the user picking a new one in Layer 1). This is the "category sync" behavior.
  useEffect(() => {
    if (!liveCategory) { setLayer2([]); return; }
    let cancelled = false;
    api.get(`/questionnaire/category/${encodeURIComponent(liveCategory)}`)
      .then((r) => { if (!cancelled) setLayer2(r.data || []); })
      .catch(() => { if (!cancelled) setLayer2([]); });
    return () => { cancelled = true; };
  }, [liveCategory]);

  // Skip-logic helper: hide a question if `show_if` is set and doesn't match.
  // Supports: { question_id: value }, { question_id: [v1, v2] }, or the shortcut
  // { category: "DJ / Music Producer" } for category-specific gating.
  const shouldShow = useCallback((q) => {
    const cond = q.show_if;
    if (!cond || typeof cond !== "object") return true;
    for (const [key, expected] of Object.entries(cond)) {
      const actual = key === "category" ? liveCategory : answers[key];
      if (Array.isArray(expected)) {
        if (!expected.includes(actual)) return false;
      } else if (actual !== expected) {
        return false;
      }
    }
    return true;
  }, [liveCategory, answers]);

  // Group Layer 1 questions by section, keep original order per section
  const sections = useMemo(() => {
    const byS = new Map();
    for (const q of layer1) {
      if (!shouldShow(q)) continue;
      const s = q.section || "Other";
      if (!byS.has(s)) byS.set(s, []);
      byS.get(s).push(q);
    }
    const arr = Array.from(byS.entries()).map(([section, qs]) => ({ section, questions: qs }));
    const visibleLayer2 = layer2.filter(shouldShow);
    if (visibleLayer2.length > 0) arr.push({ section: liveCategory || "Category specifics", questions: visibleLayer2 });
    return arr;
  }, [layer1, layer2, liveCategory, shouldShow]);

  const totalSteps = sections.length;
  const current = sections[stepIdx];
  const isLast = stepIdx === totalSteps - 1;

  // Iter 73 — Deep-link support: whenever the parent updates `startSection`
  // (e.g. sidebar dropdown click), jump to that section AND smooth-scroll
  // the wizard body into view. This re-fires on EVERY prop change, so the
  // artist can keep clicking sidebar items to navigate — the previous
  // "one-shot" behaviour ignored every click after the first.
  useEffect(() => {
    if (!startSection || loading || sections.length === 0) return;
    const target = startSection.toLowerCase();
    const idx = sections.findIndex((s) => (s.section || "").toLowerCase() === target);
    if (idx >= 0) {
      setStepIdx(idx);
      // Scroll on the next paint so the newly-rendered section is in view.
      requestAnimationFrame(() => {
        wizardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [startSection, loading, sections]);

  const setAns = (id, val) => setAnswers((a) => ({ ...a, [id]: val }));

  // Validate required fields in the current section
  const missing = useMemo(() => {
    if (!current) return [];
    return current.questions.filter((q) => q.required && (answers[q.id] === undefined || answers[q.id] === "" || answers[q.id] === null));
  }, [current, answers]);

  const saveSection = async () => {
    if (!current) return true;
    const payload = {};
    current.questions.forEach((q) => {
      if (answers[q.id] !== undefined) payload[q.id] = answers[q.id];
    });
    try {
      setSaving(true);
      await api.post("/questionnaire/answers", { answers: payload });
      return true;
    } catch (e) {
      setErr(e);
      return false;
    } finally { setSaving(false); }
  };

  const next = async () => {
    if (missing.length > 0) return;
    const ok = await saveSection();
    if (!ok) return;
    if (isLast) {
      onComplete && onComplete(answers);
    } else {
      setStepIdx((i) => Math.min(totalSteps - 1, i + 1));
    }
  };

  if (loading) return <div className="card card-pad text-center">Loading your questionnaire…</div>;
  if (err) return <div className="card card-pad text-center text-muted">Couldn't load the questionnaire. Please refresh.</div>;
  if (!current) return null;

  return (
    <div className="q-wizard" data-testid="q-wizard" ref={wizardRef}>
      <div className="q-progress">
        {sections.map((s, i) => (
          <div
            key={s.section}
            className={`q-progress-step ${i === stepIdx ? "current" : ""} ${i < stepIdx ? "done" : ""}`}
            onClick={() => setStepIdx(i)}
            data-testid={`q-step-${i}`}
            title={s.section}
          >
            <div className="q-progress-dot">{i < stepIdx ? "✓" : i + 1}</div>
            <div className="q-progress-label">{s.section}</div>
          </div>
        ))}
      </div>

      <div className="card card-pad q-body" data-testid="q-body">
        <h2 className="font-serif fs-22 fw-700 mb-4">{current.section}</h2>
        <p className="text-muted fs-13 mb-20">Step {stepIdx + 1} of {totalSteps} · your answers save as you go</p>
        <div className="q-fields">
          {current.questions.map((q) => (
            <FieldRenderer key={q.id} q={q} value={answers[q.id]} onChange={(v) => setAns(q.id, v)} />
          ))}
        </div>
        {missing.length > 0 && (
          <div className="q-missing" data-testid="q-missing">
            Please fill in: <strong>{missing.map((m) => m.label).join(", ")}</strong>
          </div>
        )}
        <div className="flex justify-between mt-24">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setStepIdx((i) => Math.max(0, i - 1))}
            disabled={stepIdx === 0 || saving}
            data-testid="q-back"
          >← Back</button>
          <button
            type="button"
            className="btn btn-gold"
            onClick={next}
            disabled={missing.length > 0 || saving}
            data-testid="q-next"
          >
            {saving ? "Saving…" : isLast ? "Finish Onboarding →" : "Save & Continue →"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldRenderer({ q, value, onChange }) {
  const label = (
    <div className="field-label">
      {q.label}{q.required && <span className="text-gold" aria-label="required"> *</span>}
    </div>
  );
  switch (q.type) {
    case "textarea":
      return (
        <div className="field">
          {label}
          <textarea className="field-input" rows={4} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`q-${q.id}`} />
        </div>
      );
    case "select":
      return (
        <div className="field">
          {label}
          <select className="field-input" value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`q-${q.id}`}>
            <option value="">Select…</option>
            {(q.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      );
    case "multiselect":
      return (
        <div className="field">
          {label}
          <div className="q-multi">
            {(q.options || []).map((o) => {
              const arr = Array.isArray(value) ? value : [];
              const on = arr.includes(o);
              return (
                <button
                  type="button"
                  key={o}
                  className={`mult-chip ${on ? "active" : ""}`}
                  onClick={() => onChange(on ? arr.filter((x) => x !== o) : [...arr, o])}
                  data-testid={`q-${q.id}-${o}`}
                >
                  {o}
                </button>
              );
            })}
          </div>
        </div>
      );
    case "boolean":
    case "toggle":
      return (
        <div className="field q-bool">
          {label}
          <div className="q-multi">
            <button type="button" className={`mult-chip ${value === true ? "active" : ""}`} onClick={() => onChange(true)} data-testid={`q-${q.id}-yes`}>Yes</button>
            <button type="button" className={`mult-chip ${value === false ? "active" : ""}`} onClick={() => onChange(false)} data-testid={`q-${q.id}-no`}>No</button>
          </div>
        </div>
      );
    case "number":
      return (
        <div className="field">
          {label}
          <input type="number" step={q.step || 1} className="field-input" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} data-testid={`q-${q.id}`} />
        </div>
      );
    case "price":
      return (
        <div className="field">
          {label}
          <div className="q-price">
            <span className="q-price-prefix">₹</span>
            <input type="number" min="0" step="100" className="field-input" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} data-testid={`q-${q.id}`} />
          </div>
        </div>
      );
    case "time":
      return (
        <div className="field">
          {label}
          <input type="time" className="field-input" value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`q-${q.id}`} />
        </div>
      );
    case "date":
      return (
        <div className="field">
          {label}
          <input type="date" className="field-input" value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`q-${q.id}`} />
        </div>
      );
    case "file":
    case "photo":
    case "photos":
    case "video":
    case "videos":
    case "media":
    case "attachment":
    case "image":
      // Iter 55 — Photo / video / media questions must NEVER open a separate
      // upload dialog. Every artist upload flows through the Media & Photos
      // module so all assets live in one gallery + CDN pipeline.
      return (
        <div className="field">
          {label}
          <div className="q-file-hint" data-testid={`q-media-hint-${q.id}`}>
            <span style={{ fontSize: 18, marginRight: 8 }}>📸</span>
            <span>
              Upload happens on the <b>Media &amp; Photos</b> tab of your dashboard, so all your assets live in one gallery.
              Skip this here — we'll take you there right after you finish the questionnaire.
            </span>
          </div>
        </div>
      );
    case "info":
      return (
        <div className="field q-info">
          {label}
        </div>
      );
    case "tel":
    case "url":
    case "text":
    default:
      return (
        <div className="field">
          {label}
          <input type={q.type === "tel" ? "tel" : q.type === "url" ? "url" : "text"} className="field-input" value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={`q-${q.id}`} />
        </div>
      );
  }
}
