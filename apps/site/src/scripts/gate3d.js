// "Sift then settle", in three dimensions. Three glass rules (decision, orchestration, operations) float
// in the hero. Payments fall through them as coins: most pass, some are held at the decision rule until a
// person approves (safety orange), some are blocked and leave the stack (graphite, never orange, B-02).
// What passes narrows to one rail and settles with a pulse. The stack turns toward the pointer.
// three.js is bundled with the site (no third-party requests). Colours come from the palette roles.
import * as THREE from "three";

const PLATE_Y = [1.35, 0, -1.35];
const LAYER_OF = { RECEIVED: -1, ESCALATED: 0, HELD: 0, READY: 0, SUBMITTED: 1, UNKNOWN: 1, FAILED: 1, CONFIRMED: 2 };

function roles() {
  const css = getComputedStyle(document.body);
  const get = (n, f) => css.getPropertyValue(`--${n}`).trim() || f;
  return { paper: get("paper", get("bg")), signal: get("signal"), ok: get("ok"), ink: get("ink", get("text")) };
}

export function mountGate(canvas) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { return null; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  const col = { paper: new THREE.Color(c.paper), signal: new THREE.Color(c.signal), ok: new THREE.Color(c.ok), ink: new THREE.Color(c.ink) };

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, 0.4, 10.5);
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(3, 6, 5); scene.add(key);
  const rim = new THREE.PointLight(col.signal, 6, 12); rim.position.set(0, -2.6, 1.5); scene.add(rim);

  const rig = new THREE.Group();
  rig.rotation.set(0.42, -0.62, 0);
  scene.add(rig);

  // the three rules: thin glass plates with lit edges
  const plates = PLATE_Y.map((y, i) => {
    const size = 3.4 - i * 0.55;
    const geo = new THREE.BoxGeometry(size, 0.05, size);
    const fill = new THREE.MeshStandardMaterial({ color: col.paper, transparent: true, opacity: 0.07, roughness: 0.2, metalness: 0.1, depthWrite: false });
    const mesh = new THREE.Mesh(geo, fill);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: col.paper, transparent: true, opacity: 0.4 }));
    mesh.add(edges);
    mesh.position.y = y;
    rig.add(mesh);
    return { mesh, fill, edges, size, glow: 0 };
  });

  // the rail and the settle ring
  const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 2.45, 8), new THREE.MeshBasicMaterial({ color: col.signal, transparent: true, opacity: 0.55 }));
  rail.position.y = -1.225; rig.add(rail);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.025, 12, 64), new THREE.MeshBasicMaterial({ color: col.signal }));
  ring.rotation.x = Math.PI / 2; ring.position.y = -2.45; rig.add(ring);
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.012, 8, 64), new THREE.MeshBasicMaterial({ color: col.signal, transparent: true, opacity: 0 }));
  halo.rotation.x = Math.PI / 2; halo.position.y = -2.45; rig.add(halo);

  // payments as coins
  const coinGeo = new THREE.CylinderGeometry(0.15, 0.15, 0.04, 40);
  const coins = Array.from({ length: 26 }, (_, i) => {
    const mat = new THREE.MeshStandardMaterial({ color: col.paper, roughness: 0.35, metalness: 0.55, transparent: true, opacity: 1 });
    const m = new THREE.Mesh(coinGeo, mat);
    rig.add(m);
    const coin = { m, mat, phase: "fall", t: 0, vx: 0, vz: 0, fate: "pass", layer: 0 };
    spawn(coin, i * 0.38);
    return coin;
  });

  function spawn(coin, delay = 0) {
    const r = Math.random();
    coin.fate = r < 0.66 ? "pass" : r < 0.86 ? "hold" : "block";
    coin.phase = "wait"; coin.t = -delay; coin.layer = 0;
    coin.m.position.set((Math.random() - 0.5) * 2.4, 3.1, (Math.random() - 0.5) * 2.4);
    coin.m.rotation.set(Math.random(), 0, Math.random() * 0.4);
    coin.mat.color.copy(col.paper); coin.mat.opacity = 0;
  }

  let settled = 0;
  function step(coin, dt) {
    const p = coin.m.position;
    coin.t += dt;
    if (coin.phase === "wait") { if (coin.t >= 0) { coin.phase = "fall"; } else return; }
    coin.mat.opacity = Math.min(1, coin.mat.opacity + dt * 2);
    coin.m.rotation.y += dt * 1.4;
    if (coin.phase === "fall") {
      p.y -= dt * 1.25;
      // after the decision rule, payments narrow toward the one rail
      if (coin.layer >= 1) { p.x += (0 - p.x) * dt * 1.6; p.z += (0 - p.z) * dt * 1.6; }
      const target = PLATE_Y[coin.layer];
      if (target !== undefined && p.y <= target + 0.05) {
        p.y = target + 0.05;
        if (coin.layer === 0 && coin.fate === "block") { coin.phase = "eject"; coin.t = 0; const a = Math.atan2(p.z, p.x) || Math.random() * 6.28; coin.vx = Math.cos(a) * 2.2; coin.vz = Math.sin(a) * 2.2; return; }
        if (coin.layer === 0 && coin.fate === "hold") { coin.phase = "held"; coin.t = 0; return; }
        coin.phase = "pause"; coin.t = 0;
      }
      if (coin.layer > 2 && p.y <= -2.45) { settled++; halo.material.opacity = 0.9; halo.scale.setScalar(1); spawn(coin, Math.random() * 0.8); }
    } else if (coin.phase === "pause") {
      if (coin.t > 0.22) { coin.layer++; coin.phase = "fall"; if (coin.layer === 3) coin.mat.color.lerp(col.ok, 0.6); }
    } else if (coin.phase === "held") {
      coin.mat.color.lerp(col.signal, Math.min(1, dt * 4));
      coin.m.position.y = PLATE_Y[0] + 0.05 + Math.sin(coin.t * 5) * 0.02;
      if (coin.t > 1.8) { coin.mat.color.copy(col.paper); coin.phase = "pause"; coin.t = 0; }
    } else if (coin.phase === "eject") {
      coin.mat.color.lerp(col.ink, Math.min(1, dt * 5));
      p.x += coin.vx * dt; p.z += coin.vz * dt; p.y -= dt * 2.4 * coin.t;
      coin.mat.opacity = Math.max(0, 1 - coin.t * 0.9);
      if (coin.t > 1.2) spawn(coin, Math.random() * 0.6);
    }
  }

  // pointer: the stack turns toward it
  const aim = { x: 0, y: 0 }, look = { x: 0, y: 0 };
  const onMove = (e) => { aim.x = (e.clientX / innerWidth) * 2 - 1; aim.y = (e.clientY / innerHeight) * 2 - 1; };
  addEventListener("pointermove", onMove, { passive: true });

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  let active = -1, visible = true, last = performance.now(), raf = 0;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !reduce) loop(); }).observe(canvas);

  function frame(dt) {
    look.x += (aim.x - look.x) * Math.min(1, dt * 3);
    look.y += (aim.y - look.y) * Math.min(1, dt * 3);
    rig.rotation.y = -0.62 + look.x * 0.55;
    rig.rotation.x = 0.42 + look.y * 0.22;
    rig.position.x = 0.55 + look.x * 0.15;
    plates.forEach((pl, i) => {
      pl.glow += ((i === active ? 1 : 0) - pl.glow) * Math.min(1, dt * 4);
      pl.edges.material.color.copy(col.paper).lerp(col.signal, pl.glow);
      pl.edges.material.opacity = 0.4 + pl.glow * 0.5;
      pl.fill.opacity = 0.07 + pl.glow * 0.08;
      pl.mesh.position.y = PLATE_Y[i] + Math.sin(performance.now() / 1400 + i) * 0.03;
    });
    halo.scale.multiplyScalar(1 + dt * 1.6);
    halo.material.opacity = Math.max(0, halo.material.opacity - dt * 1.2);
    for (const coin of coins) step(coin, dt);
    renderer.render(scene, camera);
  }

  function loop() {
    cancelAnimationFrame(raf);
    const tick = (now) => {
      if (!visible) return;
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      frame(dt);
      raf = requestAnimationFrame(tick);
    };
    last = performance.now();
    raf = requestAnimationFrame(tick);
  }

  if (reduce) {
    // one still frame: coins resting at each rule
    coins.forEach((coin, i) => { coin.layer = i % 3; coin.mat.opacity = 1; coin.phase = "pause"; coin.t = -99; coin.m.position.y = PLATE_Y[coin.layer] + 0.05; if (coin.layer > 0) { coin.m.position.x *= 0.4; coin.m.position.z *= 0.4; } });
    frame(0); renderer.render(scene, camera);
  } else loop();

  return {
    setState(status, transferred) {
      active = LAYER_OF[status] ?? -1;
      if (transferred) { halo.material.opacity = 1; halo.scale.setScalar(1); }
      if (reduce) frame(0);
    },
    settledCount: () => settled,
  };
}
