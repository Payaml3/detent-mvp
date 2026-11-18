// "What goes wrong?": the same payment, through the real states (spec/02, spec/06).
// Pure data and one function, shared by the page (no-JS text) and the live demonstration.

export const PAYMENT_ID = "pay_01JDQ3H7ZK4M9V2B8XWT6CNR5E";

const s = (status, event, extra = {}) => ({ status, event, paymentId: PAYMENT_ID, ...extra });

export const SCENARIOS = [
  {
    id: "approve",
    label: "It needs a human",
    summary: "First payment to a new supplier, above the auto limit. A reviewer approves; the rules run again before anything moves.",
    steps: [
      s("RECEIVED", "intent proposed by the AP agent, inside its mandate"),
      s("ESCALATED", "FIRST_PAYMENT, ABOVE_AUTO_LIMIT: $18,500 against a $10,000 limit. Case opened, owner Sam, 2 h deadline"),
      s("ESCALATED", "approved by Sam with a reason; raw facts read first"),
      s("READY", "policy re-run", { note: "active rule version: EXECUTE" }),
      s("SUBMITTED", "sent once on Base Sepolia", { rail: "Base Sepolia" }),
      s("CONFIRMED", "receipt status 1 after 3 confirmations", { rail: "Base Sepolia", transfer: true }),
    ],
  },
  {
    id: "timeout",
    label: "The rail times out",
    summary: "The transaction reached the chain but the answer was lost. A timeout is UNKNOWN, never FAILED, and nothing is resent.",
    steps: [
      s("RECEIVED", "intent received from the platform"),
      s("READY", "decision EXECUTE"),
      s("SUBMITTED", "sent on Base Sepolia", { rail: "Base Sepolia" }),
      s("UNKNOWN", "response lost: the outcome is unknown, so nothing is resent", { rail: "Base Sepolia" }),
      s("UNKNOWN", "polled by transaction hash at 5 s and 15 s: no receipt yet", { rail: "Base Sepolia" }),
      s("CONFIRMED", "receipt found: one transfer, same payment ID", { rail: "Base Sepolia", transfer: true }),
    ],
  },
  {
    id: "reverted",
    label: "The transaction reverts",
    summary: "A definitive technical failure. The payment fails over to another rail under the same ID, because the platform allowed a network switch.",
    steps: [
      s("RECEIVED", "intent received, network switch allowed"),
      s("READY", "decision EXECUTE"),
      s("SUBMITTED", "sent on Base Sepolia", { rail: "Base Sepolia" }),
      s("FAILED", "receipt status 0: TECHNICAL_FINAL", { rail: "Base Sepolia" }),
      s("READY", "failover: attempt 2, same payment ID"),
      s("SUBMITTED", "sent on Ethereum Sepolia", { rail: "Ethereum Sepolia" }),
      s("CONFIRMED", "receipt status 1: one transfer", { rail: "Ethereum Sepolia", transfer: true }),
    ],
  },
  {
    id: "screening",
    label: "The payee is on a list",
    summary: "A screening hit blocks the payment. A block is final: it is never approved, retried, re-routed or resubmitted.",
    steps: [
      s("RECEIVED", "intent received"),
      s("BLOCKED", "SCREENING_HIT: the address is on the screening list"),
      s("BLOCKED", "approval attempted: refused, the payment is blocked"),
    ],
  },
  {
    id: "killswitch",
    label: "Someone pulls the kill switch",
    summary: "The kill switch is checked inside the lock before every send. Only the payments lead can release it, and the rules run again first.",
    steps: [
      s("RECEIVED", "intent received"),
      s("READY", "decision EXECUTE"),
      s("HELD", "kill switch engaged by on-call: nothing is sent"),
      s("READY", "released by the payments lead; policy re-run: EXECUTE"),
      s("SUBMITTED", "sent once on Base Sepolia", { rail: "Base Sepolia" }),
      s("CONFIRMED", "one transfer", { rail: "Base Sepolia", transfer: true }),
    ],
  },
];

export function runScenario(id) {
  const sc = SCENARIOS.find((x) => x.id === id);
  if (!sc) throw new Error(`unknown scenario ${id}`);
  const transfers = sc.steps.filter((st) => st.transfer).length;
  return { ...sc, transfers };
}
