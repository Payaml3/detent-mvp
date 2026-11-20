# Source documents

The repository cites these founder documents but doesn't contain them. Specs and backlog items were built
from one-line extracts (see A-01 in `specs/001-detent-mvp/decisions.md`). With the originals here, Claude can
check every Proposed item against the full text.

| Document | Cited by | Drop it here as |
|---|---|---|
| Product model (sections A1 to A7) | `backlog/model-items.yaml`, `spec/00` | `founder/sources/product-model.md` |
| Operating model (sections B1 to B8) | `backlog/model-items.yaml` | `founder/sources/operating-model.md` |
| MVP scope: launch criteria, section 3 flow, triage | `spec/00` (L1 to L8), `backlog/model-items.yaml` | `founder/sources/mvp-scope.md` |
| Developer portal spec | `spec/08` | `founder/sources/05-developer-portal.md` |
| `facts.md` (16 and 17 Nov), case study v2 | `spec/product-definition.md` | `founder/sources/facts.md` |

## How to add one

1. Export the document as Markdown (or paste it into a new `.md` file). PDF works too, but Markdown is cheaper to read.
2. Remove personal data, real client names and anything from a former employer.
3. Save it under the name above, commit it on a branch, and open a PR. Or ask Claude Code: "add this as founder/sources/<name>".
4. Then ask Claude to "check the Proposed items against founder/sources/<name>".
