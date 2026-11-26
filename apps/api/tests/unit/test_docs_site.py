"""P3 group 1: the docs site's structure and its code (DOC-01, DOC-02, DOC-06, SDK-03).

Every page in the navigation exists, nothing internal in docs/ is published, the webhook verification sample on
the signatures page agrees with the API's signing code, and the Postman collection is current.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

from detent.webhooks import signing

ROOT = Path(__file__).resolve().parents[4]
DOCS = ROOT / "docs"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_docs", ROOT / "tools" / "build_docs.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_docs"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_docs_site_is_complete_and_publishes_nothing_internal() -> None:
    tool = _tool()
    assert tool.problems() == []
    assert tool.mdx_issues("Pay {amount} to <b>x</b>") and not tool.mdx_issues(
        "Pay `{amount}` <Note>x</Note>"
    )
    assert "brand/" in tool.ignored() and "product/" in tool.ignored()


def test_every_nav_section_of_the_spec_is_there() -> None:
    nav = json.loads((DOCS / "docs.json").read_text())["navigation"]["tabs"]
    groups = [g["group"] for g in nav[0]["groups"]]
    for want in ("Get started", "Concepts", "Webhooks", "Errors and limits", "SDKs and tools", "Changelog"):
        assert want in groups
    assert nav[1]["openapi"] == "api/openapi.json"  # the reference is generated from the OpenAPI file


def test_the_signature_sample_matches_the_signing_code() -> None:
    page = (DOCS / "webhooks" / "signatures.mdx").read_text()
    m = re.search(r"```python Python\n(.*?)```", page, re.S)
    assert m
    ns: dict[str, object] = {}
    exec(m.group(1), ns)  # our own docs sample
    verify = ns["verify_webhook"]
    import time

    now = int(time.time())
    body = b'{"id":"evt_1","type":"webhook.test"}'
    good = signing.sign("whsec_test", now, body)
    assert verify("whsec_test", good, body) is True  # type: ignore[operator]
    assert verify("whsec_other", good, body) is False  # type: ignore[operator]
    assert verify("whsec_test", good, body + b" ") is False  # type: ignore[operator]
    stale = signing.sign("whsec_test", now - 301, body)
    assert verify("whsec_test", stale, body) is False  # type: ignore[operator]
    rotated = f"{good},v1={'0' * 64}"
    assert verify("whsec_test", rotated, body) is True  # type: ignore[operator]
    assert verify("whsec_test", "v1=abc", body) is False  # type: ignore[operator]
