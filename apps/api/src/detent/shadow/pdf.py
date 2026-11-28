"""A minimal text PDF writer (SHD-02, AUD-03 exports). No dependency: Helvetica, A4, wrapped lines.

Only the PDF 1.4 basics: a catalog, a page tree, one content stream per page and the built-in Helvetica
font (WinAnsi). Characters outside Latin-1 are replaced, so the output is always valid.
"""

from __future__ import annotations

import textwrap

WIDTH, HEIGHT, MARGIN, LEADING = 595, 842, 50, 14
CHARS_PER_LINE = 95


def _esc(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render(lines: list[str], *, title: str) -> bytes:
    wrapped: list[tuple[str, int]] = []  # (text, font size)
    for line in lines:
        size = 15 if line.startswith("# ") else 12 if line.startswith("## ") else 10
        body = line.lstrip("#").strip()
        for part in textwrap.wrap(body, CHARS_PER_LINE) or [""]:
            wrapped.append((part, size))
    per_page = (HEIGHT - 2 * MARGIN) // LEADING
    pages = [wrapped[i : i + per_page] for i in range(0, len(wrapped), per_page)] or [[]]
    objs: list[bytes] = []
    n_pages = len(pages)
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs, then the info dictionary.
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, page in enumerate(pages):
        y = HEIGHT - MARGIN
        ops = ["BT"]
        for txt, size in page:
            ops.append(f"/F1 {size} Tf 1 0 0 1 {MARGIN} {y} Tm ({_esc(txt)}) Tj")
            y -= LEADING
        ops.append(f"/F1 8 Tf 1 0 0 1 {MARGIN} 30 Tm (Page {i + 1} of {n_pages}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(f"<< /Title ({_esc(title)}) /Producer (DekernAI prototype) >>".encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\n"
    out += (trailer + f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
