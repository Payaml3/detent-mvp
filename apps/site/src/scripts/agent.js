// The AI agent, drawn in halftone dots (D-21). A plain lit bust is rendered off-screen; a halftone pass then
// redraws it as dots on a regular grid, each dot sized by the light it receives and tinted by the surface colour.
// An orange visor band marks it as an agent. It turns toward the pointer. Original work.
import {
  AmbientLight, Color, CylinderGeometry, DirectionalLight, Group, LatheGeometry, Mesh, MeshBasicMaterial,
  MeshLambertMaterial, OrthographicCamera, PerspectiveCamera, PlaneGeometry, Scene, ShaderMaterial, SphereGeometry,
  Vector2, WebGLRenderer, WebGLRenderTarget,
} from "three";

const halftoneFrag = /* glsl */ `
  uniform sampler2D tScene; uniform vec2 uRes; uniform float uCell; uniform float uTime;
  uniform vec3 uVisor; uniform vec3 uDeep; uniform vec3 uPale;
  varying vec2 vUv;
  void main() {
    vec2 px = vUv * uRes;
    vec2 cell = floor(px / uCell);
    vec2 centre = (cell + 0.5) * uCell;
    vec4 c = texture2D(tScene, centre / uRes);
    float lum = dot(c.rgb, vec3(0.3, 0.45, 0.25)) * c.a;
    bool visor = c.r > c.b * 1.4 && c.a > 0.5;
    float tone = visor ? 1.0 : pow(clamp((lum - 0.04) / 0.75, 0.0, 1.0), 0.7);
    // fade the bust out toward the bottom, like a print that dissolves
    float fade = smoothstep(0.02, 0.32, centre.y / uRes.y);
    float r = 0.52 * uCell * tone * fade * (0.96 + 0.04 * sin(uTime * 2.0 + cell.x * 0.7 + cell.y * 0.4));
    float d = length(px - centre);
    float a = smoothstep(r, r - 1.2, d) * step(0.03, lum);
    vec3 tint = visor ? uVisor : mix(uDeep, uPale, tone);
    gl_FragColor = vec4(tint, a);
  }`;
const quadVert = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const role = (name, fallback) =>
  new Color(getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim() || fallback);

function bust() {
  const g = new Group();
  const skin = new MeshLambertMaterial({ color: new Color("#FFFFFF") });
  // head
  const head = new Mesh(new SphereGeometry(1, 64, 48), skin);
  head.scale.set(0.62, 0.8, 0.7);
  head.position.set(0, 1.28, 0);
  // jaw and chin, slightly forward
  const jaw = new Mesh(new SphereGeometry(1, 48, 32), skin);
  jaw.scale.set(0.46, 0.4, 0.52);
  jaw.position.set(0, 0.82, 0.1);
  // neck and shoulders as one turned profile, flattened front to back
  const profile = [
    [0.0, -1.9], [1.7, -1.9], [1.72, -1.2], [1.62, -0.55], [1.38, -0.12], [0.95, 0.12], [0.5, 0.26], [0.3, 0.42], [0.29, 0.8], [0.0, 0.82],
  ].map(([x, y]) => new Vector2(x, y));
  const torso = new Mesh(new LatheGeometry(profile, 96), skin);
  torso.scale.set(1, 1, 0.5);
  // the agent's visor: a lit band across the eyes
  const visor = new Mesh(
    new CylinderGeometry(0.66, 0.66, 0.13, 64, 1, true, -1.15, 2.3),
    new MeshBasicMaterial({ color: new Color("#F2622E"), side: 2 }),
  );
  visor.scale.set(0.98, 1, 1.06);
  visor.position.set(0, 1.27, 0.02);
  // a nose, a brow and ears so the light can model a face
  const nose = new Mesh(new SphereGeometry(1, 24, 16), skin);
  nose.scale.set(0.09, 0.17, 0.12);
  nose.position.set(0, 1.08, 0.66);
  const brow = new Mesh(new SphereGeometry(1, 32, 16), skin);
  brow.scale.set(0.5, 0.1, 0.2);
  brow.position.set(0, 1.42, 0.48);
  const earL = new Mesh(new SphereGeometry(1, 16, 12), skin);
  earL.scale.set(0.07, 0.2, 0.13);
  earL.position.set(-0.6, 1.2, 0);
  const earR = earL.clone();
  earR.position.x = 0.6;
  g.add(head, jaw, torso, visor, nose, brow, earL, earR);
  return g;
}

export function mountAgent(canvas) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: "low-power" });
  } catch {
    canvas.remove();
    return null;
  }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = new Scene();
  const camera = new PerspectiveCamera(30, 1, 0.1, 50);
  camera.position.set(0, 0.3, 8.8);
  const figure = bust();
  scene.add(figure);
  scene.add(new AmbientLight(0xffffff, 0.16));
  const key = new DirectionalLight(0xffffff, 2.4);
  key.position.set(-2.5, 2.5, 5);
  const rim = new DirectionalLight(new Color("#6F97FF"), 0.9);
  rim.position.set(4, 1, -2);
  scene.add(key, rim);

  const target = new WebGLRenderTarget(2, 2);
  const quadScene = new Scene();
  const quadCam = new OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const halftone = new ShaderMaterial({
    vertexShader: quadVert, fragmentShader: halftoneFrag, transparent: true,
    uniforms: {
      tScene: { value: target.texture }, uRes: { value: new Vector2(2, 2) }, uCell: { value: 9 }, uTime: { value: 0 },
      // output colours come from the palette roles; the off-screen render keeps fixed colours to find the visor
      uVisor: { value: role("signal", "#F2622E") }, uDeep: { value: role("interactive", "#2F6BFF") }, uPale: { value: role("code", "#DCE6FF") },
    },
  });
  quadScene.add(new Mesh(new PlaneGeometry(2, 2), halftone));

  let px = 0, py = 0, yaw = -0.35, pitch = 0;
  function resize() {
    const dpr = Math.min(devicePixelRatio, 2);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    target.setSize(w * dpr, h * dpr);
    halftone.uniforms.uRes.value.set(w * dpr, h * dpr);
    halftone.uniforms.uCell.value = Math.round((w < 700 ? 7 : 9) * dpr);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  function frame(t) {
    const time = t / 1000;
    yaw += (-0.35 + px * 0.9 - yaw) * 0.05;
    pitch += (py * 0.25 - pitch) * 0.05;
    figure.rotation.set(pitch, yaw + (reduce ? 0 : Math.sin(time * 0.4) * 0.05), 0);
    figure.position.y = reduce ? 0 : Math.sin(time * 0.9) * 0.03;
    halftone.uniforms.uTime.value = reduce ? 0 : time;
    renderer.setRenderTarget(target);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.clear();
    renderer.render(quadScene, quadCam);
  }
  let raf = 0, running = false;
  const loop = (t) => { frame(t); raf = requestAnimationFrame(loop); };
  const start = () => { if (!running && !reduce) { running = true; raf = requestAnimationFrame(loop); } };
  const stop = () => { running = false; cancelAnimationFrame(raf); };
  resize();
  frame(0);
  addEventListener("resize", () => { resize(); frame(performance.now()); });
  addEventListener("pointermove", (e) => { px = e.clientX / innerWidth - 0.5; py = e.clientY / innerHeight - 0.5; if (reduce) frame(0); }, { passive: true });
  new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop())).observe(canvas);
  return { stop };
}
