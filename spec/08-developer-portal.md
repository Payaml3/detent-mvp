# 08 · Developer portal: dashboard, sandbox, docs, SDKs and website

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** how developers and buyers reach all three layers (dashboard, sandbox, docs, SDKs, website).

Source: `venture/05-developer-portal.md` (16 Nov 2026). The marketing site and docs are public. **Access is not self-serve.** A client gets access only through onboarding (`docs/product/client-journey.md`, B-04): once DekernAI has approved the client's KYB, the admin creates the organisation and sends the account owner a registration email. The owner then invites their own team.

## Surfaces (domains are placeholders until the name is final)

| Surface | Host | Built with |
|---|---|---|
| Marketing site | `<domain>` | Astro static site (`apps/site`) |
| Docs | `docs.<domain>` | Mintlify Starter from `docs/` |
| Dashboard and console | `dashboard.<domain>` | The `api` app (Jinja and htmx) |
| Sandbox API | `sandbox.api.<domain>` | The `api` app |
| Status | `status.<domain>` | A hosted status page fed by `/healthz` (WEB-07) |

## Dashboard (DSH)

- **KYB-gated access (DSH-01, DSH-02, DSH-03):**
  - There is no public sign-up route.
  - After KYB is approved, the admin creates the client organisation (name, KYB reference and date) and invites the account owner. A client organisation does not expire; the admin can suspend it.
  - An evaluation organisation (sandbox only, no KYB) can still be created, with an expiry of 60 days by default.
  - An invite link is single-use and lasts 7 days.
  - The account owner verifies their email and sets a password (argon2), then lands on the onboarding checklist: invite team, create sandbox keys, set up policy, integrate, request verification.
- **Team, roles and permissions (DSH-11):** the account owner (and admins) invite members by email, assign and change roles, and remove members. Roles: account owner, admin, developer, payments lead, compliance lead, reviewer, backup owner, auditor (spec/02). At least one account owner always remains; every change is audited.

  | Role | Can |
  |---|---|
  | Account owner, admin | Team and roles, keys, webhooks, settings, request verification and production |
  | Developer | Keys, request logs, webhooks, sandbox controls |
  | Payments lead, compliance lead | Policy (rule sets need two approvers, spec/04), mandates, mode moves, sign-offs |
  | Reviewer, backup owner | Exceptions queue in the console |
  | Auditor | Read-only: audit, replay, export |
- **Integration verification (DSH-12):** a checklist filled from sandbox evidence (every test value, a signed webhook acknowledged, an idempotent retry, an UNKNOWN resolved without a resend). The owner requests verification; a DekernAI admin verifies it or returns it with a note.
- **Production mode (DSH-13, after the MVP):** enabled by the account owner only once the integration is verified and rule set v1 is signed off; it starts in Shadow. In the prototype it is shown as not available, and no `sk_live_` key exists (invariant 14).
- **Keys:**
  - `sk_test_` keys only.
  - Create, roll (with an overlap window) and revoke.
  - Shown once; scopes; last used.
- **Request logs:** method, path, status, latency, idempotency key, payment ID and request ID. Bodies are redacted. Kept for 30 days.
- **Webhooks:** endpoints, event types, a secret shown once, "send test event", and a delivery log with resend.
- **Sandbox controls:**
  - reset test data (a new data generation; earlier data is hidden, never deleted: D-08)
  - force a scenario for the next payment
  - toggle real testnet mode (Should)
- **Usage:** calls, payments decided and agent investigations against daily quotas.
- **Console and policy:** the back-office screens scoped to the organisation, including the policy screens (rule sets, counterparties, mandates). Demo-only controls are hidden.
- **Admin (DekernAI only):** organisations (with the KYB reference), owner invites, evaluation expiry and client suspension, integration verification, and the access-requests inbox (DSH-10).

## Sandbox (SBX)

- Simulated rails by default (`simchain`, `banksim-*`). Real Base Sepolia or Ethereum Sepolia is opt-in, from a shared, rate-limited faucet wallet with a daily outflow cap.
- Test values: see spec/06.
- **Quotas (defaults, Estimate):**
  - 60 requests per minute per key
  - 500 payments a day per organisation
  - 50 agent investigations a day per organisation
- Expired organisations get 403 `organisation_expired`, and their dashboard becomes read-only.

## Docs (DOC)

