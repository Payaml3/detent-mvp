"""Run the docs code samples in every docs language (DOC-04, WHK-02).

    python tools/run_snippets.py                 # every language: signature vectors, then the quickstart payout
    python tools/run_snippets.py --vectors-only  # no sandbox needed
    python tools/run_snippets.py --lang go,ruby

The samples live in docs/snippets/<lang>/. Each language's verify_webhook sample checks every case in
docs/snippets/webhook-vectors.txt and exits non-zero on a mismatch. Each create_payout sample sends the
quickstart's payout.json (read from docs/quickstart.mdx) to DEKERNAI_BASE_URL with DEKERNAI_API_KEY and
must print a payment ID. CI runs this against the sandbox it starts in the pipeline.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNIPPETS = ROOT / "docs" / "snippets"
VECTORS = SNIPPETS / "webhook-vectors.txt"
LANGS = ("curl", "python", "typescript", "go", "java", "csharp", "php", "ruby")


def payout_json() -> str:
    page = (ROOT / "docs" / "quickstart.mdx").read_text()
    m = re.search(r"```json payout\.json\n(.*?)```", page, re.S)
    assert m, "docs/quickstart.mdx has no payout.json block"
    return m.group(1)


def _commands(lang: str, work: Path) -> tuple[list[list[str]], list[str], list[str]]:
    """(build commands, the vectors command, the payout command), all run in `work`."""
    d, v = SNIPPETS / lang, str(VECTORS)
    if lang == "curl":
        return [], ["bash", str(d / "verify_webhook.sh"), v], ["bash", str(d / "create_payout.sh")]
    if lang == "python":
        return (
            [],
            [sys.executable, str(d / "verify_webhook.py"), v],
            [sys.executable, str(d / "create_payout.py")],
        )
    if lang == "typescript":
        return [], ["node", str(d / "verify_webhook.ts"), v], ["node", str(d / "create_payout.ts")]
    if lang == "go":
        build = [["go", "-C", str(d), "build", "-o", str(work / name), f"./{name}"]
                 for name in ("verify_webhook", "create_payout")]  # fmt: skip
        return build, [str(work / "verify_webhook"), v], [str(work / "create_payout")]
    if lang == "java":
        return [], ["java", str(d / "VerifyWebhook.java"), v], ["java", str(d / "CreatePayout.java")]
    if lang == "csharp":
        build = [["dotnet", "build", "--nologo", "-v", "q", str(d / name), "-o", str(work / name)]
                 for name in ("VerifyWebhook", "CreatePayout")]  # fmt: skip
        verify = ["dotnet", str(work / "VerifyWebhook" / "VerifyWebhook.dll"), v]
        return build, verify, ["dotnet", str(work / "CreatePayout" / "CreatePayout.dll")]
    if lang == "php":
        return [], ["php", str(d / "verify_webhook.php"), v], ["php", str(d / "create_payout.php")]
    if lang == "ruby":
        return [], ["ruby", str(d / "verify_webhook.rb"), v], ["ruby", str(d / "create_payout.rb")]
    raise ValueError(lang)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600, check=False)


def run(lang: str, *, payout: bool) -> list[str]:
    """Problems found for one language (empty when its samples pass)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "payout.json").write_text(payout_json())
        setup, verify, create = _commands(lang, work)
        for cmd in setup:
            r = _run(cmd, work)
            if r.returncode:
                return [f"{lang}: {' '.join(cmd[:2])} failed\n{r.stdout}{r.stderr}"]
        r = _run(verify, work)
        print(r.stdout.strip() or f"{lang}: (no output)")
        if r.returncode:
            return [f"{lang}: the signature vectors failed\n{r.stdout}{r.stderr}"]
        if not payout:
            return []
        r = _run(create, work)
        if r.returncode or not re.search(r"\bpay_[0-9A-Za-z]+", r.stdout):
            return [f"{lang}: create_payout did not print a payment ID\n{r.stdout}{r.stderr}"]
        print(f"{lang}: created {re.search(r'pay_[0-9A-Za-z]+', r.stdout).group(0)}")  # type: ignore[union-attr]
        return []


def main(argv: list[str]) -> int:
    langs = list(LANGS)
    if "--lang" in argv:
        langs = argv[argv.index("--lang") + 1].split(",")
    payout = "--vectors-only" not in argv
    if payout and not (os.environ.get("DEKERNAI_BASE_URL") and os.environ.get("DEKERNAI_API_KEY")):
        print("snippets: set DEKERNAI_BASE_URL and DEKERNAI_API_KEY (a sandbox key), or pass --vectors-only")
        return 2
    problems = [p for lang in langs for p in run(lang, payout=payout)]
    for p in problems:
        print(p)
    print("snippets: OK" if not problems else f"snippets: {len(problems)} language(s) failed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
