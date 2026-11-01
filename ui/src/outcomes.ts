// One glyph per ledger outcome, used by the diagram's ledger slots.
export const OUTCOME_GLYPH = {
  ok: "✓",
  duplicate: "×2",
  missing: "∅",
  unapproved: "!",
  denied: "—", // owed nothing, paid nothing: a human said no, or the ticket broke the refund policy
} as const;

// A ticket approved this long ago with no refund is waiting on something, not just in transit: say so on screen.
const UNPAID_AFTER_S = 5;

// The approved tickets the audit is still giving time to show up in the ledger (past the first few seconds), and how long
// until it counts them lost. Null while nothing is waiting that long.
export function auditWait(pending: Record<string, { since: number; verdict_at: number }> | undefined, now: number) {
  const late = Object.values(pending ?? {}).filter((p) => now - p.since >= UNPAID_AFTER_S);
  if (late.length === 0) return null;
  return { count: late.length, secs: Math.max(0, Math.ceil(Math.max(...late.map((p) => p.verdict_at)) - now)) };
}
