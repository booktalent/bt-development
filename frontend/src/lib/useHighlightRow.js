import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Iter 65 — Auto-scroll + gold flash for notification-driven navigation.
 *
 * Reads `?highlight=<id>` (or a custom param) from the URL, waits for the
 * element with `data-testid="{prefix}-{id}"` to appear in the DOM, scrolls
 * it into view smoothly, then adds `.row-flash-gold` for a soft gold pulse.
 *
 * Usage:
 *   useHighlightRow({ prefix: "booking-row" });   // /page?highlight=abc → booking-row-abc
 *   useHighlightRow({ prefix: "payment-row", param: "highlight" });
 *
 * The hook re-runs whenever the URL, prefix, or `enabled` flag change and
 * whenever `dataKey` changes (pass the length or last-updated of your list
 * so we retry once the rows actually render).
 */
export default function useHighlightRow({ prefix, param = "highlight", enabled = true, dataKey } = {}) {
  const location = useLocation();
  useEffect(() => {
    if (!enabled || !prefix) return;
    const sp = new URLSearchParams(location.search);
    const id = sp.get(param);
    if (!id) return;

    // Poll for the element for up to ~4s. Row renders are async so a single
    // rAF isn't reliable; retry ~250ms x 16.
    let tries = 0;
    let cancelled = false;

    const attempt = () => {
      if (cancelled) return;
      const el = document.querySelector(`[data-testid="${prefix}-${id}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("row-flash-gold");
        // Remove after animation ends so it can re-trigger on next click.
        setTimeout(() => el.classList.remove("row-flash-gold"), 2400);
        return;
      }
      if (++tries < 16) setTimeout(attempt, 250);
    };
    // Small delay so parent layouts finish rendering before we search.
    const t = setTimeout(attempt, 60);
    return () => { cancelled = true; clearTimeout(t); };
  }, [location.search, prefix, param, enabled, dataKey]);
}
