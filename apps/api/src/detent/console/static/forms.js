// Pending state for every plain form post: the pressed button shows a spinner and a second press is ignored,
// so a slow answer never looks like nothing happened and a payment action is not sent twice from the page.
// The server stays the authority (idempotency and state checks); this is feedback only.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
  if (form.getAttribute("aria-busy") === "true") { event.preventDefault(); return; }
  if (form.method.toLowerCase() !== "post" || form.target) return;
  form.setAttribute("aria-busy", "true");
  const button = event.submitter;
  if (button) button.classList.add("pending");
});
// Back/forward cache: a page restored from history must not stay busy.
window.addEventListener("pageshow", () => {
  document.querySelectorAll('form[aria-busy="true"]').forEach((f) => f.removeAttribute("aria-busy"));
  document.querySelectorAll("button.pending").forEach((b) => b.classList.remove("pending"));
});
