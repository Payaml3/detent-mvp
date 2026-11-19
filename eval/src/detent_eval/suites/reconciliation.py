"""Operations proof: the reconciliation match rate on the 500-item synthetic set (spec/09, REC stories).

It reuses the set the reconciliation tests build (``apps/api/tests/recon_helpers.build_500``): 247 matched
payouts and 250 deposits with three designed breaks. The figure is the run's match rate and whether each
designed break was found. Synthetic data; the reconciliation agent's fix proposals are recorded stand-ins.
"""

from __future__ import annotations

import sys
from typing import Any

from detent.settings import REPO_ROOT


def run(world: Any, *, progress: bool = True) -> dict[str, Any]:
    from detent.clock import FrozenClock

    from detent_eval.harness import START

    tests = str(REPO_ROOT / "apps" / "api" / "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    import recon_helpers  # the same synthetic set the REC tests use

    clock = FrozenClock(START)
    ro = recon_helpers.build_500(world.engine, clock)
    res = recon_helpers.reconcile(world.engine, clock, ro.id)
    from sqlalchemy import text

    with world.engine.connect() as c:
        keys = set(
            c.execute(text("SELECT subject_key FROM recon_breaks WHERE org_id=:o"), {"o": ro.id}).scalars()
        )
    found = {name: key in keys for name, key in ro.designed.items()}
    out = {
        "count": res.counted,
        "synthetic": True,
        "matched": res.matched,
        "pending": res.pending,
        "match_rate": res.rate_text(),
        "match_rate_bps": res.match_rate_bps,
        "breaks_found": len(res.breaks),
        "designed_breaks_found": found,
    }
    if progress:
        print(
            f"  {res.counted} items, {res.matched} matched ({res.rate_text()}), breaks found: {found}",
            flush=True,
        )
    return out
