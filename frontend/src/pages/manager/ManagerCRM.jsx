import React, { useEffect, useState, useMemo } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import api, { formatApiError as fmt } from "../../lib/api";
import { useToast } from "../../lib/toast";

/**
 * Iter 85 — Manager & CRM UIs (Sec 26-30).
 *
 * Three pages in one module:
 *   • ManagerDashboard     — pipeline counts, my active bookings, quick nav
 *   • LeadBoard            — Kanban across 12 stages
 *   • LeadDetail           — single lead with timeline + assignment picker
 *
 * All three read from /api/leads*, /api/manager/dashboard endpoints
 * already delivered in Iter 84.
 */

const STAGES = [
  { key: "new_lead", label: "New", tint: "sky" },
  { key: "contacted", label: "Contacted", tint: "sky" },
  { key: "requirement_received", label: "Requirement", tint: "cyan" },
  { key: "artist_suggested", label: "Suggested", tint: "cyan" },
  { key: "quotation_sent", label: "Quoted", tint: "gold" },
  { key: "negotiation", label: "Negotiating", tint: "gold" },
  { key: "booking_pending", label: "Booking Pending", tint: "gold" },
  { key: "booking_confirmed", label: "Confirmed", tint: "green" },
  { key: "payment_pending", label: "Payment Pending", tint: "orange" },
  { key: "event_upcoming", label: "Event Upcoming", tint: "green" },
  { key: "event_completed", label: "Event Done", tint: "green" },
  { key: "closed", label: "Closed", tint: "muted" },
];

const money = (n) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));


// ─── Page 1: Manager Dashboard ─────────────────────────────────────
export function ManagerDashboard() {
  const toast = useToast();
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [bookOpen, setBookOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/manager/dashboard");
        setDash(r.data);
      } catch (e) { toast(fmt(e), "error"); }
      setLoading(false);
    })();
  }, []); // eslint-disable-line

  if (loading) return <div className="pad-24" data-testid="mgr-dash-loading">Loading…</div>;
  if (!dash) return <div className="pad-24">No data</div>;

  const totalLeads = Object.values(dash.counts || {}).reduce((a, b) => a + b, 0);

  return (
    <div className="pad-24" data-testid="manager-dashboard">
      <h1 className="font-serif fs-24 fw-700 mb-16">Manager Dashboard</h1>
      <div className="grid grid-4 gap-12 mb-24">
        <StatCard label="Total Leads" value={totalLeads} testid="stat-total-leads" />
        <StatCard label="Active Bookings" value={dash.active_bookings || 0} testid="stat-active-bookings" />
        <StatCard label="Booking Pending" value={dash.counts.booking_pending || 0} testid="stat-booking-pending" />
        <StatCard label="Event Upcoming" value={dash.counts.event_upcoming || 0} testid="stat-event-upcoming" />
      </div>
      <h2 className="font-serif fs-18 fw-700 mb-12">Pipeline</h2>
      <div className="grid grid-4 gap-8 mb-24">
        {STAGES.map((s) => (
          <Link key={s.key} to={`/manager/leads?stage=${s.key}`}
            className="card card-pad hover-lift" data-testid={`pipeline-${s.key}`}>
            <div className="text-muted fs-12">{s.label}</div>
            <div className="fs-24 fw-700 mt-4">{dash.counts[s.key] || 0}</div>
          </Link>
        ))}
      </div>
      <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
        <Link to="/manager/leads" className="btn btn-gold" data-testid="btn-lead-board">Open Lead Board →</Link>
        <Link to="/manager/leads?stage=new_lead" className="btn btn-ghost">Work New Leads</Link>
        <Link to="/manager/leaderboard" className="btn btn-ghost" data-testid="btn-leaderboard">🏆 Team Leaderboard</Link>
        <Link to="/manager/chat" className="btn btn-ghost" data-testid="btn-chat">💬 Chat Moderation</Link>
        <button
          className="btn btn-ghost"
          onClick={() => document.getElementById("mgr-add-customer-modal")?.showModal?.() || setAddOpen(true)}
          data-testid="btn-add-customer"
        >+ Add Customer</button>
        <button
          className="btn btn-ghost"
          onClick={() => setBookOpen(true)}
          data-testid="btn-create-booking-on-behalf"
        >+ Create Booking on Behalf</button>
      </div>
      {addOpen && <AddCustomerModal onClose={() => setAddOpen(false)} onSaved={() => setAddOpen(false)} toast={toast} />}
      {bookOpen && <CreateBookingOnBehalfModal onClose={() => setBookOpen(false)} toast={toast} />}
    </div>
  );
}


