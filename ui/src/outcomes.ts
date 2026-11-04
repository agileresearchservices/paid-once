// One glyph per ledger outcome, used by the diagram's ledger slots.
export const OUTCOME_GLYPH = {
  ok: "✓",
  duplicate: "×2",
  missing: "∅", // approved, never refunded, past the settle window: counted lost
  unapproved: "!", // refunded with no approval on record: an invariant violation
  denied: "—", // owed nothing, paid nothing: a human said no, or the ticket broke the refund policy
} as const;

// An approved ticket whose stack has given up, with no refund for this long, is waiting on the audit's verdict, not in
// transit: `auditWait` says so on screen.
const UNPAID_AFTER_S = 5;

// Where a stack leaves a ticket it has given up on (STOPPED_STATES in paidonce/show/timeline.py).
const STOPPED_STATES = new Set(["failed", "terminated", "canceled", "timed out", "continued as new"]);

// The approved tickets whose stack has given up and that the audit is still giving time to show up in the ledger, and
// how long until it counts them lost. A ticket its stack is still working on (Temporal, queued for a worker after a
// restart) is not on this list: it is not about to be lost. Null while nothing qualifies.
export function auditWait(
  pending: Record<string, { since: number; verdict_at: number }> | undefined,
  dots: { ticket: string; state: string }[],
  now: number,
) {
  const stopped = new Set(dots.filter((d) => STOPPED_STATES.has(d.state)).map((d) => d.ticket));
  const late = Object.entries(pending ?? {}).filter(([tid, p]) => stopped.has(tid) && now - p.since >= UNPAID_AFTER_S);
  if (late.length === 0) return null;
  return { count: late.length, secs: Math.max(0, Math.ceil(Math.max(...late.map(([, p]) => p.verdict_at)) - now)) };
}
