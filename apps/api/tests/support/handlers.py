"""Job handlers used only by tests (loaded with WORKER_EXTRA_HANDLER_MODULES under APP_ENV=test)."""

from __future__ import annotations

import time
from pathlib import Path

from detent.worker.registry import JobContext, handler
from sqlalchemy import text


@handler("test.side_effect")
def side_effect(ctx: JobContext) -> None:
    """Write one side-effect row in the job's transaction.

    With ``marker`` in the payload, the first attempt writes the row, signals the test through the
    marker file and then hangs, so the test can kill the worker mid-job.
    """
    ctx.conn.execute(
        text("INSERT INTO testsupport.side_effects (org_id, job_id, attempt) VALUES (:o, :j, :a)"),
        {"o": ctx.job.org_id, "j": ctx.job.id, "a": ctx.job.attempts},
    )
    marker = ctx.job.payload.get("marker")
    if marker and ctx.job.attempts == 1:
        Path(marker).write_text("in handler")
        time.sleep(120)
    if ctx.job.payload.get("fail_times", 0) >= ctx.job.attempts:
        raise RuntimeError("planned failure")
