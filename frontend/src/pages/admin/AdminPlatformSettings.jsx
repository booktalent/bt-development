import React, { useEffect, useMemo, useState } from "react";
import api, { formatApiError as fmt } from "../../lib/api";
import { useToast } from "../../lib/toast";

/**
 * Admin → Platform Settings (Sec 5, 33, 42, 43, 63)
 *
 * Single-page tabbed editor for the v2 config singleton. Every save is
 * audit-logged on the backend automatically. UI never calculates anything
 * itself — it just reads /platform-settings/admin, edits, and PATCHes.
 */
export default function AdminPlatformSettings() {
  const toast = useToast();
  const [tab, setTab] = useState("fees");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState(null);
  const [dirty, setDirty] = useState({});
  const [confirmSave, setConfirmSave] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/platform-settings/admin");
      setState(r.data);
      setDirty({});
    } catch (e) { toast(fmt(e), "error"); }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const set = (k, v) => {
    setState((s) => ({ ...s, [k]: v }));
    setDirty((d) => ({ ...d, [k]: true }));
  };

  const changedFields = useMemo(() => Object.keys(dirty), [dirty]);

  const submit = async () => {
    if (!changedFields.length) return;
    const payload = {};
    changedFields.forEach((k) => { payload[k] = state[k]; });
    setBusy(true);
    try {
      await api.patch("/platform-settings/admin", payload);
      toast("Settings saved. Audit log updated.", "success");
      setConfirmSave(false);
      await load();
    } catch (e) { toast(fmt(e), "error"); }
    setBusy(false);
  };

  if (loading || !state) return (
    <div className="pad-24" data-testid="admin-settings-loading">Loading settings…</div>
  );

  const scheduleTotal = (state.payment_schedule || []).reduce(
    (a, s) => a + Number(s.percent || 0), 0,
  );

  return (
    <div className="pad-24" data-testid="admin-platform-settings">
      <div className="flex-between mb-16">
        <h2 className="font-serif fs-24 fw-700">Platform Settings</h2>
        <div className="flex-row gap-8">
          <span className={`fs-13 ${changedFields.length ? "text-gold" : "text-muted"}`}>
            {changedFields.length ? `${changedFields.length} unsaved change(s)` : "All saved"}
          </span>
          <button
            className="btn btn-gold"
            disabled={!changedFields.length || busy}
            onClick={() => setConfirmSave(true)}
            data-testid="settings-save-btn"
          >
            {busy ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      <div className="tab-bar mb-16" data-testid="settings-tabs">
        {[
          ["fees", "Fees & GST"],
          ["schedule", "Payment Schedule"],
          ["payout", "Payout Mode"],
          ["kyc", "KYC Documents"],
          ["company", "Company Info"],
        ].map(([k, label]) => (
          <button key={k}
            className={`tab-btn ${tab === k ? "active" : ""}`}
            onClick={() => setTab(k)}
            data-testid={`settings-tab-${k}`}
          >{label}</button>
        ))}
      </div>

      {tab === "fees" && (
        <div className="card card-pad" data-testid="settings-pane-fees">
          <label className="field-label">Platform Fee % (customer)</label>
          <input type="number" step="0.1" min="0" max="50"
            className="field-input mb-16"
            value={state.platform_fee_percent}
            onChange={(e) => set("platform_fee_percent", parseFloat(e.target.value || 0))}
            data-testid="settings-platform-fee"
          />
          <label className="field-label">GST %</label>
          <input type="number" step="0.1" min="0" max="50"
            className="field-input"
            value={state.gst_percent}
            onChange={(e) => set("gst_percent", parseFloat(e.target.value || 0))}
            data-testid="settings-gst"
          />
          <p className="text-muted fs-12 mt-8">
            Set GST to <b>0</b> to hide it from customer checkout and invoices.
          </p>
        </div>
      )}

      {tab === "schedule" && (
        <div className="card card-pad" data-testid="settings-pane-schedule">
          <p className="text-muted fs-13 mb-12">
            Business goal: collect ≥ 90% before the event. Percents must sum to <b>100</b>. Current total: {" "}
            <b className={Math.abs(scheduleTotal - 100) < 0.01 ? "text-good" : "text-danger"}>{scheduleTotal}%</b>
          </p>
          {(state.payment_schedule || []).map((row, idx) => (
            <div key={idx} className="grid grid-4 gap-8 mb-8 items-center" data-testid={`schedule-row-${idx}`}>
              <input className="field-input" value={row.label}
                onChange={(e) => {
                  const arr = [...state.payment_schedule];
                  arr[idx] = { ...row, label: e.target.value };
                  set("payment_schedule", arr);
                }}
              />
              <input className="field-input" type="number" step="1" value={row.percent}
                onChange={(e) => {
                  const arr = [...state.payment_schedule];
                  arr[idx] = { ...row, percent: parseFloat(e.target.value || 0) };
                  set("payment_schedule", arr);
                }}
              />
              <input className="field-input" type="number" placeholder="offset days (blank=at booking)"
                value={row.offset_days ?? ""}
                onChange={(e) => {
                  const arr = [...state.payment_schedule];
                  arr[idx] = { ...row, offset_days: e.target.value === "" ? null : parseInt(e.target.value) };
                  set("payment_schedule", arr);
                }}
              />
              <label className="fs-13">
                <input type="checkbox" checked={row.mandatory !== false}
                  onChange={(e) => {
                    const arr = [...state.payment_schedule];
                    arr[idx] = { ...row, mandatory: e.target.checked };
                    set("payment_schedule", arr);
                  }} /> Required
              </label>
            </div>
          ))}
        </div>
      )}

      {tab === "payout" && (
        <div className="card card-pad" data-testid="settings-pane-payout">
          <label className="field-label">Payout Mode</label>
          <select className="field-input mb-16"
            value={state.payout_mode}
            onChange={(e) => set("payout_mode", e.target.value)}
            data-testid="settings-payout-mode"
          >
            <option value="manual">Manual (current)</option>
            <option value="easebuzz">Easebuzz Automated</option>
          </select>
          <label className="fs-13 mb-8" style={{ display: "block" }}>
            <input type="checkbox"
              checked={!!state.enable_automated_payout}
              onChange={(e) => set("enable_automated_payout", e.target.checked)}
              data-testid="settings-payout-flag"
            /> Enable Automated Artist Payout (feature flag)
          </label>
          <div className="notice-warn fs-12 mt-8">
            <b>⚠ Live payout impact:</b> Switching to Easebuzz will start routing every
            approved settlement through the Easebuzz Payouts API immediately. Only turn on
            after your Easebuzz Payout credentials are configured. This flag is OFF by default.
          </div>
        </div>
      )}

      {tab === "kyc" && (
        <div className="card card-pad" data-testid="settings-pane-kyc">
          <p className="text-muted fs-13 mb-12">
            Documents artists must upload during KYC. Uncheck "Required" to make a document optional.
          </p>
          {(state.required_kyc_docs || []).map((row, idx) => (
            <div key={idx} className="grid grid-3 gap-8 mb-8 items-center" data-testid={`kyc-doc-row-${idx}`}>
              <input className="field-input" value={row.code}
                onChange={(e) => {
                  const arr = [...state.required_kyc_docs];
                  arr[idx] = { ...row, code: e.target.value };
                  set("required_kyc_docs", arr);
                }}
              />
              <input className="field-input" value={row.label}
                onChange={(e) => {
                  const arr = [...state.required_kyc_docs];
                  arr[idx] = { ...row, label: e.target.value };
                  set("required_kyc_docs", arr);
                }}
              />
              <label className="fs-13">
                <input type="checkbox" checked={!!row.required}
                  onChange={(e) => {
                    const arr = [...state.required_kyc_docs];
                    arr[idx] = { ...row, required: e.target.checked };
                    set("required_kyc_docs", arr);
                  }} /> Required
              </label>
            </div>
          ))}
        </div>
      )}

      {tab === "company" && (
        <div className="card card-pad" data-testid="settings-pane-company">
          {["legal_name", "gstin", "pan", "address", "state", "support_email", "support_phone"].map((k) => (
            <div key={k} className="mb-12">
              <label className="field-label">{k.replace(/_/g, " ").toUpperCase()}</label>
              <input className="field-input"
                value={(state.company_info || {})[k] || ""}
                onChange={(e) => set("company_info", { ...(state.company_info || {}), [k]: e.target.value })}
                data-testid={`settings-company-${k}`}
              />
            </div>
          ))}
        </div>
      )}

      {confirmSave && (
        <div className="modal-backdrop" data-testid="settings-confirm-modal" onClick={() => setConfirmSave(false)}>
          <div className="modal card card-pad" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
            <h3 className="font-serif fs-20 fw-700 mb-8">Confirm changes</h3>
            <p className="text-muted fs-13 mb-16">
              You're about to change <b>{changedFields.length}</b> setting(s). Every field is audit-logged
              with your email + IP. This affects every future booking.
            </p>
            <ul className="fs-13 mb-16" style={{ paddingLeft: 20 }}>
              {changedFields.map((k) => <li key={k}><code>{k}</code></li>)}
            </ul>
            <div className="flex-row gap-8" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={() => setConfirmSave(false)} data-testid="settings-cancel-btn">Cancel</button>
              <button className="btn btn-gold" disabled={busy} onClick={submit} data-testid="settings-confirm-btn">
                {busy ? "Saving…" : "Confirm & Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
