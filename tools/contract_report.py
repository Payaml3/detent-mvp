"""RAL-10: turn a pytest JUnit XML report from the daily adapter contract run into an issue title and body.

    python tools/contract_report.py report.xml [run_url]

Prints a JSON object {"failed": n, "title": ..., "body": ...}. The body lists each failing adapter and test.
The adapter is the test's parameter (for example ``test_submit[local-evm]``) or, for the simulated bank suite,
the module name. Error text is cut short and never includes environment values.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ADAPTER = re.compile(r"\[([^\]]+)\]$")
SUITES = {"test_banksim": "banksim", "test_rail_contract": "local-evm", "test_simchain": "simchain"}


def adapter_of(classname: str, name: str) -> str:
    m = ADAPTER.search(name)
    if m:
        return m.group(1).split("-")[0] if m.group(1).startswith(("banksim", "simchain")) else m.group(1)
    module = classname.rsplit(".", 1)[-1]
    return SUITES.get(module, module)


def failures(xml: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml)
    out = []
    for case in root.iter("testcase"):
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is None:
            continue
        name, classname = case.get("name", "?"), case.get("classname", "")
        message = (bad.get("message") or bad.text or "").strip().splitlines()
        out.append(
            {
                "adapter": adapter_of(classname, name),
                "test": f"{classname.replace('.', '/')}.py::{name}" if classname else name,
                "message": (message[0] if message else "")[:200],
            }
        )
    return out


def report(xml: str, run_url: str | None = None) -> dict[str, object]:
    found = failures(xml)
    adapters = sorted({f["adapter"] for f in found})
    title = f"Daily adapter contract tests failed: {', '.join(adapters)}" if found else ""
    lines = ["The scheduled adapter contract run (RAL-10) failed.", ""]
    if run_url:
        lines += [f"Run: {run_url}", ""]
    lines += ["| Adapter | Test | First line of the error |", "| --- | --- | --- |"]
    lines += [f"| {f['adapter']} | `{f['test']}` | {f['message'].replace('|', '/')} |" for f in found]
    lines += ["", "A rail API or the simulator changed, or a testnet is down. Fix before the next demo."]
    return {"failed": len(found), "title": title, "body": "\n".join(lines) if found else ""}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    print(json.dumps(report(Path(argv[1]).read_text(), argv[2] if len(argv) > 2 else None)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
