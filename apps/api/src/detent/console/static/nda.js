// D-45: the NDA page's drawing pad. Pointer events cover mouse, touch and pen. On submit the drawing goes into
// the hidden `signature` field as a PNG data URL; the server checks it is a real PNG of a sensible size.
(() => {
  const pad = document.getElementById("nda-pad");
  const form = document.getElementById("nda-form");
  if (!pad || !form) return;
  const ctx = pad.getContext("2d");
  const field = document.getElementById("nda-signature");
  const warn = document.getElementById("nda-pad-error");
  let drawing = false;
  let drawn = false;
  ctx.lineWidth = 2.5;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#111";
  const point = (e) => {
    const r = pad.getBoundingClientRect();
    return [((e.clientX - r.left) * pad.width) / r.width, ((e.clientY - r.top) * pad.height) / r.height];
  };
  pad.addEventListener("pointerdown", (e) => {
    drawing = true;
    pad.setPointerCapture(e.pointerId);
    const [x, y] = point(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    e.preventDefault();
  });
  pad.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    const [x, y] = point(e);
    ctx.lineTo(x, y);
    ctx.stroke();
    drawn = true;
    warn.hidden = true;
  });
  const stop = () => { drawing = false; };
  pad.addEventListener("pointerup", stop);
  pad.addEventListener("pointercancel", stop);
  document.getElementById("nda-clear").addEventListener("click", () => {
    ctx.clearRect(0, 0, pad.width, pad.height);
    drawn = false;
    field.value = "";
  });
  form.addEventListener("submit", (e) => {
    if (!drawn) {
      e.preventDefault();
      warn.hidden = false;
      return;
    }
    field.value = pad.toDataURL("image/png");
  });
})();
