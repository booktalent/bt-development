import React, { useEffect, useRef, useState } from "react";
import api, { formatApiError, mediaUrl } from "../lib/api";
import { useToast } from "../lib/toast";

/**
 * 5-step Artist Onboarding Wizard.
 * Renders as a full-screen overlay on top of /artist when status.completed === false.
 * Auto-resumes from the next incomplete step.
 */
export default function OnboardingWizard({ user, onComplete, onClose }) {
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  const [basics, setBasics] = useState({ stage_name: "", category: "", city: "", phone: "" });
  const [branding, setBranding] = useState({ bio: "", languages: "", experience_years: 0 });
  const [pkg, setPkg] = useState({ name: "Standard Set", price: 50000, duration: "2 hours", features: ["Acoustic setup", "20 songs"] });
  const [availDate, setAvailDate] = useState("");
  const [profileImg, setProfileImg] = useState(null);
  const [coverImg, setCoverImg] = useState(null);
  const [galleryFiles, setGalleryFiles] = useState([]);
  const profileRef = useRef();
  const coverRef = useRef();
  const galleryRef = useRef();

  useEffect(() => { reload(); }, []);

  const reload = async () => {
    const r = await api.get("/onboarding/me");
    setStatus(r.data);
    if (r.data.required && !r.data.completed) setStep(r.data.current_step || r.data.next_step || 1);
    // Pre-fill basics
    const me = await api.get("/auth/me");
    const p = me.data.artist_profile || {};
    setBasics({
      stage_name: p.stage_name || `${me.data.first_name} ${me.data.last_name || ""}`.trim(),
      category: p.category || "",
      city: p.city || "",
      phone: me.data.phone || "",
    });
    setBranding({
      bio: p.bio || "",
      languages: (p.languages || []).join(", "),
      experience_years: p.experience_years || 0,
    });
  };

  const fileToDataUrl = (f) => new Promise((r) => { const x = new FileReader(); x.onload = () => r(x.result); x.readAsDataURL(f); });

  const saveStep1 = async () => {
    if (!basics.stage_name || !basics.category || !basics.city) { toast("Please fill all fields", "error"); return; }
    setBusy(true);
    try {
      await api.put("/users/me", {
        phone: basics.phone, stage_name: basics.stage_name,
        category: basics.category, city: basics.city, onboarding_step: 2,
      });
      toast("Saved");
      setStep(2);
      reload();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const saveStep2 = async () => {
    setBusy(true);
    try {
      if (profileImg) {
        const du = await fileToDataUrl(profileImg);
        await api.post("/media/upload", { type: "profile", data_url: du, title: "Profile" });
      }
      if (coverImg) {
        const du = await fileToDataUrl(coverImg);
        await api.post("/media/upload", { type: "cover", data_url: du, title: "Cover" });
      }
      await api.put("/users/me", {
        bio: branding.bio,
        languages: branding.languages.split(",").map(s => s.trim()).filter(Boolean),
        experience_years: Number(branding.experience_years) || 0,
        onboarding_step: 3,
      });
      toast("Branding saved");
      setStep(3);
      reload();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const saveStep3 = async () => {
    if (galleryFiles.length === 0 && !(status?.checks?.step3_media)) {
      toast("Upload at least one media item", "error"); return;
    }
    setBusy(true);
    try {
      for (const f of galleryFiles) {
        if (f.size > 100 * 1024 * 1024) { toast(`${f.name} too large (max 100MB)`, "error"); continue; }
        const du = await fileToDataUrl(f);
        const isVideo = f.type.startsWith("video/");
        await api.post("/media/upload", { type: isVideo ? "video" : "gallery", data_url: du, title: f.name });
      }
      await api.put("/users/me", { onboarding_step: 4 });
      toast("Portfolio uploaded");
      setStep(4);
      reload();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const saveStep4 = async () => {
    if (!pkg.name || !pkg.price) { toast("Fill package details", "error"); return; }
    setBusy(true);
    try {
      // Only create if no packages yet
      const existing = await api.get("/packages/mine");
      if (existing.data.length === 0) {
        await api.post("/packages", {
          name: pkg.name, price: Number(pkg.price), duration: pkg.duration,
          features: pkg.features, is_popular: true,
        });
      }
      await api.put("/users/me", { onboarding_step: 5 });
      toast("Package saved");
      setStep(5);
      reload();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const saveStep5 = async () => {
    setBusy(true);
    try {
      if (availDate) await api.post("/availability", { date: availDate, status: "available" });
      await api.post("/onboarding/complete");
      toast("Profile is live! 🎉");
      onComplete?.();
    } catch (e) { toast(formatApiError(e), "error"); }
    setBusy(false);
  };

  const skip = async () => {
    await api.post("/onboarding/complete");
    onComplete?.();
  };

  // Iter 91 — Persistent dismiss without marking onboarding as complete.
  // Sets seen_welcome_at so it doesn't auto-open again; artist can still
  // return to it from the KYC/Profile tab.
  const dismiss = () => {
    onClose?.();
  };

  if (!status || !status.required || status.completed) return null;

  return (
    <div className="modal-bg" style={{ alignItems: "flex-start", paddingTop: "5vh" }} data-testid="onboarding-wizard">
      <div className="modal-card" style={{ maxWidth: 720, width: "100%", padding: 0 }}>
        <div style={{ padding: "24px 28px", borderBottom: "1px solid var(--glass-border)" }}>
          <div className="flex justify-between items-center mb-12">
            <div className="font-serif fs-20 fw-700">Welcome to <span className="text-gold">BookTalent</span></div>
            <div className="flex gap-8">
              <button className="btn btn-ghost btn-xs" onClick={skip} data-testid="wiz-skip">Skip for now</button>
              <button className="btn btn-ghost btn-xs" onClick={dismiss} data-testid="wiz-dismiss" title="Close and don't show again on next login">×</button>
            </div>
          </div>
          <div className="text-muted fs-13">Get booking-ready in 5 quick steps · Step {step} of 5</div>
          <div className="steps mt-12" style={{ marginBottom: 0 }}>
            {[1, 2, 3, 4, 5].map((n, i) => (
              <React.Fragment key={n}>
                <div className="step-node">
                  <div className={`step-circle ${step === n ? "active" : step > n ? "done" : ""}`} style={{ width: 30, height: 30, fontSize: 12 }}>
                    {step > n ? "✓" : n}
                  </div>
                </div>
                {i < 4 && <div className={`step-line ${step > n ? "done" : ""}`} style={{ width: 40 }} />}
              </React.Fragment>
            ))}
          </div>
        </div>

        <div style={{ padding: 28 }}>
          {step === 1 && (
            <div data-testid="wiz-step-1">
              <div className="font-serif fs-20 fw-700 mb-8">Basic Information</div>
              <div className="text-muted fs-13 mb-20">Let's start with the basics.</div>
              <div className="field">
                <div className="field-label">Stage Name *</div>
                <input className="field-input" value={basics.stage_name} onChange={(e) => setBasics({ ...basics, stage_name: e.target.value })} data-testid="wiz-stage-name" />
              </div>
              <div className="field-row">
                <div className="field">
                  <div className="field-label">Category *</div>
                  <select
                    className="field-input"
                    value={basics.category === "__other__" ? "__other__" : (["Bollywood Vocalist","Classical Vocalist","DJ / Music Producer","Stand-up Comedian","Anchor / Emcee","Dancer / Troupe","Live Band","Magician","Folk Artist"].includes(basics.category) ? basics.category : (basics.category ? "__other__" : ""))}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "__other__") setBasics({ ...basics, category: "__other__" });
                      else setBasics({ ...basics, category: v });
                    }}
                    data-testid="wiz-category"
                  >
                    <option value="">Select…</option>
                    <option>Bollywood Vocalist</option><option>Classical Vocalist</option>
                    <option>DJ / Music Producer</option><option>Stand-up Comedian</option>
                    <option>Anchor / Emcee</option><option>Dancer / Troupe</option>
                    <option>Live Band</option><option>Magician</option><option>Folk Artist</option>
                    <option value="__other__">Other (specify below)</option>
                  </select>
                  {(basics.category === "__other__" || (basics.category && !["Bollywood Vocalist","Classical Vocalist","DJ / Music Producer","Stand-up Comedian","Anchor / Emcee","Dancer / Troupe","Live Band","Magician","Folk Artist"].includes(basics.category))) && (
                    <input
                      className="field-input mt-8"
                      placeholder="Enter your category (e.g. Beatboxer)"
                      value={basics.category === "__other__" ? "" : basics.category}
                      onChange={(e) => setBasics({ ...basics, category: e.target.value })}
                      data-testid="wiz-category-other"
                      autoFocus
                    />
                  )}
                </div>
                <div className="field">
                  <div className="field-label">Primary City *</div>
                  <select className="field-input" value={basics.city} onChange={(e) => setBasics({ ...basics, city: e.target.value })} data-testid="wiz-city">
                    <option value="">Select…</option>
                    <option>Mumbai</option><option>Delhi NCR</option><option>Bangalore</option>
                    <option>Chennai</option><option>Hyderabad</option><option>Kolkata</option><option>Pune</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <div className="field-label">Mobile</div>
                <input className="field-input" value={basics.phone} onChange={(e) => setBasics({ ...basics, phone: e.target.value })} data-testid="wiz-phone" />
              </div>
              <button className="btn btn-gold btn-block" onClick={saveStep1} disabled={busy} data-testid="wiz-next-1">
                {busy ? "Saving…" : "Continue →"}
              </button>
            </div>
          )}

          {step === 2 && (
            <div data-testid="wiz-step-2">
              <div className="font-serif fs-20 fw-700 mb-8">Profile Branding</div>
              <div className="text-muted fs-13 mb-20">Make your profile stand out.</div>
              <div className="grid grid-2 mb-16">
                <div className="upload-zone" data-testid="wiz-profile-zone" onClick={() => profileRef.current?.click()} style={{ padding: 20 }}>
                  <input ref={profileRef} type="file" accept="image/*" onChange={(e) => setProfileImg(e.target.files[0])} />
                  <div className="upload-zone-icon">👤</div>
                  <div className="fs-13 fw-600">Profile Picture</div>
                  <div className="text-muted fs-11">{profileImg ? `✓ ${profileImg.name}` : "Click to upload"}</div>
                </div>
                <div className="upload-zone" data-testid="wiz-cover-zone" onClick={() => coverRef.current?.click()} style={{ padding: 20 }}>
                  <input ref={coverRef} type="file" accept="image/*" onChange={(e) => setCoverImg(e.target.files[0])} />
                  <div className="upload-zone-icon">🖼️</div>
                  <div className="fs-13 fw-600">Cover Banner</div>
                  <div className="text-muted fs-11">{coverImg ? `✓ ${coverImg.name}` : "Click to upload"}</div>
                </div>
              </div>
              <div className="field">
                <div className="field-label">Bio</div>
                <textarea className="field-input" rows={4} value={branding.bio} onChange={(e) => setBranding({ ...branding, bio: e.target.value })} placeholder="Tell event planners what makes you special…" data-testid="wiz-bio" />
              </div>
              <div className="field-row">
                <div className="field">
                  <div className="field-label">Languages (comma-separated)</div>
                  <input className="field-input" value={branding.languages} onChange={(e) => setBranding({ ...branding, languages: e.target.value })} placeholder="Hindi, English, Punjabi" data-testid="wiz-languages" />
                </div>
                <div className="field">
                  <div className="field-label">Years of Experience</div>
                  <input type="number" className="field-input" value={branding.experience_years} onChange={(e) => setBranding({ ...branding, experience_years: e.target.value })} data-testid="wiz-exp" />
                </div>
              </div>
              <div className="flex gap-12">
                <button className="btn btn-ghost" onClick={() => setStep(1)} data-testid="wiz-back-2">← Back</button>
                <button className="btn btn-gold" style={{ flex: 1 }} onClick={saveStep2} disabled={busy} data-testid="wiz-next-2">
                  {busy ? "Saving…" : "Continue →"}
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div data-testid="wiz-step-3">
              <div className="font-serif fs-20 fw-700 mb-8">Media Portfolio</div>
              <div className="text-muted fs-13 mb-20">Upload performance photos, videos, and clips. Max 12 MB per file (local storage).</div>
              <div className="upload-zone mb-16" data-testid="wiz-gallery-zone" onClick={() => galleryRef.current?.click()} style={{ padding: 30 }}>
                <input ref={galleryRef} type="file" multiple accept="image/*,video/*" onChange={(e) => setGalleryFiles(Array.from(e.target.files))} />
                <div className="upload-zone-icon">📁</div>
                <div className="fs-14 fw-600 mb-4">Drop files here or click to browse</div>
                <div className="text-muted fs-12">{galleryFiles.length ? `${galleryFiles.length} file(s) selected` : "Bulk upload supported · Up to 12 MB each"}</div>
              </div>
              <div className="flex gap-12">
                <button className="btn btn-ghost" onClick={() => setStep(2)} data-testid="wiz-back-3">← Back</button>
                <button className="btn btn-gold" style={{ flex: 1 }} onClick={saveStep3} disabled={busy} data-testid="wiz-next-3">
                  {busy ? "Uploading…" : status?.checks?.step3_media ? "Skip & Continue →" : "Upload & Continue →"}
                </button>
              </div>
            </div>
          )}

          {step === 4 && (
            <div data-testid="wiz-step-4">
              <div className="font-serif fs-20 fw-700 mb-8">Your Starting Package</div>
              <div className="text-muted fs-13 mb-20">Create your most popular offering. You can add more packages later.</div>
              <div className="field">
                <div className="field-label">Package Name</div>
                <input className="field-input" value={pkg.name} onChange={(e) => setPkg({ ...pkg, name: e.target.value })} data-testid="wiz-pkg-name" />
              </div>
              <div className="field-row">
                <div className="field">
                  <div className="field-label">Price (₹)</div>
                  <input type="number" className="field-input" value={pkg.price} onChange={(e) => setPkg({ ...pkg, price: e.target.value })} data-testid="wiz-pkg-price" />
                </div>
                <div className="field">
                  <div className="field-label">Duration</div>
                  <input className="field-input" value={pkg.duration} onChange={(e) => setPkg({ ...pkg, duration: e.target.value })} data-testid="wiz-pkg-duration" />
                </div>
              </div>
              <div className="field">
                <div className="field-label">What's Included (one per line)</div>
                <textarea className="field-input" rows={4} value={pkg.features.join("\n")} onChange={(e) => setPkg({ ...pkg, features: e.target.value.split("\n").filter(Boolean) })} data-testid="wiz-pkg-features" />
              </div>
              <div className="flex gap-12">
                <button className="btn btn-ghost" onClick={() => setStep(3)} data-testid="wiz-back-4">← Back</button>
                <button className="btn btn-gold" style={{ flex: 1 }} onClick={saveStep4} disabled={busy} data-testid="wiz-next-4">
                  {busy ? "Saving…" : "Continue →"}
                </button>
              </div>
            </div>
          )}

          {step === 5 && (
            <div data-testid="wiz-step-5">
              <div className="font-serif fs-20 fw-700 mb-8">Mark Your Availability</div>
              <div className="text-muted fs-13 mb-20">Add at least one available date. You can fully manage your calendar in the dashboard.</div>
              <div className="field">
                <div className="field-label">Next Available Date</div>
                <input type="date" className="field-input" value={availDate} onChange={(e) => setAvailDate(e.target.value)} data-testid="wiz-avail-date" />
                <div className="field-hint">Tip: mark next weekend so you're discoverable for upcoming events.</div>
              </div>
              <div className="card card-pad mb-16" style={{ background: "rgba(212,175,55,0.08)" }}>
                <div className="fs-13 fw-700 text-gold mb-8">🎉 You're almost done!</div>
                <div className="text-muted fs-12">
                  After this step, your profile will go live and be searchable by 68,000+ event planners across India.
                </div>
              </div>
              <div className="flex gap-12">
                <button className="btn btn-ghost" onClick={() => setStep(4)} data-testid="wiz-back-5">← Back</button>
                <button className="btn btn-gold" style={{ flex: 1 }} onClick={saveStep5} disabled={busy} data-testid="wiz-finish">
                  {busy ? "Activating…" : "Go Live ✨"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
