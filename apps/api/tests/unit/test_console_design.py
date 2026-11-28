"""D-39: the console uses design tokens only. Colours live in design/tokens.json, rendered to tokens.css."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATIC = ROOT / "apps/api/src/detent/console/static"
TEMPLATES = ROOT / "apps/api/src/detent/console/templates"
RAW = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def test_tokens_css_matches_tokens_json() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools/build_tokens.py"), "--check"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_console_css_has_no_raw_colours() -> None:
    css = (STATIC / "console.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not RAW.findall(css), "use a var(--token) from design/tokens.json"


def test_templates_have_no_inline_colours() -> None:
    for t in TEMPLATES.glob("*.html"):
        text = re.sub(r"\{#.*?#\}", "", t.read_text(), flags=re.S)
        hits = [m for m in RAW.findall(text)]
        assert not hits, f"{t.name}: raw colour {hits[0]}"


def test_notices_are_quiet_and_errors_are_callouts() -> None:
    """A notice uses the wait colour as an edge, not a fill, so the fill keeps meaning "waiting"; an error is a
    bordered callout with a cross, so it never reads as an ordinary sentence."""
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "console.css").read_text(), flags=re.S)
    note = re.search(r"\.note \{([^}]*)\}", css)
    assert note and "--pill-wait-bg" not in note.group(1) and "--pill-wait-border" in note.group(1)
    assert re.search(r"p\.error::before[^{]*\{[^}]*mask", css)
