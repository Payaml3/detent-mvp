# HANDOFF: start here in every new session

One repository, one session per slice. A new session reads `CLAUDE.md`, then this file, and then only
the specs and code the slice needs. At the end of the slice, update this file and push it with the slice.

Last updated: 2026-11-20, S9 code built (branch `claude/project-thread-rbgh7v`); the live deploy and testnet run wait on the founder.

## Where we are

| Slice | Status | Branch |
|---|---|---|
| S0 to S7 (prototype engine: decide, send once, review, never twice, agent + mandates, operations, ledger, deposits, reconciliation, replay) | done | `main` |
| S8 Proof and release gate | done | `main` |
| **S9 Demo-ready prototype in the EU** | **code built; deploy and live testnet run pending** | `claude/project-thread-rbgh7v` (one PR into `main`) |
| P1 Sandbox API and webhooks, P2 Dashboard, P3 Docs and SDKs, P4 Website launch | todo | |
| L After launch (Should and Could) | todo | |

`main` holds S0 to S8. Each new slice branches from `main` and comes back as one pull request into `main`.
Progress: `make spec` reports criteria done with evidence (219/308 after the S9 build).

## Start a session

```
git fetch origin main && git checkout -b s9 origin/main
```

The cloud environment `detent-mvp` has a setup script that starts Postgres, creates the `detent` role
and the `detent` and `detent_test` databases, runs `uv sync`, migrates and seeds. If a session was not
built fresh (a resumed container), run the same steps by hand (there is no Docker in cloud containers):

```
pg_ctlcluster 16 main start
su postgres -c "psql -c \"CREATE ROLE detent LOGIN SUPERUSER PASSWORD 'detent'\""   # if missing
su postgres -c "createdb -O detent detent"; su postgres -c "createdb -O detent detent_test"
uv sync && make migrate seed
```

Then `make lint typecheck test` (about 3 minutes; chain tests need Foundry, which is installed).
`make eval` runs every evaluation suite and the release gate (about 10 minutes; needs Postgres and
`cd chain && forge build`). The environment setup script installs Foundry from npm (GitHub release
downloads are blocked in cloud containers) and needs `binaries.soliditylang.org` allowed for solc.

## Session names

Name each session `Detent · <slice> <slice name>`, for example `Detent · S8 Proof and release gate`, and
tag it `detent` and `slice:<id>`. When a slice is done, rename its session to end in `(done)`.
The S0 to S7 work happened in one session: `Detent · S0–S7 build (done)`.

## How we work (unchanged)

- One session per story group: 3 to 6 related stories that share files. Aim to finish well before the warn
  limit, about 100k tokens.
- A slice can take several sessions.
- Read the slice and its stories: `specs/001-detent-mvp/slices.yaml`, `backlog/user-stories.md`.
- Before building on a rule marked **Proposed** or **Open** in `specs/001-detent-mvp/decisions.md`, ask the
  founder (AskUserQuestion), then record the answer as a new `D-` row and mark the item Confirmed.
- Test first. Never weaken a test; tightening an old placeholder test is fine and is said in the commit.
- Finish: tick `done:` in `backlog/stories.yaml`, add evidence to `specs/001-detent-mvp/test-map.yaml`,
  mark the slice `status: done` in `slices.yaml`, run `make backlog spec roadmap-page`, update specs, commit with the
  story IDs, push the slice branch, check CI, then update this file.
- Refresh the founder's phone roadmap: publish `build/roadmap.html` (from `make roadmap-page`) to the existing
  Artifact https://claude.ai/artifact/THq22MAqSJrDauRH39oWAe (pass it as `url`; never create a new one).
- Report to the founder: what was built, test evidence, screenshots of new screens, gaps, open items.

## What S8 built

- `detent eval run|report|publish` (`eval/`, package `detent-eval`): scenarios are YAML in `eval/scenarios/`,
  the step vocabulary is `eval/src/detent_eval/steps.py`, and `checks.py` is an independent checker that reads
  the audit log, attempts, the chain's Transfer logs and banksim's payments. See spec/09 "As built (S8)".
