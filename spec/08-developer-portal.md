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
- **AI team (CON-11):** a navigation link to the console's AI team page: the organisation's three DekernAI agents with their limits, their work and the people who approved or rejected it. The agents propose; the client's rules and people decide.
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
5. **Measured results:** shown only once `results.json` exists, each figure labelled "evaluation on synthetic data, [date]. Not production results.". Left out of the page until then.
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
  An invite to the same address replaces the open one. Invites go to the outbox and the admin sees the owner's link
  once on the organisation page; with `EMAIL_PROVIDER=zeptomail` (D-43) the worker also emails them.
- **Sign-in:** one email signs in to one organisation. Attempts are limited per email (10 a minute) and per client
  address (30). A new session on every sign-in; every page reloads the member, so removal or a role change takes
  effect at once. Every form carries a per-session CSRF token; redirects after sign-in stay on site.
- **Team (DSH-11):** owners and admins invite, change roles and remove members; only an account owner grants or
  takes away the account owner role. The last account owner can't be demoted or removed (database trigger, plus a
  lock on the organisation row against two owners demoting each other). Removing a member revokes their API keys
  at once. Members are never deleted.
- **Email (DSH-02 criterion 2, D-43):** `dashboard/email.send_email` writes every dashboard email to the outbox in
  the caller's transaction. With `EMAIL_PROVIDER=zeptomail` the row's channel is `email` and an `email.send` job
  (`dashboard/email_delivery.py`) posts it to ZeptoMail's EU API from `EMAIL_FROM`: 2xx stores `sent_at` and the
  provider's request ID; 429, 5xx and network errors retry with the worker's backoff; other 4xx are stored in
  `last_error` and not retried. Console notices to counterparties stay `email_mock` whatever the provider.
- **Not yet (at the time):** the sandbox and verification pages (later P2 groups; the checklist links to them). Keys, logs, webhooks and usage: P2 group 2 below.

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

## As built (P2 group 4a)

- **Access requests (DSH-10):** the website's form posts to `POST /access-requests` (public: no session or CSRF
  token, as the site is another origin). Name, work email and company are required; role and use case are kept,
  and the site's own field names (`title`, `message`) and extra questions (country, platform, rails) are accepted.
  A lead is stored in the operator organisation (`leads`, migration 0015) and emailed to `SALES_INBOX` through the
  outbox, like every dashboard email until the founder chooses a provider; with no inbox set it is only listed.
  The same work email within a day is stored once, and a form with the hidden `website` field filled in is
  treated as a bot. The text is untrusted: shown escaped, never sent to a model. Admins list requests at
  `/admin/access-requests`, filter by status (new, contacted, approved, declined) and move them along with a note.
  Audited (`lead.received`, `lead.status_changed`). The site keeps its placeholder action until the dashboard is
  deployed (WEB-06, P4).
- **Integration verification (DSH-12):** `/dashboard/verification` fills eight checks from the organisation's own
  records: `.13` timed out and was confirmed, `.42` reverted on its first rail, a screening block, an allowlist
  escalation, a mandate-limit block, a 2xx-acknowledged delivery of a real (not test) event, an idempotent retry of
  `POST /v1/payment_intents`, and an UNKNOWN payout confirmed with a single attempt. Evidence counts across data
  generations. The account owner or an admin requests verification once all pass; the checklist is stored with the
  request (`verification_requests`, one open at a time, a decided request is final by trigger). DekernAI admins
  verify or return it with a note at `/admin/verifications`. Audited in the organisation's log
  (`verification.requested`, `verification.verified`, `verification.returned`). Production mode stays unavailable
  (DSH-13).

## As built (P2 group 4b)

- **Console per organisation (DSH-09):** a member signed in to the dashboard opens `/console/` (linked from the
  dashboard nav) and uses the same screens as themselves, in their own organisation: overview, policy,
  mandates, counterparties, exceptions, payments, rails, reconciliation, outbox and settings. There is no demo
  password and no act-as; the demo-only screens and controls (the clock, the invoice agent, the scenario runner,
  act-as) are hidden and answer 404. Reads show only the organisation's current data generation (SBX-04),
  including the overview numbers, and an earlier generation's case can't be approved. Permissions come from the
  member's role, as in the demo console. Writes are refused while the organisation is read-only (DSH-03) and
  unless the request's Origin or Referer is this site (the console's forms carry no CSRF token). Every write is
  audited with the member's ID and role. `/dashboard/policy` redirects to `/console/policy`.
- **Reset and the kill switch:** a sandbox reset (SBX-04) also waits for payments the kill switch holds, because
  releasing the switch would send them with no approval.

## As built (P3 group 1)

