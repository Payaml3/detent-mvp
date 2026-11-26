# Research and technical decisions: DekernAI MVP

Phase 0 of [plan.md](plan.md). These are **technical** decisions within the stack the founder fixed in `AGENTS.md`.
None of them sets a business rule. Business rules are in [decisions.md](decisions.md).

## R-01 Identifiers: prefixed UUIDv7 in Crockford base32 (implemented, M0)

- **Decision**: `<prefix>_<26 chars>`, time-ordered; seeded fixture rows keep readable IDs (`cpt_bluefin`).
- **Rationale**: spec/02 asks for prefixed UUIDv7; base32 keeps them short, sortable and URL-safe.
- **Alternatives**: ULID (not UUIDv7), hex UUIDs (long), database sequences (leak volume, not portable across orgs).

## R-02 Database access: SQLAlchemy Core with SQL migrations (implemented, M0)

- **Decision**: Core tables, not the ORM; migrations are hand-written SQL files run by Alembic, forward-only.
- **Rationale**: the invariants live in constraints and triggers (partial unique indexes, terminal and append-only
  triggers) that read best as SQL; Core keeps every statement visible for the org-scope guard.
- **Alternatives**: ORM models with autogenerate (hides partial indexes and triggers); raw psycopg (loses composition).

## R-03 Organisation isolation: composite foreign keys plus a statement guard (implemented, M0)

- **Decision**: every child references `(org_id, id)` of its parent; an engine hook refuses SELECT, UPDATE or DELETE
  on organisation tables without `org_id`, unless the call declares `cross_org=<reason>`.
- **Rationale**: invariant 16 fails closed in two independent places.
- **Alternatives**: Postgres row-level security (stronger, but needs per-request roles and complicates the worker;
  candidate for production).

## R-04 Background jobs: Postgres queue with lease and fencing (implemented, M0)

- **Decision**: `FOR UPDATE SKIP LOCKED` claim with a lease; the handler's writes and `done_at` commit together,
  fenced on `locked_by`.
- **Rationale**: one dependency fewer than a broker; exactly-once database effects proven by the SIGKILL test.
- **Alternatives**: Celery or RQ with Redis (another service, at-least-once only), holding the row lock for the
  whole job (blocks intermediate commits the execution layer needs).

## R-05 Time: Clock service with a persisted demo offset (implemented, M0)

- **Decision**: `SystemClock`, `FrozenClock` (tests), `DemoClock` (real time plus a per-organisation offset in
  `demo_clock`, cached for 0.5 s).
- **Rationale**: the API and the worker must agree on fast-forwarded time for deadlines and polling.

## R-06 Sending EVM transactions: sign locally, store raw transaction before broadcast (S2)

- **Decision**: the `Signer` interface signs with test keys from settings; the attempt stores `nonce`, `raw_tx` and
  `tx_hash` in a committed row **before** broadcast; the resolver can re-broadcast `raw_tx` (D-02).
- **Rationale**: a crash after broadcast still leaves the hash to look up; the same bytes can only land once.
- **Alternatives**: web3 `send_transaction` with an unlocked account (no hash before broadcast), signing at send
  time (no re-broadcast of the identical transaction).

## R-07 Nonce allocation: per (rail, wallet) counter row under lock (S2)

- **Decision**: `nonce_allocations(org_id, rail_id, from_address, next_nonce)` incremented with `UPDATE ... RETURNING`
  in the attempt's transaction; reconciled against `eth_getTransactionCount(pending)` on start.
- **Rationale**: the `one_tx_per_nonce` index already prevents reuse; the counter avoids gaps under concurrency.

## R-08 Policy evaluation: pure function over a typed input snapshot (S1)

- **Decision**: `evaluate(ruleset, snapshot) -> Decision` with no I/O; the service gathers the snapshot (counterparty
  facts, counters, mandate state, screening result) first and stores it in `decisions.inputs_snapshot`.
- **Rationale**: determinism (Hypothesis property test), replay without I/O, and fail-closed handling stays in one
  wrapper around snapshot collection.

## R-09 Agent calls: one `LLMClient` wrapper with recorded responses in tests (S5)

