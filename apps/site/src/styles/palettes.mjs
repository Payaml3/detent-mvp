// Colour roles for the design system (B-01). Components use only these role tokens (`--bg`,
// `--signal`, ...), never raw hex, so a palette is one object here and one value in site.config.mjs.
// The founder chose B, Parchment and seal (B-02); site.config.mjs selects it. "current" (the D-18 colours),
// A and C stay as references and keep passing the same checks. tests/palette.test.mjs checks every palette against WCAG AA.
//
// Roles
//   bg, bgAlt, surface, surfaceSunk, surfaceHover  page and panel backgrounds, darkest to lightest step
//   line, lineStrong                                 borders and wires
//   text, textSoft                                   body text and secondary text
//   signal, signalHover, signalPress, onSignal       the one call-to-action colour and the text on it
//   interactive, interactiveStrong, interactiveSoft, onInteractive  links, active and selected states;
//                                    soft is link text on the page, onInteractive is text on a selected state,
//                                    interactiveDeep is the blueprint panel behind diagrams
//   ok, wait, danger, dangerLine                     status: CONFIRMED, UNKNOWN/ESCALATED, BLOCKED/REJECTED
//   code, codeKey, plot                              code samples and diagram strokes
//   settle                                           the settled dot in the "sift then settle" mark
//   accent                                           decoration only (rules, hairlines, ornaments), never text
//   scheme                                           "dark" or "light"; the canvas art blends to suit it

export const palettes = {
  current: {
    label: "Current (Detent, D-18)",
    scheme: "dark",
    bg: "#070C1A", bgAlt: "#0F1629", surface: "#141D36", surfaceSunk: "#0D1530", surfaceHover: "#18233F",
    line: "#24304F", lineStrong: "#2A4386",
    text: "#F6F5F0", textSoft: "#B9BFCE",
    signal: "#F2622E", signalHover: "#FF7240", signalPress: "#D9521F", onSignal: "#070C1A",
    interactive: "#2F6BFF", interactiveStrong: "#1F4FCC", interactiveSoft: "#8FB0FF", onInteractive: "#F6F5F0", interactiveDeep: "#10307A",
    ok: "#7FD1A4", wait: "#F2B84B", danger: "#FF8A64", dangerLine: "#8A3A22",
    code: "#DCE6FF", codeKey: "#A9C2FF", plot: "#CFE0FF",
    settle: "#F2622E", accent: "#C9935F",
  },
  a: {
    label: "A · Settled ink",
    scheme: "dark",
    bg: "#070C1A", bgAlt: "#0F1629", surface: "#141D36", surfaceSunk: "#0D1530", surfaceHover: "#18233F",
    line: "#24304F", lineStrong: "#2A4386",
    text: "#F6F5F0", textSoft: "#B9BFCE",
    signal: "#14B8A6", signalHover: "#2DD4BF", signalPress: "#0F9A8B", onSignal: "#070C1A",
    interactive: "#2F5BEA", interactiveStrong: "#2F5BEA", interactiveSoft: "#93AEFF", onInteractive: "#F6F5F0", interactiveDeep: "#12307F",
    ok: "#3FB37F", wait: "#F2B84B", danger: "#F2766B", dangerLine: "#8C2F28",
    code: "#DCE6FF", codeKey: "#A9C2FF", plot: "#CFE0FF",
    settle: "#14B8A6", accent: "#14B8A6",
  },
  b: {
    label: "B · Parchment and seal",
    scheme: "light",
    bg: "#F4EFE6", bgAlt: "#EDE6D8", surface: "#FFFDF8", surfaceSunk: "#EAE2D2", surfaceHover: "#E3D9C6",
    line: "#D8CDB8", lineStrong: "#C9935F",
    text: "#14161F", textSoft: "#4E5160",
    signal: "#B3261E", signalHover: "#C7342B", signalPress: "#931E18", onSignal: "#FFFFFF",
    interactive: "#2E5AAC", interactiveStrong: "#2E5AAC", interactiveSoft: "#2E5AAC", onInteractive: "#FFFFFF", interactiveDeep: "#DCE3F0",
    ok: "#23714D", wait: "#8A5A00", // amber #E0A33A is the fill tone; as text it fails AA on parchment
    danger: "#B3261E", dangerLine: "#D99A94",
    code: "#14161F", codeKey: "#2E5AAC", plot: "#5A4A30",
    settle: "#B3261E", accent: "#C9935F",
  },
  c: {
    label: "C · Night console",
    scheme: "dark",
    bg: "#070C1A", bgAlt: "#0F1629", surface: "#141D36", surfaceSunk: "#0D1530", surfaceHover: "#18233F",
    line: "#24304F", lineStrong: "#3A3F86",
    text: "#EDEFF5", textSoft: "#B4BACB",
    signal: "#6D5BFF", signalHover: "#5E4BF5", signalPress: "#4A39CC", onSignal: "#FFFFFF",
    interactive: "#22D3EE", interactiveStrong: "#5847E6", interactiveSoft: "#8BE7F5", onInteractive: "#FFFFFF", interactiveDeep: "#1E1A5C",
    ok: "#34D399", wait: "#F2B84B", danger: "#F87171", dangerLine: "#8A2A2A",
    code: "#E2E8FF", codeKey: "#8BE7F5", plot: "#C9D2FF",
    settle: "#22D3EE", accent: "#22D3EE",
  },
};

const kebab = (k) => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/** The `:root` block for one palette: every role as a custom property, plus `color-scheme`. */
export function paletteCss(name) {
  const p = palettes[name];
  if (!p) throw new Error(`unknown palette "${name}" (choose one of ${Object.keys(palettes).join(", ")})`);
  const vars = Object.entries(p).filter(([k]) => k !== "label" && k !== "scheme").map(([k, v]) => `--${kebab(k)}:${v}`);
  return `:root{color-scheme:${p.scheme};${vars.join(";")}}`;
}

// WCAG 2.2 relative luminance and contrast ratio
function lum(hex) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}
export function contrast(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

/** The pairs the site actually renders, with the WCAG AA minimum each must meet. */
export const PAIRS = [
  ["text", "bg", 4.5], ["text", "surface", 4.5], ["textSoft", "bg", 4.5], ["textSoft", "surface", 4.5],
  ["onSignal", "signal", 4.5], ["onSignal", "signalHover", 4.5],
  ["interactiveSoft", "bg", 4.5], ["interactiveSoft", "surface", 4.5], ["onInteractive", "interactiveStrong", 4.5],
  ["ok", "surface", 4.5], ["wait", "surface", 4.5], ["danger", "surface", 4.5],
  ["code", "surfaceSunk", 4.5], ["codeKey", "surfaceSunk", 4.5],
  ["signal", "bg", 3], ["interactive", "bg", 3], ["lineStrong", "bg", 1.5],
];
