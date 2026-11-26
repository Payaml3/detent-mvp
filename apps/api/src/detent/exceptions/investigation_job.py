"""Worker job: run the investigation agent for a newly opened case (EXC-03).

The case is usable at once; this job adds the agent's cited evidence and recommendation when it
finishes. The agent can only record its answer. Lives here, outside ``detent.agents``, so the agent
package never imports exception-handling code.
"""

from __future__ import annotations

from detent.agents.investigation import investigate, placeholders
from detent.agents.llm import llm_for
from detent.db.engine import transaction
from detent.sandbox import usage
from detent.worker.registry import JobContext, handler

INVESTIGATE_JOB = "case.investigate"


@handler(INVESTIGATE_JOB)
def investigate_job(ctx: JobContext) -> None:
    assert ctx.engine is not None
    assert ctx.settings is not None
    case_id = str(ctx.job.payload["case_id"])
    with ctx.engine.connect() as conn:
        ph = placeholders(conn, ctx.job.org_id, case_id)
    llm, _label = llm_for(ctx.settings, ph, kind="investigation")
    try:  # SBX-02, LED-08: counted before the model is called
        with transaction(ctx.engine) as conn:
            usage.consume(conn, ctx.clock, ctx.job.org_id, "agent_investigations")
        quota_reached = False
    except usage.QuotaExceeded:
        quota_reached = True
    investigate(
        ctx.engine,
        ctx.clock,
        org_id=ctx.job.org_id,
        case_id=case_id,
        llm=llm,
        model=ctx.settings.model_agent,
        daily_token_budget=ctx.settings.ai_daily_token_budget,
        quota_reached=quota_reached,
    )
