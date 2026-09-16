import React, { useEffect, useRef, useState } from "react";
import api from "../../../lib/api";

const KIND_OPTIONS = [
  { value: "contract", label: "Contract" },
  { value: "agreement", label: "Agreement" },
  { value: "invoice", label: "Invoice / Bill" },
  { value: "id", label: "ID / KYC" },
  { value: "rider", label: "Tech Rider" },
  { value: "other", label: "Other" },
];

function humanSize(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileToDataUrl(f) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [clients, setClients] = useState([]);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ title: "", kind: "contract", client_id: "", event_id: "", notes: "" });
  const [msg, setMsg] = useState(null);
  const fileRef = useRef(null);

  const load = () => api.get("/agency/documents").then((r) => setDocs(r.data || [])).catch(() => setDocs([]));

  useEffect(() => {
    load();
    api.get("/agency/clients").then((r) => setClients(r.data || [])).catch(() => {});
    api.get("/agency/events").then((r) => setEvents(r.data || [])).catch(() => {});
  }, []);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) { setMsg({ ok: false, text: "Pick a file first." }); return; }
    if (!form.title) { setMsg({ ok: false, text: "Title is required." }); return; }
    if (file.size > 8 * 1024 * 1024) { setMsg({ ok: false, text: "File too large (max 8 MB)." }); return; }
    setBusy(true);
    try {
      const data_url = await fileToDataUrl(file);
      await api.post("/agency/documents", { ...form, data_url });
      setMsg({ ok: true, text: `${file.name} uploaded.` });
      setForm({ title: "", kind: "contract", client_id: "", event_id: "", notes: "" });
      if (fileRef.current) fileRef.current.value = "";
      load();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Upload failed" });
    } finally { setBusy(false); }
  };

  const download = async (id, title) => {
    try {
      const r = await api.get(`/agency/documents/${id}/download`);
      const a = document.createElement("a");
      a.href = r.data.data_url;
      a.download = title || "document";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (_e) {
      setMsg({ ok: false, text: "Download failed" });
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this document? This cannot be undone.")) return;
    await api.delete(`/agency/documents/${id}`);
    load();
  };

  const clientName = (id) => clients.find((c) => c.id === id)?.name || "";
  const eventName = (id) => events.find((e) => e.id === id)?.title || "";

  return (
    <div data-testid="agency-documents">
      <div className="ag-section-head">
        <div>
          <h2>Documents</h2>
          <div className="fs-13">Contracts, agreements, tech riders, IDs — one private vault, tagged by client or event.</div>
        </div>
      </div>

      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Upload Document</h4>
        <div className="ag-form-grid">
          <label>Title
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Wedding Contract - Kapoor" data-testid="ag-doc-title" />
          </label>
          <label>Type
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} data-testid="ag-doc-kind">
              {KIND_OPTIONS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </label>
          <label>Link to Client (optional)
            <select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} data-testid="ag-doc-client">
              <option value="">— none —</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{`${c.name}${c.company ? ` · ${c.company}` : ""}`}</option>)}
            </select>
          </label>
          <label>Link to Event (optional)
            <select value={form.event_id} onChange={(e) => setForm({ ...form, event_id: e.target.value })} data-testid="ag-doc-event">
              <option value="">— none —</option>
              {events.map((e) => <option key={e.id} value={e.id}>{`${e.title} · ${e.event_date}`}</option>)}
            </select>
          </label>
          <label style={{ gridColumn: "1 / -1" }}>Notes (optional)
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Anything the team should know" />
          </label>
          <label>File (PDF, image, doc — max 8 MB)
            <input type="file" ref={fileRef} accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp" data-testid="ag-doc-file" />
          </label>
          <label style={{ justifyContent: "flex-end" }}>
            <span>&nbsp;</span>
            <button className="btn btn-gold btn-sm" disabled={busy} onClick={upload} data-testid="ag-doc-upload">
              {busy ? "Uploading…" : "Upload Document"}
            </button>
          </label>
        </div>
        {msg && <div className="fs-12 mt-8" style={{ color: msg.ok ? "#6ee7a8" : "#ff8888" }}>{msg.text}</div>}
      </div>

      {docs.length === 0 ? (
        <div className="ag-empty">
          <h3>No documents yet</h3>
          <div>Upload your first contract, invoice, or tech rider above.</div>
        </div>
      ) : (
        <table className="ag-table" data-testid="ag-docs-list">
          <thead><tr><th>Title</th><th>Type</th><th>Linked To</th><th>Size</th><th>Uploaded</th><th style={{ textAlign: "right" }}></th></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} data-testid={`ag-doc-row-${d.id}`}>
                <td>
                  <b>{d.title}</b>
                  {d.notes && <div className="text-muted fs-11">{d.notes}</div>}
                </td>
                <td><span className="ag-badge">{d.kind}</span></td>
                <td className="fs-12">
                  {d.client_id ? <>👤 {clientName(d.client_id) || "Client"}<br/></> : null}
                  {d.event_id ? <>🎪 {eventName(d.event_id) || "Event"}</> : null}
                  {!d.client_id && !d.event_id ? <span className="text-muted">—</span> : null}
                </td>
                <td className="fs-12">{humanSize(d.size_bytes)}</td>
                <td className="fs-12">
                  {(d.created_at || "").slice(0, 10)}
                  <div className="text-muted fs-11">{d.uploaded_by_name}</div>
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => download(d.id, d.title)} data-testid={`ag-doc-dl-${d.id}`}>Download</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => remove(d.id)} data-testid={`ag-doc-del-${d.id}`} style={{ marginLeft: 6 }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
