import json
import os

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

F = os.environ.get("FONTS_DIR", "fonts") + "/"  # Space Grotesk static TTFs (OFL), e.g. sg700.ttf


def word(text, font, track=0.0, kern=None, size=100):
    """Return (svg path d, width, capheight) for text set at `size` px cap-height-scaled em."""
    t = TTFont(F + font)
    gs = t.getGlyphSet()
    cmap = t.getBestCmap()
    hm = t["hmtx"]
    upm = t["head"].unitsPerEm
    s = size / upm
    pen = SVGPathPen(gs)
    x = 0
    kern = kern or {}
    prev = None
    for ch in text:
        g = cmap[ord(ch)]
        if prev:
            x += kern.get(prev + ch, 0)
        tp = TransformPen(pen, (s, 0, 0, -s, x * s, 0))
        gs[g].draw(tp)
        x += hm[g][0] + track * upm
        prev = ch
    x -= track * upm
    bp = BoundsPen(gs)
    x2 = 0
    prev = None
    for ch in text:
        g = cmap[ord(ch)]
        if prev:
            x2 += kern.get(prev + ch, 0)
        gs[g].draw(TransformPen(bp, (s, 0, 0, -s, x2 * s, 0)))
        x2 += hm[g][0] + track * upm
        prev = ch
    return pen.getCommands(), x * s, t["OS/2"].sCapHeight * s, bp.bounds


if __name__ == "__main__":
    out = {}
    for key, font, track, kern in [
        ("A", "sg600.ttf", -0.01, {"De": -10, "rn": -5}),
        ("B", "sg700.ttf", -0.025, {"De": -15, "ke": -5}),
        ("C", "sg500.ttf", 0.0, {"De": -5}),
    ]:
        d, w, ch, bb = word("DekernAI", font, track, kern)
        out[key] = {"d": d, "w": w, "cap": ch, "bb": bb}
        # The logo: the mark replaces the D, so set the rest of the name and the D's sidebearings.
        d, w, ch, bb = word("ekernAI", font, -0.02, {})
        t = TTFont(F + font)
        gs = t.getGlyphSet()
        g = t.getBestCmap()[ord("D")]
        dbp = BoundsPen(gs)
        gs[g].draw(dbp)
        k = 100 / t["head"].unitsPerEm
        rsb = (t["hmtx"][g][0] - dbp.bounds[2]) * k
        out[key]["rest"] = {"d": d, "bb": bb, "d_lsb": dbp.bounds[0] * k, "d_rsb": rsb}
    with open("words.json", "w") as fh:
        json.dump(out, fh)
    print({k: (round(v["w"], 1), v["cap"]) for k, v in out.items()})
