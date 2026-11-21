/* Northcart Seller Hub behaviour. Plain JS; pages keep working without it. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const csrf = () => $('meta[name="csrf-token"]')?.content || "";

  async function post(url, data = {}) {
    const body = data instanceof FormData ? data : Object.entries(data).reduce((fd, [k, v]) => (fd.append(k, v), fd), new FormData());
    const res = await fetch(url, { method: "POST", body, credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf(), "X-Requested-With": "fetch", Accept: "application/json" } });
    let json = {};
    try { json = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) throw new Error(json.error || `Request failed (${res.status})`);
    return json;
  }

  function toast(text, kind = "success") {
    const box = $("[data-toasts]");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.setAttribute("role", "status");
    el.textContent = text;
    box.appendChild(el);
    setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 350); }, 4000);
  }
  const usd = (n) => Number(n || 0).toLocaleString("en-US");
  window.Admin = { post, toast, usd, $, $$ };

  $$("[data-toasts] .toast").forEach((el, i) => setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 350); }, 5000 + i * 400));

  // Sidebar (mobile)
  const side = $("[data-sidebar]"), scrim = $("[data-scrim]");
  const setSide = (open) => { side?.classList.toggle("open", open); if (scrim) scrim.hidden = !open; };
  $("[data-side-toggle]")?.addEventListener("click", () => setSide(!side.classList.contains("open")));
  scrim?.addEventListener("click", () => setSide(false));

  // "/" focuses search
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) {
      e.preventDefault(); $(".top-search input")?.focus();
    }
  });
  // Close user menu on outside click
  document.addEventListener("click", (e) => { $$("details.user-menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; }); });

  // Confirm before destructive submits
  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset?.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });

  // Bulk selection: <form data-bulk> containing [data-check-all] and [data-check] boxes, and a .bulk-bar
  $$("[data-bulk]").forEach((form) => {
    const all = $("[data-check-all]", form);
    const boxes = $$("[data-check]", form);
    const bar = $(".bulk-bar", form);
    const count = $("[data-bulk-count]", form);
    const sync = () => {
      const n = boxes.filter((b) => b.checked).length;
      bar?.classList.toggle("show", n > 0);
      if (count) count.textContent = n;
      if (all) { all.checked = n && n === boxes.length; all.indeterminate = n > 0 && n < boxes.length; }
    };
    all?.addEventListener("change", () => { boxes.forEach((b) => (b.checked = all.checked)); sync(); });
    boxes.forEach((b) => b.addEventListener("change", sync));
    sync();
  });

  // Active toggles in tables
  document.addEventListener("change", async (e) => {
    const t = e.target.closest("[data-toggle-url]");
    if (!t) return;
    try {
      const d = await post(t.dataset.toggleUrl);
      t.checked = d.active;
      toast(d.active ? "Product is live on the store" : "Product hidden from the store", d.active ? "success" : "info");
    } catch (err) { t.checked = !t.checked; toast(err.message, "error"); }
  });

  // Inventory quick adjust: <div data-stock="url"> with [data-step] buttons, input[data-set]
  $$("[data-stock]").forEach((wrap) => {
    const out = $("[data-stock-value]", wrap.closest("tr") || wrap);
    const apply = async (mode, value) => {
      try {
        const d = await post(wrap.dataset.stock, { mode, value });
        if (out) { out.textContent = d.stock; out.className = `stock stock-${d.state}`; }
        const input = $("[data-set]", wrap); if (input) input.value = "";
        toast(`Stock updated to ${d.stock}`);
      } catch (err) { toast(err.message, "error"); }
    };
    $$("[data-step]", wrap).forEach((b) => b.addEventListener("click", () => apply("add", b.dataset.step)));
    $("[data-set-btn]", wrap)?.addEventListener("click", () => {
      const v = $("[data-set]", wrap).value.trim();
      if (v === "") return toast("Enter the new stock level", "warn");
      apply("set", v);
    });
    $("[data-set]", wrap)?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("[data-set-btn]", wrap).click(); } });
  });

  // Character counters: <input data-count="70"> with a sibling .counter
  $$("[data-count]").forEach((el) => {
    const max = +el.dataset.count;
    const c = $(`[data-counter-for="${el.id}"]`);
    const upd = () => { if (!c) return; c.textContent = `${el.value.length}/${max}`; c.classList.toggle("over", el.value.length > max); };
    el.addEventListener("input", upd); upd();
  });

  // ---------- Product form ----------
  const pf = $("[data-product-form]");
  if (pf) {
    const f = (n) => pf.elements[n];
    const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 150);
    let slugTouched = !!f("slug").value;
    f("slug").addEventListener("input", () => { slugTouched = true; });
    f("name").addEventListener("input", () => { if (!slugTouched) f("slug").value = slugify(f("name").value); });

    const margin = $("[data-margin]");
    const updMargin = () => {
      const price = +f("price").value || 0, mrp = +f("mrp").value || 0, cost = +f("cost_price").value || 0;
      if (!margin) return;
      const parts = [];
      if (mrp > price && price) parts.push(`<b>${Math.floor((mrp - price) * 100 / mrp)}% off</b> list price`);
      if (price && cost) {
        const net = price / 1.06; // price includes ~6% sales tax
        const m = ((net - cost) / net) * 100;
        parts.push(`Margin after sales tax: <b class="${m < 15 ? "text-red" : "text-green"}">$${usd(Math.round(net - cost))} (${m.toFixed(1)}%)</b>`);
      }
      margin.innerHTML = parts.join(" · ") || "Enter price, list price and cost to see discount and margin.";
    };
    ["price", "mrp", "cost_price"].forEach((n) => f(n).addEventListener("input", updMargin)); updMargin();

    const prev = $("[data-art-preview]");
    const updArt = () => {
      if (!prev || prev.dataset.hasPhotos) return;
      const q = new URLSearchParams({ kind: f("art_kind").value, color: f("color").value, label: f("brand").value });
      prev.src = "/admin/art-preview?" + q;
    };
    ["art_kind", "color", "brand"].forEach((n) => f(n).addEventListener("input", updArt));

    // Drop zone file list
    const drop = $("[data-drop]");
    if (drop) {
      const input = $("input[type=file]", drop), label = $("[data-drop-label]", drop);
      const show = () => { label.textContent = input.files.length ? `${input.files.length} file(s) ready: ${Array.from(input.files).map((x) => x.name).join(", ")}` : label.dataset.default; };
      input.addEventListener("change", show);
      ["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("drag")));
      drop.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; show(); });
    }

    // AI writer
    const aiBtn = $("[data-ai-describe]");
    aiBtn?.addEventListener("click", async () => {
      const facts = [f("highlights").value, f("specs").value, f("short_description").value].join("\n");
      const cat = f("category_id").selectedOptions[0]?.textContent || "";
      const label = aiBtn.innerHTML;
      aiBtn.disabled = true;
      aiBtn.innerHTML = '<span class="spinner"></span> Writing with ' + (aiBtn.dataset.model || "AI") + "…";
      try {
        const d = await post("/admin/products/ai-describe", { name: f("name").value, brand: f("brand").value, category: cat, facts });
        const fill = (name, value) => { if (!value) return; f(name).value = value; f(name).classList.remove("flash-fill"); void f(name).offsetWidth; f(name).classList.add("flash-fill"); f(name).dispatchEvent(new Event("input")); };
        fill("short_description", d.short_description);
        fill("description", d.description);
        if (d.highlights?.length) fill("highlights", d.highlights.join("\n"));
        fill("seo_title", d.seo_title);
        fill("seo_meta", d.seo_meta);
        toast(`Draft written by ${d.model}. Review it, then save.`);
      } catch (err) { toast(err.message, "error"); }
      finally { aiBtn.disabled = false; aiBtn.innerHTML = label; }
    });
  }
})();
