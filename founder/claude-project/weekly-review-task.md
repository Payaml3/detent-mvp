# Monday weekly review: scheduled task prompt

Create a scheduled Claude Code task on `Payaml3/detent-mvp`, every Monday at 08:00 (your time zone),
starting from `main`, and paste the prompt below as its message.

---

Name this session `Detent · Weekly review <today's date>`.

You are working in `Payaml3/detent-mvp`, starting from `main`. Read `CLAUDE.md`, then run the
`weekly-review` skill (`.claude/skills/weekly-review/SKILL.md`) exactly as written:

- Start with its step 0. If nothing changed since `founder/status.md`'s "Last updated" date (no commits,
  no PR activity, CI on `main` passing), reply in at most 2 lines and stop: no branch, no PR.
- Read only the files and GitHub data the skill lists.
- Report progress since last week, CI health on `main`, Proposed or Open items older than 7 days,
  contradictions between documents, merged branches not yet deleted, founder items blocking the next
  slice, and one recommended focus.
- Update `founder/status.md` on a branch `review/<yyyy-mm-dd>` and open a PR into `main`. Never merge it.
- Mark nothing Approved. The recommended focus is Proposed.

End with the PR link and the report, in at most 25 lines (or the 2-line early stop).
