---
name: handoff
description: Use when the founder says "close", "handoff" or "wrap up", when the context guard asks for a handoff, or when a slice is done; writes the closing summary into the repo, pushes and names the next session.
---

# Handoff

Close the session so the next one starts from the repository, not from chat history.
Stop starting new work. Finish or revert the step in progress first.

## 1. Closing summary (protocol §7), at most 15 lines

```
Outcome: <one or two lines>
Approved: <decisions the founder approved in this session, with their words; or "none">
Pending: <Proposed / Assumption / Open items raised, with IDs>
Files changed: <paths, grouped>
Risks / blockers: <short list>
Next action: <one line>
```

Only list something under Approved if the founder said so in this session. Everything else is Pending.

## 2. Write it into the right files

| What | Where |
|---|---|
| Build state: slices, branches, what was built, known gaps, next slice | `HANDOFF.md` |
| Priorities, risks, open founder items, this week's focus | `founder/status.md` (bump "Last updated") |
| Decisions the founder approved in this session | Product/engineering: `specs/001-detent-mvp/decisions.md` (next `D-` row). Business: `founder/decisions.md` (next `B-` row). Use the `record-decision` skill. |

Rules:
- Edit only what changed. Keep `HANDOFF.md` and `founder/status.md` to one page each.
- Never mark a row Approved or Confirmed without the founder's words in this session.
- If a slice is done: `status: done` in `specs/001-detent-mvp/slices.yaml`, then `make backlog spec`.
- Always run `make roadmap-page` and commit `founder/roadmap.md`; then publish `build/roadmap.html` to the roadmap
  Artifact URL in `HANDOFF.md` (pass it as `url`, never create a new one).

## 3. Check, commit, push, PR

```
make governance            # registers, HANDOFF-on-slice-done, tool tests
git add -A && git commit -m "HANDOFF: <slice or task>"
git push -u origin <branch>
```

- Never push to `main`. If the branch has no PR, open one into `main`; otherwise the push updates it.
- If `make governance` fails, fix the cause; never weaken the check.

## 4. Tell the founder the next session

End with exactly:

```
Next session name: Detent · <slice or task> <short name>
First message:
  Read CLAUDE.md and HANDOFF.md, then <the next action>. Start from main.
```

If the work continues on the same branch (PR not yet merged), say "Start from <branch>" instead.
