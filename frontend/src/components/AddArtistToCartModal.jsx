import React, { useEffect, useState, useMemo } from "react";
import api, { mediaUrl, thumbUrl, fmtINRFull } from "../lib/api";

/**
 * Iter 45 — AddArtistToCartModal
 * Lightweight modal that lets the customer pick a package + mandatory add-ons
 * for a SECONDARY artist during the primary booking flow. Fetches the artist's
 * packages + add-ons once, and calls onAdd(cartItem) when the user confirms.
 *
 * cartItem shape returned to parent:
 *   {
 *     artist_id, artist_name, artist_photo, category, city, emoji,
 *     package_id, package_name, package_price,
 *     addon_selections: [{addon_id, quantity, name, price}],
 *     price_subtotal
 *   }
 */
export default function AddArtistToCartModal({ suggestedArtist, onAdd, onClose }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedPkgId, setSelectedPkgId] = useState(null);
  const [addonQty, setAddonQty] = useState({});   // { addon_id: quantity }

  useEffect(() => {
    if (!suggestedArtist?.user_id) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.get(`/artists/${suggestedArtist.user_id}`),
      api.get(`/artists/${suggestedArtist.user_id}/addons`).catch(() => ({ data: [] })),
    ])
      .then(([pr, ar]) => {
        if (cancelled) return;
        const data = { ...pr.data, addons: Array.isArray(ar.data) ? ar.data : (ar.data?.addons || []) };
        setProfile(data);
        // default: cheapest package
        if (data.packages?.length) {
          const cheapest = [...data.packages].sort((a, b) => a.price - b.price)[0];
          setSelectedPkgId(cheapest.id);
        }
        // default: mandatory add-ons pre-checked
        const initQty = {};
        (data.addons || []).forEach((a) => {
          if (a.is_mandatory) initQty[a.id] = 1;
        });
        setAddonQty(initQty);
      })
      .catch((e) => !cancelled && setError("Could not load artist details"))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [suggestedArtist?.user_id]);

  const selectedPkg = useMemo(
    () => profile?.packages?.find((p) => p.id === selectedPkgId),
    [profile, selectedPkgId]
  );

  const addonsTotal = useMemo(() => {
    if (!profile) return 0;
    return (profile.addons || []).reduce((s, a) => s + (addonQty[a.id] ? Number(a.price) * addonQty[a.id] : 0), 0);
  }, [profile, addonQty]);

  const subtotal = (Number(selectedPkg?.price) || 0) + addonsTotal;

  const canConfirm = !!selectedPkg && !loading;

  const toggleAddon = (a) => {
    if (a.is_mandatory) return; // cannot remove mandatory
    setAddonQty((prev) => {
      const next = { ...prev };
      if (next[a.id]) delete next[a.id]; else next[a.id] = 1;
      return next;
    });
  };

  const confirm = () => {
    if (!canConfirm) return;
    const addon_selections = Object.keys(addonQty).map((aid) => {
      const a = profile.addons.find((x) => x.id === aid);
      return { addon_id: aid, quantity: addonQty[aid], name: a?.name, price: a?.price };
    });
    const photoRaw = profile.profile_image;
    const artist_photo = photoRaw
      ? (thumbUrl(photoRaw) || mediaUrl(photoRaw) || (/^https?:\/\//.test(photoRaw) ? photoRaw : null))
      : null;
    onAdd({
      artist_id: suggestedArtist.user_id,
      artist_name: profile.stage_name || suggestedArtist.stage_name,
      artist_photo,
      category: profile.category || suggestedArtist.category,
      city: profile.city || suggestedArtist.city,
      emoji: profile.emoji || "🎤",
      package_id: selectedPkg.id,
      package_name: selectedPkg.name,
      package_price: Number(selectedPkg.price),
      addon_selections,
      price_subtotal: subtotal,
    });
  };

  return (
    <div className="cart-modal-backdrop" onClick={onClose} data-testid="add-artist-modal-backdrop">
      <div className="cart-modal" onClick={(e) => e.stopPropagation()} data-testid="add-artist-modal">
        <button className="cart-modal-close" onClick={onClose} data-testid="add-artist-modal-close" aria-label="Close">×</button>

        <div className="cart-modal-head">
          <div className="cart-modal-thumb">
            {suggestedArtist.profile_image ? (
              <img
                src={/^https?:\/\//.test(suggestedArtist.profile_image) ? suggestedArtist.profile_image : `${api.defaults.baseURL}/media/${suggestedArtist.profile_image}`}
                alt={suggestedArtist.stage_name}
              />
            ) : (
              <span>🎤</span>
            )}
          </div>
          <div>
            <div className="fs-11 text-muted" style={{ letterSpacing: 1, textTransform: "uppercase" }}>Add to your event</div>
            <div className="fs-20 fw-700">{suggestedArtist.stage_name}</div>
            <div className="text-muted fs-12">{suggestedArtist.category}{suggestedArtist.city ? ` · ${suggestedArtist.city}` : ""}</div>
          </div>
        </div>

        {loading && <div className="text-center text-muted fs-13" style={{ padding: 30 }}>Loading packages…</div>}
        {error && <div className="text-center fs-13" style={{ padding: 30, color: "#f87171" }}>{error}</div>}

        {profile && !loading && (
          <>
            <div className="cart-modal-section">
              <div className="cart-modal-section-title">Choose a Package</div>
              <div className="cart-modal-pkg-list">
                {profile.packages?.map((p) => (
                  <label
                    key={p.id}
                    className={`cart-modal-pkg ${selectedPkgId === p.id ? "selected" : ""}`}
                    data-testid={`add-pkg-${p.id}`}
                  >
                    <input
                      type="radio"
                      name="pkg"
                      checked={selectedPkgId === p.id}
                      onChange={() => setSelectedPkgId(p.id)}
                    />
                    <div className="cart-modal-pkg-body">
                      <div className="fw-700 fs-14">{p.name}</div>
                      <div className="text-muted fs-11">{p.duration_hours}h · {p.description || ""}</div>
                    </div>
                    <div className="fw-700 text-gold">{fmtINRFull(p.price)}</div>
                  </label>
                ))}
              </div>
            </div>

            {profile.addons?.length > 0 && (
              <div className="cart-modal-section">
                <div className="cart-modal-section-title">Add-ons</div>
                <div className="cart-modal-addon-list">
                  {profile.addons.map((a) => {
                    const on = !!addonQty[a.id];
                    return (
                      <label
                        key={a.id}
                        className={`cart-modal-addon ${on ? "on" : ""} ${a.is_mandatory ? "mandatory" : ""}`}
                        data-testid={`add-addon-${a.id}`}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggleAddon(a)}
                          disabled={a.is_mandatory}
                        />
                        <div className="cart-modal-addon-body">
                          <div className="fw-600 fs-13">
                            {a.name}
                            {a.is_mandatory && <span className="cart-modal-mandatory-pill">Mandatory</span>}
                          </div>
                          {a.description && <div className="text-muted fs-11">{a.description}</div>}
                        </div>
                        <div className="text-gold fw-600 fs-13">+{fmtINRFull(a.price)}</div>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="cart-modal-total-row">
              <div>
                <div className="text-muted fs-11" style={{ textTransform: "uppercase", letterSpacing: 1 }}>Subtotal</div>
                <div className="fs-22 fw-700 text-gold">{fmtINRFull(subtotal)}</div>
              </div>
              <button
                className="btn btn-gold"
                onClick={confirm}
                disabled={!canConfirm}
                data-testid="add-artist-confirm"
              >
                + Add to Event
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
