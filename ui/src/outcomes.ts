// One glyph per ledger outcome, shared by the diagram's ledger slots and the scoreboard, so a mark means the same
// thing in both places.
export const OUTCOME_GLYPH = {
  ok: "✓",
  duplicate: "×2",
  missing: "∅",
  unapproved: "!",
  settling: "…",
} as const;
