// The hero's live scene: "Agents prepare. Your rules decide." An AI agent, a small robot of particles whose
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
    renderer.render(scene, camera);
    placeLabels();
  }

  // captions that travel with the scene: "AI agent prepares" under the agent, "Your rules decide" under the D
  const labels = [...document.querySelectorAll("[data-art-label]")];
  const anchor = { agent: new THREE.Vector3(0, -18.5, 0), rules: new THREE.Vector3(0, -22.5 * S, 0) };
  const proj = new THREE.Vector3();
  function placeLabels() {
    if (!labels.length) return;
    const w = canvas.clientWidth, h = canvas.clientHeight, ox = canvas.offsetLeft, oy = canvas.offsetTop;
    for (const el of labels) {
      const g = el.dataset.artLabel === "agent" ? agent : rules;
      g.localToWorld(proj.copy(anchor[el.dataset.artLabel])).project(camera);
      el.style.transform = `translate(${ox + (proj.x + 1) / 2 * w}px, ${oy + (1 - proj.y) / 2 * h}px) translate(-50%, 0)`;
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

  if (reduce) { home.forEach((h, i) => d.pos.set([h.x, h.y, h.z], i * 3)); frame(0); }
  else loop();

  return { setState(status, transferred) { if (transferred) pulse = 1; if (reduce) frame(0); } };
}
