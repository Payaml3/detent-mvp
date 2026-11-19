"""The step vocabulary scenarios are written in (EVL-01: scenarios are data, these are the verbs).

Every step is ``{name: {args}}`` in a scenario's ``steps`` list. Steps drive the product the way a
client, a reviewer, an attacker with an API key or a crashing worker would: through the public API, the
console's service functions, the worker's job handlers, the fault proxy and, for tamper attempts, the
database directly. A step that expects a refusal says so with ``expect_http`` or ``expect_error``; a
refusal that does not happen fails the scenario. Whether money moved without authorisation is never
judged here: ``checks.py`` reads the audit log, the database and the rails afterwards.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
from detent.audit.log import Actor
from detent.policy.screening import MockScreening
from sqlalchemy import text

from detent_eval.harness import MANDATE_KEY, Env, open_client


class StepFailed(AssertionError):
    """The product did not behave as the scenario expects (a refusal didn't happen, a status differs)."""


class Crash(BaseException):
    """A simulated worker crash. BaseException, so the product's own ``except Exception`` doesn't see it."""


STEPS: dict[str, Callable[[Env, dict[str, Any]], dict[str, Any]]] = {}


def step(name: str) -> Callable[[Callable[[Env, dict[str, Any]], dict[str, Any]]], Any]:
    def deco(fn: Callable[[Env, dict[str, Any]], dict[str, Any]]) -> Any:
        STEPS[name] = fn
        return fn

    return deco


def ref(env: Env, value: Any) -> Any:
    """``$name`` is a value an earlier step saved; ``$name.field`` reads into it."""
    if isinstance(value, str) and value.startswith("$"):
        name, _, path = value[1:].partition(".")
        cur = env.saved[name]
        for part in path.split(".") if path else []:
            cur = cur[part]
        return cur
    if isinstance(value, dict):
        return {k: ref(env, v) for k, v in value.items()}
    if isinstance(value, list):
        return [ref(env, v) for v in value]
    return value


def pid_of(env: Env, value: Any) -> Any:
    """A payment named by a step: ``p1`` (saved by an earlier step), ``$p1``, or a literal ``pay_`` ID."""
    if isinstance(value, str) and not value.startswith("$") and value in env.saved:
        return env.saved[value]
    return ref(env, value)


def actor(env: Env, role: str) -> Actor:
    return Actor(env.users[role], role)


def _client(env: Env) -> Any:
    return env.client or open_client(env)


def _expect_http(r: httpx.Response, args: dict[str, Any]) -> None:
    want = args.get("expect_http")
    if want is None:
        return
    wants = want if isinstance(want, list) else [want]
    if r.status_code not in wants:
        raise StepFailed(f"expected HTTP {want}, got {r.status_code}: {r.text[:300]}")
    code = args.get("expect_code")
    if code is not None:
        got = (
            (r.json().get("error") or {}).get("code")
            if r.headers.get("content-type", "").startswith("application/json")
            else None
        )
        if got != code:
            raise StepFailed(f"expected error code {code}, got {got}: {r.text[:300]}")


def _expect_error(fn: Callable[[], Any], args: dict[str, Any]) -> tuple[Any, str | None]:
    """Run ``fn``. With ``expect_error`` the call must raise; the error's type name is returned."""
    want = args.get("expect_error")
    try:
        out = fn()
    except Exception as exc:
        if want is None:
            raise
        name = type(exc).__name__
        if want is not True and want not in (name, str(exc)) and want not in str(exc):
            raise StepFailed(f"expected error {want!r}, got {name}: {exc}") from exc
        return None, name
    if want is not None:
        raise StepFailed(f"expected error {want!r}, but the call succeeded: {out!r}"[:400])
    return out, None


def _status(env: Env, pid: str) -> str:
    with env.engine.connect() as c:
        return str(
            c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"),
                {"o": env.org_id, "p": pid},
            ).scalar_one()
        )


def _expect_status(env: Env, pid: str, args: dict[str, Any]) -> None:
    want = args.get("expect_status")
    if want is None:
        return
    got = _status(env, pid)
    wants = want if isinstance(want, list) else [want]
    if got not in wants:
        raise StepFailed(f"payment {pid}: expected {want}, got {got}")


