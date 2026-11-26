# DekernAI logo: the settled D

Status: direction chosen by the founder on 26 Nov 2026 ("B, Settled D"), then refined at their request so the mark
is the D of the name ("use the first D as the D of the decker word"). Approved on merge (B-03).

## The idea

A D whose counter holds one orange point, resting on its floor. *Dēcernere* is to sift, then settle: the
D is the frame the platform's rules set, and the point is the one outcome that settles inside it. The point
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

- **Name:** DekernAI. The rest of the name is Space Grotesk Bold, outlined, tracked -2%. "AI" takes the same weight
  and colour as the rest of the name: it is never highlighted, because the rules decide, never the AI.
- **Colours:** ink is graphite #18191B on light grounds and paper #F3F3F1 on dark. The point is safety orange
  #FF4A1F. On an orange ground, the point turns paper. Nothing else.
- **Clear space:** the width of the D's stem (one sixth of the mark's height) on every side.
- **Minimum size:** mark 16 px (use the favicon tile below 24 px); logo 16 px cap height.
- **The mark is the D.** In the logo the mark replaces the first letter, so the name reads once: never set
  the mark next to a typed "DekernAI". The D is cap height, sits on the baseline, and keeps Space Grotesk
  Bold's own D spacing before "ekernAI". Don't rebuild it by hand: use the files.
- **The mark alone** (favicon, app icon, avatar) stands for the whole name.
- **Don't:** recolour the D orange, add effects or outlines, rotate, move the point, set the name in
  another font, or put the mark on a busy photo without a graphite or paper panel.

## Regenerating

`docs/brand/logo-source/` holds the scripts. Put the Space Grotesk static TTFs (OFL) in a `fonts` folder, then run
`python gen.py` and `python final.py B <out-dir>`. Needs `fonttools`.
