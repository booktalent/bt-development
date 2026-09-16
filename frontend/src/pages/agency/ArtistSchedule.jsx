/**
 * ArtistSchedule — Iter 68
 * -----------------------
 * Agency Dashboard → Artists → Select Artist → View Schedule
 *
 * Route: /agency/artist/:artistId/schedule
 *
 * Shows:
 *  - 9 KPI tiles (bookings by status + earnings)
 *  - Calendar (Month / Week / Day) using /agency/artist/:id/schedule range
 *  - Sortable + filterable list view
 *  - Availability checker (uses /agency/artist/:id/availability)
 *  - Event drawer with full booking details
 */
import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../../lib/api";
import { useToast } from "../../lib/toast";

/* ── helpers ─────────────────────────────────────────────────── */

const iso = (d) => d.toISOString().slice(0, 10);
const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const endOfMonth = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 0);
const startOfWeek = (d) => {
  const x = new Date(d);
  const day = x.getDay(); // 0..6, 0=Sun
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
};
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const fmtINR = (n) => `₹${Number(n || 0).toLocaleString("en-IN")}`;
const monthLabel = (d) => d.toLocaleString("default", { month: "long", year: "numeric" });

// Normalise "19:00" / "4:00 PM" → minutes since midnight, or null.
const timeToMin = (t) => {
  if (!t) return null;
  const s = String(t).trim().toUpperCase();
  const pm = s.endsWith("PM"); const am = s.endsWith("AM");
  const bare = s.replace(/(AM|PM)/, "").trim();
  const parts = bare.split(":");
  if (parts.length < 2) return null;
  let h = parseInt(parts[0], 10); const m = parseInt(parts[1], 10);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  if (pm && h < 12) h += 12;
  if (am && h === 12) h = 0;
  return h * 60 + m;
};
const minToHHMM = (v) => {
  if (v == null) return "";
  const h = Math.floor(v / 60), m = v % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

const STATUS_TONE = {
  completed: { bg: "#dcfce7", fg: "#166534", label: "Completed" },
  reviewed: { bg: "#dcfce7", fg: "#166534", label: "Reviewed" },
  confirmed: { bg: "#dbeafe", fg: "#1e3a8a", label: "Confirmed" },
  started: { bg: "#bfdbfe", fg: "#1e3a8a", label: "Started" },
  completed_by_artist: { bg: "#e9d5ff", fg: "#6b21a8", label: "Awaiting review" },
  pending_artist: { bg: "#fef3c7", fg: "#92400e", label: "Pending artist" },
  pending_payment: { bg: "#fef3c7", fg: "#92400e", label: "Pending payment" },
  rejected: { bg: "#fee2e2", fg: "#991b1b", label: "Rejected" },
  cancelled: { bg: "#fee2e2", fg: "#991b1b", label: "Cancelled" },
  auto_expired: { bg: "#fee2e2", fg: "#991b1b", label: "Expired" },
};
const StatusPill = ({ status, refund_status }) => {
  const t = STATUS_TONE[status] || { bg: "#e5e7eb", fg: "#374151", label: status || "—" };
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 999, background: t.bg, color: t.fg,
      fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
    }}>
      {refund_status === "successful" ? "Refunded" : t.label}
    </span>
  );
};

/* ── KPI grid ────────────────────────────────────────────────── */

