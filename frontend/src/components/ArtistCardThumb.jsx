import React, { useEffect, useMemo, useRef, useState } from "react";
import { thumbUrl, mediaUrl } from "../lib/api";

/**
 * Dynamic, database-driven rotating thumbnail for an artist card.
 *
 *  • Pulls images from `artist.gallery_thumbs` (array of {id, is_featured}).
 *  • Featured image is shown first, then the remaining gallery images rotate
 *    every 3.5s with a crossfade.
 *  • Single image → static (no rotation).
 *  • Pauses while the user hovers the card.
 *  • Preloads the next image to avoid flicker.
 *  • Only ticks while the card is visible (IntersectionObserver) so we can
 *    render hundreds of cards on a page without a memory/CPU hit.
 *  • Falls back to profile_image → cover_image → `placeholder` text (e.g. emoji).
 *
 * The wrapper preserves the existing `.artist-card-cover` styling exactly —
 * we only swap what's inside it.
 */
export default function ArtistCardThumb({
  artist,
  className = "artist-card-cover",
  placeholder = null,
  interval = 3500,
  children, // overlay content (e.g. boost tags)
}) {
  // Build ordered image URL list — featured first, deduped to guard against
  // backend returning the same media id twice in gallery_thumbs.
  const images = useMemo(() => {
    const out = [];
    const seen = new Set();
    const push = (u) => {
      if (!u || seen.has(u)) return;
      seen.add(u);
      out.push(u);
    };
    const thumbs = artist?.gallery_thumbs || [];
    const featured = thumbs.find((t) => t.is_featured);
    const others = thumbs.filter((t) => !t.is_featured);
    if (featured) push(thumbUrl(featured.id));
    others.forEach((t) => push(thumbUrl(t.id)));
    if (out.length === 0) {
      if (artist?.profile_image) push(thumbUrl(artist.profile_image));
      else if (artist?.cover_image) push(mediaUrl(artist.cover_image));
    }
    return out;
  }, [artist]);

  const [idx, setIdx] = useState(0);
  const [hover, setHover] = useState(false);
  const [visible, setVisible] = useState(false);
  const rootRef = useRef(null);

  // IntersectionObserver — only tick visible cards
  useEffect(() => {
    if (!rootRef.current) return;
    const obs = new IntersectionObserver(
      (entries) => entries.forEach((e) => setVisible(e.isIntersecting)),
      { rootMargin: "120px" }
    );
    obs.observe(rootRef.current);
    return () => obs.disconnect();
  }, []);

  // Rotation
  useEffect(() => {
    if (images.length < 2 || hover || !visible) return;
    const t = setInterval(() => {
      setIdx((i) => (i + 1) % images.length);
    }, interval);
    return () => clearInterval(t);
  }, [images.length, hover, visible, interval]);

  // Preload next image
  useEffect(() => {
    if (images.length < 2) return;
    const next = images[(idx + 1) % images.length];
    if (!next) return;
    const im = new Image();
    im.src = next;
  }, [idx, images]);

  // Render
  if (images.length === 0) {
    return (
      <div ref={rootRef} className={className}>
        {placeholder}
        {children}
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className={className}
      style={{ position: "relative", overflow: "hidden", fontSize: 0 }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      data-testid="artist-thumb-rotator"
    >
      {images.map((src, i) => (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            opacity: i === idx ? 1 : 0,
            transition: "opacity 700ms ease-in-out",
            zIndex: i === idx ? 2 : 1,
          }}
        />
      ))}
      {children && (
        <div style={{ position: "absolute", inset: 0, zIndex: 5, pointerEvents: "none" }}>
          {children}
        </div>
      )}
      {images.length > 1 && (
        <div
          aria-hidden
          style={{
            position: "absolute",
            bottom: 8, left: 0, right: 0,
            display: "flex", justifyContent: "center", gap: 4,
            zIndex: 6,
          }}
        >
          {images.map((img, i) => (
            <span
              key={img?.id || img?.url || img?.src || `dot-${i}`}
              style={{
                width: i === idx ? 18 : 6,
                height: 4,
                borderRadius: 4,
                background: i === idx ? "rgba(255,255,255,.9)" : "rgba(255,255,255,.35)",
                transition: "width 400ms ease, background 400ms ease",
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
