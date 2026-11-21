/* Northcart storefront behaviour. Plain JS, progressive enhancement: every form works without it. */
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const csrf = () => $('meta[name="csrf-token"]')?.content || "";

  /** POST helper: sends FormData/object with CSRF header, returns parsed JSON. */
  async function post(url, data = {}) {
    const body = data instanceof FormData ? data : Object.entries(data).reduce((fd, [k, v]) => (fd.append(k, v), fd), new FormData());
    const res = await fetch(url, {
      method: "POST",
      body,
      headers: { "X-CSRF-Token": csrf(), "X-Requested-With": "fetch", Accept: "application/json" },
      credentials: "same-origin",
    });
    let json = {};
    try { json = await res.json(); } catch { /* non-JSON */ }
    if (res.status === 401 && json.login) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      throw new Error("login required");
    }
    if (!res.ok) throw new Error(json.error || "Something went wrong. Please try again.");
    return json;
  }

  /** Show a toast message. kind: success | error | info | warn */
  function toast(text, kind = "success") {
    const stack = $("[data-toasts]");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.setAttribute("role", "status");
    el.textContent = text;
    stack.appendChild(el);
    setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 350); }, 3500);
  }

  function setCartCount(n) {
    $$("[data-cart-count]").forEach((el) => {
      el.textContent = n;
      el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
    });
  }

  // Expose for page scripts.
  window.Northcart = { post, toast, setCartCount, $, $$ };

  // Auto-hide server flash toasts.
  $$("[data-toasts] .toast").forEach((el, i) => setTimeout(() => { el.classList.add("hide"); setTimeout(() => el.remove(), 350); }, 4500 + i * 400));

  // Add to cart (any form with data-add-to-cart). "Buy now" buttons carry name=buy_now and go to checkout.
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-add-to-cart]");
    if (!form) return;
    const submitter = e.submitter;
    if (submitter && submitter.name === "buy_now") return; // let it navigate
    e.preventDefault();
    const btn = submitter || $("button[type=submit]", form);
    const label = btn?.textContent;
    if (btn) { btn.disabled = true; btn.textContent = "Adding…"; }
    try {
      const data = await post(form.action, new FormData(form));
      setCartCount(data.count);
      toast(data.message || "Added to cart");
      if (btn) btn.textContent = "✓ Added";
      setTimeout(() => { if (btn) { btn.textContent = label; btn.disabled = false; } }, 1400);
    } catch (err) {
      toast(err.message, "error");
      if (btn) { btn.textContent = label; btn.disabled = false; }
    }
  });

  // Wishlist hearts. The body carries data-wishlist="1,5,9" with the user's saved product ids.
  const savedIds = new Set((document.body.dataset.wishlist || "").split(",").filter(Boolean));
  $$("[data-wishlist]").forEach((b) => b.classList.toggle("saved", savedIds.has(b.dataset.wishlist)));
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-wishlist]");
    if (!btn || btn === document.body) return;
    e.preventDefault();
    try {
      const data = await post("/wishlist/toggle", { product_id: btn.dataset.wishlist });
      $$(`[data-wishlist="${btn.dataset.wishlist}"]`).forEach((b) => b.classList.toggle("saved", data.saved));
      toast(data.saved ? "Saved to your wishlist" : "Removed from wishlist", data.saved ? "success" : "info");
    } catch (err) { if (err.message !== "login required") toast(err.message, "error"); }
  });

  // Search suggestions.
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const input = $("[data-suggest]");
  const box = $("[data-suggest-box]");
  if (input && box) {
    let timer, active = -1;
    const close = () => { box.hidden = true; active = -1; };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) return close();
      timer = setTimeout(async () => {
        const res = await fetch("/api/suggest?q=" + encodeURIComponent(q));
        const data = await res.json();
        if (!data.items?.length) return close();
        box.innerHTML = data.items.map((it) =>
          `<a href="${esc(it.url)}"><img src="${esc(it.thumb)}" alt=""><span>${esc(it.name)}</span><span class="s-price">$${esc(it.price)}</span></a>`
        ).join("") + `<a href="/search?q=${encodeURIComponent(q)}"><span>See all results for “<b>${esc(q)}</b>”</span></a>`;
        box.hidden = false;
      }, 160);
    });
    input.addEventListener("keydown", (e) => {
      const links = $$("a", box);
      if (box.hidden || !links.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
        links.forEach((l, i) => l.classList.toggle("active", i === active));
      } else if (e.key === "Enter" && active >= 0) {
        e.preventDefault(); location.href = links[active].href;
      } else if (e.key === "Escape") close();
    });
    document.addEventListener("click", (e) => { if (!e.target.closest(".search")) close(); });
  }

  // Mobile category menu.
  $("[data-menu-toggle]")?.addEventListener("click", () => $("[data-menu]")?.classList.toggle("open"));

  // Delivery ZIP code (kept in the browser; used for delivery estimates).
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage blocked */ } },
  };
  const pinLabel = $("[data-zip-label]");
  const dialog = $("[data-zip-dialog]");
  const showPin = (pin, city) => { if (pinLabel && pin) pinLabel.textContent = city ? `${city} ${pin}` : pin; };
  if (store.get("northcart_zip_code")) showPin(store.get("northcart_zip_code"), store.get("northcart_city"));
  $$("[data-zip-open]").forEach((b) => b.addEventListener("click", () => dialog?.showModal()));
  $("[data-zip-apply]")?.addEventListener("click", async (e) => {
    e.preventDefault();
    const form = $("[data-zip-form]");
    const pin = form.zip_code.value.trim();
    const out = $("[data-zip-result]");
    if (!/^[0-9]{5}(-[0-9]{4})?$/.test(pin)) { out.textContent = "Please enter a valid 5-digit ZIP code."; out.className = "small text-red"; return; }
    try {
      const data = await (await fetch("/api/delivery?zip_code=" + pin)).json();
      store.set("northcart_zip_code", pin);
      store.set("northcart_city", data.city || "");
      showPin(pin, data.city);
      document.dispatchEvent(new CustomEvent("northcart:zip_code", { detail: { zip_code: pin, ...data } }));
      dialog.close();
      toast(`Delivering to ${pin}: ${data.message}`, "info");
    } catch { out.textContent = "Could not check this ZIP code."; }
  });
})();

