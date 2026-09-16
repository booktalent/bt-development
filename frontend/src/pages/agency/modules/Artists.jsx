import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../../../lib/api";

function OnlineRoster() {
  const [roster, setRoster] = useState([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteCommission, setInviteCommission] = useState(15);
  const [seedName, setSeedName] = useState("");
  const [seedPhone, setSeedPhone] = useState("");
  const [seedCategory, setSeedCategory] = useState("");
  const [seedCity, setSeedCity] = useState("");
  const [showSeed, setShowSeed] = useState(false);
  const [msg, setMsg] = useState(null);
  const [referral, setReferral] = useState(null); // Iter 63
  const [paymentsFor, setPaymentsFor] = useState(null); // Iter 63.4 — artist row we're viewing history for
  const [paymentsRows, setPaymentsRows] = useState([]);
  const [earningsFor, setEarningsFor] = useState(null); // Iter 64 — artist earnings drawer
  const [earnings, setEarnings] = useState(null);

  // Load artist boost + subscription payments whenever a row is opened.
  useEffect(() => {
    if (!paymentsFor) { setPaymentsRows([]); return; }
    api.get(`/agency/artist/${paymentsFor.artist_id}/payments`)
      .then((r) => setPaymentsRows(r.data || []))
      .catch(() => setPaymentsRows([]));
  }, [paymentsFor]);

  // Iter 64 — Load complete artist earnings (bookings across full history).
  useEffect(() => {
    if (!earningsFor) { setEarnings(null); return; }
    api.get(`/agency/artist/${earningsFor.artist_id}/earnings`)
      .then((r) => setEarnings(r.data))
      .catch(() => setEarnings(null));
  }, [earningsFor]);

  const load = () => api.get("/agency/roster").then((r) => setRoster(r.data || [])).catch(() => setRoster([]));
  useEffect(() => {
    load();
    // Iter 63 — Load the agency's stable referral link.
    api.get("/agency/referral").then((r) => setReferral(r.data)).catch(() => setReferral(null));
  }, []);

  const copyReferral = async () => {
    if (!referral?.link) return;
    try {
      await navigator.clipboard.writeText(referral.link);
      setMsg({ ok: true, text: "Referral link copied — share with the artist." });
    } catch { /* ignore */ }
  };

  const invite = async () => {
    if (!inviteEmail) return;
    try {
      const payload = { artist_email: inviteEmail, commission_pct: Number(inviteCommission) };
      if (showSeed) {
        const [first, ...rest] = (seedName || "").trim().split(/\s+/);
        if (first) payload.first_name = first;
        if (rest.length) payload.last_name = rest.join(" ");
        if (seedPhone) payload.phone = seedPhone;
        if (seedCategory) payload.category = seedCategory;
        if (seedCity) payload.city = seedCity;
        if (seedName) payload.stage_name = seedName;
      }
      const r = await api.post("/agency/invite", payload);
      if (r.data?.auto_provisioned) {
        setMsg({ ok: true, text: `New artist account created for ${inviteEmail}. They can claim it via "Forgot password" on login.` });
      } else {
        setMsg({ ok: true, text: `Invite sent to ${inviteEmail}. Awaiting their acceptance.` });
      }
      setInviteEmail(""); setSeedName(""); setSeedPhone(""); setSeedCategory(""); setSeedCity(""); setShowSeed(false);
      load();
    } catch (e) { setMsg({ ok: false, text: e?.response?.data?.detail || "Failed to invite" }); }
  };
  const remove = async (id) => {
    if (!window.confirm("Remove artist from roster?")) return;
    await api.post(`/agency/remove/${id}`); load();
  };
  const changeCommission = async (id, pct) => {
    try { await api.patch(`/agency/roster/${id}/commission`, { commission_pct: Number(pct) }); load(); }
    catch { /* ignore */ }
  };

  return (
    <div>
      {/* Iter 63 — Referral link card */}
      {referral && (
        <div className="ag-card" style={{ marginBottom: 16, background: "linear-gradient(135deg, rgba(212,175,55,0.08), rgba(124,58,237,0.08))", border: "1px solid rgba(212,175,55,0.25)" }} data-testid="ag-referral-card">
          <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>🔗 Your Referral Link</h4>
          <div className="text-muted fs-12" style={{ marginBottom: 10 }}>{referral.note}</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              readOnly
              value={referral.link}
              onClick={(e) => e.target.select()}
              style={{ flex: 1, minWidth: 260, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.12)", color: "#fff", borderRadius: 6, padding: "8px 10px", fontSize: 12 }}
              data-testid="ag-referral-link"
            />
            <button className="btn btn-gold btn-sm" onClick={copyReferral} data-testid="ag-referral-copy">Copy Link</button>
          </div>
          <div className="text-muted fs-11" style={{ marginTop: 8 }}>
            Code: <code style={{ color: "#F1D17A" }}>{referral.code}</code>
          </div>
        </div>
      )}

      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>Add Artist to Roster</h4>
        <div className="text-muted fs-12" style={{ marginBottom: 12 }}>
          If the artist already has a BookTalent account, they'll get an invite to accept. If not, we'll auto-create a pending account and they can claim it via "Forgot password".
        </div>
        <div className="ag-form-grid">
          <label>Artist email
            <input type="email" placeholder="artist@example.com" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} data-testid="ag-invite-email" />
          </label>
          <label>Commission %
            <input type="number" min="0" max="50" value={inviteCommission} onChange={(e) => setInviteCommission(e.target.value)} data-testid="ag-invite-commission" />
          </label>
          <label style={{ justifyContent: "flex-end" }}>
            <span>&nbsp;</span>
            <button className="btn btn-gold btn-sm" onClick={invite} data-testid="ag-invite-send">Send Invite / Add Artist</button>
          </label>
        </div>

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ marginTop: 12 }}
          onClick={() => setShowSeed((v) => !v)}
          data-testid="ag-invite-seed-toggle"
        >
          {showSeed ? "− Hide extra profile fields" : "+ Add profile details (for brand-new artists)"}
        </button>

        {showSeed && (
          <div className="ag-form-grid" style={{ marginTop: 12 }}>
            <label>Full name / Stage name
              <input value={seedName} onChange={(e) => setSeedName(e.target.value)} placeholder="Priya Sharma" data-testid="ag-invite-seed-name" />
            </label>
            <label>Phone
              <input value={seedPhone} onChange={(e) => setSeedPhone(e.target.value)} placeholder="+91 98765 43210" data-testid="ag-invite-seed-phone" />
            </label>
            <label>Category
              <input value={seedCategory} onChange={(e) => setSeedCategory(e.target.value)} placeholder="Bollywood Vocalist" data-testid="ag-invite-seed-category" />
            </label>
            <label>City
              <input value={seedCity} onChange={(e) => setSeedCity(e.target.value)} placeholder="Mumbai" data-testid="ag-invite-seed-city" />
            </label>
          </div>
        )}

        {msg && <div className="fs-12 mt-8" style={{ color: msg.ok ? "#6ee7a8" : "#ff8888" }}>{msg.text}</div>}
      </div>

      {roster.length === 0 ? (
        <div className="ag-empty"><h3>No online artists yet</h3><div>Add your first artist using the form above. Their profile will show up here once they're active.</div></div>
      ) : (
        <table className="ag-table" data-testid="ag-online-roster">
          <thead><tr><th>Artist</th><th>Category</th><th>Commission %</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {roster.map((r) => (
              <tr key={r.id} data-testid={`ag-roster-row-${r.artist_id}`}>
                <td>
                  <b>{r.artist?.stage_name || r.artist_email}</b>
                  <div className="text-muted fs-11">{r.artist_email}</div>
                  {r.auto_provisioned && <span className="ag-badge violet" style={{ marginTop: 4 }}>Auto-provisioned</span>}
                </td>
                <td>{r.artist?.category || "—"}</td>
                <td>
                  <input
                    type="number" min="0" max="50" defaultValue={r.commission_pct || 15}
                    onBlur={(e) => changeCommission(r.artist_id, e.target.value)}
                    style={{ width: 70, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", color: "#fff", borderRadius: 6, padding: "6px 8px" }}
                  />
                </td>
                <td><span className={`ag-badge ${r.status === "active" || r.status === "accepted" ? "ok" : r.status === "pending" ? "warn" : ""}`}>{r.status || "active"}</span></td>
                <td>
                  {r.status === "active" && (
                    <>
                      <Link
                        to={`/agency/artist/${r.artist_id}/schedule`}
                        className="btn btn-gold btn-sm"
                        data-testid={`ag-view-schedule-${r.artist_id}`}
                        style={{ marginRight: 6 }}
                      >
                        📅 View Schedule
                      </Link>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEarningsFor(r)} data-testid={`ag-view-earnings-${r.artist_id}`}>Earnings</button>
                    </>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={() => setPaymentsFor(r)} data-testid={`ag-view-payments-${r.artist_id}`}>Payments</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => remove(r.artist_id)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {earningsFor && (
        <div
          data-testid="ag-earnings-drawer"
          onClick={() => setEarningsFor(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
            zIndex: 200, display: "flex", justifyContent: "flex-end",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 820, maxWidth: "95vw", background: "#0F0F1B", color: "#F0EEFF",
              padding: 26, overflow: "auto", boxShadow: "-8px 0 32px rgba(0,0,0,0.55)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0 }}>Artist Earnings</h3>
                <div className="text-muted fs-12">
                  {earnings?.artist?.stage_name || earningsFor.artist_email}
                  {earnings?.artist?.category && <> · {earnings.artist.category}</>}
                  {earnings?.artist?.city && <> · {earnings.artist.city}</>}
                </div>
              </div>
              <button className="btn btn-link" onClick={() => setEarningsFor(null)} data-testid="ag-earnings-close">✕</button>
            </div>

            {!earnings ? (
              <div className="text-muted fs-13" style={{ padding: 32, textAlign: "center" }}>Loading earnings…</div>
            ) : (
              <>
                {/* Totals grid */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
                  <EarningsKpi label="Total Earnings" value={earnings.totals.total_earnings} testId="ag-earn-total" />
                  <EarningsKpi label="Completed" value={earnings.totals.completed_earnings} testId="ag-earn-completed" sub={`${earnings.totals.completed_events} events`} />
                  <EarningsKpi label="Upcoming" value={earnings.totals.upcoming_earnings} testId="ag-earn-upcoming" sub={`${earnings.totals.upcoming_events} events`} />
                  <EarningsKpi label="Confirmed" value={earnings.totals.confirmed_booking_value} testId="ag-earn-confirmed" sub={`${earnings.totals.confirmed_events} events`} />
                </div>
                <div className="text-muted fs-12" style={{ marginBottom: 12 }}>
                  Commission @ <b>{earnings.totals.commission_pct}%</b> · Agency earned so far:
                  <b style={{ color: "#F1D17A", marginLeft: 6 }}>₹{Number(earnings.totals.agency_commission_earned || 0).toLocaleString("en-IN")}</b>
                </div>

                {/* Bookings table */}
                {earnings.bookings.length === 0 ? (
                  <div className="text-muted fs-13" style={{ padding: 24, textAlign: "center" }}>
                    No bookings yet for this artist.
                  </div>
                ) : (
                  <div style={{ overflow: "auto" }}>
                    <table className="table" style={{ width: "100%", minWidth: 720, fontSize: 12 }} data-testid="ag-earnings-bookings">
                      <thead>
                        <tr>
                          <th>Ref</th>
                          <th>Date</th>
                          <th>Customer</th>
                          <th>Location</th>
                          <th>Status</th>
                          <th>Artist Fee</th>
                          <th>Platform</th>
                          <th>Commission</th>
                          <th>Payment</th>
                          <th>Refund</th>
                        </tr>
                      </thead>
                      <tbody>
                        {earnings.bookings.map((b) => (
                          <tr key={b.id} data-testid={`ag-earn-row-${b.id}`}>
                            <td><code style={{ fontSize: 11 }}>{b.ref || b.id.slice(0, 8)}</code></td>
                            <td>{b.event_date || "—"}</td>
                            <td>{b.customer_name || "—"}</td>
                            <td>{[b.venue, b.city].filter(Boolean).join(", ") || "—"}</td>
                            <td>
                              <span style={{
                                padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 600,
                                background: b.status === "completed" ? "#dcfce7"
                                          : b.status === "confirmed" ? "#dbeafe"
                                          : b.status?.includes("pending") ? "#fef3c7"
                                          : b.status === "rejected" || b.status === "cancelled" || b.status === "auto_expired" ? "#fee2e2"
                                          : "#e5e7eb",
                                color: b.status === "completed" ? "#166534"
                                     : b.status === "confirmed" ? "#1e3a8a"
                                     : b.status?.includes("pending") ? "#92400e"
                                     : b.status === "rejected" || b.status === "cancelled" || b.status === "auto_expired" ? "#991b1b"
                                     : "#374151",
                              }}>{b.status?.replace(/_/g, " ")}</span>
                            </td>
                            <td>₹{Number(b.artist_fee || 0).toLocaleString("en-IN")}</td>
                            <td>₹{Number(b.platform_charges || 0).toLocaleString("en-IN")}</td>
                            <td style={{ color: "#F1D17A" }}>₹{Number(b.agency_commission || 0).toLocaleString("en-IN")}</td>
                            <td style={{ fontSize: 11 }}>{b.payment_status || "—"}</td>
                            <td style={{ fontSize: 11 }}>
                              {b.refund_status ? (
                                <span style={{ color: b.refund_status === "successful" ? "#6ee7a8" : b.refund_status === "failed" ? "#ff8888" : "#fbbf24" }}>
                                  {b.refund_status}
                                  {b.refund_amount ? ` · ₹${Number(b.refund_amount).toLocaleString("en-IN")}` : ""}
                                </span>
                              ) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {paymentsFor && (
        <div
          data-testid="ag-payments-drawer"
          onClick={() => setPaymentsFor(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
            zIndex: 200, display: "flex", justifyContent: "flex-end",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 560, background: "#0F0F1B", color: "#F0EEFF", padding: 26,
              overflow: "auto", boxShadow: "-8px 0 32px rgba(0,0,0,0.55)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0 }}>Payment History</h3>
                <div className="text-muted fs-12">{paymentsFor.artist?.stage_name || paymentsFor.artist_email}</div>
              </div>
              <button className="btn btn-link" onClick={() => setPaymentsFor(null)} data-testid="ag-payments-close">✕</button>
            </div>
            <div className="text-muted fs-12" style={{ marginBottom: 12 }}>
              Subscription + boost payments made by this artist. Bookings are on the CRM tab.
            </div>
            {paymentsRows.length === 0 ? (
              <div className="text-muted fs-13" style={{ padding: 20, textAlign: "center" }}>No boost or subscription payments yet.</div>
            ) : (
              <table className="table" style={{ width: "100%" }}>
                <thead><tr><th>When</th><th>Kind</th><th>Description</th><th>Amount</th><th>Status</th><th>Ref</th></tr></thead>
                <tbody>
                  {paymentsRows.map((p) => (
                    <tr key={p.id} data-testid={`ag-payment-row-${p.id}`}>
                      <td style={{ fontSize: 12 }}>{p.created_at?.slice(0, 16).replace("T", " ")}</td>
                      <td>{p.payment_kind === "subscription" ? "💎 Sub" : "🚀 Boost"}</td>
                      <td style={{ fontSize: 12 }}>{p.label || "—"}</td>
                      <td>₹{Number(p.amount || 0).toLocaleString("en-IN")}</td>
                      <td>
                        <span style={{
                          padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600,
                          background: p.status === "completed" ? "#dcfce7" : p.status === "failed" ? "#fee2e2" : "#fef3c7",
                          color: p.status === "completed" ? "#166534" : p.status === "failed" ? "#991b1b" : "#92400e",
                        }}>{p.status || "—"}</span>
                      </td>
                      <td><code style={{ fontSize: 10 }}>{p.easepayid || p.txnid || "—"}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function OfflineArtists() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ name: "", category: "", phone: "", email: "", base_price: 0, city: "" });
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/agency/offline-artists").then((r) => setList(r.data || [])).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.name) return;
    setBusy(true);
    try {
      await api.post("/agency/offline-artists", { ...form, base_price: Number(form.base_price) || 0 });
      setForm({ name: "", category: "", phone: "", email: "", base_price: 0, city: "" }); load();
    } finally { setBusy(false); }
  };
  const remove = async (id) => {
    if (!window.confirm("Delete offline artist?")) return;
    await api.delete(`/agency/offline-artists/${id}`); load();
  };

  return (
    <div>
      <div className="ag-card" style={{ marginBottom: 16 }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>Add Offline Artist</h4>
        <div className="ag-form-grid">
          <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="ag-off-name" /></label>
          <label>Category<input placeholder="e.g. Singer" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></label>
          <label>Phone<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label>Email<input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>City<input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></label>
          <label>Base price (₹)<input type="number" value={form.base_price} onChange={(e) => setForm({ ...form, base_price: e.target.value })} /></label>
          <label style={{ justifyContent: "flex-end" }}><span>&nbsp;</span>
            <button className="btn btn-gold btn-sm" disabled={busy} onClick={create} data-testid="ag-off-create">Add Artist</button>
          </label>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="ag-empty"><h3>No offline artists yet</h3><div>These records stay private to your agency — never shown on BookTalent.</div></div>
      ) : (
        <table className="ag-table" data-testid="ag-offline-list">
          <thead><tr><th>Name</th><th>Category</th><th>Contact</th><th>City</th><th>Base ₹</th><th></th></tr></thead>
          <tbody>
            {list.map((a) => (
              <tr key={a.id}>
                <td><b>{a.name}</b>{a.stage_name && <div className="text-muted fs-11">{a.stage_name}</div>}</td>
                <td>{a.category || "—"}</td>
                <td>{a.phone || "—"}<div className="text-muted fs-11">{a.email || ""}</div></td>
                <td>{a.city || "—"}</td>
                <td>{a.base_price?.toLocaleString?.("en-IN") || 0}</td>
                <td><button className="btn btn-ghost btn-sm" onClick={() => remove(a.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Artists() {
  const [tab, setTab] = useState("online");
  return (
    <div data-testid="agency-artists">
      <div className="ag-section-head">
        <div>
          <h2>Artist Management</h2>
          <div className="fs-13">Unified view — the same artist can be managed both online (BookTalent roster) and offline (private CRM).</div>
        </div>
      </div>

      <div className="ag-tabs">
        <button className={`ag-tab ${tab === "online" ? "active" : ""}`} onClick={() => setTab("online")} data-testid="ag-tab-online">Online Roster</button>
        <button className={`ag-tab ${tab === "offline" ? "active" : ""}`} onClick={() => setTab("offline")} data-testid="ag-tab-offline">Offline Artists</button>
      </div>

      {tab === "online" ? <OnlineRoster /> : <OfflineArtists />}
    </div>
  );
}

function EarningsKpi({ label, value, sub, testId }) {
  return (
    <div style={{ padding: 12, borderRadius: 10, background: "rgba(212,175,55,0.06)", border: "1px solid rgba(212,175,55,0.18)" }} data-testid={testId}>
      <div style={{ fontSize: 11, color: "rgba(240,238,255,0.6)" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: "#F1D17A", marginTop: 2 }}>
        ₹{Number(value || 0).toLocaleString("en-IN")}
      </div>
      {sub && <div style={{ fontSize: 10, color: "rgba(240,238,255,0.5)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
