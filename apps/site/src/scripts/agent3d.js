// The hero's live scene: "Agents prepare. Your rules decide." An AI agent, a sphere of particles that
// ripples while it works, prepares payments and streams them toward the "settled D" (B-03), the rules.
// Each payment lands in the D and settles; the orange point is the one outcome the rules settle on and
// pulses with each sent example payment. The agent leans toward the pointer and its surface swells
// toward it; the D turns to face it and parts around it. Orange never marks a block (B-02).
// three.js is bundled with the site; colours come from the palette roles. Original work.
import * as THREE from "three";

const POINT = { cx: 22, cy: 30.5, r: 5.5 };
const inD = (x, y) => {
  const outer = y >= 4 && y <= 44 && x >= 5 && (x <= 23 || Math.hypot(x - 23, y - 24) <= 20);
  const inner = y >= 12 && y <= 36 && x >= 13 && (x <= 23 || Math.hypot(x - 23, y - 24) <= 12);
  return outer && !inner;
};
const inPoint = (x, y) => Math.hypot(x - POINT.cx, y - POINT.cy) <= POINT.r;

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

  // ---- the rules: the settled D, lower right ----
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

  // ---- the agent: a sphere of particles, upper left, rippling while it works ----
  const A_AT = new THREE.Vector3(-4, 19, 0), AR = 9, AN = 2600;
  const agent = new THREE.Group(); agent.position.copy(A_AT); scene.add(agent);
  const a = cloud(AN, 1.15, map);
  const dirs = [];
  for (let i = 0; i < AN; i++) {
    const y = 1 - (i / (AN - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.39996323;
    dirs.push(new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r));
    const k = Math.random() < 0.06 ? signal : paper.clone().multiplyScalar(0.45 + Math.random() * 0.55);
    a.col.set([k.r, k.g, k.b], i * 3);
  }
  agent.add(a.pts);
  // two thin orbit rings around the agent
  const ringMat = new THREE.LineBasicMaterial({ color: paper, transparent: true, opacity: 0.22 });
  const ringGeo = new THREE.BufferGeometry().setFromPoints(new THREE.EllipseCurve(0, 0, AR * 1.55, AR * 1.55).getPoints(96).map((p) => new THREE.Vector3(p.x, 0, p.y)));
  const ring1 = new THREE.LineLoop(ringGeo, ringMat), ring2 = new THREE.LineLoop(ringGeo, ringMat);
  ring1.rotation.set(1.2, 0.3, 0); ring2.rotation.set(-0.9, 0.8, 0.4);
  agent.add(ring1, ring2);

  // ---- the stream: payments the agent prepares, flying to the rules ----
  const SN = 360;
  const s = cloud(SN, 1.3, map);
  const flights = Array.from({ length: SN }, () => ({ u: Math.random(), speed: 0.22 + Math.random() * 0.18, from: new THREE.Vector3(), mid: new THREE.Vector3(), to: new THREE.Vector3(), held: false }));
  scene.add(s.pts);
  const tmp = new THREE.Vector3();
  function launch(f) {
    const dir = new THREE.Vector3(1, -0.6, 0.2).normalize().add(new THREE.Vector3((Math.random() - 0.5) * 0.9, (Math.random() - 0.5) * 0.9, (Math.random() - 0.5) * 0.9)).normalize();
    agent.localToWorld(f.from.copy(dir).multiplyScalar(AR)); // world space
    const h = home[Math.floor(Math.random() * DN * 0.88)];
    rules.localToWorld(f.to.copy(h));
    f.mid.copy(f.from).lerp(f.to, 0.5).add(tmp.set((Math.random() - 0.3) * 14, 12 + Math.random() * 10, (Math.random() - 0.5) * 16));
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

    // the agent leans toward the pointer and turns slowly while it works
    agent.position.set(A_AT.x + look.x * 4, A_AT.y - look.y * 3, 0);
    agent.rotation.y = t * 0.25 + look.x * 0.6;
    agent.rotation.x = look.y * 0.4;
    ring1.rotation.z = t * 0.4; ring2.rotation.z = -t * 0.3;
    if (near) { toward.copy(hit); agent.worldToLocal(toward); toward.normalize(); }
    for (let i = 0; i < AN; i++) {
      const v = dirs[i];
      let r = AR + Math.sin(v.y * 6 + t * 2.2) * 0.35 + Math.sin(v.x * 5 - t * 1.7) * 0.3; // thinking ripples
      if (near) { const dot = v.x * toward.x + v.y * toward.y + v.z * toward.z; if (dot > 0.6) r += (dot - 0.6) * 9; }
      a.pos[i * 3] = v.x * r; a.pos[i * 3 + 1] = v.y * r; a.pos[i * 3 + 2] = v.z * r;
    }
    a.geo.attributes.position.needsUpdate = true;

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
  const anchor = { agent: new THREE.Vector3(0, -AR * 1.75, 0), rules: new THREE.Vector3(0, -22.5 * S, 0) };
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
