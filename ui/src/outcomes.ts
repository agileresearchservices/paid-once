// One glyph per ledger outcome, used by the diagram's ledger slots.
export const OUTCOME_GLYPH = {
  ok: "✓",
  duplicate: "×2",
  missing: "∅",
  unapproved: "!",
  denied: "—", // owed nothing, paid nothing: a human said no, or the ticket broke the refund policy
} as const;