- **Decision**: `LLMClient.complete(prompt_version, system, data_blocks, schema) -> Parsed`; tests use a recorder that
  replays stored responses; `make eval-interpretation` calls the real model.
- **Rationale**: CI never calls the API; replay uses `agent_calls`; a second provider can be added (B6.dependence).
- **Open input**: the founder's confirmation of the AI provider's data terms (UK or EU processing, no training) is
  required before any client data is used (spec/05).

## R-10 Console: server-rendered Jinja with htmx, Playwright for screenshots (S3)

- **Decision**: one CSS file with the spec/07 tokens; htmx served from `/static`, not a CDN; Playwright screenshots in
  the e2e suite.

## R-11 OpenAPI: written contract first, then checked against the code (P1)

- **Decision**: [contracts/openapi.yaml](contracts/openapi.yaml) is the target; API-05 adds a test that compares the
  FastAPI-generated schema with it, so drift fails CI.

## R-12 Secrets and scanning: gitleaks plus a private denylist (implemented, M0)

- **Decision**: gitleaks in pre-commit and CI with a project rule for `sk_test_`/`sk_live_` keys; the denylist lives
  only in the `INDEPENDENCE_DENYLIST` secret and the check prints file and line, never the term.

## R-13 Tooling the environment needed

- Foundry is installed from GitHub releases; in this cloud environment solc must come from GitHub releases because
  the Solidity binaries host is not reachable. CI downloads solc normally.
- Docker runs Postgres 16 locally (`make db`); CI uses a service container.

## R-14 External data sources: shortlist for when a solution is needed (research, nothing chosen)

- **Status**: options to reach for when a story needs outside data, checked against the
  [public-apis list](https://github.com/public-apis/public-apis) on 26 Nov 2026. Nothing here is adopted; each pick
  needs its own story, and vendor contracts go through the `gate` skill. Limits are from search results, so confirm
  them before signing.
- **Phasing**: test networks first, main networks only after the founder approves and lifts invariant 14. Free chain
  tiers are fine on test networks; screening, KYB and calendar data come from production sources from the start.

| Need | First choice | Alternative | Notes |
| --- | --- | --- | --- |
| Wallet screening | OFAC SDN files ("Digital Currency Address - ETH/USDC" fields) | OpenSanctions (paid licence: compliance screening is commercial use) | Free government data; ingest the files, OFAC's search tool can't search addresses |
| Name screening | UK Sanctions List (sole UK list since 28 Jan 2026), EU Financial Sanctions Files, UN list | OpenSanctions or an established screening vendor | Store the list version on each decision |
| Chain RPC | Alchemy or Infura (free tiers on testnets) | A second node provider for read failover | Paid plans with a service level on mainnet; chain-ID guard stays |
| Explorer and indexer | Blockscout PRO API (free: 5 req/s, 100K credits/day, key required) | Etherscan V2 (Base and its testnets are paid only) | `explorer_url()`, deposit matching, reconciliation |
| Counterparty KYB | GLEIF API (free, no key, CC0) | UK Companies House (free key, 600 requests per 5 min) | `kyb_status`, read-only agent tools |
| Business days | gov.uk bank holidays JSON, ECB TARGET calendar | Nager.Date (no service level; Docker image needs a sponsor key) | Snapshot into config, read through `Clock` |
| FX for reports | ECB reference rates, self-hosted Frankfurter | None needed | Once per working day; never for execution |
| Stablecoin peg | Chainlink USDC/USD feed (mainnet) | CoinGecko paid plan (Demo has no commercial licence) | A policy input only if the founder decides |
| Transactional email | SendGrid or Mailjet | Any provider with EU hosting and a DPA | Open founder decision |

- **Avoid**: free or demo tiers in production; third-party IBAN/BIC checkers (validate IBANs locally, BICs from
  GLEIF); small unvetted sanctions APIs; FX feeds with no clear source; exchange APIs as price references.
- **Rules for any source in a decision path**: store what it returned as evidence (replay never calls out), and fail
  closed to `ESCALATE` with `SYSTEM_UNAVAILABLE` when it is down.
