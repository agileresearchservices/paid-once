import type { Topology } from "./types";

// Why Nexus, in two pictures, before the run. Without it, support's code reaches across the team line into payments'
// internals (namespace, task queue, workflow type) and has to make the call reliable itself. With it, support makes one
// call to one endpoint and payments owns everything behind it. Names come from the topology, so they match the code.
// Static: nothing here moves with the run. The viewBox is about one unit per CSS px at a 1512 px window.

const W = 1440;
const H = 186;
const CARD_W = 700;
const BOX_Y = 52;
const BOX_H = 96;
const MID = BOX_Y + BOX_H / 2;

function Box({ x, w, label, cls = "" }: { x: number; w: number; label: string; cls?: string }) {
  return (
    <g className={`why-box ${cls}`}>
      <rect x={x} y={BOX_Y} width={w} height={BOX_H} rx={10} />
      <text x={x + w / 2} y={MID + 7} textAnchor="middle">
        {label}
      </text>
    </g>
  );
}

const LEAKS = ["namespace", "task queue", "workflow type", "retries & timeouts"];

export function NexusWhy({ t }: { t: Topology }) {
  const wo = 0; // the "without" card's left edge
  const wi = W - CARD_W; // the "with" card's left edge
  return (
    <svg className="why" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Without Nexus and with Nexus">
      <defs>
        <marker id="why-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head" />
        </marker>
        <marker id="why-arrow-good" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head good" />
        </marker>
      </defs>

      {/* Without: four things support has to know, each crossing the team line */}
      <g className="why-card without">
        <rect className="card" x={wo + 1} y={1} width={CARD_W - 2} height={H - 2} rx={12} />
        <text className="why-title" x={wo + 20} y={34}>
          ✕ Without Nexus
        </text>
        <Box x={wo + 20} w={130} label="Support" />
        <Box x={wo + CARD_W - 150} w={130} label="Payments" />
        <line className="team-line" x1={wo + CARD_W / 2} x2={wo + CARD_W / 2} y1={BOX_Y - 8} y2={BOX_Y + BOX_H + 8} />
        {LEAKS.map((label, i) => {
          const y = BOX_Y + 15 + i * 22;
          return (
            <g key={label}>
              <line className="why-wire leak" x1={wo + 150} x2={wo + CARD_W - 153} y1={y} y2={y} markerEnd="url(#why-arrow)" />
              <text className="why-leak" x={wo + CARD_W / 2} y={y + 5} textAnchor="middle">
                {label}
              </text>
            </g>
          );
        })}
        <text className="why-caption" x={wo + 20} y={H - 14}>
          Support knows payments' insides and makes each call reliable itself.
        </text>
      </g>

      {/* With: one call to one endpoint */}
      <g className="why-card with">
        <rect className="card" x={wi + 1} y={1} width={CARD_W - 2} height={H - 2} rx={12} />
        <text className="why-title" x={wi + 20} y={34}>
          ✓ With Nexus
        </text>
        <Box x={wi + 20} w={120} label="Support" />
        <g className="why-box door">
          <rect x={wi + 270} y={BOX_Y} width={190} height={BOX_H} rx={10} />
          <text x={wi + 365} y={MID - 6} textAnchor="middle">
            Nexus endpoint
          </text>
          <text className="mono" x={wi + 365} y={MID + 20} textAnchor="middle">
            {t.endpoint}
          </text>
        </g>
        <Box x={wi + CARD_W - 140} w={120} label="Payments" />
        <line className="why-wire one" x1={wi + 140} x2={wi + 267} y1={MID} y2={MID} markerEnd="url(#why-arrow-good)" />
        <text className="why-op mono" x={wi + 205} y={MID - 12} textAnchor="middle">
          {t.operation}
        </text>
        <line className="why-wire one" x1={wi + 460} x2={wi + CARD_W - 143} y1={MID} y2={MID} markerEnd="url(#why-arrow-good)" />
        <text className="why-caption" x={wi + 20} y={H - 14}>
          One durable call. Payments owns everything behind the endpoint.
        </text>
      </g>
    </svg>
  );
}
