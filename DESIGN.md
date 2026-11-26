# DekernAI design system

The one place that says how DekernAI looks and behaves, for the marketing site (`apps/site`) and the back-office console (`apps/api/src/detent/console`). The detail for the site's colour roles and art is in `docs/brand/design-system.md`. Decision: D-39.

## Principle

The rules decide, never the AI. The design shows that: every payment has one visible state, every decision has a reason you can read, and nothing final is shown by colour alone.

## One source of tokens

`design/tokens.json` holds every colour, type size, space, radius, control size and motion value.

| Consumer | How it reads the tokens |
|---|---|
| Site | `apps/site/src/styles/palettes.mjs` spreads `tokens.site` into the live palette; `Base.astro` writes them to `:root` |
| Console | `python tools/build_tokens.py` renders `console/static/tokens.css`; `console.css` imports it |

To change the palette, edit `design/tokens.json`, run `python tools/build_tokens.py`, then `npm test` in `apps/site` and the console tests. No component changes.

Token names are roles, not colours (`stop`, not "red"), so a new palette swaps values only.

**Palette status:** the founder is choosing a new palette (2026-11-26). The values now in `tokens.json` are palette B and are a placeholder until then.

## Two surfaces

| Surface | Mode | Direction |
|---|---|---|
| Marketing site | Persuade | "Sift then settle": payments fall as dots through three rules (decision, orchestration, operations) and settle to one point |
| Console | Operate | Achromatic ledger: ink on paper, one data hue, the stop colour only for what is final |

### Console rules

- Shell: a 240px sidebar with the nav grouped by layer (Decision, Orchestration, Operations, then Prototype). The current page carries `aria-current="page"`. The user row and log out sit at the foot. Under 860px the sidebar folds into a top bar.
- Title bar: demo clock, kill-switch state and the kill-switch button, on every page.
- One primary button per screen, in the `primary` (ink) colour. The `stop` colour is only for block, reject and the kill switch.
- Figures: one container split by dividers, label above value, tabular numbers.
- Tables: no zebra stripes, 12px muted headers, numbers right-aligned, a quiet hover row.

## Status vocabulary

| State | Pill | Meaning |
|---|---|---|
| CONFIRMED | `pill-confirmed` | Definitive rail evidence |
| HELD, ESCALATED, UNKNOWN | `pill-wait` (with border) | Waiting on a person or evidence |
| BLOCKED, REJECTED | `pill-blocked` plus a cross icon | Final; never retried |
| Everything else | `pill-neutral` | In progress |

A blocked state always carries an icon and its label, never colour alone (B-02).

## Type, space, motion

- Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (ids, amounts, code). Self-hosted.
- Console sizes: title 24, section 16, figure 24, body 14, small 12.
- Space on a 4px unit; card padding 20, page padding 32.
- Motion: ease-out `cubic-bezier(0.23,1,0.32,1)`; press 100ms with `scale(0.97)`; hover only on fine pointers; everything off under `prefers-reduced-motion`.

## Accessibility

- Every text pair meets WCAG AA; `apps/site/tests/palette.test.mjs` checks the site palettes.
- Visible focus ring in the `focus` colour on every control.
- Status is never colour alone.

## Checks that block drift

| Check | Where |
|---|---|
| No raw `#hex`, `rgb()` or `hsl()` in site `.astro`/`.css` | `apps/site/tests/palette.test.mjs` |
| No raw colours in `console.css` or console templates; `tokens.css` matches `tokens.json` | `apps/api/tests/unit/test_console_design.py` |

## Don't

- Write a raw colour anywhere but `design/tokens.json`.
- Use the stop colour for decoration or for a primary action.
- Put a gradient, glow or icon-in-a-tinted-square in the console.
- Call DekernAI a payments company or payment provider.
