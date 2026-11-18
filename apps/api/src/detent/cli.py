"""The ``detent`` command line.

detent check-config      validate settings, including the test-network guard
detent api [--port N]    run the API and console
detent worker            run the job worker
detent seed              seed the fictional demo organisation and users
detent eval run ...      evaluation suites (built in M6)
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


def cmd_eval(_: argparse.Namespace) -> int:
    print(
        "detent eval: not built yet (EVL-01, milestone M6). Failing so CI can't pass by accident.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="detent", description="Detent agentic payment controls (prototype)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config").set_defaults(fn=cmd_check_config)
    a = sub.add_parser("api")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8000)
    a.set_defaults(fn=cmd_api)
    sub.add_parser("worker").set_defaults(fn=cmd_worker)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    e = sub.add_parser("eval")
    e.add_argument("action", nargs="?", default="run")
    e.add_argument("--suite", default="all")
    e.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    rc: int = args.fn(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
