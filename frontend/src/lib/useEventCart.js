import { useState, useEffect, useMemo, useCallback } from "react";
import { mediaUrl, thumbUrl } from "./api";

/**
 * Iter 46 — useEventCart
 *
 * Owns everything about the multi-artist event cart that lives inside a
 * primary BookingFlow session:
 *   • Primary artist row (derived from the parent's `artist` + `pkg` + `form`)
 *   • Secondary artists added via the "Add to Event" modal
 *   • Persistence to localStorage (keyed by primary artist id)
 *   • Aggregate pricing (5% Platform Service Fee + 18% GST)
 *
 * This keeps BookingFlow.jsx free of state management and lets us test the
 * cart contract in isolation.
 */
export function useEventCart({ id, artist, pkg, form, primarySubtotal, legacyAddonsMeta, toast }) {
  const storageKey = id ? `bt_event_cart_${id}` : null;

  // Restore any prior cart on mount (Cart Persistence)
  const [extraArtists, setExtraArtists] = useState(() => {
    try {
      if (!storageKey) return [];
      const raw = localStorage.getItem(storageKey);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed?.items) ? parsed.items : [];
    } catch { return []; }
  });

  const [addModalArtist, setAddModalArtist] = useState(null);
  const [cartRestoredNotified, setCartRestoredNotified] = useState(false);

  // Persist after every mutation.
  // Payload now includes primary artist name + photo so the "Pending Carts"
  // panel on the Customer Dashboard can render a Resume card without having
  // to re-fetch the artist. (Iter 52.5 UX request — users kept losing carts
  // when they navigated away by mistake and forgot which artist they had
  // started with.)
  useEffect(() => {
    if (!storageKey) return;
    try {
      if (extraArtists.length === 0) {
        localStorage.removeItem(storageKey);
      } else {
        const primaryProfile = artist?.profile || {};
        const primaryPhoto = primaryProfile.profile_image
          ? (thumbUrl?.(primaryProfile.profile_image) || mediaUrl?.(primaryProfile.profile_image) || null)
          : null;
        const primaryName =
          primaryProfile.stage_name ||
          `${artist?.first_name || ""} ${artist?.last_name || ""}`.trim() ||
          "Primary Artist";
        localStorage.setItem(storageKey, JSON.stringify({
          items: extraArtists,
          saved_at: Date.now(),
          primary_id: id,
          primary_name: primaryName,
          primary_photo: primaryPhoto,
          primary_category: primaryProfile.category,
          primary_city: primaryProfile.city,
          event_date: form?.event_date || null,
          event_city: form?.city || null,
        }));
      }
    } catch { /* localStorage disabled */ }
    // Notify listeners (EventCartIndicator in the top nav) that the pending
    // cart map has changed so they can re-render without polling.
    try { window.dispatchEvent(new Event("bt-event-cart-changed")); } catch { /* SSR */ }
    if (!cartRestoredNotified && extraArtists.length > 0 && typeof toast === "function") {
      setCartRestoredNotified(true);
      toast(`Welcome back — ${extraArtists.length} artist${extraArtists.length > 1 ? "s" : ""} still in your event cart`, "success");
    }
  }, [extraArtists, storageKey, artist, id, form?.event_date, form?.city]); // eslint-disable-line react-hooks/exhaustive-deps

  const addSecondaryArtist = useCallback((cartItem) => {
    setExtraArtists((prev) => prev.some((x) => x.artist_id === cartItem.artist_id) ? prev : [...prev, cartItem]);
    setAddModalArtist(null);
    if (typeof toast === "function") toast(`${cartItem.artist_name} added to your event`, "success");
  }, [toast]);

  const removeSecondaryArtist = useCallback((artist_id) => {
    setExtraArtists((prev) => prev.filter((x) => x.artist_id !== artist_id));
  }, []);

  const clearCart = useCallback(() => {
    setExtraArtists([]);
    try { if (storageKey) localStorage.removeItem(storageKey); } catch { /* ignore */ }
  }, [storageKey]);

  // Compose primary + secondaries into a display list
  const cartItems = useMemo(() => {
    const items = [];
    const primaryProfile = artist?.profile || {};
    if (artist && pkg) {
      const primaryPhoto = primaryProfile.profile_image;
      items.push({
        artist_id: id,
        artist_name:
          primaryProfile.stage_name ||
          `${artist.first_name || ""} ${artist.last_name || ""}`.trim() ||
          "Primary Artist",
        artist_photo: primaryPhoto
          ? (thumbUrl?.(primaryPhoto) || mediaUrl?.(primaryPhoto) || (/^https?:\/\//.test(primaryPhoto) ? primaryPhoto : null))
          : null,
        category: primaryProfile.category,
        city: primaryProfile.city,
        emoji: primaryProfile.emoji || "🎤",
        package_id: pkg.id,
        package_name: pkg.name,
        package_price: Number(pkg.price),
        addon_selections: [
          ...(form?.addons || []).map((slug) => {
            const meta = (legacyAddonsMeta || []).find((x) => x.id === slug);
            return { addon_id: slug, quantity: 1, name: meta?.label || slug, price: meta?.price || 0 };
          }),
          ...(form?.addon_selections || []),
        ],
        price_subtotal: primarySubtotal,
        is_primary: true,
      });
    }
    return [...items, ...extraArtists];
  }, [artist, pkg, id, form?.addons, form?.addon_selections, primarySubtotal, extraArtists, legacyAddonsMeta]);

  const cartArtistIds = useMemo(() => new Set(cartItems.map((c) => c.artist_id)), [cartItems]);

  const cartPricing = useMemo(() => {
    const subtotal = cartItems.reduce((s, i) => s + Number(i.price_subtotal || 0), 0);
    const platform_fee = Math.round(subtotal * 0.05 * 100) / 100;
    const gst = Math.round(platform_fee * 0.18 * 100) / 100;
    return { subtotal, platform_fee, gst, token_amount: Math.round((platform_fee + gst) * 100) / 100 };
  }, [cartItems]);

  const isMultiEvent = extraArtists.length > 0;

  return {
    // state
    extraArtists,
    addModalArtist,
    // derived
    cartItems,
    cartArtistIds,
    cartPricing,
    isMultiEvent,
    // actions
    setAddModalArtist,
    addSecondaryArtist,
    removeSecondaryArtist,
    clearCart,
  };
}
