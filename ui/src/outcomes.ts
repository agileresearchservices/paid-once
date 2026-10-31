// One glyph per ledger outcome, shared by the diagram's ledger slots and the scoreboard, so a mark means the same
// thing in both places.
export const OUTCOME_GLYPH = {
  ok: "✓",
  duplicate: "×2",
  missing: "∅",
  unapproved: "!",
  denied: "—", // owed nothing, paid nothing: a human said no, or the ticket broke the refund policy
  settling: "…",
} as const;
