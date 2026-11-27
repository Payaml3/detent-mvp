// Section entrances: parts rise in order as they enter. Content is visible without script, and anything
// already scrolled past (a jump from a link, a fast scroll) is shown at once, so nothing can stay hidden.
const items = [...document.querySelectorAll("[data-reveal]")];
// Phones get a shorter, lighter entrance (site.css); the sweep below shows anything a flick scroll skipped.
if (items.length && "IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.documentElement.classList.add("will-reveal");
  const show = (el) => { el.classList.add("revealed"); io.unobserve(el); };
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) show(e.target);
  }, { rootMargin: "0px 0px -8% 0px" });
  const bySection = new Map();
  items.forEach((el) => {
    const s = el.closest("section") || document.body;
    const n = bySection.get(s) || 0;
    el.style.setProperty("--d", `${Math.min(n, 5) * 80}ms`);
    bySection.set(s, n + 1);
    io.observe(el);
  });
  const sweep = () => {
    for (const el of items) {
      if (!el.classList.contains("revealed") && el.getBoundingClientRect().top < innerHeight) show(el);
    }
  };
  addEventListener("scroll", sweep, { passive: true });
  addEventListener("resize", sweep);
  addEventListener("beforeprint", () => items.forEach(show));
  requestAnimationFrame(sweep);
}
