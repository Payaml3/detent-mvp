// The hero's live mark: the Route mark (B-03) built from a few thousand particles, each one a payment.
// On load they sift down from above and settle into the monogram; the orange point in the counter is the
// one outcome the rules settle on. The mark turns toward the pointer and parts around it, then closes
// again. Each sent example payment pulses the point. three.js is bundled with the site; colours come from
// the palette roles. Original work, drawn from the Route mark geometry (markShape.js) (viewBox 48).
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

export function mountMark(canvas, { count = 7000 } = {}) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch { return null; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const c = roles();
  const paper = new THREE.Color(c.paper), signal = new THREE.Color(c.signal);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
  camera.position.set(0, 0, 150);

  // home positions: the D, with depth, and the settled point in front of it
  const S = 1.15; // world units per viewBox unit
  const home = [], start = [], delay = [], isPoint = [];
  const dCount = Math.floor(count * 0.88);
  while (home.length < dCount) {
    const x = Math.random() * 48, y = Math.random() * 48;
    if (!inD(x, y)) continue;
    home.push(new THREE.Vector3((x - 24) * S, (24 - y) * S, (Math.random() - 0.5) * 7));
    isPoint.push(false);
  }
  while (home.length < count) {
    const x = Math.random() * 48, y = Math.random() * 48;
    if (!inPoint(x, y)) continue;
    home.push(new THREE.Vector3((x - 24) * S, (24 - y) * S, 2.5 + Math.random() * 3));
    isPoint.push(true);
  }
  for (const h of home) {
    start.push(new THREE.Vector3(h.x + (Math.random() - 0.5) * 30, 70 + Math.random() * 60, h.z + (Math.random() - 0.5) * 20));
    delay.push(Math.random() * 1.6 + (h.y < 0 ? 0.3 : 0)); // the lower half settles a little later, like a fill
  }

  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
  const vel = new Float32Array(count * 3);
  home.forEach((h, i) => {
    const p = reduce ? h : start[i];
    pos.set([p.x, p.y, p.z], i * 3);
    const k = isPoint[i] ? signal : paper.clone().multiplyScalar(0.55 + Math.random() * 0.45);
    col.set([k.r, k.g, k.b], i * 3);
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  const mat = new THREE.PointsMaterial({ size: 1.5, map: dotTexture(), vertexColors: true, transparent: true, depthWrite: false, sizeAttenuation: true });
  const points = new THREE.Points(geo, mat);
  points.frustumCulled = false; // the particles start far above their resting place
  const rig = new THREE.Group();
  rig.add(points);
  rig.position.x = 7;
  scene.add(rig);

  // pointer: the mark turns toward it, and particles near it part
  const aim = { x: 0, y: 0 }, look = { x: 0, y: 0 };
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  const hit = new THREE.Vector3(), local = new THREE.Vector3();
  let near = false;
  const onMove = (e) => {
    aim.x = (e.clientX / innerWidth) * 2 - 1; aim.y = (e.clientY / innerHeight) * 2 - 1;
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    near = Math.abs(ndc.x) < 1.2 && Math.abs(ndc.y) < 1.2;
  };
  addEventListener("pointermove", onMove, { passive: true });
  canvas.ownerDocument.addEventListener("pointerleave", () => { near = false; });

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
    rig.rotation.y = -0.28 + look.x * 0.5;
    rig.rotation.x = 0.06 + look.y * 0.22;

    if (near) {
      ray.setFromCamera(ndc, camera);
      ray.ray.intersectPlane(plane, hit);
      local.copy(hit); rig.worldToLocal(local);
    }
    pulse = Math.max(0, pulse - dt * 0.9);
    const R = 9, R2 = R * R;
    for (let i = 0; i < count; i++) {
      const j = i * 3, h = home[i];
      const settle = Math.min(1, Math.max(0, (t - delay[i]) / 1.4));
      // target: home, breathing a little; the point swells with each pulse
      let tx = h.x, ty = h.y, tz = h.z + Math.sin(t * 1.2 + i) * 0.25;
      if (isPoint[i]) { const s = 1 + pulse * 0.35; tx = POINT_X + (h.x - POINT_X) * s; ty = POINT_Y + (h.y - POINT_Y) * s; }
      if (settle < 1) {
        const e = 1 - Math.pow(1 - settle, 3), sp = start[i];
        tx = sp.x + (tx - sp.x) * e; ty = sp.y + (ty - sp.y) * e; tz = sp.z + (tz - sp.z) * e;
      }
      // spring toward the target
      vel[j] += (tx - pos[j]) * 14 * dt; vel[j + 1] += (ty - pos[j + 1]) * 14 * dt; vel[j + 2] += (tz - pos[j + 2]) * 14 * dt;
      if (near && settle >= 1) {
        const dx = pos[j] - local.x, dy = pos[j + 1] - local.y, d2 = dx * dx + dy * dy;
        if (d2 < R2) { const f = (1 - d2 / R2) * 160 * dt / Math.sqrt(d2 + 0.01); vel[j] += dx * f; vel[j + 1] += dy * f; vel[j + 2] += 6 * f; }
      }
      vel[j] *= 0.86; vel[j + 1] *= 0.86; vel[j + 2] *= 0.86;
      pos[j] += vel[j] * dt * 4; pos[j + 1] += vel[j + 1] * dt * 4; pos[j + 2] += vel[j + 2] * dt * 4;
    }
    geo.attributes.position.needsUpdate = true;
    renderer.render(scene, camera);
  }
  const POINT_X = (POINT.cx - 24) * S, POINT_Y = (24 - POINT.cy) * S;

  function loop() {
    cancelAnimationFrame(raf);
    last = performance.now();
    const tick = (now) => {
      if (!visible) return;
      const dt = Math.min(0.033, (now - last) / 1000); last = now;
      frame(dt);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  if (reduce) { t = 10; renderer.render(scene, camera); } else loop();

  return {
    setState(status, transferred) { if (transferred) pulse = 1; if (reduce) renderer.render(scene, camera); },
  };
}
