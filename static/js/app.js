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
