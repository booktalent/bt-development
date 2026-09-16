import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PartyPopper, Mic2, Building2 } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import api, { formatApiError as fmtErr } from "../lib/api";

// Iter 66 — Corporate role temporarily hidden from public signup. Kept in
// the backend (existing Corporate accounts + admin panel) so we can re-enable
// it later without a migration. Re-add the {value:'corporate', ...} entry to
// bring the option back on the signup screen.
const ROLES = [
  { value: "customer", Icon: PartyPopper, name: "Customer",
    desc: "Book verified artists for your next event",
    popular: true },
  { value: "artist",   Icon: Mic2,        name: "Artist",
    desc: "List yourself and get discovered by planners" },
  { value: "agency",   Icon: Building2,   name: "Agency",
    desc: "Manage a roster of artists in one dashboard" },
];

/** Password field with a "show/hide" eye toggle. */
function PasswordField({ value, onChange, placeholder, required, testid, autoComplete }) {
  const [show, setShow] = React.useState(false);
  return (
    <div className="pwd-wrap">
      <input
        className="field-input pwd-input"
        type={show ? "text" : "password"}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        autoComplete={autoComplete || "current-password"}
        data-testid={testid}
      />
      <button
        type="button"
        className="pwd-toggle"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        data-testid={`${testid}-toggle`}
        tabIndex={-1}
      >
        {show ? "🙈" : "👁"}
      </button>
    </div>
  );
}

