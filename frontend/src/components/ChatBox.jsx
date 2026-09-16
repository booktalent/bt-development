import React, { useEffect, useRef, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";/**
 * Live chat box for a booking. Connects to /api/ws/chat/{bookingId} for realtime
 * messages, typing indicators, and read receipts. Falls back to REST polling
 * if the WebSocket fails.
 */
export default function ChatBox({ bookingId, otherName = "Counterparty", paymentStatus, height = 420 }) {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(null);
  const [connected, setConnected] = useState(false);
  const [participants, setParticipants] = useState([]);
  const [access, setAccess] = useState(null); // { enabled, payment_status, reason }
  const wsRef = useRef(null);
  const listRef = useRef(null);
  const typingTimer = useRef(null);

  // Verify chat access (payment gate). Backend is the source of truth.
  useEffect(() => {
    if (!bookingId) return;
    let cancelled = false;
    api.get(`/chat/${bookingId}/access`)
      .then((r) => { if (!cancelled) setAccess(r.data); })
      .catch((e) => {
        if (cancelled) return;
        if (e?.response?.status === 403) {
          setAccess({ enabled: false, reason: e.response.data?.detail || "Chat locked", payment_status: paymentStatus || "unpaid" });
        } else {
          // network error — optimistic fallback to prop
          setAccess({ enabled: paymentStatus && paymentStatus !== "unpaid", payment_status: paymentStatus || "unpaid" });
        }
      });
    return () => { cancelled = true; };
  }, [bookingId, paymentStatus]);

  const locked = access && access.enabled === false;

  // Load history (only when chat is unlocked)
  const loadHistory = async () => {
    try {
      const r = await api.get(`/chat/${bookingId}/messages?limit=200`);
      setMessages(r.data || []);
      // Mark as read
      api.post(`/chat/${bookingId}/read`).catch(() => {});
    } catch (_e) { /* ignore */ }
  };
  useEffect(() => {
    if (!access?.enabled) return;
    loadHistory();
    // `loadHistory` is a new closure every render; including it loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookingId, access?.enabled]);

  // WebSocket
  useEffect(() => {
    if (!bookingId || !user) return;
    if (!access?.enabled) return; // payment gate
    // Auth is carried by the httpOnly access_token cookie — browsers attach
    // same-origin cookies to WebSocket handshakes automatically. The backend
    // (chat_routes.ws_chat) prefers the cookie and falls back to ?token= for
    // legacy clients. Nothing to read from JS storage anymore.
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${wsProto}//${window.location.host}/api/ws/chat/${bookingId}`;
    let ws;
    try {
      ws = new WebSocket(url);
    } catch (_e) {
      return;
    }
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch (_e) { return; }
      if (data.event === "message") {
        setMessages((prev) => {
          if (prev.some((m) => m.id === data.message.id)) return prev;
          return [...prev, data.message];
        });
      } else if (data.event === "typing" && data.by !== user.id) {
        setTyping(data.name || "Typing");
        if (typingTimer.current) clearTimeout(typingTimer.current);
        typingTimer.current = setTimeout(() => setTyping(null), 2500);
      } else if (data.event === "read") {
        setMessages((prev) => prev.map((m) => {
          if (m.sender_id === user.id && !(m.read_by || []).includes(data.by)) {
            return { ...m, read_by: [...(m.read_by || []), data.by] };
          }
          return m;
        }));
      } else if (data.event === "presence") {
        setParticipants(data.participants || []);
      }
    };
    return () => {
      try { ws.close(); } catch (_e) { /* */ }
    };
  }, [bookingId, user, access?.enabled]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  const send = () => {
    const content = draft.trim();
    if (!content) return;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ event: "message", content }));
    } else {
      // Fallback REST
      api.post(`/chat/${bookingId}/messages`, { content })
        .then((r) => setMessages((prev) => [...prev, r.data]))
        .catch(() => {});
    }
    setDraft("");
  };

  // ── File / voice / video upload ─────────────────────────────────────
  const fileInputRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const mediaRecRef = useRef(null);
  const recChunksRef = useRef([]);
  const recStartRef = useRef(0);

  const readDataUrl = (file) => new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.readAsDataURL(file);
  });

  const uploadFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 15 * 1024 * 1024) { alert("Max 15 MB"); return; }
    const dataUrl = await readDataUrl(f);
    try {
      const r = await api.post(`/chat/${bookingId}/upload`, {
        booking_id: bookingId, type: "file", data_url: dataUrl, filename: f.name,
      });
      setMessages((prev) => [...prev, r.data]);
    } catch (err) { alert(err?.response?.data?.detail || "Upload failed"); }
    e.target.value = "";
  };

  const startVoice = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      recChunksRef.current = [];
      rec.ondataavailable = (e) => recChunksRef.current.push(e.data);
      rec.onstop = async () => {
        const dur = (Date.now() - recStartRef.current) / 1000;
        const blob = new Blob(recChunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size > 5 * 1024 * 1024) { alert("Voice note > 5 MB"); return; }
        const dataUrl = await new Promise((res) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.readAsDataURL(blob);
        });
        try {
          const r = await api.post(`/chat/${bookingId}/upload`, {
            booking_id: bookingId, type: "voice", data_url: dataUrl, duration_sec: dur,
          });
          setMessages((prev) => [...prev, r.data]);
        } catch (err) { alert(err?.response?.data?.detail || "Voice upload failed"); }
        stream.getTracks().forEach((t) => t.stop());
      };
      mediaRecRef.current = rec;
      recStartRef.current = Date.now();
      rec.start();
      setRecording(true);
    } catch (err) {
      alert("Microphone access denied");
    }
  };

  const stopVoice = () => {
    if (mediaRecRef.current && recording) {
      mediaRecRef.current.stop();
      setRecording(false);
    }
  };

  const requestVideo = async () => {
    const note = window.prompt("Add a note for your video-call request (optional):", "Hey, can we hop on a quick video call?");
    if (note === null) return;
    try {
      const r = await api.post(`/chat/${bookingId}/upload`, {
        booking_id: bookingId, type: "video-request", note,
      });
      setMessages((prev) => [...prev, r.data]);
    } catch (err) { alert(err?.response?.data?.detail || "Failed"); }
  };

  const onTyping = (v) => {
    setDraft(v);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ event: "typing" })); } catch (_e) { /* */ }
    }
  };

  return (
    <div className="card" data-testid="chat-box" style={{ display: "flex", flexDirection: "column", height }}>
      {locked ? (
        <div
          data-testid="chat-locked"
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: 32,
            textAlign: "center",
            gap: 14,
          }}
          title="Chat will be available after successful payment of the Platform Service Fee."
        >
          <div style={{ fontSize: 44, lineHeight: 1 }} aria-hidden>🔒</div>
          <div className="card-title" style={{ fontSize: 18 }}>
            Complete Platform Fee Payment to Unlock Chat
          </div>
          <div className="text-muted fs-13" style={{ maxWidth: 380 }}>
            For your safety, the Customer ↔ Artist chat (including file, voice and contact sharing)
            opens automatically after the <strong>Platform Service Fee (5% + 18% GST)</strong> is paid.
            You can still view the booking details and accept / reject the request.
          </div>
          <span className="pill pill-amber fs-11" data-testid="chat-locked-status">
            Payment status: {(access?.payment_status || "unpaid").replace("_", " ")}
          </span>
        </div>
      ) : (
      <>
      <div className="card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="card-title">💬 Chat with {otherName}</div>
        <div className="flex gap-8 items-center">
          <span className={`pill ${connected ? "pill-green" : "pill-amber"}`} data-testid="chat-status">
            {connected ? "● Live" : "○ Reconnecting"}
          </span>
          <span className="text-muted fs-11">{participants.length} online</span>
        </div>
      </div>

      <div
        ref={listRef}
        style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}
        data-testid="chat-messages"
      >
        {messages.length === 0 && (
          <div className="text-muted fs-13" style={{ textAlign: "center", padding: 40 }}>
            No messages yet. Say hello! 👋
          </div>
        )}
        {messages.map((m) => {
          const mine = m.sender_id === user?.id;
          const readByOther = (m.read_by || []).filter((u) => u !== m.sender_id).length > 0;
          return (
            <div key={m.id} style={{ alignSelf: mine ? "flex-end" : "flex-start", maxWidth: "80%" }} data-testid={`chat-msg-${m.id}`}>
              <div
                style={{
                  background: mine ? "linear-gradient(135deg, var(--gold), var(--gold-dim))" : "var(--glass)",
                  color: mine ? "#1a1a1a" : "var(--white)",
                  padding: "8px 12px", borderRadius: 12,
                  borderTopRightRadius: mine ? 4 : 12,
                  borderTopLeftRadius: mine ? 12 : 4,
                  fontSize: 14, lineHeight: 1.4,
                  wordBreak: "break-word",
                }}
              >
                {m.type === "voice" && m.media_id ? (
                  <div>
                    <audio src={`${api.defaults.baseURL}/media/${m.media_id}`} controls style={{ maxWidth: 220 }} />
                    <div className="fs-11" style={{ opacity: .7 }}>🎤 Voice note · {Math.round(m.duration_sec || 0)}s</div>
                  </div>
                ) : m.type === "file" && m.media_id ? (
                  <a href={`${api.defaults.baseURL}/media/${m.media_id}`} target="_blank" rel="noreferrer" style={{ color: "inherit", textDecoration: "underline" }}>
                    📎 {m.filename || "file"}
                  </a>
                ) : m.type === "video-request" ? (
                  <div style={{ borderLeft: `3px solid ${mine ? "#1a1a1a" : "var(--gold)"}`, paddingLeft: 8 }}>
                    <div className="fw-700">📹 Video call request</div>
                    <div className="fs-12">{m.content}</div>
                  </div>
                ) : (
                  m.content
                )}
              </div>
              <div className="fs-10 text-muted" style={{ marginTop: 2, textAlign: mine ? "right" : "left" }}>
                {!mine && <span style={{ marginRight: 6 }}>{m.sender_name}</span>}
                {m.created_at?.slice(11, 16)}
                {mine && <span style={{ marginLeft: 4 }} data-testid={`chat-read-${m.id}`}>{readByOther ? "✓✓" : "✓"}</span>}
              </div>
            </div>
          );
        })}
        {typing && (
          <div className="text-muted fs-12" data-testid="chat-typing" style={{ alignSelf: "flex-start", fontStyle: "italic" }}>
            {typing} is typing…
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--glass-border)", alignItems: "center" }}>
        <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={uploadFile} data-testid="chat-file-input" />
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fileInputRef.current?.click()}
          title="Attach file"
          data-testid="chat-attach"
        >📎</button>
        <button
          className={`btn btn-sm ${recording ? "btn-red" : "btn-ghost"}`}
          onClick={recording ? stopVoice : startVoice}
          title={recording ? "Stop recording" : "Voice note"}
          data-testid="chat-voice"
        >{recording ? "■" : "🎤"}</button>
        <button
          className="btn btn-ghost btn-sm"
          onClick={requestVideo}
          title="Request video call"
          data-testid="chat-video"
        >📹</button>
        <input
          className="field-input"
          placeholder={recording ? "Recording…" : "Type a message…"}
          value={draft}
          onChange={(e) => onTyping(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          disabled={recording}
          style={{ flex: 1 }}
          data-testid="chat-input"
        />
        <button className="btn btn-gold" onClick={send} disabled={!draft.trim() || recording} data-testid="chat-send">Send</button>
      </div>
      </>
      )}
    </div>
  );
}
