// The ticket status icons: one badge per status, so a status reads by shape as well as colour. Drawn centred on (0, 0) with
// a radius of 8.5; the diagram places them (Dots) and the legend repeats them (LegendIcon), so the two can't drift apart.
// The glyphs echo the rest of the page: the person is the human in the diagram, the dash is the ledger's "denied" box.

export type TicketKind = "active" | "waiting" | "paying" | "failed" | "closed" | "done";

export const TICKET_ICON_R = 8.5;

export function TicketGlyph({ kind }: { kind: TicketKind }) {
  switch (kind) {
    case "active": // a quarter-ring that turns slowly
      return (
        <g>
          <circle className="ti-ring" r={6.5} />
          <path className="ti-arc ti-spin" d="M0,-6.5 A6.5,6.5 0 0 1 6.5,0" />
        </g>
      );
    case "waiting": // a person: head and shoulders
      return (
        <g>
          <circle className="ti-face" r={TICKET_ICON_R - 1} />
          <circle className="ti-ink-fill" cx={0} cy={-2.6} r={2.4} />
          <path className="ti-ink-fill" d="M-5,5 Q-5,0.4 0,0.4 Q5,0.4 5,5 Z" />
        </g>
      );
    case "paying": // money on its way: an arrow
      return (
        <g>
          <circle className="ti-fill-violet" r={TICKET_ICON_R} />
          <path className="ti-line ti-light" d="M-4.5,0 H4 M0.5,-3.8 L4.3,0 L0.5,3.8" />
        </g>
      );
    case "failed":
      return (
        <g>
          <circle className="ti-fill-critical" r={TICKET_ICON_R} />
          <path className="ti-line ti-light" d="M-3.6,-3.6 L3.6,3.6 M3.6,-3.6 L-3.6,3.6" />
        </g>
      );
    case "closed": // the same dash as the ledger's "denied, nothing owed"
      return (
        <g>
          <circle className="ti-fill-muted" r={TICKET_ICON_R} />
          <path className="ti-line ti-dark" d="M-4.2,0 H4.2" />
        </g>
      );
    case "done":
      return (
        <g>
          <circle className="ti-fill-good" r={TICKET_ICON_R} />
          <path className="ti-line ti-dark" d="M-4,0.4 L-1.2,3.2 L4.2,-3" />
        </g>
      );
  }
}

export function LegendIcon({ kind }: { kind: TicketKind }) {
  return (
    <svg className="lg-icon" viewBox="-10 -10 20 20" aria-hidden="true">
      <TicketGlyph kind={kind} />
    </svg>
  );
}
