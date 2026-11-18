// The detent, drawn in light: an escape wheel rendered as halftone dots, held by a catch with an orange jewel.
// While a payment is held the catch locks the wheel; when a payment is sent the catch lifts and the wheel
// advances exactly one tooth. Original work (D-19, D-20).
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, Color, Group, PerspectiveCamera, Points, Scene,
  ShaderMaterial, WebGLRenderer,
} from "three";

const TEETH = 15;
const TOOTH = (Math.PI * 2) / TEETH;
const HELD = new Set(["RECEIVED", "ESCALATED", "HELD", "UNKNOWN", "BLOCKED", "READY"]);

const vert = /* glsl */ `
  attribute float size; attribute vec3 tint; attribute float seed;
  uniform float uTime; uniform float uScale;
  varying vec3 vTint; varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float tw = 0.85 + 0.15 * sin(uTime * 1.3 + seed * 6.2831);
    gl_PointSize = size * tw * uScale / -mv.z;
    vTint = tint; vAlpha = 0.55 + 0.45 * tw;
    gl_Position = projectionMatrix * mv;
  }`;
const frag = /* glsl */ `
  varying vec3 vTint; varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5; float d = length(c);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.18, d) * vAlpha;
    gl_FragColor = vec4(vTint, a);
  }`;

function toothProfile(theta) {
  // a hooked escape tooth: the radius climbs along each tooth, then drops at the locking face
  const phase = (((theta % TOOTH) + TOOTH) % TOOTH) / TOOTH;
  return phase < 0.78 ? 1.85 + 0.55 * (phase / 0.78) ** 1.4 : 1.85;
}

function wheelDots() {
  const out = [];
  const step = 0.048;
  const light = { x: -0.6, y: 0.8 };
  for (let x = -2.5; x <= 2.5; x += step) {
    for (let y = -2.5; y <= 2.5; y += step) {
      const r = Math.hypot(x, y);
      const t = Math.atan2(y, x);
      const hub = r < 0.38;
      const rim = r > 1.52 && r < toothProfile(t);
      let spoke = false;
      if (r >= 0.38 && r <= 1.52) {
        for (let k = 0; k < 5; k++) {
          const a = (k * Math.PI * 2) / 5 + 0.3;
          const dist = Math.abs(Math.sin(t - a)) * r;
          if (dist < 0.09 && Math.cos(t - a) > 0) spoke = true;
        }
      }
      if (!(hub || rim || spoke)) continue;
      // halftone: dot size follows the light falling across the face
      const lit = 0.5 + 0.5 * ((x * light.x + y * light.y) / 2.5);
      const jx = (Math.random() - 0.5) * 0.012;
      const jy = (Math.random() - 0.5) * 0.012;
      out.push({ x: x + jx, y: y + jy, z: (Math.random() - 0.5) * 0.06, size: 0.025 + 0.085 * lit * lit, lit });
    }
  }
  return out;
}

function catchDots() {
  // the detent: a slim lever from its pivot to a jewel resting against a tooth's locking face
  const out = [];
  const jewel = { x: 2.02 * Math.cos(-0.28), y: 2.02 * Math.sin(-0.28) };
  const pivot = { x: 3.9, y: -2.35 };
  const len = Math.hypot(jewel.x - pivot.x, jewel.y - pivot.y);
  const ux = (jewel.x - pivot.x) / len, uy = (jewel.y - pivot.y) / len;
  for (let s = 0; s <= len; s += 0.055) {
    for (let w = -0.07; w <= 0.07; w += 0.055) {
      out.push({ x: pivot.x + ux * s - uy * w, y: pivot.y + uy * s + ux * w, z: 0, size: 0.09, lit: 0.6 });
    }
  }
  for (let a = 0; a < Math.PI * 2; a += 0.35) out.push({ x: pivot.x + 0.16 * Math.cos(a), y: pivot.y + 0.16 * Math.sin(a), z: 0, size: 0.1, lit: 0.8 });
  return { dots: out, jewel, pivot };
}

function makePoints(dots, colourOf, scale) {
  const g = new BufferGeometry();
  const n = dots.length;
  const pos = new Float32Array(n * 3), size = new Float32Array(n), tint = new Float32Array(n * 3), seed = new Float32Array(n);
  dots.forEach((d, i) => {
    pos.set([d.x, d.y, d.z], i * 3);
    size[i] = d.size;
    const c = colourOf(d);
    tint.set([c.r, c.g, c.b], i * 3);
    seed[i] = Math.random();
  });
  g.setAttribute("position", new BufferAttribute(pos, 3));
  g.setAttribute("size", new BufferAttribute(size, 1));
  g.setAttribute("tint", new BufferAttribute(tint, 3));
  g.setAttribute("seed", new BufferAttribute(seed, 1));
  const m = new ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthWrite: false, blending: AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uScale: { value: scale } },
  });
  return new Points(g, m);
}

