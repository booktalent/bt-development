import React, { useEffect, useMemo, useState } from "react";
import api from "../../../lib/api";

/** Simple month grid — no external calendar dep. Rows are weeks. */
function monthDays(year, month) {
  const first = new Date(year, month, 1);
  const startDay = first.getDay(); // 0-Sun
  const days = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= days; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

export default function CalendarView() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const first = `${year}-${String(month + 1).padStart(2, "0")}-01`;
    const last = new Date(year, month + 1, 0);
    const to = `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, "0")}-${String(last.getDate()).padStart(2, "0")}`;
    api.get(`/agency/calendar?from=${first}&to=${to}`).then((r) => setEvents(r.data || [])).catch(() => setEvents([]));
  }, [year, month]);

  const byDay = useMemo(() => {
    const map = {};
    events.forEach((e) => { if (!e.date) return; (map[e.date] ||= []).push(e); });
    return map;
  }, [events]);
  const cells = monthDays(year, month);

  const prev = () => { const m = month - 1; if (m < 0) { setYear(year - 1); setMonth(11); } else setMonth(m); };
  const next = () => { const m = month + 1; if (m > 11) { setYear(year + 1); setMonth(0); } else setMonth(m); };

  return (
    <div data-testid="agency-calendar">
      <div className="ag-section-head">
        <div><h2>Calendar</h2><div className="fs-13">Unified — offline events, platform bookings, follow-ups.</div></div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button className="btn btn-ghost btn-sm" onClick={prev} data-testid="cal-prev">‹</button>
          <div style={{ minWidth: 140, textAlign: "center", fontFamily: "var(--font-serif)", fontSize: 20 }}>
            {MONTHS[month]} {year}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={next} data-testid="cal-next">›</button>
        </div>
      </div>

      <div className="ag-card">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6, marginBottom: 6 }}>
          {DOW.map((d) => (
            <div key={d} className="text-muted fs-11" style={{ textAlign: "center", letterSpacing: ".14em", textTransform: "uppercase" }}>{d}</div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
          {cells.map((d, i) => {
            const key = d ? `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}` : `blank-${i}`;
            const dayEvents = d ? (byDay[key] || []) : [];
            const isToday = d && year === now.getFullYear() && month === now.getMonth() && d === now.getDate();
            return (
              <div key={key} style={{
                minHeight: 88, padding: 6, borderRadius: 8,
                background: d ? "rgba(255,255,255,0.02)" : "transparent",
                border: d ? "1px solid rgba(255,255,255,0.05)" : "1px solid transparent",
                borderColor: isToday ? "rgba(246,211,102,0.5)" : undefined,
              }}>
                {d && <div style={{ fontSize: 12, fontWeight: 600, color: isToday ? "#f6d366" : "#eaeaea" }}>{d}</div>}
                {dayEvents.slice(0, 3).map((e) => (
                  <div key={e.id + e.kind} style={{
                    marginTop: 4, padding: "3px 6px", borderRadius: 4,
                    fontSize: 10.5,
                    background: e.kind === "platform" ? "rgba(246,211,102,0.14)"
                              : e.kind === "offline" ? "rgba(178,148,255,0.14)"
                              : "rgba(110,231,168,0.14)",
                    color: e.kind === "platform" ? "#f6d366" : e.kind === "offline" ? "#b294ff" : "#6ee7a8",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }} title={e.title}>{e.title}</div>
                ))}
                {dayEvents.length > 3 && <div className="text-muted fs-11" style={{ marginTop: 2 }}>+{dayEvents.length - 3} more</div>}
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, marginTop: 12 }} className="text-muted fs-12">
        <div><span className="ag-badge gold">Platform</span> BookTalent bookings</div>
        <div><span className="ag-badge violet">Offline</span> Your events</div>
        <div><span className="ag-badge ok">Follow-up</span> Client CRM</div>
      </div>
    </div>
  );
}
