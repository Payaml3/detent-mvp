"""Write the final logo SVG set. Usage: python final.py B <out-dir> (run gen.py first)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from marks import OR, mark

G, P = "#18191B", "#F3F3F1"
HDR = '<svg xmlns="http://www.w3.org/2000/svg"'
TITLE = "<title>DekernAI</title>"
LABEL = 'role="img" aria-label="DekernAI"'


def main(key, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "words.json")) as fh:
        w = json.load(fh)[key]

    def write(name, body):
        with open(f"{out}/{name}", "w") as fh:
            fh.write(body + "\n")

    def svg(vb, body, labelled=True):
        attrs = f'viewBox="{vb}" {LABEL}>{TITLE}' if labelled else f'viewBox="{vb}">'
        return f"{HDR} {attrs}{body}</svg>"

    for name, ink, dot in [
        ("mark", G, OR),
        ("mark-reverse", P, OR),
        ("mark-mono-black", "#000", "#000"),
        ("mark-mono-white", "#fff", "#fff"),
    ]:
        write(f"{name}.svg", svg("0 0 48 48", mark(key, ink, dot)))
    write("mark-currentcolor.svg", f'{HDR} viewBox="0 0 48 48" aria-hidden="true">{mark(key)}</svg>')

    cap, d = w["cap"], w["d"]
    x0, _, x1, _ = w["bb"]
    word_w = x1 - x0
    for name, ink in [("wordmark", G), ("wordmark-reverse", P)]:
        write(
            f"{name}.svg", svg(f"{x0:.1f} {-cap:.1f} {word_w:.1f} {cap:.1f}", f'<path fill="{ink}" d="{d}"/>')
        )

    # Horizontal lockup: mark height = 1.42 x cap height, gap = 0.27 x mark height.
    m = cap * 1.42
    gap = m * 0.27
    my = -cap / 2 - m / 2
    for name, ink in [("lockup-horizontal", G), ("lockup-horizontal-reverse", P)]:
        body = (
            f'<g transform="translate(0 {my:.2f}) scale({m / 48:.4f})">{mark(key, ink, OR)}</g>'
            f'<path fill="{ink}" transform="translate({m + gap - x0:.2f} 0)" d="{d}"/>'
        )
        write(f"{name}.svg", svg(f"0 {my:.2f} {m + gap + word_w:.2f} {m:.2f}", body))

    # Stacked lockup: mark 2.6 x cap height, centred above the wordmark.
    m2 = cap * 2.6
    gap2 = cap * 0.7
    tw = max(word_w, m2)
    h = m2 + gap2 + cap
    for name, ink in [("lockup-stacked", G), ("lockup-stacked-reverse", P)]:
        body = (
            f'<g transform="translate({(tw - m2) / 2:.2f} 0) scale({m2 / 48:.4f})">{mark(key, ink, OR)}</g>'
            f'<path fill="{ink}" transform="translate({(tw - word_w) / 2 - x0:.2f} {h:.2f})" d="{d}"/>'
        )
        write(f"{name}.svg", svg(f"0 0 {tw:.2f} {h:.2f}", body))

    # Favicon: ink follows the browser's light or dark chrome.
    style = f"<style>.i{{fill:{G}}}@media (prefers-color-scheme:dark){{.i{{fill:{P}}}}}</style>"
    write(
        "favicon.svg",
        f'{HDR} viewBox="0 0 48 48">{style}' + mark(key, "X", OR).replace('fill="X"', 'class="i"') + "</svg>",
    )
    tile = f'<rect width="48" height="48" fill="{G}"/>'
    write(
        "app-icon.svg",
        svg(
            "0 0 48 48", tile + f'<g transform="translate(7.2 7.2) scale(0.7)">{mark(key, P, OR)}</g>', False
        ),
    )
    rtile = f'<rect width="48" height="48" rx="9" fill="{G}"/>'
    small = f'<g transform="translate(4.8 4.8) scale(0.8)">{mark(key, P, OR)}</g>'
    write("favicon-tile.svg", svg("0 0 48 48", rtile + small, False))
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
