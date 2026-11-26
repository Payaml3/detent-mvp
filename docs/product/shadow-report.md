# Free shadow report: definition (I5, O2.1)

Status: Proposed. Becomes Approved when the founder merges this PR. Stories: SHD-01, SHD-02, SHD-04 (Should, slice L). Source: `docs/product/operating-model.md` (lead to shadow report), D-15, D-24.

## Promise

One month of a platform's past payouts and deposits, decided under the platform's own rules. Nothing is sent. Report delivered within 5 working days of receiving the export. Free; no prices on the page ("Talk to us" for the paid plans, D-15).

## Input: the export

| Item | Rule |
|---|---|
| Format | CSV, one row per payment, one month, payouts and deposits |
| Required columns | platform payment ref, date and time (UTC), direction, amount (integer minor units or decimal with currency), currency, counterparty ref, rail used |
| Optional columns | the platform's own decision (approved, held, rejected), counterparty country, invoice or payee text, fee paid |
| Mapping | Column-mapping and validation report before any decision runs (SHD-01). Rows that fail validation are listed, not dropped silently |
| Personal data | Names and account identifiers hashed with a per-import salt on import; raw values never stored (SHD-04). DPA signed before the file is sent (landing page promise) |
| Rules | The platform's rules, written down in the policy workshop; where none exist, a labelled default rule set that the report says was used |

## Output: the report

HTML and PDF (SHD-02). Plain language, no raw hashes. Sections, in order:

1. **Summary (one screen).** Payments read, payments decided, period, rule set and version used, and a statement that nothing was sent.
2. **Decision mix.** Count and amount of would-execute, would-escalate and would-block, with the top reason for each.
3. **Agreement.** Where the platform supplied its own decision: how often Dekernai matched it, and the list of disagreements.
4. **Unsafe approvals.** Payments the platform approved that the rules would have blocked or escalated, each with the rule that applied. This is the headline section; it is a list, not a score.
5. **Unreconciled items.** Rows with no matching counterpart (e.g. a deposit with no payout, a duplicate ref).
6. **Simulated routing saving.** Fees under the rail Dekernai's routing would have chosen, against the fee paid. Shown only if fee and rail columns exist; labelled a simulation.
7. **Method and limits.** Rule version, what was and wasn't checked, and the honesty note: prototype, test data not used, no live rails touched.

## Honesty rules

- No claim of savings or fraud caught beyond what the export shows; each figure links to the rows behind it.
- The report is replayable: the same export and rule version give the same report (replay uses stored outputs, never a model call).
- Dekernai is described as agentic payment controls, never a payment provider.

## Done when (for this ticket)

- This definition is approved by merge.
- Engineering gap noted: SHD-01 and SHD-02 are not built (HTML/PDF export, column mapping). Until they are, the first report is assembled by hand from the existing import, decide and replay and checked against this format.
- Producing a report needs a real export from a platform. None exists yet; sourcing it is the growth role's I6 and a founder-led conversation. Not fabricated here.

## Open for the founder

- Is the 5-working-day promise realistic before SHD-02 is built (manual assembly)?
- Whether SHD-01, SHD-02 and SHD-04 move from slice L ahead of P2 to P4.