- **Docs site (DOC-01):** Mintlify from `docs/` (`docs/docs.json`, theme `mint`, the brand's orange and logos). The
  API reference tab is generated from `docs/api/openapi.json`, and the error-code page is the generated
  `docs/api/errors.md` (now with Mintlify front matter). `docs/` also holds internal documents, so
  `docs/.mintignore` excludes `brand/`, `design/`, `product/` and `engineering-standards.md`, and
  `tools/build_docs.py --check` (CI, `make docs-check`) fails if any page is neither in the navigation nor
  excluded, if the navigation names a missing page, or if a page has text MDX would read as code. The site's
  domain and the website's access link are placeholders (`sandbox.api.<domain>`, `SITE_DOMAIN`) until the founder
  connects Mintlify and sets the domains.
- **Pages:** Get started (overview, quickstart, sandbox and test values, authentication), the nine concept pages
  (DOC-02), webhooks (event types, signature verification, retries and ordering), errors and limits
  (idempotency, rate limits, versioning), Postman and OpenAPI, and the changelog (DOC-06, one entry for
  `2026-12-01`, linked from the reference's description). Guides (DOC-03) and the 8-language samples (DOC-04)
  come in later P3 groups; the signature page has a Python sample until then.
- **Docs that are tested:** the quickstart's request body is read from the page and sent to the API, in shadow
  and in auto mode, and so is its table of other outcomes; the sandbox page is checked against the simulated
  chain's test values (SBX-01 criterion 1); the signature sample is run against the API's signing code.
- **Postman (SDK-03):** `docs/api/postman.json`, generated from the OpenAPI file by `make openapi`, with
  `baseUrl`, `apiKey` and `apiVersion` variables and a fresh `Idempotency-Key` on every create. CI fails if it is
  stale.
- **As found:** the default sandbox rate limit is 120 requests a minute per key (`API_RATE_LIMIT_PER_MINUTE`), not
  the 60 estimated above; the docs say 120. In shadow mode an ESCALATE decision opens no exception case.

## As built (P3 group 2)

- **Guides (DOC-03):** six pages in `docs/guides/`: let an AI agent pay a supplier invoice (18,500.00 USDC to
  `cpt_bluefin` under `mnd_demo_ap_agent`, escalated, approved by a second member, confirmed; 20,000.01 blocks
  with `MANDATE_AMOUNT_EXCEEDED`), credit deposits safely, handle UNKNOWN payments, approve escalations by API,
  use the kill switch, and move from shadow to auto mode (in the console's Settings, two people). Each guide's
  request bodies and shown responses are read from the page and run against a sandbox organisation
  (`tests/integration/test_docs_guides.py`).
- **Try it (DOC-05):** Mintlify's interactive playground with bearer auth (`tools/try-it.mdx`). The OpenAPI file
  names only local and sandbox servers, with no server variables, and the navbar has "Request sandbox access";
  a test holds all three. The sandbox server is added when its address is known (founder item).
- **Sandbox seed (G-18, as found):** a new sandbox organisation now also gets the fictional accounts-payable
  agent's mandate (`mnd_demo_ap_agent`, valid for 365 days) when the mandate signing key is set, so the agent
  guide and the "amount above mandate" test value work outside the demo organisation; there is no API to issue
  mandates. It also gets travel-rule originator details (its name and a fictional `SANDBOX-<org_id>` account),
  as the demo organisation has, so payouts over the threshold no longer escalate `TRAVEL_RULE_MISSING`.
- **As found:** in a client organisation only the payments lead may engage or release the kill switch (on-call is
  not a dashboard role), and the account owner may not approve, reject or engage.

## As built (P3 group 3)

- **Generated, then polished (SDK-01, SDK-02):** `tools/build_sdks.py` writes each SDK's typed models and one
  method per API operation from `docs/api/openapi.json` (`sdks/python/src/dekernai/_generated.py`,
  `sdks/typescript/src/generated.ts`); `NAMES` there gives each operation its resource and method name, and the
  build fails on an operation without one. CI checks the files are current (`--check`); `make openapi` rebuilds
  them. The client itself is hand-written: `dekernai/_client.py` and `src/client.ts`.
- **Behaviour (both):** an `Idempotency-Key` on every create (UUIDv4 unless given); retries only on 429, 503 and
  connection errors before the request arrives (refused, DNS, connect timeout), with the same key, `Retry-After`
  honoured, 2 retries by default; never a read timeout or a dropped connection. Errors carry the error body's
  fields. `verify_webhook(secret, header, body, tolerance=300)` / `verifyWebhook(...)` return the event. A
  `sk_live_` key is refused when the client is created.
- **Python:** `sdks/python`, package `dekernai`, Python 3.11 or later, `httpx` only; a workspace member, so
  `apps/api/tests/integration/test_sdk_python.py` runs it against the real app and database in process, and
  `sdks/python/tests` against a fake transport. CI builds the wheel and installs it in a clean environment.
- **TypeScript:** `sdks/typescript`, Node 18 or later, no runtime dependencies, ESM and CommonJS builds. CI's
  `sdks` job starts the sandbox API with the seeded demo organisation and a throwaway key and runs the unit, CJS
  and sandbox tests against it.
- **Not published:** no licence and no package index release yet (`private`, "Do Not Upload"); both are founder
  decisions. The docs page `tools/sdks.mdx` says to install from the repository.
- **Fixed on the way:** `POST /v1/decisions` returns a decision, not a payment intent; the OpenAPI file now says
  so. IDs made in the same millisecond in one process now sort in the order they were made (RFC 9562 monotonic
  UUIDv7): with a frozen clock, "the latest decision" was a coin toss, so releasing the kill switch right after an
  approval could re-escalate the payment.

## As built (P3 group 4)

- **Samples are files (DOC-04):** `docs/snippets/<lang>/` holds a `create_payout` (the quickstart's
  `payout.json`, with a fresh `Idempotency-Key`) and a `verify_webhook` sample in cURL (bash and openssl), Python,
  TypeScript (Node 22, run as is), Go, Java (single-file programs), C#, PHP and Ruby, each with its language's
  standard library only. The part a page shows sits between `docs:start` and `docs:end`; `tools/build_docs.py`
  writes it into the page between `{/* snippet: <name> */}` and `{/* /snippet */}` as a `<CodeGroup>`, and its
  `--check` fails when a page differs from the files.
- **Run in CI (DOC-04, WHK-02):** `tools/run_snippets.py` runs every language's `verify_webhook` against the shared
  cases in `docs/snippets/webhook-vectors.txt` (valid, edge of the window, rotated, stale, future, changed body,
  secret or timestamp, malformed headers), then its `create_payout` against the sandbox API that CI's SDK job
  starts, and needs a `pay_` ID back. A unit test checks each vector against the API's own signing code.
  `--vectors-only` needs no sandbox.
- **Reference samples (DOC-04):** Mintlify generates the API reference's request samples from
  `docs/api/openapi.json` in the same eight languages (`api.examples.languages` in `docs/docs.json`).
- **Changed on the way:** the docs name the key variable `DEKERNAI_API_KEY`, as the SDKs do.
- **Website code tabs (WEB-04):** `tools/build_docs.py` also writes `apps/site/src/data/snippets.json` (the
  `create_payout` regions, the quickstart's `payout.json` and its response) and `--check` fails when it is stale;
  the home page's engineering panel renders it, so the site shows the same tested code as the docs.

## As built (P4)

- **Onboarding page (WEB-02):** `/design-partners/` ("Onboarding" in the menus) lists the seven phases from
  `apps/site/src/data/onboarding.mjs` and a "Your data" section: what data each phase uses, the append-only audit
  trail, the G-19 sandbox retention (request logs 30 days; other sandbox data until the organisation expires plus
  30 days) and that DekernAI never holds client funds or keys. G-19 still needs the founder's legal review.
- **Access form (WEB-06):** `accessFormAction` in `apps/site/site.config.mjs` is the live deploy's
  `https://app.dekernai.com/access-requests` (DSH-10); a plain form post, so the visitor lands on the dashboard's
  thank-you page. "Book a demo" stays an email to the sales inbox until the founder's booking URL replaces
  `bookingUrl`; WEB-06 is done when it does.
- **Status page (WEB-07):** `GET /status.json` (`detent/api/status.py`) reports `sandbox_api`, `dashboard` and
  `docs` as `operational`, `down` or `not_monitored`, with `checked_at`. API and dashboard share the database check
  (one process); docs is an HTTP GET of `STATUS_DOCS_URL` (empty: not monitored). Results are reused for
  `STATUS_CACHE_SECONDS` (60) and served to any origin, with nothing private in them. The site's `/status/` page
  fetches it in the browser every minute (`apps/site/src/lib/status.mjs`); because the site is hosted apart from
  the deploy, a failed fetch shows the API and dashboard as "can't be reached".

## As built (L group 2: DSH-13)

- **Production mode (DSH-13):** the verification page ends with "Production mode". The request button is offered to
  the account owner only when the integration is verified (DSH-12) and the active rule version was attested by the
  client's compliance lead. A request is recorded (`production_requests`, audit `production.requested` with
  `starts_in: shadow`) and the page says the switch is not available in the prototype. Nothing else changes: no mode
  change and no `sk_live_` key (invariant 14). In production the organisation starts in Shadow and moves up on
  signed mode gates (SHD-03).

## As built (slice T: CON-11)

- **AI team:** the dashboard navigation has "AI team", which opens the console's AI team page (`/console/agents`,
  spec/07) for the member's own organisation; `/dashboard/ai-team` and `/dashboard/agents` redirect there.
- **Website AI team section (WEB-09):** the home page has "Your AI team comes with the service." after the rules
  demo (`apps/site/src/components/AiTeam.astro`): the three AI agents, each with what it does, what the client gets
  and what it can't do, a note that orchestration has no agent, and the built-in limits. The spine's orchestration
  column now says no agent works there, matching the product (the investigation agent runs on held payout cases).

## Needed from the founder before M8 to M11

- the name and domain
- a transactional email provider (chosen: ZeptoMail, D-43)
- an always-on hosting tier for the sandbox
- a Mintlify account
- the booking page link
- the sales inbox address
- legal text review (privacy, sandbox terms, cookies)
