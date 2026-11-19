# HANDOFF: start here in every new session

One repository, one session per slice. A new session reads `CLAUDE.md`, then this file, and then only
the specs and code the slice needs. At the end of the slice, update this file and push it with the slice.

Last updated: 2026-11-19, after slice S7.

## Where we are

| Slice | Status | Branch |
|---|---|---|
| S0 to S7 (prototype engine: decide, send once, review, never twice, agent + mandates, operations, ledger, deposits, reconciliation, replay) | done | `s7` holds all of them (stacked: m0 -> s1 -> ... -> s7) |
| **S8 Proof and release gate** | **next** | start `s8` from `s7` |
| S9 Demo-ready prototype in the EU | todo | |
| P1 Sandbox API and webhooks, P2 Dashboard, P3 Docs and SDKs, P4 Website launch | todo | |
| L After launch (Should and Could) | todo | |

Nothing is merged to `main`; the founder has not asked for PRs. Each slice branches from the previous one.
Progress: `make spec` reports criteria done with evidence (199/308 after S7).

## Start a session

```
git fetch origin s7 && git checkout -b s8 origin/s7   # or the latest slice branch
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

## Session names

Name each session `Detent · <slice> <slice name>`, for example `Detent · S8 Proof and release gate`, and
tag it `detent` and `slice:<id>`. When a slice is done, rename its session to end in `(done)`.
The S0 to S7 work happened in one session: `Detent · S0–S7 build (done)`.

## How we work (unchanged)

- Read the slice and its stories: `specs/001-detent-mvp/slices.yaml`, `backlog/user-stories.md`.
- Before building on a rule marked **Proposed** or **Open** in `specs/001-detent-mvp/decisions.md`, ask the
  founder (AskUserQuestion), then record the answer as a new `D-` row and mark the item Confirmed.
- Test first. Never weaken a test; tightening an old placeholder test is fine and is said in the commit.
- Finish: tick `done:` in `backlog/stories.yaml`, add evidence to `specs/001-detent-mvp/test-map.yaml`,
  mark the slice `status: done` in `slices.yaml`, run `make backlog spec`, update specs, commit with the
  story IDs, push the slice branch, check CI, then update this file.
- Report to the founder: what was built, test evidence, screenshots of new screens, gaps, open items.

## Next slice: S8 Proof and release gate

Exit: `make eval` passes with 100+ attacks and 0 unauthorised, 30+ faults and 0 duplicates, canonical
invoice 10/10; a dated report is generated; CI blocks a deliberately injected regression.
Stories: EVL-01 to EVL-08. Specs: `spec/09-evaluation-and-tests.md`, `eval/`.
Reusable pieces: `tests/recon_helpers.py` (500-item reconciliation set), the fault proxy
(`apps/faultproxy`), `tests/bank_helpers.py`, `tests/chain_helpers.py`, recorded agent stand-ins in
`fixtures/agent-recordings/`. The judge model is `claude-opus-5-5` (evaluation only).

## Open founder items

- `INDEPENDENCE_DENYLIST` CI secret (the OPS-02 check fails closed until it is set).
- `ANTHROPIC_API_KEY`: every agent answer is a labelled hand-written stand-in until real runs are recorded
  (AGT-01 10/10, EVL-04).
- A funded test wallet for Base Sepolia and Ethereum Sepolia (RAL-02, RAL-03, S9).
- User payouts are deferred (founder, before S1): demo batch p07 to p20 can't run, so LED-06 AC4 stays open.
- C-13 scope choice; C-10, C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 still Proposed or Open.
- Booking URL, inbox, final name and domain (`BRAND_NAME`), legal review of the site.
- Delete the stale remote branch `s3-unknown-resolved` (the proxy refused).

## Known gaps carried forward

- RAL-02/03 real Sepolia runs; RAL-07 switching networks; POL-06 retry and re-route endpoints.
- EXC-07 incident notices; CON-03 route display; CON-05 PDF path untested; EVL-02 attack suite (S8).
- Return-to-sender books a refund as due; sending the refund payout is not automated.
- A bank deposit is "pending" in reconciliation until that day's statement is imported.
- Flaky under load: `test_banksim.py::test_contract` (passes on rerun).

## Business context

`founder/` holds the founder material written so far (landing page copy). Business notes from the
claude.ai chat "Stablecoin payment acceptance MVP" belong in `founder/business-context.md` once the
founder shares them (see that file). Read it when a slice touches positioning, pricing or the website.
