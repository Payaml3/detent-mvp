// The hero's live scene: "Agents prepare. Your rules decide." An AI agent, a small robot of particles with a
// network for a mind that fires while it reasons and three tools on an orbit (read, check, propose), whose
// head follows the pointer and whose visor scans while it works, prepares payments and streams them toward the D of the Route mark (B-03), the rules.
// Each payment lands in the D and settles; the orange point is the one outcome the rules settle on and
// pulses with each sent example payment. The robot looks toward the pointer; the D turns to face it and parts around it. Orange never marks a block (B-02).
// three.js is bundled with the site; colours come from the palette roles. Original work.
import * as THREE from "three";
import { POINT, inD, inPoint } from "./markShape.js";


function roles() {
  const css = getComputedStyle(document.body);
  const get = (n, f) => css.getPropertyValue(`--${n}`).trim() || f;
  return { paper: get("paper", get("bg")), signal: get("signal") };
}

function dotTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.45, "rgba(255,255,255,0.85)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

function cloud(count, size, map) {
  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size, map, vertexColors: true, transparent: true, depthWrite: false, sizeAttenuation: true }));
  pts.frustumCulled = false; // particles move far from where they start
  return { pos, col, geo, pts };
}

export function mountAgent(canvas) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { return null; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  const paper = new THREE.Color(c.paper), signal = new THREE.Color(c.signal);
  const map = dotTexture();

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 300);
  camera.position.set(0, 0, 150);

  // ---- the rules: the Route mark, lower right ----
  const S = 0.74, D_AT = new THREE.Vector3(20, -12, 0);
  const rules = new THREE.Group(); rules.position.copy(D_AT); scene.add(rules);
  const DN = 4600, home = [], isPoint = [];
  while (home.length < DN * 0.88) {
    const x = Math.random() * 48, y = Math.random() * 48;
    if (inD(x, y)) { home.push(new THREE.Vector3((x - 24) * S, (24 - y) * S, (Math.random() - 0.5) * 5)); isPoint.push(false); }
  }
  while (home.length < DN) {
    const x = Math.random() * 48, y = Math.random() * 48;
    if (inPoint(x, y)) { home.push(new THREE.Vector3((x - 24) * S, (24 - y) * S, 2 + Math.random() * 2.5)); isPoint.push(true); }
  }
  const d = cloud(DN, 1.35, map);
  const dVel = new Float32Array(DN * 3);
  home.forEach((h, i) => {
    d.pos.set([h.x + (Math.random() - 0.5) * 40, h.y + 50 + Math.random() * 30, h.z], i * 3);
    const k = isPoint[i] ? signal : paper.clone().multiplyScalar(0.5 + Math.random() * 0.5);
    d.col.set([k.r, k.g, k.b], i * 3);
  });
  rules.add(d.pts);
  const PX = (POINT.cx - 24) * S, PY = (24 - POINT.cy) * S;

  // ---- the agent: a small robot built from particles, upper left. Its head turns to follow the pointer,
  // its eyes blink, a scan line crosses its visor while it works, and it hands payments over from its hand.
  const A_AT = new THREE.Vector3(-5, 17, 0), AS = 1.12;
  const agent = new THREE.Group(); agent.position.copy(A_AT); agent.scale.setScalar(AS); scene.add(agent);
  const head = new THREE.Group(); head.position.set(0, 2, 0); agent.add(head);
  const rnd = (a, b) => a + Math.random() * (b - a);
  const shade = (lo = 0.45, hi = 1) => paper.clone().multiplyScalar(rnd(lo, hi));
  // a point on a rounded box (superellipsoid) surface
  const box = (hx, hy, hz, n = 5) => {
    const v = new THREE.Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize();
    const k = Math.pow(Math.pow(Math.abs(v.x / hx), n) + Math.pow(Math.abs(v.y / hy), n) + Math.pow(Math.abs(v.z / hz), n), -1 / n);
    return v.multiplyScalar(k);
  };
  const disc = (r) => { const a = rnd(0, Math.PI * 2), q = Math.sqrt(Math.random()) * r; return [Math.cos(a) * q, Math.sin(a) * q]; };
  const HX = 7.5, HY = 6, HZ = 6;
  const headPts = [], headCol = [], visor = [];
  for (let i = 0; i < 2300; i++) {
    const p = box(HX, HY, HZ);
    const onVisor = p.z > HZ * 0.55 && Math.abs(p.y) < 2.8 && Math.abs(p.x) < HX * 0.8;
    if (onVisor) { p.z -= 0.5; visor.push(headPts.length); headCol.push(paper.clone().multiplyScalar(0.18)); }
    else headCol.push(shade(0.5, 1));
    headPts.push(p);
  }
  for (const side of [-1, 1]) for (let i = 0; i < 110; i++) { const [a, b] = disc(2.1); headPts.push(new THREE.Vector3(side * (HX + rnd(0.2, 1)), a, b)); headCol.push(shade(0.6, 1)); } // ears
  for (let i = 0; i < 70; i++) { headPts.push(new THREE.Vector3(rnd(-0.15, 0.15), HY + rnd(0, 3.6), rnd(-0.15, 0.15))); headCol.push(shade(0.5, 0.8)); } // antenna
  const tipAt = headPts.length;
  for (let i = 0; i < 60; i++) { const v = new THREE.Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(rnd(0.3, 1)); headPts.push(v.add(new THREE.Vector3(0, HY + 4.3, 0))); headCol.push(signal.clone()); }
  const h = cloud(headPts.length, 1.05, map);
  headPts.forEach((p, i) => { h.pos.set([p.x, p.y, p.z], i * 3); h.col.set([headCol[i].r, headCol[i].g, headCol[i].b], i * 3); });
  head.add(h.pts);
  // the eyes: two bright discs on the visor, in their own group so they can blink and glance
  const eyes = new THREE.Group(); eyes.position.set(0, 0.3, HZ - 0.1); head.add(eyes);
  const e = cloud(360, 1.15, map);
  for (let i = 0; i < 360; i++) { const [a, b] = disc(1.35); e.pos.set([(i % 2 ? 2.9 : -2.9) + a, b, rnd(0, 0.4)], i * 3); e.col.set([paper.r, paper.g, paper.b], i * 3); }
  eyes.add(e.pts);
  // neck, body with a chest light, and the right arm reaching toward the rules
  const bodyPts = [], bodyCol = [];
  for (let i = 0; i < 160; i++) { const a = rnd(0, Math.PI * 2); bodyPts.push(new THREE.Vector3(Math.cos(a) * 2.2, rnd(-6.8, -4.2), Math.sin(a) * 2.2)); bodyCol.push(shade(0.35, 0.6)); }
  for (let i = 0; i < 1700; i++) { const p = box(8.5, 5.5, 5, 4).add(new THREE.Vector3(0, -12.5, 0)); if (p.y < -16.5) continue; bodyPts.push(p); bodyCol.push(shade(0.45, 0.95)); }
  const chestAt = bodyPts.length;
  for (let i = 0; i < 140; i++) { const a = rnd(0, Math.PI * 2), q = rnd(1.1, 1.6); bodyPts.push(new THREE.Vector3(Math.cos(a) * q, -11.5 + Math.sin(a) * q, 5.2)); bodyCol.push(signal.clone()); }
  const SHOULDER = new THREE.Vector3(8.8, -9.5, 0), HAND = new THREE.Vector3(14.5, -11, 5);
  for (let i = 0; i < 260; i++) { const u = Math.random(); const p = SHOULDER.clone().lerp(HAND, u); const [a, b] = disc(1.1); bodyPts.push(p.add(new THREE.Vector3(0, a, b))); bodyCol.push(shade(0.45, 0.9)); }
  for (let i = 0; i < 120; i++) { bodyPts.push(new THREE.Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(rnd(0.8, 1.6)).add(HAND)); bodyCol.push(shade(0.7, 1)); }
  const b = cloud(bodyPts.length, 1.05, map);
  bodyPts.forEach((p, i) => { b.pos.set([p.x, p.y, p.z], i * 3); b.col.set([bodyCol[i].r, bodyCol[i].g, bodyCol[i].b], i * 3); });
  agent.add(b.pts);
  const AR = 9; // the agent's reach, for the label

  // ---- the mind: a small network inside the head that fires while the agent reasons ----
  const BN = 30, bNodes = [];
  while (bNodes.length < BN) {
    const v = new THREE.Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1));
    if (v.lengthSq() <= 1) bNodes.push(v.multiply(new THREE.Vector3(4.8, 3.4, 3.2)).add(new THREE.Vector3(0, 0.6, -0.4)));
  }
  const bEdges = [];
  bNodes.forEach((a, i) => {
    bNodes.map((b2, j) => [j, a.distanceToSquared(b2)]).filter(([j]) => j !== i).sort((x, y) => x[1] - y[1]).slice(0, 3)
      .forEach(([j]) => { if (!bEdges.some(([x, y]) => (x === j && y === i))) bEdges.push([i, j]); });
  });
  const ePos = new Float32Array(bEdges.length * 6), eCol = new Float32Array(bEdges.length * 6), eHeat = new Float32Array(bEdges.length);
  bEdges.forEach(([i, j], k) => { ePos.set([bNodes[i].x, bNodes[i].y, bNodes[i].z, bNodes[j].x, bNodes[j].y, bNodes[j].z], k * 6); });
  const eGeo = new THREE.BufferGeometry();
  eGeo.setAttribute("position", new THREE.BufferAttribute(ePos, 3)); eGeo.setAttribute("color", new THREE.BufferAttribute(eCol, 3));
  const wires = new THREE.LineSegments(eGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  wires.renderOrder = 1; head.add(wires);
  const BP = 26, brain = cloud(BN + BP, 1.5, map);
  bNodes.forEach((v, i) => brain.pos.set([v.x, v.y, v.z], i * 3));
  const sparks = Array.from({ length: BP }, () => ({ e: Math.floor(Math.random() * bEdges.length), u: Math.random(), dir: Math.random() < 0.5 }));
  brain.pts.renderOrder = 1; head.add(brain.pts);
  e.pts.renderOrder = 2;

  // ---- its tools: three on an orbit around it. It reads, it checks, and it proposes. Nothing else:
  // an agent's tools are read-only, except proposing a payment intent, and the rules decide (invariant 5).
  const orbit = new THREE.Group(); orbit.position.set(0, -12, 0); orbit.rotation.set(0.22, 0, -0.06); agent.add(orbit);
  const spin = new THREE.Group(); orbit.add(spin);
  const OR = 14.5, RN = 300, TN = 3, TP = 70;
  const ring = cloud(RN + TN * TP, 1, map);
  for (let i = 0; i < RN; i++) { const a = (i / RN) * Math.PI * 2; ring.pos.set([Math.cos(a) * OR, rnd(-0.12, 0.12), Math.sin(a) * OR], i * 3); }
  const toolAt = Array.from({ length: TN }, (_, k) => { const a = Math.PI * (0.8 - k * 0.3); return new THREE.Vector3(Math.cos(a) * OR, 0, Math.sin(a) * OR); });
  toolAt.forEach((c0, k) => { for (let i = 0; i < TP; i++) { const v = new THREE.Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(rnd(0.2, 1.7)).add(c0); ring.pos.set([v.x, v.y, v.z], (RN + k * TP + i) * 3); } });
  spin.add(ring.pts);
  // read, check and propose sit left to right on the front of the orbit, toward the rules
  const toolHeat = new Float32Array(TN);
  // a beam from the head to the tool in use
  const BEAM = 22, beam = cloud(BEAM, 1.25, map); agent.add(beam.pts);
  const beamFrom = new THREE.Vector3(), beamTo = new THREE.Vector3();
  let think = 0, activeTool = -1;

  // ---- the stream: payments the agent prepares, flying to the rules ----
  const SN = 360;
  const s = cloud(SN, 1.3, map);
  const flights = Array.from({ length: SN }, () => ({ u: Math.random(), speed: 0.22 + Math.random() * 0.18, from: new THREE.Vector3(), mid: new THREE.Vector3(), to: new THREE.Vector3(), held: false }));
  scene.add(s.pts);
  const tmp = new THREE.Vector3();
  function launch(f) {
    agent.localToWorld(f.from.copy(HAND).add(tmp.set(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)))); // world space, from the hand
    const h = home[Math.floor(Math.random() * DN * 0.88)];
    rules.localToWorld(f.to.copy(h));
    f.mid.copy(f.from).lerp(f.to, 0.5).add(tmp.set((Math.random() - 0.3) * 10, 6 + Math.random() * 8, (Math.random() - 0.5) * 16));
    f.held = Math.random() < 0.14; // escalated: waits at the rules, in orange, for a person
    f.u = 0;
  }
  scene.updateMatrixWorld(true);
  flights.forEach((f) => { const u = f.u; launch(f); f.u = u; });

  // ---- the story: one payment at a time, told in words. The robot says what it is preparing; the payment
  // travels to the D; the rules answer with a verdict. Execute settles into the point. Escalate waits, in
  // orange, for a person, and the rules run again before it settles. Block is final: the payment drops away
  // in graphite, never orange (B-02). Example payees, sample data.
  const CASES = [
    { steps: ["read · invoice INV-2291 · €2,400.00 due today", "check · Harbor Logistics · 14 paid, same bank"], say: "propose · payout €2,400.00 to Harbor Logistics GmbH", verdict: "EXECUTE", why: "Within your limits. Sent once." },
    { steps: ["read · invoice INV-0418 · £820.00", "check · Quill Studio · bank details changed"], say: "propose · payout £820.00 to Quill Studio Ltd", verdict: "ESCALATE", why: "Bank details changed 3 days ago", after: "Approved by a person · rules ran again" },
    { steps: ["read · withdrawal request · 500.00 USDC", "check · address 0x9f…c21 · history"], say: "propose · withdrawal 500.00 USDC to 0x9f…c21", verdict: "BLOCK", why: "Screening hit. A block is final." },
    { steps: ["read · creator statement · $1,120.00 earned", "check · Northwind Creators · 31 paid"], say: "propose · payout $1,120.00 to Northwind Creators", verdict: "EXECUTE", why: "Within your limits. Sent once." },
    { steps: ["read · withdrawal request · $64,000.00", "check · Marlow Prop · usual is $2,100"], say: "propose · payout $64,000.00 to Marlow Prop Traders", verdict: "ESCALATE", why: "Far above this trader’s usual payout", after: "Approved by a person · rules ran again" },
  ];
  const bubble = document.querySelector("[data-bubble-text]"), verdictEl = document.querySelector("[data-verdict]"), rulesLabel = document.querySelector('[data-art-label="rules"]');
  const token = new THREE.Sprite(new THREE.SpriteMaterial({ map, color: paper, transparent: true, depthWrite: false }));
  token.scale.setScalar(4.2); token.visible = false; scene.add(token);
  const trail = cloud(40, 1.6, map); scene.add(trail.pts);
  const trailAt = Array.from({ length: 40 }, () => new THREE.Vector3());
  const tk = { i: -1, phase: "say", t: 0, s: 0, from: new THREE.Vector3(), mid: new THREE.Vector3(), gate: new THREE.Vector3(), seat: new THREE.Vector3(), vel: new THREE.Vector3() };
  const graphite = paper.clone().multiplyScalar(0.28);
  function showVerdict(kind, text) {
    if (!verdictEl) return;
    verdictEl.dataset.kind = kind || ""; verdictEl.classList.toggle("on", !!text);
    rulesLabel?.classList.toggle("off", !!text); // the verdict takes the caption's place
    if (!text) return;
    const [head2, ...rest] = text.split(" · ");
    const b = document.createElement("b"); b.textContent = head2;
    verdictEl.replaceChildren(b, rest.join(" · "));
  }
  function nextCase() {
    tk.i = (tk.i + 1) % CASES.length; tk.phase = "say"; tk.t = 0; tk.s = 0; token.visible = false;
    showVerdict("", "");
    if (bubble) bubble.textContent = "";
  }
  function story(dt) {
    const c = CASES[tk.i];
    tk.t += dt;
    if (tk.phase === "say") {
      // the agent works through its tools: read, check, then propose. Each line is one tool call.
      const line = tk.s < c.steps.length ? c.steps[tk.s] : c.say;
      activeTool = Math.min(tk.s, TN - 1);
      const n = Math.min(line.length, Math.floor(tk.t * 38));
      if (bubble && bubble.textContent !== line.slice(0, n)) bubble.textContent = line.slice(0, n);
      if (tk.s < c.steps.length && tk.t > line.length / 38 + 0.6) { tk.s++; tk.t = 0; }
      else if (tk.s >= c.steps.length && tk.t > line.length / 38 + 0.5) {
        activeTool = -1;
        agent.localToWorld(tk.from.copy(HAND));
        rules.localToWorld(tk.gate.set(PX - 1, PY + 9, 7));
        rules.localToWorld(tk.seat.set(PX, PY, 4));
        tk.mid.copy(tk.from).lerp(tk.gate, 0.5).add(tmp.set(2, 9, 6));
        token.material.color.copy(paper); token.material.opacity = 1; token.visible = true;
        trailAt.forEach((v) => v.copy(tk.from));
        tk.phase = "fly"; tk.t = 0;
      }
    } else if (tk.phase === "fly") {
      const u = Math.min(1, tk.t / 1.3), e = u * u * (3 - 2 * u), v = 1 - e;
      token.position.set(v * v * tk.from.x + 2 * v * e * tk.mid.x + e * e * tk.gate.x, v * v * tk.from.y + 2 * v * e * tk.mid.y + e * e * tk.gate.y, v * v * tk.from.z + 2 * v * e * tk.mid.z + e * e * tk.gate.z);
      if (u >= 1) {
        tk.phase = c.verdict; tk.t = 0;
        showVerdict(c.verdict, `${c.verdict} · ${c.why}`);
        if (c.verdict === "BLOCK") tk.vel.set(-9, 6, 4);
      }
    } else if (tk.phase === "EXECUTE") {
      token.position.lerp(tk.seat, Math.min(1, dt * 4));
      token.material.color.lerp(signal, Math.min(1, dt * 3));
      if (tk.t > 0.7 && token.visible) { token.visible = false; pulse = 1; }
      if (tk.t > 2.6) nextCase();
    } else if (tk.phase === "ESCALATE") {
      token.material.color.lerp(signal, Math.min(1, dt * 5));
      const a = tk.t * 2.4;
      token.position.set(tk.gate.x + Math.cos(a) * 2.6, tk.gate.y + Math.sin(a * 2) * 0.8, tk.gate.z + Math.sin(a) * 2.6);
      if (tk.t > 2.6) { tk.phase = "EXECUTE"; tk.t = 0; showVerdict("APPROVED", c.after); }
    } else if (tk.phase === "BLOCK") {
      token.material.color.lerp(graphite, Math.min(1, dt * 6));
      tk.vel.y -= 26 * dt;
      token.position.addScaledVector(tk.vel, dt);
      token.material.opacity = Math.max(0, 1 - tk.t * 0.5);
      if (tk.t > 3) nextCase();
    }
    // the token's trail
    for (let i = trailAt.length - 1; i > 0; i--) trailAt[i].lerp(trailAt[i - 1], 0.6);
    trailAt[0].copy(token.position);
    const tc = token.material.color, on = token.visible ? token.material.opacity : 0;
    trailAt.forEach((v, i) => {
      trail.pos.set([v.x, v.y, v.z], i * 3);
      const k = on * (1 - i / trailAt.length) * 0.8;
      trail.col.set([tc.r * k, tc.g * k, tc.b * k], i * 3);
    });
    trail.geo.attributes.position.needsUpdate = true; trail.geo.attributes.color.needsUpdate = true;
  }

  // ---- the floor: a field of dots receding into the dark, drifting toward the rules ----
  const FX = 34, FZ = 22, fl = cloud(FX * FZ, 0.9, map);
  const floorY = -34;
  for (let i = 0; i < FX; i++) for (let j = 0; j < FZ; j++) {
    const k = (i * FZ + j) * 3, a = 0.05 + 0.13 * (j / FZ);
    fl.pos.set([(i - FX / 2) * 6, floorY, -90 + j * 6], k);
    fl.col.set([paper.r * a, paper.g * a, paper.b * a], k);
  }
  scene.add(fl.pts);

  // ---- pointer ----
  const aim = { x: 0, y: 0 }, look = { x: 0, y: 0 };
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  const hit = new THREE.Vector3(), local = new THREE.Vector3(), toward = new THREE.Vector3();
  let near = false;
  addEventListener("pointermove", (e) => {
    aim.x = (e.clientX / innerWidth) * 2 - 1; aim.y = (e.clientY / innerHeight) * 2 - 1;
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    near = true;
  }, { passive: true });
  document.addEventListener("pointerleave", () => { near = false; });

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  let t = 0, pulse = 0, visible = true, raf = 0, last = performance.now();
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !reduce) loop(); }).observe(canvas);

  function frame(dt) {
    t += dt;
    look.x += (aim.x - look.x) * Math.min(1, dt * 2.5);
    look.y += (aim.y - look.y) * Math.min(1, dt * 2.5);
    if (near) { ray.setFromCamera(ndc, camera); ray.ray.intersectPlane(plane, hit); }

    // the agent: the body turns a little, the head follows the pointer, the eyes blink and glance
    agent.position.set(A_AT.x + look.x * 1.5, A_AT.y - look.y * 1 + Math.sin(t * 1.6) * 0.35, 0);
    agent.rotation.y = 0.35 + look.x * 0.25;
    head.rotation.y = look.x * 0.65; head.rotation.x = look.y * 0.35; head.rotation.z = Math.sin(t * 0.9) * 0.04;
    const blink = (t % 3.8) > 3.62 ? 0.12 : 1;
    eyes.scale.y += (blink - eyes.scale.y) * Math.min(1, dt * 30);
    eyes.position.x = look.x * 0.6; eyes.position.y = 0.3 - look.y * 0.4;
    // a scan line crosses the visor while it works
    const scan = ((t * 0.6) % 1) * HX * 1.8 - HX * 0.9;
    for (const i of visor) {
      const k = Math.max(0, 1 - Math.abs(h.pos[i * 3] - scan) / 0.9);
      const c = 0.18 + k * 0.6;
      h.col[i * 3] = paper.r * c + signal.r * k * 0.2; h.col[i * 3 + 1] = paper.g * c; h.col[i * 3 + 2] = paper.b * c;
    }
    // the antenna tip and chest light breathe; both flare when a payment is sent
    const glow = 0.55 + 0.45 * Math.sin(t * 3) + pulse * 0.8;
    for (let i = tipAt; i < headPts.length; i++) h.col.set([signal.r * glow, signal.g * glow, signal.b * glow], i * 3);
    for (let i = chestAt; i < chestAt + 140; i++) b.col.set([signal.r * glow, signal.g * glow, signal.b * glow], i * 3);
    h.geo.attributes.color.needsUpdate = true; b.geo.attributes.color.needsUpdate = true;

    // the mind fires while the agent reasons; the tool in use lights up and a beam joins it to the head
    think += ((tk.phase === "say" && !reduce ? 1 : reduce ? 0.7 : 0.12) - think) * Math.min(1, dt * 3);
    for (let k = 0; k < bEdges.length; k++) {
      if (Math.random() < dt * 3 * think) eHeat[k] = 1;
      eHeat[k] = Math.max(0, eHeat[k] - dt * 1.8);
      const a = 0.05 + think * 0.08 + eHeat[k] * 0.55 * think;
      eCol.set([paper.r * a, paper.g * a, paper.b * a, paper.r * a, paper.g * a, paper.b * a], k * 6);
    }
    eGeo.attributes.color.needsUpdate = true;
    for (let i = 0; i < BN; i++) { const a = 0.35 + think * 0.5 + 0.15 * Math.sin(t * 4 + i); brain.col.set([paper.r * a, paper.g * a, paper.b * a], i * 3); }
    sparks.forEach((sp, i) => {
      sp.u += dt * (0.6 + think * 2.2);
      if (sp.u >= 1) { const [x, y] = bEdges[sp.e]; const at = sp.dir ? y : x; const next = bEdges.map((ed, k) => [ed, k]).filter(([ed]) => ed[0] === at || ed[1] === at); const [ed, k] = next[Math.floor(Math.random() * next.length)]; sp.e = k; sp.dir = ed[0] === at; sp.u = 0; }
      const [x, y] = bEdges[sp.e], A = bNodes[sp.dir ? x : y], B = bNodes[sp.dir ? y : x];
      tmp.copy(A).lerp(B, sp.u); brain.pos.set([tmp.x, tmp.y, tmp.z], (BN + i) * 3);
      const k = think * Math.sin(Math.PI * sp.u);
      brain.col.set([signal.r * k + paper.r * k * 0.3, signal.g * k + paper.g * k * 0.3, signal.b * k + paper.b * k * 0.3], (BN + i) * 3);
    });
    brain.geo.attributes.position.needsUpdate = true; brain.geo.attributes.color.needsUpdate = true;
    spin.rotation.y = reduce ? 0 : Math.sin(t * 0.35) * 0.18;
    for (let k = 0; k < TN; k++) toolHeat[k] += ((k === activeTool ? 1 : 0) - toolHeat[k]) * Math.min(1, dt * 6);
    for (let i = 0; i < RN; i++) { const a = 0.2 + 0.08 * Math.sin(i * 0.37 + t * 2); ring.col.set([paper.r * a, paper.g * a, paper.b * a], i * 3); }
    for (let k = 0; k < TN; k++) for (let i = 0; i < TP; i++) {
      const hot = toolHeat[k], base = 0.45 + 0.1 * Math.sin(t * 3 + i), kk = k === 2 ? signal : paper;
      const a = base + hot * 0.7;
      ring.col.set([paper.r * a * (1 - hot) + kk.r * a * hot, paper.g * a * (1 - hot) + kk.g * a * hot, paper.b * a * (1 - hot) + kk.b * a * hot], (RN + k * TP + i) * 3);
    }
    ring.geo.attributes.color.needsUpdate = true;
    const bt = activeTool >= 0 ? activeTool : 0, bk = activeTool >= 0 ? toolHeat[activeTool] : Math.max(...toolHeat);
    agent.worldToLocal(spin.localToWorld(beamTo.copy(toolAt[bt])));
    agent.worldToLocal(head.localToWorld(beamFrom.set(0, 0, 0)));
    for (let i = 0; i < BEAM; i++) {
      const u = ((i / BEAM) + t * 0.9) % 1;
      tmp.copy(beamFrom).lerp(beamTo, u); beam.pos.set([tmp.x, tmp.y, tmp.z], i * 3);
      const kc = bt === 2 ? signal : paper, a = bk * Math.sin(Math.PI * u) * 0.9;
      beam.col.set([kc.r * a, kc.g * a, kc.b * a], i * 3);
    }
    beam.geo.attributes.position.needsUpdate = true; beam.geo.attributes.color.needsUpdate = true;
    tools.forEach((el, k) => {
      spin.localToWorld(proj.copy(toolAt[k]));
      const depth = (proj.z + OR * AS) / (2 * OR * AS);
      el.style.opacity = String(0.25 + 0.75 * Math.max(toolHeat[k], depth * 0.6));
      el.classList.toggle("on", toolHeat[k] > 0.5);
    });

    // the rules turn to face the pointer and part around it
    rules.rotation.y = -0.25 + look.x * 0.45;
    rules.rotation.x = 0.05 + look.y * 0.2;
    if (near) { local.copy(hit); rules.worldToLocal(local); }
    pulse = Math.max(0, pulse - dt * 0.9);
    const R2 = 64;
    for (let i = 0; i < DN; i++) {
      const j = i * 3, h = home[i];
      let tx = h.x, ty = h.y, tz = h.z + Math.sin(t * 1.2 + i) * 0.2;
      if (isPoint[i]) { const k = 1 + pulse * 0.35; tx = PX + (h.x - PX) * k; ty = PY + (h.y - PY) * k; }
      dVel[j] += (tx - d.pos[j]) * 10 * dt; dVel[j + 1] += (ty - d.pos[j + 1]) * 10 * dt; dVel[j + 2] += (tz - d.pos[j + 2]) * 10 * dt;
      if (near) {
        const dx = d.pos[j] - local.x, dy = d.pos[j + 1] - local.y, d2 = dx * dx + dy * dy;
        if (d2 < R2) { const f = (1 - d2 / R2) * 120 * dt / Math.sqrt(d2 + 0.01); dVel[j] += dx * f; dVel[j + 1] += dy * f; dVel[j + 2] += 4 * f; }
      }
      dVel[j] *= 0.86; dVel[j + 1] *= 0.86; dVel[j + 2] *= 0.86;
      d.pos[j] += dVel[j] * dt * 4; d.pos[j + 1] += dVel[j + 1] * dt * 4; d.pos[j + 2] += dVel[j + 2] * dt * 4;
    }
    d.geo.attributes.position.needsUpdate = true;

    // payments in flight: agent to rules
    for (let i = 0; i < SN; i++) {
      const f = flights[i];
      f.u += dt * (f.held && f.u > 0.9 ? f.speed * 0.1 : f.speed); // an escalated payment waits at the rules
      if (f.u >= 1) { launch(f); }
      const u = Math.min(1, f.u), v = 1 - u;
      tmp.set(v * v * f.from.x + 2 * v * u * f.mid.x + u * u * f.to.x, v * v * f.from.y + 2 * v * u * f.mid.y + u * u * f.to.y, v * v * f.from.z + 2 * v * u * f.mid.z + u * u * f.to.z);
      s.pos.set([tmp.x, tmp.y, tmp.z], i * 3);
      const fade = Math.sin(Math.PI * u); // appears at the agent, dissolves into the rules
      const k = f.held && u > 0.8 ? signal : paper;
      s.col.set([k.r * fade, k.g * fade, k.b * fade], i * 3);
    }
    s.geo.attributes.position.needsUpdate = true; s.geo.attributes.color.needsUpdate = true;
    if (!reduce) story(dt);
    fl.pts.position.x = ((t * 3) % 6) - look.x * 4; fl.pts.rotation.x = 0.04 + look.y * 0.03;
    renderer.render(scene, camera);
    placeLabels();
  }

  // captions that travel with the scene: "AI agent prepares" under the agent, "Your rules decide" under the D
  const labels = [...document.querySelectorAll("[data-art-label]")];
  const tools = [...document.querySelectorAll("[data-art-tool]")];
  const anchor = { agent: new THREE.Vector3(0, -23.5, 0), rules: new THREE.Vector3(0, -22.5 * S, 0), bubble: new THREE.Vector3(HX + 2, 1, 0), verdict: new THREE.Vector3(0, -22.5 * S, 0) };
  const owner = { agent: () => agent, bubble: () => head, rules: () => rules, verdict: () => rules };
  const shift = { agent: "translate(-50%, 0)", rules: "translate(-50%, 0)", bubble: "translate(0, -50%)", verdict: "translate(-50%, 0)" };
  const proj = new THREE.Vector3();
  function placeLabels() {
    if (!labels.length) return;
    const w = canvas.clientWidth, h = canvas.clientHeight, ox = canvas.offsetLeft, oy = canvas.offsetTop;
    tools.forEach((el, k) => {
      spin.localToWorld(proj.copy(toolAt[k]).add(tmp.set(0, -2, 0))).project(camera);
      el.style.transform = `translate(${ox + (proj.x + 1) / 2 * w}px, ${oy + (1 - proj.y) / 2 * h}px) translate(-50%, 0)`;
      el.hidden = false;
    });
    for (const el of labels) {
      const key = el.dataset.artLabel;
      owner[key]().localToWorld(proj.copy(anchor[key])).project(camera);
      el.style.transform = `translate(${ox + (proj.x + 1) / 2 * w}px, ${oy + (1 - proj.y) / 2 * h}px) ${shift[key]}`;
      el.hidden = false;
    }
  }

  function loop() {
    cancelAnimationFrame(raf);
    last = performance.now();
    const tick = (now) => {
      if (!visible) return;
      frame(Math.min(0.033, (now - last) / 1000)); last = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  nextCase();
  if (reduce) { home.forEach((h, i) => d.pos.set([h.x, h.y, h.z], i * 3)); if (bubble) bubble.textContent = CASES[1].say; activeTool = 2; showVerdict("ESCALATE", `ESCALATE · ${CASES[1].why}`); frame(0); }
  else loop();

  return { setState(status, transferred) { if (transferred) pulse = 1; if (reduce) frame(0); } };
}
