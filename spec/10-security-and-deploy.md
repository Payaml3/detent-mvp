# 10 · Security, settings and deploy

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** security and hosting for all three layers.

## Settings (`.env.example`)

```
APP_ENV=dev                         # dev | test | demo | sandbox
BRAND_NAME=DekernAI                 # brand name (B-01); change in one place
DATABASE_URL=postgresql+psycopg://...
DEMO_PASSWORD=change-me
SESSION_SECRET=...
API_KEY_PEPPER=...
CREDENTIALS_ENCRYPTION_KEY=...       # Fernet key for rail credentials (RAL-09)
MANDATE_SIGNING_KEY_DEMO=...         # HMAC key for demo mandates
WEBHOOK_SECRET_PEPPER=...            # unused for signing secrets: those are encrypted with CREDENTIALS_ENCRYPTION_KEY (D-12)
ANTHROPIC_API_KEY=...
MODEL_AGENT=claude-sonnet-5-5
MODEL_LIGHT=claude-haiku-5-5
MODEL_EVAL_JUDGE=claude-opus-5-5
AI_DAILY_TOKEN_BUDGET=2000000
BASE_SEPOLIA_RPC_URL=...             # via faultproxy in test/sandbox
ETH_SEPOLIA_RPC_URL=...
ALLOWED_CHAIN_IDS=84532,11155111,31337
TEST_WALLET_PRIVATE_KEY_BASE=...     # testnet only, never mainnet funds
TEST_WALLET_PRIVATE_KEY_ETH=...
DEMO_PAYER_PRIVATE_KEY_BASE=...      # S9: the fictional payer that sends the demo batch's deposits (testnet only)
DEMO_PAYER_PRIVATE_KEY_ETH=...
HOSTING_REGION=...                   # FND-07: stated in the console footer and /healthz
DATABASE_REGION=...
USDC_ADDRESS_BASE_SEPOLIA=0x036CbD53842c5426634e7929541eC2318f3dCF7e
USDC_ADDRESS_ETH_SEPOLIA=0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238
BANKSIM_URL=http://localhost:8100
FAULTPROXY_URL=http://localhost:8200
EMAIL_PROVIDER=outbox                # outbox | <provider>
SALES_INBOX=...
```

The two testnet USDC contract addresses were checked against Circle's "USDC on Test Networks" page on 17 Nov 2026 (https://developers.circle.com/docs/usdc-on-testnet). Re-check them if a transfer fails. The live demo instead sets both to its own test token (D-33): `detent demo token deploy --network <n>` deploys `chain/src/MockUSDC.sol` ("DekernAI Demo USD (test stand-in, not USDC)", symbol `tUSDC`) from the sending wallet and prints the address to set. The contract reverts on any chain but 31337, 84532 and 11155111, and only its deployer can mint. Startup fails if a configured chain ID is not in `ALLOWED_CHAIN_IDS`.

## Security controls in the MVP

| Control | Where |
|---|---|
| TLS only; HSTS on public hosts | Hosting |
| API keys hashed (SHA-256 with a pepper); passwords argon2; secrets shown once | API-01, DSH-02, WHK-01 |
| Rail credentials encrypted at rest (Fernet), never displayed again | RAL-09 |
| Least-privilege scopes; agent key limited to `intents:create` with a mandate | API-01, AGT-03 |
| Organisation isolation on every query; cross-organisation tests | FND-03, EVL-02 |
| Append-only, hash-chained audit log; append-only ledger | AUD-01, LED-01 |
| No secrets or personal data in logs | FND-08 |
| Rate limits and quotas | API-04, SBX-02 |
| Secret scanning pre-commit and in CI; private denylist check | FND-01, OPS-02 |
| Test networks only; live keys rejected | FND-02 |
| Sev 1 invariant monitor engages the kill switch | EXE-10, OPS-01 |
| Shadow imports hash names and account identifiers with a per-import salt | SHD-04 |
| Rail circuit breaker takes a failing rail out of routing | RAL-08 |
| Evidence export with the hash-chain check | AUD-03 |

**Roadmap, not built:** hardware-backed vault, IP allowlists, pen test, SOC 2. Label these as roadmap on the website.
`docs/security.md` (OPS-04) is generated from this table by `tools/build_security.py`; edit the table, then run it.

## Hosting

| Stage | Option | Notes |
|---|---|---|
| Prototype demo (M7) | Render free web service plus worker in Frankfurt; Neon free Postgres in an EU region | A free web service sleeps after about 15 idle minutes, so open it 2 minutes before a demo. Don't use Render's free Postgres, which expires |
| Public sandbox (M8 onwards) | An always-on paid instance for the API, dashboard and worker in an EU region | Free tiers that sleep give developers a poor first impression. Check current prices before choosing |
| Site and docs | A static host for Astro; Mintlify for docs | |

Recheck free-tier limits and prices when you deploy; they change.

### Chosen host (27 Nov 2026): Hetzner + Neon

