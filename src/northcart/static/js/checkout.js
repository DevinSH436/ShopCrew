/* Checkout: payment method panels, live total, client-side validation, payment interstitial. */
(() => {
  "use strict";
  const { $, $$, toast } = window.Northcart;
  const form = $("[data-checkout]");
  if (!form) return;
  const usd = (n) => Number(n).toLocaleString("en-US");

  function luhn(num) {
    const d = num.replace(/\D/g, "");
    if (d.length < 13 || d.length > 19) return false;
    let sum = 0;
    for (let i = 0; i < d.length; i++) {
      let n = +d[d.length - 1 - i];
      if (i % 2) { n *= 2; if (n > 9) n -= 9; }
      sum += n;
    }
    return sum % 10 === 0;
  }

  // Payment method switch: open the selected panel, update COD fee + total.
  const total = $("[data-total]");
  function onPayment() {
    const method = form.payment_method.value;
    $$(".pay-option").forEach((o) => o.classList.toggle("selected", $("input[type=radio]", o).checked));
    const cod = method === "cod";
    $$("[data-cod-row]").forEach((el) => { el.hidden = !cod; });
    if (total) total.textContent = "$" + usd(cod ? total.dataset.cod : total.dataset.online);
    const btn = $("[data-place-btn]");
    if (btn) btn.textContent = cod ? "Place your order" : `Pay $${usd(total.dataset.online)}`;
  }
  $$("input[name=payment_method]").forEach((r) => r.addEventListener("change", onPayment));
  onPayment();

  // Address radio: update the delivery date shown in step 3.
  const dateOut = $("[data-checkout-date]");
  $$("input[name=address_id]").forEach((r) => r.addEventListener("change", () => {
    if (dateOut && r.dataset.deliveryLabel) dateOut.textContent = r.dataset.deliveryLabel;
    $$(".address-option").forEach((o) => o.classList.toggle("selected", $("input", o).checked));
  }));
  $$(".address-option").forEach((o) => o.classList.toggle("selected", $("input", o).checked));

  // Card input formatting.
  const cardNum = form.card_number;
  cardNum?.addEventListener("input", () => {
    const d = cardNum.value.replace(/\D/g, "").slice(0, 19);
    cardNum.value = d.replace(/(.{4})/g, "$1 ").trim();
  });
  const exp = form.card_expiry;
  exp?.addEventListener("input", () => {
    const d = exp.value.replace(/\D/g, "").slice(0, 4);
    exp.value = d.length > 2 ? d.slice(0, 2) + "/" + d.slice(2) : d;
  });

  function validate() {
    if (!form.address_id || !$("input[name=address_id]:checked", form)) return "Please choose a delivery address.";
    const method = form.payment_method.value;
    if (method === "upi" && !/^[\w.-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$/.test(form.upi_id.value.trim())) return "Enter a valid UPI ID, like name@okbank.";
    if (method === "card") {
      if (!luhn(form.card_number.value)) return "That card number doesn't look right.";
      if (!/^(0[1-9]|1[0-2])\/\d{2}$/.test(form.card_expiry.value.trim())) return "Enter the expiry date as MM/YY.";
      if (!/^\d{3,4}$/.test(form.card_cvv.value.trim())) return "Enter the 3 or 4 digit CVV.";
      if (!form.card_name.value.trim()) return "Enter the name on the card.";
    }
    if (method === "netbanking" && !form.bank.value) return "Choose your bank.";
    return "";
  }

  let submitting = false;
  form.addEventListener("submit", (e) => {
    if (submitting) return;
    e.preventDefault();
    const error = validate();
    if (error) { toast(error, "error"); return; }
    submitting = true;
    $$("[data-place-btn]").forEach((b) => { b.disabled = true; });
    if (form.payment_method.value === "cod") { form.submit(); return; }
    const overlay = $("[data-processing]");
    if (overlay) overlay.hidden = false;
    setTimeout(() => form.submit(), 1500);
  });
})();
