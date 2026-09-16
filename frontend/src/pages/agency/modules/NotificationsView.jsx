import React, { useEffect, useState } from "react";
import api from "../../../lib/api";

export default function NotificationsView() {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const load = () => api.get("/agency/notifications").then((r) => { setItems(r.data.items || []); setUnread(r.data.unread || 0); }).catch(() => {});
  useEffect(() => { load(); }, []);

  const read = async (id) => { await api.post(`/agency/notifications/${id}/read`); load(); };

  return (
    <div data-testid="agency-notifications">
      <div className="ag-section-head">
        <div><h2>Notifications</h2><div className="fs-13">Follow-ups, event alerts, payment reminders — everything the agency team should know.</div></div>
        {unread > 0 && <span className="ag-badge gold">{unread} unread</span>}
      </div>

      {items.length === 0 ? (
        <div className="ag-empty"><h3>All clear ✨</h3><div>New notifications will appear here.</div></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((n) => (
            <div key={n.id} className="ag-card" style={{ display: "flex", justifyContent: "space-between", gap: 12, opacity: n.read ? 0.6 : 1 }}>
              <div>
                <span className={`ag-badge ${n.kind === "event_created" ? "gold" : n.kind === "followup" ? "violet" : ""}`}>{n.kind}</span>
                <span style={{ marginLeft: 8 }}>{n.title}</span>
                <div className="text-muted fs-11 mt-4">{new Date(n.created_at).toLocaleString()}</div>
              </div>
              {!n.read && <button className="btn btn-ghost btn-sm" onClick={() => read(n.id)}>Mark read</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