The founder chose one Hetzner Cloud server (CAX11, Arm64, Helsinki, Finland (EU)) over Render, to pay less, with everything on it: the
API, console, dashboard and admin (one `app` container), the worker, the bank simulator and fault proxy
(private, no domain) and the static website. Coolify deploys `infra/hetzner/docker-compose.yml` from `main`
and ends TLS. Neon Postgres stays in AWS Europe (Frankfurt) `eu-central-1`. `HOSTING_REGION` says
"Hetzner Cloud, Helsinki, Finland (EU)". The step-by-step setup is `infra/hetzner/README.md`. Empty environment
variables count as unset (`env_ignore_empty`), so optional secrets can stay blank until they exist. The Render
notes below describe `render.yaml`, which was never deployed and is kept only as a fallback.

### As built (S9, FND-07)

- **Blueprint:** `render.yaml` at the repository root. Four services, all in Render's **Frankfurt (EU Central)**
  region: the web service (API and console, `/healthz` as its health check), the worker, and two private
  services, the bank simulator and the fault proxy. The fault proxy runs with `FAULTPROXY_DEMO_MODE=1`, so only
  the scenario runner can arm a fault, and it is private, so it is not reachable from the internet.
- **Database:** Neon Postgres in an EU region (AWS Europe (Frankfurt) `eu-central-1` is the intended one), set
  as `DATABASE_URL`. Migrations and the idempotent seed run in the web service's build.
- **Regions are stated, not assumed:** `HOSTING_REGION` and `DATABASE_REGION` appear in the console footer
  and in `/healthz` (`regions`). Defaults say "local machine (not deployed)".
- **`/healthz`** reports `database` and each demo chain RPC (`base-sepolia`, `eth-sepolia`) as `ok`,
  `not_configured`, `unreachable` or `wrong_chain` (the endpoint reports another chain ID). In `APP_ENV=demo`
  both chains must be `ok`; elsewhere an unconfigured chain does not fail the check.
- **Proposed (founder):** the plans. Render's free plan covers the web service only; the worker and the two
  private services need a paid instance type. Not deployed yet: deploying needs the founder's Render and Neon
  accounts, the secrets, and funded test wallets (`detent demo check`).

## Runbooks (write as the features land)

- **Fund test wallets:** `detent demo check` (DEM-04) prints each demo wallet's test USDC and gas against what one
  full demo run needs (from the fixtures), and what to top up. `detent demo token fund --network <n> [--runs 3]`
  mints the demo token (D-33) to the sending wallet and the payer up to that many runs; gas still comes from a faucet for each chain.
- **Kill switch:** engage from the Overview or `POST /v1/kill_switch`; release by the payments lead only.
- **Sev 1:** triggered by the invariant monitor. Kill switch on, incident opened, notification within 1 hour (outbox), replay the affected payments, root cause within 5 days.
- **Incidents (OPS-01, as built):** severities and notification windows: Sev 1 (an invariant broke or money may be at
  risk; 1 hour), Sev 2 (a control misbehaved without loss, such as a replay mismatch; 4 hours), Sev 3 (degraded
  service; 24 hours), Sev 4 (near miss or cosmetic; 5 days). The timeline is `incident_events` (append-only), and each
  step writes an audit event. Root cause is required before a Sev 1 or 2 is resolved; replays are linked from the
  incident page.
- **Invariant monitor (EXE-10, as built):** `detent/incidents/monitor.py`, run by the worker every
  `INVARIANT_MONITOR_SECONDS` (60) and by the `invariants.check` job queued when a payment becomes CONFIRMED. Findings:
  `duplicate_payment` (two CONFIRMED attempts or two confirmed transaction hashes for one payment ID),
  `unauthorised_execution` (a CONFIRMED attempt without an EXECUTE decision) and `double_credit` (two credits for one
  inbound transfer). A hit opens one Sev 1 per finding, engages the kill switch unless
  `INVARIANT_MONITOR_KILL_SWITCH=false`, posts `incident_sev1` to the outbox (logging the notification) and shows the
  red banner.
- **Restore (OPS-03, as built):** target under 1 hour, no decision lost.
  1. Engage the kill switch for every organisation (Overview), so nothing is sent during the restore.
  2. In Neon, restore the database to a new branch at the chosen point in time (point-in-time restore).
  3. Prove the copy: `detent ops restore-drill --source-url <old DATABASE_URL> --target-url <new branch URL>` is the
     drill form (dump and restore into an empty database named `*restore*` or `*drill*`); for a provider restore,
     run `detent audit verify --org <id>` for each organisation on the new branch. Every hash chain must verify.
  4. Point `DATABASE_URL` at the new branch, restart the web service and the worker, check `/healthz`.
  5. The payments lead releases the kill switch after the open UNKNOWN attempts are resolved.
- **Restore drill log:** `detent ops restore-drill` (`detent/ops/restore_drill.py`) times the backup, the restore and
  the checks, and compares each organisation's chain head and the decision, audit, ledger, payment and attempt row
  counts with the source. It refuses a target that is the source or whose name lacks `restore` or `drill`.
  - 2026-11-28, local (Postgres 16, `pg_dump`/`pg_restore`, seeded demo database): passed in 0.5 s; 1 organisation,
    1 hash chain verified, heads and counts matched. CI repeats it on every run (`test_restore_drill.py`).
  - Open: repeat the drill with Neon's point-in-time restore once the hosted database exists (founder item).
