// WEB-07: turns the deploy's /status.json (detent/api/status.py) into the rows the status page shows.
// The site is hosted apart from the deploy, so a failed fetch is itself an answer: the API can't be reached.
export const COMPONENTS = [
  { id: "sandbox_api", name: "Sandbox API" },
  { id: "dashboard", name: "Dashboard" },
  { id: "docs", name: "Docs" },
];

const LABELS = {
  operational: "Operational",
  down: "Down",
  not_monitored: "Not monitored yet",
  unreachable: "Can't be reached",
  unknown: "Unknown",
};

// body: the parsed JSON, or null when the fetch failed or the answer was not JSON.
export function statusRows(body) {
  const given = new Map((body?.components ?? []).map((c) => [c.id, c.status]));
  const rows = COMPONENTS.map(({ id, name }) => {
    let state;
    if (!body) state = id === "docs" ? "unknown" : "unreachable";
    else state = LABELS[given.get(id)] ? given.get(id) : "unknown";
    return { id, name, state, label: LABELS[state] };
  });
  const bad = rows.filter((r) => r.state === "down" || r.state === "unreachable");
  const summary = !body
    ? "We can't reach the sandbox API right now."
    : bad.length
      ? `${bad.map((r) => r.name).join(" and ")} ${bad.length > 1 ? "are" : "is"} having problems.`
      : "All monitored systems are operational.";
  return { rows, summary, checkedAt: body?.checked_at ?? null };
}
