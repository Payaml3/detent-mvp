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

    # The logo: the mark is the D of DekernAI. Its 40-unit-tall D matches the cap height and sits on the
    # baseline; the rest of the name follows at the font's own D sidebearings.
    cap, rest = w["cap"], w["rest"]
    s = cap / 40
    x0, x1 = 5, 43  # the D's extent on the 48-unit grid
    mx = rest["d_lsb"] - x0 * s
    ex = rest["d_lsb"] + (x1 - x0) * s + rest["d_rsb"]
    total = ex + rest["bb"][2]
    pad = cap * 0.12
    for name, ink in [("logo", G), ("logo-reverse", P)]:
        body = (
            f'<g transform="translate({mx:.2f} {-cap - 4 * s:.2f}) scale({s:.4f})">{mark(key, ink, OR)}</g>'
            f'<path fill="{ink}" transform="translate({ex:.2f} 0)" d="{rest["d"]}"/>'
        )
        write(f"{name}.svg", svg(f"0 {-cap - pad:.2f} {total:.2f} {cap + 2 * pad:.2f}", body))

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