export default function Auth({ mode = "signin" }) {
  const [params] = useSearchParams();
  // Iter 66 — silently coerce legacy `?role=corporate` links to the Customer
  // flow now that Corporate signup is hidden. Any bookmarks / old marketing
  // links still work, they just land on the Customer signup instead of 404.
  const rawRole = params.get("role") || "customer";
  const initialRole = rawRole === "corporate" ? "customer" : rawRole;
  const { login, register, formatApiError, user: currentUser } = useAuth();
  const toast = useToast();
  const nav = useNavigate();

  const [tab, setTab] = useState(mode === "signin" ? "signin" : "signup");
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    email: "", password: "", confirm: "",
    first_name: "", last_name: "", phone: "",
    role: initialRole, category: "", city: "", company_name: "",
  });
  const [emailOtp, setEmailOtp] = useState("");
  const [mockOtpHint, setMockOtpHint] = useState("");
  const [emailVerified, setEmailVerified] = useState(false);
  const [emailProviderEnabled, setEmailProviderEnabled] = useState(false);
  // Iter 66 — Category catalog is loaded from the master list so it stays
  // in sync with what admins publish (no hard-coded dropdown drift).
  const [categoryList, setCategoryList] = useState([]);
  // Iter 67 — Same for cities.
  const [cityList, setCityList] = useState([]);
  // Iter 66 — "Request a new category" flow. When the artist picks the
  // special "__request__" option we surface an inline form; the payload
  // rides along with /auth/register so the request is saved atomically.
  const [showCatRequest, setShowCatRequest] = useState(false);
  const [catRequest, setCatRequest] = useState({ name: "", description: "", example_artists: "", portfolio_link: "" });
  // Iter 67 — "Request a new city" flow (mirror of category).
  const [showCityRequest, setShowCityRequest] = useState(false);
  const [cityRequest, setCityRequest] = useState({ name: "", state: "", country: "India", description: "", reason: "" });

  useEffect(() => {
    api.get("/auth/config").then((r) => setEmailProviderEnabled(r.data?.email_provider_enabled));
    // Pull live master categories so signup reflects what admins have
    // published — no more hard-coded options.
    api.get("/catalog/categories").then((r) => setCategoryList(r.data || [])).catch(() => setCategoryList([]));
    api.get("/catalog/cities").then((r) => setCityList(r.data || [])).catch(() => setCityList([]));
  }, []);

  // Iter 74 — If a signed-in user lands on /login or /signup (e.g. browser
  // Back after logging in, or a stale bookmark), route them straight to
  // their dashboard / the `?next=` param instead of showing the sign-in
  // form. This is done in an effect (not during render) so it survives a
  // successful auth call and doesn't fight the `nav(resolveDest(u))` line.
  useEffect(() => {
    if (!currentUser) return;
    const dest = resolveDest(currentUser);
    nav(dest, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  // Determine the post-login destination: (1) `?returnTo=` (session-expiry
  // bounce from api.js interceptor) or `?next=` param wins,
  // (2) sessionStorage `bt_post_login_redirect` (set by cart flow), else
  // (3) fall back to the role-based dashboard.
  const resolveDest = (u) => {
    const returnTo = params.get("returnTo");
    if (returnTo && returnTo.startsWith("/") && !returnTo.startsWith("//")) return returnTo;
    const nextParam = params.get("next");
    if (nextParam) return nextParam;
    try {
      const stashed = sessionStorage.getItem("bt_post_login_redirect");
      if (stashed) { sessionStorage.removeItem("bt_post_login_redirect"); return stashed; }
    } catch { /* ignore */ }
    return u.role === "admin" ? "/admin" : u.role === "artist" ? "/artist" : u.role === "agency" ? "/agency" : u.role === "corporate" ? "/corporate" : "/customer";
  };

  const doSignIn = async (e) => {
    e?.preventDefault();
    setBusy(true);
    try {
      const u = await login(form.email, form.password);
      toast(`Welcome back, ${u.first_name}!`);
      nav(resolveDest(u));
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const doSignUp = async () => {
    if (form.password !== form.confirm) { toast("Passwords do not match", "error"); return; }
    if (form.password.length < 6) { toast("Password too short (min 6)", "error"); return; }
    if (!emailVerified) { toast("Please verify your email first", "error"); return; }
    setBusy(true);
    try {
      const payload = {
        email: form.email, password: form.password,
        first_name: form.first_name, last_name: form.last_name,
        phone: form.phone, role: form.role,
        category: form.category, city: form.city,
        company_name: form.company_name,
      };
      // Iter 66 — Include the requested-category payload so the /auth/register
      // handler can atomically save the request row + flag the artist profile
      // as pending admin approval. See routes/category_requests.py for the
      // decision workflow that follows.
      if (form.role === "artist" && showCatRequest && catRequest.name.trim()) {
        payload.category_request = {
          name: catRequest.name.trim(),
          description: catRequest.description.trim(),
          example_artists: catRequest.example_artists.trim(),
          portfolio_link: catRequest.portfolio_link.trim(),
        };
        // Use the requested name as the placeholder on the profile so the
        // artist immediately sees what they typed. Server also does this.
        payload.category = catRequest.name.trim();
      }
      // Iter 67 — Same mechanism for city.
      if (form.role === "artist" && showCityRequest && cityRequest.name.trim()) {
        payload.city_request = {
          name: cityRequest.name.trim(),
          state: cityRequest.state.trim(),
          country: cityRequest.country.trim() || "India",
          description: cityRequest.description.trim(),
          reason: cityRequest.reason.trim(),
        };
        payload.city = cityRequest.name.trim();
      }
      const u = await register(payload);
      // Iter 63 — If ?ref=CODE is in the URL and role=artist, auto-join the
      // referring agency (server-side rule: no accept step needed).
      const ref = new URLSearchParams(window.location.search).get("ref");
      if (ref && u.role === "artist") {
        try {
          await api.post("/auth/roster/consume-ref", { referral_code: ref });
          toast("You've been added to the agency roster.", "success");
        } catch (_e) { /* non-fatal */ }
      }
      toast(`Welcome to BookTalent, ${u.first_name}!`);
      nav(resolveDest(u));
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const sendEmailOtp = async () => {
    if (!form.email) { toast("Enter your email first", "error"); return; }
    setBusy(true);
    try {
      const r = await api.post("/auth/email/send", { email: form.email, name: form.first_name });
      if (r.data?.test_otp) setMockOtpHint(r.data.test_otp);
      toast(emailProviderEnabled ? "Code sent — check your inbox" : "Code sent", "success");
      setStep(3);
    } catch (e) { toast(fmtErr(e), "error"); }
    setBusy(false);
  };

  const verifyEmailOtp = async () => {
    setBusy(true);
    try {
      await api.post("/auth/email/verify", { email: form.email, otp: emailOtp });
      setEmailVerified(true);
      toast("Email verified ✓");
      setStep(4);
    } catch (e) { toast(fmtErr(e), "error"); }
    setBusy(false);
  };

  return (
    <div className="auth-wrap" data-testid="auth-page">
      <div className="auth-mobile-topbar" data-testid="auth-mobile-topbar">
        <Link to="/" className="auth-mobile-back" data-testid="auth-mobile-home">
          ← Home
        </Link>
        <Link to="/" className="logo auth-mobile-logo" data-testid="auth-mobile-logo">
          <div className="logo-mark">B</div>
          <span>Book<span className="gold">Talent</span></span>
        </Link>
      </div>
      <div className="auth-left">
        <Link to="/" className="logo" data-testid="auth-logo">
          <div className="logo-mark">B</div>
          <span>Book<span className="gold">Talent</span></span>
        </Link>
        <div>
          <div className="hero-tag" style={{ marginBottom: 18 }}>India's #1 Talent Marketplace</div>
          <h1 style={{ fontFamily: "Cormorant Garamond, serif", fontSize: 52, fontWeight: 700, lineHeight: 1.1, marginBottom: 18 }}>
            Book India's<br/>
            <span style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Finest</span> Talent
          </h1>
          <p style={{ color: "var(--white-muted)", fontSize: 15, lineHeight: 1.6, marginBottom: 30 }}>
            Join 68,000+ event planners and artists on the most premium talent booking platform.
          </p>
          <div style={{ display: "flex", gap: 30 }}>
            <div><div className="hero-stat-num">5,200+</div><div className="hero-stat-label">Artists</div></div>
            <div><div className="hero-stat-num">48K+</div><div className="hero-stat-label">Events</div></div>
            <div><div className="hero-stat-num">32</div><div className="hero-stat-label">Cities</div></div>
          </div>
        </div>
        <div className="card card-pad" style={{ maxWidth: 340 }}>
          <div className="fs-13 mb-12" style={{ lineHeight: 1.6 }}>
            "BookTalent transformed how we book artists for our events. Transparent, fast and the contract system gives us complete peace of mind."
          </div>
          <div className="flex items-center gap-10">
            <div className="avatar" style={{ background: "linear-gradient(135deg, var(--gold), var(--purple))" }}>RK</div>
            <div>
              <div className="fw-600 fs-13">Rajesh Khanna</div>
              <div className="text-muted fs-11">Wedding Planner, Mumbai</div>
            </div>
            <span style={{ color: "var(--gold)", marginLeft: "auto" }}>★★★★★</span>
          </div>
        </div>
      </div>

      <div className="auth-right">
        <div className="auth-tabs" data-testid="auth-tabs">
          <button className={`auth-tab ${tab === "signin" ? "active" : ""}`} onClick={() => setTab("signin")} data-testid="tab-signin">Sign In</button>
          <button className={`auth-tab ${tab === "signup" ? "active" : ""}`} onClick={() => { setTab("signup"); setStep(1); }} data-testid="tab-signup">Create Account</button>
        </div>

        {tab === "signin" ? (
          <form onSubmit={doSignIn} data-testid="signin-form">
            <div className="auth-title">Welcome <span className="gold-grad" style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Back</span></div>
            <div className="auth-sub">Sign in to manage your bookings and events.</div>
            <div className="field">
              <div className="field-label">Email</div>
              <input className="field-input" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder="you@example.com" required data-testid="signin-email" />
            </div>
            <div className="field">
              <div className="field-label">Password</div>
              <PasswordField
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                placeholder="••••••••"
                required
                testid="signin-password"
                autoComplete="current-password"
              />
            </div>
            <button type="submit" className="btn btn-gold btn-block" disabled={busy} data-testid="signin-submit">
              {busy ? "Signing in…" : "Sign In →"}
            </button>
            <div className="mt-12" style={{ textAlign: "center" }}>
              <Link
                to="/forgot-password"
                className="text-muted fs-13"
                style={{ textDecoration: "underline", opacity: 0.75 }}
                data-testid="login-forgot-password-link"
              >
                Forgot your password?
              </Link>
            </div>
          </form>
        ) : (
          <div data-testid="signup-form">
            {step === 1 && (
              <>
                <div className="auth-title">I am <span className="gold-grad" style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>a…</span></div>
                <div className="auth-sub">Pick the role that fits — you can always add more later.</div>
                <div className="role-grid" role="radiogroup" aria-label="Choose your role">
                  {ROLES.map((r) => {
                    const Icon = r.Icon;
                    const isSelected = form.role === r.value;
                    return (
                      <button
                        type="button"
                        key={r.value}
                        role="radio"
                        aria-checked={isSelected}
                        className={`role-opt ${isSelected ? "selected" : ""}`}
                        onClick={() => set("role", r.value)}
                        data-testid={`role-${r.value}`}
                      >
                        {r.popular && !isSelected && (
                          <span className="role-pill">Popular</span>
                        )}
                        <span className="role-check" aria-hidden="true">✓</span>
                        <span className="role-ico">
                          <Icon size={22} strokeWidth={2.2} />
                        </span>
                        <div className="role-name">{r.name}</div>
                        <div className="role-desc">{r.desc}</div>
                      </button>
                    );
                  })}
                </div>
                <button className="btn btn-gold btn-block" onClick={() => setStep(2)} data-testid="signup-next-1">Continue →</button>
              </>
            )}
            {step === 2 && (
              <>
                <div className="auth-title">Your <span className="gold-grad" style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Details</span></div>
                <div className="auth-sub">Fill in your information to create your account.</div>
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">First Name</div>
                    <input className="field-input" value={form.first_name} onChange={(e) => set("first_name", e.target.value)} data-testid="signup-first-name" />
                  </div>
                  <div className="field">
                    <div className="field-label">Last Name</div>
                    <input className="field-input" value={form.last_name} onChange={(e) => set("last_name", e.target.value)} data-testid="signup-last-name" />
                  </div>
                </div>
                <div className="field">
                  <div className="field-label">Email</div>
                  <input className="field-input" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} data-testid="signup-email" />
                </div>
                <div className="field">
                  <div className="field-label">Mobile</div>
                  <input className="field-input" value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91 98765 43210" data-testid="signup-phone" />
                </div>
                {form.role === "artist" && (
                  <>
                    <div className="field">
                      <div className="field-label">Artist Category</div>
                      <select
                        className="field-input"
                        value={showCatRequest ? "__request__" : form.category}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "__request__") {
                            setShowCatRequest(true);
                            set("category", "");
                          } else {
                            setShowCatRequest(false);
                            set("category", v);
                          }
                        }}
                        data-testid="signup-category"
                      >
                        <option value="">Select your category…</option>
                        {categoryList.map((c) => (
                          <option key={c.slug} value={c.name}>{c.icon ? `${c.icon} ` : ""}{c.name}</option>
                        ))}
                        <option value="__request__">✨ Can't find your category? Request a new one</option>
                      </select>
                    </div>

                    {showCatRequest && (
                      <div
                        style={{
                          padding: 16, borderRadius: 12,
                          background: "rgba(212,175,55,0.06)",
                          border: "1px solid rgba(212,175,55,0.25)",
                          marginBottom: 12,
                        }}
                        data-testid="cat-request-block"
                      >
                        <div style={{ fontWeight: 600, marginBottom: 6, color: "var(--gold-light)" }}>
                          Request a New Category
                        </div>
                        <div className="text-muted fs-12" style={{ marginBottom: 10 }}>
                          We'll create your account with this as a placeholder. Once our team approves it (usually within 24 hrs), your listing goes live — no need to re-enter anything.
                        </div>
                        <div className="field">
                          <div className="field-label">Requested Category Name *</div>
                          <input
                            className="field-input"
                            value={catRequest.name}
                            onChange={(e) => setCatRequest({ ...catRequest, name: e.target.value })}
                            placeholder="e.g. Sufi Qawwal, Ghazal Trio, Sitar Soloist…"
                            data-testid="cat-request-name"
                          />
                        </div>
                        <div className="field">
                          <div className="field-label">Short Description *</div>
                          <textarea
                            className="field-input"
                            rows={3}
                            value={catRequest.description}
                            onChange={(e) => setCatRequest({ ...catRequest, description: e.target.value })}
                            placeholder="Describe your art form, typical event, instruments / troupe size, etc."
                            data-testid="cat-request-desc"
                          />
                        </div>
                        <div className="field">
                          <div className="field-label">Similar / Reference Artists (optional)</div>
                          <input
                            className="field-input"
                            value={catRequest.example_artists}
                            onChange={(e) => setCatRequest({ ...catRequest, example_artists: e.target.value })}
                            placeholder="Any well-known artists we can compare to"
                            data-testid="cat-request-examples"
                          />
                        </div>
                        <div className="field">
                          <div className="field-label">Portfolio / Sample Link (optional)</div>
                          <input
                            className="field-input"
                            value={catRequest.portfolio_link}
                            onChange={(e) => setCatRequest({ ...catRequest, portfolio_link: e.target.value })}
                            placeholder="YouTube, Instagram, website…"
                            data-testid="cat-request-link"
                          />
                        </div>
                      </div>
                    )}

                    <div className="field">
                      <div className="field-label">Primary City</div>
                      <select
                        className="field-input"
                        value={showCityRequest ? "__request__" : form.city}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "__request__") {
                            setShowCityRequest(true);
                            set("city", "");
                          } else {
                            setShowCityRequest(false);
                            set("city", v);
                          }
                        }}
                        data-testid="signup-city"
                      >
                        <option value="">Select city…</option>
                        {cityList.map((c) => (
                          <option key={c.slug} value={c.name}>{c.name}</option>
                        ))}
                        <option value="__request__">📍 Can't find your city? Request a new one</option>
                      </select>
                    </div>

                    {showCityRequest && (
                      <div
                        style={{
                          padding: 16, borderRadius: 12,
                          background: "rgba(109,40,217,0.10)",
                          border: "1px solid rgba(109,40,217,0.35)",
                          marginBottom: 12,
                        }}
                        data-testid="city-request-block"
                      >
                        <div style={{ fontWeight: 600, marginBottom: 6, color: "#c4b5fd" }}>
                          Request a New City
                        </div>
                        <div className="text-muted fs-12" style={{ marginBottom: 10 }}>
                          Same idea — we'll create your account with this as a placeholder while admin reviews (usually within 24 hrs).
                        </div>
                        <div className="field-row">
                          <div className="field">
                            <div className="field-label">City *</div>
                            <input
                              className="field-input"
                              value={cityRequest.name}
                              onChange={(e) => setCityRequest({ ...cityRequest, name: e.target.value })}
                              placeholder="e.g. Coimbatore, Guwahati, Panaji…"
                              data-testid="city-request-name"
                            />
                          </div>
                          <div className="field">
                            <div className="field-label">State</div>
                            <input
                              className="field-input"
                              value={cityRequest.state}
                              onChange={(e) => setCityRequest({ ...cityRequest, state: e.target.value })}
                              placeholder="e.g. Tamil Nadu"
                              data-testid="city-request-state"
                            />
                          </div>
                        </div>
                        <div className="field">
                          <div className="field-label">Why this city (optional)</div>
                          <textarea
                            className="field-input"
                            rows={2}
                            value={cityRequest.reason}
                            onChange={(e) => setCityRequest({ ...cityRequest, reason: e.target.value })}
                            placeholder="Local venues, growing event scene, willing to travel from here…"
                            data-testid="city-request-reason"
                          />
                        </div>
                      </div>
                    )}
                  </>
                )}
                {form.role === "agency" && (
                  <div className="field">
                    <div className="field-label">Agency Name</div>
                    <input className="field-input" value={form.company_name} onChange={(e) => set("company_name", e.target.value)} data-testid="signup-company" />
                  </div>
                )}
                <div className="field">
                  <div className="field-label">Create Password</div>
                  <PasswordField
                    value={form.password}
                    onChange={(e) => set("password", e.target.value)}
                    placeholder="Min 6 chars"
                    testid="signup-password"
                    autoComplete="new-password"
                  />
                </div>
                <div className="field">
                  <div className="field-label">Confirm Password</div>
                  <PasswordField
                    value={form.confirm}
                    onChange={(e) => set("confirm", e.target.value)}
                    placeholder="••••••••"
                    testid="signup-confirm"
                    autoComplete="new-password"
                  />
                </div>
                <div className="flex gap-12">
                  <button className="btn btn-ghost" onClick={() => setStep(1)} data-testid="signup-back-1">← Back</button>
                  <button
                    className="btn btn-gold" style={{ flex: 1 }}
                    onClick={() => {
                      if (!form.first_name || !form.email || !form.password) { toast("Please fill all fields", "error"); return; }
                      if (form.password !== form.confirm) { toast("Passwords do not match", "error"); return; }
                      if (form.password.length < 6) { toast("Password too short (min 6)", "error"); return; }
                      // Iter 66 — require category request details when the
                      // artist picked "Request a new one" so we don't ship an
                      // empty request row to the admin queue.
                      if (form.role === "artist" && showCatRequest) {
                        if (!catRequest.name.trim() || !catRequest.description.trim()) {
                          toast("Please fill the requested category name and description.", "error");
                          return;
                        }
                      } else if (form.role === "artist" && !form.category) {
                        toast("Please select or request an artist category.", "error");
                        return;
                      }
                      // Iter 67 — Same for city request.
                      if (form.role === "artist" && showCityRequest && !cityRequest.name.trim()) {
                        toast("Please enter the requested city name.", "error");
                        return;
                      }
                      sendEmailOtp();
                    }}
                    disabled={busy} data-testid="signup-send-otp"
                  >
                    {busy ? "Sending…" : "Continue → Verify Email"}
                  </button>
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <div className="auth-title">Verify your <span className="gold-grad" style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>Email</span></div>
                <div className="auth-sub">
                  We sent a 6-digit code to <b style={{ color: "var(--gold-light)" }}>{form.email}</b>. Check your inbox (and spam folder).
                </div>
                <div className="field">
                  <div className="field-label">Verification Code</div>
                  <input
                    className="field-input font-mono" style={{ fontSize: 22, letterSpacing: 8, textAlign: "center" }}
                    value={emailOtp} maxLength={6}
                    onChange={(e) => setEmailOtp(e.target.value.replace(/\D/g, ""))}
                    placeholder="------" data-testid="signup-email-otp"
                  />
                </div>
                <div className="flex gap-12">
                  <button className="btn btn-ghost" onClick={() => setStep(2)} data-testid="signup-back-otp">← Back</button>
                  <button className="btn btn-gold" style={{ flex: 1 }} onClick={verifyEmailOtp} disabled={busy || emailOtp.length !== 6} data-testid="signup-verify-otp">
                    {busy ? "Verifying…" : "Verify & Continue →"}
                  </button>
                </div>
                <button
                  className="btn btn-ghost btn-sm mt-12" style={{ width: "100%" }}
                  onClick={sendEmailOtp} disabled={busy} data-testid="signup-resend-otp"
                >Resend Code</button>
              </>
            )}

            {step === 4 && (
              <>
                <div className="auth-title">Almost <span className="gold-grad" style={{ background: "linear-gradient(135deg, var(--gold-light), var(--gold))", WebkitBackgroundClip: "text", color: "transparent" }}>there!</span></div>
                <div className="auth-sub">Email verified ✓ — click below to finish creating your account.</div>
                <div className="card card-pad mb-16" style={{ background: "rgba(16,185,129,0.06)", borderColor: "var(--green-border)" }}>
                  <div className="text-green fs-13 mb-8">✓ Email Verified</div>
                  <div className="fs-14 fw-600">{form.email}</div>
                  <div className="text-muted fs-12 mt-4">Role: {form.role} · {form.first_name} {form.last_name}</div>
                </div>
                <div className="flex gap-12">
                  <button className="btn btn-ghost" onClick={() => setStep(3)} data-testid="signup-back-final">← Back</button>
                  <button className="btn btn-gold" style={{ flex: 1 }} onClick={doSignUp} disabled={busy} data-testid="signup-submit">
                    {busy ? "Creating…" : "Create My Account ✨"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
