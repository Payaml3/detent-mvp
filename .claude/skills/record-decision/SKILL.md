---
name: record-decision
description: Use when the founder approves, rejects or changes a decision; adds the register row with their words, then traces and prepares every downstream edit.
---

# Record a decision

**Read lean.** Never read a whole file over 150 lines. Use `grep -n` to find the section, then read only that line range. Use `git diff` and `git log` to see what changed instead of re-reading files.

## 1. Pick the register

| Decision is about | Register | Next ID |
|---|---|---|
| Product behaviour, rules, architecture, engineering, tests | `specs/001-detent-mvp/decisions.md`, "Decision log" | next `D-` |
| Business, GTM, pricing, brand, legal, hiring | `founder/decisions.md`, "Register" | next `B-` |

Find the next ID with `grep -noE "^\| [DB]-[0-9]+" <register> | tail -1`. If unsure which register, ask.
Never move existing rows between registers.

## 2. Add the row

- Status:
  - founder approved in words → **Approved** (business) / **Confirmed** (specs register's word)
  - founder rejected → keep the row, status **Open** or **Proposed** with "rejected <date>: <reason>"
  - founder changed it → new row; the old row says "superseded by <new ID>"
- Date: today (YYYY-MM-DD). Source: the founder's exact words, plus where (session name or PR).
- Business rows: fill "Affected layers" from Business → Product → MVP → Architecture → Tasks → Tests → Release.
- If it resolves a `C-`, `G-` or `A-` item, update that item's Status to `**Confirmed** <date> (founder, <D-ID>)`.

## 3. Walk the traceability chain

Grep, then read only the matching line ranges:

```
grep -n "<ID or term>" backlog/traceability.md specs/001-detent-mvp/traceability.md specs/001-detent-mvp/slices.yaml
grep -rn "<ID or term>" spec/ specs/ backlog/stories.yaml founder/ fixtures/
```

For each hit, read a few lines around it (`sed -n '<start>,<end>p' <file>`), never the whole file.
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
- After applying: `make backlog spec governance`, commit `<ID>: <one line>`.
- Summarise what changed in at most 5 lines.
