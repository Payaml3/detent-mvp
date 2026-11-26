// "Sift then settle" (B-01, replaces the D-20 detent wheel): payments fall as halftone dots through three
// rules, the decision, orchestration and operations layers. Some are held at a rule, some are blocked and
// drop away, the rest narrow to one settled point. One brighter dot is the example payment: it stops at the
// rule its state belongs to and, when it is sent, settles with one pulse. Canvas 2D, colours from the palette
// roles on :root, so it follows site.config.mjs `palette`. Original work.

const RULES = [0.3, 0.52, 0.74]; // rule heights, as a share of the canvas height
const SPAN = [0.36, 0.25, 0.14]; // half-width of each rule, as a share of the width
const SETTLE_Y = 0.9;
// where the example payment rests for each state: the index of the rule it waits at, or "settled"
const AT = { RECEIVED: -1, ESCALATED: 0, HELD: 0, READY: 1, SUBMITTED: 2, UNKNOWN: 2, FAILED: 2, CONFIRMED: "settled" };
const STOPPED = new Set(["BLOCKED", "REJECTED", "FAILED_FINAL"]);
const WAITING = new Set(["ESCALATED", "HELD", "UNKNOWN", "FAILED"]);

function roles() {
  const css = getComputedStyle(document.documentElement);
  const get = (n) => css.getPropertyValue(`--${n}`).trim();
  return {
    dot: get("interactive-soft"), rule: get("text-soft"), settle: get("settle"), wait: get("wait"),
    danger: get("danger"), ok: get("ok"), text: get("text"),
    additive: document.documentElement.dataset.scheme !== "light", // light dots add up on a dark page only
  };
}

export function mountSift(canvas) {
  const ctx = canvas.getContext("2d");
  if (!ctx) { canvas.remove(); return null; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  let W = 0, H = 0, cx = 0, dpr = 1;
  const flow = [];
  const focus = { x: 0, y: 0, tx: 0, ty: 0, status: "RECEIVED", pulse: 0 };

  function place() {
    const at = AT[focus.status];
    const stopAt = STOPPED.has(focus.status) ? Math.max(0, Math.min(2, at ?? 0)) : null;
    if (at === "settled") { focus.tx = cx; focus.ty = SETTLE_Y * H; return; }
    const k = stopAt ?? at;
    focus.tx = cx + (k < 0 ? 0.1 * W : 0);
    focus.ty = k < 0 ? 0.12 * H : RULES[k] * H - 9;
  }

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight; cx = W * 0.62;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    place();
    if (!focus.x) { focus.x = focus.tx; focus.y = focus.ty; }
  }

  function spawn(p = {}) {
    // a dot enters at the top, already spread across the first rule's width
    p.x = cx + (Math.random() * 2 - 1) * SPAN[0] * W * 1.15;
    p.y = -10 - Math.random() * H * 0.4;
    p.vy = 0.35 + Math.random() * 0.45;
    p.r = 1.2 + Math.random() * 1.6;
    p.next = 0; p.fate = "pass"; p.hold = 0; p.a = 1;
    return p;
  }

  function stepFlow(p) {
    if (p.fate === "blocked") { p.x += p.vx; p.y += 0.6; p.a -= 0.012; if (p.a <= 0) spawn(p); return; }
    if (p.hold > 0) { p.hold -= 1; return; }
    p.y += p.vy;
    const k = p.next;
    if (k < RULES.length && p.y >= RULES[k] * H) {
      const roll = Math.random();
      if (roll < 0.08) { p.fate = "blocked"; p.vx = (p.x < cx ? -1 : 1) * (0.6 + Math.random()); return; }
      if (roll < 0.2) p.hold = 40 + Math.random() * 90;
      p.next += 1;
    }
    // narrow toward the centre: each rule admits a tighter span than the one before
    const span = (p.next < RULES.length ? SPAN[p.next] : 0.02) * W;
    const off = p.x - cx;
    if (Math.abs(off) > span) p.x -= off * 0.018;
    else p.x -= off * 0.004;
    if (p.y > SETTLE_Y * H) { p.a -= 0.05; if (p.a <= 0) spawn(p); }
  }

  function dot(x, y, r, colour, a = 1) {
    ctx.globalAlpha = a; ctx.fillStyle = colour;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }

  function draw(t) {
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = c.additive ? "lighter" : "source-over";
    // the rules: dotted lines, a halftone sieve
    RULES.forEach((ry, k) => {
      const half = SPAN[k] * W;
      for (let x = cx - half; x <= cx + half; x += 7) {
        const edge = 1 - Math.abs(x - cx) / half;
        dot(x, ry * H, 1 + 1.1 * edge, c.rule, 0.35 + 0.4 * edge);
      }
    });
    // the flow
    for (const p of flow) {
      if (!reduce) stepFlow(p);
      const colour = p.fate === "blocked" ? c.danger : p.hold > 0 ? c.wait : c.dot;
      dot(p.x, p.y, p.r, colour, Math.max(0, p.a) * 0.75);
    }
    // the settled point: a halftone disc, brighter for a moment after each send
    const glow = focus.pulse;
    for (let ring = 0; ring < 5; ring++) {
      const rr = ring * 6, n = Math.max(1, ring * 7);
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + ring * 0.4;
        dot(cx + rr * Math.cos(a), SETTLE_Y * H + rr * Math.sin(a), 3.2 - ring * 0.5 + glow * 1.2, c.settle, 0.95 - ring * 0.17);
      }
    }
    if (glow > 0) {
      ctx.globalAlpha = glow * 0.6; ctx.strokeStyle = c.settle; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx, SETTLE_Y * H, 34 + (1 - glow) * 40, 0, Math.PI * 2); ctx.stroke();
    }
    // the example payment
    const stopped = STOPPED.has(focus.status), waiting = WAITING.has(focus.status);
    const fc = stopped ? c.danger : waiting ? c.wait : focus.status === "CONFIRMED" ? c.ok : c.text;
    const breathe = reduce ? 0 : 0.5 + 0.5 * Math.sin(t / 420);
    if (focus.status !== "CONFIRMED") {
      ctx.globalAlpha = 0.5 + 0.3 * breathe; ctx.strokeStyle = fc; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(focus.x, focus.y, 11 + 2 * breathe, 0, Math.PI * 2); ctx.stroke();
      dot(focus.x, focus.y, 5, fc, 1);
      if (stopped) {
        ctx.globalAlpha = 1; ctx.strokeStyle = fc; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(focus.x - 20, focus.y + 9); ctx.lineTo(focus.x + 20, focus.y + 9); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function frame(t) {
    focus.x += (focus.tx - focus.x) * 0.08;
    focus.y += (focus.ty - focus.y) * 0.08;
    focus.pulse = Math.max(0, focus.pulse - 0.012);
    draw(t);
  }

  let running = false, raf = 0;
  const loop = (t) => { frame(t); raf = requestAnimationFrame(loop); };
  const start = () => { if (!running && !reduce) { running = true; raf = requestAnimationFrame(loop); } };
  const stop = () => { running = false; cancelAnimationFrame(raf); };
  const still = () => { focus.x = focus.tx; focus.y = focus.ty; draw(0); };

  resize();
  for (let i = 0; i < 150; i++) { const p = spawn(); p.y = Math.random() * H; flow.push(p); }
  still();
  addEventListener("resize", () => { resize(); if (!running) still(); });
  new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop())).observe(canvas);

  return {
    setState(status, transferred) {
      focus.status = status;
      place();
      if (transferred) focus.pulse = 1;
      if (!running) still();
    },
  };
}
