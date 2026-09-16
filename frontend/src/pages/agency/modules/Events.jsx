import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

export default function Events() {
  const [list, setList] = useState([]);
  const [clients, setClients] = useState([]);
  const [artists, setArtists] = useState([]);
  const [roster, setRoster] = useState([]);
  const [form, setForm] = useState({ title: "", client_id: "", event_date: "", venue: "", city: "", event_type: "", quotation_amount: 0, notes: "" });
  const [selArtists, setSelArtists] = useState([]);

  const load = () => api.get("/agency/events").then((r) => setList(r.data || [])).catch(() => setList([]));
  useEffect(() => {
    load();
    api.get("/agency/clients").then((r) => setClients(r.data || [])).catch(() => {});
    api.get("/agency/offline-artists").then((r) => setArtists(r.data || [])).catch(() => {});
    api.get("/agency/roster").then((r) => setRoster(r.data || [])).catch(() => {});
  }, []);

  const create = async () => {
    if (!form.title || !form.event_date) return;
    await api.post("/agency/events", {
      ...form, quotation_amount: Number(form.quotation_amount) || 0,
      artists: selArtists,
      checklist: [
        { text: "Confirm venue", done: false },
        { text: "Confirm artists", done: false },
        { text: "Collect advance", done: false },
        { text: "Send call sheet", done: false },
      ],
    });
    setForm({ title: "", client_id: "", event_date: "", venue: "", city: "", event_type: "", quotation_amount: 0, notes: "" });
    setSelArtists([]);
    load();
  };
  const remove = async (id) => {
    if (!window.confirm("Delete event?")) return;
    await api.delete(`/agency/events/${id}`);
    load();
  };
  const patchStatus = async (id, status) => {
    await api.patch(`/agency/events/${id}`, { status });
    load();
  };

  const toggleArtist = (a, offline) => {
    const line = { artist_id: a.id || a.artist_id, is_offline: offline, name: a.name || a.stage_name || "Artist", price: a.base_price || 0 };
    setSelArtists((prev) =>
      prev.some((x) => x.artist_id === line.artist_id) ? prev.filter((x) => x.artist_id !== line.artist_id) : [...prev, line]
    );
  };

  return (
    <div data-testid="agency-events">
      <div className="ag-section-head">
        <div><h2>Events</h2><div className="fs-13">Create offline events, assign artists, track payment & checklists.</div></div>
      </div>

      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Create Event</h4>
        <div className="ag-form-grid">
          <label>Title<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="ag-event-title" /></label>
          <label>Client
            <select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
              <option value="">— none —</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>Date<input type="date" value={form.event_date} onChange={(e) => setForm({ ...form, event_date: e.target.value })} data-testid="ag-event-date" /></label>
          <label>Venue<input value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} /></label>
          <label>City<input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></label>
          <label>Event type<input placeholder="Wedding, Corporate…" value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })} /></label>
          <label>Quotation ₹<input type="number" value={form.quotation_amount} onChange={(e) => setForm({ ...form, quotation_amount: e.target.value })} /></label>
          <label style={{ gridColumn: "1 / -1" }}>Notes<textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
        </div>

        <div style={{ marginTop: 12 }}>
          <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginBottom: 8 }}>Assign Artists</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {roster.map((a) => (
              <button key={"r" + a.artist_id} onClick={() => toggleArtist(a, false)}
                className={`ag-badge ${selArtists.some((x) => x.artist_id === a.artist_id) ? "gold" : ""}`}
                style={{ cursor: "pointer", border: "1px solid rgba(255,255,255,0.1)" }}
                data-testid={`ag-event-artist-${a.artist_id}`}>
                {a.stage_name || a.artist_name} · online
              </button>
            ))}
            {artists.map((a) => (
              <button key={"o" + a.id} onClick={() => toggleArtist(a, true)}
                className={`ag-badge ${selArtists.some((x) => x.artist_id === a.id) ? "violet" : ""}`}
                style={{ cursor: "pointer", border: "1px solid rgba(255,255,255,0.1)" }}>
                {a.name} · offline
              </button>
            ))}
            {roster.length === 0 && artists.length === 0 && (
              <div className="text-muted fs-12">Add artists in Artist Management first.</div>
            )}
          </div>
        </div>

        <div style={{ marginTop: 12, textAlign: "right" }}>
          <button className="btn btn-gold" onClick={create} data-testid="ag-event-create">Create Event</button>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="ag-empty"><h3>No events yet</h3><div>Create your first event above.</div></div>
      ) : (
        <table className="ag-table" data-testid="ag-events-list">
          <thead><tr><th>Event</th><th>Date</th><th>Venue</th><th>Artists</th><th>Payment</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {list.map((e) => (
              <tr key={e.id}>
                <td><b>{e.title}</b><div className="text-muted fs-11">{e.event_type || ""}</div></td>
                <td>{e.event_date}</td>
                <td>{e.venue || "—"}<div className="text-muted fs-11">{e.city || ""}</div></td>
                <td>{(e.artists || []).length}</td>
                <td><span className={`ag-badge ${e.payment_status === "paid" ? "ok" : e.payment_status === "partial" ? "warn" : "err"}`}>{e.payment_status || "unpaid"}</span></td>
                <td>
                  <select value={e.status || "scheduled"} onChange={(ev) => patchStatus(e.id, ev.target.value)}
                    style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", color: "#fff", padding: "6px 8px", borderRadius: 6 }}>
                    <option value="scheduled">Scheduled</option>
                    <option value="in_progress">In progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </td>
                <td><button className="btn btn-ghost btn-sm" onClick={() => remove(e.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
