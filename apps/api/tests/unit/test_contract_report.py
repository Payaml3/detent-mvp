"""RAL-10: the daily contract run's failure report names the failing adapter and test."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml
from detent.settings import REPO_ROOT

SCRIPT = REPO_ROOT / "tools" / "contract_report.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rail-contracts.yml"

XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4" failures="1" errors="1">
  <testcase classname="apps.api.tests.chain.test_rail_contract" name="test_submit_then_confirm[local-evm]"/>
  <testcase classname="apps.api.tests.chain.test_rail_contract" name="test_timeout_is_unknown[local-evm]">
    <failure message="AssertionError: assert 'FAILED' == 'TIMEOUT'&#10;more">trace</failure></testcase>
  <testcase classname="apps.api.tests.integration.test_banksim" name="test_status_after_submit">
    <error message="ConnectionError: banksim | down">trace</error></testcase>
  <testcase classname="apps.api.tests.integration.test_banksim" name="test_quote"><skipped/></testcase>
</testsuite></testsuites>"""


def run(tmp_path: Path, xml: str) -> dict[str, object]:
    p = tmp_path / "report.xml"
    p.write_text(xml)
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(p), "https://example.invalid/run/1"],
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(json.loads(out.stdout))


def test_failures_name_the_adapter_and_test(tmp_path: Path) -> None:
    r = run(tmp_path, XML)
    assert r["failed"] == 2
    assert r["title"] == "Daily adapter contract tests failed: banksim, local-evm"
    body = str(r["body"])
    assert (
        "| local-evm | `apps/api/tests/chain/test_rail_contract.py::test_timeout_is_unknown[local-evm]` |"
        in body
    )
    assert "| banksim | `apps/api/tests/integration/test_banksim.py::test_status_after_submit` |" in body
    assert "banksim / down" in body and "more" not in body  # first line only; table-safe
    assert "https://example.invalid/run/1" in body


def test_a_clean_run_reports_nothing(tmp_path: Path) -> None:
    clean = XML.split(
        '<testcase classname="apps.api.tests.chain.test_rail_contract" name="test_timeout', maxsplit=1
    )[0]
    r = run(tmp_path, clean + "</testsuite></testsuites>")
    assert r == {"failed": 0, "title": "", "body": ""}


def test_the_workflow_runs_daily_and_opens_an_issue_on_failure() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text())
    on = wf.get("on", wf.get(True))  # yaml reads a bare `on` key as True
    assert on["schedule"][0]["cron"] and "workflow_dispatch" in on
    assert wf["permissions"] == {"contents": "read", "issues": "write"}
    steps = wf["jobs"]["contracts"]["steps"]
    text = json.dumps(steps)
    assert "tests/chain/test_rail_contract.py" in text and "tests/integration/test_banksim.py" in text
    assert "--junitxml" in text and "contract_report.py" in text
    issue = next(s for s in steps if "issue" in s.get("name", "").lower())
    assert issue["if"] == "failure()" and "gh issue create" in issue["run"]
