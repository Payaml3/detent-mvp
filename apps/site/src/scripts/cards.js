// Scroll-linked cards: each card rises, untilts and sharpens as it comes up the screen, and sinks back and
// fades as it leaves at the top, in both directions, so scrolling feels like moving through a stack. A card
// also leans toward the pointer while hovered. Content is fully visible without script and with reduced
// motion. Phones get a lighter version (site.css: no blur, less tilt) so scrolling stays smooth.
const cards = [...document.querySelectorAll("[data-card]")];
if (cards.length && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.documentElement.classList.add("cards-live");
  // cards in one row enter one after another, left to right
  const rows = new Map();
  cards.forEach((el) => {
    const n = rows.get(el.parentElement) || 0;
    el.dataset.cardK = String(n);
    rows.set(el.parentElement, n + 1);
  });
  const clamp = (v) => Math.max(0, Math.min(1, v));
  let ticking = false;
  const update = () => {
    ticking = false;
    const vh = innerHeight;
    for (const el of cards) {
      const r = el.getBoundingClientRect();
      if (r.bottom < -200 || r.top > vh + 200) continue;
      const k = Number(el.dataset.cardK) * 0.03 * vh;
      const enter = clamp((r.top + k - vh * 0.7) / (vh * 0.3)); // 1 at the bottom edge, 0 once settled
      const leave = clamp((vh * 0.05 - r.top) / Math.max(r.height, vh * 0.3)); // 0 until it nears the top
      el.style.setProperty("--in", enter.toFixed(3));
      el.style.setProperty("--out", leave.toFixed(3));
    }
  };
  const ask = () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } };
  addEventListener("scroll", ask, { passive: true });
  addEventListener("resize", ask);
  addEventListener("beforeprint", () => cards.forEach((el) => { el.style.setProperty("--in", "0"); el.style.setProperty("--out", "0"); }));
  update();

  // hover: the card leans toward the pointer
  if (matchMedia("(hover: hover)").matches) {
    for (const el of cards) {
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--tx", (((e.clientX - r.left) / r.width) - 0.5).toFixed(3));
        el.style.setProperty("--ty", (((e.clientY - r.top) / r.height) - 0.5).toFixed(3));
        el.style.setProperty("--lx", `${(((e.clientX - r.left) / r.width) * 100).toFixed(1)}%`);
        el.style.setProperty("--ly", `${(((e.clientY - r.top) / r.height) * 100).toFixed(1)}%`);
      });
      el.addEventListener("pointerleave", () => { el.style.setProperty("--tx", "0"); el.style.setProperty("--ty", "0"); });
    }
  }
}
