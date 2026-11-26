"""API-05: the OpenAPI file is generated from the code and covers every public route."""

from __future__ import annotations

import json
import re

import pytest
from detent.api.app import create_app
from detent.api.error_codes import BY_CODE
from detent.api.openapi import DOCS_PATH, OPS, build, render
from detent.settings import REPO_ROOT, Settings
from detent.webhooks.events import EVENT_TYPES, TEST_EVENT_TYPE
from sqlalchemy import create_engine


@pytest.fixture(scope="module")
def app():  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, app_env="test")  # type: ignore[call-arg]
    return create_app(s, engine=create_engine(s.database_url), configure_logging=False)


def test_the_committed_file_matches_the_code(app) -> None:  # type: ignore[no-untyped-def]
    assert (REPO_ROOT / DOCS_PATH).read_text() == render(app), "run `make openapi`"


def test_every_v1_route_is_described(app) -> None:  # type: ignore[no-untyped-def]
    raw = app.openapi()["paths"]
    routes = {(m, p) for p, item in raw.items() if p.startswith("/v1/") for m in item}
    assert routes == set(OPS)


def test_refs_resolve_and_examples_use_catalogued_codes(app) -> None:  # type: ignore[no-untyped-def]
    spec = build(app)
    text = json.dumps(spec)
    for kind, name in re.findall(r'"\$ref": "#/components/(\w+)/([\w.-]+)"', text):
        assert name in spec["components"][kind], f"{kind}/{name}"
    assert "HTTPValidationError" not in text
    for item in spec["paths"].values():
        for op in item.values():
            assert op["operationId"] and op["summary"]
            for status, resp in op["responses"].items():
                if status.startswith(("4", "5")):
                    examples = resp["content"]["application/json"]["examples"]
                    assert examples, f"{status} has no catalogued code"
                    assert all(code in BY_CODE for code in examples)
    assert set(spec["webhooks"]) == {*EVENT_TYPES, TEST_EVENT_TYPE}
