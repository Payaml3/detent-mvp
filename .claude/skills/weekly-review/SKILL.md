---
name: weekly-review
description: Use for the Monday weekly review, whether a scheduled task or the founder triggers it; reports progress, CI health, stale items and contradictions, and proposes a status update as a PR.
---

# Weekly review

Read only what is listed. Do not open specs, code or the backlog unless a contradiction needs one line checked.

## 1. Read

- `HANDOFF.md`, `founder/status.md`
- `founder/decisions.md`, `specs/001-detent-mvp/decisions.md`
- `specs/001-detent-mvp/slices.yaml`
- CI on `main`: `gh api "repos/Payaml3/detent-mvp/actions/runs?branch=main&per_page=10" --jq '.workflow_runs[] | [.name, .conclusion, .created_at] | @tsv'`
- Open PRs: `gh api "repos/Payaml3/detent-mvp/pulls?state=open" --jq '.[] | [.number, .title, .head.ref, .updated_at] | @tsv'`
- Branches: `git fetch origin` then `git branch -r --merged origin/main` (merged, not deleted) and `git branch -r --no-merged origin/main`

## 2. Report (at most 25 lines)

```
Weekly review <yyyy-mm-dd>
Progress since last week: <slices/criteria moved; compare with status.md "Where the build is">
CI health: <pass/fail of the last runs on main, failing job names>
Stale (Proposed/Open older than 7 days): <IDs with dates>
Contradictions: <doc A says X, doc B says Y>
Merged branches not deleted: <names>
Founder items blocking the next slice: <items>
Recommended focus: <one item, one line why>
```

- "Older than 7 days" uses the row's date; if a row has no date, say so.
- A contradiction needs both sources named. Don't report style differences.

## 3. Update status on a branch

```
git checkout -b review/<yyyy-mm-dd> origin/main
```

Edit `founder/status.md` only: "Last updated", "Where the build is", risks, founder items, and
"This week's focus" (always **Proposed**). Then:

```
make governance
git commit -am "Weekly review <yyyy-mm-dd>"
git push -u origin review/<yyyy-mm-dd>
gh api repos/Payaml3/detent-mvp/pulls -f title="Weekly review <yyyy-mm-dd>" -f head=review/<yyyy-mm-dd> -f base=main -f body="<the report>"
```

**Never merge it.** The founder reviews and merges.