| Section | Pages |
|---|---|
| Get started | Overview · Quickstart (first payment intent in 5 minutes) · Sandbox and test values · Authentication |
| Concepts | Payment intents and the payment ID · Decisions · Payment states · Policies and rule versions · Mandates for AI agents · Exceptions and deadlines · Deposits and reconciliation · Routing and failover · Audit and replay |
| Guides | Let an AI agent pay a supplier invoice ($18,500 USDC) · Credit deposits safely · Handle UNKNOWN payments · Approve escalations by API · Use the kill switch · Move from shadow to auto mode |
| API reference | Generated from `openapi.yaml`, with "try it" against the sandbox only |
| Webhooks | Event types · Signature verification (8 languages) · Retries and ordering |
| Errors and limits | Error codes · Idempotency · Rate limits · Versioning |
| SDKs and tools | Python · TypeScript · Postman · OpenAPI download |
| Changelog | Dated entries |

**Samples:** cURL, Python, TypeScript, Go, Java, C#, PHP and Ruby.

- Snippets live in `docs/snippets/<lang>/` as runnable files.
- CI starts the API and sandbox, then runs each snippet in a language container and checks the output (DOC-04).
- Reference request samples are generated from the OpenAPI file.

## SDKs (SDK)

Python (`sdks/python`) and TypeScript (`sdks/typescript`), generated from `openapi.yaml` and then polished:

- typed models
- automatic `Idempotency-Key` on creates (UUIDv4 unless provided)
- retries only on 429, 503 and connection errors that happen before a response, reusing the same idempotency key
- `verify_webhook(secret, header, body, tolerance=300)`

## Website (WEB)

**Home page sections, in order** (structure and reasons: `docs/design/landing-page-ux.md`, approved in #59):

1. **Hero:** "Every deposit and payout, decided by your rules." Category line: "Agentic payment controls: one layer that decides, orchestrates and operates every deposit and payout, under your rules." The primary CTA is "Book a demo"; the secondary is "Talk to us" (B-04). The example payment plays through the three layers beside the agent and rules art. A small line: sits beside your rails, never holds funds or keys.
2. **The problem:** "On rails you can't reverse, every mistake is permanent." Manual review queues, deposits credited wrong, retries that become double payments, decisions nobody can replay.
3. **Sift. Settle. Prove.:** the three layers as one payment's life, with the same payment ID: your rules decide in each, agents do the groundwork. "Agents prepare. Your rules decide." is said here once.
3a. **Change a rule, watch the decision:** the page's one live control. An auto-limit slider and three toggles (first payment, changed wallet, screening hit) re-decide the fictional $18,500 payout in the browser, using the spec/04 checks and reason codes. Labelled a simulation; without script the default decision shows.
4. **Built for irreversible payments:** "A failure can retry. A rejection can't. No retry ever becomes a second payment.", with the payment states shown and the kill switch.
5. **Measured results:** shown only once `results.json` exists, each figure labelled "test-network evaluation, [date]". Left out of the page until then.
6. **Roles:** tabs for Payments, Compliance and Engineering. Engineering holds the 8-language code tab creating a payment intent (pre-launch label) and the sandbox access link; Compliance links to the Security page, which holds non-custodial, audit and replay, kill switch, EU hosting and the roadmap list.
7. **Onboarding:** the seven phases of the client journey (docs/product/client-journey.md, B-04): discovery, contract and due diligence, sandbox integration, policy setup, shadow on live traffic, go-live, scale. Each shows both owners and its exit check; phases 4 to 6 are signed by the client, and the Pilot covers phases 3 to 6 on one rail. Paid plans (Pilot, Growth, Scale) are "Talk to us", with no prices. There is no free shadow report: shadow is a phase after the contract.
8. **Use cases and FAQ:** payout platforms, crypto service providers, brokers and prop firms, marketplaces; then 8 questions (money and custody, does the AI approve, changing rails, who approves, timeouts, rails, how onboarding works, cost).
9. **Close:** "Held until it's right. Sent exactly once." with both CTAs.
10. **Footer:** docs, status, privacy, terms, contact.

**Sub-pages:** Product, Security, and Onboarding (at `/design-partners/`: the seven phases in full, data handling and plans).

**Honesty checklist (WEB-01 acceptance):**
- Uses "agentic payment controls" (or "payment controls") and never "payments company" or "payment provider".
- No logos, testimonials, customer counts or volume figures.
- No certification badges and no "licensed" or "regulated" claims.
- Results are dated and labelled.
- The dashboard and API show a "Sandbox, pre-launch" label.
- Prior-company figures appear only as the founder's experience on an About section.

**SEO (WEB-08):**
- Titles pair the name with the category ("DekernAI agentic payment controls" or "DekernAI payment controls").
- Topic pages and docs target the searches buyers make: "stablecoin payout controls", "payout exception handling", "payment reconciliation across rails" and "APP fraud reimbursement".
- Add sitemap.xml, Open Graph images, and schema.org `Organization` and `SoftwareApplication` markup.

## As built (P2 group 1)

- **Who is a DekernAI admin:** an admin of the operator organisation (`org_detent`). Only the command line creates
  one (`detent staff add --email --name`; the password is read from the terminal). They sign in on the same page as
  everyone else and land on `/admin/`.
- **Organisations (DSH-01, DSH-03):** `/admin/organisations/new` creates a client organisation (KYB reference and
  approval date required, no expiry; the database refuses anything else) or an evaluation organisation (expiry,
  60 days by default). A new organisation starts with the fictional counterparties, the simulated rails and rule
  set version 1 (G-18), in shadow mode. Admins extend an evaluation and suspend or reinstate an organisation with a
  reason; each is audited in that organisation. A suspended organisation gets 403 `organisation_suspended` (an
  expired one keeps `organisation_expired`) and a read-only dashboard.
- **Invites and sign-up (DSH-01, DSH-02, DSH-11):** an invite stores only a SHA-256 of a 256-bit token. Opening the
  link confirms the email; the person sets a password (argon2id, at least 12 characters, not containing the email).
  An invite to the same address replaces the open one. Until the founder chooses an email provider, invites go to
  the outbox and the admin sees the owner's link once on the organisation page.
- **Sign-in:** one email signs in to one organisation. Attempts are limited per email (10 a minute) and per client
  address (30). A new session on every sign-in; every page reloads the member, so removal or a role change takes
  effect at once. Every form carries a per-session CSRF token; redirects after sign-in stay on site.
- **Team (DSH-11):** owners and admins invite, change roles and remove members; only an account owner grants or
  takes away the account owner role. The last account owner can't be demoted or removed (database trigger, plus a
  lock on the organisation row against two owners demoting each other). Removing a member revokes their API keys
  at once. Members are never deleted.
