// "The stack": the three layers as one sculpture on the light page, for the scroll-driven stage beside Sift, Settle
// and Prove. Three white slabs float over the page and cast soft shadows on each other. Payments are small ink
// tiles. On the decision layer a field of rule pins rises under each one as it is checked: most slide into the gate,
// some wait in orange for a person, and a few are blocked and slide off the edge in graphite, never orange (B-02).
// On the orchestration layer each payment rides one of three curved rails to its exit. On the operations layer it
// lands in the ledger, flashes green and stacks into columns joined by an orange hash chain. A thin focus ring
// travels to the layer whose card is in view, and the camera follows it and turns a little toward the pointer.
// three.js is bundled with the site; colours come from the palette roles. Original work.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

const LAYER_OF = { RECEIVED: 0, ESCALATED: 0, HELD: 0, READY: 0, SUBMITTED: 1, UNKNOWN: 1, FAILED: 1, CONFIRMED: 2 };
const Y = [2.5, 0, -2.5];
const SIZE = 4.4, THICK = 0.14, TOP = THICK / 2;

function roles() {
  const css = getComputedStyle(document.body);
  const get = (n, f) => css.getPropertyValue(`--${n}`).trim() || f;
  return {
    bg: get("bg", "#F3F3F1"), alt: get("bg-alt", "#EAEAE7"), surface: get("surface", "#FFFFFF"),
    line: get("line-strong", "#8E8F8A"), ink: get("text", "#18191B"), signal: get("signal", "#FF4A1F"), ok: get("ok", "#237A46"),
  };
}

function roundedRect(w, r, y) {
  const s = new THREE.Shape(), h = w / 2;
  s.moveTo(-h + r, -h); s.lineTo(h - r, -h); s.quadraticCurveTo(h, -h, h, -h + r); s.lineTo(h, h - r);
  s.quadraticCurveTo(h, h, h - r, h); s.lineTo(-h + r, h); s.quadraticCurveTo(-h, h, -h, h - r); s.lineTo(-h, -h + r);
  s.quadraticCurveTo(-h, -h, -h + r, -h);
  return new THREE.BufferGeometry().setFromPoints(s.getPoints(12).map((p) => new THREE.Vector3(p.x, y, p.y)));
}

function softSpot() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, "rgba(0,0,0,0.14)"); grad.addColorStop(0.5, "rgba(0,0,0,0.05)"); grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

