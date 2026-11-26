// The brand mark's geometry (B-03, Route), in the mark's own 48-unit viewBox, for the 3D scenes that build it
// from particles. One stroke, 7 wide with round caps and joins, along M9 41V7H23A17 17 0 0 1 23 41H17, and the
// orange point at (22, 27), radius 5.5. Keep in step with Mark.astro and apps/site/public/brand/mark.svg.
export const POINT = { cx: 22, cy: 27, r: 5.5 };
const HALF = 3.5; // half the stroke width
const seg = (x, y, ax, ay, bx, by) => {
  const dx = bx - ax, dy = by - ay;
  const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(x - (ax + t * dx), y - (ay + t * dy));
};
// distance from (x, y) to the route's centre line
const dist = (x, y) => Math.min(
  seg(x, y, 9, 41, 9, 7),
  seg(x, y, 9, 7, 23, 7),
  x >= 23 ? Math.abs(Math.hypot(x - 23, y - 24) - 17) : Infinity, // the right half-circle, top to bottom
  seg(x, y, 23, 41, 17, 41),
);
export const inD = (x, y) => dist(x, y) <= HALF;
export const inPoint = (x, y) => Math.hypot(x - POINT.cx, y - POINT.cy) <= POINT.r;