- **Not yet:** the transactional email provider (DSH-02 criterion 2 stays open), and the sandbox and verification
  pages (later P2 groups; the checklist links to them). Keys, logs, webhooks and usage: P2 group 2 below.

## As built (P2 group 2)

- **Keys (DSH-04):** `/dashboard/keys`, for account owners, admins and developers. A key has a name, scopes
  (`read`, `intents:create`, `exceptions:approve`, `admin`) and an owner (the member who made it; the member's role
  still applies to every call). The secret is shown once, on a page that is never cached; only an HMAC of it is kept.
  Rolling makes a new key with the same owner, scopes and name; the old one works for an overlap (24 hours by
  default, `KEY_ROLL_OVERLAP_HOURS`, 0 to 168 chosen per roll), and a rolled key can't be rolled again. Revoking is
  immediate. Last use is written by the request log, at most once a minute per key. Each change is audited
  (`api_key.created`, `api_key.rolled`, `api_key.revoked`). Production keys are labelled as not available.
- **Request logs (DSH-05):** `/dashboard/logs` filters by status (a code or a class such as `4xx`), path, idempotency
  key and payment ID over the 30-day window; the detail page shows the metadata and marks both bodies as redacted,
  because they are never stored.
- **Webhooks (DSH-06):** `/dashboard/webhooks` creates an endpoint (signing secret shown once), lists endpoints and
  opens each one's delivery log with "send test event", resend per event and disable. The same services as the API;
  audit events name the member and carry `"via": "dashboard"`.
- **Metering (LED-08):** `usage_daily` counts API calls, payments decided (payment intents and dry-run decisions;
  an idempotent replay is not counted) and agent investigations per organisation and UTC day, in the same
  transaction as the work. A month is the sum of its days (`detent.sandbox.usage.monthly`).
- **Quotas (SBX-02):** each new client or evaluation organisation gets 500 payments decided and 50 agent
  investigations a day (`SANDBOX_DAILY_PAYMENTS`, `SANDBOX_DAILY_INVESTIGATIONS`); demo and test organisations have
  none. The check and the count are one statement, so concurrent requests never pass the cap. Over the payment
  quota the API answers 429 with type `quota` and code `quota_exceeded`, `Retry-After` runs to the next UTC day, and
  nothing is created. Over the investigation quota the case still opens and the agent records `QUOTA_EXCEEDED`, so a
  person works from the raw facts. API calls have no daily quota; the per-key rate limit applies.
