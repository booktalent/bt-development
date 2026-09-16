import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { LogIn, UserPlus, X } from "lucide-react";

/**
 * LoginGate — Iter 70
 * -------------------
 * Shared guest-action guardrail. Renders a friendly modal explaining the
 * action requires an account, with clear Sign In / Create Account CTAs.
 *
 * Props:
 *   open       — bool, controls visibility
 *   onClose    — cb to close (backdrop / ✕ / esc)
 *   title      — headline (e.g. "Login to continue booking")
 *   message    — body text (e.g. "You'll need an account to check availability
 *                 on this date. Sign in or create a free account to continue.")
 *   returnTo   — where to bring the user back after auth (default: current pathname + search)
 */
export default function LoginGate({
  open,
  onClose,
  title = "Please sign in to continue",
  message = "This action requires a BookTalent account. Sign in or create a free account to continue — you'll come right back here after.",
  returnTo,
}) {
  const { user } = useAuth();
  const location = useLocation();

  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  // Auto-close if the user is already signed in (edge: modal opened during logout race).
  if (user) return null;

  const back = returnTo || `${location.pathname}${location.search}`;
  const nextParam = encodeURIComponent(back);
  const stop = (e) => e.stopPropagation();

  return (
    <div
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="login-gate-title"
      data-testid="login-gate"
      style={{
        position: "fixed", inset: 0, zIndex: 400,
        background: "rgba(4,6,20,0.72)",
        backdropFilter: "blur(10px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={stop}
        style={{
          width: 460, maxWidth: "100%",
          background: "linear-gradient(180deg, #16172B, #0F0F1B)",
          border: "1px solid rgba(212,175,55,0.35)",
          borderRadius: 20,
          padding: "28px 24px 22px",
          color: "#F0EEFF",
          boxShadow: "0 24px 64px -12px rgba(0,0,0,0.75)",
          position: "relative",
        }}
      >
        <button
          aria-label="Close"
          onClick={onClose}
          data-testid="login-gate-close"
          style={{
            position: "absolute", top: 12, right: 12,
            background: "transparent", border: 0, color: "rgba(240,238,255,0.6)",
            cursor: "pointer", padding: 6,
          }}
        >
          <X size={18} />
        </button>

        <div style={{
          width: 52, height: 52, borderRadius: 16,
          background: "linear-gradient(135deg, #FFE08F, #D4AF37)",
          color: "#1a0f00", display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 14, boxShadow: "0 6px 20px -6px rgba(212,175,55,0.55)",
        }}>
          <LogIn size={22} strokeWidth={2.4} />
        </div>

        <h3
          id="login-gate-title"
          style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: 24, fontWeight: 700, margin: "0 0 8px",
          }}
        >
          {title}
        </h3>

        <p style={{
          fontSize: 14, lineHeight: 1.55, color: "rgba(240,238,255,0.75)", margin: "0 0 20px",
        }}>
          {message}
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <Link
            to={`/login?next=${nextParam}`}
            className="btn btn-gold"
            data-testid="login-gate-signin"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
          >
            <LogIn size={16} /> Sign In
          </Link>
          <Link
            to={`/signup?role=customer&next=${nextParam}`}
            className="btn btn-ghost"
            data-testid="login-gate-signup"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
          >
            <UserPlus size={16} /> Create Free Account
          </Link>
        </div>

        <div style={{
          marginTop: 14, textAlign: "center",
          fontSize: 12, color: "rgba(240,238,255,0.5)",
        }}>
          Takes less than a minute · No credit card required
        </div>
      </div>
    </div>
  );
}

/**
 * useLoginGate — hook helper. Returns `{gate, requireAuth}`.
 *
 *   const { gate, requireAuth } = useLoginGate();
 *   const handleBook = requireAuth(() => actuallyBook(), {
 *     title: "Login to book this date",
 *   });
 *   return (<><button onClick={handleBook}>Book</button>{gate}</>);
 */
export function useLoginGate() {
  const { user } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [context, setContext] = React.useState({});
  const gate = (
    <LoginGate
      open={open}
      onClose={() => setOpen(false)}
      title={context.title}
      message={context.message}
      returnTo={context.returnTo}
    />
  );
  const requireAuth = (fn, opts = {}) => (...args) => {
    if (user) return fn(...args);
    setContext(opts);
    setOpen(true);
    return null;
  };
  return { gate, requireAuth, promptLogin: (opts = {}) => { setContext(opts); setOpen(true); } };
}
