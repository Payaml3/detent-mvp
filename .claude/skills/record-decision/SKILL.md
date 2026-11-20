---
name: record-decision
description: Use when the founder approves, rejects or changes a decision; adds the register row with their words, then traces and prepares every downstream edit.
---

# Record a decision

## 1. Pick the register

| Decision is about | Register | Next ID |
|---|---|---|
| Product behaviour, rules, architecture, engineering, tests | `specs/001-detent-mvp/decisions.md`, "Decision log" | next `D-` |
| Business, GTM, pricing, brand, legal, hiring | `founder/decisions.md`, "Register" | next `B-` |

If unsure, ask the founder which one. Never move existing rows between registers.

## 2. Add the row

- Status:
  - founder approved in words → **Approved** (business) / **Confirmed** (specs register's word)
  - founder rejected → keep the row, status **Open** or **Proposed** with "rejected <date>: <reason>"
  - founder changed it → new row; the old row says "superseded by <new ID>"
- Date: today (YYYY-MM-DD).
- Source: quote the founder's words exactly, plus where (session name or PR).
- Business rows: fill "Affected layers" from Business → Product → MVP → Architecture → Tasks → Tests → Release.
- If it resolves a `C-`, `G-` or `A-` item, update that item's Status to `**Confirmed** <date> (founder, <D-ID>)`.

## 3. Walk the traceability chain

Find everything the decision touches, layer by layer:

1. `backlog/traceability.md`: model items → stories.
2. `specs/001-detent-mvp/traceability.md`: requirements → stories → criteria → tests.
3. `specs/001-detent-mvp/slices.yaml`: which slices hold those stories.
4. `grep -rn "<ID or key term>" spec/ specs/ backlog/ founder/ fixtures/` for prose that restates the old rule.

List the result as:

```
Decision <ID>: <one line>
Affected:
- spec/04-policy.md §<section>: <what changes>
- backlog/stories.yaml <STORY-ID> AC<n>: <what changes>
- test <path>::<name>: <new or changed>
- slice <id>: <impact>
```

## 4. Prepare, then wait

- Prepare the edits (as a diff or a short list). **Apply them only if the founder says so.**
- Writing the register row itself is part of recording it; downstream edits are not.
- After applying: run `make backlog spec governance`, commit `<ID>: <one line>`.
- Summarise what changed in at most 5 lines.