- Results of the last full run: 120 attacks with 0 unauthorised executions, 52 faults with 0 duplicates,
  interpretation 30 invoices (canonical 10/10, 0 invented values, stand-in answers), agreement 96% (rules vs
  synthetic labels) and 59% (stand-in investigation vs labels), reconciliation 99.40% with all 3 designed
  breaks found, latency p95 about 39 ms rules-only and 75 ms with the investigation (in-process, CI-class).
- CI: the `release gate (detent eval)` job runs on main, tags, pull requests and `claude/` branches and uploads
  `eval/out/` (report.html, report.md, results.json) as an artifact. Nightly: `.github/workflows/eval-nightly.yml`.
- Five product gaps the suites found, fixed with regression tests (`integration/test_eval_findings.py`):
  attempt for a BLOCKED payment (code check + migration 0008 trigger); replay of an older signed mandate
  version (audit-backed check); destination changed after the decision (pre-send re-run); expired
  organisation keys still worked (403 `organisation_expired`, the API half of DSH-03); worker crash between
  storing the signed transaction and broadcasting it left the payment SUBMITTED (now UNKNOWN + resolver).
- 24 new invoices with expected outputs (`fixtures/invoices/interpretation-set.yaml`, generated by
  `eval/tools/make_interpretation_set.py`) and their hand-written stand-ins; 50 synthetic agreement cases
  (`eval/data/agreement-set.yaml`).

## What S9 built (code; the slice exit needs the live run)

- **Demo generations (CON-09 reset, G-26 Proposed):** `detent/demo/generations.py`, migration 0009
  (`demo_generations`, append-only). Reset seeds a fresh fictional organisation (`org_demo_g2`, ...); the console,
  the demo clock and the agent's key follow the newest one; the old one keeps everything and has its kill switch
  engaged. Refused while an attempt is in flight; payments lead only. Later generations suffix user IDs
  (`usr_pl_demo_g2`); each gets its own agent key, derived from `AGENT_API_KEY`.
- **Scenario runner (CON-09):** `detent/demo/scenarios.py`, the console **Demo** screen and `detent demo run <id>`:
  `invoice_18500`, `forced_timeout`, `batch_20`, `close_day`, `attack_sample`, `reset`. Once per generation
  (recorded as `demo.scenario_run`). The runner never sends a payout or approves; it plays the payers and arms
  faults (fault proxy: new `body_contains` filter and `GET /__faults`; `FAULTPROXY_DEMO_MODE=1`).
- **Batch (DEM-03, D-32):** p07 to p20 now pay two new fictional counterparties, `cpt_lumen` (both chains) and
  `cpt_kestrel` (Faster Payments). Deposits need `DEMO_PAYER_PRIVATE_KEY_BASE/ETH`.
- **`detent demo check` (DEM-04):** `detent/demo/wallets.py`; needs come from the fixtures.
- **FND-07:** `/healthz` reports database, `base-sepolia`, `eth-sepolia` (both must be ok in demo mode) and the
  regions; the footer states `HOSTING_REGION` and `DATABASE_REGION`; `render.yaml` (Frankfurt) plus Neon EU.
- **spec/11 rewritten** to the built screens (DEM-05); spec/07 and spec/10 have "As built (S9)" notes.
- **Two product gaps found and fixed:** seeded EVM rails had no `from_address`, so the watcher never recorded the
  demo's own payouts and every chain payout would have been a reconciliation break (`seed_rails` now sets it);
  the bank statement day now comes from the bank simulator's own business date (`/healthz` `business_date`).
- **Evidence:** `chain/test_demo_scenarios.py` is a full local rehearsal (two anvil chains standing in for the
  Sepolias, banksim, fault proxy, the real worker): $18,500 escalates, is approved, times out to UNKNOWN and is
  confirmed with one transaction; the batch gives 17 CONFIRMED, 2 ESCALATED, 1 BLOCKED (no attempt), p08 fails
  over Base to Ethereum under one ID, close the day gives 24 of 25 matched with one break (dep-07), and a rerun
  changes nothing. `integration/test_demo_generations.py`, `unit/test_demo_wallets.py`.