- **Usage (DSH-08):** `/dashboard/usage`, for every member: today against the quotas, and the month so far.
- **Not yet:** the shared testnet wallet's daily outflow cap arrives with real testnet mode (SBX-03, P2 group 3).

## As built (P2 group 3a)

- **Simulated chain (RAL-11):** a client or evaluation organisation starts with `sandbox_rails = simulated`. Its
  `base-sepolia` and `eth-sepolia` rails keep their IDs (so routing, failover and the API are unchanged) but run on
  an in-database simulated chain (`detent/rails/simchain.py`, table `simchain_transfers`, append-only). It follows
  the EVM contract: a nonce and a stored "signed" transaction (a deterministic hash) before broadcast, the same
  bytes broadcast twice are one transaction, and an UNKNOWN attempt is resolved only from what the chain recorded.
  Payouts settle at once and use no faucet wallet. Simulated attempts show `simulated: true` and no explorer link.
  The deposit watcher records simulated payouts as rail records, so reconciliation matches them. The simulated
  chain has no deposits; inbound transfers need a real test network. Demo and test organisations keep `testnet`.
- **Test values (SBX-01):** on the simulated chain, an amount of exactly `.13` (10.13, not 10.1301) times out after
  forwarding: UNKNOWN, then CONFIRMED a few seconds later, never resent; exactly `.42` reverts on a payment's first
  attempt (TECHNICAL_FINAL), then fails over to the other network under the same payment ID if the intent allows a
  network switch, else the payment fails. Flagged address, allowlist and mandate values come from the policy, as on
  every rail. The docs page arrives with P3 (SBX-01 criterion 1 stays open).
- **Real test networks (SBX-03):** the sandbox page moves an organisation to `testnet` when this instance has an RPC
  URL, a faucet wallet and a token for at least one network, and never while a payout on those networks is in
  flight. Payouts then come from the shared faucet wallet and carry explorer links. Daily caps on that wallet
  (SBX-02): `FAUCET_DAILY_CAP` (500 USDC) for all organisations together per network and `FAUCET_ORG_DAILY_CAP`
  (50 USDC) for each, checked inside the send lock under one advisory lock; a payout over a cap is held
  (`SHARED_WALLET_DAILY_CAP`). Known limit: after a move to `testnet`, earlier simulated payouts have no real-chain
  record, so a later reconciliation run can list them as missing on the rail.
- **Sandbox controls (DSH-07):** `/dashboard/sandbox`, for account owners, admins and developers: run a scenario
  (timeout to UNKNOWN, rail failure with failover, flagged address), each one sandbox payout to a fictional payee
  through the same decision path as the API; switch rails; recent payouts with their attempts and explorer links.
  Audited (`sandbox.scenario_run`, `sandbox.rails_mode_changed`, `sandbox.reset`), with the reset below.

## As built (P2 group 3b)

- **Sandbox reset (SBX-04, C-04, D-08):** "Reset test data" on `/dashboard/sandbox` (sandbox control, typed
  confirmation) raises `organisations.data_generation`. A trigger stamps every new root row with the organisation's
  generation: payment and deposit intents, exception cases, journal entries, request logs, webhook events,
  reconciliation runs and breaks (migration 0014). The API and dashboard read only the current generation, so
  earlier rows answer 404 or drop out of lists, and nothing is deleted. Children (attempts, decisions, postings, case
  events, deliveries) follow their root. Keys, webhook endpoints, members, rules and settings stay. Audited
  (`sandbox.reset`, from and to generation).
- **Refused** while a payout could still reach a rail (READY, SUBMITTED, UNKNOWN, FAILED, or an attempt CREATED,
  SUBMITTED or UNKNOWN), so a hidden payment never sends. An ESCALATED or HELD payment waits for an approval that no
  screen of the new generation can give, so it stays held (invariant 7). The demo organisation has its own reset
  (CON-09, G-26) and is refused here.
- **Not reset, on purpose:** decision history (velocity counters, first-payment and resubmission-after-block
  checks), so a reset can't launder a block or a limit; idempotency keys, so a retry across a reset returns its
  first response and never pays twice; daily quotas and the shared-wallet caps; account balances, which are what
  the rails moved. Webhook deliveries already queued for earlier events still run.
- **For DSH-09:** the console's own list queries (overview, queues) don't filter on the generation yet; the shared
  payment and case views do. The per-organisation console must add the filter before sandbox orgs reach it.

## Needed from the founder before M8 to M11

- the name and domain
- a transactional email provider
- an always-on hosting tier for the sandbox
- a Mintlify account
- the booking page link
- the sales inbox address
- legal text review (privacy, sandbox terms, cookies)
