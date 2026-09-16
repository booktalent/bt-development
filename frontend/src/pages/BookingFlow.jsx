import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import Nav from "../components/Nav";
import AvailabilityCalendar from "../components/AvailabilityCalendar";
import BookingCart from "../components/BookingCart";
import AddArtistToCartModal from "../components/AddArtistToCartModal";
import PaymentStep from "../components/booking/PaymentStep";
import ReviewStep from "../components/booking/ReviewStep";
import api, { fmtINRFull, formatApiError, mediaUrl, thumbUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { useEventCart } from "../lib/useEventCart";

const ADDONS = [
  { id: "dhol", label: "🥁 Dhol Player", price: 3500 },
  { id: "anchor", label: "🎙️ Anchor / Emcee", price: 5000 },
  { id: "photo", label: "📸 Photography", price: 4000 },
  { id: "extra-hour", label: "⏱️ Extra Hour", price: 8000 },
];

// Iter 52.5 — Time slots now carry a mood-label so the grid reads like a
// premium concierge picker ("6:00 PM · Evening") instead of a bare list.
const TIME_SLOTS = [
  { time: "2:00 PM",  label: "Matinee" },
  { time: "4:00 PM",  label: "Afternoon" },
  { time: "6:00 PM",  label: "Evening" },
  { time: "7:00 PM",  label: "Evening" },
  { time: "8:00 PM",  label: "Prime" },
  { time: "9:00 PM",  label: "Popular" },
  { time: "10:00 PM", label: "Late" },
  { time: "11:00 PM", label: "Late" },
];

export default function BookingFlow() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const nav = useNavigate();

  const [artist, setArtist] = useState(null);
  const [packages, setPackages] = useState([]);
  const [artistAddons, setArtistAddons] = useState([]); // Sprint 3
  const [platformSettings, setPlatformSettings] = useState({});  // Outstation policy strings
  const [busy, setBusy] = useState(false);
  // Iter 73 — Persist multi-step booking state to sessionStorage so:
  //   (a) hitting Back inside the flow never loses previously entered data,
  //   (b) an auth bounce (login/signup) followed by a return-to-URL lands
  //       the customer on the SAME step with the SAME selections,
  //   (c) an accidental refresh doesn't reset the funnel to step 1.
  // Key is scoped to the artist so switching artists doesn't cross-pollute.
  const storageKey = `bt_book_state_${id}`;
  const restored = React.useMemo(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }, [storageKey]);
  const [step, setStep] = useState(restored?.step || 1);

  const [form, setForm] = useState(() => {
    const base = {
      package_id: params.get("pkg") || "",
      addons: [],
      addon_selections: [],  // Sprint 3: [{addon_id, quantity}]
      // Iter 44 — pre-fill from URL for "Add another artist to this event" flow
      event_date: params.get("date") || "",
      event_time: params.get("time") || "",
      event_type: params.get("event_type") || "Wedding / Sangeet",
      venue: params.get("venue") || "",
      city: params.get("city") || "",
      guests: "300-600",
      language_pref: "Hindi (Bollywood)",
      notes: "",
      customer_name: user ? `${user.first_name} ${user.last_name || ""}`.trim() : "",
      customer_phone: user?.phone || "",
      customer_email: user?.email || "",
      coupon_code: "",
      // Iter 52.5 additions ↓
      customer_travel_allowance: "",
      tnc_accepted: false,
      // Iter 52.6 — outstation ack pre-collected on the artist profile
      outstation_ack: params.get("outstation_ack") === "1",
    };
    // Merge in any persisted form values — URL params still override so a
    // "share this booking" link keeps the same explicit values.
    if (restored?.form) {
      Object.keys(restored.form).forEach((k) => {
        if (!params.get(k === "package_id" ? "pkg" : k) && restored.form[k] !== undefined) {
          base[k] = restored.form[k];
        }
      });
    }
    return base;
  });
  const [paymentMethod, setPaymentMethod] = useState("card");
  const [successData, setSuccessData] = useState(null);
  const [gatewayInfo, setGatewayInfo] = useState({ provider: "easebuzz", enabled: true, environment: "sandbox" });
  const [quoteMeta, setQuoteMeta] = useState(null); // full breakdown from /finance/quote
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [alternatives, setAlternatives] = useState(null);
  // Iter 44 — Multi-Artist Event: if we came in from another booking's
  // "Add another artist" strip, pre-fill event basics and thread the
  // event_id through so the new booking joins the same umbrella.
  const eventIdParam = params.get("event_id") || "";
  const [suggested, setSuggested] = useState([]);  // shown on success screen

  useEffect(() => {
    if (!user) {
      // Iter 73 — Preserve the full booking URL (including pkg/city/date/
      // outstation_ack) so login → sign-up flow returns the customer to
      // this exact step with everything they had already selected.
      const back = `${window.location.pathname}${window.location.search}`;
      nav(`/login?next=${encodeURIComponent(back)}`);
      return;
    }
    api.get(`/artists/${id}`).then((r) => {
      setArtist(r.data);
      setPackages(r.data.packages);
      if (!form.package_id && r.data.packages.length) {
        const pop = r.data.packages.find((p) => p.is_popular) || r.data.packages[0];
        setForm((f) => ({ ...f, package_id: pop.id }));
      }
    });
    // Iter 74 — Cross-device draft restore. Only apply the server draft
    // when we DON'T have a local sessionStorage state (that always wins
    // because it's more recent) AND no URL params provided pkg/city/date
    // (a shared deep-link must also win). This makes "start on desktop,
    // finish on phone" work seamlessly.
    if (!restored && !params.get("pkg") && !params.get("city") && !params.get("date")) {
      api.get(`/customer/booking-drafts/${id}`).then((r) => {
        if (r.data?.form) {
          setForm((f) => ({ ...f, ...r.data.form }));
          if (typeof r.data.step === "number" && r.data.step > 1 && r.data.step < 6) {
            setStep(r.data.step);
          }
        }
      }).catch(() => { /* no draft — normal path */ });
    }
    // Sprint 3 — load artist-defined add-ons
    api.get(`/artists/${id}/addons`).then((r) => {
      setArtistAddons(r.data || []);
      // Auto-select mandatory add-ons
      const mandatory = (r.data || []).filter((a) => a.is_mandatory).map((a) => ({ addon_id: a.id, quantity: 1 }));
      if (mandatory.length) setForm((f) => ({ ...f, addon_selections: mandatory }));
    }).catch(() => setArtistAddons([]));
    // Outstation policy strings — admin-editable via /admin/settings
    api.get("/settings/public").then((r) => setPlatformSettings(r.data || {})).catch(() => {});
    // Iter 61 — Admin-configurable active payment gateway (Easebuzz only).
    api.get("/payment-gateway/public").then((r) => setGatewayInfo(r.data)).catch(() => {});
    // Iter 83 — Fetch canonical price quote from backend so the summary
    // shows waiver + Total per Sec 3-4. The backend is the only source
    // of truth for fees/waivers/GST. This runs once on mount for initial
    // quoteMeta hydration; a second effect below re-fetches whenever the
    // pricing inputs (package + add-ons) change.
    api.get(`/finance/quote?artist_id=${id}&package_fee=0`)
      .then((r) => setQuoteMeta(r.data))
      .catch(() => setQuoteMeta(null));
    // Fetch only when the artist/package `id` changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Iter 44 — Load complementary artists once the booking is confirmed so we
  // can show the "Complete your event" strip on the success screen.
  useEffect(() => {
    if (step !== 6 || !successData?.booking?.artist_id) return;
    const params = new URLSearchParams();
    if (successData.booking.event_date) params.set("date_str", successData.booking.event_date);
    params.set("limit", "6");
    api
      .get(`/artists/${successData.booking.artist_id}/suggested?${params.toString()}`)
      .then((r) => setSuggested(Array.isArray(r.data) ? r.data : (r.data?.suggested || r.data?.artists || [])))
      .catch(() => setSuggested([]));
  }, [step, successData]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const toggleAddon = (a) => set("addons", form.addons.includes(a) ? form.addons.filter(x => x !== a) : [...form.addons, a]);

  // Iter 73 — Auto-persist form + step to sessionStorage on every change
  // so refresh / back / login-bounce can restore the exact state. We
  // clear on step 6 (success) so the next booking starts fresh.
  React.useEffect(() => {
    try {
      if (step === 6) {
        sessionStorage.removeItem(storageKey);
      } else {
        sessionStorage.setItem(storageKey, JSON.stringify({ form, step }));
      }
    } catch { /* private-mode / quota — silently ignore */ }
  }, [form, step, storageKey]);

  // Iter 74 — Cross-device draft sync. Debounce writes 1.2s so we don't
  // spam the backend on every keystroke, but still preserve on nav-away
  // or unmount. Cleared server-side once the booking hits step 6.
  const draftSyncTimer = React.useRef(null);
  React.useEffect(() => {
    if (!user || step === 6 || !id) return;
    // Only push meaningful drafts — skip the mount-time no-op call.
    if (step === 1 && !form.package_id && !form.city && !form.event_date) return;
    clearTimeout(draftSyncTimer.current);
    draftSyncTimer.current = setTimeout(() => {
      api.post("/customer/booking-drafts", { artist_id: id, form, step })
        .catch(() => {}); // silent — sessionStorage still holds the state
    }, 1200);
    return () => clearTimeout(draftSyncTimer.current);
  }, [form, step, id, user]);

  React.useEffect(() => {
    if (step === 6 && id) {
      api.delete(`/customer/booking-drafts/${id}`).catch(() => {});
    }
  }, [step, id]);

  // Iter 74 — Browser-Back walks the wizard. Every step change (except
  // the initial mount) pushes a new history entry keyed with `{step}`.
  // A popstate handler intercepts Back to decrement the step in-place
  // instead of letting the browser tear the whole booking flow down.
  // Step 6 (success) is a terminal state → we do NOT push it so Back
  // takes the user out of the wizard entirely (expected UX).
  const initialStepRef = React.useRef(step);
  React.useEffect(() => {
    if (step === initialStepRef.current) return; // don't push the mount step
    if (step === 6) return; // terminal → let Back leave the flow
    try {
      window.history.pushState({ __bt_step: step, __bt_artist: id }, "", window.location.href);
    } catch { /* ignore */ }
  }, [step, id]);
  React.useEffect(() => {
    const onPop = (e) => {
      // Ignore popstate for other pages / artists.
      const s = e.state?.__bt_step;
      if (typeof s === "number" && e.state?.__bt_artist === id) {
        setStep(s);
        return;
      }
      // No step in state → user is exiting the flow entirely; if we're
      // past step 1 we treat this as walking back one step so single Back
      // presses inside the wizard don't blow it up. Only decrement if
      // there IS a previous step to walk to.
      if (step > 1 && step < 6) {
        setStep((s) => Math.max(1, s - 1));
        try {
          window.history.pushState({ __bt_step: step - 1, __bt_artist: id }, "", window.location.href);
        } catch { /* ignore */ }
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, id]);

  // Iter 35 — Canonicalise cities before comparing so intra-region events
  // (Delhi/New Delhi/NCR, Mumbai/Bombay, Bengaluru/Bangalore, ...) don't
  // wrongly trigger the outstation gate. Uses the same alias table as the
  // backend, exposed via /settings/public.
  const canonicalCity = (name) => {
    const key = (name || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (!key) return "";
    const table = platformSettings.city_aliases || {};
    for (const [canon, aliases] of Object.entries(table)) {
      if (canon.toLowerCase() === key) return canon.toLowerCase();
      if (Array.isArray(aliases) && aliases.some((a) => (a || "").toLowerCase() === key)) return canon.toLowerCase();
    }
    return key;
  };
  const isOutstation = !!(
    form.city &&
    artist?.profile?.city &&
    canonicalCity(form.city) !== canonicalCity(artist.profile.city)
  );

  // Sprint 3 — Artist-defined add-on helpers
  const isAddonSelected = (id) => form.addon_selections.some((x) => x.addon_id === id);
  const addonQty = (id) => form.addon_selections.find((x) => x.addon_id === id)?.quantity || 0;
  const toggleArtistAddon = (a) => {
    if (a.is_mandatory) return; // cannot deselect mandatory
    setForm((f) => ({
      ...f,
      addon_selections: isAddonSelected(a.id)
        ? f.addon_selections.filter((x) => x.addon_id !== a.id)
        : [...f.addon_selections, { addon_id: a.id, quantity: 1 }],
    }));
  };
  const setArtistAddonQty = (a, qty) => {
    const q = Math.max(1, Math.min(a.max_quantity || 1, Number(qty) || 1));
    setForm((f) => ({
      ...f,
      addon_selections: f.addon_selections.map((x) =>
        x.addon_id === a.id ? { ...x, quantity: q } : x,
      ),
    }));
  };

  const pkg = packages.find((p) => p.id === form.package_id);
  const addonsTotal = form.addons.reduce((s, a) => s + (ADDONS.find(x => x.id === a)?.price || 0), 0);
  // Sprint 3 — artist add-ons total (unit_price * qty + gst_pct)
  const artistAddonsTotal = form.addon_selections.reduce((s, sel) => {
    const a = artistAddons.find((x) => x.id === sel.addon_id);
    if (!a) return s;
    const sub = a.price * sel.quantity;
    const gst = sub * (a.gst_pct || 0) / 100;
    return s + sub + gst;
  }, 0);
  const pkgPrice = pkg?.price || 0;
  const primarySubtotal = pkgPrice + addonsTotal + artistAddonsTotal;

  // ── Iter 45/46 — Multi-Artist Event Cart via useEventCart hook ──────────
  // Secondary artists added via the "Need More Artists?" panel on Step 2.
  // The primary artist is derived from the current form state and lives at
  // cartItems[0]. Secondary artists persist to localStorage keyed by primary
  // artist id — so a coffee-break refresh brings them back.
  const {
    extraArtists,
    addModalArtist,
    cartItems,
    cartArtistIds,
    cartPricing,
    isMultiEvent,
    setAddModalArtist,
    addSecondaryArtist,
    removeSecondaryArtist,
    clearCart,
  } = useEventCart({
    id,
    artist,
    pkg,
    form,
    primarySubtotal,
    legacyAddonsMeta: ADDONS,
    toast,
  });

  // ── BookTalent business model ─────────────────────────────────────
  // Backend is the ONLY source of truth for pricing. We call /finance/quote
  // whenever the base inputs change and read platform_fee / gst / total
  // from the response — no more hardcoded 5% / 18% on the frontend.
  const artistFee = primarySubtotal;                    // paid directly to artist
  const platformFee = quoteMeta ? Math.round(quoteMeta.platform_fee || 0)         : Math.round(artistFee * 0.05);
  const platformFeeNet = quoteMeta ? Math.round(quoteMeta.platform_fee_net || 0) : platformFee;
  const gst = quoteMeta ? Math.round(quoteMeta.gst_amount || 0)                   : Math.round(platformFee * 0.18);
  const gstPercent = quoteMeta?.gst_percent ?? 18;
  const feePercent = quoteMeta?.platform_fee_percent ?? 5;
  const gstVisible = quoteMeta ? !!quoteMeta.gst_visible : true;
  // "Amount payable to BookTalent" = net platform fee + GST + add-ons GST.
  // Artist Performance Fee is settled directly customer↔artist, not through us.
  const total = platformFeeNet + gst;                    // BookTalent-collected amount
  const token = total;                                   // legacy alias
  const subtotal = artistFee;                            // legacy alias for display blocks

  // Re-fetch canonical quote when pricing inputs change so the summary
  // stays perfectly in sync with what the server will actually charge.
  useEffect(() => {
    if (!id) return;
    const packageFee = pkgPrice + addonsTotal + artistAddonsTotal;
    setQuoteLoading(true);
    api.get(`/finance/quote?artist_id=${id}&package_fee=${packageFee}`)
      .then((r) => setQuoteMeta(r.data))
      .catch(() => { /* keep last good quote */ })
      .finally(() => setQuoteLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, pkgPrice, addonsTotal, artistAddonsTotal]);

  const submitBooking = async () => {
    setBusy(true);
    setAlternatives(null);

    // Iter 59.1 — DEFENSIVE session + T&C check.
    // User reported "randomly redirects to login / T&C error / Not
    // Authorized" after clicking Pay. Root cause was any one of:
    //   (a) form state stale/unset for hidden fields → 422
    //   (b) `tnc_accepted` un-ticked between step 4 and Pay → 400
    //   (c) transient 401 on a background call
    // We now:
    //   1) Probe /auth/me — if it 401s we still let the flow continue so
    //      /bookings can produce the authoritative error (the api.js
    //      interceptor rewrites 401s to a friendly message). Previously we
    //      short-circuited here with a "session ended" toast that fired
    //      even when the real cookie was perfectly valid.
    //   2) Explicitly build the payload — NEVER spread `...form` — so
    //      only the fields the backend expects are sent, with correct
    //      types. tnc_accepted is HARD-FORCED to true (user is on step 5
    //      which means they cleared the ReviewStep T&C gate on step 4).
    try {
      await api.get("/auth/me");
    } catch (_e) {
      // Non-fatal — /bookings will re-check auth and produce a real error.
      // eslint-disable-next-line no-console
      console.warn("[booking] /auth/me probe failed, continuing anyway");
    }

    // Iter 62 — Defensive mandatory-addon merge. The backend rejects a
    // booking if any artist-defined `is_mandatory` add-on is missing. We
    // auto-select these on mount, but a race condition or user's own
    // deselect action could still leave them out at submit time — so re-
    // merge them here as a belt-and-braces guarantee.
    const mandatoryAddons = (artistAddons || []).filter((a) => a.is_mandatory && a.active !== false);
    const currentSels = form.addon_selections || [];
    const mergedSelections = [...currentSels];
    for (const md of mandatoryAddons) {
      if (!mergedSelections.some((x) => x.addon_id === md.id)) {
        mergedSelections.push({ addon_id: md.id, quantity: 1 });
      }
    }

    const commonFields = {
      event_date: form.event_date,
      event_time: form.event_time,
      event_type: form.event_type || "Wedding",
      // Iter 83 — Sec 20/21/22 new fields
      event_type_other: form.event_type === "Others" ? (form.event_type_other || "") : null,
      number_of_days: parseInt(form.number_of_days) || 1,
      venue_address: form.venue_address || "",
      venue: form.venue,
      city: form.city,
      guests: (form.guests || form.guest_count || "").toString(),
      language_pref: form.language_pref || "",
      notes: form.notes || "",
      special_instructions: form.special_instructions || "",
      customer_name: form.customer_name || user?.first_name || "",
      customer_phone: form.customer_phone || "",
      customer_email: form.customer_email || user?.email || "",
      tnc_accepted: true, // forced — user is past step 4 gate
      customer_travel_allowance:
        form.customer_travel_allowance === "" || form.customer_travel_allowance == null
          ? 0
          : Number(form.customer_travel_allowance) || 0,
    };

    try {
      // ── Iter 45: Multi-Artist Batch Checkout (Easebuzz-only) ─────────
      // All bookings created under one event_id and paid in a single hosted
      // Easebuzz checkout. Each artist still gets an isolated booking,
      // contract and 24-hour confirmation window.
      if (isMultiEvent) {
        const items = cartItems.map((c) => ({
          artist_id: c.artist_id,
          package_id: c.package_id,
          addons: c.is_primary ? form.addons : [],
          addon_selections: c.is_primary ? mergedSelections : (c.addon_selections || []),
          coupon_code: c.is_primary ? form.coupon_code : "",
          ...commonFields,
        }));
        const batchR = await api.post("/bookings/batch", { items });
        const { booking_ids } = batchR.data;
        const ebR = await api.post("/payments/easebuzz/init", {
          booking_ids, method: paymentMethod,
        });
        window.location.href = ebR.data.payment_url;
        return;
      }
      // ── Single-artist flow — explicit payload ─────────────────────────
      const payload = {
        artist_id: id,
        package_id: form.package_id,
        addons: form.addons || [],
        addon_selections: mergedSelections,
        coupon_code: form.coupon_code || "",
        ...commonFields,
        ...(eventIdParam ? { event_id: eventIdParam } : {}),
      };
      let r;
      try {
        r = await api.post("/bookings", payload);
      } catch (e) {
        const detail = e?.response?.data?.detail;
        if (typeof detail === "object" && !Array.isArray(detail) && detail?.alternatives) {
          setAlternatives({ message: detail.message, date: detail.date, list: detail.alternatives });
          setBusy(false);
          return;
        }
        throw e;
      }
      const booking = r.data;
      const ebR = await api.post("/payments/easebuzz/init", {
        booking_ids: [booking.id], method: paymentMethod,
      });
      window.location.href = ebR.data.payment_url;
      return;
    } catch (e) {
      toast(formatApiError(e), "error");
    }
    setBusy(false);
  };

  if (!artist) return (
    <div><Nav /><div className="loading"><div className="spinner" /></div></div>
  );

  return (
    <div data-testid="booking-flow-page">
      <Nav />
      <div className="container" style={{ paddingTop: 32, paddingBottom: 60 }}>
        {step < 6 && (
          <div className="steps" data-testid="booking-steps">
            {[1, 2, 3, 4, 5].map((n, i) => (
              <React.Fragment key={n}>
                <div className="step-node">
                  <div className={`step-circle ${step === n ? "active" : step > n ? "done" : ""}`}>{step > n ? "✓" : n}</div>
                </div>
                {i < 4 && <div className={`step-line ${step > n ? "done" : ""}`} />}
              </React.Fragment>
            ))}
          </div>
        )}
        {step > 1 && step < 6 && (
          /* Iter 74 — Save & Finish Later. The draft is already being
             synced in the background, so this button just flushes any
             pending debounce and takes the customer to their dashboard
             where the "Continue Booking" strip is waiting. */
          <div style={{ display: "flex", justifyContent: "flex-end", margin: "-8px 0 10px" }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="save-and-finish-later"
              onClick={async () => {
                try {
                  await api.post("/customer/booking-drafts", { artist_id: id, form, step });
                } catch { /* ignore — sessionStorage still has it */ }
                nav("/customer?tab=drafts");
              }}
              title="Your progress is saved. Pick it up later from any device."
            >💾 Save & Finish Later</button>
          </div>
        )}

        <div className="booking-flow-grid" data-testid="booking-flow-grid">
          <div>
            {step === 1 && (
              <>
                {artist && (() => {
                  const answers = artist.answers || {};
                  const filled = Object.values(answers).filter((v) => v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)).length;
                  if (filled >= 8) return null;
                  return (
                    <div className="booking-incomplete-warn" data-testid="booking-incomplete-warn">
                      <span className="booking-incomplete-icon">⚠️</span>
                      <div>
                        <div className="booking-incomplete-title">
                          {(artist.stage_name || [artist.first_name, artist.last_name].filter(Boolean).join(" ").trim() || "The artist")}'s profile is still being completed
                        </div>
                        <div className="booking-incomplete-sub">
                          Some details (equipment, travel radius, technical rider) may not be filled in yet.
                          You can still book — we'll confirm the finer points once the artist accepts.
                        </div>
                      </div>
                    </div>
                  );
                })()}
                <div className="card card-pad" data-testid="step-1">
                <h2 className="font-serif fs-20 fw-700 mb-8">Choose your Package</h2>
                <p className="text-muted fs-13 mb-20">Select the package that fits your event.</p>
                {packages.map((p) => (
                  <div
                    key={p.id} onClick={() => set("package_id", p.id)}
                    className={`pkg-card mb-12 ${form.package_id === p.id ? "selected" : ""}`}
                    data-testid={`pkg-opt-${p.id}`}
                  >
                    {p.is_popular && <span className="popular-tag">★ Most Popular</span>}
                    <div className="flex justify-between items-center" style={{ marginTop: p.is_popular ? 12 : 0 }}>
                      <div>
                        <div className="pkg-name" style={{ fontSize: 18 }}>{p.name}</div>
                        <div className="text-muted fs-12 mt-4">⏱ {p.duration} · {p.features.slice(0, 3).join(" · ")}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-gold font-serif" style={{ fontSize: 24, fontWeight: 700 }}>{fmtINRFull(p.price)}</div>
                        <div className="text-muted fs-11">per event</div>
                      </div>
                    </div>
                  </div>
                ))}
                {/* Iter 76.7 — Add-ons now come EXCLUSIVELY from what the
                    artist configured. The old "Optional Add-ons" grid
                    (Dhol / Anchor / Photography / Extra Hour) was a
                    hard-coded placeholder that appeared for every
                    artist even when they had no real add-ons — and
                    its ids never mapped to real DB rows so the
                    backend snapshot ignored them. If the artist
                    hasn't set any add-ons, the section is simply
                    hidden. */}
                {artistAddons.length > 0 && (
                  <>
                    <h3 className="fs-13 fw-600 mt-24 mb-12 text-gold" style={{ textTransform: "uppercase", letterSpacing: 1 }}>🎁 Optional Add-ons</h3>
                    <div className="flex-col gap-10">
                      {artistAddons.map((a) => {
                        const selected = isAddonSelected(a.id);
                        return (
                          <div
                            key={a.id}
                            onClick={() => toggleArtistAddon(a)}
                            className={`pkg-card ${selected ? "selected" : ""} ${a.is_mandatory ? "popular" : ""}`}
                            style={{ padding: 14, cursor: a.is_mandatory ? "default" : "pointer" }}
                            data-testid={`artist-addon-${a.id}`}
                          >
                            {a.is_mandatory && <span className="popular-tag">★ Mandatory</span>}
                            <div className="flex justify-between items-center" style={{ marginTop: a.is_mandatory ? 12 : 0 }}>
                              <div style={{ flex: 1 }}>
                                <div className="fw-600 fs-14">{a.name}</div>
                                {a.description && <div className="text-muted fs-12">{a.description}</div>}
                                {a.gst_pct > 0 && <div className="text-muted fs-11">+{a.gst_pct}% GST</div>}
                              </div>
                              <div className="text-right">
                                <div className="text-gold fw-700 fs-15">+{fmtINRFull(a.price)}</div>
                                {selected && a.max_quantity > 1 && (
                                  <div className="flex items-center gap-8 mt-8" onClick={(e) => e.stopPropagation()}>
                                    <button className="btn btn-ghost btn-xs" onClick={() => setArtistAddonQty(a, addonQty(a.id) - 1)} data-testid={`artist-addon-qty-dec-${a.id}`}>−</button>
                                    <span className="fs-13 fw-600" data-testid={`artist-addon-qty-${a.id}`}>{addonQty(a.id)}</span>
                                    <button className="btn btn-ghost btn-xs" onClick={() => setArtistAddonQty(a, addonQty(a.id) + 1)} data-testid={`artist-addon-qty-inc-${a.id}`}>+</button>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}

                <div className="flex justify-between mt-24">
                  <div />
                  <button className="btn btn-gold" disabled={!form.package_id} onClick={() => setStep(2)} data-testid="step1-next">Continue to Schedule →</button>
                </div>
              </div>
              </>
            )}

            {step === 2 && (
              <>
              <div className="card card-pad datetime-step" data-testid="step-2">
                <h2 className="datetime-heading">
                  Pick your <span className="datetime-heading-serif">Date &amp; Time</span>
                </h2>
                <p className="text-muted fs-13 mb-20" style={{ paddingBottom: 14, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  Select an available date and preferred performance time slot.
                </p>
                <AvailabilityCalendar
                  artistUserId={id}
                  selected={form.event_date}
                  onPick={(d) => set("event_date", d)}
                />
                {form.event_date && (
                  <div className="datetime-selected-pill" data-testid="selected-date-pill">
                    <span aria-hidden style={{ fontSize: 15 }}>📅</span>
                    <span>{new Date(form.event_date + "T00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}</span>
                  </div>
                )}
                {form.event_date && (
                  <div className="field mt-20 timeslot-block">
                    <div className="fs-14 fw-700 mb-12">Select Performance Start Time</div>
                    <div className="timeslot-grid">
                      {TIME_SLOTS.map((t) => {
                        const active = form.event_time === t.time;
                        return (
                          <button
                            key={t.time}
                            type="button"
                            onClick={() => set("event_time", t.time)}
                            className={`timeslot-card ${active ? "active" : ""}`}
                            data-testid={`time-${t.time.replace(/[^0-9]/g, "")}`}
                          >
                            <div className="timeslot-time">{t.time}</div>
                            <div className="timeslot-label">{t.label}</div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                <div className="flex justify-between mt-24">
                  <button className="btn btn-ghost" onClick={() => setStep(1)} data-testid="step2-back">← Back</button>
                  <button className="btn btn-gold" disabled={!form.event_date || !form.event_time} onClick={() => setStep(3)} data-testid="step2-next">
                    Continue to Event Info →
                  </button>
                </div>
              </div>
              {form.event_date && (
                <SuggestedArtistsPanel
                  artistId={id}
                  date={form.event_date}
                  cartArtistIds={cartArtistIds}
                  onOpenAdd={(a) => setAddModalArtist(a)}
                />
              )}
              {/* Multi-artist cart preview once anyone added.
                  Mirrors the left-side Continue button so users don't have
                  to scroll back up after adding more artists at the bottom
                  (user request, Iter 52.5). */}
              {isMultiEvent && (
                <BookingCart
                  items={cartItems}
                  pricing={cartPricing}
                  onRemove={removeSecondaryArtist}
                  onContinue={() => setStep(3)}
                  continueDisabled={!form.event_date || !form.event_time}
                  continueLabel="Continue to Event Details →"
                  continueTestId="cart-step2-next"
                />
              )}
              </>
            )}

            {step === 3 && (
              <div className="card card-pad" data-testid="step-3">
                <h2 className="font-serif fs-20 fw-700 mb-8">Tell us about your Event</h2>
                <p className="text-muted fs-13 mb-20">Help the artist prepare the perfect performance.</p>
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">Your Full Name *</div>
                    <input className="field-input" value={form.customer_name} onChange={(e) => set("customer_name", e.target.value)} data-testid="booking-name" />
                  </div>
                  <div className="field">
                    <div className="field-label">Mobile Number *</div>
                    <input className="field-input" value={form.customer_phone} onChange={(e) => set("customer_phone", e.target.value)} data-testid="booking-phone" />
                  </div>
                </div>
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">Email *</div>
                    <input className="field-input" type="email" value={form.customer_email} onChange={(e) => set("customer_email", e.target.value)} data-testid="booking-email" />
                  </div>
                  <div className="field">
                    <div className="field-label">Event Type *</div>
                    <select className="field-input" value={form.event_type} onChange={(e) => set("event_type", e.target.value)} data-testid="booking-event-type">
                      <option>Wedding / Sangeet</option><option>Corporate Event</option><option>Birthday Celebration</option>
                      <option>Private Concert</option><option>College Fest</option>
                      <option>Product Launch</option><option>Award Function</option>
                      <option>Festival</option><option>Conference</option>
                      <option>Others</option>
                    </select>
                  </div>
                </div>
                {form.event_type === "Others" && (
                  <div className="field">
                    <div className="field-label">Please specify your event type *</div>
                    <input
                      className="field-input"
                      value={form.event_type_other || ""}
                      onChange={(e) => set("event_type_other", e.target.value)}
                      placeholder="e.g. Anniversary Gala, Store Opening…"
                      maxLength={200}
                      data-testid="booking-event-type-other"
                    />
                  </div>
                )}
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">No. of Days *</div>
                    <input
                      className="field-input" type="number" min="1" max="30"
                      value={form.number_of_days || 1}
                      onChange={(e) => set("number_of_days", parseInt(e.target.value) || 1)}
                      data-testid="booking-number-of-days"
                    />
                  </div>
                  <div className="field">
                    <div className="field-label">Venue *</div>
                    <input className="field-input" value={form.venue} onChange={(e) => set("venue", e.target.value)} placeholder="e.g. Taj Lands End" data-testid="booking-venue" />
                  </div>
                </div>
                <div className="field-row">
                  <div className="field">
                    <div className="field-label">Full Address *</div>
                    <input
                      className="field-input"
                      value={form.venue_address || ""}
                      onChange={(e) => set("venue_address", e.target.value)}
                      placeholder="Complete event location / postal address"
                      maxLength={500}
                      data-testid="booking-venue-address"
                    />
                  </div>
                  <div className="field">
                    <div className="field-label">City *</div>
                    <input className="field-input" value={form.city} onChange={(e) => set("city", e.target.value)} placeholder="Mumbai" data-testid="booking-city" />
                  </div>
                </div>

                {/* Outstation Business Rule — auto-shown when event city ≠ artist city (alias-aware) */}
                {isOutstation && (
                  <div
                    className="card card-pad mb-16"
                    style={{ background: "rgba(212,175,55,0.08)", border: "1px solid rgba(212,175,55,0.35)" }}
                    data-testid="outstation-notice"
                  >
                    <div className="flex gap-8" style={{ alignItems: "flex-start" }}>
                      <div style={{ fontSize: 24, lineHeight: 1 }}>📢</div>
                      <div style={{ flex: 1 }}>
                        <div className="fw-700 text-gold fs-13 mb-4" style={{ textTransform: "uppercase", letterSpacing: 1 }}>
                          Outstation Booking Notice
                        </div>
                        <div className="fs-13" style={{ lineHeight: 1.5, whiteSpace: "pre-line" }}>
                          {platformSettings.outstation_notice ||
                            "Travel, accommodation, local transportation, meals, hospitality, and any other outstation expenses are NOT included in the Artist Package Fee. Please arrange these directly with the artist."}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
                <div className="field">
                  <div className="field-label">Song Requests / Dedications</div>
                  <textarea className="field-input" value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Song dedications, playlist ideas, special requests…" data-testid="booking-notes" />
                </div>
                <div className="field">
                  <div className="field-label">
                    Special Instructions
                    {isOutstation && <span className="text-gold fs-11" style={{ marginLeft: 8 }}>· recommended for outstation bookings</span>}
                  </div>
                  <textarea
                    className="field-input"
                    value={form.special_instructions || ""}
                    onChange={(e) => set("special_instructions", e.target.value)}
                    placeholder={isOutstation
                      ? "Outstation asks: hotel preference, flight class, arrival/departure timing, dietary needs, green-room setup, security…"
                      : "Anything else the artist should know — dietary needs, green-room setup, dress code, load-in access…"}
                    rows={3}
                    data-testid="booking-special-instructions"
                  />
                </div>
                <div className="field">
                  <div className="field-label">Coupon Code (optional)</div>
                  <input className="field-input" value={form.coupon_code} onChange={(e) => set("coupon_code", e.target.value.toUpperCase())} placeholder="e.g. WEDDING20" data-testid="booking-coupon" />
                </div>
                <div className="flex justify-between mt-24">
                  <button className="btn btn-ghost" onClick={() => setStep(2)} data-testid="step3-back">← Back</button>
                  <button className="btn btn-gold" disabled={!form.customer_name || !form.venue || !form.city} onClick={() => setStep(4)} data-testid="step3-next">Continue →</button>
                </div>
              </div>
            )}

            {step === 4 && (
              <ReviewStep
                pkg={pkg}
                form={form}
                set={set}
                isOutstation={isOutstation}
                platformSettings={platformSettings}
                onBack={() => setStep(3)}
                onNext={() => setStep(5)}
                artistId={id}
              />
            )}

            {step === 5 && (
              <PaymentStep
                paymentMethod={paymentMethod}
                setPaymentMethod={setPaymentMethod}
                gatewayInfo={gatewayInfo}
                busy={busy}
                token={token}
                cartPricing={cartPricing}
                isMultiEvent={isMultiEvent}
                cartItems={cartItems}
                onBack={() => setStep(4)}
                onSubmit={submitBooking}
              />
            )}

            {step === 6 && successData && (
              <div className="card card-pad text-center" data-testid="step-success">
                <div style={{ fontSize: 72, marginBottom: 12 }}>✅</div>
                <h2 className="font-serif" style={{ fontSize: 40, fontWeight: 700, marginBottom: 8 }}>Booking Confirmed!</h2>
                <p className="text-muted mb-20">
                  {successData.batch ? (
                    <>Your event with <strong>{successData.count} artists</strong> is officially booked. All artists have been notified.</>
                  ) : (
                    <>Your booking with <strong>{artist.profile.stage_name}</strong> is officially confirmed. The artist has been notified.</>
                  )}
                </p>
                <div className="pill pill-gold mb-24" style={{ fontSize: 14, padding: "8px 16px" }} data-testid="booking-ref">
                  {successData.batch ? `Event Refs: ${(successData.refs || []).join(" · ")}` : `Booking Ref: ${successData.ref}`}
                </div>
                {successData.batch ? (
                  <div className="card card-pad mb-20" style={{ textAlign: "left", maxWidth: 520, margin: "0 auto 20px" }}>
                    <div className="fs-13 mb-12">
                      <div className="text-muted">Event Date</div>
                      <div className="fw-700">{form.event_date} · {form.event_time}</div>
                    </div>
                    <div className="fs-13 mb-12">
                      <div className="text-muted">Venue</div>
                      <div className="fw-700">{form.venue}, {form.city}</div>
                    </div>
                    <div className="fs-13">
                      <div className="text-muted mb-8">Artists in this Event</div>
                      {cartItems.map((c) => (
                        <div key={c.artist_id} className="flex justify-between fs-12" style={{ padding: "6px 0", borderBottom: "1px dashed rgba(255,255,255,0.06)" }}>
                          <span>{c.artist_name}<span className="text-muted"> · {c.category}</span></span>
                          <span className="text-gold">{fmtINRFull(c.price_subtotal || c.package_price || 0)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="card card-pad mb-20" style={{ textAlign: "left", maxWidth: 480, margin: "0 auto 20px" }}>
                    <div className="flex justify-between mb-8"><span className="text-muted">Artist</span><span>{artist.profile.stage_name}</span></div>
                    <div className="flex justify-between mb-8"><span className="text-muted">Package</span><span>{pkg?.name}</span></div>
                    <div className="flex justify-between mb-8"><span className="text-muted">Date</span><span>{form.event_date} · {form.event_time}</span></div>
                    <div className="flex justify-between mb-8"><span className="text-muted">Venue</span><span>{form.venue}</span></div>
                    <div className="flex justify-between mb-8"><span className="text-muted">Artist Performance Fee</span><span>{fmtINRFull(artistFee)}</span></div>
                    <div className="flex justify-between"><span className="text-muted">Paid to BookTalent</span><span className="text-green">{fmtINRFull(total)}</span></div>
                    <div className="text-muted fs-11 mt-12" style={{ marginTop: 12, lineHeight: 1.4 }}>
                      ℹ️ The Artist Performance Fee of <b>{fmtINRFull(artistFee)}</b> will be settled directly with the artist as per your signed agreement.
                    </div>
                  </div>
                )}
                <div className="flex gap-12 justify-center" style={{ flexWrap: "wrap" }}>
                  <button className="btn btn-gold" onClick={() => nav("/customer")} data-testid="success-go-dashboard">📊 Go to Dashboard</button>
                  {successData.event_id && (
                    <button
                      className="btn btn-ghost"
                      onClick={() => window.open(`/recap/${successData.event_id}`, "_blank", "noopener")}
                      data-testid="success-share-recap"
                    >💬 Share Event Recap</button>
                  )}
                  <button
                    className="btn btn-ghost"
                    style={{ display: successData.batch ? "none" : undefined }}
                    onClick={async () => {
                      const r = await fetch(`${api.defaults.baseURL}/bookings/${successData.booking.id}/invoice`, { credentials: "include" });
                      const blob = await r.blob();
                      const a = document.createElement("a");
                      a.href = window.URL.createObjectURL(blob);
                      a.download = `invoice_${successData.ref}.pdf`;
                      a.click();
                    }}
                    data-testid="success-dl-invoice"
                  >🧾 Download Invoice</button>
                  <button className="btn btn-ghost" onClick={() => nav("/")} data-testid="success-go-home">🏠 Home</button>
                </div>

                {/* Iter 44 — Complete-your-event suggestion strip */}
                {suggested.length > 0 && successData.event_id && (
                  <div className="event-strip" data-testid="event-strip">
                    <div className="event-strip-head">
                      <div>
                        <div className="event-strip-title">Complete your event 🎉</div>
                        <div className="event-strip-sub">Same date, same city — add another artist and it joins this event automatically.</div>
                      </div>
                    </div>
                    <div className="event-strip-scroll">
                      {suggested.map((s) => {
                        const qs = new URLSearchParams({
                          event_id: successData.event_id,
                          date: form.event_date,
                          time: form.event_time,
                          city: form.city,
                          venue: form.venue,
                          event_type: form.event_type,
                        }).toString();
                        return (
                          <a
                            key={s.user_id}
                            href={`/book/${s.user_id}?${qs}`}
                            className="event-strip-card"
                            data-testid={`event-suggest-${s.user_id}`}
                          >
                            <div className="event-strip-thumb">
                              <span>{s.emoji || "🎤"}</span>
                            </div>
                            <div className="event-strip-name">{s.stage_name || s.name}</div>
                            <div className="event-strip-cat">{s.category}{s.city ? ` · ${s.city}` : ""}</div>
                            <div className="event-strip-add">+ Add to event</div>
                          </a>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {step < 6 && (
            <div data-testid="order-summary">
              {isMultiEvent ? (
                <div className="booking-flow-summary">
                  <BookingCart items={cartItems} pricing={cartPricing} onRemove={removeSecondaryArtist} compact />
                </div>
              ) : (
              <div className="card card-pad booking-flow-summary">
                <div className="flex items-center gap-12 mb-16" style={{ padding: 8, background: "var(--glass)", borderRadius: 10 }}>
                  <div className="avatar avatar-lg" style={{ background: "linear-gradient(135deg, var(--purple), var(--gold))", width: 50, height: 50, fontSize: 24 }}>
                    {artist.profile.emoji || "🎤"}
                  </div>
                  <div>
                    <div className="fw-700 font-serif fs-16">{artist.profile.stage_name}</div>
                    <div className="text-muted fs-11">{artist.profile.category} · {artist.profile.city}</div>
                  </div>
                </div>
                <div className="divider" style={{ margin: "12px 0" }} />
                <div className="flex justify-between mb-8 fs-13"><span className="text-muted">Artist Performance Fee</span><span>{fmtINRFull(artistFee)}</span></div>
                {addonsTotal > 0 && (
                  <div className="flex justify-between mb-8 fs-11" style={{ marginLeft: 12 }}><span className="text-muted">  Package {fmtINRFull(pkgPrice)} + basic add-ons {fmtINRFull(addonsTotal)}</span></div>
                )}
                {artistAddonsTotal > 0 && (
                  <div className="flex justify-between mb-8 fs-11" style={{ marginLeft: 12 }} data-testid="summary-artist-addons"><span className="text-muted">  + Artist add-ons {fmtINRFull(Math.round(artistAddonsTotal))}</span></div>
                )}
                <div className="divider" style={{ margin: "8px 0" }} />
                {quoteMeta?.is_service_artist ? (
                  <>
                    {/* Service artists: show the notional 5% fee, waiver line and payable=0
                        so the customer clearly understands they're getting a waiver worth ₹X. */}
                    {(() => {
                      const notionalPct = feePercent || 5;
                      const notionalFee = Math.round((artistFee * notionalPct) / 100);
                      return (
                        <>
                          <div className="flex justify-between mb-8 fs-13" data-testid="summary-fee-notional">
                            <span className="text-muted">Platform Service Fee ({notionalPct}%)</span>
                            <span style={{ textDecoration: "line-through", opacity: 0.6 }}>{fmtINRFull(notionalFee)}</span>
                          </div>
                          <div className="flex justify-between mb-8 fs-13" data-testid="summary-fee-waiver">
                            <span className="text-good">Platform Fee Waiver</span>
                            <span className="text-good">−{fmtINRFull(notionalFee)}</span>
                          </div>
                          <div className="flex justify-between mb-8 fs-13" data-testid="summary-fee-payable">
                            <span className="text-muted">Platform Fee Payable</span>
                            <span>{fmtINRFull(0)}</span>
                          </div>
                          <div
                            className="text-good fs-12 mb-8"
                            data-testid="summary-fee-waiver-banner"
                            style={{ padding: "8px 10px", borderRadius: 8, background: "rgba(46,204,113,0.08)", border: "1px solid rgba(46,204,113,0.25)", marginTop: 4 }}
                          >
                            🎉 Your 5% Platform Fee has been waived for this artist.
                          </div>
                        </>
                      );
                    })()}
                  </>
                ) : (
                  <div className="flex justify-between mb-8 fs-13"><span className="text-muted">Platform Service Fee ({feePercent}%)</span><span>{fmtINRFull(platformFee)}</span></div>
                )}
                {gstVisible && gst > 0 && (
                  <div className="flex justify-between mb-8 fs-13"><span className="text-muted">GST ({gstPercent}% on {quoteMeta?.is_service_artist ? "Artist Fee" : "Artist Fee + Platform Fee"})</span><span>{fmtINRFull(gst)}</span></div>
                )}
                <div className="divider" style={{ margin: "12px 0" }} />
                <div className="flex justify-between mb-12" data-testid="summary-total-row">
                  <span className="fw-700 font-serif fs-16">Total</span>
                  <span className="fw-700 text-gold font-serif fs-20">{fmtINRFull(artistFee + platformFeeNet + gst)}</span>
                </div>
                <div className="flex justify-between mb-12">
                  <span className="fw-700">Amount Payable to BookTalent</span>
                  <span className="fw-700 text-gold font-serif fs-18" data-testid="bt-amount">{fmtINRFull(total)}</span>
                </div>
                <div style={{ background: "var(--gold-dim)", padding: 14, borderRadius: 10 }}>
                  <div className="text-muted fs-11 mb-4">🔐 Pay Now to BookTalent</div>
                  <div className="font-serif fs-20 fw-700 text-gold" data-testid="token-amount">{fmtINRFull(total)}</div>
                  <div className="text-muted fs-11 mt-8" style={{ marginTop: 8, lineHeight: 1.4 }}>
                    ℹ️ Remaining Artist Performance Fee of <b>{fmtINRFull(artistFee)}</b> will be settled directly between the Customer and the Artist as per the signed agreement.
                  </div>
                </div>

                {/* Fee-Inclusion Note — always visible under the totals */}
                <div
                  className="text-muted fs-11 mt-12"
                  style={{ padding: 10, borderRadius: 8, background: "rgba(255,255,255,0.03)", lineHeight: 1.5 }}
                  data-testid="booking-fee-note"
                >
                  {platformSettings.booking_fee_note ||
                    "Travel, accommodation, local transport, food, hospitality and any other outstation expenses are NOT included in the Artist Package Fee. These expenses will be discussed and managed directly between the Customer and the Artist."}
                </div>
              </div>
              )}
            </div>
          )}
        </div>
      </div>

      {addModalArtist && (
        <AddArtistToCartModal
          suggestedArtist={addModalArtist}
          onAdd={addSecondaryArtist}
          onClose={() => setAddModalArtist(null)}
        />
      )}

      {alternatives && (
        <div className="modal-bg" onClick={() => setAlternatives(null)} data-testid="alternatives-modal">
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">📅 Date Not Available</div>
            <div className="modal-sub">{alternatives.message} on {alternatives.date}. Here are some great alternatives:</div>
            {alternatives.list.length === 0 ? (
              <div className="empty"><div className="empty-icon">🔍</div><div className="empty-title">No alternatives found</div><p className="fs-13">Try picking a different date.</p></div>
            ) : (
              <div className="flex-col gap-12">
                {alternatives.list.map((a) => (
                  <div
                    key={a.user_id} className="card card-pad flex items-center gap-12"
                    onClick={() => { window.location.href = `/artist/${a.user_id}`; }}
                    style={{ cursor: "pointer" }}
                    data-testid={`alt-${a.user_id}`}
                  >
                    <div className="avatar avatar-lg" style={{ background: "linear-gradient(135deg, var(--purple), var(--gold))", width: 48, height: 48, fontSize: 22 }}>{a.emoji || "🎤"}</div>
                    <div style={{ flex: 1 }}>
                      <div className="fw-700 font-serif">{a.stage_name}</div>
                      <div className="text-muted fs-12">{a.category} · 📍 {a.city}</div>
                    </div>
                    <div className="text-gold fs-13 fw-700">★ {(a.rating_avg || 0).toFixed(1)}</div>
                  </div>
                ))}
              </div>
            )}
            <button className="btn btn-ghost btn-block mt-16" onClick={() => { setAlternatives(null); setStep(2); }} data-testid="alt-pick-different-date">Pick a Different Date</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Suggested Artists panel — cross-sell during date-pick step ─────────
function SuggestedArtistsPanel({ artistId, date, cartArtistIds, onOpenAdd }) {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  React.useEffect(() => {
    if (!artistId || !date) return;
    setLoading(true);
    api.get(`/artists/${artistId}/suggested?date_str=${date}&limit=6`)
      .then((r) => setItems(r.data?.suggested || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [artistId, date]);

  if (loading) {
    return <div className="card card-pad mt-16 text-center text-muted fs-13" data-testid="suggested-loading">Finding complementary artists…</div>;
  }
  if (items.length === 0) return null;
  const hasAdd = typeof onOpenAdd === "function";
  return (
    <div className="card card-pad mt-16 suggested-panel" data-testid="suggested-artists">
      <div className="smart-panel-head">
        <span className="smart-panel-icon" style={{ background: "linear-gradient(135deg, #22d3ee, #7c3aed)" }}>✨</span>
        <div>
          <div className="smart-panel-title">Need More Artists for This Event?</div>
          <div className="smart-panel-sub">Available on {date} — add them to the same booking, one checkout, separate contracts.</div>
        </div>
      </div>
      <div className="suggested-grid">
        {items.map((a) => {
          const alreadyInCart = cartArtistIds?.has?.(a.user_id);
          return (
            <div key={a.user_id} className="suggested-card" data-testid={`suggested-${a.user_id}`}>
              <div
                className="suggested-thumb"
                style={a.profile_image ? {
                  background: `linear-gradient(180deg, rgba(0,0,0,0.15), rgba(0,0,0,0.7)), url(${/^https?:\/\//.test(a.profile_image) ? a.profile_image : `${api.defaults.baseURL}/media/${a.profile_image}`}) center/cover`,
                } : {}}
              >
                {!a.profile_image && <span style={{ fontSize: 40 }}>🎤</span>}
              </div>
              <div className="suggested-body">
                <div className="fw-700 fs-13">{a.stage_name}</div>
                <div className="text-muted fs-11">{a.category}</div>
                <div className="suggested-foot">
                  <span className="text-gold fs-12">★ {(a.rating_avg || 0).toFixed(1)}</span>
                  {a.starting_price && <span className="text-gold fw-600 fs-12">{fmtINRFull(a.starting_price)}</span>}
                </div>
                {hasAdd ? (
                  <button
                    type="button"
                    className={`suggested-add-btn ${alreadyInCart ? "added" : ""}`}
                    disabled={alreadyInCart}
                    onClick={() => onOpenAdd(a)}
                    data-testid={`add-to-event-${a.user_id}`}
                    title={alreadyInCart ? "This artist is already in your event cart" : "Add this artist to your event"}
                  >
                    {alreadyInCart ? "✓ Already in your event" : "+ Add to Event"}
                  </button>
                ) : (
                  <a
                    href={`/artist/${a.slug || a.user_id}`}
                    className="suggested-add-btn"
                    data-testid={`view-artist-${a.user_id}`}
                  >View Profile →</a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

