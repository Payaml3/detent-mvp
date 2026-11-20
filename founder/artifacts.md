# Live views

Views are generated from the repo and never edited as the source. `publish-views` republishes only rows whose sources changed since the last published commit, on the Monday scheduled task. Comments on a view become proposed edits in the repo.

| View | Artifact type | Slug | Sources | Last published commit |
| --- | --- | --- | --- | --- |
| Detent roadmap | Page (HTML, from `make roadmap-page`) | THq22MAqSJrDauRH39oWAe | founder/roadmap.md (built to build/roadmap.html) | |
| Detent progress | Data (dashboard) | 0e2dd42e-b068-4da7-9ff5-a4decc3333bb | founder/roadmap.json, founder/traceability.json | |
| Detent AI team | Team view page | e0c660a5-1fee-44ec-af9f-6b89c1f97b3e | founder/team.json | |
| Business docs | Docs | | founder/business-context.md, founder/brand.md, founder/status.md | |
| Design system | Design System | | design/tokens.json | |
