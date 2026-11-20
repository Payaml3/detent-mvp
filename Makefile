# Detent MVP. Test networks and simulated rails only. See README for setup.
SHELL := /bin/bash
UV ?= uv
export PATH := $(HOME)/.foundry/bin:$(PATH)

.PHONY: setup db db-reset migrate seed chain chain-build dev test test-fast lint typecheck eval backlog spec roadmap roadmap-page site site-dev site-test denylist governance agents secrets check

setup:            ## install dependencies and pre-commit hooks
	$(UV) sync --all-packages
	$(UV) run pre-commit install

db:               ## start local Postgres 16 and run migrations
	docker compose up -d --wait postgres
	$(MAKE) migrate

migrate:
	$(UV) run alembic -c apps/api/alembic.ini upgrade head

db-reset:         ## drop and recreate the local schema (local only)
	docker compose exec -T postgres psql -U detent -d detent -c "DROP SCHEMA IF EXISTS detent CASCADE"
	$(MAKE) migrate seed

seed:             ## seed the fictional demo organisation and users
	$(UV) run detent seed

chain-build:
	cd chain && forge build

chain: chain-build ## start anvil and deploy MockUSDC (writes chain/local.json); Ctrl-C to stop
	$(UV) run python -m detent.devchain 8545

dev:              ## api + worker + banksim + faultproxy (Ctrl-C stops all)
	trap 'kill 0' EXIT; \
	$(UV) run detent api --port 8000 & \
	$(UV) run detent worker & \
	$(UV) run uvicorn banksim.app:create_app --factory --port 8100 & \
	$(UV) run uvicorn faultproxy.app:app --port 8200 & \
	wait

test:             ## unit + property + integration + concurrency (needs `make db`; chain tests need foundry)
	$(UV) run pytest

test-fast:        ## unit and property tests only, no database
	$(UV) run pytest apps/api/tests/unit apps/api/tests/property

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy

eval:             ## evaluation suites and the release gate (S8); needs make db and forge build
	$(UV) run detent eval run --suite all

backlog:          ## regenerate backlog documents and check coverage
	$(UV) run python tools/build_backlog.py

site-dev:         ## marketing site dev server (http://localhost:4321)
	cd apps/site && npm install && npm run dev

site:             ## build the marketing site into apps/site/dist (reports placeholders)
	cd apps/site && npm ci && npm run build

site-test:        ## site logic tests, build, then honesty/structure/SEO checks over the build
	cd apps/site && npm ci && npm test

spec:             ## regenerate specs/001-detent-mvp inventory, traceability and tasks; check coverage
	$(UV) run python tools/build_spec.py

agents:           ## rebuild .claude/agents (Claude Code roles) from .codex/agents
	$(UV) run python tools/sync_claude_agents.py

roadmap:          ## regenerate founder/roadmap.md (and roadmap.json) from slices, stories, decisions and founder/status.md
	$(UV) run python tools/build_roadmap_page.py
	$(UV) run python tools/build_roadmap.py

roadmap-page:     ## founder/roadmap.md plus the phone page at build/roadmap.html (publish it to the roadmap Artifact)
	$(UV) run python tools/build_roadmap_page.py --html build/roadmap.html

denylist:         ## OPS-02 independence check; needs DENYLIST in the environment
	$(UV) run python tools/check_denylist.py .

governance:       ## operating-protocol checks (registers, HANDOFF on slice done) and the hook/tool tests
	$(UV) run python tools/check_governance.py
	$(UV) run pytest tools/tests -q -p no:cacheprovider

check: lint typecheck test
