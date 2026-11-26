"""API-02: one error envelope, a catalogue of every code, and a docs page generated from it."""

from __future__ import annotations

import json
import typing

from detent.api import errors
from detent.api.error_codes import BY_CODE, CATALOGUE, DOCS_PATH, HTTP_STATUS_CODES, render_markdown
from detent.settings import REPO_ROOT


def test_codes_are_unique_and_types_are_valid() -> None:
    assert len(BY_CODE) == len(CATALOGUE)
    valid = set(typing.get_args(errors.ErrorType))
    for c in CATALOGUE:
        assert c.type in valid and c.statuses and c.meaning and c.action
        assert all(400 <= s <= 599 for s in c.statuses)
        assert c.code == c.code.lower() and " " not in c.code


def test_framework_errors_map_onto_catalogued_codes() -> None:
    for status, (type_, code) in HTTP_STATUS_CODES.items():
        assert code in BY_CODE and BY_CODE[code].type == type_
        assert status in BY_CODE[code].statuses or code in {"invalid_api_key", "validation_error"}


def test_the_docs_page_is_generated_from_the_catalogue() -> None:
    page = (REPO_ROOT / DOCS_PATH).read_text()
    assert page == render_markdown(), "run `make error-docs`"
    assert all(f"`{c.code}`" in page for c in CATALOGUE)


def test_every_envelope_has_the_spec_03_fields() -> None:
    body = json.loads(errors.error_response(409, "conflict", "payment_blocked", "m", request_id="req_1").body)
    assert set(body["error"]) == {"type", "code", "message", "payment_id", "request_id", "param"}


def test_an_uncatalogued_code_is_recorded() -> None:
    errors.error_response(400, "invalid_request", "made_up_code_for_test", "m", request_id=None)
    try:
        assert "made_up_code_for_test" in errors.UNCATALOGUED
    finally:
        errors.UNCATALOGUED.discard("made_up_code_for_test")
