import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

// ────────────────────────────────────────────────────────────────────────────
// Global unhandled-rejection swallower for benign Axios failures.
//
// The dashboards (Admin, Artist, Customer, Agency) fire dozens of `api.get()`
// calls that don't `.catch()` — a stale session, a 404 on a deprecated endpoint,
// or a transient hiccup then bubbles up as an "Uncaught runtime errors"
// overlay in dev mode, which spooks users and hides the real UI.
//
// This one listener catches network-layer rejections (Axios errors from any
// caller), logs them for debugging, and swallows them so the React overlay
// stays out of the way. Non-Axios errors still fall through to the overlay so
// real programmer mistakes remain visible.
//
// Adding a global handler is safer than injecting `.catch(() => {})` in ~50+
// individual call-sites because it's DRY and future-proof: any new fetch
// added later automatically inherits the protection.
// ────────────────────────────────────────────────────────────────────────────
if (typeof window !== "undefined") {
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    // Axios errors always carry either `.isAxiosError` or `.response`
    // (from a response) or `.request` (from a network fail).
    const isAxios =
      reason &&
      (reason.isAxiosError === true ||
        reason.name === "AxiosError" ||
        (typeof reason === "object" && (reason.response || reason.request)));
    if (isAxios) {
      if (typeof console !== "undefined") {
        // eslint-disable-next-line no-console
        console.warn(
          "[api] Unhandled Axios rejection swallowed:",
          reason?.config?.method?.toUpperCase(),
          reason?.config?.url,
          reason?.response?.status,
        );
      }
      event.preventDefault();
    }
  });
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
