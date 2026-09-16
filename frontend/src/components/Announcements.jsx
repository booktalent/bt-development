import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * <Announcements /> — mounts once at the top of the App.
 * Renders both a top strip Banner and a modal Popup based on what the Admin
 * broadcast module has configured for the current user's audience. Popups
 * are shown once per browser session unless marked `critical`.
 */
export default function Announcements() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);

  useEffect(() => {
    let cancelled = false;
    api.get("/announcements/active")
      .then((r) => { if (!cancelled) setItems(r.data || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [user?.id]);

  const banners = items.filter((i) => i.channels?.includes("banner"));
  const popups = items.filter((i) => i.channels?.includes("popup"));

  return (
    <>
      {banners.map((b) => <Banner key={b.id} ann={b} onDismiss={() => setItems(items.filter((x) => x.id !== b.id))} />)}
      {popups.map((p) => <Popup key={p.id} ann={p} />)}
    </>
  );
}

function Banner({ ann, onDismiss }) {
  const key = `bt_ann_dismiss_${ann.id}`;
  const [visible, setVisible] = useState(() => !localStorage.getItem(key));
  if (!visible) return null;

  const dismiss = () => {
    if (ann.priority !== "critical") localStorage.setItem(key, "1");
    setVisible(false);
    onDismiss?.();
    api.post(`/announcements/${ann.id}/read`).catch(() => {});
  };

  const bg = {
    critical: "linear-gradient(90deg, #dc2626, #b91c1c)",
    high: "linear-gradient(90deg, #f59e0b, #d97706)",
    normal: "linear-gradient(90deg, rgba(212,175,55,0.9), rgba(180,140,30,0.85))",
    low: "rgba(255,255,255,0.06)",
  }[ann.priority || "normal"];

  return (
    <div className="site-banner" style={{ background: bg }} data-testid={`banner-${ann.id}`}>
      <div className="site-banner-inner">
        <span className="site-banner-title">{ann.title}</span>
        {ann.body && <span className="site-banner-body">— {ann.body}</span>}
        {ann.cta_url && (
          <a href={ann.cta_url} className="site-banner-cta" data-testid={`banner-cta-${ann.id}`}>
            {ann.cta_label || "Learn more"} →
          </a>
        )}
        <button className="site-banner-dismiss" onClick={dismiss} aria-label="Dismiss" data-testid={`banner-dismiss-${ann.id}`}>×</button>
      </div>
    </div>
  );
}

function Popup({ ann }) {
  const key = `bt_ann_popup_${ann.id}`;
  const [visible, setVisible] = useState(() => !sessionStorage.getItem(key));
  if (!visible) return null;

  const close = () => {
    sessionStorage.setItem(key, "1");
    setVisible(false);
    api.post(`/announcements/${ann.id}/read`).catch(() => {});
  };

  return (
    <div className="popup-scrim" data-testid={`popup-${ann.id}`}>
      <div className="popup-card">
        <button className="popup-close" onClick={close} aria-label="Close" data-testid={`popup-close-${ann.id}`}>×</button>
        <h3 style={{ marginTop: 0 }}>{ann.title}</h3>
        {ann.body && <p style={{ color: "var(--white-muted)" }}>{ann.body}</p>}
        {ann.cta_url && (
          <a href={ann.cta_url} className="btn btn-gold" onClick={close} data-testid={`popup-cta-${ann.id}`}>
            {ann.cta_label || "Explore"} →
          </a>
        )}
      </div>
    </div>
  );
}