function KpiTile({ label, value, sub, tone = "gold", testId }) {
  const toneMap = {
    gold: { bg: "rgba(212,175,55,0.06)", border: "rgba(212,175,55,0.22)", fg: "#F1D17A" },
    blue: { bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.25)", fg: "#93c5fd" },
    green: { bg: "rgba(34,197,94,0.08)", border: "rgba(34,197,94,0.25)", fg: "#86efac" },
    amber: { bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.28)", fg: "#fcd34d" },
    red: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.25)", fg: "#fca5a5" },
    purple: { bg: "rgba(147,51,234,0.08)", border: "rgba(147,51,234,0.25)", fg: "#c4b5fd" },
  };
  const c = toneMap[tone];
  return (
    <div
      style={{
        padding: 12, borderRadius: 10, background: c.bg, border: `1px solid ${c.border}`,
      }}
      data-testid={testId}
    >
      <div style={{ fontSize: 10.5, color: "rgba(240,238,255,0.6)", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: c.fg, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "rgba(240,238,255,0.5)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* ── Event card (compact — inside a calendar cell) ─────────────── */

function EventChip({ b, onClick }) {
  const t = STATUS_TONE[b.status] || { bg: "#e5e7eb", fg: "#374151" };
  return (
    <button
      onClick={() => onClick(b)}
      title={`${b.event_type} · ${b.customer_name}`}
      className="row-flash-target"
      data-testid={`schedule-event-${b.id}`}
      style={{
        display: "block", width: "100%", textAlign: "left",
        padding: "3px 6px", borderRadius: 6, marginTop: 3,
        background: t.bg, color: t.fg,
        fontSize: 10.5, fontWeight: 600, cursor: "pointer",
        border: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}
    >
      {b.event_time ? `${b.event_time} · ` : ""}{b.event_type || "Booking"}
    </button>
  );
}

/* ── Calendar views ─────────────────────────────────────────── */

function MonthView({ cursor, bookings, onOpen }) {
  const first = startOfMonth(cursor);
  const last = endOfMonth(cursor);
  const leading = first.getDay(); // days from prev month
  const totalCells = Math.ceil((leading + last.getDate()) / 7) * 7;
  const gridStart = addDays(first, -leading);
  const today = iso(new Date());
  const byDate = useMemo(() => {
    const m = {};
    for (const b of bookings) {
      if (!b.event_date) continue;
      (m[b.event_date] = m[b.event_date] || []).push(b);
    }
    return m;
  }, [bookings]);
  return (
    <div data-testid="schedule-month-view">
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(7,1fr)",
        gap: 4, marginBottom: 4, fontSize: 11, color: "rgba(240,238,255,0.55)", textAlign: "center",
      }}>
        {["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map((d) => <div key={d}>{d}</div>)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 4 }}>
        {Array.from({ length: totalCells }).map((_, i) => {
          const d = addDays(gridStart, i);
          const isCur = d.getMonth() === cursor.getMonth();
          const key = iso(d);
          const list = byDate[key] || [];
          return (
            <div
              key={key}
              style={{
                minHeight: 92, padding: 6, borderRadius: 8,
                background: isCur ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.01)",
                border: `1px solid ${key === today ? "#F1D17A" : "rgba(255,255,255,0.06)"}`,
                opacity: isCur ? 1 : 0.4,
                overflow: "hidden",
              }}
            >
              <div style={{
                fontSize: 11, fontWeight: 600, color: key === today ? "#F1D17A" : "rgba(240,238,255,0.7)",
              }}>{d.getDate()}</div>
              {list.slice(0, 3).map((b) => <EventChip key={b.id} b={b} onClick={onOpen} />)}
              {list.length > 3 && (
                <div style={{ fontSize: 10, color: "rgba(240,238,255,0.5)", marginTop: 2 }}>+{list.length - 3} more</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({ cursor, bookings, onOpen }) {
  const s = startOfWeek(cursor);
  const days = Array.from({ length: 7 }, (_, i) => addDays(s, i));
  const byDate = useMemo(() => {
    const m = {}; for (const b of bookings) {
      if (!b.event_date) continue; (m[b.event_date] = m[b.event_date] || []).push(b);
    } return m;
  }, [bookings]);
  const today = iso(new Date());
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 6 }} data-testid="schedule-week-view">
      {days.map((d) => {
        const key = iso(d);
        const list = byDate[key] || [];
        return (
          <div key={key} style={{
            padding: 10, borderRadius: 10, minHeight: 200,
            background: "rgba(255,255,255,0.03)",
            border: `1px solid ${key === today ? "#F1D17A" : "rgba(255,255,255,0.06)"}`,
          }}>
            <div style={{ fontSize: 11, textTransform: "uppercase", color: "rgba(240,238,255,0.55)" }}>
              {d.toLocaleDateString("default", { weekday: "short" })}
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: key === today ? "#F1D17A" : "#F0EEFF", marginBottom: 8 }}>
              {d.getDate()}
            </div>
            {list.length === 0 ? (
              <div style={{ fontSize: 11, color: "rgba(240,238,255,0.35)" }}>—</div>
            ) : (
              list.map((b) => <EventChip key={b.id} b={b} onClick={onOpen} />)
            )}
          </div>
        );
      })}
    </div>
  );
}

function DayView({ cursor, bookings, onOpen }) {
  const key = iso(cursor);
  const list = bookings.filter((b) => b.event_date === key)
    .sort((a, b) => (timeToMin(a.event_time) ?? 9999) - (timeToMin(b.event_time) ?? 9999));
  return (
    <div data-testid="schedule-day-view" style={{ padding: 6 }}>
      <div style={{ fontSize: 13, color: "rgba(240,238,255,0.6)", marginBottom: 12 }}>
        {cursor.toLocaleDateString("default", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
      </div>
      {list.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", color: "rgba(240,238,255,0.4)" }}>
          No events scheduled on this day.
        </div>
      )}
      {list.map((b) => (
        <button
          key={b.id}
          onClick={() => onOpen(b)}
          data-testid={`schedule-event-${b.id}`}
          style={{
            display: "flex", width: "100%", textAlign: "left",
            padding: "10px 14px", borderRadius: 10, marginBottom: 6, cursor: "pointer",
            background: "rgba(255,255,255,0.04)", color: "#F0EEFF", border: "1px solid rgba(255,255,255,0.06)",
            gap: 14, alignItems: "center",
          }}
        >
          <div style={{ minWidth: 70, fontSize: 13, fontWeight: 700, color: "#F1D17A" }}>
            {b.event_time || "—"}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>{b.event_type} · {b.customer_name}</div>
            <div style={{ fontSize: 11, color: "rgba(240,238,255,0.55)" }}>
              {[b.venue, b.city].filter(Boolean).join(" · ") || "—"}
            </div>
          </div>
          <div style={{ minWidth: 100, textAlign: "right", fontWeight: 700 }}>{fmtINR(b.artist_fee)}</div>
          <StatusPill status={b.status} refund_status={b.refund_status} />
        </button>
      ))}
    </div>
  );
}

/* ── List view (filters + sort) ────────────────────────────────── */

function ListView({ bookings, onOpen }) {
  const [status, setStatus] = useState("");
  const [eventType, setEventType] = useState("");
  const [city, setCity] = useState("");
  const [paymentStatus, setPaymentStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [sortKey, setSortKey] = useState("event_date");
  const [sortDir, setSortDir] = useState("desc");

  const eventTypes = useMemo(() => Array.from(new Set(bookings.map((b) => b.event_type).filter(Boolean))).sort(), [bookings]);
  const cities = useMemo(() => Array.from(new Set(bookings.map((b) => b.city).filter(Boolean))).sort(), [bookings]);
  const statuses = useMemo(() => Array.from(new Set(bookings.map((b) => b.status).filter(Boolean))).sort(), [bookings]);
  const payStatuses = useMemo(() => Array.from(new Set(bookings.map((b) => b.payment_status).filter(Boolean))).sort(), [bookings]);

  const filtered = useMemo(() => {
    let out = bookings.slice();
    if (status) out = out.filter((b) => b.status === status);
    if (eventType) out = out.filter((b) => b.event_type === eventType);
    if (city) out = out.filter((b) => b.city === city);
    if (paymentStatus) out = out.filter((b) => b.payment_status === paymentStatus);
    if (from) out = out.filter((b) => (b.event_date || "") >= from);
    if (to) out = out.filter((b) => (b.event_date || "") <= to);
    const dir = sortDir === "asc" ? 1 : -1;
    out.sort((a, b) => {
      let x = a[sortKey], y = b[sortKey];
      if (sortKey === "amount") { x = a.artist_fee; y = b.artist_fee; }
      if ((x == null) && (y == null)) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x).localeCompare(String(y)) * dir;
    });
    return out;
  }, [bookings, status, eventType, city, paymentStatus, from, to, sortKey, sortDir]);

  const toggleSort = (k) => {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("asc"); }
  };
  const SortHead = ({ k, label }) => (
    <th onClick={() => toggleSort(k)} style={{ cursor: "pointer", userSelect: "none" }} data-testid={`sort-${k}`}>
      {label} {sortKey === k ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </th>
  );

  return (
    <div data-testid="schedule-list-view">
      {/* Filters */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 12, padding: 12, borderRadius: 10, background: "rgba(255,255,255,0.03)" }}>
        <input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="filter-from" title="From date" />
        <input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} data-testid="filter-to" title="To date" />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="filter-status">
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input" value={eventType} onChange={(e) => setEventType(e.target.value)} data-testid="filter-event-type">
          <option value="">All event types</option>
          {eventTypes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input" value={city} onChange={(e) => setCity(e.target.value)} data-testid="filter-city">
          <option value="">All cities</option>
          {cities.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="input" value={paymentStatus} onChange={(e) => setPaymentStatus(e.target.value)} data-testid="filter-payment">
          <option value="">All payment statuses</option>
          {payStatuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={() => { setStatus(""); setEventType(""); setCity(""); setPaymentStatus(""); setFrom(""); setTo(""); }} data-testid="filter-reset">Reset</button>
        <span className="text-muted fs-12" style={{ marginLeft: "auto", alignSelf: "center" }}>{filtered.length} of {bookings.length}</span>
      </div>

      <div style={{ overflow: "auto" }}>
        <table className="table" style={{ width: "100%", minWidth: 900, fontSize: 12 }}>
          <thead>
            <tr>
              <th>Ref</th>
              <SortHead k="event_date" label="Event Date" />
              <th>Time</th>
              <SortHead k="event_type" label="Event" />
              <th>Client</th>
              <th>Location</th>
              <SortHead k="amount" label="Amount" />
              <SortHead k="status" label="Status" />
              <th>Payment</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((b) => (
              <tr key={b.id} onClick={() => onOpen(b)} style={{ cursor: "pointer" }} data-testid={`list-row-${b.id}`}>
                <td><code style={{ fontSize: 10 }}>{b.ref}</code></td>
                <td>{b.event_date}</td>
                <td>{b.event_time || "—"}</td>
                <td>{b.event_type}</td>
                <td>{b.customer_name}</td>
                <td>{[b.venue, b.city].filter(Boolean).join(", ") || "—"}</td>
                <td>{fmtINR(b.artist_fee)}</td>
                <td><StatusPill status={b.status} refund_status={b.refund_status} /></td>
                <td>{b.payment_status || "—"}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={9} style={{ padding: 40, textAlign: "center", color: "#6b7280" }}>No bookings match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Availability check panel ─────────────────────────────────── */

function AvailabilityPanel({ artistId }) {
  const [date, setDate] = useState(iso(new Date()));
  const [time, setTime] = useState("19:00");
  const [duration, setDuration] = useState(4);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const check = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.get(`/agency/artist/${artistId}/availability`, {
        params: { date, event_time: time, duration_hours: duration },
      });
      setResult(r.data);
    } catch (e) {
      setResult({ available: null, error: e?.response?.data?.detail || "check failed" });
    }
    setBusy(false);
  };
  return (
    <div style={{ padding: 14, borderRadius: 10, background: "rgba(255,255,255,0.03)", marginBottom: 14 }} data-testid="availability-panel">
      <div style={{ fontWeight: 700, marginBottom: 8, color: "#F1D17A" }}>🔎 Check Availability</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
        <div>
          <div className="text-muted fs-11">Date</div>
          <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} data-testid="avail-date" />
        </div>
        <div>
          <div className="text-muted fs-11">Start time</div>
          <input type="time" className="input" value={time} onChange={(e) => setTime(e.target.value)} data-testid="avail-time" />
        </div>
        <div>
          <div className="text-muted fs-11">Duration (hrs)</div>
          <input type="number" min="1" max="12" step="0.5" className="input" style={{ width: 100 }} value={duration} onChange={(e) => setDuration(parseFloat(e.target.value) || 4)} data-testid="avail-duration" />
        </div>
        <button className="btn btn-gold" disabled={busy} onClick={check} data-testid="avail-check-btn">
          {busy ? "Checking…" : "Check"}
        </button>
      </div>
      {result && (
        <div style={{
          marginTop: 12, padding: 12, borderRadius: 8,
          background: result.available === false ? "rgba(239,68,68,0.10)"
                   : result.available === true ? "rgba(34,197,94,0.10)"
                   : "rgba(239,68,68,0.10)",
          border: `1px solid ${result.available === false ? "rgba(239,68,68,0.35)" : "rgba(34,197,94,0.35)"}`,
        }} data-testid="avail-result">
          {result.error && <div style={{ color: "#fca5a5", fontWeight: 600 }}>{result.error}</div>}
          {result.available === true && <div style={{ color: "#86efac", fontWeight: 700 }}>✅ Artist is available at this time.</div>}
          {result.available === false && (
            <>
              <div style={{ color: "#fca5a5", fontWeight: 700, marginBottom: 6 }}>⚠️ Artist is already booked during this time.</div>
              {result.conflicts.map((c) => (
                <div key={c.id} className="fs-12" style={{ marginTop: 4 }}>
                  · <code>{c.ref}</code> — {c.event_type} @ {c.event_time || "all day"}
                  <StatusPill status={c.status} /> {c.customer_name}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Event drawer ─────────────────────────────────────────────── */

function EventDrawer({ b, onClose }) {
  if (!b) return null;
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 200, display: "flex", justifyContent: "flex-end" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 540, maxWidth: "95vw", background: "#0F0F1B", color: "#F0EEFF", padding: 24, overflow: "auto", boxShadow: "-8px 0 32px rgba(0,0,0,0.55)" }}
        data-testid="event-drawer"
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>{b.event_type || "Booking"}</h3>
          <button className="btn btn-link" onClick={onClose} data-testid="event-drawer-close">✕</button>
        </div>
        <code style={{ fontSize: 11, color: "#F1D17A" }}>{b.ref}</code>

        <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", fontSize: 13 }}>
          <b>Event Date</b><span>{b.event_date}</span>
          <b>Start Time</b><span>{b.event_time || "—"}</span>
          <b>Client</b><span>{b.customer_name}{b.customer_email && <> · {b.customer_email}</>}</span>
          <b>Location</b><span>{[b.venue, b.city].filter(Boolean).join(", ") || "—"}</span>
          <b>Package</b><span>{b.package_name || "—"}</span>
          {b.guests && (<><b>Guests</b><span>{b.guests}</span></>)}
          <b>Booking Status</b><span><StatusPill status={b.status} refund_status={b.refund_status} /></span>
          <b>Payment Status</b><span>{b.payment_status || "—"}</span>
          <b>Artist Fee</b><span style={{ color: "#F1D17A", fontWeight: 700 }}>{fmtINR(b.artist_fee)}</span>
          {b.platform_charges != null && (<><b>Platform Charges</b><span>{fmtINR(b.platform_charges)}</span></>)}
          {b.agency_commission != null && (<><b>Agency Commission</b><span>{fmtINR(b.agency_commission)}</span></>)}
          {b.refund_status && (
            <>
              <b>Refund Status</b>
              <span style={{ color: b.refund_status === "successful" ? "#86efac" : "#fca5a5" }}>
                {b.refund_status}{b.refund_amount ? ` · ${fmtINR(b.refund_amount)}` : ""}
              </span>
            </>
          )}
          {b.refund_reason && (<><b>Refund Reason</b><span className="fs-12">{b.refund_reason}</span></>)}
        </div>
      </div>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────── */

export default function ArtistSchedule() {
  const { artistId } = useParams();
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("month"); // month | week | day | list
  const [cursor, setCursor] = useState(new Date());
  const [openEvent, setOpenEvent] = useState(null);

  useEffect(() => {
    api.get(`/agency/artist/${artistId}/earnings`)
      .then((r) => setData(r.data))
      .catch((e) => toast(e?.response?.data?.detail || "Failed to load schedule", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artistId]);

  const bookings = data?.bookings || [];
  const totals = data?.totals || {};
  const artist = data?.artist || {};

  const shift = (dir) => {
    const c = new Date(cursor);
    if (tab === "month") c.setMonth(c.getMonth() + dir);
    else if (tab === "week") c.setDate(c.getDate() + 7 * dir);
    else c.setDate(c.getDate() + dir);
    setCursor(c);
  };

  return (
    <div style={{ padding: 24 }} data-testid="artist-schedule-page">
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 18, flexWrap: "wrap", gap: 12 }}>
        <div>
          <Link to="/agency/artists" style={{ fontSize: 12, color: "rgba(240,238,255,0.6)" }} data-testid="back-to-artists">← Back to Artists</Link>
          <h1 style={{ margin: "6px 0", fontFamily: "'Cormorant Garamond', serif", fontSize: 30 }}>
            {artist.stage_name || artist.name || "Artist"} <span style={{ color: "#F1D17A" }}>· Schedule</span>
          </h1>
          <div className="text-muted fs-12">
            {artist.category}{artist.city && <> · {artist.city}</>}{artist.email && <> · {artist.email}</>}
          </div>
        </div>
      </div>

      {/* KPI Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 18 }}>
        <KpiTile label="Total Bookings" value={totals.total_bookings ?? 0} tone="gold" testId="kpi-total" />
        <KpiTile label="Completed" value={totals.completed_events ?? 0} sub={fmtINR(totals.completed_earnings)} tone="green" testId="kpi-completed" />
        <KpiTile label="Upcoming" value={totals.upcoming_events ?? 0} sub={fmtINR(totals.upcoming_earnings)} tone="blue" testId="kpi-upcoming" />
        <KpiTile label="Confirmed" value={totals.confirmed_events ?? 0} sub={fmtINR(totals.confirmed_booking_value)} tone="blue" testId="kpi-confirmed" />
        <KpiTile label="Pending" value={totals.pending_events ?? 0} tone="amber" testId="kpi-pending" />
        <KpiTile label="Cancelled" value={totals.cancelled_events ?? 0} tone="red" testId="kpi-cancelled" />
        <KpiTile label="Refunded" value={totals.refunded_events ?? 0} tone="red" testId="kpi-refunded" />
        <KpiTile label="Total Earnings" value={fmtINR(totals.total_earnings)} tone="gold" testId="kpi-earnings" />
        <KpiTile label="Agency Commission" value={fmtINR(totals.agency_commission_earned)}
                 sub={`@ ${totals.commission_pct ?? 0}%`} tone="purple" testId="kpi-commission" />
      </div>

      {/* Availability check */}
      <AvailabilityPanel artistId={artistId} />

      {/* Tabs + navigator */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        {["month", "week", "day", "list"].map((k) => (
          <button
            key={k}
            className={`btn btn-sm ${tab === k ? "btn-gold" : "btn-ghost"}`}
            onClick={() => setTab(k)}
            data-testid={`schedule-tab-${k}`}
          >
            {k[0].toUpperCase() + k.slice(1)}
          </button>
        ))}
        {tab !== "list" && (
          <>
            <div style={{ marginLeft: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => shift(-1)} data-testid="cal-prev">‹</button>
              <div style={{ minWidth: 180, textAlign: "center", fontWeight: 600 }} data-testid="cal-label">
                {tab === "month" && monthLabel(cursor)}
                {tab === "week" && `Week of ${iso(startOfWeek(cursor))}`}
                {tab === "day" && iso(cursor)}
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => shift(1)} data-testid="cal-next">›</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setCursor(new Date())} data-testid="cal-today">Today</button>
            </div>
          </>
        )}
      </div>

      {!data && <div style={{ padding: 40, textAlign: "center", color: "rgba(240,238,255,0.5)" }}>Loading schedule…</div>}

      {data && (
        <>
          {tab === "month" && <MonthView cursor={cursor} bookings={bookings} onOpen={setOpenEvent} />}
          {tab === "week"  && <WeekView cursor={cursor} bookings={bookings} onOpen={setOpenEvent} />}
          {tab === "day"   && <DayView cursor={cursor} bookings={bookings} onOpen={setOpenEvent} />}
          {tab === "list"  && <ListView bookings={bookings} onOpen={setOpenEvent} />}
        </>
      )}

      <EventDrawer b={openEvent} onClose={() => setOpenEvent(null)} />
    </div>
  );
}
