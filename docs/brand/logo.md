# DekernAI logo: Route

Status: chosen by the founder on 26 Nov 2026 after three rounds: first "B, Settled D", then, asking for something
more creative and for the mark to be the D of the name ("use the first D as the D of the decker word"), "Route".
Approved on merge (B-03).

## The idea

One unbroken stroke runs down the stem, round the bowl and curls inward to one orange point: a payment's
route to its outcome. *Dēcernere* is to sift, then settle: the stroke is the path the platform's rules set, and
the point is the one outcome that settles at its end. The point
is the only orange in the logo, as orange only ever means "act here" (B-02).

## Files (`apps/site/public/brand/`)

| File | Use |
|---|---|
| `mark.svg` / `mark-reverse.svg` | The mark on light / dark grounds |
| `mark-currentcolor.svg` | Inline use; the D takes `currentColor`, the point stays orange |
| `mark-mono-black.svg` / `mark-mono-white.svg` | One-colour print, embossing, fax-grade contexts |
| `logo.svg` / `logo-reverse.svg` | **The logo.** The mark is the D of DekernAI: nav, docs, email, slides |
| `app-icon.svg` | Graphite tile for app icons and social avatars |

Site root: `favicon.svg` (switches ink for dark browser chrome), `favicon.ico` (16, 32, 48), `apple-touch-icon.png` (180),
`icon-192.png`, `icon-512.png`.

## Rules

- **Name:** DekernAI. The rest of the name is JetBrains Mono Bold, outlined, tracked -4%: an engineer's wordmark. "AI" takes the same weight
  and colour as the rest of the name: it is never highlighted, because the rules decide, never the AI.
- **Colours:** ink is graphite #18191B on light grounds and paper #F3F3F1 on dark. The point is safety orange
  #FF4A1F. On an orange ground, the point turns paper. Nothing else.
- **Clear space:** the width of the D's stroke (one sixth of the mark's height) on every side.
- **Minimum size:** mark 16 px (use the favicon tile below 24 px); logo 16 px cap height.
- **The mark is the D.** In the logo the mark replaces the first letter, so the name reads once: never set
  the mark next to a typed "DekernAI". The D is cap height, sits on the baseline, and keeps JetBrains
  Mono Bold's own D spacing before "ekernAI". Don't rebuild it by hand: use the files.
- **The mark alone** (favicon, app icon, avatar) stands for the whole name.
- **Don't:** recolour the D orange, close the stroke's gap, add effects or outlines, rotate, move the point, set the name in
  another font, or put the mark on a busy photo without a graphite or paper panel.

## Regenerating

`docs/brand/logo-source/` holds the scripts. Put the Space Grotesk and JetBrains Mono static TTFs (OFL; `jbm700.ttf` for Route) in a `fonts` folder, then run
`python gen.py` and `python final.py R <out-dir>`. Needs `fonttools`.
