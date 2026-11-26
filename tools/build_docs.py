"""Build and check the public docs site (DOC-01, SDK-03).

    python tools/build_docs.py           # write docs/api/postman.json from docs/api/openapi.json
    python tools/build_docs.py --check   # fail if the collection is stale or the site is incomplete

The site is Mintlify, from `docs/` (`docs/docs.json`). `docs/` also holds internal documents (brand, design,
product, engineering standards), so the check makes sure every Markdown page is either in the navigation or
excluded by `docs/.mintignore`: nothing internal is published by accident.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OPENAPI = DOCS / "api" / "openapi.json"
POSTMAN = DOCS / "api" / "postman.json"
PAGE_SUFFIXES = (".mdx", ".md")
_METHODS = ("get", "post", "put", "patch", "delete")


def nav_pages(config: dict[str, Any]) -> list[str]:
    pages: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            pages.append(node)
        elif isinstance(node, dict):
            for key in ("tabs", "groups", "pages"):
                for child in node.get(key, []):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(config["navigation"])
    return pages


def ignored() -> list[str]:
    lines = (DOCS / ".mintignore").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _is_ignored(rel: str, patterns: list[str]) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in patterns)


def _page_file(page: str) -> Path | None:
    for suffix in PAGE_SUFFIXES:
        if (DOCS / f"{page}{suffix}").is_file():
            return DOCS / f"{page}{suffix}"
    return None


def mdx_issues(source: str) -> list[str]:
    """Characters that MDX reads as code outside code blocks and spans: a brace starts an expression and a
    lower-case `<` an HTML tag, and either breaks the page's build."""
    body = re.sub(r"\A---\n.*?\n---\n", "", source, flags=re.S)
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"`[^`\n]*`", "", body)
    body = re.sub(
        r"<[A-Z][^>]*>|</[A-Z][A-Za-z]*>", "", body
    )  # components such as <Note> and <CardGroup cols={2}>
    return [f"MDX would read {m.group(0)!r} as code" for m in re.finditer(r"[{}]|<(?=[a-z!])", body)]


def build_postman(spec: dict[str, Any]) -> dict[str, Any]:
    """A Postman v2.1 collection: one request per operation, in folders by the operation's first tag."""
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, item in spec["paths"].items():
        for method in _METHODS:
            op = item.get(method)
            if op is None:
                continue
            raw = "{{baseUrl}}" + path.replace("{", "{{").replace("}", "}}")
            headers = [
                {"key": "Authorization", "value": "Bearer {{apiKey}}"},
                {"key": "DekernAI-Version", "value": "{{apiVersion}}"},
            ]
            request: dict[str, Any] = {
                "method": method.upper(),
                "header": headers,
                "url": {"raw": raw, "host": ["{{baseUrl}}"], "path": [p for p in raw.split("/")[1:] if p]},
                "description": op.get("description", ""),
            }
            names = {p.get("name") for p in op.get("parameters", []) if p.get("in") == "header"}
            if method == "post" and "Idempotency-Key" in names:
                headers.append({"key": "Idempotency-Key", "value": "{{$guid}}"})
            if "requestBody" in op:
                headers.append({"key": "Content-Type", "value": "application/json"})
                request["body"] = {"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}}
            tag = (op.get("tags") or ["API"])[0]
            folders.setdefault(tag, []).append({"name": op.get("summary") or f"{method.upper()} {path}",
                                                "request": request})  # fmt: skip
    return {
        "info": {
            "name": spec["info"]["title"],
            "description": spec["info"].get("description", ""),
            "version": spec["info"]["version"],
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000"},
            {"key": "apiKey", "value": "sk_test_..."},
            {"key": "apiVersion", "value": spec["info"]["version"]},
        ],
        "item": [{"name": name, "item": items} for name, items in folders.items()],
    }


def render_postman() -> str:
    return json.dumps(build_postman(json.loads(OPENAPI.read_text())), indent=2) + "\n"


def problems() -> list[str]:
    out: list[str] = []
    config = json.loads((DOCS / "docs.json").read_text())
    pages = nav_pages(config)
    patterns = ignored()
    for page in pages:
        if _page_file(page) is None:
            out.append(f"docs.json names a page that does not exist: {page}")
    for tab in config["navigation"].get("tabs", []):
        if "openapi" in tab and not (DOCS / tab["openapi"]).is_file():
            out.append(f"docs.json names an OpenAPI file that does not exist: {tab['openapi']}")
    for p in patterns:
        if not (DOCS / p.rstrip("/")).exists():
            out.append(f".mintignore names something that does not exist: {p}")
    listed = {str(_page_file(p).relative_to(DOCS)) for p in pages if _page_file(p) is not None}  # type: ignore[union-attr]
    for f in sorted(DOCS.rglob("*")):
        rel = f.relative_to(DOCS).as_posix()
        if f.suffix in PAGE_SUFFIXES and rel not in listed and not _is_ignored(rel, patterns):
            out.append(f"{rel} is neither in the navigation nor in .mintignore (it would be published)")
    for page in pages:
        f = _page_file(page)
        if f is not None:
            out += [f"{page}: {issue}" for issue in mdx_issues(f.read_text())]
    if not POSTMAN.is_file() or POSTMAN.read_text() != render_postman():
        out.append("docs/api/postman.json is stale: run python tools/build_docs.py")
    return out


def main(argv: list[str]) -> int:
    if "--check" in argv:
        found = problems()
        for p in found:
            print(f"docs: {p}")
        print("docs: OK" if not found else f"docs: {len(found)} problem(s)")
        return 1 if found else 0
    POSTMAN.write_text(render_postman())
    print(f"wrote {POSTMAN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
