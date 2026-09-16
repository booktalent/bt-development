import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { formatApiError as fmtErr } from "../lib/api";
import { useToast } from "../lib/toast";

/**
 * Two-step password reset:
 *   1. Enter email — backend emails both a reset link (magic token) and a 6-digit OTP.
 *   2. Enter OTP + new password (or land here from the emailed link, which
 *      pre-fills the token and skips the OTP step).
 *
 * Both paths hit /api/auth/reset-password.
 */
export default function ForgotPassword() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const toast = useToast();

  // Detect the "landed from email link" case up-front.
  const initialToken = params.get("token") || "";
  const initialEmail = params.get("email") || "";
  const cameFromLink = Boolean(initialToken && initialEmail);

  const [step, setStep] = useState(cameFromLink ? 2 : 1);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState(initialEmail);
  const [otp, setOtp] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (!cooldown) return;
    const t = setInterval(() => setCooldown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const sendCode = async () => {
    if (!email.trim()) { toast("Enter your email first", "error"); return; }
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { email: email.trim().toLowerCase() });
      toast("If that email is registered, we've sent a reset code and link.", "success");
      setStep(2);
      setCooldown(60);
    } catch (e) { toast(fmtErr(e), "error"); }
    setBusy(false);
  };

  const submitReset = async () => {
    if (!pw || pw.length < 6) { toast("Password must be at least 6 characters", "error"); return; }
    if (pw !== pw2) { toast("Passwords do not match", "error"); return; }
    if (!cameFromLink && otp.length !== 6) { toast("Enter the 6-digit code from your email", "error"); return; }

    setBusy(true);
    try {
      const body = { email: email.trim().toLowerCase(), new_password: pw };
      if (cameFromLink) body.token = initialToken;
      else body.otp = otp;
      await api.post("/auth/reset-password", body);
      toast("Password reset! Sign in with your new password.", "success");
      nav("/login");
    } catch (e) { toast(fmtErr(e), "error"); }
    setBusy(false);
  };

  const title = useMemo(() => (step === 1 ? "Forgot your password?" : "Set a new password"), [step]);
  const sub = useMemo(() =>
    step === 1
      ? "Enter the email on your BookTalent account. We'll send you a 6-digit code and a reset link."
      : cameFromLink
        ? "Choose a strong new password. The reset link stays valid for 10 minutes."
        : "Enter the code from your inbox along with your new password.",
    [step, cameFromLink]);

  return (
    <div className="auth-wrap" data-testid="forgot-password-page">
      <div className="auth-mobile-topbar" data-testid="auth-mobile-topbar">
        <Link to="/login" className="auth-mobile-back" data-testid="forgot-back-to-login">
          ← Sign In
        </Link>
        <Link to="/" className="logo auth-mobile-logo">
          <div className="logo-mark">B</div>
          <span>Book<span className="gold">Talent</span></span>
        </Link>
      </div>

      <div className="auth-left">
        <Link to="/" className="logo">
          <div className="logo-mark">B</div>
          <span>Book<span className="gold">Talent</span></span>
        </Link>
        <div>
          <div className="hero-tag" style={{ marginBottom: 18 }}>Secure account recovery</div>
          <h1 style={{ fontFamily: "Cormorant Garamond, serif", fontSize: 52, fontWeight: 700, lineHeight: 1.1, marginBottom: 18 }}>
            Reset your<br/>
            <span style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Password</span>
          </h1>
          <p style={{ color: "var(--white-muted)", fontSize: 15, lineHeight: 1.6, marginBottom: 30 }}>
            We'll send a verification code and a magic reset link to the email on file. Use either to set a new password.
          </p>
        </div>
      </div>

      <div className="auth-right">
        <div className="auth-tabs" data-testid="forgot-tabs">
          <Link to="/login" className="auth-tab" data-testid="forgot-link-signin">Sign In</Link>
          <Link to="/signup" className="auth-tab" data-testid="forgot-link-signup">Create Account</Link>
        </div>

        <div className="auth-title">{title}</div>
        <div className="auth-sub">{sub}</div>

        {step === 1 && (
          <>
            <div className="field">
              <div className="field-label">Email</div>
              <input
                className="field-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                data-testid="forgot-email-input"
              />
            </div>
            <button
              className="btn btn-gold btn-block"
              onClick={sendCode}
              disabled={busy || !email.trim()}
              data-testid="forgot-send-code-btn"
            >
              {busy ? "Sending…" : "Send Reset Code →"}
            </button>
            <Link to="/login" className="btn btn-ghost btn-block mt-12" data-testid="forgot-back-signin-btn" style={{ textAlign: "center", display: "block" }}>
              ← Back to Sign In
            </Link>
          </>
        )}

        {step === 2 && (
          <>
            {!cameFromLink && (
              <>
                <div className="field">
                  <div className="field-label">Email</div>
                  <input
                    className="field-input"
                    type="email"
                    value={email}
                    disabled
                    data-testid="forgot-email-readonly"
                  />
                </div>
                <div className="field">
                  <div className="field-label">6-digit code</div>
                  <input
                    className="field-input font-mono"
                    style={{ fontSize: 22, letterSpacing: 8, textAlign: "center" }}
                    value={otp}
                    maxLength={6}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                    placeholder="------"
                    data-testid="forgot-otp-input"
                  />
                </div>
              </>
            )}
            <div className="field">
              <div className="field-label">New password</div>
              <div className="pwd-wrap">
                <input
                  className="field-input pwd-input"
                  type={showPw ? "text" : "password"}
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  placeholder="At least 6 characters"
                  required
                  autoComplete="new-password"
                  data-testid="forgot-newpassword-input"
                />
                <button
                  type="button"
                  className="pwd-toggle"
                  onClick={() => setShowPw((s) => !s)}
                  aria-label={showPw ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showPw ? "🙈" : "👁"}
                </button>
              </div>
            </div>
            <div className="field">
              <div className="field-label">Confirm new password</div>
              <input
                className="field-input"
                type={showPw ? "text" : "password"}
                value={pw2}
                onChange={(e) => setPw2(e.target.value)}
                placeholder="Re-type your new password"
                required
                autoComplete="new-password"
                data-testid="forgot-confirmpassword-input"
              />
            </div>
            <button
              className="btn btn-gold btn-block"
              onClick={submitReset}
              disabled={busy}
              data-testid="forgot-submit-btn"
            >
              {busy ? "Resetting…" : "Reset Password →"}
            </button>
            {!cameFromLink && (
              <button
                className="btn btn-ghost btn-block mt-12"
                onClick={sendCode}
                disabled={busy || cooldown > 0}
                data-testid="forgot-resend-btn"
              >
                {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
              </button>
            )}
            <Link to="/login" className="btn btn-ghost btn-block mt-12" data-testid="forgot-back-signin-btn-2" style={{ textAlign: "center", display: "block" }}>
              ← Back to Sign In
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
