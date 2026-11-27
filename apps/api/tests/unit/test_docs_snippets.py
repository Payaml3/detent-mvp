"""DOC-04, WHK-02: the docs code samples in eight languages.

The samples are files under docs/snippets/<lang>/. CI runs every language's samples against the sandbox it starts
(tools/run_snippets.py); these tests check what can be checked without the other runtimes: the shared signature
vectors agree with the API's own signing code, every language has every sample, the pages show exactly the files,
and the reference pages' request samples come from the OpenAPI file in the same eight languages.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from detent.webhooks.signing import SignatureError, verify

ROOT = Path(__file__).resolve().parents[4]
SNIPPETS = ROOT / "docs" / "snippets"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _vectors() -> list[list[str]]:
    lines = (SNIPPETS / "webhook-vectors.txt").read_text().splitlines()
    return [ln.split("|", 5) for ln in lines if ln and not ln.startswith("#")]


@pytest.mark.parametrize("vector", _vectors(), ids=lambda v: v[0])
def test_every_signature_vector_agrees_with_the_api_signing_code(vector: list[str]) -> None:
    _name, expect, secret, now, header, body = vector
    try:
        verify(secret, header, body.encode(), now=int(now))
        got = "ok"
    except SignatureError:
        got = "fail"
    assert got == expect


def test_the_vectors_cover_the_cases_the_spec_names() -> None:
    names = {v[0] for v in _vectors()}
    assert {
        "valid",
        "rotated",
        "stale",
        "future",
        "changed_body",
        "wrong_secret",
        "changed_timestamp",
    } <= names
    assert {v[1] for v in _vectors()} == {"ok", "fail"}


def test_every_language_has_every_sample_and_the_pages_show_exactly_the_files() -> None:
    docs, runner = _load("build_docs"), _load("run_snippets")
    assert [folder for _, _, folder in docs.SNIPPET_LANGS] == list(runner.LANGS)
    assert sorted(p.name for p in SNIPPETS.iterdir() if p.is_dir()) == sorted(runner.LANGS)
    for name in docs.SNIPPET_FILES:
        group = docs.render_snippet(name)
        assert group.count("```") == 2 * len(runner.LANGS)
    for page in ("quickstart.mdx", "webhooks/signatures.mdx"):
        source = (ROOT / "docs" / page).read_text()
        assert "{/* snippet: " in source and docs.render_page(source) == source


def test_the_python_sample_passes_the_vectors() -> None:
    out = subprocess.run(
        [
            sys.executable,
            str(SNIPPETS / "python" / "verify_webhook.py"),
            str(SNIPPETS / "webhook-vectors.txt"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_reference_request_samples_are_generated_from_openapi_in_the_eight_languages() -> None:
    config = json.loads((ROOT / "docs" / "docs.json").read_text())
    assert config["navigation"]["tabs"][1]["openapi"] == "api/openapi.json"
    assert config["api"]["examples"]["languages"] == [
        "curl", "python", "javascript", "go", "java", "csharp", "php", "ruby",
    ]  # fmt: skip
