---
name: weekly-review
description: Use for the Monday weekly review, whether a scheduled task or the founder triggers it; stops early on quiet weeks, otherwise reports progress, CI, stale items and contradictions and proposes a status update as a PR.
---

# Weekly review

**Read lean.** Never read a whole file over 150 lines. Use `grep -n` to find the section, then read only that line range. Use `git diff` and `git log` to see what changed instead of re-reading files.

## 0. Quiet week? (before reading anything else)

```
SINCE=$(grep -oE "Last updated: [0-9-]+" founder/status.md | cut -d' ' -f3)
git fetch origin main --depth=50
git log origin/main --since="$SINCE" --oneline        # new commits?
gh api "repos/Payaml3/detent-mvp/pulls?state=all&sort=updated&per_page=5" --jq '.[] | .updated_at'   # PR activity since SINCE?
gh api "repos/Payaml3/detent-mvp/actions/runs?branch=main&per_page=1" --jq '.workflow_runs[0].conclusion'
```

Stop early only if there are **no commits**, **no PR updated on or after SINCE**, and the last run on `main`
is `success`. Then reply in at most 2 lines and stop (no branch, no PR, no further reads):

`No change since <SINCE>; CI passing. Still blocking: <top founder item>.`

The top founder item is the first data row under "Open founder items":
`grep -n -A4 "^## Open founder items" founder/status.md`. Otherwise, run the full review below.

## 1. Read (targeted)

- `HANDOFF.md` and `founder/status.md`: `grep -n "^## "`, then only "Where we are", "Next slice" and the founder items.
- Registers: `grep -nE "\| \*{0,2}(Proposed|Open)" founder/decisions.md specs/001-detent-mvp/decisions.md` for
  stale items, plus rows dated on or after SINCE (`grep -nE "20[0-9]{2}-[0-9]{2}-[0-9]{2}"`, keep dates >= SINCE).
- `grep -nE "^- id:|status:" specs/001-detent-mvp/slices.yaml`
- CI: `gh api "repos/Payaml3/detent-mvp/actions/runs?branch=main&per_page=10" --jq '.workflow_runs[] | [.name, .conclusion, .created_at] | @tsv'`
- PRs: `gh api "repos/Payaml3/detent-mvp/pulls?state=open" --jq '.[] | [.number, .title, .head.ref, .updated_at] | @tsv'`
- Branches: `git branch -r --merged origin/main` (merged, not deleted) and `git branch -r --no-merged origin/main`

## 2. Report (at most 25 lines)

```
Weekly review <yyyy-mm-dd>
Progress since <SINCE>: <slices/criteria moved>
CI health: <last runs on main, failing job names>
Stale (Proposed/Open older than 7 days): <IDs with dates; "no date" if none>
Contradictions: <doc A says X, doc B says Y>
Merged branches not deleted: <names>
Founder items blocking the next slice: <items>
Recommended focus: <one item, one line why>
```

A contradiction needs both sources named. Don't report style differences.

## 3. Update status on a branch

```
git checkout -b review/<yyyy-mm-dd> origin/main
```

Edit only the changed lines of `founder/status.md` (found with `grep -n`): "Last updated", "Where the build is",
risks, founder items, "This week's focus" (always **Proposed**). Then:

```
make roadmap-page          # founder/roadmap.md picks up the status changes
make governance
git commit -am "Weekly review <yyyy-mm-dd>"
git push -u origin review/<yyyy-mm-dd>
gh api repos/Payaml3/detent-mvp/pulls -f title="Weekly review <yyyy-mm-dd>" -f head=review/<yyyy-mm-dd> -f base=main -f body="<the report>"
```

**Never merge it.** The founder reviews and merges.

Publish `build/roadmap.html` to the roadmap Artifact URL in `HANDOFF.md` (pass it as `url`; never create a new one),
so the founder's phone view shows this week's state.
