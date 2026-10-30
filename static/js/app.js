// Small progressive enhancements; every page also works without JavaScript.
document.addEventListener("change", (e) => {
  const el = e.target.closest("[data-autosubmit]");
  if (el) el.form.requestSubmit();
});
document.addEventListener("submit", (e) => {
  const msg = e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// Show a form field only when another control has a given value:
// data-show-if="account_type!=customer_private" or "vat_registered=on".
function controlValue(form, name) {
  const els = form.querySelectorAll(`[name="${name}"]`);
  for (const el of els) {
    if (el.type === "radio") { if (el.checked) return el.value; continue; }
    if (el.type === "checkbox") return el.checked ? "on" : "off";
    return el.value;
  }
  return "";
}
function applyConditions(root) {
  root.querySelectorAll("[data-show-if]").forEach((el) => {
    const m = el.dataset.showIf.match(/^([\w-]+)(!=|=)(.*)$/);
    if (!m || !el.form) return;
    const allowed = m[3].split("|");
    const value = controlValue(el.form, m[1]);
    const show = m[2] === "=" ? allowed.includes(value) : !allowed.includes(value);
    const wrap = el.closest(".field") || el;
    wrap.hidden = !show;
  });
}
document.addEventListener("DOMContentLoaded", () => applyConditions(document));
document.addEventListener("change", () => applyConditions(document));

// Price calculator: customer price <-> what the supplier receives (commission from the form).
const round05 = (x) => (Math.round(x * 20) / 20).toFixed(2);
const round01 = (x) => (Math.round(x * 100) / 100).toFixed(2);
document.addEventListener("input", (e) => {
  const input = e.target.closest("[data-price]");
  const row = input && input.closest("[data-price-row]");
  const form = input && input.form;
  if (!row || !form || !form.dataset.commission) return;
  const share = 1 - parseFloat(form.dataset.commission) / 100;
  const customer = row.querySelector('[data-price="customer"]');
  const supplier = row.querySelector('[data-price="supplier"]');
  const basis = row.querySelector('[data-price="basis"]');
  const value = parseFloat(String(input.value).replace(",", "."));
  if (input === customer) {
    basis.value = "customer";
    supplier.value = isNaN(value) ? "" : round01(value * share);
  } else if (input === supplier) {
    basis.value = "supplier";
    customer.value = isNaN(value) ? "" : round05(value / share);
  }
});

// Inline formsets: <template id="variant-template"> + [data-add-variant]
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-add-variant]");
  if (!btn) return;
  const tpl = document.getElementById("variant-template");
  const total = document.querySelector('input[name$="-TOTAL_FORMS"]');
  const index = parseInt(total.value, 10);
  const html = tpl.innerHTML.replace(/__prefix__/g, String(index));
  document.getElementById("variants").insertAdjacentHTML("beforeend", html);
  total.value = String(index + 1);
  applyConditions(document);
});

// Shop filters start collapsed on small screens.
document.addEventListener("DOMContentLoaded", () => {
  if (window.matchMedia("(max-width: 760px)").matches) {
    document.querySelectorAll("[data-open-desktop]").forEach((d) => {
      if (!d.querySelector("select option[selected]:not([value=''])") && !d.querySelector("input:checked")) d.open = false;
    });
  }
});

// Checkout: only show dates of the chosen delivery option.
function syncDates(scope) {
  scope.querySelectorAll('input[type=radio][name^="option_"]:checked').forEach((radio) => {
    const select = document.getElementById("date_" + radio.name.slice(7));
    if (!select) return;
    let first = null;
    for (const opt of select.options) {
      const match = opt.dataset.option === radio.value;
      opt.hidden = !match;
      opt.disabled = !match;
      if (match && !first) first = opt;
    }
    if (select.selectedOptions[0] && select.selectedOptions[0].disabled && first) first.selected = true;
  });
}
document.addEventListener("DOMContentLoaded", () => syncDates(document));
document.addEventListener("change", (e) => { if (e.target.name && e.target.name.startsWith("option_")) syncDates(document); });
