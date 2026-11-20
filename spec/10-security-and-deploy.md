# 10 · Security, settings and deploy

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** security and hosting for all three layers.

## Settings (`.env.example`)

```
APP_ENV=dev                         # dev | test | demo | sandbox
BRAND_NAME=Detent                   # working name; change in one place
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
USDC_ADDRESS_BASE_SEPOLIA=0x036CbD53842c5426634e7929541eC2318f3dCF7e
USDC_ADDRESS_ETH_SEPOLIA=0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238
BANKSIM_URL=http://localhost:8100
FAULTPROXY_URL=http://localhost:8200
EMAIL_PROVIDER=outbox                # outbox | <provider>
SALES_INBOX=...
```

The two testnet USDC contract addresses were checked against Circle's "USDC on Test Networks" page on 17 Nov 2026 (https://developers.circle.com/docs/usdc-on-testnet). Re-check them if a transfer fails. Startup fails if a configured chain ID is not in `ALLOWED_CHAIN_IDS`.

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

**Roadmap, not built:** hardware-backed vault, IP allowlists, pen test, SOC 2. Label these as roadmap on the website.

## Hosting

| Stage | Option | Notes |
|---|---|---|
| Prototype demo (M7) | Render free web service plus worker in Frankfurt; Neon free Postgres in an EU region | A free web service sleeps after about 15 idle minutes, so open it 2 minutes before a demo. Don't use Render's free Postgres, which expires |
| Public sandbox (M8 onwards) | An always-on paid instance for the API, dashboard and worker in an EU region | Free tiers that sleep give developers a poor first impression. Check current prices before choosing |
| Site and docs | A static host for Astro; Mintlify for docs | |

Recheck free-tier limits and prices when you deploy; they change.

## Runbooks (write as the features land)

- **Fund test wallets:** `detent demo check`, then Circle's faucet (20 test USDC per address per chain every 2 hours, as of Nov 2026; check), plus a gas faucet for each chain.
- **Kill switch:** engage from the Overview or `POST /v1/kill_switch`; release by the payments lead only.
- **Sev 1:** triggered by the invariant monitor. Kill switch on, incident opened, notification within 1 hour (outbox), replay the affected payments, root cause within 5 days.
- **Restore (OPS-03):** use the provider's point-in-time restore to a new branch, run `detent audit verify` and switch the URL. Target under 1 hour.
