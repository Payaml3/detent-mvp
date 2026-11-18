# Tasks: Marketing website

**Input**: [plan.md](plan.md), [spec.md](spec.md). Tests first (constitution, Principle VI).

## Phase 1: Setup

- [x] T001 Create the Astro project in `apps/site/` with `site.config.mjs` (FR-209, FR-207) and self-hosted fonts (D-18)
- [x] T002 Add `make site`, `make site-test` and CI steps that build the site and run its checks

## Phase 2: Tests first

- [x] T003 Write `apps/site/tests/site.test.mjs`: banned phrases and claims on every page (FR-202); eleven home sections in order and both CTAs (FR-201); sub-pages exist (FR-203); results section honest with and without a results file (FR-204); code labelled pre-launch (FR-205); legal pages marked draft (FR-206); placeholder report (FR-207); titles, sitemap, OG and schema.org (FR-208); pricing has no prices (FR-210). Run it and watch it fail.

## Phase 3: User Story 1 (P1) home page

- [x] T004 Tokens and base layout (`src/styles/`, `src/layouts/Base.astro`)
- [x] T005 Hero with the held $18,500 payment fragment (data-ui)
- [x] T006 Sections 2 to 11 from the dealt blueprints
- [x] T007 The "What goes wrong?" live demonstration with a no-script fallback

## Phase 4: User Story 2 (P1) sub-pages

- [x] T008 Product, Security, Design partners pages

## Phase 5: User Story 3 (P2) honest placeholders

- [x] T009 Results section reading `src/data/results.json` if present; pre-launch code tabs; draft legal pages; SEO outputs

## Phase 6: Polish

- [x] T010 Design gate: `lint.mjs`, `inspect.mjs` at 1440, 768, 390 until 0 FAIL; critique round; motion layer
- [x] T011 Screenshots of every page for the founder; report sample content and placeholders

## Status (2026-11-18)

Done: all tasks. Open by design: WEB-04 (snippets become the DOC-04 tested set), WEB-06 (booking URL and access endpoint
are placeholders until the founder supplies them and DSH-10 exists), WEB-07 (status page needs the deployed services).
