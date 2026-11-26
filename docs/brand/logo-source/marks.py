"""The three logo marks shown to the founder (B-03 chose B), drawn on a 48 x 48 grid."""

INK = "currentColor"
OR = "#FF4A1F"

D_PATH = "M5 4H23A20 20 0 0 1 23 44H5Z M13 12V36H23A12 12 0 0 0 23 12Z"


def _dots(points, r):
    return "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y in points)


def _rects(rects):
    return "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for x, y, w, h in rects)


def mark(key, ink=INK, orange=OR):
    if key == "A":  # Sieve: three, then two, pass the rule; one settles
        dots = _dots([(9, 7.5), (24, 7.5), (39, 7.5)], 4) + _dots([(16.5, 19), (31.5, 19)], 4)
        return (
            f'<g fill="{ink}">{dots}<rect x="4" y="27" width="40" height="4" rx="0"/></g>'
            f'<circle cx="24" cy="40" r="6" fill="{orange}"/>'
        )
    if key == "B":  # Settled D: a D whose counter holds one settled point
        return (
            f'<path fill="{ink}" fill-rule="evenodd" d="{D_PATH}"/>'
            f'<circle cx="22" cy="30.5" r="5.5" fill="{orange}"/>'
        )
    if key == "C":  # Three rules: decision, orchestration, operations narrow to one outcome
        bars = _rects([(4, 6, 40, 5), (11, 16, 26, 5), (18, 26, 12, 5)])
        return f'<g fill="{ink}">{bars}</g><circle cx="24" cy="40" r="5.5" fill="{orange}"/>'
    raise ValueError(key)
