/* Product page: gallery, zoom, PIN-code delivery check, reviews, frequently bought together. */
(() => {
  "use strict";
  const { $, $$, post, toast, setCartCount } = window.Northcart;

  // Gallery thumbnails + hover zoom.
  const main = $("[data-main-image]");
  $$("[data-thumb]").forEach((btn) => {
    const show = () => {
      main.src = btn.dataset.thumb;
      $$("[data-thumb]").forEach((b) => b.classList.toggle("active", b === btn));
    };
    btn.addEventListener("click", show);
    btn.addEventListener("mouseenter", show);
  });
  const zoom = $("[data-zoom]");
  if (zoom && main && window.matchMedia("(hover: hover)").matches) {
    zoom.addEventListener("mousemove", (e) => {
      const r = zoom.getBoundingClientRect();
      main.style.transformOrigin = `${((e.clientX - r.left) / r.width) * 100}% ${((e.clientY - r.top) / r.height) * 100}%`;
      main.style.transform = "scale(1.9)";
    });
    zoom.addEventListener("mouseleave", () => { main.style.transform = ""; });
  }

  // Delivery estimate.
  const est = $("[data-delivery]");
  const dateEl = $("[data-delivery-date]");
  const result = $("[data-pin-result]");
  const pinForm = $("[data-pin-check]");
  async function check(pin, quiet) {
    try {
      const res = await fetch("/api/delivery?pincode=" + encodeURIComponent(pin));
      const data = await res.json();
      if (!data.ok) { if (result) { result.textContent = data.message; result.className = "small text-red"; } return; }
      if (dateEl) dateEl.innerHTML = `<strong>${data.date_label}</strong>`;
      if (result) {
        result.className = "small";
        result.textContent = `Delivering to ${data.city ? data.city + " " : ""}${pin} · Cash on delivery available`;
      }
      try { localStorage.setItem("northcart_pincode", pin); if (data.city) localStorage.setItem("northcart_city", data.city); } catch { /* ignore */ }
      if (!quiet) toast(`Delivery by ${data.date_label}`, "info");
    } catch { /* offline */ }
  }
  pinForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    const pin = pinForm.pincode.value.trim();
    if (!/^[1-9][0-9]{5}$/.test(pin)) { result.textContent = "Please enter a valid 6-digit PIN code."; result.className = "small text-red"; return; }
    check(pin, false);
  });
  let saved = null;
  try { saved = localStorage.getItem("northcart_pincode"); } catch { /* ignore */ }
  if (saved && est) { if (pinForm) pinForm.pincode.value = saved; check(saved, true); }
  document.addEventListener("northcart:pincode", (e) => { if (pinForm) pinForm.pincode.value = e.detail.pincode; check(e.detail.pincode, true); });

  // Review form toggle.
  const form = $("[data-review-form]");
  $("[data-review-open]")?.addEventListener("click", () => { form.hidden = false; form.scrollIntoView({ behavior: "smooth", block: "center" }); });
  $("[data-review-cancel]")?.addEventListener("click", () => { form.hidden = true; });
  if (form && !form.hidden) setTimeout(() => form.scrollIntoView({ block: "center" }), 200);

  // Helpful votes.
  $$("form[data-helpful]").forEach((f) => f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button", f);
    try {
      const data = await post(f.action, new FormData(f));
      const id = f.action.match(/reviews\/(\d+)/)[1];
      const label = $(`[data-helpful-count="${id}"]`);
      if (label) label.textContent = `${data.count} ${data.count === 1 ? "person" : "people"} found this helpful`;
      btn.textContent = "✓ Thanks for your feedback"; btn.disabled = true;
    } catch (err) { toast(err.message, "error"); }
  }));

  // Frequently bought together: add each item in turn.
  $("form[data-fbt]")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button", e.target);
    const ids = btn.dataset.fbtIds.split(",");
    btn.disabled = true;
    let count = 0;
    for (const id of ids) {
      try { count = (await post("/cart/add", { product_id: id, quantity: 1 })).count; } catch (err) { toast(err.message, "error"); }
    }
    setCartCount(count);
    toast(`Added ${ids.length} items to your cart`);
    btn.disabled = false;
  });
})();
