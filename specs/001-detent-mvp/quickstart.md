# Quickstart: validate the MVP slice by slice

How to check each slice's exit (see [tasks.md](tasks.md)). Commands assume the repository root.

## Every slice

```bash
make db
```

```bash
make lint typecheck test
```

```bash
python tools/build_spec.py
```

`build_spec.py` must print `OK`: every requirement covered, every cited test present.

## S0 Foundation (done)

```bash
uv run pytest -q
```

Expect 326 passed (2026-11-18), including the worker-kill test and the local-chain tests.

## S1 to S9 (after implementation)

| Slice | Validation |
|---|---|
| S1 | `uv run pytest apps/api/tests -k "int_0 or pol_0 or aud_01"`; then `POST /v1/payment_intents` for each fixture counterparty and compare with spec.md User Story 1 |
| S2 | `make chain` in one terminal, `make dev` in another; an EXECUTE payout reaches CONFIRMED with one transfer (check `chain/local.json` and the explorer-less anvil logs) |
| S3 | In the console as Sam (reviewer): open the case, check raw facts are first, approve with a reason; payment detail shows the re-run decision and one attempt |
| S4 | `uv run pytest apps/api/tests -m fault` (marker added in S4) and the fault scenarios in `eval/scenarios/faults` |
| S5 | Console → Invoice drop → `fixtures/invoices/inv-canonical-18500-usdc.txt` → Submit as agent → follow S3 |
| S6 | Demo clock +1 h, +1 h, +15 m on an escalation; check Outbox and the case owner |
| S7 | Run `fixtures/batches/demo-batch-20.yaml`; Reconciliation shows one break (dep-07) with a proposed fix; Replay any payment |
| S8 | `make eval`; open `eval/out/report.html` |
| S9 | Follow `spec/11-demo-script.md` on the deployed instance |
