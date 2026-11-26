// "The stack": the three layers as one machine, for the scroll-driven stage beside Sift, Settle and Prove.
// Payments fall as small lit packets. On the decision layer a grid of rule cells checks each one: most pass
// through the gate, some wait in orange for a person, and a few are blocked and slide off the edge in graphite,
// never orange (B-02). On the orchestration layer each payment takes one of three rail lanes to its exit. On the
// operations layer it lands in the ledger, stacking into columns joined by a hash chain. As you scroll, the
// camera travels down to the layer whose card is in view; it also turns a little toward the pointer.
// three.js is bundled with the site; colours come from the palette roles. Original work.
import * as THREE from "three";

const LAYER_OF = { RECEIVED: 0, ESCALATED: 0, HELD: 0, READY: 0, SUBMITTED: 1, UNKNOWN: 1, FAILED: 1, CONFIRMED: 2 };
const Y = [2.3, 0, -2.3];
const SIZE = 4.4;

function roles() {
  const css = getComputedStyle(document.body);
  const get = (n, f) => css.getPropertyValue(`--${n}`).trim() || f;
  return { paper: get("paper", get("bg")), signal: get("signal"), ok: get("ok"), ink: get("ink", get("text")) };
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

export function mountLayers(canvas) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { return null; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  const paper = new THREE.Color(c.paper), signal = new THREE.Color(c.signal), ok = new THREE.Color(c.ok), ink = new THREE.Color(c.ink);
  const graphite = paper.clone().multiplyScalar(0.22);
  const glow = glowTexture();

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(ink, 13, 26);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  scene.add(new THREE.AmbientLight(0xffffff, 0.5));
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(4, 8, 6); scene.add(key);
  const under = new THREE.PointLight(signal, 4, 9); under.position.set(0, -3.6, 1); scene.add(under);
  const rig = new THREE.Group(); scene.add(rig);

  // ---- the three plates: thin glass with lit edges ----
  const plates = Y.map((y) => {
    const geo = new THREE.BoxGeometry(SIZE, 0.06, SIZE);
    const fill = new THREE.MeshStandardMaterial({ color: paper, transparent: true, opacity: 0.05, roughness: 0.15, metalness: 0.2, depthWrite: false });
    const mesh = new THREE.Mesh(geo, fill);
    const edgeMat = new THREE.LineBasicMaterial({ color: paper, transparent: true, opacity: 0.35 });
    mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat));
    mesh.position.y = y; rig.add(mesh);
    return { mesh, fill, edgeMat, glow: 0 };
  });

  // decision: a grid of rule cells and the gate in the middle
  const N = 11, cells = new THREE.BufferGeometry(), cellPos = new Float32Array(N * N * 3), cellCol = new Float32Array(N * N * 3), flash = new Float32Array(N * N);
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const k = i * N + j;
    cellPos.set([(i / (N - 1) - 0.5) * SIZE * 0.86, Y[0] + 0.05, (j / (N - 1) - 0.5) * SIZE * 0.86], k * 3);
  }
  cells.setAttribute("position", new THREE.BufferAttribute(cellPos, 3));
  cells.setAttribute("color", new THREE.BufferAttribute(cellCol, 3));
  const cellPts = new THREE.Points(cells, new THREE.PointsMaterial({ size: 0.09, vertexColors: true, map: glow, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  rig.add(cellPts);
  const gate = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([[-0.35, -0.35], [0.35, -0.35], [0.35, 0.35], [-0.35, 0.35]].map(([x, z]) => new THREE.Vector3(x, Y[0] + 0.05, z))), new THREE.LineBasicMaterial({ color: signal, transparent: true, opacity: 0.8 }));
  rig.add(gate);
  const scanner = new THREE.Mesh(new THREE.RingGeometry(0.98, 1, 64), new THREE.MeshBasicMaterial({ color: paper, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  scanner.rotation.x = -Math.PI / 2; rig.add(scanner);

  // orchestration: three rail lanes from the centre to their exits
  const EXITS = [Math.PI * 0.2, Math.PI * 0.85, Math.PI * 1.5].map((a) => new THREE.Vector3(Math.cos(a) * 1.75, Y[1] + 0.05, Math.sin(a) * 1.75));
  const lanes = EXITS.map((e) => {
    const mat = new THREE.LineBasicMaterial({ color: paper, transparent: true, opacity: 0.35 });
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, Y[1] + 0.05, 0), e]), mat);
    const hole = new THREE.Mesh(new THREE.RingGeometry(0.14, 0.18, 32), new THREE.MeshBasicMaterial({ color: paper, transparent: true, opacity: 0.6, side: THREE.DoubleSide }));
    hole.rotation.x = -Math.PI / 2; hole.position.copy(e); rig.add(line, hole);
    return { mat, hole, glow: 0 };
  });

  // operations: the ledger, columns of settled entries joined by a hash chain
  const COLS = 8, ROWS = 7, BLOCK = new THREE.BoxGeometry(0.3, 0.1, 0.3);
  const ledger = new THREE.InstancedMesh(BLOCK, new THREE.MeshStandardMaterial({ color: paper, roughness: 0.4, metalness: 0.3, emissive: paper, emissiveIntensity: 0.08 }), COLS * ROWS);
  ledger.count = 0; rig.add(ledger);
  const heights = new Array(COLS).fill(0);
  const colX = (k) => (k / (COLS - 1) - 0.5) * SIZE * 0.7;
  const chainGeo = new THREE.BufferGeometry().setFromPoints(Array.from({ length: COLS }, (_, k) => new THREE.Vector3(colX(k), Y[2] + 0.1, 0.9)));
  const chain = new THREE.Line(chainGeo, new THREE.LineBasicMaterial({ color: signal, transparent: true, opacity: 0.7 }));
  rig.add(chain);
  const m4 = new THREE.Matrix4();
  let ledgerFade = 0;
  function settle(k) {
    if (ledger.count >= COLS * ROWS || heights[k] >= ROWS) return;
    m4.makeTranslation(colX(k), Y[2] + 0.08 + heights[k] * 0.11, 0.9);
    ledger.setMatrixAt(ledger.count++, m4); ledger.instanceMatrix.needsUpdate = true;
    heights[k]++;
    const p = chainGeo.attributes.position; p.setY(k, Y[2] + 0.1 + heights[k] * 0.11); p.needsUpdate = true;
    if (heights.every((h) => h >= 3) || heights[k] >= ROWS) ledgerFade = 1; // a full day: start a new page
  }

  // ---- payments: small lit packets with a glow ----
  const packetGeo = new THREE.BoxGeometry(0.26, 0.07, 0.36);
  const packets = Array.from({ length: 16 }, (_, i) => {
    const mat = new THREE.MeshStandardMaterial({ color: paper, emissive: paper, emissiveIntensity: 0.25, roughness: 0.3, metalness: 0.4, transparent: true });
    const m = new THREE.Mesh(packetGeo, mat);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: paper, transparent: true, opacity: 0.5, depthWrite: false, blending: THREE.AdditiveBlending }));
    halo.scale.setScalar(0.8); m.add(halo); rig.add(m);
    const p = { m, mat, halo, phase: "wait", t: -i * 0.55, fate: "pass", lane: 0, col: 0, v: new THREE.Vector3(), to: new THREE.Vector3() };
    reset(p, i * 0.55);
    return p;
  });
  function tint(p, col) { p.mat.color.copy(col); p.mat.emissive.copy(col); p.halo.material.color.copy(col); }
  function reset(p, delay = 0) {
    const r = Math.random();
    p.fate = r < 0.72 ? "pass" : r < 0.9 ? "hold" : "block";
    p.phase = "wait"; p.t = -delay; p.mat.opacity = 0; p.halo.material.opacity = 0;
    p.m.position.set((Math.random() - 0.5) * SIZE * 0.7, Y[0] + 2.6, (Math.random() - 0.5) * SIZE * 0.7);
    p.m.rotation.set(0, Math.random() * Math.PI, 0);
    tint(p, paper);
  }
  function flashAt(x, z) {
    for (let k = 0; k < N * N; k++) {
      const d = Math.hypot(cellPos[k * 3] - x, cellPos[k * 3 + 2] - z);
      if (d < 0.9) flash[k] = Math.max(flash[k], 1 - d / 0.9);
    }
    scanner.position.set(x, Y[0] + 0.06, z); scanner.scale.setScalar(0.1); scanner.material.opacity = 0.8;
  }
  function step(p, dt) {
    const pos = p.m.position;
    p.t += dt;
    if (p.phase === "wait") { if (p.t < 0) return; p.phase = "fall0"; }
    p.mat.opacity = Math.min(1, p.mat.opacity + dt * 3); p.halo.material.opacity = 0.5 * p.mat.opacity;
    p.m.rotation.y += dt * 0.8;
    switch (p.phase) {
      case "fall0":
        pos.y -= dt * 2.4;
        if (pos.y <= Y[0] + 0.1) { pos.y = Y[0] + 0.1; p.phase = "check"; p.t = 0; flashAt(pos.x, pos.z); }
        break;
      case "check":
        if (p.t > 0.45) {
          if (p.fate === "block") { p.phase = "block"; p.t = 0; const a = Math.atan2(pos.z, pos.x) || Math.random() * 6.28; p.v.set(Math.cos(a) * 1.6, 0, Math.sin(a) * 1.6); }
          else if (p.fate === "hold") { p.phase = "hold"; p.t = 0; }
          else { p.phase = "toGate"; p.t = 0; }
        }
        break;
      case "hold":
        tint(p, p.mat.color.clone().lerp(signal, Math.min(1, dt * 6)));
        pos.y = Y[0] + 0.25 + Math.sin(p.t * 4) * 0.05;
        p.halo.scale.setScalar(0.8 + Math.sin(p.t * 6) * 0.2 + 0.4);
        if (p.t > 2) { p.halo.scale.setScalar(0.8); tint(p, paper); p.phase = "toGate"; p.t = 0; } // a person approved; the rules ran again
        break;
      case "block":
        tint(p, p.mat.color.clone().lerp(graphite, Math.min(1, dt * 8)));
        pos.addScaledVector(p.v, dt);
        if (Math.abs(pos.x) > SIZE / 2 || Math.abs(pos.z) > SIZE / 2) pos.y -= dt * 3 * (1 + p.t * 2);
        p.mat.opacity = Math.max(0, 1 - p.t * 0.6);
        if (p.t > 1.8) reset(p, Math.random());
        break;
      case "toGate":
        pos.x += (0 - pos.x) * Math.min(1, dt * 5); pos.z += (0 - pos.z) * Math.min(1, dt * 5);
        if (Math.hypot(pos.x, pos.z) < 0.05) { p.phase = "fall1"; p.lane = (Math.random() * 3) | 0; }
        break;
      case "fall1":
        pos.y -= dt * 2.4;
        if (pos.y <= Y[1] + 0.1) { pos.y = Y[1] + 0.1; p.phase = "lane"; p.t = 0; lanes[p.lane].glow = 1; }
        break;
      case "lane": {
        const e = EXITS[p.lane];
        pos.x += (e.x - pos.x) * Math.min(1, dt * 3.2); pos.z += (e.z - pos.z) * Math.min(1, dt * 3.2);
        if (Math.hypot(pos.x - e.x, pos.z - e.z) < 0.04) { p.phase = "fall2"; p.col = (Math.random() * COLS) | 0; }
        break;
      }
      case "fall2": {
        pos.y -= dt * 2.4;
        pos.x += (colX(p.col) - pos.x) * Math.min(1, dt * 2.5); pos.z += (0.9 - pos.z) * Math.min(1, dt * 2.5);
        const top = Y[2] + 0.08 + heights[p.col] * 0.11;
        if (pos.y <= top + 0.05) { tint(p, ok); settle(p.col); under.intensity = 9; reset(p, Math.random() * 0.8); }
        break;
      }
    }
  }

  // captions for the plates, projected beside each one
  const labels = [...canvas.parentElement.querySelectorAll("[data-stage-label]")];
  const corner = new THREE.Vector3();
  function placeLabels() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    labels.forEach((el, i) => {
      rig.localToWorld(corner.set(-SIZE / 2, Y[i] + 0.05, SIZE / 2)).project(camera);
      el.style.transform = `translate(20px, ${(1 - corner.y) / 2 * h}px) translate(0, -50%)`;
      el.classList.toggle("on", i === active);
      el.hidden = false;
    });
  }

  // pointer and camera
  const aim = { x: 0, y: 0 }, look = { x: 0, y: 0 };
  addEventListener("pointermove", (e) => { aim.x = (e.clientX / innerWidth) * 2 - 1; aim.y = (e.clientY / innerHeight) * 2 - 1; }, { passive: true });
  let active = 0, focusY = Y[0];
  const target = new THREE.Vector3();
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  let t = 0, visible = true, raf = 0, last = performance.now();
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !reduce) loop(); }).observe(canvas);

  function frame(dt) {
    t += dt;
    look.x += (aim.x - look.x) * Math.min(1, dt * 2.5); look.y += (aim.y - look.y) * Math.min(1, dt * 2.5);
    // the camera travels down the stack to the active layer and orbits a little with the pointer
    focusY += (Y[active] - focusY) * Math.min(1, dt * 2.2);
    const az = 0.72 + look.x * 0.3 + Math.sin(t * 0.15) * 0.05, dist = 14, el = 0.5 - look.y * 0.1;
    camera.position.set(Math.sin(az) * dist * Math.cos(el), focusY + Math.sin(el) * dist, Math.cos(az) * dist * Math.cos(el));
    camera.lookAt(target.set(0, focusY - 0.2, 0));

    plates.forEach((pl, i) => {
      pl.glow += ((i === active ? 1 : 0) - pl.glow) * Math.min(1, dt * 4);
      pl.edgeMat.color.copy(paper).lerp(signal, pl.glow);
      pl.edgeMat.opacity = 0.3 + pl.glow * 0.6;
      pl.fill.opacity = 0.04 + pl.glow * 0.06;
    });
    // rule cells: dim, flashing where a payment is checked; the gate breathes
    for (let k = 0; k < N * N; k++) {
      flash[k] = Math.max(0, flash[k] - dt * 1.6);
      const b = 0.18 + flash[k] * 0.9 + (active === 0 ? 0.08 : 0);
      cellCol[k * 3] = paper.r * b; cellCol[k * 3 + 1] = paper.g * b; cellCol[k * 3 + 2] = paper.b * b;
    }
    cells.attributes.color.needsUpdate = true;
    gate.material.opacity = 0.5 + 0.4 * Math.sin(t * 3);
    scanner.scale.multiplyScalar(1 + dt * 5); scanner.material.opacity = Math.max(0, scanner.material.opacity - dt * 1.4);
    lanes.forEach((l) => { l.glow = Math.max(0, l.glow - dt * 1.2); l.mat.color.copy(paper).lerp(signal, l.glow); l.mat.opacity = 0.3 + l.glow * 0.6; l.hole.material.color.copy(l.mat.color); });
    under.intensity += (4 - under.intensity) * Math.min(1, dt * 2);
    if (ledgerFade > 0) {
      ledgerFade -= dt * 0.6;
      if (ledgerFade <= 0) { ledger.count = 0; heights.fill(0); const p = chainGeo.attributes.position; for (let k = 0; k < COLS; k++) p.setY(k, Y[2] + 0.1); p.needsUpdate = true; }
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

  [0, 1, 2, 2, 3, 4, 4, 5, 6, 7].forEach(settle); // the day already has a few entries
  if (reduce) {
    // one still frame: a few entries in the ledger and packets resting at each layer
    packets.forEach((p, i) => { p.mat.opacity = 1; p.halo.material.opacity = 0.5; p.m.position.set((i % 4 - 1.5) * 0.8, Y[i % 2] + 0.1, ((i / 4) | 0) * 0.6 - 1.2); if (i === 3) tint(p, signal); });
    frame(0);
  } else loop();

  return {
    setState(status, transferred) {
      active = LAYER_OF[status] ?? 0;
      if (transferred) under.intensity = 9;
      if (reduce) { focusY = Y[active]; frame(0); }
    },
  };
}
