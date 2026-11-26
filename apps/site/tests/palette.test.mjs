// Design-system checks (B-01): every palette meets WCAG AA on the pairs the site renders, every palette
// defines every role, the configured palette exists, and components use role tokens, never raw colours.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { palettes, PAIRS, contrast, paletteCss } from "../src/styles/palettes.mjs";
import config from "../site.config.mjs";

test("the configured palette exists", () => {
  assert.ok(palettes[config.palette], `site.config.mjs palette "${config.palette}"`);
  assert.match(paletteCss(config.palette), /^:root\{color-scheme:(dark|light);--bg:#/);
});

test("every palette defines the same roles", () => {
  const roles = Object.keys(palettes.current).sort();
  for (const [name, p] of Object.entries(palettes)) assert.deepEqual(Object.keys(p).sort(), roles, name);
});

test("every palette meets WCAG AA on the rendered pairs", () => {
  for (const [name, p] of Object.entries(palettes)) {
    for (const [fg, bg, min] of PAIRS) {
      const ratio = contrast(p[fg], p[bg]);
      assert.ok(ratio >= min, `${name}: ${fg} on ${bg} is ${ratio.toFixed(2)}:1, needs ${min}:1`);
    }
  }
});

test("components use colour roles, never raw hex or rgba", () => {
  const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
  const src = new URL("../src/", import.meta.url).pathname;
  for (const f of walk(src)) {
    if (!/\.(astro|css)$/.test(f)) continue;
    const body = readFileSync(f, "utf8").replace(/mask-image:[^;]*;/g, ""); // a mask's #000 is alpha, not colour
    assert.doesNotMatch(body, /#[0-9a-f]{3,8}\b|rgba?\(/i, `${f} uses a raw colour; use a role from palettes.mjs`);
  }
});
