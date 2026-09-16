import React, { useEffect, useState } from "react";
import api, { fmtINRFull } from "../../lib/api";

/* ─────────────────────────────────────────────────────────────────
   Master Data — Categories / Cities / Event Types / Languages
   ───────────────────────────────────────────────────────────────── */
export function AdminMaster({ toast }) {
  const EMPTY = { name: "", icon: "", sort_order: 0, active: true,
    hero_image: "", hero_title: "", hero_subtitle: "", hero_cta_label: "", hero_cta_url: "" };
  const [entity, setEntity] = useState("categories");
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null);
  const [showBanner, setShowBanner] = useState(false);
  const supportsBanner = entity === "categories" || entity === "cities";

  const load = () => api.get(`/admin/master/${entity}`).then((r) => setList(r.data));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [entity]);

  const save = async () => {
    if (!form.name.trim()) return toast("Name is required");
    const body = supportsBanner ? form : {
      name: form.name, icon: form.icon, sort_order: form.sort_order, active: form.active,
    };
    if (editing) {
      await api.put(`/admin/master/${entity}/${editing}`, body);
      toast("Updated");
    } else {
      await api.post(`/admin/master/${entity}`, body);
      toast("Added");
    }
    setForm(EMPTY); setEditing(null); setShowBanner(false); load();
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this entry?")) return;
    await api.delete(`/admin/master/${entity}/${id}`);
    toast("Deleted"); load();
  };

  const edit = (item) => {
    setEditing(item.id);
    setForm({
      name: item.name, icon: item.icon || "", sort_order: item.sort_order || 0, active: !!item.active,
      hero_image: item.hero_image || "", hero_title: item.hero_title || "",
      hero_subtitle: item.hero_subtitle || "", hero_cta_label: item.hero_cta_label || "",
      hero_cta_url: item.hero_cta_url || "",
    });
    setShowBanner(!!(item.hero_image || item.hero_title));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const previewHref = (m) => entity === "categories" ? `/artists/${m.slug}` : entity === "cities" ? `/artists/city/${m.slug}` : null;

  return (
    <div className="card" data-testid="admin-master">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center" }}>
        <div className="card-title">🗂️ Master Data</div>
        <select value={entity} onChange={(e) => { setEntity(e.target.value); setForm(EMPTY); setEditing(null); setShowBanner(false); }} className="input" style={{ width: 200 }} data-testid="master-entity-select">
          <option value="categories">Categories</option>
          <option value="cities">Cities</option>
          <option value="event-types">Event Types</option>
          <option value="languages">Languages</option>
        </select>
      </div>
      <div style={{ padding: 14 }}>
        <div className="grid grid-4 gap-12" style={{ marginBottom: 10 }}>
          <input className="input" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="master-name" />
          <input className="input" placeholder="Icon (emoji)" value={form.icon} onChange={(e) => setForm({ ...form, icon: e.target.value })} data-testid="master-icon" />
          <input className="input" type="number" placeholder="Sort order" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: parseInt(e.target.value) || 0 })} data-testid="master-sort" />
          <button className="btn btn-gold" onClick={save} data-testid="master-save">{editing ? "Update" : "+ Add"}</button>
        </div>
        {supportsBanner && (
          <>
            <button className="btn btn-ghost btn-xs" onClick={() => setShowBanner(!showBanner)} data-testid="master-toggle-banner" style={{ marginBottom: 10 }}>
              {showBanner ? "▲ Hide Featured Banner" : "▼ Featured Banner (hero on landing page)"}
            </button>
            {showBanner && (
              <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 8, marginBottom: 12 }}>
                <input className="input mb-8" placeholder="Banner image URL (1600×600)" value={form.hero_image} onChange={(e) => setForm({ ...form, hero_image: e.target.value })} style={{ width: "100%" }} data-testid="master-hero-image" />
                <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
                  <input className="input" placeholder="Banner title" value={form.hero_title} onChange={(e) => setForm({ ...form, hero_title: e.target.value })} data-testid="master-hero-title" />
                  <input className="input" placeholder="Banner subtitle" value={form.hero_subtitle} onChange={(e) => setForm({ ...form, hero_subtitle: e.target.value })} data-testid="master-hero-subtitle" />
                </div>
                <div className="grid grid-2 gap-12">
                  <input className="input" placeholder="CTA label (e.g. Book now)" value={form.hero_cta_label} onChange={(e) => setForm({ ...form, hero_cta_label: e.target.value })} data-testid="master-hero-cta-label" />
                  <input className="input" placeholder="CTA URL" value={form.hero_cta_url} onChange={(e) => setForm({ ...form, hero_cta_url: e.target.value })} data-testid="master-hero-cta-url" />
                </div>
              </div>
            )}
          </>
        )}
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Name</th><th>Slug</th><th>Icon</th><th>Order</th><th>Banner</th><th>Active</th><th>Actions</th></tr></thead>
            <tbody>
              {list.map((m) => (
                <tr key={m.id} data-testid={`master-row-${m.id}`}>
                  <td className="fw-600">{m.name}</td>
                  <td className="text-muted fs-12">{m.slug}</td>
                  <td>{m.icon || "—"}</td>
                  <td>{m.sort_order}</td>
                  <td className="fs-11">
                    {supportsBanner && (m.hero_image || m.hero_title) ? <span className="pill" style={{ background: "linear-gradient(135deg, var(--gold), var(--gold-light))", color: "#000" }}>🖼️ Set</span> : <span className="text-muted">—</span>}
                  </td>
                  <td>{m.active ? <span className="pill pill-green">Yes</span> : <span className="pill pill-amber">No</span>}</td>
                  <td>
                    <button className="btn btn-ghost btn-xs" onClick={() => edit(m)} data-testid={`master-edit-${m.id}`}>Edit</button>
                    {previewHref(m) && <a className="btn btn-ghost btn-xs" href={previewHref(m)} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 6 }} data-testid={`master-view-${m.id}`}>View ↗</a>}
                    <button className="btn btn-red btn-xs" onClick={() => remove(m.id)} style={{ marginLeft: 6 }} data-testid={`master-del-${m.id}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Boost Packages Manager
   ───────────────────────────────────────────────────────────────── */
export function AdminBoost({ toast }) {
  const [tab, setTab] = useState("packages");
  const [packages, setPackages] = useState([]);
  const [subs, setSubs] = useState([]);
  const [form, setForm] = useState({
    name: "", type: "featured_artist", duration_days: 30, price: 1999,
    gst_pct: 18, commission_pct: 0, description: "", active: true,
  });
  const [editing, setEditing] = useState(null);

  const loadPkgs = () => api.get("/admin/boost/packages").then((r) => setPackages(r.data));
  const loadSubs = () => api.get("/admin/boost/subscriptions").then((r) => setSubs(r.data));

  useEffect(() => { loadPkgs(); loadSubs(); }, []);

  const save = async () => {
    if (!form.name.trim()) return toast("Name required");
    if (editing) {
      await api.put(`/admin/boost/packages/${editing}`, form);
      toast("Package updated");
    } else {
      await api.post("/admin/boost/packages", form);
      toast("Package created");
    }
    setForm({ name: "", type: "featured_artist", duration_days: 30, price: 1999, gst_pct: 18, commission_pct: 0, description: "", active: true });
    setEditing(null);
    loadPkgs();
  };

  const edit = (p) => { setEditing(p.id); setForm({ name: p.name, type: p.type, duration_days: p.duration_days, price: p.price, gst_pct: p.gst_pct, commission_pct: p.commission_pct, description: p.description, active: p.active }); };
  const remove = async (id) => { if (!window.confirm("Delete?")) return; await api.delete(`/admin/boost/packages/${id}`); toast("Deleted"); loadPkgs(); };
  const cancelSub = async (id) => { await api.post(`/admin/boost/${id}/cancel`); toast("Cancelled"); loadSubs(); };

  return (
    <div className="card" data-testid="admin-boost">
      <div className="card-head">
        <div className="card-title">🚀 Boost / Promotion Manager</div>
      </div>
      <div className="flex gap-12" style={{ padding: "12px 14px 0" }}>
        <button className={`btn btn-xs ${tab === "packages" ? "btn-gold" : "btn-ghost"}`} onClick={() => setTab("packages")} data-testid="boost-tab-packages">Packages ({packages.length})</button>
        <button className={`btn btn-xs ${tab === "subs" ? "btn-gold" : "btn-ghost"}`} onClick={() => setTab("subs")} data-testid="boost-tab-subs">Active Subscribers ({subs.filter((s) => s.status === "active").length})</button>
      </div>

      {tab === "packages" && (
        <div style={{ padding: 14 }}>
          <div className="grid grid-4 gap-12" style={{ marginBottom: 14 }}>
            <input className="input" placeholder="Package name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="boost-pkg-name" />
            <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} data-testid="boost-pkg-type">
              {["featured_artist", "homepage_banner", "category_top", "search_priority", "premium_badge", "verified_badge", "city_featured", "trending", "recommended"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <input className="input" type="number" placeholder="Days" value={form.duration_days} onChange={(e) => setForm({ ...form, duration_days: parseInt(e.target.value) || 0 })} data-testid="boost-pkg-days" />
            <input className="input" type="number" placeholder="Price ₹" value={form.price} onChange={(e) => setForm({ ...form, price: parseFloat(e.target.value) || 0 })} data-testid="boost-pkg-price" />
            <input className="input" type="number" placeholder="GST %" value={form.gst_pct} onChange={(e) => setForm({ ...form, gst_pct: parseFloat(e.target.value) || 0 })} />
            <input className="input" type="number" placeholder="Commission %" value={form.commission_pct} onChange={(e) => setForm({ ...form, commission_pct: parseFloat(e.target.value) || 0 })} />
            <input className="input" placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <button className="btn btn-gold" onClick={save} data-testid="boost-pkg-save">{editing ? "Update" : "+ Add Package"}</button>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Type</th><th>Days</th><th>Price</th><th>GST</th><th>Active</th><th>Actions</th></tr></thead>
              <tbody>
                {packages.map((p) => (
                  <tr key={p.id} data-testid={`boost-pkg-row-${p.id}`}>
                    <td className="fw-600">{p.name}</td>
                    <td><span className="pill pill-purple">{p.type}</span></td>
                    <td>{p.duration_days}d</td>
                    <td className="text-gold font-serif fw-700">{fmtINRFull(p.price)}</td>
                    <td>{p.gst_pct}%</td>
                    <td>{p.active ? <span className="pill pill-green">Yes</span> : <span className="pill pill-amber">No</span>}</td>
                    <td>
                      <button className="btn btn-ghost btn-xs" onClick={() => edit(p)} data-testid={`boost-edit-${p.id}`}>Edit</button>
                      <button className="btn btn-red btn-xs" onClick={() => remove(p.id)} style={{ marginLeft: 6 }} data-testid={`boost-del-${p.id}`}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "subs" && (
        <div style={{ padding: 14 }}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Artist</th><th>Package</th><th>Type</th><th>Paid</th><th>Status</th><th>Expires</th><th>Actions</th></tr></thead>
              <tbody>
                {subs.map((s) => (
                  <tr key={s.id} data-testid={`boost-sub-${s.id}`}>
                    <td>{s.artist?.name || s.artist_id?.slice(0, 8)}</td>
                    <td>{s.package_snapshot?.name}</td>
                    <td><span className="pill pill-purple">{s.type}</span></td>
                    <td className="text-gold">{fmtINRFull(s.total)}</td>
                    <td><span className={`pill ${s.status === "active" ? "pill-green" : "pill-amber"}`}>{s.status}</span></td>
                    <td className="fs-12 text-muted">{s.expires_at?.slice(0, 10)}</td>
                    <td>{s.status === "active" && <button className="btn btn-red btn-xs" onClick={() => cancelSub(s.id)} data-testid={`boost-cancel-${s.id}`}>Cancel</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Templates editor (email / sms / whatsapp / push / in_app)
   ───────────────────────────────────────────────────────────────── */
export function AdminTemplates({ toast }) {
  const [channel, setChannel] = useState("email");
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ channel: "email", code: "", subject: "", body: "", active: true });

  const load = () => api.get(`/admin/templates?channel=${channel}`).then((r) => setList(r.data));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); setForm({ ...form, channel }); }, [channel]);

  const save = async () => {
    if (!form.code.trim() || !form.body.trim()) return toast("Code & body required");
    await api.post("/admin/templates", form);
    toast("Saved");
    setForm({ channel, code: "", subject: "", body: "", active: true });
    load();
  };

  const edit = (t) => setForm({ channel: t.channel, code: t.code, subject: t.subject || "", body: t.body, active: t.active });
  const remove = async (id) => { await api.delete(`/admin/templates/${id}`); toast("Deleted"); load(); };

  return (
    <div className="card" data-testid="admin-templates">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center" }}>
        <div className="card-title">📧 Notification Templates</div>
        <select value={channel} onChange={(e) => setChannel(e.target.value)} className="input" style={{ width: 180 }} data-testid="tpl-channel">
          {["email", "in_app", "sms", "whatsapp", "push"].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ padding: 14 }}>
        <div className="grid grid-2 gap-12" style={{ marginBottom: 14 }}>
          <input className="input" placeholder="Event code (e.g. booking.confirmed)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} data-testid="tpl-code" />
          <input className="input" placeholder="Subject / Title" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} data-testid="tpl-subject" />
        </div>
        <textarea className="input" placeholder="Body — use {variable} tokens. e.g. Hi {customer_name}, your booking {ref} is confirmed for {event_date}." value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} rows={4} style={{ marginBottom: 12, width: "100%" }} data-testid="tpl-body" />
        <button className="btn btn-gold" onClick={save} data-testid="tpl-save">Save Template</button>

        <div className="table-wrap" style={{ marginTop: 18 }}>
          <table className="table">
            <thead><tr><th>Code</th><th>Subject</th><th>Body Preview</th><th>Active</th><th>Actions</th></tr></thead>
            <tbody>
              {list.map((t) => (
                <tr key={t.id} data-testid={`tpl-row-${t.id}`}>
                  <td className="font-mono fs-12">{t.code}</td>
                  <td>{t.subject || "—"}</td>
                  <td className="fs-12" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis" }}>{t.body}</td>
                  <td>{t.active ? <span className="pill pill-green">Yes</span> : <span className="pill pill-amber">No</span>}</td>
                  <td>
                    <button className="btn btn-ghost btn-xs" onClick={() => edit(t)} data-testid={`tpl-edit-${t.id}`}>Edit</button>
                    <button className="btn btn-red btn-xs" onClick={() => remove(t.id)} style={{ marginLeft: 6 }} data-testid={`tpl-del-${t.id}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   FAQs / CMS / Broadcast / Settings / Audit / Reports
   ───────────────────────────────────────────────────────────────── */
export function AdminFAQs({ toast }) {
  const [list, setList] = useState([]);
  const [form, setForm] = useState({ question: "", answer: "", category: "general", sort_order: 0, active: true, is_featured: false });
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/faqs-v2").then((r) => setList(r.data));
  useEffect(() => { load(); }, []);
  const save = async () => {
    if (!form.question.trim()) return toast("Question required");
    if (editing) await api.put(`/admin/faqs-v2/${editing}`, form); else await api.post("/admin/faqs-v2", form);
    toast("Saved"); setEditing(null); setForm({ question: "", answer: "", category: "general", sort_order: 0, active: true, is_featured: false }); load();
  };
  const edit = (f) => { setEditing(f.id); setForm({ question: f.question, answer: f.answer, category: f.category, sort_order: f.sort_order, active: f.active, is_featured: !!f.is_featured }); };
  const del = async (id) => { if (!window.confirm("Delete FAQ?")) return; await api.delete(`/admin/faqs-v2/${id}`); toast("Deleted"); load(); };
  return (
    <div className="card" data-testid="admin-faqs">
      <div className="card-head">
        <div className="card-title">❓ FAQs ({list.length}) <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— live on the Help Center and Landing page</span></div>
      </div>
      <div style={{ padding: 14 }}>
        <input className="input mb-8" placeholder="Question" value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} data-testid="faq-q" style={{ width: "100%", marginBottom: 8 }} />
        <textarea className="input mb-8" placeholder="Answer" value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} rows={3} data-testid="faq-a" style={{ width: "100%", marginBottom: 8 }} />
        <div className="flex gap-12" style={{ marginBottom: 12, flexWrap: "wrap" }}>
          <input className="input" placeholder="Category (booking, payment, trust…)" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <input className="input" type="number" placeholder="Sort" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: parseInt(e.target.value) || 0 })} style={{ width: 100 }} />
          <label className="flex gap-4" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="faq-active" /> Active
          </label>
          <label className="flex gap-4" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.is_featured} onChange={(e) => setForm({ ...form, is_featured: e.target.checked })} data-testid="faq-featured" /> Featured (show on landing)
          </label>
          <button className="btn btn-gold" onClick={save} data-testid="faq-save">{editing ? "Update" : "+ Add"}</button>
        </div>
        {list.map((f) => (
          <div key={f.id} className="card card-pad mb-12" data-testid={`faq-row-${f.id}`}>
            <div className="fw-600">{f.question}</div>
            <div className="text-muted fs-13 mt-4">{f.answer}</div>
            <div className="mt-8 flex gap-8" style={{ flexWrap: "wrap" }}>
              <span className="pill pill-purple">{f.category}</span>
              {f.is_featured && <span className="pill" style={{ background: "linear-gradient(135deg, var(--gold), var(--gold-light))", color: "#000" }}>★ Featured</span>}
              {!f.active && <span className="pill pill-amber">Inactive</span>}
              <button className="btn btn-ghost btn-xs" onClick={() => edit(f)}>Edit</button>
              <button className="btn btn-red btn-xs" onClick={() => del(f.id)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdminCMS({ toast }) {
  const EMPTY = { slug: "", title: "", body_html: "", meta_description: "", published: true,
    header_menu: false, footer_menu: true, menu_order: 100,
    seo_title: "", seo_keywords: "", og_image: "", canonical: "", schema_json: "",
    hero_image: "", hero_title: "", hero_subtitle: "", hero_cta_label: "", hero_cta_url: "" };
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const load = () => api.get("/admin/cms-v2").then((r) => setList(r.data));
  useEffect(() => { load(); }, []);
  const save = async () => {
    if (!form.slug || !form.title) return toast("Slug & title required");
    try {
      if (editing) await api.put(`/admin/cms-v2/${editing}`, form); else await api.post("/admin/cms-v2", form);
      toast("Saved"); setEditing(null); setForm(EMPTY); setShowAdvanced(false); load();
    } catch (e) { toast(e?.response?.data?.detail || "Save failed", "error"); }
  };
  const edit = (p) => { setEditing(p.id); setForm({ ...EMPTY, ...p }); setShowAdvanced(true); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const del = async (id) => { if (!window.confirm("Delete page?")) return; await api.delete(`/admin/cms-v2/${id}`); toast("Deleted"); load(); };
  const togglePublish = async (p) => {
    await api.put(`/admin/cms-v2/${p.id}`, { ...p, published: !p.published });
    toast(p.published ? "Unpublished" : "Published"); load();
  };
  return (
    <div className="card" data-testid="admin-cms">
      <div className="card-head">
        <div className="card-title">📄 CMS Pages ({list.length}) <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— live on the site under /page/&lt;slug&gt;</span></div>
      </div>
      <div style={{ padding: 14 }}>
        <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
          <input className="input" placeholder="Slug (e.g. about, terms)" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} data-testid="cms-slug" />
          <input className="input" placeholder="Page Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="cms-title" />
        </div>
        <textarea className="input" placeholder="HTML body" rows={8} value={form.body_html} onChange={(e) => setForm({ ...form, body_html: e.target.value })} data-testid="cms-body" style={{ width: "100%", marginBottom: 8, fontFamily: "monospace", fontSize: 13 }} />
        <input className="input" placeholder="Meta description (shown in Google snippets)" value={form.meta_description} onChange={(e) => setForm({ ...form, meta_description: e.target.value })} style={{ width: "100%", marginBottom: 10 }} data-testid="cms-meta-desc" />

        <div className="flex gap-12" style={{ marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
          <label className="flex gap-6" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.published} onChange={(e) => setForm({ ...form, published: e.target.checked })} data-testid="cms-published" /> Published
          </label>
          <label className="flex gap-6" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.header_menu} onChange={(e) => setForm({ ...form, header_menu: e.target.checked })} data-testid="cms-header-menu" /> Header menu
          </label>
          <label className="flex gap-6" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.footer_menu} onChange={(e) => setForm({ ...form, footer_menu: e.target.checked })} data-testid="cms-footer-menu" /> Footer menu
          </label>
          <input className="input" type="number" placeholder="Menu order" value={form.menu_order} onChange={(e) => setForm({ ...form, menu_order: parseInt(e.target.value) || 100 })} style={{ width: 120 }} data-testid="cms-menu-order" />
          <button className="btn btn-ghost btn-xs" onClick={() => setShowAdvanced(!showAdvanced)} data-testid="cms-toggle-advanced">
            {showAdvanced ? "▲ Hide Banner + SEO" : "▼ Banner + Advanced SEO"}
          </button>
        </div>

        {showAdvanced && (
          <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 8, marginBottom: 12 }}>
            <div className="text-muted fs-11 mb-8" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>Featured Banner (hero on this page)</div>
            <input className="input mb-8" placeholder="Hero image URL (1600×600 recommended)" value={form.hero_image} onChange={(e) => setForm({ ...form, hero_image: e.target.value })} style={{ width: "100%" }} data-testid="cms-hero-image" />
            <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
              <input className="input" placeholder="Hero title (defaults to page title)" value={form.hero_title} onChange={(e) => setForm({ ...form, hero_title: e.target.value })} data-testid="cms-hero-title" />
              <input className="input" placeholder="Hero subtitle" value={form.hero_subtitle} onChange={(e) => setForm({ ...form, hero_subtitle: e.target.value })} data-testid="cms-hero-subtitle" />
            </div>
            <div className="grid grid-2 gap-12" style={{ marginBottom: 12 }}>
              <input className="input" placeholder="CTA label (e.g. Contact us)" value={form.hero_cta_label} onChange={(e) => setForm({ ...form, hero_cta_label: e.target.value })} data-testid="cms-hero-cta-label" />
              <input className="input" placeholder="CTA URL (/page/contact or https://…)" value={form.hero_cta_url} onChange={(e) => setForm({ ...form, hero_cta_url: e.target.value })} data-testid="cms-hero-cta-url" />
            </div>

            <div className="text-muted fs-11 mb-8" style={{ textTransform: "uppercase", letterSpacing: 0.5, marginTop: 8 }}>SEO Overrides</div>
            <input className="input mb-8" placeholder="SEO title (browser tab & Google)" value={form.seo_title} onChange={(e) => setForm({ ...form, seo_title: e.target.value })} style={{ width: "100%" }} data-testid="cms-seo-title" />
            <input className="input mb-8" placeholder="SEO keywords (comma-separated)" value={form.seo_keywords} onChange={(e) => setForm({ ...form, seo_keywords: e.target.value })} style={{ width: "100%" }} data-testid="cms-seo-keywords" />
            <input className="input mb-8" placeholder="Open-Graph image URL (1200x630 recommended)" value={form.og_image} onChange={(e) => setForm({ ...form, og_image: e.target.value })} style={{ width: "100%" }} data-testid="cms-og-image" />
            <input className="input mb-8" placeholder="Canonical URL (override auto)" value={form.canonical} onChange={(e) => setForm({ ...form, canonical: e.target.value })} style={{ width: "100%" }} data-testid="cms-canonical" />
            <textarea className="input" rows={3} placeholder="Custom JSON-LD (optional)" value={form.schema_json} onChange={(e) => setForm({ ...form, schema_json: e.target.value })} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} data-testid="cms-schema-json" />
          </div>
        )}

        <button className="btn btn-gold" onClick={save} data-testid="cms-save">{editing ? "Update Page" : "+ Add Page"}</button>
        {editing && <button className="btn btn-ghost" onClick={() => { setEditing(null); setForm(EMPTY); setShowAdvanced(false); }} style={{ marginLeft: 8 }} data-testid="cms-cancel">Cancel</button>}

        <div className="table-wrap" style={{ marginTop: 18 }}>
          <table className="table">
            <thead><tr><th>Slug</th><th>Title</th><th>Menus</th><th>Order</th><th>Published</th><th>Actions</th></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} data-testid={`cms-row-${p.id}`}>
                  <td className="font-mono fs-12">{p.slug}</td>
                  <td>{p.title}</td>
                  <td className="fs-11">
                    {p.header_menu && <span className="pill pill-purple" style={{ marginRight: 4 }}>Header</span>}
                    {p.footer_menu && <span className="pill pill-green">Footer</span>}
                    {!p.header_menu && !p.footer_menu && <span className="text-muted">—</span>}
                  </td>
                  <td className="fs-12">{p.menu_order ?? "—"}</td>
                  <td>
                    <button
                      className={`pill ${p.published ? "pill-green" : "pill-amber"}`}
                      onClick={() => togglePublish(p)}
                      style={{ border: "none", cursor: "pointer" }}
                      data-testid={`cms-toggle-publish-${p.id}`}
                    >{p.published ? "Yes" : "No"}</button>
                  </td>
                  <td>
                    <button className="btn btn-ghost btn-xs" onClick={() => edit(p)} data-testid={`cms-edit-${p.id}`}>Edit</button>
                    <a className="btn btn-ghost btn-xs" href={`/page/${p.slug}`} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 6 }} data-testid={`cms-view-${p.id}`}>View ↗</a>
                    <button className="btn btn-red btn-xs" onClick={() => del(p.id)} style={{ marginLeft: 6 }} data-testid={`cms-delete-${p.id}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function AdminBroadcast({ toast }) {
  // ── Announcements (banner / popup / dashboard bell) ──────────────────
  const EMPTY = { title: "", body: "", audience: "all", channels: ["dashboard"],
    priority: "normal", cta_label: "", cta_url: "", starts_at: "", expires_at: "", active: true };
  const [anns, setAnns] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null);
  const loadAnns = () => api.get("/admin/announcements").then((r) => setAnns(r.data || []));
  useEffect(() => { loadAnns(); }, []);
  const saveAnn = async () => {
    if (!form.title.trim()) return toast("Title required");
    try {
      if (editing) await api.put(`/admin/announcements/${editing}`, form); else await api.post("/admin/announcements", form);
      toast("Saved"); setEditing(null); setForm(EMPTY); loadAnns();
    } catch (e) { toast(e?.response?.data?.detail || "Save failed", "error"); }
  };
  const editAnn = (a) => { setEditing(a.id); setForm({ ...EMPTY, ...a }); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const delAnn = async (id) => { if (!window.confirm("Delete announcement?")) return; await api.delete(`/admin/announcements/${id}`); toast("Deleted"); loadAnns(); };
  const toggleAnnChannel = (c) => setForm({ ...form, channels: form.channels.includes(c) ? form.channels.filter(x => x !== c) : [...form.channels, c] });

  // ── Legacy email/SMS/WhatsApp broadcast (kept for transactional bulk) ─
  const [log, setLog] = useState([]);
  const [ch, setCh] = useState({ audience: "artist", event: "platform.announcement", channels: ["in_app"], title: "", body: "" });
  const loadLog = () => api.get("/admin/notifications/log?limit=50").then((r) => setLog(r.data));
  useEffect(() => { loadLog(); }, []);
  const sendCh = async () => {
    if (!ch.title || !ch.body) return toast("Title & body required");
    const r = await api.post("/admin/notifications/broadcast", ch);
    toast(`Delivered to ${r.data.delivered} users`);
    setCh({ ...ch, title: "", body: "" });
    loadLog();
  };
  const toggleCh = (c) => setCh({ ...ch, channels: ch.channels.includes(c) ? ch.channels.filter((x) => x !== c) : [...ch.channels, c] });

  return (
    <div data-testid="admin-broadcast">
      {/* Announcements section */}
      <div className="card mb-24">
        <div className="card-head">
          <div className="card-title">📣 Site Announcements ({anns.length}) <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— Banner / Popup / Dashboard Bell</span></div>
        </div>
        <div style={{ padding: 14 }}>
          <input className="input" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ width: "100%", marginBottom: 8 }} data-testid="ann-title" />
          <textarea className="input" placeholder="Body (optional)" rows={2} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} style={{ width: "100%", marginBottom: 8 }} data-testid="ann-body" />
          <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
            <input className="input" placeholder="CTA label (e.g. Explore)" value={form.cta_label} onChange={(e) => setForm({ ...form, cta_label: e.target.value })} data-testid="ann-cta-label" />
            <input className="input" placeholder="CTA URL (e.g. /page/careers)" value={form.cta_url} onChange={(e) => setForm({ ...form, cta_url: e.target.value })} data-testid="ann-cta-url" />
          </div>
          <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
            <div>
              <div className="text-muted fs-11 mb-4">Starts at (ISO)</div>
              <input className="input" placeholder="2026-02-20T09:00:00Z" value={form.starts_at || ""} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} data-testid="ann-starts" />
            </div>
            <div>
              <div className="text-muted fs-11 mb-4">Expires at (ISO)</div>
              <input className="input" placeholder="2026-03-01T00:00:00Z" value={form.expires_at || ""} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} data-testid="ann-expires" />
            </div>
          </div>
          <div className="flex gap-12" style={{ marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select className="input" value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })} data-testid="ann-audience">
              {["all","artist","customer","agency","corporate","admin"].map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <select className="input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} data-testid="ann-priority">
              {["low","normal","high","critical"].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <label className="flex gap-4" style={{ alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="ann-active" /> Active
            </label>
          </div>
          <div className="flex gap-8" style={{ marginBottom: 12, flexWrap: "wrap" }}>
            {["banner","popup","dashboard"].map((c) => (
              <button key={c} className={`btn btn-xs ${form.channels.includes(c) ? "btn-gold" : "btn-ghost"}`} onClick={() => toggleAnnChannel(c)} data-testid={`ann-ch-${c}`}>{c}</button>
            ))}
          </div>
          <button className="btn btn-gold" onClick={saveAnn} data-testid="ann-save">{editing ? "Update Announcement" : "+ Publish Announcement"}</button>
          {editing && <button className="btn btn-ghost" onClick={() => { setEditing(null); setForm(EMPTY); }} style={{ marginLeft: 8 }} data-testid="ann-cancel">Cancel</button>}

          <div className="table-wrap" style={{ marginTop: 18 }}>
            <table className="table">
              <thead><tr><th>Title</th><th>Audience</th><th>Channels</th><th>Priority</th><th>Window</th><th>Active</th><th>Actions</th></tr></thead>
              <tbody>
                {anns.length === 0 && <tr><td colSpan={7} className="empty">No announcements yet</td></tr>}
                {anns.map((a) => (
                  <tr key={a.id} data-testid={`ann-row-${a.id}`}>
                    <td>{a.title}</td>
                    <td className="fs-12">{a.audience}</td>
                    <td className="fs-11">{(a.channels || []).join(", ")}</td>
                    <td><span className={`pill ${a.priority === "critical" ? "pill-red" : a.priority === "high" ? "pill-amber" : "pill-purple"}`}>{a.priority}</span></td>
                    <td className="fs-11 text-muted">{(a.starts_at || "").slice(0, 10) || "—"} → {(a.expires_at || "").slice(0, 10) || "∞"}</td>
                    <td>{a.active ? <span className="pill pill-green">Live</span> : <span className="pill pill-amber">Off</span>}</td>
                    <td>
                      <button className="btn btn-ghost btn-xs" onClick={() => editAnn(a)} data-testid={`ann-edit-${a.id}`}>Edit</button>
                      <button className="btn btn-red btn-xs" onClick={() => delAnn(a.id)} style={{ marginLeft: 6 }} data-testid={`ann-del-${a.id}`}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Legacy channel broadcast (Email / SMS / WhatsApp / Push) */}
      <div className="card">
        <div className="card-head"><div className="card-title">📧 Transactional Broadcast (Email / SMS / WhatsApp / Push)</div></div>
        <div style={{ padding: 14 }}>
          <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
            <select className="input" value={ch.audience} onChange={(e) => setCh({ ...ch, audience: e.target.value })} data-testid="bc-audience">
              {["all", "artist", "customer", "agency", "corporate", "admin"].map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <input className="input" placeholder="Event code (e.g. platform.announcement)" value={ch.event} onChange={(e) => setCh({ ...ch, event: e.target.value })} data-testid="bc-event" />
          </div>
          <input className="input" placeholder="Title" value={ch.title} onChange={(e) => setCh({ ...ch, title: e.target.value })} style={{ width: "100%", marginBottom: 8 }} data-testid="bc-title" />
          <textarea className="input" placeholder="Body" rows={3} value={ch.body} onChange={(e) => setCh({ ...ch, body: e.target.value })} style={{ width: "100%", marginBottom: 12 }} data-testid="bc-body" />
          <div className="flex gap-8" style={{ marginBottom: 12 }}>
            {["in_app", "email", "sms", "whatsapp", "push"].map((c) => (
              <button key={c} className={`btn btn-xs ${ch.channels.includes(c) ? "btn-gold" : "btn-ghost"}`} onClick={() => toggleCh(c)} data-testid={`bc-ch-${c}`}>{c}</button>
            ))}
          </div>
          <button className="btn btn-gold" onClick={sendCh} data-testid="bc-send">Send Broadcast</button>

          <h4 className="font-serif mt-24 fs-16 fw-700" style={{ marginTop: 24, marginBottom: 8 }}>Recent Notification Log</h4>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Event</th><th>Channel</th><th>Subject</th><th>Status</th><th>Mode</th></tr></thead>
              <tbody>
                {log.slice(0, 20).map((l) => (
                  <tr key={l.id} data-testid={`bc-log-${l.id}`}>
                    <td className="fs-11 text-muted">{l.created_at?.slice(0, 19).replace("T", " ")}</td>
                    <td className="font-mono fs-11">{l.event}</td>
                    <td><span className="pill pill-purple">{l.channel}</span></td>
                    <td className="fs-12">{l.subject}</td>
                    <td><span className={`pill ${l.status === "sent" ? "pill-green" : "pill-amber"}`}>{l.status}</span></td>
                    <td className="fs-11">{l.mode}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

// Iter 89 — Financial keys have moved to Platform Settings v2 (canonical
// source used by the Financial Engine). We HIDE them from this raw
// key-value editor to prevent admins from setting stale values here and
// wondering why bookings still compute at 18% GST. Legacy reads via
// /settings/public are kept alive by a server-side mirror.
const HIDDEN_LEGACY_SETTINGS = new Set([
  "gst_pct", "platform_fee_pct", "token_pct",
]);

export function AdminSettings({ toast }) {
  const [list, setList] = useState([]);
  const [draft, setDraft] = useState({});
  const load = () => api.get("/admin/settings").then((r) => {
    setList(r.data);
    setDraft({});
  });
  useEffect(() => { load(); }, []);
  const save = async (key) => {
    if (!(key in draft)) return;
    let value = draft[key];
    if (!isNaN(parseFloat(value)) && isFinite(value)) value = parseFloat(value);
    await api.put(`/admin/settings/${key}`, { value });
    toast("Saved"); load();
  };
  // Iter 99 — hide blog_hero_* keys from the generic table since they are now
  // edited via the Blogs tab's "Blog Index Page Banner" card.
  const BLOG_BANNER_KEYS = new Set([
    "blog_hero_image", "blog_hero_title", "blog_hero_subtitle",
    "blog_hero_cta_label", "blog_hero_cta_url",
  ]);
  const visible = (list || []).filter((s) => !HIDDEN_LEGACY_SETTINGS.has(s.key) && !BLOG_BANNER_KEYS.has(s.key));
  return (
    <div data-testid="admin-settings">
      {/* Iter 89 — pointer banner so nobody edits GST here anymore */}
      <div className="card card-pad mb-16" style={{ background: "rgba(212,175,55,0.06)", border: "1px solid rgba(212,175,55,0.2)" }}>
        <div className="fw-700 mb-4">💡 Looking for GST / Platform Fee / Payment Schedule?</div>
        <div className="text-muted fs-13">
          Those are now managed in <b>🏗️ Platform Settings (v2)</b> — the canonical source used by
          the Financial Engine. This page keeps only copy/CMS-style key-value settings.
        </div>
      </div>
      {/* Iter 99 — pointer for blog banner */}
      <div className="card card-pad mb-16" style={{ background: "rgba(155,89,182,0.06)", border: "1px solid rgba(155,89,182,0.2)" }}>
        <div className="fw-700 mb-4">🖼️ Looking for the Blog Banner?</div>
        <div className="text-muted fs-13">
          Blog Index Page banner + per-article banners are now managed under <b>📝 Blogs</b> in the sidebar.
        </div>
      </div>

      <div className="card">
        <div className="card-head"><div className="card-title">📢 Site Notices & Misc Copy <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— shown on booking/checkout, footer, help pages</span></div></div>
        <div style={{ padding: 14 }}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Key</th><th>Current Value</th><th>New Value</th><th>Actions</th></tr></thead>
              <tbody>
                {visible.map((s) => (
                  <tr key={s.key} data-testid={`set-row-${s.key}`}>
                    <td className="font-mono fs-12">{s.key}</td>
                    <td className="text-gold" style={{ maxWidth: 240, wordBreak: "break-all" }}>{String(s.value)}</td>
                    <td><input className="input" defaultValue={s.value} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })} data-testid={`set-input-${s.key}`} /></td>
                    <td><button className="btn btn-gold btn-xs" onClick={() => save(s.key)} data-testid={`set-save-${s.key}`}>Save</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AdminAudit() {
  const [list, setList] = useState([]);
  const [filters, setFilters] = useState({ actor: "", action: "", entity: "", start: "", end: "" });
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "300" });
      if (filters.actor) params.set("actor", filters.actor);
      if (filters.action) params.set("action", filters.action);
      if (filters.entity) params.set("entity", filters.entity);
      if (filters.start) params.set("start", filters.start);
      if (filters.end) params.set("end", filters.end);
      const r = await api.get(`/admin/audit-logs/unified?${params.toString()}`);
      setList(r.data.items || []);
    } catch { /* leave empty */ }
    setLoading(false);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  return (
    <div className="card" data-testid="admin-audit">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title">🛡️ Audit Logs ({list.length})</div>
        <div className="flex gap-8" style={{ flexWrap: "wrap" }}>
          <input className="input" placeholder="Actor (email or id)" value={filters.actor}
            onChange={(e) => setFilters({ ...filters, actor: e.target.value })}
            data-testid="audit-filter-actor" style={{ width: 180 }} />
          <input className="input" placeholder="Action (regex)" value={filters.action}
            onChange={(e) => setFilters({ ...filters, action: e.target.value })}
            data-testid="audit-filter-action" style={{ width: 160 }} />
          <input className="input" placeholder="Entity" value={filters.entity}
            onChange={(e) => setFilters({ ...filters, entity: e.target.value })}
            data-testid="audit-filter-entity" style={{ width: 130 }} />
          <input className="input" type="date" value={filters.start}
            onChange={(e) => setFilters({ ...filters, start: e.target.value })}
            data-testid="audit-filter-start" title="Start date" />
          <input className="input" type="date" value={filters.end}
            onChange={(e) => setFilters({ ...filters, end: e.target.value })}
            data-testid="audit-filter-end" title="End date" />
          <button className="btn btn-gold btn-sm" onClick={load} data-testid="audit-filter-apply">Filter</button>
          <button className="btn btn-ghost btn-sm" onClick={() => { setFilters({ actor: "", action: "", entity: "", start: "", end: "" }); setTimeout(load, 50); }}
            data-testid="audit-filter-clear">Clear</button>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time</th><th>Source</th><th>Actor</th><th>Action</th><th>Entity</th><th>Entity ID</th><th>IP</th></tr></thead>
          <tbody>
            {loading && <tr><td colSpan="7" className="text-muted text-center pad-16">Loading…</td></tr>}
            {!loading && list.length === 0 && <tr><td colSpan="7" className="text-muted text-center pad-16">No audit entries match your filters</td></tr>}
            {list.map((a, i) => (
              <tr key={i} data-testid={`audit-row-${i}`}>
                <td className="fs-11 text-muted">{(a.at || "").slice(0, 19).replace("T", " ")}</td>
                <td><span className={`pill pill-${a.source === "admin" ? "gold" : "green"}`} style={{ fontSize: 10 }}>{a.source}</span></td>
                <td className="fs-12">{a.actor_email || (a.actor_id || "").slice(0, 8)}</td>
                <td className="font-mono fs-12">{a.action}</td>
                <td>{a.entity || "—"}</td>
                <td className="fs-11 text-muted">{(a.entity_id || "").slice(0, 12)}</td>
                <td className="fs-11 text-muted">{a.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AdminReports() {
  const [subtab, setSubtab] = useState("revenue");
  const [days, setDays] = useState(30);
  const [revenue, setRevenue] = useState(null);
  const [top, setTop] = useState([]);
  // Iter 87 — new report data slots
  const [artistBookings, setArtistBookings] = useState(null);
  const [managerLeads, setManagerLeads] = useState(null);
  const [waivers, setWaivers] = useState(null);
  const [range, setRange] = useState({ start: "", end: "" });

  const load = () => {
    api.get(`/admin/reports/revenue?days=${days}`).then((r) => setRevenue(r.data)).catch(() => {});
    api.get(`/admin/reports/top-artists?limit=10`).then((r) => setTop(r.data)).catch(() => {});
  };
  const loadArtistBookings = () => {
    const qs = new URLSearchParams();
    if (range.start) qs.set("start", range.start);
    if (range.end) qs.set("end", range.end);
    api.get(`/admin/reports/artist-bookings?${qs}`).then((r) => setArtistBookings(r.data)).catch(() => {});
  };
  const loadManagerLeads = () => {
    api.get(`/admin/reports/manager-leads`).then((r) => setManagerLeads(r.data)).catch(() => {});
  };
  const loadWaivers = () => {
    const qs = new URLSearchParams();
    if (range.start) qs.set("start", range.start);
    if (range.end) qs.set("end", range.end);
    api.get(`/admin/reports/platform-waivers?${qs}`).then((r) => setWaivers(r.data)).catch(() => {});
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [days]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (subtab === "artist-bookings") loadArtistBookings();
    if (subtab === "manager-leads") loadManagerLeads();
    if (subtab === "waivers") loadWaivers();
  }, [subtab]);

  const downloadCsv = async (endpoint, filename) => {
    const qs = new URLSearchParams({ format: "csv" });
    if (range.start) qs.set("start", range.start);
    if (range.end) qs.set("end", range.end);
    try {
      const r = await api.get(`${endpoint}?${qs.toString()}`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) { /* silent */ }
  };

  return (
    <div className="card" data-testid="admin-reports">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title">📈 Reports & Analytics</div>
        {subtab === "revenue" && (
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))} className="input" style={{ width: 160 }} data-testid="rep-days">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last year</option>
          </select>
        )}
        {(subtab === "artist-bookings" || subtab === "waivers") && (
          <div className="flex gap-8">
            <input className="input" type="date" value={range.start}
              onChange={(e) => setRange({ ...range, start: e.target.value })}
              data-testid="rep-range-start" title="Event date from" />
            <input className="input" type="date" value={range.end}
              onChange={(e) => setRange({ ...range, end: e.target.value })}
              data-testid="rep-range-end" title="Event date to" />
            <button className="btn btn-gold btn-sm" data-testid="rep-range-apply"
              onClick={() => { if (subtab === "artist-bookings") loadArtistBookings(); else loadWaivers(); }}>
              Apply
            </button>
          </div>
        )}
      </div>

      <div className="flex gap-8 pad-16" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", flexWrap: "wrap" }}>
        <button className={`btn btn-sm ${subtab === "revenue" ? "btn-gold" : "btn-ghost"}`}
          onClick={() => setSubtab("revenue")} data-testid="rep-tab-revenue">💰 Revenue</button>
        <button className={`btn btn-sm ${subtab === "artist-bookings" ? "btn-gold" : "btn-ghost"}`}
          onClick={() => setSubtab("artist-bookings")} data-testid="rep-tab-artist-bookings">🎤 Artist Bookings</button>
        <button className={`btn btn-sm ${subtab === "manager-leads" ? "btn-gold" : "btn-ghost"}`}
          onClick={() => setSubtab("manager-leads")} data-testid="rep-tab-manager-leads">👤 Manager Leads</button>
        <button className={`btn btn-sm ${subtab === "waivers" ? "btn-gold" : "btn-ghost"}`}
          onClick={() => setSubtab("waivers")} data-testid="rep-tab-waivers">🎁 Platform Waivers</button>
      </div>

      <div style={{ padding: 14 }}>
        {subtab === "revenue" && (
          <>
            {revenue && (
              <div className="kpi-grid mb-24">
                <div className="kpi"><div className="kpi-num text-gold">{fmtINRFull(revenue.gmv)}</div><div className="kpi-label">Marketplace GMV<br/><span className="fs-10 text-muted">(artist fees — informational)</span></div></div>
                <div className="kpi"><div className="kpi-num text-gold">{fmtINRFull(revenue.platform_revenue)}</div><div className="kpi-label">Platform Service Revenue<br/><span className="fs-10 text-muted">(BookTalent net earnings)</span></div></div>
                <div className="kpi"><div className="kpi-num text-gold">{fmtINRFull(revenue.gst_collected || 0)}</div><div className="kpi-label">GST Collected</div></div>
                <div className="kpi"><div className="kpi-num text-gold">{fmtINRFull(revenue.boost_revenue)}</div><div className="kpi-label">Boost Revenue</div></div>
                <div className="kpi"><div className="kpi-num text-gold">{fmtINRFull(revenue.net_revenue || (revenue.platform_revenue + revenue.boost_revenue))}</div><div className="kpi-label">Net BookTalent Revenue</div></div>
                <div className="kpi"><div className="kpi-num">{revenue.bookings}</div><div className="kpi-label">Bookings</div></div>
              </div>
            )}
            <h4 className="font-serif fs-16 fw-700" style={{ marginBottom: 12 }}>Top Artists by Revenue</h4>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>#</th><th>Artist</th><th>Category</th><th>City</th><th>Bookings</th><th>Revenue</th></tr></thead>
                <tbody>
                  {top.map((t, i) => (
                    <tr key={t.artist_id} data-testid={`rep-artist-${t.artist_id}`}>
                      <td className="fw-700">{i + 1}</td>
                      <td>{t.stage_name}</td>
                      <td>{t.category}</td>
                      <td>{t.city}</td>
                      <td>{t.bookings}</td>
                      <td className="text-gold font-serif fw-700">{fmtINRFull(t.revenue || 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {subtab === "artist-bookings" && (
          <div data-testid="rep-artist-bookings-view">
            <div className="flex-between mb-16">
              <div className="text-muted fs-13">
                {artistBookings ? `${artistBookings.count} artists · ${artistBookings.totals?.bookings || 0} bookings · GMV ${fmtINRFull(artistBookings.totals?.gross_revenue || 0)}` : "Loading…"}
              </div>
              <button className="btn btn-ghost btn-sm" data-testid="rep-csv-artist-bookings"
                onClick={() => downloadCsv("/admin/reports/artist-bookings", "artist_bookings.csv")}>
                ⬇ Download CSV
              </button>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>#</th><th>Artist</th><th>Email</th><th>Bookings</th><th>Gross Revenue</th><th>Artist Payable</th><th>Platform Fee</th><th>GST</th><th>Paid</th><th>Pending</th></tr></thead>
                <tbody>
                  {(artistBookings?.items || []).map((t, i) => (
                    <tr key={t.artist_id} data-testid={`rep-ab-row-${t.artist_id}`}>
                      <td className="fw-700">{i + 1}</td>
                      <td>{t.artist_name}</td>
                      <td className="fs-11 text-muted">{t.artist_email}</td>
                      <td>{t.bookings_count}</td>
                      <td className="text-gold font-serif fw-700">{fmtINRFull(t.gross_revenue)}</td>
                      <td>{fmtINRFull(t.artist_payable)}</td>
                      <td>{fmtINRFull(t.platform_fee)}</td>
                      <td>{fmtINRFull(t.gst)}</td>
                      <td className="text-green">{t.paid_count}</td>
                      <td className="text-gold">{t.pending_payout_count}</td>
                    </tr>
                  ))}
                  {artistBookings && artistBookings.items.length === 0 && (
                    <tr><td colSpan="10" className="text-muted text-center pad-16">No bookings in selected range</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {subtab === "manager-leads" && (
          <div data-testid="rep-manager-leads-view">
            <div className="flex-between mb-16">
              <div className="text-muted fs-13">
                {managerLeads ? `${managerLeads.count} managers · 12-stage pipeline` : "Loading…"}
              </div>
              <button className="btn btn-ghost btn-sm" data-testid="rep-csv-manager-leads"
                onClick={() => downloadCsv("/admin/reports/manager-leads", "manager_leads.csv")}>
                ⬇ Download CSV
              </button>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>#</th><th>Manager</th><th>Email</th><th>Total</th><th>Won</th><th>Lost</th><th>In Pipeline</th><th>Conversion %</th></tr></thead>
                <tbody>
                  {(managerLeads?.items || []).map((m, i) => (
                    <tr key={m.manager_id} data-testid={`rep-ml-row-${m.manager_id}`}>
                      <td className="fw-700">{i + 1}</td>
                      <td>{m.manager_name || "—"}</td>
                      <td className="fs-11 text-muted">{m.manager_email}</td>
                      <td className="fw-700">{m.total_leads}</td>
                      <td className="text-green">{m.won}</td>
                      <td className="text-red">{m.lost}</td>
                      <td className="text-gold">{m.in_pipeline}</td>
                      <td className="fw-700">{m.conversion_pct}%</td>
                    </tr>
                  ))}
                  {managerLeads && managerLeads.items.length === 0 && (
                    <tr><td colSpan="8" className="text-muted text-center pad-16">No managers configured</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {subtab === "waivers" && (
          <div data-testid="rep-waivers-view">
            <div className="flex-between mb-16">
              <div className="text-muted fs-13">
                {waivers ? `${waivers.count} bookings · Total waived: ${fmtINRFull(waivers.totals?.waived_amount || 0)}` : "Loading…"}
              </div>
              <button className="btn btn-ghost btn-sm" data-testid="rep-csv-waivers"
                onClick={() => downloadCsv("/admin/reports/platform-waivers", "platform_waivers.csv")}>
                ⬇ Download CSV
              </button>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Ref</th><th>Event Date</th><th>Artist</th><th>Customer</th><th>Service Artist?</th><th>Gross Total</th><th>Actual Fee</th><th>Would-be Fee</th><th>Waived</th></tr></thead>
                <tbody>
                  {(waivers?.items || []).map((w) => (
                    <tr key={w.booking_id} data-testid={`rep-w-row-${w.booking_id}`}>
                      <td className="font-mono fs-11">{w.ref}</td>
                      <td>{w.event_date}</td>
                      <td>{w.artist_name}</td>
                      <td className="fs-12">{w.customer_name}</td>
                      <td>{w.is_service_artist ? "✓" : "—"}</td>
                      <td>{fmtINRFull(w.gross_total)}</td>
                      <td>{fmtINRFull(w.actual_platform_fee)}</td>
                      <td className="text-muted">{fmtINRFull(w.would_be_platform_fee)}</td>
                      <td className="text-gold font-serif fw-700">{fmtINRFull(w.waived_amount)}</td>
                    </tr>
                  ))}
                  {waivers && waivers.items.length === 0 && (
                    <tr><td colSpan="9" className="text-muted text-center pad-16">No platform fee waivers in selected range</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Reviews Moderation
   ───────────────────────────────────────────────────────────────── */
export function AdminReviewsModeration({ toast }) {
  const [status, setStatus] = useState("pending");
  const [list, setList] = useState([]);
  const load = () => api.get(`/admin/reviews?status=${status}`).then((r) => setList(r.data));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [status]);

  const decide = async (rid, decision) => {
    let reason = "";
    if (decision === "reject") {
      reason = window.prompt("Reason for rejection (will be sent to customer):", "") || "";
      if (!reason.trim()) { toast("Reason required", "error"); return; }
    }
    try {
      await api.post(`/admin/reviews/${rid}/moderate`, { decision, reason });
      toast(`Review ${decision === "approve" ? "approved" : "rejected"}`);
      load();
    } catch (e) { toast(e?.response?.data?.detail || "Failed", "error"); }
  };

  const pendingCount = list.length;

  return (
    <div className="card" data-testid="admin-reviews-mod">
      <div className="card-head" style={{ justifyContent: "space-between", display: "flex", alignItems: "center" }}>
        <div className="card-title">🛡️ Reviews Moderation ({pendingCount})</div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="input" style={{ width: 200 }} data-testid="review-status-filter">
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="all">All</option>
        </select>
      </div>
      <div style={{ padding: 14 }}>
        {list.length === 0 && <div className="empty"><div className="empty-icon">🛡️</div><div className="empty-title">No reviews to moderate</div></div>}
        {list.map((r) => (
          <div key={r.id} className="card card-pad mb-12" style={{ marginBottom: 12 }} data-testid={`review-${r.id}`}>
            <div className="flex items-center" style={{ justifyContent: "space-between" }}>
              <div>
                <div className="fw-700">★ {r.rating} — {r.customer_name}</div>
                <div className="text-muted fs-12">Artist: {r.artist_stage_name || r.artist_id?.slice(0, 8)} · {r.created_at?.slice(0, 10)} · <span className={`pill pill-${r.moderated === "approved" ? "green" : r.moderated === "rejected" ? "red" : "amber"}`}>{r.moderated}</span></div>
              </div>
              {r.moderated === "pending" && (
                <div className="flex gap-8">
                  <button className="btn btn-green btn-sm" onClick={() => decide(r.id, "approve")} data-testid={`approve-rv-${r.id}`}>✓ Approve</button>
                  <button className="btn btn-red btn-sm" onClick={() => decide(r.id, "reject")} data-testid={`reject-rv-${r.id}`}>✕ Reject</button>
                </div>
              )}
            </div>
            <div className="mt-8 fs-13" style={{ marginTop: 8 }}>{r.text}</div>
            {(r.photos?.length > 0 || r.videos?.length > 0) && (
              <div className="grid grid-4 gap-12 mt-12" style={{ marginTop: 12 }}>
                {(r.photos || []).map((mid) => (
                  <a key={mid} href={`${api.defaults.baseURL}/media/${mid}`} target="_blank" rel="noreferrer">
                    <img src={`${api.defaults.baseURL}/media/${mid}/thumb`} alt="" style={{ width: "100%", borderRadius: 8 }} />
                  </a>
                ))}
                {(r.videos || []).map((mid) => (
                  <video key={mid} src={`${api.defaults.baseURL}/media/${mid}`} controls style={{ width: "100%", borderRadius: 8 }} />
                ))}
              </div>
            )}
            {r.moderation_reason && <div className="text-muted fs-12 mt-8" style={{ marginTop: 8 }}>Reason: {r.moderation_reason}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Providers — status + test hooks
   ───────────────────────────────────────────────────────────────── */
export function AdminProviders({ toast }) {
  const [status, setStatus] = useState(null);
  const [test, setTest] = useState({ provider: "sms", to: "", message: "BookTalent test ping" });
  const [result, setResult] = useState(null);

  const load = () => api.get("/admin/providers/status").then((r) => setStatus(r.data));
  useEffect(() => { load(); }, []);

  const send = async () => {
    if (!test.to.trim()) return toast("Recipient required", "error");
    try {
      const r = await api.post(`/admin/providers/test/${test.provider}`, { to: test.to, message: test.message });
      setResult(r.data);
      toast(r.data.status === "sent" ? "✓ Sent live" : r.data.status === "mocked" ? "Mock (no keys set)" : "Failed");
    } catch (e) { toast(e?.response?.data?.detail || "Failed", "error"); }
  };

  const providers = status ? [
    { key: "email_resend", label: "📧 Email (Resend)", info: "RESEND_API_KEY" },
    { key: "sms_twilio", label: "📱 SMS (Twilio)", info: "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM" },
    { key: "whatsapp_gupshup", label: "💬 WhatsApp (Gupshup/Meta)", info: "WHATSAPP_TOKEN, WHATSAPP_FROM" },
    { key: "push_fcm", label: "🔔 Push (FCM)", info: "FCM_SERVER_KEY" },
    { key: "easebuzz", label: "💳 Payments (Easebuzz)", info: "Configured from Admin → Payment Settings" },
    { key: "stripe", label: "💳 Payments (Stripe)", info: "STRIPE_SECRET_KEY" },
  ] : [];

  return (
    <div className="card" data-testid="admin-providers">
      <div className="card-head"><div className="card-title">🔌 Provider Integrations</div></div>
      <div style={{ padding: 14 }}>
        <p className="text-muted fs-13 mb-12">Each provider auto-activates when its environment variables are present in <code>/app/backend/.env</code>. No code change required.</p>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Provider</th><th>Status</th><th>Required ENV Keys</th></tr></thead>
            <tbody>
              {providers.map((p) => (
                <tr key={p.key} data-testid={`prov-${p.key}`}>
                  <td className="fw-700">{p.label}</td>
                  <td>{status[p.key].live
                    ? <span className="pill pill-green" data-testid={`prov-${p.key}-status`}>● Live</span>
                    : <span className="pill pill-amber" data-testid={`prov-${p.key}-status`}>○ Mock (no key)</span>}</td>
                  <td className="text-muted fs-11">{p.info}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h4 className="font-serif mt-24 fs-16 fw-700" style={{ marginTop: 24, marginBottom: 8 }}>Send Test Message</h4>
        <div className="grid grid-3 gap-12" style={{ marginBottom: 12 }}>
          <select className="input" value={test.provider} onChange={(e) => setTest({ ...test, provider: e.target.value })} data-testid="prov-test-channel">
            <option value="sms">SMS</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="push">Push</option>
          </select>
          <input className="input" placeholder={test.provider === "push" ? "FCM token" : "+91xxxxxxxxxx"} value={test.to} onChange={(e) => setTest({ ...test, to: e.target.value })} data-testid="prov-test-to" />
          <input className="input" placeholder="Message" value={test.message} onChange={(e) => setTest({ ...test, message: e.target.value })} data-testid="prov-test-msg" />
        </div>
        <button className="btn btn-gold" onClick={send} data-testid="prov-test-send">Send Test</button>
        {result && (
          <pre className="card card-pad mt-12 fs-12" style={{ marginTop: 12, background: "var(--glass)" }}>{JSON.stringify(result, null, 2)}</pre>
        )}
      </div>
    </div>
  );
}



// ═══════════════════════════════════════════════════════════════════════
// Blogs — admin CRUD with per-article featured banner (Iter 41)
// + Global /blog index page banner (moved here from Site Notices in Iter 99)
// ═══════════════════════════════════════════════════════════════════════
export function AdminBlogs({ toast }) {
  const EMPTY = {
    title: "", slug: "", content: "", cover_image: "", excerpt: "", author: "",
    tags: [], published: true,
    hero_image: "", hero_title: "", hero_subtitle: "", hero_cta_label: "", hero_cta_url: "",
  };
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null);
  const [showBanner, setShowBanner] = useState(false);
  const [tagInput, setTagInput] = useState("");

  // Global /blog index page banner — stored as key/value on /admin/settings.
  const [indexBanner, setIndexBanner] = useState({
    blog_hero_image: "", blog_hero_title: "", blog_hero_subtitle: "",
    blog_hero_cta_label: "", blog_hero_cta_url: "",
  });
  const [indexBannerBusy, setIndexBannerBusy] = useState(false);

  const load = () => api.get("/admin/blogs").then((r) => setList(r.data)).catch(() => setList([]));
  const loadIndexBanner = () => api.get("/admin/settings").then((r) => {
    const map = Object.fromEntries((r.data || []).map((s) => [s.key, s.value]));
    setIndexBanner({
      blog_hero_image: map.blog_hero_image || "",
      blog_hero_title: map.blog_hero_title || "",
      blog_hero_subtitle: map.blog_hero_subtitle || "",
      blog_hero_cta_label: map.blog_hero_cta_label || "",
      blog_hero_cta_url: map.blog_hero_cta_url || "",
    });
  }).catch(() => {});
  useEffect(() => { load(); loadIndexBanner(); }, []);

  const saveIndexBanner = async () => {
    setIndexBannerBusy(true);
    try {
      for (const [k, v] of Object.entries(indexBanner)) {
        await api.put(`/admin/settings/${k}`, { value: v });
      }
      toast("Blog index banner saved");
    } catch (e) { toast(e?.response?.data?.detail || "Save failed", "error"); }
    setIndexBannerBusy(false);
  };

  const save = async () => {
    if (!form.title.trim() || !form.slug.trim()) return toast("Title & slug required");
    try {
      if (editing) await api.put(`/admin/blogs/${editing}`, form);
      else await api.post("/admin/blogs", form);
      toast("Saved"); setEditing(null); setForm(EMPTY); setShowBanner(false); setTagInput(""); load();
    } catch (e) { toast(e?.response?.data?.detail || "Save failed", "error"); }
  };
  const edit = (b) => {
    setEditing(b.id);
    setForm({ ...EMPTY, ...b, tags: b.tags || [] });
    setShowBanner(!!(b.hero_image || b.hero_title));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const del = async (id) => {
    if (!window.confirm("Delete this blog article?")) return;
    await api.delete(`/admin/blogs/${id}`); toast("Deleted"); load();
  };
  const togglePublish = async (b) => {
    await api.put(`/admin/blogs/${b.id}`, { ...b, published: !b.published });
    toast(b.published ? "Unpublished" : "Published"); load();
  };
  const addTag = () => {
    const t = tagInput.trim();
    if (t && !form.tags.includes(t)) setForm({ ...form, tags: [...form.tags, t] });
    setTagInput("");
  };
  const removeTag = (t) => setForm({ ...form, tags: form.tags.filter((x) => x !== t) });

  return (
    <div data-testid="admin-blogs-wrap">
      {/* Global /blog index page banner — Iter 99 consolidation */}
      <div className="card mb-16" data-testid="blog-index-banner-card">
        <div className="card-head">
          <div className="card-title">🖼️ Blog Index Page Banner <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— hero shown at the top of /blog</span></div>
        </div>
        <div style={{ padding: 14 }}>
          <input className="input mb-8" placeholder="Banner image URL (1600×600 recommended)" value={indexBanner.blog_hero_image} onChange={(e) => setIndexBanner({ ...indexBanner, blog_hero_image: e.target.value })} style={{ width: "100%" }} data-testid="blog-index-hero-image" />
          <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
            <input className="input" placeholder="Banner title" value={indexBanner.blog_hero_title} onChange={(e) => setIndexBanner({ ...indexBanner, blog_hero_title: e.target.value })} data-testid="blog-index-hero-title" />
            <input className="input" placeholder="Banner subtitle" value={indexBanner.blog_hero_subtitle} onChange={(e) => setIndexBanner({ ...indexBanner, blog_hero_subtitle: e.target.value })} data-testid="blog-index-hero-subtitle" />
          </div>
          <div className="grid grid-2 gap-12" style={{ marginBottom: 12 }}>
            <input className="input" placeholder="CTA label (e.g. Subscribe)" value={indexBanner.blog_hero_cta_label} onChange={(e) => setIndexBanner({ ...indexBanner, blog_hero_cta_label: e.target.value })} data-testid="blog-index-hero-cta-label" />
            <input className="input" placeholder="CTA URL" value={indexBanner.blog_hero_cta_url} onChange={(e) => setIndexBanner({ ...indexBanner, blog_hero_cta_url: e.target.value })} data-testid="blog-index-hero-cta-url" />
          </div>
          <button className="btn btn-gold" onClick={saveIndexBanner} disabled={indexBannerBusy} data-testid="blog-index-hero-save">
            {indexBannerBusy ? "Saving…" : "Save Index Banner"}
          </button>
          <a className="btn btn-ghost" href="/blog" target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8 }} data-testid="blog-index-hero-preview">Preview /blog ↗</a>
          <div className="text-muted fs-11" style={{ marginTop: 10 }}>
            👇 Per-article banners are set below by editing each blog post.
          </div>
        </div>
      </div>

      <div className="card" data-testid="admin-blogs">
        <div className="card-head">
          <div className="card-title">📝 Blogs ({list.length}) <span className="text-muted fs-11" style={{ marginLeft: 8 }}>— live on /blog & /blog/&lt;slug&gt;</span></div>
        </div>
      <div style={{ padding: 14 }}>
        <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
          <input className="input" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="blog-title" />
          <input className="input" placeholder="Slug (e.g. how-to-book-a-singer)" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} data-testid="blog-slug" />
        </div>
        <input className="input mb-8" placeholder="Author (defaults to BookTalent Editorial)" value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })} style={{ width: "100%" }} data-testid="blog-author" />
        <input className="input mb-8" placeholder="Cover image URL" value={form.cover_image} onChange={(e) => setForm({ ...form, cover_image: e.target.value })} style={{ width: "100%" }} data-testid="blog-cover" />
        <input className="input mb-8" placeholder="Excerpt (short teaser)" value={form.excerpt} onChange={(e) => setForm({ ...form, excerpt: e.target.value })} style={{ width: "100%" }} data-testid="blog-excerpt" />
        <textarea className="input" rows={8} placeholder="HTML content" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} style={{ width: "100%", marginBottom: 8, fontFamily: "monospace", fontSize: 13 }} data-testid="blog-content" />

        <div className="flex gap-8" style={{ alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <input className="input" placeholder="Add a tag & press Enter" value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} data-testid="blog-tag-input" style={{ maxWidth: 220 }} />
          {form.tags.map((t) => (
            <span key={t} className="pill pill-purple" style={{ cursor: "pointer" }} onClick={() => removeTag(t)} data-testid={`blog-tag-${t}`}>#{t} ×</span>
          ))}
        </div>

        <div className="flex gap-12" style={{ marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
          <label className="flex gap-6" style={{ alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={form.published} onChange={(e) => setForm({ ...form, published: e.target.checked })} data-testid="blog-published" /> Published
          </label>
          <button className="btn btn-ghost btn-xs" onClick={() => setShowBanner(!showBanner)} data-testid="blog-toggle-banner">
            {showBanner ? "▲ Hide Featured Banner" : "▼ Featured Banner for this article"}
          </button>
        </div>

        {showBanner && (
          <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 8, marginBottom: 12 }}>
            <input className="input mb-8" placeholder="Banner image URL (1600×600)" value={form.hero_image} onChange={(e) => setForm({ ...form, hero_image: e.target.value })} style={{ width: "100%" }} data-testid="blog-hero-image" />
            <div className="grid grid-2 gap-12" style={{ marginBottom: 8 }}>
              <input className="input" placeholder="Banner title (defaults to article title)" value={form.hero_title} onChange={(e) => setForm({ ...form, hero_title: e.target.value })} data-testid="blog-hero-title" />
              <input className="input" placeholder="Banner subtitle" value={form.hero_subtitle} onChange={(e) => setForm({ ...form, hero_subtitle: e.target.value })} data-testid="blog-hero-subtitle" />
            </div>
            <div className="grid grid-2 gap-12">
              <input className="input" placeholder="CTA label" value={form.hero_cta_label} onChange={(e) => setForm({ ...form, hero_cta_label: e.target.value })} data-testid="blog-hero-cta-label" />
              <input className="input" placeholder="CTA URL" value={form.hero_cta_url} onChange={(e) => setForm({ ...form, hero_cta_url: e.target.value })} data-testid="blog-hero-cta-url" />
            </div>
          </div>
        )}

        <button className="btn btn-gold" onClick={save} data-testid="blog-save">{editing ? "Update Article" : "+ Add Article"}</button>
        {editing && <button className="btn btn-ghost" onClick={() => { setEditing(null); setForm(EMPTY); setShowBanner(false); setTagInput(""); }} style={{ marginLeft: 8 }} data-testid="blog-cancel">Cancel</button>}

        <div className="table-wrap" style={{ marginTop: 18 }}>
          <table className="table">
            <thead><tr><th>Title</th><th>Slug</th><th>Author</th><th>Banner</th><th>Published</th><th>Actions</th></tr></thead>
            <tbody>
              {list.map((b) => (
                <tr key={b.id} data-testid={`blog-row-${b.id}`}>
                  <td className="fw-600">{b.title}</td>
                  <td className="font-mono fs-11">{b.slug}</td>
                  <td className="fs-12">{b.author || "—"}</td>
                  <td className="fs-11">{(b.hero_image || b.hero_title) ? <span className="pill" style={{ background: "linear-gradient(135deg, var(--gold), var(--gold-light))", color: "#000" }}>🖼️ Set</span> : <span className="text-muted">—</span>}</td>
                  <td>
                    <button className={`pill ${b.published ? "pill-green" : "pill-amber"}`} onClick={() => togglePublish(b)} style={{ border: "none", cursor: "pointer" }} data-testid={`blog-toggle-publish-${b.id}`}>
                      {b.published ? "Yes" : "No"}
                    </button>
                  </td>
                  <td>
                    <button className="btn btn-ghost btn-xs" onClick={() => edit(b)} data-testid={`blog-edit-${b.id}`}>Edit</button>
                    <a className="btn btn-ghost btn-xs" href={`/blog/${b.slug}`} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 6 }} data-testid={`blog-view-${b.id}`}>View ↗</a>
                    <button className="btn btn-red btn-xs" onClick={() => del(b.id)} style={{ marginLeft: 6 }} data-testid={`blog-delete-${b.id}`}>Delete</button>
                  </td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={6} className="empty">No blog articles yet. Add one above.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </div>
  );
}
