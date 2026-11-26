// The hero's live scene: "Agents prepare. Your rules decide." An AI agent, a small solid robot whose
// head follows the pointer and whose visor scans while it works, prepares payments and streams them toward the D of the Route mark (B-03), the rules.
// Each payment lands in the D and settles; the orange point is the one outcome the rules settle on and
// pulses with each sent example payment. The robot looks toward the pointer; the D turns to face it and parts around it. Orange never marks a block (B-02).
// three.js is bundled with the site; colours come from the palette roles. Original work.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
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
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size, map, vertexColors: true, transparent: true, depthWrite: false, sizeAttenuation: true, toneMapped: false }));
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

  // ---- the agent: a small solid robot, upper left, in ceramic, dark metal and glass. Its head turns to
  // follow the pointer, its eyes blink, a scan line crosses its visor while it works, and it hands payments
  // over from its hand. Lit by a soft studio environment so the surfaces read as real materials.
  const A_AT = new THREE.Vector3(-3, 17, 0), AS = 1.04;
  const agent = new THREE.Group(); agent.position.copy(A_AT); agent.scale.setScalar(AS); scene.add(agent);
  const head = new THREE.Group(); head.position.set(0, 2, 0); agent.add(head);
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x1a1b1d, 0.7));
  const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(-50, 70, 90); scene.add(key);
  const rim = new THREE.DirectionalLight(paper.getHex(), 1.6); rim.position.set(70, 25, -70); scene.add(rim);
  const shell = new THREE.MeshPhysicalMaterial({ color: paper.clone().multiplyScalar(0.84), roughness: 0.42, metalness: 0, clearcoat: 0.6, clearcoatRoughness: 0.25 });
  const metal = new THREE.MeshStandardMaterial({ color: 0x2b2c2f, roughness: 0.32, metalness: 0.85 });
  const glass = new THREE.MeshPhysicalMaterial({ color: 0x07080a, roughness: 0.06, metalness: 0.2, clearcoat: 1, clearcoatRoughness: 0.03 });
  const lamp = () => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: signal, emissiveIntensity: 1.4, roughness: 0.4 });
  const mesh = (geo, mat, parent, x = 0, y = 0, z = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); parent.add(m); return m; };
  const HX = 7.5, HY = 6, HZ = 6;
  // head: a rounded ceramic shell, a glass visor, ear pods, an antenna with a lamp
  mesh(new RoundedBoxGeometry(HX * 2, HY * 2, HZ * 2, 8, 3.4), shell, head);
  mesh(new RoundedBoxGeometry(HX * 1.68, 6.4, 1.6, 6, 0.75), glass, head, 0, 0.2, HZ - 0.55);
  for (const side of [-1, 1]) {
    const pod = mesh(new THREE.CylinderGeometry(2.2, 2.2, 1.4, 40), metal, head, side * (HX + 0.35), 0, 0); pod.rotation.z = Math.PI / 2;
    const cap = mesh(new THREE.CylinderGeometry(1.3, 1.3, 0.3, 32), shell, head, side * (HX + 1.15), 0, 0); cap.rotation.z = Math.PI / 2;
  }
  mesh(new THREE.CylinderGeometry(0.95, 1.15, 0.6, 32), metal, head, 0, HY + 0.1, 0);
  mesh(new THREE.CylinderGeometry(0.16, 0.16, 3.6, 12), metal, head, 0, HY + 2, 0);
  const tipMat = lamp();
  mesh(new THREE.SphereGeometry(0.85, 24, 16), tipMat, head, 0, HY + 4.3, 0);
  const tipLight = new THREE.PointLight(signal, 0, 26, 2); tipLight.position.set(0, HY + 4.3, 0.6); head.add(tipLight);
  // the eyes: two soft lit capsules behind the visor glass, in their own group so they can blink and glance
  const eyes = new THREE.Group(); eyes.position.set(0, 0.3, HZ + 0.27); head.add(eyes);
  const eyeMat = new THREE.MeshBasicMaterial({ color: paper, toneMapped: false });
  for (const side of [-1, 1]) { const ey = mesh(new THREE.CapsuleGeometry(0.85, 0.9, 6, 20), eyeMat, eyes, side * 2.9, 0, 0); ey.scale.z = 0.25; }
  const scanLine = mesh(new THREE.PlaneGeometry(0.45, 5.4), new THREE.MeshBasicMaterial({ color: signal, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }), head, 0, 0.2, HZ + 0.29);
  // neck, body with a chest lamp, a resting left arm and the right arm reaching toward the rules
  mesh(new THREE.CylinderGeometry(1.9, 2.2, 2.8, 32), metal, agent, 0, -5.5, 0);
  for (const y of [-4.8, -6]) { const r = mesh(new THREE.TorusGeometry(2.15, 0.18, 10, 40), metal, agent, 0, y, 0); r.rotation.x = Math.PI / 2; }
  mesh(new RoundedBoxGeometry(17, 9.6, 10, 8, 3.2), shell, agent, 0, -11.8, 0);
  mesh(new RoundedBoxGeometry(9, 0.35, 0.4, 2, 0.15), metal, agent, 0, -14.6, 5.0);
  mesh(new THREE.CylinderGeometry(2.1, 2.1, 0.5, 40), glass, agent, 0, -11.2, 4.9).rotation.x = Math.PI / 2;
  const chestMat = lamp();
  mesh(new THREE.TorusGeometry(1.35, 0.26, 14, 48), chestMat, agent, 0, -11.2, 5.2);
  const SHOULDER = new THREE.Vector3(8.8, -9.5, 0), ELBOW = new THREE.Vector3(12.4, -13.4, 2.2), HAND = new THREE.Vector3(14.5, -11, 5);
  const limb = (a, b, r, mat) => {
    const len = a.distanceTo(b), m = new THREE.Mesh(new THREE.CapsuleGeometry(r, Math.max(0.01, len - r * 2), 6, 20), mat);
    m.position.copy(a).lerp(b, 0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tmpV.copy(b).sub(a).normalize()); agent.add(m);
  };
  const tmpV = new THREE.Vector3();
  const L_SH = new THREE.Vector3(-8.8, -9.5, 0), L_EL = new THREE.Vector3(-10.6, -13.8, 0.8), L_HA = new THREE.Vector3(-10.2, -17.6, 2);
  for (const [s, el, ha] of [[SHOULDER, ELBOW, HAND], [L_SH, L_EL, L_HA]]) {
    mesh(new THREE.SphereGeometry(1.7, 28, 18), metal, agent, s.x, s.y, s.z);
    limb(s, el, 1.05, shell); limb(el, ha, 0.95, shell);
    mesh(new THREE.SphereGeometry(1.15, 24, 16), metal, agent, el.x, el.y, el.z);
    mesh(new THREE.SphereGeometry(1.35, 28, 18), metal, agent, ha.x, ha.y, ha.z);
  }
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

  // ---- the story: one payment at a time, told in words. The robot says what it is preparing; the payment
  // travels to the D; the rules answer with a verdict. Execute settles into the point. Escalate waits, in
  // orange, for a person, and the rules run again before it settles. Block is final: the payment drops away
  // in graphite, never orange (B-02). Fictional payees on test networks.
  const CASES = [
    { say: "Preparing payout · €2,400.00 to Harbor Logistics GmbH", verdict: "EXECUTE", why: "Within your limits. Sent once." },
    { say: "Preparing payout · £820.00 to Quill Studio Ltd", verdict: "ESCALATE", why: "Bank details changed 3 days ago", after: "Approved by a person · rules ran again" },
    { say: "Preparing withdrawal · 500.00 USDC to 0x9f…c21", verdict: "BLOCK", why: "Screening hit. A block is final." },
    { say: "Preparing payout · $1,120.00 to Northwind Creators", verdict: "EXECUTE", why: "Within your limits. Sent once." },
    { say: "Preparing payout · $64,000.00 to Marlow Prop Traders", verdict: "ESCALATE", why: "Far above this trader’s usual payout", after: "Approved by a person · rules ran again" },
  ];
  const bubble = document.querySelector("[data-bubble-text]"), verdictEl = document.querySelector("[data-verdict]"), rulesLabel = document.querySelector('[data-art-label="rules"]');
  const token = new THREE.Sprite(new THREE.SpriteMaterial({ map, color: paper, transparent: true, depthWrite: false }));
  token.scale.setScalar(4.2); token.visible = false; scene.add(token);
  const trail = cloud(40, 1.6, map); scene.add(trail.pts);
  const trailAt = Array.from({ length: 40 }, () => new THREE.Vector3());
  const tk = { i: -1, phase: "say", t: 0, from: new THREE.Vector3(), mid: new THREE.Vector3(), gate: new THREE.Vector3(), seat: new THREE.Vector3(), vel: new THREE.Vector3() };
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
    tk.i = (tk.i + 1) % CASES.length; tk.phase = "say"; tk.t = 0; token.visible = false;
    showVerdict("", "");
    if (bubble) bubble.textContent = "";
  }
  function story(dt) {
    const c = CASES[tk.i];
    tk.t += dt;
    if (tk.phase === "say") {
      const n = Math.min(c.say.length, Math.floor(tk.t * 34));
      if (bubble && bubble.textContent.length !== n) bubble.textContent = c.say.slice(0, n);
      if (tk.t > c.say.length / 34 + 0.5) {
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
    const sw = (t * 0.6) % 1;
    scanLine.position.x = sw * HX * 1.5 - HX * 0.75; scanLine.material.opacity = 0.5 * Math.sin(Math.PI * sw);
    // the antenna lamp and chest light breathe; both flare when a payment is sent
    const glow = 0.55 + 0.45 * Math.sin(t * 3) + pulse * 0.8;
    tipMat.emissiveIntensity = chestMat.emissiveIntensity = 0.6 + glow * 1.4;
    tipLight.intensity = 30 * glow;

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
  const anchor = { agent: new THREE.Vector3(0, -18.5, 0), rules: new THREE.Vector3(0, -22.5 * S, 0), bubble: new THREE.Vector3(HX + 2, 1, 0), verdict: new THREE.Vector3(0, -22.5 * S, 0) };
  const owner = { agent: () => agent, bubble: () => head, rules: () => rules, verdict: () => rules };
  const shift = { agent: "translate(-50%, 0)", rules: "translate(-50%, 0)", bubble: "translate(0, -50%)", verdict: "translate(-50%, 0)" };
  const proj = new THREE.Vector3();
  function placeLabels() {
    if (!labels.length) return;
    const w = canvas.clientWidth, h = canvas.clientHeight, ox = canvas.offsetLeft, oy = canvas.offsetTop;
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
  if (reduce) { home.forEach((h, i) => d.pos.set([h.x, h.y, h.z], i * 3)); if (bubble) bubble.textContent = CASES[1].say; showVerdict("ESCALATE", `ESCALATE · ${CASES[1].why}`); frame(0); }
  else loop();

  return { setState(status, transferred) { if (transferred) pulse = 1; if (reduce) frame(0); } };
}
