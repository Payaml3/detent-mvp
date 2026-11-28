"""The ``invariants.check`` job (EXE-10): the monitor runs again after each confirmation."""

from __future__ import annotations

from detent.incidents.monitor import JOB_KIND, check_org
from detent.worker.registry import JobContext, handler


@handler(JOB_KIND)
def run_invariant_check(ctx: JobContext) -> None:
    kill_switch = ctx.settings.invariant_monitor_kill_switch if ctx.settings is not None else True
    check_org(ctx.conn, ctx.clock, ctx.job.org_id, kill_switch=kill_switch)
