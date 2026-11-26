# 08 · Developer portal: dashboard, sandbox, docs, SDKs and website

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** how developers and buyers reach all three layers (dashboard, sandbox, docs, SDKs, website).

Source: `venture/05-developer-portal.md` (16 Nov 2026). The marketing site and docs are public. **Sandbox keys are not self-serve.** A developer gets keys only after contacting sales by email or booking a demo; the admin then creates the organisation and sends an invite.

## Surfaces (domains are placeholders until the name is final)

| Surface | Host | Built with |
|---|---|---|
| Marketing site | `<domain>` | Astro static site (`apps/site`) |
| Docs | `docs.<domain>` | Mintlify Starter from `docs/` |
| Dashboard and console | `dashboard.<domain>` | The `api` app (Jinja and htmx) |
| Sandbox API | `sandbox.api.<domain>` | The `api` app |
| Status | `status.<domain>` | A hosted status page fed by `/healthz` (WEB-07) |

## Dashboard (DSH)

- **Sales-led access:**
  - There is no public sign-up route.
  - The admin creates an organisation (name, expiry 60 days by default) and invites emails.
  - An invite link is single-use and lasts 7 days.
  - The developer verifies their email and sets a password (argon2), then lands on the Keys page.
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
- **Console:** the back-office screens scoped to the organisation. Demo-only controls are hidden.
- **Admin (DekernAI only):** organisations, invites, expiry extension, and the access-requests inbox (DSH-10).

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

1. **Hero:** "Every deposit and payout, decided by your rules." Category line: "Agentic payment controls: one layer that decides, orchestrates and operates every deposit and payout, under your rules." The primary CTA is "Get a free shadow report"; the secondary CTA is Book a demo. The example payment plays through the three layers beside the "sift then settle" art. A small honesty line: prototype, test networks only, never holds funds or keys.
2. **The problem:** "On rails you can't reverse, every mistake is permanent." Manual review queues, deposits credited wrong, retries that become double payments, decisions nobody can replay.
3. **Sift. Settle. Prove.:** the three layers as one payment's life, with the same payment ID: your rules decide in each, agents do the groundwork. "Agents prepare. Your rules decide." is said here once.
4. **Built for irreversible payments:** "A failure can retry. A rejection can't. No retry ever becomes a second payment.", with the payment states shown and the kill switch.
5. **Measured results:** shown only once `results.json` exists, each figure labelled "test-network evaluation, [date]". Left out of the page until then.
6. **Roles:** tabs for Payments, Compliance and Engineering. Engineering holds the 8-language code tab creating a payment intent (pre-launch label) and the sandbox access link; Compliance links to the Security page, which holds non-custodial, audit and replay, kill switch, EU hosting and the roadmap list.
7. **The free shadow report:** what you send, what we do, what you get in 5 working days, beside a sample report labelled fictional. Paid plans (Pilot, Growth, Scale) are "Talk to us", with no prices.
8. **Use cases and FAQ:** payout platforms, crypto service providers, brokers and prop firms, marketplaces; then 5 questions (money and custody, does the AI approve, rails, what the report needs, cost).
9. **Close:** "Held until it's right. Sent exactly once." with both CTAs.
10. **Footer:** docs, status, privacy, terms, contact.

**Sub-pages:** Product, Security, and Design partners (the free shadow report offer).

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

## Needed from the founder before M8 to M11

- the name and domain
- a transactional email provider
- an always-on hosting tier for the sandbox
- a Mintlify account
- the booking page link
- the sales inbox address
- legal text review (privacy, sandbox terms, cookies)
