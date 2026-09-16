import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import api, { formatApiError } from "./api";

const AuthCtx = createContext(null);

/**
 * AuthProvider — httpOnly cookie edition (Iter 51, Security Audit).
 *
 * Previously we stashed the JWT in localStorage as `bt_token` and sent it
 * via the Authorization header. That opened a classic XSS-token-exfiltration
 * hole: any injected script could `localStorage.getItem("bt_token")` and
 * ship the token to an attacker's server.
 *
 * The token now lives ONLY in an httpOnly Secure SameSite=Lax cookie set by
 * the backend on /auth/login, /auth/register and /auth/otp/verify. JavaScript
 * cannot read it — full stop. Auth state is derived by calling /auth/me on
 * mount and after each login/register. The browser attaches the cookie
 * automatically because `withCredentials: true` is set on the axios client.
 *
 * Migration cleanup: on first mount we wipe any leftover `bt_token` from
 * localStorage so returning users don't keep a stale token lying around.
 */
export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // One-time cleanup of the legacy localStorage key. Safe to run every
    // page-load — it's a no-op once the key is gone.
    try { localStorage.removeItem("bt_token"); } catch { /* storage disabled */ }
    // The cookie (if any) flows automatically via withCredentials.
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => { /* 401 → anonymous, normal path */ })
      .finally(() => setLoading(false));
  }, []);

  // Iter 58 (v2) — Removed the aggressive `bt:session-expired` auto-redirect.
  // It was yanking users off the booking page on ANY 401 (including transient
  // ones from background polls). The Protected route in App.js already
  // handles anonymous users at the route level; component-level catch blocks
  // handle transient failures with a toast.

  const login = useCallback(async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const register = useCallback(async (data) => {
    const r = await api.post("/auth/register", data);
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const logout = useCallback(() => {
    // Clears the httpOnly cookie server-side.
    api.post("/auth/logout").catch(() => {});
    setUser(null);
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const r = await api.get("/auth/me");
      setUser(r.data);
    } catch (e) {
      if (typeof console !== "undefined") console.warn("refreshMe failed:", e?.message || e);
    }
  }, []);

  // Memoise the context value so consumers only re-render when auth state
  // actually changes — not on every parent tick.
  const ctxValue = useMemo(
    () => ({ user, loading, login, register, logout, refreshMe, formatApiError }),
    [user, loading, login, register, logout, refreshMe],
  );

  return <AuthCtx.Provider value={ctxValue}>{children}</AuthCtx.Provider>;
};

export const useAuth = () => useContext(AuthCtx);
