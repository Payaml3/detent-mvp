# Implementation Plan: Marketing website

**Branch**: `web/002-marketing-site` | **Date**: 2026-11-18 | **Spec**: [spec.md](spec.md)

## Summary

A static Astro site in `apps/site/` with the home page (eleven spec/08 sections), Product, Security, Design partners
and three draft legal pages. The art direction is the design skill's "product performs" (seed 390410435) with the
spec/07 brand kept: the product's own interface, built in HTML, is the imagery. One live demonstration ("What goes
wrong?") runs the real payment states in the browser. A build-time check enforces the honesty rules and reports
placeholders.

## Technical Context

**Language/Version**: TypeScript/JavaScript on Node 22 · **Primary Dependencies**: Astro 5 (static output),
@fontsource packages for self-hosted fonts · **Storage**: none · **Testing**: `node --test` checks over the built
HTML (honesty, structure, SEO, placeholders); the design skill's `lint.mjs` and `inspect.mjs` · **Target**: static
files, any EU static host later · **Constraints**: no cookies, no third-party requests at runtime, works without
JavaScript · **Scale**: 7 pages

## Constitution Check

| Principle | Compliance |
|---|---|
| VII. Honesty, independence, no invented rules | Build check bans the forbidden phrases and claims; no figures without a dated, labelled results file; plan inclusions marked as sample content; no competitor name |
| VI. Test-first | The checks are written first and fail on an empty build |
| Others (I to V) | Not touched: no payment code |

**Gate: pass.**

## Project Structure

```text
apps/site/
├── site.config.mjs        # BRAND_NAME, domain, booking URL, access target (placeholders flagged)
├── astro.config.mjs
├── src/
│   ├── layouts/Base.astro # head (titles, OG, schema.org), nav, footer
│   ├── components/        # one per home section + interface fragments (data-ui)
│   ├── pages/             # index, product, security, design-partners, privacy, terms, cookies
│   ├── data/results.json  # optional; absent until EVL-06
│   ├── scripts/demo.js    # the "What goes wrong?" state engine
│   └── styles/            # tokens.css (spec/07), site.css
├── public/                # og image, favicon
└── tests/site.test.mjs    # honesty, structure, SEO, placeholder checks over dist/
```

## Tasks

See [tasks.md](tasks.md).
