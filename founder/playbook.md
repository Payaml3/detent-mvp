# Playbook: the journey from zero to scale

30 stages in 7 phases (A to G). A stage starts only when the previous gate is passed or explicitly deferred. Inside stages 13 to 17, work ships in slices, built one story group per session. Status is one of To do, Current, Passed or Deferred; `weekly-review` proposes changes, the founder approves them. Engineering-standards gates point to `docs/engineering-standards.md`.

## Stages

| # | Phase | Stage | Where | Gate | Status | Evidence | Start | Target |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | A Discover | Problem validation | P 01 | Pain confirmed by evidence, not assumption | To do | Not yet: no customer evidence in the repo (`founder/status.md`, risk 1; `founder/business-context.md` § Open) |  |  |
| 2 | A Discover | Customer discovery | P 01 | 5 to 8 interviews show pain and willingness to pay | To do | Not yet: no interview notes or letters of intent (`founder/business-context.md` § Open) |  |  |
| 3 | B Define | Business model and positioning | P 01 | Founder approves | To do | Partial: pricing structure D-15, prototype-first D-34 (`specs/001-detent-mvp/decisions.md`); positioning and pricing still Open (`founder/business-context.md`) | 2026-11-18 |  |
| 4 | B Define | Brand strategy | P 06 | Name, trademark and domain checked | To do | Partial: working name only, domain a placeholder (D-17, `founder/brand.md`); no trademark check | 2026-11-18 |  |
| 5 | B Define | Product and operating model | P 02 | Founder approves | To do | Partial: `spec/product-definition.md`, `spec/00-product-context.md`, `spec/01-architecture.md`; source documents exist only as extracts (`founder/sources/README.md`) | 2026-11-18 |  |
| 6 | B Define | UX prototype and test | P 02, Code | Tested with 3 to 5 target users | To do | Not yet: console screens specified (`spec/07-console.md`), no user tests recorded |  |  |
| 7 | B Define | MVP scope and launch criteria | P 02 | Founder approves scope | Passed | MVP and slices S0 to S9, P1 to P4 (D-11); prototype first (D-34); `backlog/milestones.md`, `specs/001-detent-mvp/slices.yaml` | 2026-11-18 |  |
| 8 | C Specify and design | Specify | Code | Every open item answered or deferred | To do | `specs/001-detent-mvp/spec.md`, `requirements.yaml`; decisions D-01 to D-36; still Proposed or Open: C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 (`founder/status.md`) | 2026-11-18 |  |
| 9 | C Specify and design | Screen specs | Code | Criteria linked to stories | Passed | `spec/07-console.md`; criteria traced to stories in `specs/001-detent-mvp/traceability.md` and `test-map.yaml` | 2026-11-18 |  |
| 10 | C Specify and design | Plan the system | Code, P 03 | Founder approves architecture, threat model and Well-Architected review; threat model (STRIDE), Well-Architected review, scale-ready defaults in the constitution | To do | `specs/001-detent-mvp/plan.md`, `research.md`, `data-model.md`, `contracts/`; `spec/01-architecture.md`, `spec/10-security-and-deploy.md`; no STRIDE threat model or Well-Architected review in the repo yet | 2026-11-18 |  |
| 11 | C Specify and design | Design system | Code | Founder approves foundations | To do | Brand tokens D-18 (`spec/07-console.md`); site look D-19 to D-21 | 2026-11-18 |  |
| 12 | C Specify and design | Tasks and story groups | Code | `analyze` finds no contradictions | Passed | `specs/001-detent-mvp/tasks.md`; `make spec` coverage checks | 2026-11-18 |  |
| 13 | D Build and prove | Build, one session per story group | Code 04 | Definition of done met | Current | Slices S0 to S8 done on `main` (`founder/slices.json`); S9 code built 2026-11-20, live run waiting on founder items; 219 of 308 criteria with evidence (`founder/status.md`) | 2026-11-18 |  |
| 14 | D Build and prove | Test at 5 levels | CI, founder | All levels pass | To do | Release gate and eval suites EVL-01 to EVL-08 (S8, `spec/09-evaluation-and-tests.md`); real testnet runs RAL-02/03 still missing | 2026-11-19 |  |
| 15 | D Build and prove | Integrate continuously | GitHub | Founder merges | To do |  |  |  |
| 16 | D Build and prove | Deploy continuously, to non-production | CI | Test data only; dependencies pinned, builds signed; pinned dependencies, automated updates, bill of materials, signed build provenance | To do | S9 deploy config ready (`render.yaml`, FND-07); waits on Render and Neon accounts (`founder/status.md`) |  |  |
| 17 | D Build and prove | Release check | P 05, Code | Go | To do |  |  |  |
| 18 | E Launch | Demo and website | Code, P 06 | Honesty checklist signed | To do | Marketing site built in `apps/site` (WEB-01 to WEB-08, D-14, D-22), no-index until launch | 2026-11-18 |  |
| 19 | E Launch | Sandbox or beta | Code | External user completes the core flow | To do |  |  |  |
| 20 | E Launch | Design partners | P 06 | Partner confirms value | To do |  |  |  |
| 21 | E Launch | Production readiness | P 05, Code | All readiness items closed; service targets and error-budget policy, alerts on user impact, restore and load tests, AI spending caps per customer | To do |  |  |  |
| 22 | E Launch | General availability | P 00 | Founder go-live decision | To do |  |  |  |
| 23 | F Grow to product-market fit | Measure | P 00, Task | 5 stage metrics tracked weekly | To do |  |  |  |
| 24 | F Grow to product-market fit | Iterate | P 01, P 06 | Retention and conversion hit targets | To do |  |  |  |
| 25 | F Grow to product-market fit | Fundraise | P 00 | Round closed or deferred | To do |  |  |  |
| 26 | G Scale | Team and ownership | P 00 | Every area has a human owner | To do |  |  |  |
| 27 | G Scale | Operations | Code, P 05 | Targets met for a quarter; monthly error-budget review, blameless postmortems | To do |  |  |  |
| 28 | G Scale | Compliance and certifications | P 03, P 05 | Audit passed | To do |  |  |  |
| 29 | G Scale | Platform and new products | Code, P 03 | Architecture approved | To do |  |  |  |
| 30 | G Scale | Governance cadence | P 00, Task | Cadence running | To do |  |  |  |

## Production readiness

Checked by `release-check` before any production step. Each item is To do, Done or Not needed (with a decision ID).

| Item | Status |
| --- | --- |
| Security review and penetration test | To do |
| Legal terms, privacy and data-processing terms, including the AI provider's data terms | To do |
| Monitoring, alerting on user impact, runbooks and an incident process | To do |
| Backups and a tested restore | To do |
| Load test at expected volume | To do |
| Service targets and error-budget policy (`docs/operations/slo.md`) | To do |
| AI spending caps and rate limits per customer | To do |
| Regulatory advice the domain needs | To do |