function StatCard({ label, value, testid }) {
  return (
    <div className="card card-pad" data-testid={testid}>
      <div className="text-muted fs-13">{label}</div>
      <div className="font-serif fs-28 fw-700 mt-4">{value}</div>
    </div>
  );
}


// ─── Page 2: Lead Board (Kanban) ───────────────────────────────────
export function LeadBoard() {
  const toast = useToast();
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/leads?limit=500");
      setLeads(r.data.items || []);
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const byStage = useMemo(() => {
    const m = {};
    STAGES.forEach((s) => (m[s.key] = []));
    leads.forEach((l) => { (m[l.stage] || (m[l.stage] = [])).push(l); });
    return m;
  }, [leads]);

  const advance = async (lead, newStage) => {
    try {
      await api.patch(`/leads/${lead.id}/stage`, { stage: newStage, note: "Advanced from Kanban" });
      toast(`Moved to ${newStage.replace(/_/g, " ")}`, "success");
      await load();
    } catch (e) { toast(fmt(e), "error"); }
  };

  if (loading) return <div className="pad-24">Loading leads…</div>;

  return (
    <div className="pad-24" data-testid="lead-board">
      <div className="flex-between mb-16">
        <h1 className="font-serif fs-24 fw-700">Lead Board</h1>
        <Link to="/manager/leads/new" className="btn btn-gold" data-testid="btn-new-lead">+ New Lead</Link>
      </div>
      <div className="overflow-x-auto">
        <div className="flex gap-12" style={{ minWidth: 1800 }}>
          {STAGES.map((s) => (
            <div key={s.key} className="lead-col" style={{ width: 280, flex: "0 0 280px" }} data-testid={`col-${s.key}`}>
              <div className="lead-col-head mb-8">
                <span className="fw-700">{s.label}</span>
                <span className="text-muted fs-12 ml-8">{(byStage[s.key] || []).length}</span>
              </div>
              {(byStage[s.key] || []).map((l) => (
                <div key={l.id} className="card card-pad mb-8" data-testid={`card-lead-${l.id}`}>
                  <div className="fw-700 fs-14" onClick={() => nav(`/manager/leads/${l.id}`)} style={{ cursor: "pointer" }}>
                    {l.customer_name}
                  </div>
                  <div className="text-muted fs-12">{l.event_type} · {l.city || "—"}</div>
                  <div className="text-gold fs-13 mt-4">₹{money(l.budget)}</div>
                  {l.assigned_manager_email && (
                    <div className="text-muted fs-11 mt-4">👤 {l.assigned_manager_email}</div>
                  )}
                  <select className="field-input mt-8" value={l.stage}
                    onChange={(e) => advance(l, e.target.value)}
                    data-testid={`lead-${l.id}-stage-select`}>
                    {STAGES.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                    <option value="lost_cancelled">Lost / Cancelled</option>
                  </select>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


// ─── Page 3: Lead Detail (timeline + assignment) ───────────────────
export function LeadDetail() {
  const { id } = useParams();
  const toast = useToast();
  const [lead, setLead] = useState(null);
  const [managers, setManagers] = useState([]);
  const [selectedMgr, setSelectedMgr] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const r = await api.get(`/leads?limit=500`); // simple list-then-filter (a dedicated GET /leads/{id} can come later)
      const found = (r.data.items || []).find((l) => l.id === id);
      setLead(found || null);
    } catch (e) { toast(fmt(e), "error"); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/admin/list-users?role=manager");
        setManagers(r.data.items || r.data.users || []);
      } catch {
        setManagers([]);
      }
    })();
  }, []);

  const assign = async () => {
    if (!selectedMgr) return toast("Pick a manager first", "error");
    setSaving(true);
    try {
      await api.post(`/leads/${id}/assign`, { manager_id: selectedMgr, note });
      toast("Assigned", "success");
      setNote("");
      await load();
    } catch (e) { toast(fmt(e), "error"); }
    setSaving(false);
  };

  if (!lead) return <div className="pad-24">Loading lead…</div>;

  return (
    <div className="pad-24" data-testid="lead-detail">
      <Link to="/manager/leads" className="text-muted fs-13">← Back to Board</Link>
      <div className="flex-between mt-8 mb-16">
        <div>
          <h1 className="font-serif fs-24 fw-700">{lead.customer_name}</h1>
          <div className="text-muted fs-13">{lead.company || "Individual"} · {lead.phone}</div>
        </div>
        <div className="pill pill-gold" data-testid="lead-stage-pill">{lead.stage.replace(/_/g, " ")}</div>
      </div>

      <div className="grid grid-2 gap-16 mb-24">
        <div className="card card-pad">
          <h3 className="font-serif fw-700 mb-8">Enquiry</h3>
          <Row k="Event type" v={lead.event_type} />
          <Row k="Event date" v={lead.event_date || "—"} />
          <Row k="Days" v={lead.number_of_days || 1} />
          <Row k="Venue" v={lead.venue || "—"} />
          <Row k="Address" v={lead.venue_address || "—"} />
          <Row k="Budget" v={`₹${money(lead.budget)}`} />
          <Row k="Requirements" v={lead.requirements || "—"} />
          <Row k="Source" v={lead.lead_source} />
        </div>
        <div className="card card-pad">
          <h3 className="font-serif fw-700 mb-8">Assign / Reassign Manager</h3>
          <Row k="Current" v={lead.assigned_manager_email || "Unassigned"} />
          <select className="field-input mb-8" value={selectedMgr} onChange={(e) => setSelectedMgr(e.target.value)}
            data-testid="assign-manager-select">
            <option value="">Choose a manager…</option>
            {managers.map((m) => <option key={m.id} value={m.id}>{m.email}</option>)}
          </select>
          <input className="field-input mb-8" placeholder="Note (optional)"
            value={note} onChange={(e) => setNote(e.target.value)} data-testid="assign-note" />
          <button className="btn btn-gold" disabled={saving || !selectedMgr}
            onClick={assign} data-testid="assign-submit-btn">
            {saving ? "Saving…" : "Assign"}
          </button>
        </div>
      </div>

      <div className="card card-pad">
        <h3 className="font-serif fw-700 mb-12">Timeline</h3>
        <ul className="timeline" data-testid="lead-timeline">
          {(lead.history || []).slice().reverse().map((h, i) => (
            <li key={i} className="mb-8">
              <div className="fs-13 fw-700">{h.stage?.replace(/_/g, " ")}</div>
              <div className="text-muted fs-12">{h.actor} · {new Date(h.at).toLocaleString()}</div>
              {h.note && <div className="fs-13 mt-4">{h.note}</div>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const Row = ({ k, v }) => (
  <div className="flex-between fs-13 mb-4">
    <span className="text-muted">{k}</span>
    <span className="text-right" style={{ maxWidth: "60%" }}>{v}</span>
  </div>
);



// ────────────────────────────────────────────────────────────────────────
// AddCustomerModal — manager creates a walk-in / phone-in customer.
// ────────────────────────────────────────────────────────────────────────
export function AddCustomerModal({ onClose, onSaved, toast }) {
  const [form, setForm] = useState({
    email: "", first_name: "", last_name: "", phone: "", city: "", notes: "",
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.email || !form.first_name) { toast("Email and first name are required", "error"); return; }
    setBusy(true);
    try {
      const r = await api.post("/manager/customers", form);
      toast(r.data?.existing ? "Customer already existed — linked" : "Customer added ✓", "success");
      onSaved && onSaved(r.data?.user);
    } catch (e) { toast(fmt(e), "error"); }
    setBusy(false);
  };

  return (
    <div
      data-testid="mgr-add-customer-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(6,4,20,0.75)",
        display: "grid", placeItems: "center", zIndex: 900, padding: 16,
      }}
      onClick={onClose}
    >
      <div className="card card-pad" style={{ maxWidth: 480, width: "100%", background: "#0F0F1B" }}
        onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif fw-700 fs-18 mb-12">Add Customer</h3>
        <div className="grid grid-2 gap-8">
          <input className="input" placeholder="First name *" value={form.first_name}
            onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            data-testid="mgr-add-fn" />
          <input className="input" placeholder="Last name" value={form.last_name}
            onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            data-testid="mgr-add-ln" />
        </div>
        <input className="input mt-8" placeholder="Email *" value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          data-testid="mgr-add-email" />
        <div className="grid grid-2 gap-8 mt-8">
          <input className="input" placeholder="Phone" value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            data-testid="mgr-add-phone" />
          <input className="input" placeholder="City" value={form.city}
            onChange={(e) => setForm({ ...form, city: e.target.value })}
            data-testid="mgr-add-city" />
        </div>
        <textarea className="input mt-8" placeholder="Notes (optional)" rows={2}
          value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
          data-testid="mgr-add-notes" />
        <div className="flex gap-8 mt-12" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-gold" onClick={submit} disabled={busy} data-testid="mgr-add-save">
            {busy ? "Saving…" : "Add Customer"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ────────────────────────────────────────────────────────────────────────
// CreateBookingOnBehalfModal — manager creates a booking for a chosen
// customer + artist. Basic fields; central financial engine computes the
// pricing server-side.
// ────────────────────────────────────────────────────────────────────────
export function CreateBookingOnBehalfModal({ onClose, toast }) {
  const [step, setStep] = useState(1);
  const [customers, setCustomers] = useState([]);
  const [artists, setArtists] = useState([]);
  const [presets, setPresets] = useState([]);
  const [recs, setRecs] = useState([]);
  const [q, setQ] = useState("");
  const [aq, setAq] = useState("");
  const [form, setForm] = useState({
    customer_id: "", artist_id: "", package_fee: "",
    event_type: "wedding", event_type_other: "",
    event_date: "", number_of_days: 1,
    venue: "", venue_address: "", city: "", notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [savingPreset, setSavingPreset] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [presetShared, setPresetShared] = useState(false);

  useEffect(() => {
    api.get(`/manager/customers?q=${encodeURIComponent(q)}&limit=20`)
      .then((r) => setCustomers(r.data?.items || [])).catch(() => setCustomers([]));
  }, [q]);
  useEffect(() => {
    api.get(`/artists/search?q=${encodeURIComponent(aq)}&limit=20`)
      .then((r) => setArtists(r.data?.artists || r.data?.items || r.data || []))
      .catch(() => setArtists([]));
  }, [aq]);
  useEffect(() => {
    api.get("/manager/booking-presets")
      .then((r) => setPresets(r.data?.items || []))
      .catch(() => setPresets([]));
    // Top-3 most-used team-shared presets so new managers grab proven templates first.
    api.get("/manager/booking-presets/recommendations")
      .then((r) => setRecs(r.data?.items || []))
      .catch(() => setRecs([]));
  }, []);

  const applyPreset = (p) => {
    setForm((f) => ({
      ...f,
      event_type: p.event_type || f.event_type,
      event_type_other: p.event_type_other || f.event_type_other,
      number_of_days: p.number_of_days || f.number_of_days,
      city: p.city || f.city,
      package_fee: p.default_package_fee || f.package_fee,
      notes: p.notes_template || f.notes,
    }));
    toast(`Applied preset "${p.name}"`, "success");
    // Bump usage counter server-side (fire-and-forget).
    api.post(`/manager/booking-presets/${p.id}/use`)
      .then((r) => {
        setPresets((ps) => ps.map((x) => x.id === p.id
          ? { ...x, usage_count: r.data.usage_count, last_used_at: r.data.last_used_at }
          : x));
      })
      .catch(() => { /* usage tracking is best-effort */ });
  };

  const savePreset = async () => {
    if (!presetName.trim()) { toast("Enter a preset name first", "error"); return; }
    setSavingPreset(true);
    try {
      const r = await api.post("/manager/booking-presets", {
        name: presetName.trim(),
        event_type: form.event_type,
        event_type_other: form.event_type_other || null,
        number_of_days: parseInt(form.number_of_days || 1),
        city: form.city,
        default_package_fee: parseFloat(form.package_fee || 0),
        notes_template: form.notes,
        shared: presetShared,
      });
      setPresets((ps) => [r.data.preset, ...ps]);
      setPresetName("");
      setPresetShared(false);
      toast(presetShared ? "Preset saved & shared with team ✓" : "Preset saved ✓", "success");
    } catch (e) { toast(fmt(e), "error"); }
    setSavingPreset(false);
  };

  const toggleShare = async (p) => {
    try {
      const r = await api.patch(`/manager/booking-presets/${p.id}/share`, { shared: !p.shared });
      setPresets((ps) => ps.map((x) => x.id === p.id ? { ...x, shared: r.data.shared } : x));
      toast(r.data.shared ? "Preset shared with the team" : "Preset set back to private");
    } catch (e) { toast(fmt(e), "error"); }
  };

  const removePreset = async (pid) => {
    if (!window.confirm("Delete this preset?")) return;
    try {
      await api.delete(`/manager/booking-presets/${pid}`);
      setPresets((ps) => ps.filter((x) => x.id !== pid));
      toast("Preset removed");
    } catch (e) { toast(fmt(e), "error"); }
  };

  const submit = async () => {
    if (!form.customer_id || !form.artist_id || !form.event_date || !form.venue || !form.venue_address || !form.city) {
      toast("Fill all mandatory fields (customer, artist, date, venue, address, city)", "error");
      return;
    }
    setBusy(true);
    try {
      const payload = { ...form, package_fee: parseFloat(form.package_fee || 0), number_of_days: parseInt(form.number_of_days || 1) };
      const r = await api.post("/manager/bookings", payload);
      toast(`Booking created ✓ ${r.data?.booking?.ref || ""}`, "success");
      onClose();
    } catch (e) { toast(fmt(e), "error"); }
    setBusy(false);
  };

  return (
    <div
      data-testid="mgr-create-booking-modal"
      style={{
        position: "fixed", inset: 0, background: "rgba(6,4,20,0.75)",
        display: "grid", placeItems: "center", zIndex: 900, padding: 16,
      }}
      onClick={onClose}
    >
      <div className="card card-pad" style={{ maxWidth: 640, width: "100%", background: "#0F0F1B", maxHeight: "90vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif fw-700 fs-18 mb-12">Create Booking on Behalf</h3>

        {step === 1 && (
          <>
            <div className="fw-700 fs-13 mb-4">1. Pick Customer</div>
            <input className="input mb-8" placeholder="Search customers (name / email / phone)"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="mgr-book-cust-search" />
            <div style={{ maxHeight: 200, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8 }}>
              {customers.map((c) => (
                <div key={c.id}
                  onClick={() => { setForm({ ...form, customer_id: c.id, city: c.city || form.city }); setStep(2); }}
                  style={{ padding: 10, cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                  data-testid={`mgr-book-cust-${c.id}`}>
                  <div className="fw-700 fs-13">{c.first_name} {c.last_name}</div>
                  <div className="text-muted fs-11">{c.email} · {c.phone || "—"}</div>
                </div>
              ))}
              {customers.length === 0 && <div className="text-muted pad-16 fs-13">No customers match. Use "Add Customer" first.</div>}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="fw-700 fs-13 mb-4">2. Pick Artist</div>
            <input className="input mb-8" placeholder="Search artists"
              value={aq} onChange={(e) => setAq(e.target.value)} data-testid="mgr-book-artist-search" />
            <div style={{ maxHeight: 200, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8 }}>
              {(artists || []).map((a) => {
                const aid = a.user_id || a.id;
                const name = a.stage_name || a.name || `${a.first_name || ""} ${a.last_name || ""}`.trim() || "Artist";
                return (
                  <div key={aid} onClick={() => { setForm({ ...form, artist_id: aid }); setStep(3); }}
                    style={{ padding: 10, cursor: "pointer", borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                    data-testid={`mgr-book-artist-${aid}`}>
                    <div className="fw-700 fs-13">{name}</div>
                    <div className="text-muted fs-11">{a.category || "—"} · {a.city || "—"}</div>
                  </div>
                );
              })}
              {(!artists || artists.length === 0) && <div className="text-muted pad-16 fs-13">No artists match your search.</div>}
            </div>
            <div className="flex gap-8 mt-8"><button className="btn btn-ghost btn-sm" onClick={() => setStep(1)}>← Back</button></div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="fw-700 fs-13 mb-8">3. Event Details</div>

            {/* Top team recommendations */}
            {recs.length > 0 && (
              <div className="mb-8" style={{
                background: "linear-gradient(180deg, rgba(110,231,168,0.08), rgba(110,231,168,0.02))",
                border: "1px solid rgba(110,231,168,0.25)", padding: 8, borderRadius: 8,
              }} data-testid="mgr-preset-recs">
                <div className="text-good fs-11 mb-4">🏆 Top team presets — battle-tested by your teammates</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {recs.map((p) => (
                    <span key={p.id}
                      title={`Used ${p.usage_count}× · Shared by ${p.owner_name || "team"}`}
                      style={{
                        display: "inline-flex", gap: 6, alignItems: "center",
                        border: "1px solid rgba(110,231,168,0.5)", borderRadius: 999,
                        padding: "4px 12px", fontSize: 11, background: "rgba(110,231,168,0.12)",
                        cursor: "pointer", fontWeight: 700,
                      }}
                      onClick={() => applyPreset(p)}
                      data-testid={`mgr-preset-rec-${p.id}`}>
                      🏆 {p.name} <span style={{ opacity: 0.75, fontWeight: 400 }}>· {p.usage_count}×</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Preset picker + save */}
            {presets.length > 0 && (
              <div className="mb-8" style={{ background: "rgba(255,255,255,0.03)", padding: 8, borderRadius: 8 }}>
                <div className="text-muted fs-11 mb-4">Load a saved preset (your own + team-shared)</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }} data-testid="mgr-preset-list">
                  {presets.map((p) => (
                    <span key={p.id}
                      title={
                        `${p.owned ? "Your preset" : `Shared by ${p.owner_name || "team"}`}` +
                        (p.usage_count ? ` · used ${p.usage_count}×` : " · never used")
                      }
                      style={{
                        display: "inline-flex", gap: 6, alignItems: "center",
                        border: `1px solid ${p.shared ? "rgba(110,231,168,0.45)" : "rgba(212,175,55,0.35)"}`,
                        borderRadius: 999, padding: "3px 10px", fontSize: 11,
                        background: p.shared ? "rgba(110,231,168,0.06)" : "rgba(212,175,55,0.06)",
                      }}
                      data-testid={`mgr-preset-${p.id}`}>
                      <span style={{ cursor: "pointer" }} onClick={() => applyPreset(p)}>
                        {p.shared && !p.owned && "👥 "}{p.name}
                      </span>
                      {p.usage_count > 0 && (
                        <span
                          data-testid={`mgr-preset-uses-${p.id}`}
                          style={{
                            fontSize: 10, padding: "1px 6px", borderRadius: 999,
                            background: "rgba(255,255,255,0.08)", color: "rgba(240,238,255,0.75)",
                          }}
                          title={`Used ${p.usage_count}× · last on ${(p.last_used_at || "").slice(0, 10) || "unknown"}`}>
                          {p.usage_count}×
                        </span>
                      )}
                      {p.owned && (
                        <span
                          onClick={() => toggleShare(p)}
                          style={{ cursor: "pointer", fontSize: 10, color: p.shared ? "#6ee7a8" : "rgba(240,238,255,0.5)" }}
                          data-testid={`mgr-preset-share-${p.id}`}
                          title={p.shared ? "Shared with team — click to unshare" : "Only you — click to share with team"}>
                          {p.shared ? "shared" : "private"}
                        </span>
                      )}
                      {p.owned && <span style={{ cursor: "pointer", color: "#e57373" }} onClick={() => removePreset(p.id)}>×</span>}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-2 gap-8">
              <select className="input" value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value })} data-testid="mgr-book-etype">
                <option value="wedding">Wedding</option>
                <option value="corporate">Corporate</option>
                <option value="private">Private</option>
                <option value="festival">Festival</option>
                <option value="birthday">Birthday</option>
                <option value="others">Others</option>
              </select>
              {form.event_type === "others" && (
                <input className="input" placeholder="Please specify"
                  value={form.event_type_other}
                  onChange={(e) => setForm({ ...form, event_type_other: e.target.value })}
                  data-testid="mgr-book-etype-other" />
              )}
            </div>
            <div className="grid grid-2 gap-8 mt-8">
              <input type="date" className="input" value={form.event_date}
                onChange={(e) => setForm({ ...form, event_date: e.target.value })} data-testid="mgr-book-date" />
              <input type="number" min={1} className="input" placeholder="No. of Days *"
                value={form.number_of_days}
                onChange={(e) => setForm({ ...form, number_of_days: e.target.value })} data-testid="mgr-book-days" />
            </div>
            <input className="input mt-8" placeholder="Venue *"
              value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} data-testid="mgr-book-venue" />
            <input className="input mt-8" placeholder="Full Address *"
              value={form.venue_address} onChange={(e) => setForm({ ...form, venue_address: e.target.value })} data-testid="mgr-book-addr" />
            <input className="input mt-8" placeholder="City *"
              value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} data-testid="mgr-book-city" />
            <input type="number" className="input mt-8" placeholder="Package Fee (₹)"
              value={form.package_fee} onChange={(e) => setForm({ ...form, package_fee: e.target.value })} data-testid="mgr-book-fee" />
            <textarea className="input mt-8" placeholder="Notes" rows={2}
              value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="mgr-book-notes" />

            <div className="flex gap-8 mt-12" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  className="input" style={{ minWidth: 150 }}
                  placeholder="Preset name"
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  data-testid="mgr-preset-name"
                />
                <label style={{ display: "flex", gap: 4, alignItems: "center", fontSize: 12, cursor: "pointer" }}
                        data-testid="mgr-preset-shared-wrap">
                  <input
                    type="checkbox"
                    checked={presetShared}
                    onChange={(e) => setPresetShared(e.target.checked)}
                    data-testid="mgr-preset-shared"
                  />
                  Share with team
                </label>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={savePreset}
                  disabled={savingPreset || !presetName.trim()}
                  data-testid="mgr-preset-save">
                  {savingPreset ? "Saving…" : "💾 Save as preset"}
                </button>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setStep(2)}>← Back</button>
                <button className="btn btn-gold" onClick={submit} disabled={busy} data-testid="mgr-book-submit">
                  {busy ? "Creating…" : "Create Booking"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