export function mountWheel(canvas, frameOpts = { x: 0.9, y: 0, scale: 0.7 }) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  } catch {
    canvas.remove();
    return null;
  }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = new Scene();
  const camera = new PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, 0, 10);

  const rig = new Group();
  scene.add(rig);
  const wheelGroup = new Group();
  const catchGroup = new Group();
  rig.add(wheelGroup, catchGroup);

  const blue = new Color("#2F6BFF"), pale = new Color("#DCE6FF"), paper = new Color("#B9BFCE"), orange = new Color("#F2622E");
  const scale = 700;
  const wheel = makePoints(wheelDots(), (d) => blue.clone().lerp(pale, d.lit), scale);
  wheelGroup.add(wheel);

  const { dots: cDots, jewel, pivot } = catchDots();
  const lever = makePoints(cDots, () => paper.clone().multiplyScalar(0.8), scale);
  const jewelDots = [];
  for (let i = 0; i < 70; i++) {
    const a = Math.random() * Math.PI * 2, r = Math.random() ** 0.6 * 0.15;
    jewelDots.push({ x: jewel.x + r * Math.cos(a), y: jewel.y + r * Math.sin(a), z: 0.02, size: 0.12 + Math.random() * 0.08, lit: 1 });
  }
  const jewelPts = makePoints(jewelDots, () => orange, scale);
  // the catch rotates about its pivot: move geometry so the pivot is the group origin
  [lever, jewelPts].forEach((p) => { p.position.set(-pivot.x, -pivot.y, 0); });
  catchGroup.position.set(pivot.x, pivot.y, 0);
  catchGroup.add(lever, jewelPts);

  const dust = [];
  for (let i = 0; i < 900; i++) {
    dust.push({ x: (Math.random() - 0.5) * 22, y: (Math.random() - 0.5) * 14, z: -Math.random() * 12, size: 0.03 + Math.random() * 0.05, lit: Math.random() });
  }
  const dustPts = makePoints(dust, (d) => pale.clone().multiplyScalar(0.25 + 0.35 * d.lit), scale);
  scene.add(dustPts);
  const materials = [wheel, lever, jewelPts, dustPts].map((p) => p.material);

  // motion state
  let angle = 0, target = 0, lift = 0, liftTarget = 0, pointerX = 0, pointerY = 0, progress = 0;
  let releaseAt = -1;

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    rig.position.set(frameOpts.x * Math.min(1, camera.aspect), frameOpts.y, 0);
    rig.scale.setScalar(frameOpts.scale * Math.min(1, camera.aspect * 0.9 + 0.1));
    materials.forEach((m) => (m.uniforms.uScale.value = scale * (h / 900) * Math.min(devicePixelRatio, 2)));
  }

  function frame(t) {
    const time = t / 1000;
    materials.forEach((m) => (m.uniforms.uTime.value = time));
    if (releaseAt >= 0) {
      const k = (t - releaseAt) / 1000;
      // lift the catch, let the wheel advance one tooth, drop the catch
      liftTarget = k < 0.9 ? 0.16 : 0;
      if (k > 0.25 && target === angle) target = angle - TOOTH;
      if (k > 1.6) releaseAt = -1;
    }
    angle += (target - angle) * 0.07;
    if (Math.abs(target - angle) < 0.0005) angle = target;
    lift += (liftTarget - lift) * 0.12;
    const recoil = releaseAt < 0 ? Math.sin(time * 2.2) * 0.004 : 0;
    wheelGroup.rotation.z = angle + recoil;
    catchGroup.rotation.z = lift;
    rig.rotation.y = -0.38 + progress * 0.55 + pointerX * 0.08;
    rig.rotation.x = 0.22 - progress * 0.25 + pointerY * 0.05;
    camera.position.z = 10 - progress * 1.8;
    dustPts.rotation.y = time * 0.01;
    renderer.render(scene, camera);
  }

  let running = false, raf = 0;
  const loop = (t) => { frame(t); raf = requestAnimationFrame(loop); };
  const start = () => { if (!running && !reduce) { running = true; raf = requestAnimationFrame(loop); } };
  const stop = () => { running = false; cancelAnimationFrame(raf); };

  resize();
  frame(0);
  addEventListener("resize", () => { resize(); if (!running) frame(performance.now()); });
  addEventListener("scroll", () => {
    // 0 when the canvas enters from below, 1 when it leaves at the top
    const r = canvas.getBoundingClientRect();
    progress = Math.min(1, Math.max(0, 1 - (r.bottom / (innerHeight + r.height))));
  }, { passive: true });
  addEventListener("pointermove", (e) => {
    pointerX = e.clientX / innerWidth - 0.5;
    pointerY = e.clientY / innerHeight - 0.5;
  }, { passive: true });
  new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop())).observe(canvas);

  return {
    setState(status, transferred) {
      const jewelColour = status === "BLOCKED" ? new Color("#FF4A1C") : orange;
      const tint = jewelPts.geometry.getAttribute("tint");
      for (let i = 0; i < tint.count; i++) tint.setXYZ(i, jewelColour.r, jewelColour.g, jewelColour.b);
      tint.needsUpdate = true;
      if (transferred) {
        releaseAt = performance.now();
        if (reduce) { angle = target = angle - TOOTH; frame(performance.now()); }
      } else {
        liftTarget = HELD.has(status) ? 0 : 0.05;
      }
      if (!running) frame(performance.now());
    },
  };
}
