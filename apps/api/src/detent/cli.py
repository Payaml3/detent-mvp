"""The ``detent`` command line.

detent check-config      validate settings, including the test-network guard
detent api [--port N]    run the API and console
detent worker            run the job worker
detent seed              seed the fictional demo organisation, users, counterparties and rule set
detent audit verify      verify an organisation's hash-chained audit log (AUD-01)
detent ops restore-drill --target-url URL   back up and restore into a drill database, timed, then verify
                         every hash chain, chain head and row count (OPS-03)
detent keys create       issue an sk_test_ API key to a named user (G-08)
detent agent record      run the instruction agent on an invoice with the Claude API and save the response
                         as a recording (replaces the hand-written stand-ins; EVL-04)
detent demo check        test-wallet balances per wallet and chain, and what to top up (DEM-04)
detent demo run <id>     run one demo scenario in the current generation (CON-09); --list shows them
detent demo reset        start a new demo data generation; nothing is deleted (CON-09); --pack picks a
                         scenario pack (DEM-06)
detent demo token deploy|fund --network <n>   the demo's own labelled test token (D-33)
detent eval run ...      evaluation suites and the release gate (eval/, S8)
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from types import FrameType

from pydantic import ValidationError

from detent.settings import Settings, TestNetworkGuardError, get_settings

log = logging.getLogger("detent.cli")


def _load_settings() -> Settings:
    """Load settings or exit with a clear message. Startup fails closed (FND-02)."""
    try:
        return get_settings()
    except (TestNetworkGuardError, ValidationError, ValueError) as exc:
        msg = str(exc)
        if isinstance(exc, ValidationError):
            msg = "; ".join(e["msg"] for e in exc.errors())
        print(f"detent: refusing to start: {msg}", file=sys.stderr)
        raise SystemExit(2) from exc


def _startup_checks(settings: Settings) -> None:
    """Settings are valid; now check what each RPC endpoint actually reports."""
    from detent.chainguard import check_rpc_endpoints

    try:
        check_rpc_endpoints(settings)
    except TestNetworkGuardError as exc:
        print(f"detent: refusing to start: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_check_config(_: argparse.Namespace) -> int:
    s = _load_settings()
    _startup_checks(s)
    chains = s.configured_chain_ids()
    print(f"settings OK: env={s.app_env} chains={chains} allowed={sorted(s.allowed_chain_ids)}")
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    settings = _load_settings()
    _startup_checks(settings)
    import uvicorn

    from detent.api.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_config=None)
    return 0


def cmd_worker(_: argparse.Namespace) -> int:
    settings = _load_settings()
    _startup_checks(settings)
    from detent import logging as dlog
    from detent.runtime import build_runtime
    from detent.worker.loop import Worker

    dlog.configure(settings.log_level, settings.log_json, settings.secret_values())
    worker = Worker(build_runtime(settings))

    def _stop(signum: int, frame: FrameType | None) -> None:
        worker.stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run()
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    settings = _load_settings()
    from detent.runtime import build_runtime
    from detent.seed import seed_demo

    rt = build_runtime(settings)
    summary = seed_demo(rt)
    print(f"seeded: {summary}")
    return 0


def cmd_audit_verify(args: argparse.Namespace) -> int:
    settings = _load_settings()
    from detent.audit.log import verify_chain
    from detent.runtime import build_runtime

    rt = build_runtime(settings)
    org = args.org or settings.demo_org_id
    with rt.engine.connect() as conn:
        st = verify_chain(conn, org)
    if st.ok:
        print(f"audit chain OK: {org}: {st.events} events")
        return 0
    where = f"seq {st.first_bad_seq}" if st.first_bad_seq is not None else "chain head"
    print(f"audit chain BROKEN: {org}: {where}: {st.problem}")
    return 1


def cmd_restore_drill(args: argparse.Namespace) -> int:
    settings = _load_settings()
    from detent.ops.restore_drill import DrillRefused, run_drill

    source = args.source_url or settings.database_url
    try:
        res = run_drill(source, args.target_url)
    except DrillRefused as exc:
        print(f"detent: restore drill refused: {exc}", file=sys.stderr)
        return 2
    print("\n".join(res.summary()))
    return 0 if res.ok else 1


def cmd_keys_create(args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings.api_key_pepper is None:
        print("detent: API_KEY_PEPPER is not set", file=sys.stderr)
        return 2
    from detent.api.auth import issue_key
    from detent.db.engine import transaction
    from detent.runtime import build_runtime

    rt = build_runtime(settings)
    with transaction(rt.engine) as conn:
        key = issue_key(
            conn,
            rt.clock,
            args.org or settings.demo_org_id,
            args.user,
            args.scopes.split(","),
            settings.api_key_pepper.get_secret_value(),
        )
    print(key)  # shown once; only its hash is stored
    return 0


def cmd_staff_add(args: argparse.Namespace) -> int:
    """P2: add a DekernAI admin (an admin of the operator organisation). The password is read from the
    terminal, or from standard input when it is not a terminal; it is never an argument."""
    import getpass

    from detent.dashboard.access import AccessError, create_staff
    from detent.db.engine import transaction
    from detent.runtime import build_runtime

    password = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    rt = build_runtime(_load_settings())
    try:
        with transaction(rt.engine) as conn:
            member = create_staff(conn, rt.clock, email=args.email, display_name=args.name, password=password)
    except AccessError as exc:
        print(f"detent: {exc}", file=sys.stderr)
        return 2
    print(f"added DekernAI admin {member.id} ({member.email}); sign in at /dashboard/login")
    return 0


def cmd_agent_record(args: argparse.Namespace) -> int:
    import json
    from datetime import UTC
    from pathlib import Path

    settings = _load_settings()
    if settings.anthropic_api_key is None:
        print("detent: ANTHROPIC_API_KEY is not set; nothing recorded", file=sys.stderr)
        return 2
    from detent.agents.instruction import SCHEMA, build_prompt
    from detent.agents.llm import AnthropicLLM
    from detent.runtime import build_runtime

    rt = build_runtime(settings)
    doc = Path(args.invoice).read_text()
    with rt.engine.connect() as conn:
        system, user = build_prompt(conn, args.org or settings.demo_org_id, doc, args.mandate)
    res = AnthropicLLM(settings.anthropic_api_key.get_secret_value()).complete(
        model=settings.model_agent, system=system, user=user, schema=SCHEMA
    )
    out = {
        "_provenance": (
            f"Recorded from {res.served_model} on {rt.clock.now().astimezone(UTC).date()} "
            "with `detent agent record`."
        ),
        "match": args.match,
        "usage": {"input_tokens": res.tokens_in, "output_tokens": res.tokens_out},
        "output": json.loads(res.raw_text),
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"recorded {args.out} ({res.tokens_in} in, {res.tokens_out} out)")
    return 0


def cmd_eval(argv: list[str]) -> int:
    """``detent eval run|report|publish ...``: the evaluation runner lives in ``eval/`` (detent-eval)."""
    import importlib

    try:
        runner = importlib.import_module("detent_eval.runner")
    except ImportError:
        print(
            "detent eval: the detent-eval package is not installed (uv sync --all-packages)", file=sys.stderr
        )
        return 1
    rc: int = runner.main(argv)
    return rc


def cmd_demo_check(_: argparse.Namespace) -> int:
    from detent.demo.wallets import check_wallets, render

    lines = check_wallets(_load_settings())
    print(render(lines))
    return 0 if all(w.ok for w in lines) else 1


def cmd_demo_token(args: argparse.Namespace) -> int:
    from detent.demo.token import ENV_NAME, TokenError, deploy_token, fund

    settings = _load_settings()
    try:
        if args.step == "deploy":
            address = deploy_token(settings, args.network)
            print(
                f"deployed the demo token (tUSDC, a test stand-in, not USDC) on {args.network} at {address}"
            )
            print(
                f"set {ENV_NAME[args.network]}={address}, "
                f"then run: detent demo token fund --network {args.network}"
            )
            return 0
        minted = fund(settings, args.network, runs=args.runs)
    except TokenError as exc:
        print(f"detent demo token: {exc}", file=sys.stderr)
        return 1
    if not minted:
        print(f"{args.network}: both wallets already hold enough for {args.runs} run(s)")
    for m in minted:
        print(
            f"{args.network}: minted {m.cents // 100:,}.{m.cents % 100:02d} tUSDC "
            f"to the {m.role} ({m.address})"
        )
    return 0


def cmd_demo_run(args: argparse.Namespace) -> int:
    from detent.audit.log import Actor
    from detent.demo.generations import active_demo_org, demo_user_id
    from detent.demo.scenarios import SCENARIOS, ScenarioError, run_scenario
    from detent.runtime import build_runtime

    if args.list or not args.scenario:
        for sc in SCENARIOS.values():
            print(f"{sc.id:<15} minute {sc.minute:<8} {sc.title}: {sc.what}")
        return 0
    settings = _load_settings()
    rt = build_runtime(settings)
    org = active_demo_org(rt.engine, settings)
    actor = Actor(demo_user_id("usr_pl", org), "payments_lead")  # the CLI acts as the payments lead
    try:
        result = run_scenario(rt, org, args.scenario, actor)
    except ScenarioError as exc:
        print(f"detent demo: {exc}", file=sys.stderr)
        return 1
    print(("(already ran in this generation)\n" if result.repeated else "") + "\n".join(result.lines))
    return 0


def cmd_demo_reset(args: argparse.Namespace) -> int:
    """DEM-06: reset the demo into a scenario pack."""
    from detent.audit.log import Actor
    from detent.demo.generations import ResetRefused, active_demo_org, demo_user_id, reset_demo
    from detent.runtime import build_runtime

    settings = _load_settings()
    rt = build_runtime(settings)
    org = active_demo_org(rt.engine, settings)
    try:
        r = reset_demo(rt, actor=Actor(demo_user_id("usr_pl", org), "payments_lead"), pack=args.pack)
    except ResetRefused as exc:
        print(f"detent demo: {exc}", file=sys.stderr)
        return 1
    print(f"new demo generation {r.generation}: {r.org_id} (pack {args.pack}); {r.previous_org_id} is kept")
    return 0


def _demo_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    dm = sub.add_parser("demo").add_subparsers(dest="demo_cmd", required=True)
    dm.add_parser("check").set_defaults(fn=cmd_demo_check)
    dr = dm.add_parser("run")
    dr.add_argument("scenario", nargs="?")
    dr.add_argument("--list", action="store_true")
    dr.set_defaults(fn=cmd_demo_run)
    tk = dm.add_parser("token").add_subparsers(dest="step", required=True)
    for name in ("deploy", "fund"):
        tp = tk.add_parser(name)
        tp.add_argument("--network", required=True, choices=["base-sepolia", "eth-sepolia"])
        if name == "fund":
            tp.add_argument("--runs", type=int, default=3)
        tp.set_defaults(fn=cmd_demo_token)
    dres = dm.add_parser("reset")
    dres.add_argument(
        "--pack", default="default", help="scenario pack (DEM-06): default, payout-platform, ..."
    )
    dres.set_defaults(
        fn=lambda a: (
            cmd_demo_reset(a)
            if a.pack != "default"
            else cmd_demo_run(argparse.Namespace(list=False, scenario="reset"))
        )
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="detent", description="DekernAI agentic payment controls (prototype)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config").set_defaults(fn=cmd_check_config)
    a = sub.add_parser("api")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8000)
    a.set_defaults(fn=cmd_api)
    sub.add_parser("worker").set_defaults(fn=cmd_worker)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    au = sub.add_parser("audit").add_subparsers(dest="audit_cmd", required=True).add_parser("verify")
    au.add_argument("--org", default=None)
    au.set_defaults(fn=cmd_audit_verify)
    rd = sub.add_parser("ops").add_subparsers(dest="ops_cmd", required=True).add_parser("restore-drill")
    rd.add_argument(
        "--target-url", required=True, help="a separate database whose name contains restore or drill"
    )
    rd.add_argument("--source-url", default=None, help="defaults to DATABASE_URL")
    rd.set_defaults(fn=cmd_restore_drill)
    k = sub.add_parser("keys").add_subparsers(dest="keys_cmd", required=True).add_parser("create")
    k.add_argument("--org", default=None)
    k.add_argument("--user", required=True)
    k.add_argument("--scopes", default="read,intents:create")
    k.set_defaults(fn=cmd_keys_create)
    st = sub.add_parser("staff").add_subparsers(dest="staff_cmd", required=True).add_parser("add")
    st.add_argument("--email", required=True)
    st.add_argument("--name", required=True)
    st.set_defaults(fn=cmd_staff_add)
    ag = sub.add_parser("agent").add_subparsers(dest="agent_cmd", required=True).add_parser("record")
    ag.add_argument("--invoice", required=True)
    ag.add_argument("--match", required=True, help="text in the invoice that selects this recording")
    ag.add_argument("--out", required=True)
    ag.add_argument("--org", default=None)
    ag.add_argument("--mandate", default="mnd_demo_ap_agent")
    ag.set_defaults(fn=cmd_agent_record)
    _demo_parsers(sub)
    sub.add_parser("eval", help="evaluation suites: detent eval run --suite all (see eval/)", add_help=False)
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "eval":
        return cmd_eval(argv[1:])
    args = p.parse_args(argv)
    rc: int = args.fn(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