## Next: finish S9 (live), then P1

- **S9 live run** (needs the founder items below): deploy `render.yaml`, set the secrets, `detent demo check`,
  then run spec/11 on Base Sepolia and Ethereum Sepolia and fix any mismatch in spec/11; then mark S9 done
  (FND-07 criterion 0 and the slice exit). · Model: mid-tier
- Group 1 of P1, after S9: see `specs/001-detent-mvp/slices.yaml` (P1). · Model: strongest (API and webhooks touch money paths)

## Open founder items

- **S9 live run:** a Render account (Frankfurt) and a Neon project in an EU region; the plans (Render's free plan
  covers the web service only; the worker and the two private services need a paid instance type: Proposed);
  the secrets in `render.yaml`; funded test wallets (four: sender and payer on each chain).
- **G-27 (Open):** which test USDC: the script needs about $20,000 of test USDC per run and Circle's faucet gives
  about 20 per request. Recommended: our own labelled test token (needs `MockUSDC.sol` to allow the two Sepolias).
- C-10 (match line counts money-moving items only) and C-13 (scope) were asked on 2026-11-20; still Proposed/Open
  until answered.
- `ANTHROPIC_API_KEY` (also as a GitHub secret for the nightly eval): every agent answer is a labelled
  hand-written stand-in until real runs are recorded (AGT-01 10/10, EVL-04). The interpretation and
  agreement figures measure Detent's checks, not a model, until then.
- Publishing the measured results on the website: `uv run detent eval publish` writes
  `apps/site/src/data/results.json` from a passing full run (EVL-06 criterion 1 stays open until then).
- Nightly eval against public testnets needs funded test wallets and RPC endpoints as secrets (EVL-07 criterion 0).
- A funded test wallet for Base Sepolia and Ethereum Sepolia (RAL-02, RAL-03, S9).
- User payouts are deferred (founder, before S1); the demo batch now pays counterparties instead (D-32).
- C-13 scope choice; C-10, C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 still Proposed or Open.
- Booking URL, inbox, final name and domain (`BRAND_NAME`), legal review of the site.
- Delete the stale remote branch `s3-unknown-resolved` (the proxy refused).
- Delete the merged branches (all are in `main`): `m0-foundation`, `s1-decision-layer`, `s2-send-once`, `s3-review-loop`, `s3-unknown-resolved`, `s4-unknown-resolved`, `s5-agent-mandates`, `s6`, `s7`, `claude/project-thread-uhabrn`, `spec/001-detent-mvp`, `web/002-marketing-site`.

## Known gaps carried forward

- RAL-02/03 real Sepolia runs; RAL-07 switching networks; POL-06 retry and re-route endpoints.
- EXC-07 incident notices; CON-03 route display; CON-05 PDF path untested.
- Parallel intents can deadlock on the audit head and counter rows (lock order); the loser fails closed with
  an error, nothing is paid twice, but a burst can see some 500s (seen in the split-payment attacks).
- DSH-03: only the API side (403 `organisation_expired`) is built; the read-only dashboard and extension are P2.
- Return-to-sender books a refund as due; sending the refund payout is not automated.
- A bank deposit is "pending" in reconciliation until that day's statement is imported.
- Flaky under load: `test_banksim.py::test_contract` (passes on rerun).
- The Evaluation console screen is still "not built"; spec/11 shows the release-gate report file instead.
- The seeded `local-evm` rail also appears in the deployed demo's Rails screen (no adapter there, so unused).
- dep-08's "duplicate notification" on a chain is a re-scan of the same block by the demo runner.

## Business context

`founder/` holds the founder material written so far (landing page copy). Business notes from the
claude.ai chat "Stablecoin payment acceptance MVP" belong in `founder/business-context.md` once the
founder shares them (see that file). Read it when a slice touches positioning, pricing or the website.
