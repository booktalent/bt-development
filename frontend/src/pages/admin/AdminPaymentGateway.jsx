/**
 * AdminPaymentGateway — Iter 61
 * Admin Panel → Payment Gateway settings.
 *
 * Nothing about Easebuzz Key / Salt / URL / environment is hardcoded in the
 * source anywhere. This page is the single source of truth — the backend
 * routes and BookingFlow read from `payment_gateway_settings` collection.
 *
 * Backed by:
 *   GET  /api/admin/payment-settings     (super_admin)
 *   PUT  /api/admin/payment-settings     (super_admin)
 */
import React, { useEffect, useState } from "react";
import api, { formatApiError } from "../../lib/api";

const emptyEnv = { key: "", salt: "", base_url: "" };

export default function AdminPaymentGateway({ toast }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    provider: "easebuzz",
    enabled: true,
    environment: "sandbox",
    sandbox: { ...emptyEnv, base_url: "https://testpay.easebuzz.in" },
    live: { ...emptyEnv, base_url: "https://pay.easebuzz.in" },
    success_url: "/booking/payment-return",
    failure_url: "/booking/payment-return",
    webhook_url: "",
  });

  useEffect(() => {
    api.get("/admin/payment-settings")
      .then((r) => setForm((f) => ({ ...f, ...r.data })))
      .catch(() => toast("Could not load payment settings", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const updEnv = (env, k, v) => setForm((f) => ({ ...f, [env]: { ...f[env], [k]: v } }));

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/admin/payment-settings", form);
      setForm((f) => ({ ...f, ...r.data }));
      toast("Payment settings saved", "success");
    } catch (e) {
      toast(formatApiError(e), "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="loading"><div className="spinner" /></div>;

  const activeBlock = form.environment === "live" ? form.live : form.sandbox;
  const activeReady = !!(activeBlock?.key && activeBlock?.salt && activeBlock?.base_url);

  return (
    <div data-testid="admin-payment-gateway">
      <div className="dash-head">
        <div>
          <h1>Payment Gateway</h1>
          <p>
            Configure Easebuzz credentials. Switch between Sandbox and Live without touching code.
          </p>
        </div>
      </div>

      {/* Status strip */}
      <div className="card" style={{ padding: 16, marginBottom: 20, display: "flex", gap: 24, flexWrap: "wrap" }}>
        <StatusPill
          label={form.enabled ? "Gateway Enabled" : "Gateway Disabled"}
          tone={form.enabled ? "success" : "danger"}
          testId="pill-enabled"
        />
        <StatusPill
          label={`Environment: ${form.environment.toUpperCase()}`}
          tone={form.environment === "live" ? "warn" : "info"}
          testId="pill-env"
        />
        <StatusPill
          label={activeReady ? "Credentials Configured" : "Credentials Missing"}
          tone={activeReady ? "success" : "danger"}
          testId="pill-creds"
        />
      </div>

      {/* Master switches */}
      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h3 style={{ marginTop: 0 }}>Master Controls</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <label className="stack">
            <span>Enable Payment Gateway</span>
            <select
              className="input"
              value={form.enabled ? "yes" : "no"}
              onChange={(e) => upd("enabled", e.target.value === "yes")}
              data-testid="input-enabled"
            >
              <option value="yes">Yes — accept payments</option>
              <option value="no">No — block all payments</option>
            </select>
          </label>

          <label className="stack">
            <span>Active Environment</span>
            <select
              className="input"
              value={form.environment}
              onChange={(e) => upd("environment", e.target.value)}
              data-testid="input-environment"
            >
              <option value="sandbox">Sandbox (Test)</option>
              <option value="live">Live (Production)</option>
            </select>
          </label>
        </div>
      </div>

      {/* Sandbox block */}
      <EnvCard
        title="Sandbox Credentials"
        subtitle="Used when Environment = Sandbox. Safe test money only."
        env="sandbox"
        block={form.sandbox}
        onChange={(k, v) => updEnv("sandbox", k, v)}
      />

      {/* Live block */}
      <EnvCard
        title="Live Credentials"
        subtitle="Used when Environment = Live. Real customer money — handle with care."
        env="live"
        block={form.live}
        onChange={(k, v) => updEnv("live", k, v)}
      />

      {/* URLs */}
      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h3 style={{ marginTop: 0 }}>Return URLs</h3>
        <p className="text-muted" style={{ marginTop: 0 }}>
          Where the customer's browser is redirected after Easebuzz finishes. Callbacks (server-to-server)
          always POST to <code>/api/payments/easebuzz/callback/success</code> and <code>/failure</code>.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <label className="stack">
            <span>Success Return Path</span>
            <input
              className="input"
              value={form.success_url}
              onChange={(e) => upd("success_url", e.target.value)}
              placeholder="/booking/payment-return"
              data-testid="input-success-url"
            />
          </label>
          <label className="stack">
            <span>Failure Return Path</span>
            <input
              className="input"
              value={form.failure_url}
              onChange={(e) => upd("failure_url", e.target.value)}
              placeholder="/booking/payment-return"
              data-testid="input-failure-url"
            />
          </label>
          <label className="stack" style={{ gridColumn: "1 / -1" }}>
            <span>Webhook URL (optional override)</span>
            <input
              className="input"
              value={form.webhook_url}
              onChange={(e) => upd("webhook_url", e.target.value)}
              placeholder="Leave blank to use default /api/payments/easebuzz/webhook"
              data-testid="input-webhook-url"
            />
          </label>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
        <button
          className="btn btn-primary"
          onClick={save}
          disabled={saving}
          data-testid="btn-save-payment-settings"
        >
          {saving ? "Saving…" : "Save Payment Settings"}
        </button>
      </div>
    </div>
  );
}

const EnvCard = ({ title, subtitle, env, block, onChange }) => (
  <div className="card" style={{ padding: 20, marginBottom: 20 }} data-testid={`env-card-${env}`}>
    <h3 style={{ marginTop: 0 }}>{title}</h3>
    <p className="text-muted" style={{ marginTop: 0 }}>{subtitle}</p>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <label className="stack">
        <span>Merchant Key</span>
        <input
          className="input"
          value={block?.key || ""}
          onChange={(e) => onChange("key", e.target.value)}
          placeholder="e.g. 1OCWIXWTP"
          data-testid={`input-${env}-key`}
          autoComplete="off"
        />
      </label>
      <label className="stack">
        <span>Salt</span>
        <input
          className="input"
          type="password"
          value={block?.salt || ""}
          onChange={(e) => onChange("salt", e.target.value)}
          placeholder="Never share this"
          data-testid={`input-${env}-salt`}
          autoComplete="off"
        />
      </label>
      <label className="stack" style={{ gridColumn: "1 / -1" }}>
        <span>Base API URL</span>
        <input
          className="input"
          value={block?.base_url || ""}
          onChange={(e) => onChange("base_url", e.target.value)}
          placeholder={env === "sandbox"
            ? "https://testpay.easebuzz.in"
            : "https://pay.easebuzz.in"}
          data-testid={`input-${env}-base-url`}
        />
      </label>
    </div>
  </div>
);

const StatusPill = ({ label, tone, testId }) => {
  const bg = {
    success: "#dcfce7", warn: "#fef3c7", danger: "#fee2e2", info: "#dbeafe",
  }[tone] || "#e5e7eb";
  const fg = {
    success: "#166534", warn: "#92400e", danger: "#991b1b", info: "#1e40af",
  }[tone] || "#374151";
  return (
    <span
      style={{
        padding: "6px 12px", borderRadius: 999, background: bg, color: fg,
        fontSize: 13, fontWeight: 600,
      }}
      data-testid={testId}
    >
      {label}
    </span>
  );
};