# ------------------------------------------------------------------------------------- building intents
def destination(env: Env, alias: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(alias, dict):
        return dict(ref(env, alias))
    table: dict[str, dict[str, Any]] = {
        "local": {"kind": "evm_wallet", "network": "local-evm", "address": env.payees.get("local")},
        "local_id": {"kind": "evm_wallet", "network": "local-evm", "destination_id": "dst_local"},
        "bluefin": {"kind": "evm_wallet", "network": "base-sepolia", "destination_id": "dst_bluefin_base"},
        "nova": {"kind": "evm_wallet", "network": "eth-sepolia", "destination_id": "dst_nova_eth"},
        "flagged": {"kind": "evm_wallet", "network": "base-sepolia", "destination_id": "dst_flagged"},
        "quill": {"kind": "bank_account", "network": "banksim-fps", "destination_id": "dst_quill_acct"},
        "harbor": {
            "kind": "bank_account",
            "network": "banksim-sepa-inst",
            "destination_id": "dst_harbor_iban",
        },
        "spare": {"kind": "evm_wallet", "network": "local-evm", "address": env.payees.get("spare")},
        "dead": {
            "kind": "evm_wallet",
            "network": "local-evm",
            "address": "0x000000000000000000000000000000000000dEaD",
        },
    }
    return dict(table[alias])


def intent_body(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    if "body" in a:
        return dict(ref(env, a["body"]))
    cpt = a.get("cpt", "cpt_local")
    default_dest = {
        "cpt_local": "local",
        "cpt_bluefin": "bluefin",
        "cpt_nova": "nova",
        "cpt_flagged": "flagged",
        "cpt_quill": "quill",
        "cpt_harbor": "harbor",
    }.get(cpt, "local")
    currency = a.get("currency") or {"cpt_quill": "GBP", "cpt_harbor": "EUR"}.get(cpt, "USDC")
    body: dict[str, Any] = {
        "kind": "payout",
        "source": a.get("source", "platform"),
        "counterparty_id": cpt,
        "destination": destination(env, a.get("dest", default_dest)),
        "amount": {"amount": str(a.get("amount", "50.00")), "currency": currency},
    }
    for k in ("reference", "notes", "mandate_id", "allow_network_switch", "travel_rule"):
        if k in a:
            body[k] = ref(env, a[k])
    if body["source"] == "agent":
        body.setdefault("mandate_id", "mnd_demo_ap_agent")
    return body


def _post_intent(env: Env, a: dict[str, Any], path: str) -> httpx.Response:
    client = _client(env)
    key = env.keys[a.get("key", "agent" if a.get("source") == "agent" else "lead")]
    headers = {"Authorization": f"Bearer {key}"}
    idem = a.get("idem", f"idem-{env.rng.getrandbits(48):012x}")
    if idem is not None:
        headers["Idempotency-Key"] = str(ref(env, idem))
    return client.post(path, json=intent_body(env, a), headers=headers)  # type: ignore[no-any-return]


def _save_intent(env: Env, a: dict[str, Any], r: httpx.Response) -> dict[str, Any]:
    _expect_http(r, a)
    out: dict[str, Any] = {"http": r.status_code}
    if r.status_code in (200, 201):
        j = r.json()
        out.update(
            id=j.get("id"),
            status=j.get("status"),
            reasons=sorted(
                {c.get("reason") for c in (j.get("decision") or {}).get("checks", []) if c.get("reason")}
            ),
        )
        if a.get("save"):
            env.saved[a["save"]] = j["id"]
            env.saved[a["save"] + "_body"] = j
        if a.get("expect_status") and j.get("status") not in (
            a["expect_status"] if isinstance(a["expect_status"], list) else [a["expect_status"]]
        ):
            raise StepFailed(f"expected {a['expect_status']}, got {j.get('status')} ({out['reasons']})")
        for reason in a.get("expect_reasons", []):
            if reason not in out["reasons"]:
                raise StepFailed(f"expected reason {reason} in {out['reasons']}")
    elif a.get("save"):
        env.saved[a["save"] + "_error"] = r.json() if r.content else None
    return out


@step("intent")
def intent(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """POST /v1/payment_intents."""
    return _save_intent(env, a, _post_intent(env, a, "/v1/payment_intents"))


@step("decision")
def decision(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """POST /v1/decisions (decide only, never sends)."""
    return _save_intent(env, a, _post_intent(env, a, "/v1/decisions"))


@step("parallel_intents")
def parallel_intents(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """``n`` intents at once from threads (split payments, bursts at a cap)."""
    n = int(a["n"])
    results: list[httpx.Response | None] = [None] * n
    bodies = [
        dict(
            a,
            idem=a.get("idem", f"burst-{env.rng.getrandbits(32):08x}-{i}")
            if not a.get("same_idem")
            else a.get("idem", "burst-same"),
        )
        for i in range(n)
    ]
    _client(env)

    def go(i: int) -> None:
        results[i] = _post_intent(env, bodies[i], "/v1/payment_intents")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = [
        r.json().get("status")
        if r is not None and r.status_code in (200, 201)
        else (r.status_code if r is not None else None)
        for r in results
    ]
    ids = sorted({r.json()["id"] for r in results if r is not None and r.status_code in (200, 201)})
    if a.get("save"):
        env.saved[a["save"]] = ids
    return {"statuses": statuses, "ids": ids}


@step("request")
def request(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Any API call: ``{method, path, key, body?, headers?}``. ``key`` may be ``none`` or a raw token."""
    if a.get("other_org"):
        assert env.other is not None, "the scenario needs setup: {second_org: true}"
        client = env.other.client or open_client(env.other)
    else:
        client = _client(env)
    key_name = a.get("key", "lead")
    headers = dict(a.get("headers") or {})
    if key_name != "none":
        token = env.keys.get(key_name) or (env.other.keys.get(key_name) if env.other else None) or key_name
        if key_name.startswith("other:") and env.other is not None:
            token = env.other.keys[key_name.split(":", 1)[1]]
        headers["Authorization"] = f"Bearer {token}"
    if a.get("idem"):
        headers["Idempotency-Key"] = str(ref(env, a["idem"]))
    body = ref(env, a["body"]) if "body" in a else None
    r = client.request(a.get("method", "GET"), str(ref(env, a["path"])), json=body, headers=headers)
    _expect_http(r, a)
    if a.get("save"):
        env.saved[a["save"]] = r.json() if r.content else None
    return {"http": r.status_code}


# ------------------------------------------------------------------------------------------ reviewing
def open_case(env: Env, pid: str) -> str | None:
    with env.engine.connect() as c:
        v = c.execute(
            text(
                "SELECT id FROM exception_cases WHERE org_id=:o AND payment_id=:p AND status IN "
                "('OPEN','HELD_OVERDUE') ORDER BY created_at DESC LIMIT 1"
            ),
            {"o": env.org_id, "p": pid},
        ).scalar_one_or_none()
    return str(v) if v else None


def last_case(env: Env, pid: str) -> str | None:
    with env.engine.connect() as c:
        v = c.execute(
            text(
                "SELECT id FROM exception_cases WHERE org_id=:o AND payment_id=:p "
                "ORDER BY created_at DESC, id DESC "
                "LIMIT 1"
            ),
            {"o": env.org_id, "p": pid},
        ).scalar_one_or_none()
    return str(v) if v else None


def _resolve(env: Env, a: dict[str, Any], action: str) -> dict[str, Any]:
    from detent.exceptions.cases import approve as approve_case
    from detent.exceptions.cases import reject as reject_case

    pid = pid_of(env, a["payment"])
    case = open_case(env, pid) or last_case(env, pid)
    if a.get("via", "api") == "api":
        case = case or f"exc_{pid[4:]}"  # no case exists (a blocked payment): try a made-up case ID
        r = _client(env).post(
            f"/v1/exceptions/{case}/{action}",
            json={"reason": a.get("reason", "Checked the invoice and the supplier (evaluation)")},
            headers={"Authorization": f"Bearer {env.keys[a.get('as', 'reviewer')]}"},
        )
        _expect_http(r, a)
        _expect_status(env, pid, a)
        return {"http": r.status_code, "case": case}
    fn = approve_case if action == "approve" else reject_case
    kw: dict[str, Any] = {"mandate_key": MANDATE_KEY} if action == "approve" else {}
    _, err = _expect_error(
        lambda: fn(
            env.engine,
            env.clock,
            case_id=case or "exc_missing",
            org_id=env.org_id,
            actor=actor(env, a.get("as", "reviewer")),
            reason=a.get("reason", "Checked (evaluation)"),
            **kw,
        ),
        a,
    )
    _expect_status(env, pid, a)
    return {"case": case, "error": err}


@step("approve")
def approve(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    return _resolve(env, a, "approve")


@step("reject")
def reject(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    return _resolve(env, a, "reject")


@step("approve_all_cases")
def approve_all_cases(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """A careless reviewer approves every open case. Approval re-runs policy, so this must still be safe."""
    with env.engine.connect() as c:
        rows = (
            c.execute(
                text(
                    "SELECT payment_id FROM exception_cases WHERE org_id=:o "
                    "AND status IN ('OPEN','HELD_OVERDUE') "
                    "AND payment_id IS NOT NULL"
                ),
                {"o": env.org_id},
            )
            .scalars()
            .all()
        )
    out = []
    for pid in rows:
        try:
            _resolve(env, {"payment": pid, "as": a.get("as", "reviewer"), "via": "service"}, "approve")
            out.append({"payment": pid, "status": _status(env, pid)})
        except Exception as exc:  # refusals are fine; the checks judge the outcome
            out.append({"payment": pid, "refused": type(exc).__name__})
    return {"approved": out}


# ------------------------------------------------------------------------------------------ the worker
def worker(env: Env) -> Any:
    from detent.runtime import Runtime
    from detent.worker.loop import Worker

    if "_worker" not in env.saved:
        env.saved["_worker"] = Worker(
            Runtime(env.settings, env.engine, env.clock), worker_id="eval", org_id=env.org_id
        )
    return env.saved["_worker"]


def _next_due(env: Env) -> Any:
    with env.engine.connect() as c:
        return c.execute(
            text(
                "SELECT min(greatest(run_at, coalesce(locked_until, run_at))) FROM jobs WHERE org_id=:o "
                "AND done_at IS NULL AND dead_at IS NULL"
            ),
            {"o": env.org_id},
        ).scalar_one_or_none()


@step("run_worker")
def run_worker(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Run this organisation's due jobs; when none is due, move the clock to the next one (bounded)."""
    w = worker(env)
    ran = 0
    max_jobs = int(a.get("max_jobs", 60))
    max_wait = timedelta(seconds=int(a.get("max_clock_seconds", 900)))
    waited = timedelta(0)
    while ran < max_jobs:
        if w.run_one():
            ran += 1
            continue
        if not a.get("advance", True):
            break
        nxt = _next_due(env)
        if nxt is None:
            break
        gap = max(nxt - env.clock.now(), timedelta(seconds=1))
        if waited + gap > max_wait:
            break
        env.clock.advance(gap)
        waited += gap
        if a.get("resolve_unknown", True):
            _resolve_all_unknown(env)
    if a.get("resolve_unknown", True):
        _resolve_all_unknown(env)
    for k, v in (a.get("expect_status") or {}).items():
        _expect_status(env, ref(env, f"${k}") if not str(k).startswith("pay_") else k, {"expect_status": v})
    return {"jobs": ran, "clock_advanced_s": int(waited.total_seconds())}


def _resolve_all_unknown(env: Env) -> None:
    """The UNKNOWN resolver, as its scheduled job would run it."""
    from detent.execution.resolver import resolve_unknown
    from detent.rails.registry import build_adapters

    with env.engine.connect() as c:
        pids = (
            c.execute(
                text("SELECT id FROM payment_intents WHERE org_id=:o AND status='UNKNOWN'"), {"o": env.org_id}
            )
            .scalars()
            .all()
        )
    if not pids:
        return
    adapters = build_adapters(env.settings, env.engine, env.org_id)
    for pid in pids:
        resolve_unknown(env.engine, env.clock, adapters, org_id=env.org_id, payment_id=pid)


@step("resolve_unknown")
def resolve_unknown_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    for _ in range(int(a.get("times", 1))):
        _resolve_all_unknown(env)
    return {}


@step("send_now")
def send_now(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Call the send path directly, as an extra or forged trigger would (a second worker, a replayed job)."""
    from detent.execution.send import send_payment
    from detent.rails.registry import build_adapters

    pid = pid_of(env, a["payment"])
    adapters = build_adapters(env.settings, env.engine, env.org_id)
    n = int(a.get("times", 1))
    outs: list[str] = []
    if a.get("parallel"):
        res: list[str] = [""] * n

        def go(i: int) -> None:
            res[i] = send_payment(
                env.engine,
                env.clock,
                adapters,
                org_id=env.org_id,
                payment_id=pid,
                screening=MockScreening.from_fixture(),
                mandate_key=MANDATE_KEY,
            ).value

        ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        outs = res
    else:
        for _ in range(n):
            outs.append(
                send_payment(
                    env.engine,
                    env.clock,
                    adapters,
                    org_id=env.org_id,
                    payment_id=pid,
                    screening=MockScreening.from_fixture(),
                    mandate_key=MANDATE_KEY,
                ).value
            )
    _expect_status(env, pid, a)
    return {"results": outs}


@step("enqueue_send")
def enqueue_send(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Put a send job on the queue for a payment directly (a forged or replayed job)."""
    from detent.intents.service import SEND_JOB
    from detent.worker.queue import enqueue

    pid = pid_of(env, a["payment"])
    with env.engine.begin() as c:
        jid = enqueue(
            c,
            env.clock,
            org_id=env.org_id,
            kind=SEND_JOB,
            payment_id=pid,
            dedupe_key=f"forged-{env.rng.getrandbits(32):08x}",
            payload={"payment_id": pid},
        )
    return {"job": jid}


@step("retry_failed")
def retry_failed(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Ask the execution layer to apply its retry rules to the payment (a manual retry trigger)."""
    from detent.execution.retry import after_failure
    from detent.rails.registry import build_adapters

    pid = pid_of(env, a["payment"])
    out, err = _expect_error(
        lambda: (
            after_failure(
                env.engine,
                env.clock,
                build_adapters(env.settings, env.engine, env.org_id),
                org_id=env.org_id,
                payment_id=pid,
            ).value
        ),
        a,
    )
    _expect_status(env, pid, a)
    return {"result": out, "error": err}


@step("crash_during_send")
def crash_during_send(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Claim the payment's send job and crash the worker ``before_broadcast`` or ``after_broadcast``.

    The job stays claimed until its lease runs out, as if the process died; nothing in the product
    catches the crash. A later ``run_worker`` (with the clock past the lease) runs the job again.
    """
    from detent.rails import registry as rails_registry
    from detent.worker import queue

    pid = pid_of(env, a["payment"])
    when = a.get("at", "before_broadcast")
    real = rails_registry.build_adapters

    class Crashing:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def submit(self, view: Any) -> Any:
            if when == "before_broadcast":
                raise Crash("worker died after storing the signed transaction, before broadcasting it")
            self._inner.submit(view)
            raise Crash("worker died after broadcasting, before recording the answer")

    def crashing(settings: Any, engine: Any, org_id: str) -> Any:
        return {k: Crashing(v) for k, v in real(settings, engine, org_id).items()}

    w = worker(env)
    job = queue.claim(env.engine, env.clock, "eval-crashing", w.lease, org_id=env.org_id)
    if job is None or job.payment_id != pid:
        raise StepFailed(f"no send job for {pid} to crash (got {job})")
    from detent.execution import jobs as jobs_mod
    from detent.worker.registry import JobContext

    if when != "commit":
        setattr(jobs_mod, "build_adapters", crashing)  # noqa: B010 - swapped back in finally
    try:
        with env.engine.begin() as conn:
            jobs_mod.send_job(JobContext(conn, env.clock, job, "eval-crashing", env.engine, env.settings))
            if when == "commit":  # the database connection drops as the job's transaction commits
                from sqlalchemy.exc import OperationalError

                raise OperationalError("COMMIT", {}, Exception("server closed the connection unexpectedly"))
    except Crash as exc:
        crashed = str(exc)
    except Exception as exc:
        if when != "commit":
            raise
        crashed = f"connection dropped at commit: {type(exc).__name__}"
    else:
        crashed = "no crash: the job did not reach the rail"
    finally:
        setattr(jobs_mod, "build_adapters", real)  # noqa: B010
    env.clock.advance(w.lease + timedelta(seconds=1))  # the dead worker's lease runs out
    return {"crash": crashed, "status": _status(env, pid)}


# ------------------------------------------------------------------------------------------ attacks
@step("tamper")
def tamper(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Write to the database directly, as someone with database access would try. Must be refused."""
    pid = pid_of(env, a.get("payment", ""))
    statements = {
        "set_status": (
            "UPDATE payment_intents SET status=:to WHERE org_id=:o AND id=:p",
            {"to": a.get("to")},
        ),
        "fail_unknown_attempt": (
            "UPDATE attempts SET status='FAILED', failure_class='TECHNICAL_FINAL' "
            "WHERE org_id=:o AND payment_id=:p "
            "AND status='UNKNOWN'",
            {},
        ),
        "second_inflight_attempt": (
            "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, "
            "created_at) "
            "SELECT 'att_' || md5(random()::text), org_id, payment_id, attempt_no + 1, rail_id, 'SUBMITTED', "
            "idempotency_key || ':x', created_at FROM attempts WHERE org_id=:o AND payment_id=:p "
            "ORDER BY attempt_no DESC LIMIT 1",
            {},
        ),
        "edit_audit": ("UPDATE audit_events SET payload='{}'::jsonb WHERE org_id=:o AND subject_id=:p", {}),
        "delete_audit": ("DELETE FROM audit_events WHERE org_id=:o AND subject_id=:p", {}),
        "activate_draft": (
            "UPDATE policy_versions SET status='active' WHERE org_id=:o AND status='draft'",
            {},
        ),
        "clear_mandate_revocation": (
            "UPDATE mandates SET revoked_at=NULL, revoked_by=NULL WHERE org_id=:o AND id='mnd_demo_ap_agent'",
            {},
        ),
        "allowlist_counterparty": (
            "UPDATE counterparties SET allowlisted=true, kyb_status='verified' WHERE org_id=:o AND id=:p",
            {},
        ),
    }
    sql, extra = statements[a["action"]]

    def run() -> int:
        with env.engine.begin() as c:
            return int(c.execute(text(sql), {"o": env.org_id, "p": pid, **extra}).rowcount)

    want = a.get("expect_error", True)  # false: the write is allowed; the product must cope with it
    out, err = _expect_error(run, {"expect_error": None if want is False else want})
    return {"rows": out, "refused": err}


@step("transition")
def transition_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Ask transition() for a move; refusals are audited by the product."""
    from detent.domain.states import Status
    from detent.intents.transition import apply_transition

    pid = pid_of(env, a["payment"])
    _, err = _expect_error(
        lambda: apply_transition(
            env.engine,
            env.clock,
            org_id=env.org_id,
            payment_id=pid,
            to=Status(a["to"]),
            actor=actor(env, a.get("as", "payments_lead")),
            reason="evaluation",
        ),
        a,
    )
    return {"refused": err}


@step("create_attempt")
def create_attempt_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.execution.attempts import create_attempt

    pid = pid_of(env, a["payment"])

    def run() -> Any:
        with env.engine.begin() as c:
            return create_attempt(
                c, env.clock, org_id=env.org_id, payment_id=pid, rail_id=a.get("rail", "local-evm")
            )

    _, err = _expect_error(run, a)
    return {"refused": err}


@step("change_destination")
def change_destination(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Change a registered destination (the wallet-change race), through the registry's own function."""
    from detent.intents.registry import update_destination

    alias = a.get("to", "spare")
    address = env.payees.get(alias, alias)
    with env.engine.begin() as c:
        update_destination(
            c,
            env.clock,
            env.org_id,
            a.get("destination", "dst_local"),
            actor=actor(env, a.get("as", "payments_lead")),
            address=address,
        )
    return {"address": address}


@step("kill_switch")
def kill_switch(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    r = _client(env).request(
        "POST" if a.get("action", "engage") == "engage" else "DELETE",
        "/v1/kill_switch",
        headers={"Authorization": f"Bearer {env.keys[a.get('as', 'oncall')]}"},
    )
    _expect_http(r, a)
    return {"http": r.status_code, "body": r.json() if r.content else None}


@step("advance_clock")
def advance_clock(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    env.clock.advance(
        timedelta(
            days=a.get("days", 0),
            hours=a.get("hours", 0),
            minutes=a.get("minutes", 0),
            seconds=a.get("seconds", 0),
        )
    )
    return {"now": env.clock.now().isoformat()}


@step("sweep_deadlines")
def sweep_deadlines(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.exceptions.deadlines import sweep

    return {"moved": sweep(env.engine, env.clock, env.org_id)}


@step("set_mode")
def set_mode(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Change the operating mode through the two-person flow (payments lead proposes, compliance approves)."""
    from detent.execution.modes import approve_mode_change, propose_mode_change

    cid = propose_mode_change(
        env.engine,
        env.clock,
        org_id=env.org_id,
        to_mode=a["mode"],
        actor=actor(env, "payments_lead"),
        reason="evaluation",
    )
    approve_mode_change(
        env.engine, env.clock, org_id=env.org_id, change_id=cid, actor=actor(env, "compliance_lead")
    )
    return {"mode": a["mode"]}


@step("confirm_send")
def confirm_send_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.execution.modes import confirm_send

    pid = pid_of(env, a["payment"])
    _, err = _expect_error(
        lambda: confirm_send(
            env.engine,
            env.clock,
            org_id=env.org_id,
            payment_id=pid,
            actor=actor(env, a.get("as", "reviewer")),
        ),
        a,
    )
    return {"refused": err}


# ------------------------------------------------------------------------------------------ rule changes
def _policy_yaml(env: Env, changes: dict[str, Any]) -> str:
    import yaml
    from detent.policy.store import active_policy

    with env.engine.connect() as c:
        current = active_policy(c, env.org_id)
        raw = c.execute(
            text("SELECT yaml FROM policy_versions WHERE org_id=:o AND id=:i"),
            {"o": env.org_id, "i": current.id},
        ).scalar_one()
    doc = yaml.safe_load(raw)
    for path, value in changes.items():
        cur = doc
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur[p]
        cur[parts[-1]] = value
    doc["version"] = int(doc["version"]) + 1
    return str(yaml.safe_dump(doc, sort_keys=False))


@step("policy_propose")
def policy_propose(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.policy.changes import propose_draft

    out, err = _expect_error(
        lambda: propose_draft(
            env.engine,
            env.clock,
            org_id=env.org_id,
            actor=actor(env, a.get("as", "payments_lead")),
            yaml_text=_policy_yaml(env, a.get("changes", {})),
            attest=bool(a.get("attest", False)),
        ),
        a,
    )
    if out is not None and a.get("save"):
        env.saved[a["save"]] = out.id
    return {"draft": getattr(out, "id", None), "refused": err}


@step("policy_approve")
def policy_approve(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.policy.changes import approve_draft

    _, err = _expect_error(
        lambda: approve_draft(
            env.engine,
            env.clock,
            org_id=env.org_id,
            draft_id=ref(env, a["draft"]),
            actor=actor(env, a.get("as", "compliance_lead")),
            attest=bool(a.get("attest", True)),
        ),
        a,
    )
    return {"refused": err}


# ------------------------------------------------------------------------------------------ mandates
@step("mandate_revoke")
def mandate_revoke(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    from detent.mandates.store import revoke_mandate

    with env.engine.begin() as c:
        revoke_mandate(
            c, env.clock, env.org_id, a.get("mandate", "mnd_demo_ap_agent"), actor=actor(env, "payments_lead")
        )
    return {}


@step("mandate_tamper")
def mandate_tamper(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Edit the stored mandate's scope without re-signing it (a forged mandate)."""
    import json

    with env.engine.begin() as c:
        c.execute(
            text(
                "UPDATE mandates SET payload = jsonb_set(payload, CAST(:path AS text[]), CAST(:v AS jsonb)) "
                "WHERE org_id=:o AND id=:m"
            ),
            {
                "path": "{" + ",".join(a["path"].split(".")) + "}",
                "v": json.dumps(a["value"]),
                "o": env.org_id,
                "m": a.get("mandate", "mnd_demo_ap_agent"),
            },
        )
    return {}


@step("mandate_replay_old_version")
def mandate_replay_old_version(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Put back an older signed document (version 1) after the mandate was narrowed in version 2."""
    import json

    from detent.mandates.store import fixture_mandate, issue_mandate

    with env.engine.begin() as c:
        old = c.execute(
            text("SELECT payload, signature FROM mandates WHERE org_id=:o AND id='mnd_demo_ap_agent'"),
            {"o": env.org_id},
        ).one()
        c.execute(
            text("DELETE FROM api_keys WHERE org_id=:o AND mandate_id='mnd_demo_ap_agent'"), {"o": env.org_id}
        )
        c.execute(text("DELETE FROM mandate_usage WHERE org_id=:o"), {"o": env.org_id})
        c.execute(text("DELETE FROM mandates WHERE org_id=:o AND id='mnd_demo_ap_agent'"), {"o": env.org_id})
        doc = fixture_mandate(env.clock, env.org_id)
        doc["version"] = 2
        doc["scope"]["max_per_payment"] = {"amount": "100.00", "currency": "USDC"}
        issue_mandate(c, env.clock, env.org_id, doc, MANDATE_KEY, actor=Actor.system("seed"))
        # The attacker swaps the stored v2 payload for the old, still validly signed v1 document.
        c.execute(
            text(
                "UPDATE mandates SET payload=CAST(:p AS jsonb), signature=:s WHERE org_id=:o AND "
                "id='mnd_demo_ap_agent'"
            ),
            {"p": json.dumps(dict(old.payload)), "s": old.signature, "o": env.org_id},
        )
        from detent.api.auth import issue_key

        from detent_eval.harness import PEPPER

        env.keys["agent"] = issue_key(
            c,
            env.clock,
            env.org_id,
            env.users["payments_lead"],
            ["intents:create", "read"],
            PEPPER,
            mandate_id="mnd_demo_ap_agent",
        )
    return {}


# ------------------------------------------------------------------------------------------ the agent
@step("agent_propose")
def agent_propose(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """The instruction agent reads an invoice (recorded stand-in unless the run is live)."""
    from detent.agents.instruction import fixture_placeholders, propose_from_invoice
    from detent.settings import REPO_ROOT

    from detent_eval.llm import client_for

    with env.engine.connect() as c:
        ph = fixture_placeholders(c, env.org_id)
    doc = a["text"] if "text" in a else (REPO_ROOT / a["invoice"]).read_text()
    for k, v in ph.items():
        doc = doc.replace("{{" + k + "}}", v)
    llm, model = client_for(env, ph, a.get("recording"))
    p = propose_from_invoice(
        env.engine,
        env.clock,
        org_id=env.org_id,
        document=doc,
        mandate_id=a.get("mandate", "mnd_demo_ap_agent"),
        llm=llm,
        model=model,
        daily_token_budget=2_000_000,
    )
    env.saved[a.get("save", "proposal")] = p.id
    env.saved[a.get("save", "proposal") + "_obj"] = p
    flags = sorted({f["code"] for f in p.flags})
    for f in a.get("expect_flags", []):
        if f not in flags:
            raise StepFailed(f"expected flag {f}, got {flags}")
    if "expect_amount" in a and (p.proposal.get("amount") or {}).get("value") != a["expect_amount"]:
        raise StepFailed(f"expected amount {a['expect_amount']}, got {p.proposal.get('amount')}")
    return {"proposal": p.id, "flags": flags, "status": p.status}


@step("investigate")
def investigate_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """The investigation agent writes its recommendation on a payment's open case (read-only tools)."""
    from detent.agents.investigation import investigate, placeholders

    from detent_eval.llm import client_for

    pid = pid_of(env, a["payment"])
    case = open_case(env, pid) or last_case(env, pid)
    if case is None:
        raise StepFailed(f"payment {pid} has no case to investigate")
    with env.engine.connect() as c:
        ph = placeholders(c, env.org_id, case)
    llm, model = client_for(env, ph, a.get("recording"), kind="investigation")
    inv = investigate(
        env.engine,
        env.clock,
        org_id=env.org_id,
        case_id=case,
        llm=llm,
        model=model,
        daily_token_budget=2_000_000,
    )
    env.saved["investigation"] = inv
    return {
        "case": case,
        "recommendation": inv.recommendation,
        "status": inv.status,
        "flags": [f["code"] for f in inv.flags],
    }


@step("resolve_flags")
def resolve_flags_step(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """A person resolves the agent's flags (``values`` fills or overrides fields)."""
    from detent.agents.submit import resolve_flags

    pid = env.saved[a.get("proposal", "proposal")]
    _, err = _expect_error(
        lambda: resolve_flags(
            env.engine,
            env.clock,
            org_id=env.org_id,
            proposal_id=pid,
            actor=actor(env, a.get("as", "reviewer")),
            values=ref(env, a.get("values", {})),
            note=a.get("note", "checked (evaluation)"),
        ),
        a,
    )
    return {"refused": err}


@step("agent_submit")
def agent_submit(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Submit the agent's proposal through the public API with the agent's own mandate-bound key."""
    from detent.agents.submit import NotReady, submit_proposal

    pid = env.saved[a.get("proposal", "proposal")]
    try:
        r = submit_proposal(
            env.engine,
            env.clock,
            _client(env),
            agent_key=env.keys["agent"],
            org_id=env.org_id,
            proposal_id=pid,
        )
    except NotReady as exc:
        if a.get("expect_not_ready"):
            return {"not_ready": str(exc)}
        raise
    if a.get("expect_not_ready"):
        raise StepFailed("expected the proposal to be held back for clarification, but it was submitted")
    _expect_http(r, a)
    out: dict[str, Any] = {"http": r.status_code}
    if r.status_code in (200, 201):
        j = r.json()
        out["status"] = j.get("status")
        if a.get("save"):
            env.saved[a["save"]] = j["id"]
        if a.get("expect_status") and j["status"] not in (
            a["expect_status"] if isinstance(a["expect_status"], list) else [a["expect_status"]]
        ):
            raise StepFailed(f"expected {a['expect_status']}, got {j['status']}")
    return out


# ------------------------------------------------------------------------------------------ faults
@step("fault")
def fault(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Arm the fault proxy in front of a rail: ``{rail: chain|bank, match, fault, count}``."""
    url = env.world.chain.proxy_url if a.get("rail", "chain") == "chain" else env.world.bank_proxy  # type: ignore[union-attr]
    r = httpx.post(
        f"{url}/__faults",
        json={
            "match": a["match"],
            "fault": a["fault"],
            "count": a.get("count", 1),
            "attempt": a.get("attempt"),
        },
    )
    r.raise_for_status()
    return {}


@step("clear_faults")
def clear_faults(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    for url in (env.world.chain.proxy_url if env.world.chain else None, env.world.bank_proxy):
        if url:
            httpx.delete(f"{url}/__faults").raise_for_status()
    return {}


@step("disable_rail")
def disable_rail(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE rails SET enabled=false WHERE org_id=:o AND id=:r"),
            {"o": env.org_id, "r": a["rail"]},
        )
    return {}


@step("expect")
def expect(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Mid-scenario expectation on payment statuses: ``{p1: CONFIRMED}``."""
    for name, want in a.items():
        _expect_status(env, ref(env, f"${name}"), {"expect_status": want})
    return {}


@step("concurrently")
def concurrently(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Run the listed steps at the same time, each in its own thread (races). ``steps: [...]``."""
    _client(env)
    items = list(a["steps"])
    outs: list[Any] = [None] * len(items)
    barrier = threading.Barrier(len(items))

    def go(i: int) -> None:
        name, args = next(iter(items[i].items()))
        barrier.wait()
        try:
            outs[i] = STEPS[name](env, dict(args or {}))
        except Exception as exc:  # each racer's own refusal is part of the result, not a scenario error
            outs[i] = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    ts = [threading.Thread(target=go, args=(i,)) for i in range(len(items))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return {"results": outs}


@step("update_counterparty")
def update_counterparty(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    """Change a counterparty's facts (KYB, allowlist) as an operations change would."""
    with env.engine.begin() as c:
        for col in ("kyb_status", "allowlisted", "name"):
            if col in a:
                c.execute(
                    text(f"UPDATE counterparties SET {col}=:v WHERE org_id=:o AND id=:c"),  # noqa: S608
                    {"v": a[col], "o": env.org_id, "c": a["id"]},
                )
    return {}


@step("save_case")
def save_case(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    pid = pid_of(env, a["payment"])
    env.saved[a.get("save", "case")] = open_case(env, pid) or last_case(env, pid)
    return {"case": env.saved[a.get("save", "case")]}


@step("expect_empty")
def expect_empty(env: Env, a: dict[str, Any]) -> dict[str, Any]:
    v = env.saved.get(a["saved"]) or {}
    items = v.get(a.get("field", "data")) if isinstance(v, dict) else v
    if items:
        raise StepFailed(f"expected no items, got {len(items)}")
    return {}
