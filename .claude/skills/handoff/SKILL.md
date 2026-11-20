---
name: handoff
description: Use when the founder says "close", "handoff" or "wrap up", when the context guard asks for a handoff, or when a story group or slice is done; picks a short close or a full handoff and names the next session.
---

# Handoff

**Read lean.** Never read a whole file over 150 lines. Use `grep -n` to find the section, then read only that line range. Use `git diff` and `git log` to see what changed instead of re-reading files.

Stop starting new work. Finish or revert the step in progress first.

## Pick the mode

| Situation | Mode |
|---|---|
| Small task, or a story group done with the slice still unfinished | **Short close** |
| Slice done, or the context guard fired mid-slice (the state must survive) | **Full handoff** |

When unsure, use the full handoff.

## Short close

1. In the chat, 3 lines: `Done: … / Pending: … / Next: <next story group or task>`.
2. Change no files beyond the work itself. Touch `HANDOFF.md` only if the next step changed: one line in
   the "Now" row of "Where we are" (add the row if missing), found with `grep -n "| Now" HANDOFF.md`.
3. If the work changed `slices.yaml`, `backlog/stories.yaml`, `specs/001-detent-mvp/decisions.md` or
   `founder/status.md`, run `make roadmap` and commit `founder/roadmap.md`, `founder/mvp-scope.md` and
   `founder/user-journey.md` (CI checks they are current).
4. Commit and push the branch. No PR update text, no status edit. Then the "Next session" block below.

## Full handoff

1. Closing summary (protocol §7), at most 15 lines:
   ```
   Outcome: <one or two lines>
   Approved: <decisions the founder approved in this session, with their words; or "none">
   Pending: <Proposed / Assumption / Open items raised, with IDs>
   Files changed: <paths, grouped>
   Risks / blockers: <short list>
   Next action: <one line>
   ```
   Only list something under Approved if the founder said so in this session.
2. Write it into the files. Edit only the changed lines, found with `grep -n`; never rewrite a whole file.
   - `HANDOFF.md`: build state, branches, what was built, known gaps, next slice.
   - `founder/status.md`: priorities, risks, founder items, "Last updated".
   - Decisions approved in this session: `record-decision` skill (`D-` specs register, `B-` business).
   - Slice done: `status: done` in `specs/001-detent-mvp/slices.yaml`, then `make backlog spec`.
   - Always run `make roadmap-page` and commit `founder/roadmap.md`, `founder/mvp-scope.md` and
     `founder/user-journey.md`; then publish `build/roadmap.html`, `build/mvp-scope.html` and
     `build/user-journey.html` to their Artifact URLs in `HANDOFF.md` (pass each as `url`, never create a new one).
     If this session ran a full `make eval`, run `make eval-snapshot` first and commit `eval/results/latest.json`.
3. Slice done: propose the next slice's story groups (3 to 6 related stories that share files) under
   "Next slice" in `HANDOFF.md`, one line each: `Group 1: STORY-IDs (why grouped) · Model: <strongest | mid-tier>`.
   Use the "Model choice" table in `CLAUDE.md`.
4. Check and ship:
   ```
   make governance
   git add -A && git commit -m "HANDOFF: <slice or task>"
   git push -u origin <branch>
   ```
   Never push to `main`. Open a PR into `main` if none exists; otherwise the push updates it.
   If `make governance` fails, fix the cause; never weaken the check.

Never mark a row Approved or Confirmed without the founder's words in this session.

## Next session (both modes)

End with exactly:

```
Next session name: Detent · <slice> <group or task>
Model: <strongest | mid-tier>
First message:
  Read CLAUDE.md and HANDOFF.md, then <the next action>. Start from main.
```

If the work continues on an unmerged branch, say "Start from <branch>" instead.
