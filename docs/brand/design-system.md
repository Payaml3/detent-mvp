# Dekernai design system

Status: palette **Graphite and safety orange (B-02)**. Roles, mark and art **Proposed (D-39)**.

## Colour roles

Components never use raw colours. They use role tokens, which come from one palette in
`apps/site/src/styles/palettes.mjs`; `layouts/Base.astro` writes the chosen palette onto `:root`. A test
(`apps/site/tests/palette.test.mjs`) fails the build if a component uses a raw hex or rgba value, or if any
palette misses WCAG AA on a pair the site renders.

| Role | Used for |
|---|---|
| `--bg`, `--bg-alt`, `--surface`, `--surface-sunk`, `--surface-hover` | Page and panel backgrounds |
| `--line`, `--line-strong` | Borders, wires, dividers |
| `--text`, `--text-soft` | Body and secondary text |
| `--signal`, `--signal-hover`, `--signal-press`, `--on-signal` | The one call-to-action colour, and text on it |
| `--interactive`, `--interactive-strong`, `--interactive-soft`, `--on-interactive`, `--interactive-deep` | Links, active and selected states, the diagram panel |
| `--ok`, `--wait`, `--danger`, `--danger-line` | Status: CONFIRMED; UNKNOWN, ESCALATED, HELD; BLOCKED, REJECTED |
| `--code`, `--code-key`, `--plot` | Code samples and diagram strokes |
| `--settle` | The settled dot in the mark and the art |
| `--accent` | Decoration only: the art's rule lines, hairlines, ornaments. Never text |

Status colours keep their meaning in every palette: confirmed is green, waiting is amber, blocked is red (graphite in the live palette, where orange means action).
A block is never told by colour alone: the status label always shows, and BLOCKED, REJECTED and
FAILED_FINAL carry a cross icon in place of the dot, on the site, in the console and in the art.

## Palettes

| Key | Name | Scheme | Signal | Interactive |
|---|---|---|---|---|
| `current` | Detent colours (D-18), kept as a reference | dark | orange `#F2622E` | blue `#2F6BFF` |
| `a` | Settled ink | dark | sift teal `#14B8A6` | verdict blue `#2F5BEA` |
| **`graphite`** | **Graphite and safety orange (B-02), live** | light | safety orange `#FF4A1F` | orange text `#C2360F` |
| `c` | Night console | dark | decision violet `#6D5BFF` | clear cyan `#22D3EE` |

The live palette in full (values in `design/tokens.json`): graphite `#18191B` (text, blocked), steel `#232427`,
paper `#F3F3F1` (page), white surfaces, safety orange `#FF4A1F` as a fill only with `#0A0A0A` text on it (the
call to action, the console's primary button, focus, the settled dot), `#C2360F` for orange text and links,
confirmed green `#237A46`, unknown amber `#F2C94C` as a fill with `#1B1405` text (`#7A5600` as amber text).
Blocked is a graphite pill with a cross icon and a white label: never orange, never colour alone.
The console (`apps/api/src/detent/console/static/console.css`) and the favicon use the same values.

## Mark: sift then settle

`apps/site/src/components/Mark.astro`. Five dots, then three, above a rule; one larger dot below it in
`--settle`. It reads as many inputs weighed against the rules and one outcome settled, the meaning of
*dēcernere* ("to sift, then decide"). The dots use `currentColor`, so the mark works on any background.

## Art

`apps/site/src/scripts/sift.js` (replaces the D-20 detent wheel). Payments fall as halftone dots through three
dotted rules, the decision, orchestration and operations layers. Some are held at a rule (amber), some are
blocked and drop away (red), the rest narrow to one settled point. The example payment in the "What goes
wrong?" demo stops at the rule for its current state, and the settled point pulses once when it is sent.
Canvas 2D, no WebGL needed; it honours reduced motion. The hero's AI-agent bust (D-21) stays and now takes
its colours from the palette.

## Type and spacing

Unchanged (D-18): Space Grotesk for headings, Inter for body, JetBrains Mono for IDs, hashes and code. Five
type steps, spacing and motion tokens are in `apps/site/src/styles/tokens.css`.

## Wording

See `founder/brand.md`. Key rule: the rules decide, never the AI.