export function mountLayers(canvas) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { return null; }
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  const bg = new THREE.Color(c.bg), alt = new THREE.Color(c.alt), surface = new THREE.Color(c.surface), line = new THREE.Color(c.line);
  const ink = new THREE.Color(c.ink), signal = new THREE.Color(c.signal), ok = new THREE.Color(c.ok);
  const tmp = new THREE.Color();

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(bg, 18, 32); // far edges melt into the page
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  scene.add(new THREE.HemisphereLight(0xffffff, alt, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-1.2, 12, 1.8); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -4.5, right: 4.5, top: 4.5, bottom: -4.5, near: 1, far: 30 });
  key.shadow.intensity = 0.4; key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02; key.shadow.radius = 6;
  scene.add(key);
  const rig = new THREE.Group(); scene.add(rig);
  const deck = [0, 1, 2].map(() => { const g = new THREE.Group(); rig.add(g); return g; }); // things that ride on a slab

  // ---- the three slabs: white, rounded, with a hairline that turns orange on the active layer ----
  const slabGeo = new RoundedBoxGeometry(SIZE, THICK, SIZE, 3, 0.07);
  const plates = Y.map((y) => {
    const mat = new THREE.MeshStandardMaterial({ color: surface, roughness: 0.85, metalness: 0 });
    const mesh = new THREE.Mesh(slabGeo, mat);
    mesh.position.y = y; mesh.castShadow = true; mesh.receiveShadow = true; rig.add(mesh);
    const edgeMat = new THREE.LineBasicMaterial({ color: line, transparent: true, opacity: 0.5 });
    const edge = new THREE.LineLoop(roundedRect(SIZE - 0.06, 0.12, TOP + 0.004), edgeMat);
    mesh.add(edge);
    return { mesh, mat, edgeMat, base: y, glow: 0 };
  });
  // a soft shadow on the page under the stack, so it floats
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(SIZE * 1.5, SIZE * 1.5), new THREE.MeshBasicMaterial({ map: softSpot(), transparent: true, depthWrite: false }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = Y[2] - 1.4; rig.add(ground);

  // the payment's thread: one ID for life, from the gate down to the rails' hub
  const thread = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, Y[0] + 2.4, 0), new THREE.Vector3(0, Y[1] + TOP, 0)]),
    new THREE.LineDashedMaterial({ color: signal, dashSize: 0.08, gapSize: 0.1, transparent: true, opacity: 0.55 }));
  thread.computeLineDistances(); rig.add(thread);

  // ---- decision: a field of rule pins around the gate ----
  const G = 9, pinGeo = new THREE.BoxGeometry(0.2, 1, 0.2);
  pinGeo.translate(0, 0.5, 0);
  const pinXZ = [];
  for (let i = 0; i < G; i++) for (let j = 0; j < G; j++) {
    if (Math.abs(i - 4) <= 1 && Math.abs(j - 4) <= 1) continue; // the gate sits here
    pinXZ.push([(i / (G - 1) - 0.5) * SIZE * 0.8, (j / (G - 1) - 0.5) * SIZE * 0.8]);
  }
  const PINS = pinXZ.length;
  const pins = new THREE.InstancedMesh(pinGeo, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7 }), PINS);
  pins.castShadow = true; pins.receiveShadow = true; deck[0].add(pins);
  const rise = new Float32Array(PINS), warm = new Float32Array(PINS);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v3 = new THREE.Vector3(), s3 = new THREE.Vector3();
  const gateSlot = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.62), new THREE.MeshBasicMaterial({ color: ink }));
  gateSlot.rotation.x = -Math.PI / 2; gateSlot.position.set(0, Y[0] + TOP + 0.003, 0); deck[0].add(gateSlot);
  const gateRim = new THREE.LineLoop(roundedRect(0.78, 0.06, Y[0] + TOP + 0.006), new THREE.LineBasicMaterial({ color: signal, transparent: true, opacity: 0.8 }));
  deck[0].add(gateRim);
  const holdRing = new THREE.Mesh(new THREE.RingGeometry(0.3, 0.34, 48), new THREE.MeshBasicMaterial({ color: signal, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  holdRing.rotation.x = -Math.PI / 2; rig.add(holdRing);

  // ---- orchestration: three curved rails from the hub to their exits ----
  const hub = new THREE.Vector3(0, Y[1] + TOP + 0.08, 0);
  const rails = [0.15, 0.82, 1.48].map((turn, k) => {
    const a = turn * Math.PI;
    const exit = new THREE.Vector3(Math.cos(a) * 1.7, hub.y, Math.sin(a) * 1.7);
    const bend = a + (k % 2 ? -0.7 : 0.7);
    const mid = new THREE.Vector3(Math.cos(bend) * 1.05, hub.y + 0.12, Math.sin(bend) * 1.05);
    const curve = new THREE.CatmullRomCurve3([hub.clone(), mid, exit]);
    const mat = new THREE.MeshStandardMaterial({ color: line, roughness: 0.5, emissive: signal, emissiveIntensity: 0 });
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, 0.028, 8, false), mat);
    tube.castShadow = true; deck[1].add(tube);
    const port = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.035, 12, 40), mat);
    port.rotation.x = -Math.PI / 2; port.position.copy(exit); port.position.y = Y[1] + TOP + 0.03; port.castShadow = true; deck[1].add(port);
    const hole = new THREE.Mesh(new THREE.CircleGeometry(0.15, 32), new THREE.MeshBasicMaterial({ color: ink }));
    hole.rotation.x = -Math.PI / 2; hole.position.set(exit.x, Y[1] + TOP + 0.003, exit.z); deck[1].add(hole);
    return { curve, mat, exit, glow: 0 };
  });
  const hubDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.24, 0.08, 40), new THREE.MeshStandardMaterial({ color: ink, roughness: 0.4 }));
  hubDisc.position.set(0, Y[1] + TOP + 0.04, 0); hubDisc.castShadow = true; deck[1].add(hubDisc);

  // ---- operations: the ledger, columns of settled entries joined by a hash chain ----
  const COLS = 8, ROWS = 7, BH = 0.12;
  const ledger = new THREE.InstancedMesh(new RoundedBoxGeometry(0.34, BH - 0.015, 0.34, 2, 0.03), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6 }), COLS * ROWS);
  ledger.count = 0; ledger.castShadow = true; ledger.receiveShadow = true; deck[2].add(ledger);
  const fresh = new Float32Array(COLS * ROWS);
  const entry = surface.clone().lerp(line, 0.45);
  const heights = new Array(COLS).fill(0);
  const colX = (k) => (k / (COLS - 1) - 0.5) * SIZE * 0.72, LZ = 0.75;
  const chainGeo = new THREE.BufferGeometry().setFromPoints(Array.from({ length: COLS }, (_, k) => new THREE.Vector3(colX(k), Y[2] + TOP, LZ)));
  const chain = new THREE.Line(chainGeo, new THREE.LineBasicMaterial({ color: signal }));
  deck[2].add(chain);
  const chainDots = new THREE.InstancedMesh(new THREE.SphereGeometry(0.035, 12, 8), new THREE.MeshBasicMaterial({ color: signal }), COLS);
  deck[2].add(chainDots);
  let ledgerFade = 0;
  const SEED = [0, 1, 2, 2, 3, 4, 4, 5, 6, 7];
  function placeChain() {
    const p = chainGeo.attributes.position;
    for (let k = 0; k < COLS; k++) {
      const y = Y[2] + TOP + heights[k] * BH + 0.01;
      p.setY(k, y); chainDots.setMatrixAt(k, m4.makeTranslation(colX(k), y, LZ));
    }
    p.needsUpdate = true; chainDots.instanceMatrix.needsUpdate = true;
  }
  function settle(k, flash = 1) {
    if (ledger.count >= COLS * ROWS || heights[k] >= ROWS) return;
    const n = ledger.count++;
    ledger.setMatrixAt(n, m4.makeTranslation(colX(k), Y[2] + TOP + heights[k] * BH + BH / 2, LZ));
    ledger.setColorAt(n, tmp.copy(entry).lerp(ok, flash));
    fresh[n] = flash;
    ledger.instanceMatrix.needsUpdate = true; ledger.instanceColor.needsUpdate = true;
    heights[k]++;
    placeChain();
    if (heights[k] >= ROWS) ledgerFade = 1; // a full column: start a new page
  }

  // ---- payments: small ink tiles ----
  const tileGeo = new RoundedBoxGeometry(0.3, 0.08, 0.4, 2, 0.025);
  const packets = Array.from({ length: 12 }, (_, i) => {
    const mat = new THREE.MeshStandardMaterial({ color: ink, roughness: 0.35, metalness: 0.1, transparent: true, emissive: signal, emissiveIntensity: 0 });
    const m = new THREE.Mesh(tileGeo, mat);
    m.castShadow = true; rig.add(m);
    const p = { m, mat, phase: "wait", t: 0, fate: "pass", rail: 0, col: 0, u: 0, v: new THREE.Vector3() };
    reset(p, i * 0.7);
    return p;
  });
  function tint(p, col, k = 1) { p.mat.color.lerp(col, k); }
  function reset(p, delay = 0) {
    const r = Math.random();
    p.fate = r < 0.7 ? "pass" : r < 0.88 ? "hold" : "block";
    p.phase = "wait"; p.t = -delay; p.mat.opacity = 0; p.mat.emissiveIntensity = 0; p.m.visible = false;
    p.m.position.set((Math.random() - 0.5) * SIZE * 0.66, Y[0] + 2.6, (Math.random() - 0.5) * SIZE * 0.66);
    p.m.rotation.set(0, Math.random() * Math.PI, 0);
    p.mat.color.copy(ink);
  }
  function check(x, z, hold) {
    for (let k = 0; k < PINS; k++) {
      const d = Math.hypot(pinXZ[k][0] - x, pinXZ[k][1] - z);
      if (d < 1.3) { rise[k] = Math.max(rise[k], 1 - d / 1.3); if (hold) warm[k] = Math.max(warm[k], 1 - d / 1.3); }
    }
  }
  const lift = (i) => plates[i].mesh.position.y - plates[i].base;
  const hover = () => Y[0] + TOP + 0.5 + lift(0);
  function step(p, dt) {
    const pos = p.m.position;
    p.t += dt;
    if (p.phase === "wait") { if (p.t < 0) return; p.phase = "fall0"; p.m.visible = true; }
    if (p.phase !== "block") p.mat.opacity = Math.min(1, p.mat.opacity + dt * 3);
    switch (p.phase) {
      case "fall0":
        pos.y -= dt * 2.6; p.m.rotation.y += dt * 1.2;
        if (pos.y <= hover()) { pos.y = hover(); p.phase = "check"; p.t = 0; check(pos.x, pos.z, p.fate === "hold"); }
        break;
      case "check":
        pos.y = hover() + Math.sin(p.t * 6) * 0.02;
        if (p.t > 0.6) {
          p.t = 0;
          if (p.fate === "block") { p.phase = "block"; const a = Math.atan2(pos.z, pos.x) || Math.random() * 6.28; p.v.set(Math.cos(a) * 1.7, 0, Math.sin(a) * 1.7); }
          else p.phase = p.fate === "hold" ? "hold" : "toGate";
        }
        break;
      case "hold": // waits in orange for a person, who approves; the rules run again
        tint(p, signal, Math.min(1, dt * 6)); p.mat.emissiveIntensity = 0.25 + 0.15 * Math.sin(p.t * 5);
        pos.y = hover() + 0.08 + Math.sin(p.t * 3) * 0.05;
        holdRing.position.set(pos.x, Y[0] + TOP + 0.01 + lift(0), pos.z); holdRing.scale.setScalar(1 + (p.t * 0.9) % 1.2); holdRing.material.opacity = 0.9 * (1 - ((p.t * 0.9) % 1.2) / 1.2);
        if (p.t > 2.4) { p.mat.emissiveIntensity = 0; p.phase = "toGate"; p.t = 0; holdRing.material.opacity = 0; }
        break;
      case "block": // graphite, slides off the edge and is gone: a block is final
        tint(p, line, Math.min(1, dt * 8)); p.mat.emissiveIntensity = 0;
        pos.addScaledVector(p.v, dt);
        if (Math.abs(pos.x) > SIZE / 2 || Math.abs(pos.z) > SIZE / 2) { pos.y -= dt * 3 * (1 + p.t * 2); p.m.rotation.z += dt * 2; }
        p.mat.opacity = Math.max(0, 1 - p.t * 0.6);
        if (p.t > 1.8) reset(p, Math.random());
        break;
      case "toGate":
        tint(p, ink, Math.min(1, dt * 4));
        pos.x += (0 - pos.x) * Math.min(1, dt * 4); pos.z += (0 - pos.z) * Math.min(1, dt * 4);
        p.m.rotation.y += (0 - p.m.rotation.y) * Math.min(1, dt * 4);
        if (Math.hypot(pos.x, pos.z) < 0.04) { p.phase = "fall1"; p.rail = (Math.random() * 3) | 0; }
        break;
      case "fall1":
        pos.x = 0; pos.z = 0; pos.y -= dt * 3.2;
        if (pos.y <= hub.y + lift(1)) { pos.y = hub.y + lift(1); p.phase = "rail"; p.u = 0; rails[p.rail].glow = 1; }
        break;
      case "rail": {
        p.u = Math.min(1, p.u + dt * 0.8);
        const r = rails[p.rail];
        r.curve.getPointAt(p.u, pos); pos.y += 0.04 + lift(1);
        r.curve.getTangentAt(Math.min(0.999, p.u), v3); p.m.rotation.y = Math.atan2(v3.x, v3.z);
        r.glow = 1;
        if (p.u >= 1) { p.phase = "fall2"; p.col = (Math.random() * COLS) | 0; }
        break;
      }
      case "fall2": {
        pos.y -= dt * 2.8;
        pos.x += (colX(p.col) - pos.x) * Math.min(1, dt * 2.5); pos.z += (LZ - pos.z) * Math.min(1, dt * 2.5);
        p.m.rotation.y += (0 - p.m.rotation.y) * Math.min(1, dt * 3);
        if (pos.y < Y[1] - 0.2) tint(p, ok, Math.min(1, dt * 3));
        const top = Y[2] + TOP + heights[p.col] * BH + lift(2);
        if (pos.y <= top + 0.08) { settle(p.col); reset(p, Math.random() * 0.8); }
        break;
      }
    }
  }

  // a thin focus ring that travels to the active layer
  const focusRing = new THREE.Mesh(new THREE.TorusGeometry(SIZE * 0.74, 0.008, 6, 160), new THREE.MeshBasicMaterial({ color: signal, transparent: true, opacity: 0.55 }));
  focusRing.rotation.x = -Math.PI / 2; rig.add(focusRing);

  // captions for the slabs, projected beside each one
  const labels = [...canvas.parentElement.querySelectorAll("[data-stage-label]")];
  const corner = new THREE.Vector3();
  function placeLabels() {
    const h = canvas.clientHeight;
    labels.forEach((el, i) => {
      rig.localToWorld(corner.set(-SIZE / 2, plates[i].mesh.position.y + TOP, SIZE / 2)).project(camera);
      el.style.transform = `translate(0, ${(1 - corner.y) / 2 * h}px) translate(0, -50%)`;
      el.classList.toggle("on", i === active);
      el.hidden = false;
    });
  }

  // pointer and camera
  const aim = { x: 0, y: 0 }, look = { x: 0, y: 0 };
  addEventListener("pointermove", (e) => { aim.x = (e.clientX / innerWidth) * 2 - 1; aim.y = (e.clientY / innerHeight) * 2 - 1; }, { passive: true });
  let active = 0, focusY = Y[0], dist = 15;
  const target = new THREE.Vector3();
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    dist = 15 * Math.max(1, 0.8 / camera.aspect);
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  let t = 0, visible = true, raf = 0, last = performance.now();
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !reduce) loop(); }).observe(canvas);

  function frame(dt) {
    t += dt;
    look.x += (aim.x - look.x) * Math.min(1, dt * 2.5); look.y += (aim.y - look.y) * Math.min(1, dt * 2.5);
    focusY += (Y[active] - focusY) * Math.min(1, dt * 2.2);
    const az = 0.72 + look.x * 0.3 + Math.sin(t * 0.15) * 0.06, el = 0.52 - look.y * 0.1;
    camera.position.set(Math.sin(az) * dist * Math.cos(el), focusY + Math.sin(el) * dist, Math.cos(az) * dist * Math.cos(el));
    camera.lookAt(target.set(0, focusY - 0.2, 0));

    // slabs breathe apart a little; the active one lifts and its hairline turns orange
    plates.forEach((pl, i) => {
      pl.glow += ((i === active ? 1 : 0) - pl.glow) * Math.min(1, dt * 4);
      pl.mesh.position.y = pl.base + pl.glow * 0.12 + Math.sin(t * 0.8 + i * 1.7) * 0.03;
      pl.edgeMat.color.copy(line).lerp(signal, pl.glow);
      pl.edgeMat.opacity = 0.45 + pl.glow * 0.55;
    });
    deck.forEach((g, i) => { g.position.y = lift(i); });
    focusRing.position.y = focusY + TOP + lift(active) + 0.02;
    focusRing.rotation.z = t * 0.2;
    focusRing.material.opacity = 0.3 + 0.2 * Math.sin(t * 1.6);

    // rule pins rise where a payment is checked and settle back; warm ones are the held payment's
    const y0 = Y[0] + TOP;
    for (let k = 0; k < PINS; k++) {
      rise[k] = Math.max(0, rise[k] - dt * 0.9); warm[k] = Math.max(0, warm[k] - dt * 0.45);
      const wave = 0.03 * Math.sin(t * 1.4 + pinXZ[k][0] * 1.3 + pinXZ[k][1]);
      const h = 0.06 + wave + 0.05 + rise[k] * 0.32;
      m4.compose(v3.set(pinXZ[k][0], y0 - 0.01, pinXZ[k][1]), q, s3.set(1, h, 1));
      pins.setMatrixAt(k, m4);
      pins.setColorAt(k, tmp.copy(surface).lerp(alt, 0.6).lerp(ink, rise[k] * 0.55 * (1 - warm[k])).lerp(signal, warm[k]));
    }
    pins.instanceMatrix.needsUpdate = true; pins.instanceColor.needsUpdate = true;
    gateRim.material.opacity = 0.55 + 0.35 * Math.sin(t * 3);
    holdRing.material.opacity = Math.max(0, holdRing.material.opacity - dt * 0.4);
    // rails glow orange while a payment rides them
    rails.forEach((r) => { r.glow = Math.max(0, r.glow - dt * 1.1); r.mat.color.copy(line).lerp(signal, r.glow); r.mat.emissiveIntensity = r.glow * 0.35; });
    // new ledger entries flash green, then settle to graphite
    let dirty = false;
    for (let n = 0; n < ledger.count; n++) if (fresh[n] > 0) { fresh[n] = Math.max(0, fresh[n] - dt * 0.7); ledger.setColorAt(n, tmp.copy(entry).lerp(ok, fresh[n])); dirty = true; }
    if (dirty) ledger.instanceColor.needsUpdate = true;
    if (ledgerFade > 0) {
      ledgerFade -= dt * 0.6;
      if (ledgerFade <= 0) { ledger.count = 0; heights.fill(0); SEED.forEach((k) => settle(k, 0)); }
    }
    if (!reduce) for (const p of packets) step(p, dt);
    renderer.render(scene, camera);
    placeLabels();
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

  placeChain();
  SEED.forEach((k) => settle(k, 0)); // the day already has a few entries
  if (reduce) {
    // one still frame: a payment being checked, one waiting in orange, one on a rail, and the day's ledger
    const still = [
      () => { const p = packets[0]; p.m.position.set(-0.9, hover(), 0.6); check(-0.9, 0.6, false); },
      () => { const p = packets[1]; p.m.position.set(1.1, hover() + 0.08, -0.7); p.mat.color.copy(signal); p.mat.emissiveIntensity = 0.3; check(1.1, -0.7, true); holdRing.position.set(1.1, Y[0] + TOP + 0.01, -0.7); holdRing.scale.setScalar(1.5); holdRing.material.opacity = 0.7; },
      () => { const p = packets[2]; rails[0].curve.getPointAt(0.55, p.m.position); p.m.position.y += 0.04; rails[0].glow = 1; },
      () => { const p = packets[3]; p.m.position.set(0, Y[0] + 1.3, 0); },
    ];
    packets.forEach((p) => { p.m.visible = false; });
    still.forEach((f, i) => { f(); packets[i].m.visible = true; packets[i].mat.opacity = 1; });
    frame(0.0001);
  } else loop();

  return {
    setState(status) {
      active = LAYER_OF[status] ?? 0;
      if (reduce) { focusY = Y[active]; plates.forEach((pl, i) => { pl.glow = i === active ? 1 : 0; }); frame(0.0001); }
    },
  };
}