/* Page helpers shared by several storefront pages. */
(() => {
  "use strict";
  const { $, $$, toast } = window.Northcart;

  // Horizontal shelves: arrow buttons scroll the track by roughly one screen.
  $$(".shelf").forEach((shelf) => {
    const track = $("[data-scroller]", shelf);
    if (!track) return;
    const update = () => {
      const max = track.scrollWidth - track.clientWidth - 4;
      $(".shelf-nav.prev", shelf)?.toggleAttribute("hidden", track.scrollLeft <= 4);
      $(".shelf-nav.next", shelf)?.toggleAttribute("hidden", track.scrollLeft >= max);
    };
    $$("[data-scroll]", shelf).forEach((b) => b.addEventListener("click", () => {
      track.scrollBy({ left: Number(b.dataset.scroll) * track.clientWidth * 0.85, behavior: "smooth" });
    }));
    track.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  });

  // Deal countdown to a fixed ISO time.
  $$("[data-countdown]").forEach((el) => {
    const end = new Date(el.dataset.countdown).getTime();
    const out = $("b", el);
    const tick = () => {
      let s = Math.max(0, Math.floor((end - Date.now()) / 1000));
      const h = String(Math.floor(s / 3600)).padStart(2, "0"); s %= 3600;
      const m = String(Math.floor(s / 60)).padStart(2, "0");
      out.textContent = `${h}:${m}:${String(s % 60).padStart(2, "0")}`;
    };
    tick(); setInterval(tick, 1000);
  });

  // Filter / sort forms submit as soon as a checkbox, radio or select changes.
  $$("form[data-autosubmit]").forEach((f) => {
    f.addEventListener("change", (e) => {
      if (!e.target.matches("select, input[type=checkbox], input[type=radio]")) return;
      f.requestSubmit ? f.requestSubmit() : f.submit();
    });
  });
  // Clicking a checked radio clears it (so rating/discount filters can be removed).
  $$(".filters input[type=radio]").forEach((r) => {
    r.addEventListener("mousedown", () => { r.dataset.was = r.checked ? "1" : ""; });
    r.addEventListener("click", () => { if (r.dataset.was) { r.checked = false; r.form.requestSubmit(); } });
  });

  // Mobile filter drawer.
  const filters = $("[data-filters]");
  $("[data-filter-toggle]")?.addEventListener("click", (e) => {
    const open = filters.classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", String(open));
  });

  // Copy / fill coupon codes.
  document.addEventListener("click", async (e) => {
    const chip = e.target.closest("[data-copy]");
    if (chip) {
      try { await navigator.clipboard.writeText(chip.dataset.copy); toast(`Copied ${chip.dataset.copy}. Paste it at checkout.`, "info"); }
      catch { toast(`Use code ${chip.dataset.copy} at checkout`, "info"); }
    }
    const fill = e.target.closest("[data-fill-coupon]");
    if (fill) { const input = $("#coupon"); if (input) { input.value = fill.dataset.fillCoupon; input.focus(); } }
  });

  // Demo sign-in fill.
  $("[data-demo-fill]")?.addEventListener("click", (e) => {
    const f = $("form[action='/login']");
    f.email.value = e.currentTarget.dataset.email;
    f.password.value = e.currentTarget.dataset.password;
    f.requestSubmit();
  });

  // Show / hide password, strength meter.
  $$("[data-pw-toggle]").forEach((b) => b.addEventListener("click", () => {
    const input = b.parentElement.querySelector("input");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    b.textContent = show ? "Hide" : "Show";
    b.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));
  $$("[data-pw-meter]").forEach((input) => input.addEventListener("input", () => {
    const v = input.value;
    let score = 0;
    if (v.length >= 8) score++;
    if (v.length >= 12) score++;
    if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score++;
    if (/\d/.test(v)) score++;
    if (/[^A-Za-z0-9]/.test(v)) score++;
    const bar = $("[data-pw-bar]");
    if (bar) { bar.style.width = `${score * 20}%`; bar.dataset.level = score < 2 ? "weak" : score < 4 ? "ok" : "strong"; }
  }));

  // Confirm before destructive actions.
  $$("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => {
    if (!window.confirm(f.dataset.confirm)) e.preventDefault();
  }));

  // Cart quantity selects submit on change.
  $$("form[data-qty-form] select").forEach((s) => s.addEventListener("change", () => s.form.requestSubmit()));

  // Address forms: fill the city from the ZIP code when we know it.
  $$("[data-pin-autofill]").forEach((input) => input.addEventListener("input", async () => {
    const pin = input.value.trim();
    if (!/^[0-9]{5}(-[0-9]{4})?$/.test(pin)) return;
    const scope = input.closest("form, details, .panel") || document;
    const city = $("input[name=city]", scope);
    try {
      const data = await (await fetch("/api/delivery?zip_code=" + pin)).json();
      if (data.city && city && !city.value) city.value = data.city;
    } catch { /* ignore */ }
  }));
})();
