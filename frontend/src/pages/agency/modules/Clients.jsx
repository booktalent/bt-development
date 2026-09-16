import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

export default function Clients() {
  const [list, setList] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({ name: "", phone: "", email: "", company: "", city: "" });
  const [noteText, setNoteText] = useState("");
  const [fuText, setFuText] = useState("");
  const [fuDate, setFuDate] = useState("");

  const load = () => api.get("/agency/clients").then((r) => setList(r.data || [])).catch(() => setList([]));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    api.get(`/agency/clients/${selected}`).then((r) => setDetail(r.data)).catch(() => setDetail(null));
  }, [selected]);

  const create = async () => {
    if (!form.name) return;
    await api.post("/agency/clients", form);
    setForm({ name: "", phone: "", email: "", company: "", city: "" });
    load();
  };
  const remove = async (id) => {
    if (!window.confirm("Delete client?")) return;
    await api.delete(`/agency/clients/${id}`);
    if (selected === id) setSelected(null);
    load();
  };
  const addNote = async () => {
    if (!noteText || !selected) return;
    await api.post(`/agency/clients/${selected}/notes`, { text: noteText });
    setNoteText(""); const r = await api.get(`/agency/clients/${selected}`); setDetail(r.data);
  };
  const addFollowUp = async () => {
    if (!fuText || !fuDate || !selected) return;
    await api.post(`/agency/clients/${selected}/follow-ups`, { text: fuText, due_at: fuDate });
    setFuText(""); setFuDate(""); const r = await api.get(`/agency/clients/${selected}`); setDetail(r.data);
  };

  return (
    <div data-testid="agency-clients">
      <div className="ag-section-head">
        <div><h2>Clients (CRM)</h2><div className="fs-13">Private client roster — notes, follow-ups, and complete event history.</div></div>
      </div>

      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Add Client</h4>
        <div className="ag-form-grid">
          <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="ag-client-name" /></label>
          <label>Phone<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label>Email<input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Company<input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></label>
          <label>City<input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></label>
          <label style={{ justifyContent: "flex-end" }}><span>&nbsp;</span>
            <button className="btn btn-gold btn-sm" onClick={create} data-testid="ag-client-create">Add Client</button>
          </label>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 1fr" : "1fr", gap: 16 }}>
        <div>
          {list.length === 0 ? (
            <div className="ag-empty"><h3>No clients yet</h3><div>Add your first client above.</div></div>
          ) : (
            <table className="ag-table">
              <thead><tr><th>Name</th><th>Company</th><th>City</th><th>Contact</th><th></th></tr></thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} onClick={() => setSelected(c.id)} style={{ cursor: "pointer", background: selected === c.id ? "rgba(246,211,102,0.06)" : "" }}>
                    <td><b>{c.name}</b></td>
                    <td>{c.company || "—"}</td>
                    <td>{c.city || "—"}</td>
                    <td>{c.phone || c.email || "—"}</td>
                    <td><button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); remove(c.id); }}>Delete</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected && detail && (
          <div className="ag-card" data-testid="ag-client-detail">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div>
                <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 700 }}>{detail.name}</div>
                <div className="text-muted fs-12">{detail.company || ""} {detail.city ? `· ${detail.city}` : ""}</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>Close</button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 10 }}>
              <div>
                <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginBottom: 8 }}>Notes</div>
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  <input placeholder="Add a note…" value={noteText} onChange={(e) => setNoteText(e.target.value)} className="input" style={{ flex: 1 }} />
                  <button className="btn btn-gold btn-sm" onClick={addNote}>Save</button>
                </div>
                <div style={{ maxHeight: 220, overflowY: "auto" }}>
                  {(detail.notes_log || []).slice().reverse().map((n) => (
                    <div key={n.id} className="ag-kanban-item" style={{ marginBottom: 6 }}>
                      <div>{n.text}</div>
                      <div className="text-muted fs-11 mt-4">{n.author} · {new Date(n.at).toLocaleString()}</div>
                    </div>
                  ))}
                  {(detail.notes_log || []).length === 0 && <div className="text-muted fs-12">No notes yet.</div>}
                </div>
              </div>

              <div>
                <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginBottom: 8 }}>Follow-ups</div>
                <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
                  <input type="date" value={fuDate} onChange={(e) => setFuDate(e.target.value)} className="input" style={{ flex: 1 }} />
                  <input placeholder="e.g. Call back" value={fuText} onChange={(e) => setFuText(e.target.value)} className="input" style={{ flex: 2 }} />
                  <button className="btn btn-gold btn-sm" onClick={addFollowUp}>Add</button>
                </div>
                <div style={{ maxHeight: 220, overflowY: "auto" }}>
                  {(detail.follow_ups || []).slice().reverse().map((f) => (
                    <div key={f.id} className="ag-kanban-item" style={{ marginBottom: 6 }}>
                      <div>{f.text}</div>
                      <div className="text-muted fs-11 mt-4">Due {f.due_at}</div>
                    </div>
                  ))}
                  {(detail.follow_ups || []).length === 0 && <div className="text-muted fs-12">No follow-ups scheduled.</div>}
                </div>
              </div>
            </div>

            {(detail.events || []).length > 0 && (
              <>
                <div className="fs-11 text-muted" style={{ letterSpacing: ".14em", textTransform: "uppercase", marginTop: 16, marginBottom: 8 }}>Event History</div>
                <table className="ag-table">
                  <thead><tr><th>Event</th><th>Date</th><th>Status</th><th>Payment</th></tr></thead>
                  <tbody>
                    {detail.events.map((e) => (
                      <tr key={e.id}>
                        <td>{e.title}</td><td>{e.event_date}</td>
                        <td><span className="ag-badge">{e.status || "scheduled"}</span></td>
                        <td>{e.payment_status || "unpaid"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
