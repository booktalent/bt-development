import React, { useEffect, useMemo, useState } from "react";
import api from "../../lib/api";

const FIELD_TYPES = ["text", "textarea", "select", "multiselect", "boolean", "number", "tel", "url"];
const CATEGORY_SLUGS = [
  "Bollywood Vocalist", "Classical Vocalist", "DJ / Music Producer",
  "Stand-up Comedian", "Anchor / Emcee", "Dancer / Troupe",
  "Live Band", "Magician", "Folk Artist",
];

/**
 * Admin question editor for Layer 1 + Layer 2 questionnaires.
 * - Lists every question with inline edit (label, type, required, options)
 * - Reorder with ↑ / ↓ buttons (drag-drop deferred for a UX pass)
 * - Add / delete questions
 * - Saves the whole set via PUT so it's atomic.
 */
export default function AdminQuestionEditor() {
  const [target, setTarget] = useState("universal"); // "universal" | "cat:{slug}"
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  const isCat = target.startsWith("cat:");
  const catSlug = isCat ? target.slice(4) : null;

  useEffect(() => {
    setLoading(true);
    const url = isCat ? `/questionnaire/category/${encodeURIComponent(catSlug)}` : "/questionnaire/universal";
    api.get(url).then((r) => setQuestions(r.data || [])).finally(() => setLoading(false));
  }, [target, isCat, catSlug]);

  const move = (i, delta) => {
    const next = [...questions];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    // Rebuild order numbers to keep them stable
    next.forEach((q, idx) => { q.order = (idx + 1) * 10; });
    setQuestions(next);
  };

  const patch = (i, key, val) => {
    const next = [...questions];
    next[i] = { ...next[i], [key]: val };
    setQuestions(next);
  };

  const addQuestion = () => {
    const nextOrder = (questions.length + 1) * 10;
    setQuestions([...questions, {
      id: `q_${Date.now()}`,
      section: isCat ? catSlug : "New Section",
      label: "New question",
      type: "text",
      required: false,
      order: nextOrder,
    }]);
  };

  const removeQuestion = (i) => {
    if (!window.confirm("Delete this question?")) return;
    const next = questions.filter((_, idx) => idx !== i);
    setQuestions(next);
  };

  const save = async () => {
    setSaving(true);
    try {
      const url = isCat ? `/admin/questionnaire/category/${encodeURIComponent(catSlug)}` : "/admin/questionnaire/universal";
      await api.put(url, { questions });
      setToast("Saved ✓");
      setTimeout(() => setToast(null), 2000);
    } catch (e) {
      setToast("Save failed");
      setTimeout(() => setToast(null), 2500);
    } finally { setSaving(false); }
  };

  const grouped = useMemo(() => {
    const g = new Map();
    questions.forEach((q, idx) => {
      const s = q.section || "Other";
      if (!g.has(s)) g.set(s, []);
      g.get(s).push({ q, idx });
    });
    return Array.from(g.entries());
  }, [questions]);

  return (
    <div data-testid="admin-question-editor">
      <div className="flex justify-between items-center mb-16 gap-12" style={{ flexWrap: "wrap" }}>
        <div>
          <h2 className="font-serif fs-22 fw-700">Onboarding Questionnaire Builder</h2>
          <p className="text-muted fs-12">Add, edit, reorder questions. Changes go live instantly for new onboardings.</p>
        </div>
        <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
          <select className="field-input" value={target} onChange={(e) => setTarget(e.target.value)} data-testid="qb-target" style={{ minWidth: 220 }}>
            <option value="universal">Layer 1 — Universal</option>
            {CATEGORY_SLUGS.map((c) => <option key={c} value={`cat:${c}`}>Layer 2 — {c}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={addQuestion} data-testid="qb-add">+ Add Question</button>
          <button className="btn btn-gold" onClick={save} disabled={saving} data-testid="qb-save">
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>
      {toast && <div className="qb-toast" data-testid="qb-toast">{toast}</div>}
      {loading ? (
        <div className="card card-pad text-center">Loading…</div>
      ) : (
        <div className="qb-groups">
          {grouped.map(([section, rows]) => (
            <div key={section} className="card qb-group">
              <div className="qb-group-head">
                <h3 className="fw-700">{section}</h3>
                <span className="text-muted fs-11">{rows.length} question(s)</span>
              </div>
              {rows.map(({ q, idx }) => (
                <div key={q.id || idx} className="qb-row" data-testid={`qb-row-${q.id}`}>
                  <div className="qb-row-controls">
                    <button className="btn btn-ghost btn-xs" onClick={() => move(idx, -1)} disabled={idx === 0} data-testid={`qb-up-${q.id}`}>↑</button>
                    <button className="btn btn-ghost btn-xs" onClick={() => move(idx, 1)} disabled={idx === questions.length - 1} data-testid={`qb-down-${q.id}`}>↓</button>
                  </div>
                  <div className="qb-row-fields">
                    <input
                      className="field-input" value={q.label} onChange={(e) => patch(idx, "label", e.target.value)}
                      placeholder="Question label" data-testid={`qb-label-${q.id}`}
                    />
                    <div className="qb-row-meta">
                      <input
                        className="field-input" style={{ flex: 1, minWidth: 120 }} value={q.section || ""} onChange={(e) => patch(idx, "section", e.target.value)}
                        placeholder="Section" data-testid={`qb-section-${q.id}`}
                      />
                      <select
                        className="field-input" style={{ width: 130 }} value={q.type} onChange={(e) => patch(idx, "type", e.target.value)}
                        data-testid={`qb-type-${q.id}`}
                      >
                        {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <label className="flex items-center gap-4 fs-12 text-muted">
                        <input type="checkbox" checked={!!q.required} onChange={(e) => patch(idx, "required", e.target.checked)} data-testid={`qb-req-${q.id}`} />
                        Required
                      </label>
                      <button className="btn btn-red btn-xs" onClick={() => removeQuestion(idx)} data-testid={`qb-del-${q.id}`}>Delete</button>
                    </div>
                    {(q.type === "select" || q.type === "multiselect") && (
                      <input
                        className="field-input" style={{ marginTop: 6 }} placeholder="Options (comma-separated)"
                        value={(q.options || []).join(", ")}
                        onChange={(e) => patch(idx, "options", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                        data-testid={`qb-options-${q.id}`}
                      />
                    )}
                    <input
                      className="field-input" style={{ marginTop: 6, fontSize: 12 }}
                      placeholder='Show only if (e.g. category: "DJ / Music Producer") — JSON, optional'
                      value={q.show_if ? JSON.stringify(q.show_if) : ""}
                      onChange={(e) => {
                        const v = e.target.value.trim();
                        if (!v) return patch(idx, "show_if", null);
                        try { patch(idx, "show_if", JSON.parse(v)); } catch { /* ignore until valid */ }
                      }}
                      data-testid={`qb-showif-${q.id}`}
                    />
                  </div>
                </div>
              ))}
            </div>
          ))}
          {questions.length === 0 && (
            <div className="empty" style={{ padding: 40 }}>
              <div className="empty-icon">📝</div>
              <div className="empty-title">No questions yet — click "+ Add Question" to start.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
