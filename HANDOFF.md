# HANDOFF: start here in every new session

One repository, one session per slice. A new session reads `CLAUDE.md`, then this file, and then only
the specs and code the slice needs. At the end of the slice, update this file and push it with the slice.

Last updated: 2026-11-28: P4 built except the booking URL and go-live (founder). Earlier, 2026-11-25: The founder passed playbook stage 8 (specify): every C- and G- item is Confirmed (D-38); the G-19 legal review is still due before P4.

Earlier, 2026-11-24: the founder confirmed DekernAI is in MVP development (TRL 4) and passed playbook stages 7 (MVP scope), 9 (screen specs: every criterion linked to a story in `traceability.md`) and 12 (tasks and story groups); stages 1 to 6, 10 and 11 wait on the founder's Passed or Deferred call. The founder chose the full MVP scope on 2026-11-23 (D-37). The dashboard runs on Vercel behind its login, on solo-to-scale 2.7.0.

Previous: 2026-11-20, S9 code merged into `main` (PRs #6, #8) on the solo-to-scale operating system (#7); the live deploy and testnet run wait on the founder. The Monday weekly review runs as a scheduled task (07:39 UK time).

## Where we are

| Slice | Status | Branch |
|---|---|---|
| S0 to S7 (prototype engine: decide, send once, review, never twice, agent + mandates, operations, ledger, deposits, reconciliation, replay) | done | `main` |
| S8 Proof and release gate | done | `main` |
| **S9 Demo-ready prototype in the EU** | **code merged; deploy and live testnet run pending** | `main` (the live-run fixes come back as one PR) |
| P1 Sandbox API and webhooks | done | `main` |
| P2 Dashboard and sandbox | done | `main` |
| P3 Docs and SDKs | done (Mintlify connection and SDK publishing wait on the founder) | `main` |
| P4 Website launch | built: WEB-02, WEB-07 done; the access form posts to the live deploy. Open: the booking URL (WEB-06), the legal review and the founder's go-live call | `main` |
| L After launch (Should and Could) | done: groups 1 to 4 built (17 stories); exit check met | `main` |
| U User payouts (D-40, 28 Nov) | done: USR-01 to USR-04 built | `main` |

Scope (D-37, 2026-11-23): the full MVP backlog, every slice above in order; it supersedes D-34 (prototype first).

`main` holds S0 to S8 and the S9 code. Each new slice branches from `main` and comes back as one pull request into `main`.
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

Name each session `DekernAI · <slice> <slice name>`, for example `DekernAI · S8 Proof and release gate`, and
tag it `detent` and `slice:<id>`. When a slice is done, rename its session to end in `(done)`.
The S0 to S7 work happened in one session: `DekernAI · S0–S7 build (done)`.

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

- **Demo generations (CON-09 reset, G-26 Confirmed: D-36):** `detent/demo/generations.py`, migration 0009
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

## Next: P1 now, the S9 live run when the founder items are in

- **S9 live run** (needs the founder items below): deploy on Hetzner + Neon (`infra/hetzner/README.md`; replaces `render.yaml`), set the secrets, `detent demo check`,
  then run spec/11 on Base Sepolia and Ethereum Sepolia and fix any mismatch in spec/11; then mark S9 done
  (FND-07 criterion 0 and the slice exit). · Model: mid-tier
- **P1 group 1: built (PR from `claude/project-thread-babje1`, 2026-11-26):** API-01 to API-04 and API-06. The
  error-code catalogue is `detent/api/error_codes.py` (`make error-docs` writes `docs/api/errors.md`; the test session
  fails on an uncatalogued code); `DekernAI-Version` with the organisation's pinned default; per-key and per-address
  rate limits; `GET /v1/request_logs` with a 30-day worker sweep. See spec/03 "As built (P1 group 1)".
- **P1 group 2: built (second PR from `claude/project-thread-babje1`, 2026-11-26):** WHK-01, WHK-03, API-05,
  API-07, EXC-08. Events come from `audit.log.append` in the same transaction (`detent/webhooks/events.py`);
  endpoints with encrypted secrets and an SSRF guard; signed delivery jobs with the G-20 retries and a delivery log;
  `GET /v1/events` and `GET /v1/exceptions`; `docs/api/openapi.json` from `make openapi`, Redocly-linted in CI.
  Read-only views shared by the API, console and webhooks moved to `detent/views/`. WHK-02 stays open until the
  docs verify helpers have tests in every language (DOC-04). DNS rebinding at delivery is a known follow-up.
  See spec/03 "As built (P1 group 2)".
- **P2 group 1: built (PR from `claude/project-thread-babje1`, 2026-11-26):** DSH-01, DSH-02 (criteria 0 and 1),
  DSH-03, DSH-11. `detent/dashboard/` (access rules in `access.py`, screens in `routes.py` and `admin.py`),
  migration 0011. DekernAI admins come from `detent staff add`. See spec/08 "As built (P2 group 1)". Open: the email
  provider (founder item; DSH-02 criterion 2).
- **P2 group 2: built (PR from `claude/project-thread-babje1`, 2026-11-26):** DSH-04, DSH-05, DSH-06, DSH-08,
  LED-08. Pages in `detent/dashboard/developer.py` (key service in `keys.py`), metering and quotas in
  `detent/sandbox/usage.py`, migration 0012. 429 `quota_exceeded` over the payment quota. See spec/08 "As built
  (P2 group 2)". Open: SBX-02 waits for the shared testnet wallet's daily cap (group 3).
- **P2 group 3a: built (PR from `claude/project-thread-babje1`, 2026-11-26):** RAL-11, SBX-01 (criterion 0),
  SBX-02, SBX-03. The simulated chain in `detent/rails/simchain.py` (migration 0013), chosen per organisation in
  `rails/registry.build_adapters` (now takes `clock=`); the faucet caps in `execution/send._check_shared_wallet`;
  the sandbox page in `dashboard/developer.py` and `dashboard/sandbox.py`. See spec/08 "As built (P2 group 3a)".
- **P2 group 3b: built (PR from `claude/project-thread-babje1`, 2026-11-26):** SBX-04 and DSH-07. The reset is a new
  data generation (migration 0014, `detent/sandbox/generations.py`, `dashboard/sandbox.reset_sandbox`); API and
  dashboard reads filter on it. See spec/08 "As built (P2 group 3b)".
- **P2 group 4a: built (PR from `claude/project-thread-babje1`, 2026-11-26):** DSH-10 (`dashboard/leads.py`,
  `dashboard/public.py`, `POST /access-requests`) and DSH-12 (`dashboard/verification.py`), migration 0015. See
  spec/08 "As built (P2 group 4a)". WEB-06 points the site's form at `<dashboard>/access-requests` once deployed.
- **P2 group 4b: built (PR from `claude/project-thread-babje1`, 2026-11-26):** DSH-09. A dashboard member opens
  `/console/` as themselves (`console/auth.dashboard_member`), scoped to their organisation and current data
  generation; demo-only controls answer 404 (`demo_only`). See spec/08 "As built (P2 group 4b)". P2 is complete.
- **P3 group 1: built (PR from `claude/project-thread-babje1`, 2026-11-26):** DOC-01, DOC-02, DOC-06, SDK-03 and
  SBX-01 criterion 1. The Mintlify site in `docs/` (`docs.json`, `.mintignore`), `tools/build_docs.py`
  (`make docs-check`, Postman collection). See spec/08 "As built (P3 group 1)". Founder: connect Mintlify (Starter)
  to `docs/` and set the domains (replace `SITE_DOMAIN` and `<domain>`).
- **P3 group 2: built (PR from `claude/project-thread-babje1`, 2026-11-27):** DOC-03 (six guides in
  `docs/guides/`, run by `tests/integration/test_docs_guides.py`) and DOC-05 (`tools/try-it.mdx`). Sandbox
  organisations now get the agent mandate and travel-rule originator details. See spec/08 "As built (P3 group 2)".
- **P3 group 3: built (PR from `claude/project-thread-babje1`, 2026-11-27):** SDK-01 (`sdks/python`) and SDK-02
  (`sdks/typescript`), generated by `tools/build_sdks.py`, with CI's new `sdks` job against a sandbox API. Also:
  monotonic IDs within a millisecond, and the `/v1/decisions` response in the OpenAPI file. See spec/08 "As built
  (P3 group 3)". Founder: the SDKs' licence and any package index release.
- **P3 group 4: built (PR from `claude/project-thread-babje1`, 2026-11-27):** DOC-04 and WHK-02 criterion 0. The
  quickstart payout and webhook verification samples are files in `docs/snippets/<lang>/` (cURL, Python,
  TypeScript, Go, Java, C#, PHP, Ruby; standard library only). `tools/run_snippets.py` runs each language against
  `docs/snippets/webhook-vectors.txt` and the CI sandbox; `tools/build_docs.py` writes them into the pages. See
  spec/08 "As built (P3 group 4)". P3 is complete.
- **P4 WEB-04: built (PR from `claude/project-thread-babje1`, 2026-11-27):** the site's code tabs come from the
  docs' tested samples (`apps/site/src/data/snippets.json`, written by `tools/build_docs.py`).
- **P4 rest: built (PR from `claude/project-thread-ci5zmu`, 2026-11-28):** WEB-02 criterion 1 (data handling on the
  onboarding page), WEB-06 access form to `https://app.dekernai.com/access-requests`, WEB-07 status page (`/status/` on
  the site, fed by `GET /status.json` in `detent/api/status.py`). See spec/08 "As built (P4)". To finish P4: the
  booking URL into `bookingUrl` (WEB-06), the G-19 and legal-pages review, `indexable: true` at go-live (founder), and
  `STATUS_DOCS_URL` on the deploy once the docs are published (an infra change: founder-approved label).
- **L group 1: built (PR from `claude/project-thread-zzhxlz`, 2026-11-28):** INT-05 cancel (`detent/intents/cancel.py`,
  `POST /v1/payment_intents/{id}/cancel`, 409 `not_cancellable`), EXE-10 invariant monitor and OPS-01 incidents
  (`detent/incidents/`, console Incidents screens, Sev 1 banner, migration 0016), CON-10 fail-safe changes with two
  leads plus read-only deadlines and weights. See spec/07 "As built (L group 1)" and spec/10 Runbooks.
- **L group 2: built (2026-11-28):** shadow mode. SHD-01 import with column mapping and a validation report, decided
  in memory with nothing executed (`detent/shadow/imports.py`); SHD-04 per-import salted hashes; SHD-02 report with a
  weekly view and HTML and PDF exports (`detent/shadow/report.py`, `pdf.py`); SHD-03 mode gates at 95% and zero
  unsafe approvals (D-41, `detent/shadow/gates.py`), signed by both leads and required for a production organisation to
  move up; EXC-09 agreement sample (`/console/agreement`); DSH-13 production request, recorded only. Migration
  0017. See spec/07 and spec/08 "As built (L group 2)".
- **L group 3: built (2026-11-28):** RAL-08 rail health and a per-rail circuit breaker (`detent/rails/health.py`;
  routing skips an open circuit; the worker probes and closes it), RAL-09 mock rail connection with encrypted
  credentials (`detent/rails/connections.py`, `/console/rails/connect`), RAL-10 daily contract run that opens an
  issue on failure (`.github/workflows/rail-contracts.yml`, `tools/contract_report.py`). Migration 0018. See spec/06.
- **L group 4: built (2026-11-28):** AUD-03 evidence export (`/console/audit`, JSON, HTML and PDF), OPS-03 restore
  drill (`detent ops restore-drill`, runbook and drill log in spec/10; the Neon point-in-time drill waits for the
  hosted database), OPS-04 security pack (`docs/security.md` from `tools/build_security.py`, internal only), DEM-06
  scenario packs (`fixtures/packs/`, selectable on reset). Slice L is complete.
- **Slice U: built (2026-11-28):** USR-01 user accounts with one destination each and the typed `user_verified`
  flag (`PUT /v1/user_accounts/{ref}`, `detent/intents/users.py`, migration 0019); USR-02 the user payout profile
  in the engine (counterparty checks NOT_EVALUATED, `user_verified` escalates USER_NOT_VERIFIED, platform cap only);
  USR-03 console, OpenAPI, docs guide (`docs/guides/user-payouts.mdx`) and SDKs; USR-04 nine eval attacks
  (`eval/scenarios/attacks/user-payouts.yaml`) and three seeded fictional users as sandbox test values. The demo
  batch stays counterparty-only (D-32). See spec/04 "As built (slice U)".
- **Next:** the backlog is built. Open founder items below (deploy, live testnet run, publishing). · Model: mid-tier

## Open founder items

- **S9 live run (host chosen 27 Nov: Hetzner + Neon):** a Hetzner Cloud server (CAX11, Helsinki) with Coolify and a
  Neon project in AWS Frankfurt, set up step by step in `infra/hetzner/README.md`; the secrets typed into
  Coolify; funded test wallets (four: sender and payer on each chain); `ANTHROPIC_API_KEY`.
- **G-27 Confirmed (D-33):** the live demo pays in its own labelled test token (tUSDC). Before the live run, per
  network: `detent demo token deploy --network <n>`, set `USDC_ADDRESS_*` to the printed address, then
  `detent demo token fund --network <n>`; gas comes from a faucet.
- C-10 Confirmed (D-35): the match line counts money-moving items only (24 of 25; 26 of 27 with both escalations
  approved, now tested). C-13 Confirmed (D-37, 2026-11-23): full scope,
  superseding D-34 (prototype first).
- `ANTHROPIC_API_KEY` (also as a GitHub secret for the nightly eval): every agent answer is a labelled
  hand-written stand-in until real runs are recorded (AGT-01 10/10, EVL-04). The interpretation and
  agreement figures measure DekernAI's checks, not a model, until then.
- Publishing the measured results on the website: `uv run detent eval publish` writes
  `apps/site/src/data/results.json` from a passing full run (EVL-06 criterion 1 stays open until then).
- Nightly eval against public testnets needs funded test wallets and RPC endpoints as secrets (EVL-07 criterion 0).
- A funded test wallet for Base Sepolia and Ethereum Sepolia (RAL-02, RAL-03, S9).
- User payouts are deferred (founder, before S1); the demo batch now pays counterparties instead (D-32).
- C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 Confirmed as proposed (D-38, 2026-11-24); G-19 retention still
  needs the founder's legal review before the P4 launch. With G-10 decided, user payouts (D-26) can be built; no story
  covers them yet and the API still returns 422 `user_payouts_unavailable`. Ask the founder which slice takes them.
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
