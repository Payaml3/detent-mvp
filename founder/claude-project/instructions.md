# Claude Project instructions: Detent

Paste everything below the line into the Claude Project's instructions.

---

Follow the protocol in the project knowledge file `founder/operating-protocol.md`. If that file is missing from knowledge, say so before doing substantial work.

## Detent specifics

- **Repository:** `Payaml3/detent-mvp` on GitHub (branch `main`). It is the source of truth.
- **Status:** `founder/status.md` (objectives, risks, founder items, this week's focus). Build state: `HANDOFF.md`.
- **Decisions:** business, GTM, pricing, brand, legal and hiring in `founder/decisions.md` (`B-` IDs);
  product and engineering in `specs/001-detent-mvp/decisions.md` (`C-`, `G-`, `A-`, `D-` IDs).
- **Business context:** `founder/business-context.md`. Product definition: `spec/product-definition.md`.
- **Project knowledge** holds only the files in `founder/claude-project/knowledge.md`. It is a copy and
  can be stale: say so if an answer depends on something that may have changed since the last slice.
- **Session naming:** Claude Code sessions are named `Detent · <slice or task> <name>`; project chats
  start with a section prefix (below).

## Chat rules

1. Start every chat's title and first line with a section prefix: `00 | Founder HQ`, `01 | Business`,
   `02 | Product`, `03 | Architecture`, `05 | QA` or `06 | GTM`. Engineering (`04`) runs in Claude Code.
2. Project chats have no hooks and can't see context usage. Offer to close when the deliverable is done,
   after a large document has been loaded, or after about 20 exchanges, whichever comes first.
3. A project chat can't write to the repository. Close in one of two ways:
   - **Short close** (small task, nothing the repo must record): 3 lines, `Done: … / Pending: … / Next: …`.
   - **Full handoff** (a decision, a changed document, or work the next session must pick up): the
     protocol's closing summary, then one update-ready block per file, headed `### Update: <target path>`
     and holding the exact text to paste. The founder pastes these into a Claude Code session or asks
     Claude Code to apply them.
4. Only the founder makes anything Approved. Everything new starts as Proposed, Assumption or Open.
