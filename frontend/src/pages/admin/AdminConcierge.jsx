import React, { useEffect, useRef, useState, useCallback } from "react";
import api, { formatApiError } from "../../lib/api";

/**
 * Admin Concierge — priority queue of Platinum + Elite artist support threads.
 *
 * Threads are already sorted server-side by priority (Elite=100 > Platinum=80).
 * Selecting a thread opens the chat pane on the right with the full message
 * history + a reply composer.
 */
export default function AdminConcierge({ toast }) {
  const [threads, setThreads] = useState([]);
  const [statusFilter, setStatusFilter] = useState("open");
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  const loadThreads = useCallback(async () => {
    try {
      const q = statusFilter ? `?status=${statusFilter}` : "";
      const r = await api.get(`/admin/concierge/threads${q}`);
      setThreads(r.data);
    } catch (e) { toast(formatApiError(e), "error"); }
  }, [statusFilter, toast]);

  const loadMessages = useCallback(async (tid) => {
    try {
      const r = await api.get(`/admin/concierge/${tid}/messages`);
      setMessages(r.data.messages || []);
      setActive(r.data.thread);
      setTimeout(() => { if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight; }, 50);
    } catch (e) { toast(formatApiError(e), "error"); }
  }, [toast]);

  useEffect(() => { loadThreads(); }, [loadThreads]);
  useEffect(() => {
    // Poll for new threads / replies every 15s. `loadThreads` / `loadMessages`
    // are stable references thanks to useCallback so the interval sees the
    // freshest closure without churning.
    const iv = setInterval(() => {
      loadThreads();
      if (active) loadMessages(active.id);
    }, 15000);
    return () => clearInterval(iv);
  }, [active, loadThreads, loadMessages]);

  const send = async () => {
    if (!text.trim() || !active || sending) return;
    setSending(true);
    try {
      await api.post(`/admin/concierge/${active.id}/send`, { body: text });
      setText("");
      loadMessages(active.id);
      loadThreads();
    } catch (e) { toast(formatApiError(e), "error"); }
    setSending(false);
  };

  const closeThread = async () => {
    if (!active || !window.confirm("Close this thread?")) return;
    try {
      await api.post(`/admin/concierge/${active.id}/close`);
      toast("Thread closed");
      loadThreads();
      loadMessages(active.id);
    } catch (e) { toast(formatApiError(e), "error"); }
  };

  const planBadge = (plan) => {
    const styles = {
      elite: "linear-gradient(135deg,#f472b6,#d4af37)",
      platinum: "linear-gradient(135deg,#a78bfa,#7c3aed)",
      gold: "linear-gradient(135deg,#fbbf24,#d4af37)",
      silver: "linear-gradient(135deg,#cbd5e1,#94a3b8)",
      free: "rgba(255,255,255,0.1)",
    };
    return <span style={{ background: styles[plan] || styles.free, color: "#0b0616", padding: "2px 8px", borderRadius: 6, fontSize: 10, fontWeight: 700 }}>{plan.toUpperCase()}</span>;
  };

  return (
    <div className="card" data-testid="admin-concierge">
      <div className="card-head" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="card-title">🎩 Concierge Queue ({threads.length})</div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="field-input" style={{ maxWidth: 180 }} data-testid="concierge-status-filter">
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="">All</option>
        </select>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 12, padding: 14, minHeight: 500 }}>
        {/* Thread list */}
        <div style={{ borderRight: "1px solid rgba(255,255,255,0.06)", paddingRight: 12, maxHeight: 600, overflowY: "auto" }} data-testid="concierge-thread-list">
          {threads.length === 0 && <div className="text-muted text-center" style={{ padding: 20 }}>No threads</div>}
          {threads.map((t) => (
            <div
              key={t.id}
              onClick={() => loadMessages(t.id)}
              className={`card card-pad mb-8 ${active?.id === t.id ? "selected" : ""}`}
              style={{ cursor: "pointer", padding: 10, background: active?.id === t.id ? "rgba(212,175,55,0.1)" : undefined }}
              data-testid={`concierge-thread-${t.id}`}
            >
              <div className="flex justify-between items-center mb-4">
                <div className="fw-700 fs-13">{t.artist_name || t.artist_id?.slice(0, 8)}</div>
                {planBadge(t.plan)}
              </div>
              <div className="fs-11 text-muted">{t.subject}</div>
              <div className="fs-10 text-muted mt-4" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{t.status === "open" ? "🟢" : "⚪"} {t.last_message_at?.slice(0, 16).replace("T", " ")}</span>
                {t.unread_admin > 0 && <span style={{ background: "#ef4444", color: "#fff", padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 700 }} data-testid={`unread-${t.id}`}>{t.unread_admin} new</span>}
              </div>
            </div>
          ))}
        </div>

        {/* Message pane */}
        {active ? (
          <div style={{ display: "flex", flexDirection: "column", minHeight: 480 }} data-testid="concierge-active-thread">
            <div className="flex justify-between items-center" style={{ paddingBottom: 8, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
              <div>
                <div className="fw-700">{active.artist_name} — {active.subject}</div>
                <div className="text-muted fs-11">{planBadge(active.plan)} · {active.status}</div>
              </div>
              {active.status === "open" && (
                <button className="btn btn-red btn-xs" onClick={closeThread} data-testid="concierge-close-btn">Close Thread</button>
              )}
            </div>
            <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: 12, minHeight: 320 }}>
              {messages.map((m) => (
                <div key={m.id} style={{ marginBottom: 12, display: "flex", justifyContent: m.sender_role === "admin" ? "flex-end" : "flex-start" }}>
                  <div style={{
                    maxWidth: "70%",
                    padding: "10px 14px",
                    borderRadius: 12,
                    background: m.sender_role === "admin" ? "linear-gradient(135deg,#d4af37,#fbbf24)" : "rgba(255,255,255,0.08)",
                    color: m.sender_role === "admin" ? "#0b0616" : "#fff",
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.7, marginBottom: 4 }}>{m.sender_role === "admin" ? "🎩 Support" : "Artist"}</div>
                    <div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>
                    <div style={{ fontSize: 9, opacity: 0.6, marginTop: 4, textAlign: "right" }}>{new Date(m.created_at).toLocaleString()}</div>
                  </div>
                </div>
              ))}
            </div>
            {active.status === "open" && (
              <div style={{ padding: 8, borderTop: "1px solid rgba(255,255,255,0.06)", display: "flex", gap: 8 }}>
                <textarea className="field-input" style={{ flex: 1, minHeight: 44 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a reply…"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  data-testid="admin-concierge-input" />
                <button className="btn btn-gold" onClick={send} disabled={!text.trim() || sending} data-testid="admin-concierge-send">Reply</button>
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted text-center" style={{ display: "grid", placeItems: "center" }}>
            <div>Select a thread to reply</div>
          </div>
        )}
      </div>
    </div>
  );
}
