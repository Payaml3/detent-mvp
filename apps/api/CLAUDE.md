# apps/api: conventions

Loaded when Claude works under `apps/api/`. Shared rules are in the root `AGENTS.md`.

## Repository layout (target)

```
apps/api/src/detent/
  domain/        # pure types, money, ids, state machine table (no I/O)
  intents/  policy/  mandates/  agents/  execution/  rails/  routing/
  exceptions/  ledger/  reconciliation/  audit/  webhooks/  sandbox/
  api/           # FastAPI routers for /v1
  console/       # Jinja + htmx back office
  dashboard/     # developer dashboard + admin
  worker/        # job loop and scheduled jobs
  db/            # engine + org-scope guard, org-scoped repositories, Core tables
  clock.py  settings.py  logging.py  chainguard.py  devchain.py  cli.py
apps/api/tests/  # unit, integration, property, concurrency
apps/banksim/    # simulated instant bank rail (separate FastAPI app)
apps/faultproxy/ # fault-injection proxy
apps/site/       # Astro marketing site
eval/            # scenarios (data) + runner + report templates
docs/            # Mintlify docs + snippets/<lang>/
sdks/python  sdks/typescript
fixtures/  spec/  backlog/  tools/
```

Migrations are plain SQL files in `apps/api/migrations/versions/` run by Alembic; they are forward-only. The test suite drops and re-migrates the `detent_test` database, and each test creates its own organisation, so no cleanup is needed.
