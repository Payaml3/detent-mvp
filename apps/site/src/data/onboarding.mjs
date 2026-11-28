// The client journey (docs/product/client-journey.md, B-04): how a platform becomes a client. Six phases,
// each with an owner and an exit check. The client signs every exit check that moves money closer to being
// sent (phases 4 and 5). The site shows no shadow phase (founder, 2026-11-28). There is no free pre-sale report.
export const phases = [
  { n: 1, name: "Discovery", what: "A discovery call and a live demo. We check the fit together: your rails, your volumes and how your rules work today.",
    us: "Founder", you: "Head of payments", exit: "Both sides want to go ahead; NDA signed" },
  { n: 2, name: "Contract and due diligence", what: "Our due diligence on your business (KYB). Master agreement, data processing agreement and the clause that says you own the rules. We agree the pilot scope: rail, volumes and dates.",
    us: "Founder and counsel", you: "Legal and compliance", exit: "Contract and DPA signed; pilot scope agreed" },
  { n: 3, name: "Sandbox integration", what: "Your organisation, invites and sandbox keys. Your engineers integrate the API and webhooks, and trigger every path with the sandbox values.",
    us: "Engineering support", you: "Your engineers", exit: "Integration checklist passes in the sandbox", pilot: true },
  { n: 4, name: "Policy setup", what: "A policy workshop turns your rules into rule set v1: limits, counterparties and allowlists, agent mandates, approvers and backup owners, exception tiers and deadlines.",
    us: "Solutions lead", you: "Compliance lead, head of payments", exit: "Your compliance lead signs off rule set v1", pilot: true, sign: true },
  { n: 5, name: "Go-live", what: "Assist first, where your staff click every decision, then Auto within your approved rules, on one rail. Kill-switch owner, backup owners and the incident runbook are set before day one.",
    us: "Founder", you: "Head of payments", exit: "You sign each move: Assist, then Auto", pilot: true, sign: true, mode: "Assist → Auto" },
  { n: 6, name: "Scale", what: "More rails, routing and failover across them, reconciliation across every rail, support levels and a review every quarter.",
    us: "Solutions lead", you: "Head of payments", exit: "Reviewed each quarter", mode: "Orchestrate" },
];
export const plans = ["Pilot", "Growth", "Scale"];
