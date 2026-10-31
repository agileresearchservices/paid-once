import { OUTCOME_GLYPH } from "./outcomes";
import type { FlowDot, LaneId, ShowEvent, Snapshot } from "./types";

// One architecture diagram for both stacks. Faults land on the node they hit; dots show where each stack
// thinks each of this scene's tickets is. The payments node is filled from the ledger audit, never from a stack.

const W = 1464;
const H = 244;
const ROW: Record<LaneId, number> = { lane1: 30, lane2: 144 }; // node top per row
const NODE_H = 76;

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  sub: string;
  proc?: string; // process name in snap.processes, if a process backs this node
}

const NODES: Record<string, Box> = {
  lane1_api: { x: 60, y: ROW.lane1, w: 200, h: NODE_H, title: "Queue API", sub: "jobs table (SQLite)", proc: "lane1_api" },
  lane1_worker: { x: 320, y: ROW.lane1, w: 210, h: NODE_H, title: "Queue worker", sub: "agent · state in memory", proc: "lane1_worker" },
  temporal: { x: 60, y: ROW.lane2, w: 200, h: NODE_H, title: "Temporal server", sub: "durable history" },
  support_worker: { x: 320, y: ROW.lane2, w: 210, h: NODE_H, title: "Support worker", sub: "agent · SupportTicketWorkflow", proc: "support_worker" },
  endpoint: { x: 600, y: ROW.lane2, w: 190, h: NODE_H, title: "Nexus endpoint", sub: "payments-endpoint" },
  payments_worker: { x: 860, y: ROW.lane2, w: 210, h: NODE_H, title: "Payments worker", sub: "RefundWorkflow", proc: "payments_worker" },
  payments: { x: 1170, y: ROW.lane1, w: 294, h: ROW.lane2 + NODE_H - ROW.lane1, title: "Payments service + ledger", sub: "the audit reads this ledger", proc: "payments" },
};

const mid = (lane: LaneId) => ROW[lane] + NODE_H / 2;

// Wires: [from x, to x, row, id]. A wire is "busy" while a ticket is on it or in the node it feeds.
const WIRES: { id: string; x1: number; x2: number; lane: LaneId; label?: string }[] = [
  { id: "in_lane1", x1: 8, x2: 60, lane: "lane1" },
  { id: "lane1_api>lane1_worker", x1: 260, x2: 320, lane: "lane1" },
  { id: "lane1_worker>payments", x1: 530, x2: 1170, lane: "lane1", label: "plain HTTP" },
  { id: "in_lane2", x1: 8, x2: 60, lane: "lane2" },
  { id: "temporal>support_worker", x1: 260, x2: 320, lane: "lane2" },
  { id: "support_worker>endpoint", x1: 530, x2: 600, lane: "lane2" },
  { id: "endpoint>payments_worker", x1: 790, x2: 860, lane: "lane2", label: "Nexus" },
  { id: "payments_worker>payments", x1: 1070, x2: 1170, lane: "lane2" },
];

const FLASH_S = 2.5;
const CAPTION_S = 8;

function dotPos(at: string, i: number, lane: LaneId): { x: number; y: number; gone?: boolean } {
  if (at === "done") return { x: NODES.payments.x + 12, y: mid(lane), gone: true };
  const box = NODES[at];
  if (box) return { x: box.x + 16 + (i % 12) * 15, y: box.y + box.h - 13 - Math.floor(i / 12) * 15 };
  const wire = WIRES.find((w) => w.id === at);
  if (wire) return { x: wire.x1 + 40 + i * 18, y: mid(lane) };
  return { x: 0, y: mid(lane), gone: true };
}

function dotClass(d: FlowDot): string {
  if (d.at === "done") return "tdot done";
  if (d.state === "failed") return "tdot failed";
  if (d.state.startsWith("waiting")) return "tdot waiting";
  if (d.at.includes(">") || d.at === "payments_worker" || d.at === "endpoint") return "tdot paying";
  return "tdot active";
}

const EFFECT_MARK: Record<string, string> = { duplicate: "⚡ fed twice", stall: "⚡ reply held" };

function Dots({ lane, dots }: { lane: LaneId; dots: FlowDot[] }) {
  const slot: Record<string, number> = {};
  return (
    <>
      {[...dots]
        .sort((a, b) => a.ticket.localeCompare(b.ticket))
        .map((d) => {
          const i = (slot[d.at] = (slot[d.at] ?? -1) + 1);
          const p = dotPos(d.at, i, lane);
          return (
            <circle
              key={d.ticket}
              className={dotClass(d)}
              r={5.5}
              style={{ transform: `translate(${p.x}px, ${p.y}px)`, opacity: p.gone ? 0 : 1 }}
            >
              <title>{`${d.ticket}: ${d.state}`}</title>
            </circle>
          );
        })}
    </>
  );
}

// This scene's refunds as the ledger has them: one slot per ticket, filled when the audit sees the refund.
function Ledger({ lane, label, dots, tickets }: { lane: LaneId; label: string; dots: FlowDot[]; tickets: Record<string, string> }) {
  const ids = dots.map((d) => d.ticket).sort();
  const x0 = NODES.payments.x + 16;
  const y = mid(lane) + 8;
  return (
    <g className="ledger">
      <text x={x0} y={y + 13} className="n-sub">{label}</text>
      {ids.length === 0 && <text x={x0 + 82} y={y + 13} className="n-sub">no tickets this scene</text>}
      {ids.map((id, i) => {
        const st = tickets[id] ?? "waiting";
        const x = x0 + 82 + i * 26;
        // Same colours as the scoreboard: twice and unapproved are critical (red), never refunded is serious (orange).
        const cls = st === "ok" ? "slot ok" : st === "duplicate" || st === "unapproved" ? "slot bad" : st === "missing" ? "slot missing" : "slot";
        const glyph = st === "ok" || st === "duplicate" || st === "missing" || st === "unapproved" ? OUTCOME_GLYPH[st] : "";
        return (
          <g key={id} className={cls}>
            <rect x={x} y={y} width={22} height={18} rx={4} />
            <text x={x + 11} y={y + 13.5} textAnchor="middle">{glyph}</text>
            <title>{`${id}: ${st === "ok" ? "refunded once" : st === "duplicate" ? "refunded more than once" : st}`}</title>
          </g>
        );
      })}
    </g>
  );
}

export function Diagram({ snap, scene }: { snap: Snapshot; scene: string | null }) {
  const run = scene ? snap.scene_runs?.[scene] : undefined;
  const onScreen = scene != null && snap.current === scene;
  const flow: Record<LaneId, FlowDot[]> = onScreen && snap.flow ? snap.flow : { lane1: [], lane2: [] };

  // Faults from this scene's latest run: where they landed, and whether they just happened.
  const faults: ShowEvent[] = run
    ? snap.events.filter((e) => e.kind === "fault" && e.ts >= run.started_at && (e.scene === scene || e.scene?.startsWith(`${scene}_`)))
    : [];
  const latest = faults[faults.length - 1];
  const caption = latest && snap.now - latest.ts < CAPTION_S ? latest : undefined;
  const hitNow = new Set(faults.filter((e) => snap.now - e.ts < FLASH_S).flatMap((e) => e.target ?? []));
  const marks: Record<string, string> = {};
  for (const e of faults) for (const t of e.target ?? []) if (e.effect && EFFECT_MARK[e.effect]) marks[t] = EFFECT_MARK[e.effect];
  for (const [p, n] of Object.entries(run?.kills ?? {})) marks[p] = `⚡ killed ${n === 1 ? "once" : `${n} times`}`;
  const dupNow = faults.some((e) => e.effect === "duplicate" && snap.now - e.ts < FLASH_S + 1);

  const busy = new Set<string>();
  for (const lane of ["lane1", "lane2"] as LaneId[])
    for (const d of flow[lane]) {
      if (d.at.includes(">")) busy.add(d.at);
      if (d.at === "payments_worker") busy.add("payments_worker>payments");
      if (d.at === "endpoint") busy.add("support_worker>endpoint");
    }

  const latency = (lane: LaneId) => snap.faults?.[lane]?.latency_s ?? 0;
  const stall = snap.faults?.lane1?.mode === "commit_then_stall" ? snap.faults.lane1 : snap.faults?.lane2?.mode === "commit_then_stall" ? snap.faults.lane2 : undefined;
  const audit = (lane: LaneId) => snap.audit[lane]?.tickets ?? {};

  return (
    <section className="diagram" aria-label="Architecture, with where each fault lands">
      <div className="diagram-head">
        {scene == null ? (
          <span className="legend">
            <span>Same tickets, same human approver, same payments service. Only the architecture differs.</span>
          </span>
        ) : caption ? (
          <span className="fault-caption" role="status">{caption.msg}</span>
        ) : (
          <span className="legend">
            <span><i className="lg active" /> where each stack thinks a ticket is</span>
            <span><i className="lg waiting" /> waiting for a human</span>
            <span><i className="lg paying" /> refund in flight</span>
            <span className="lg-slots">
              ledger {OUTCOME_GLYPH.ok} once · {OUTCOME_GLYPH.duplicate} twice · {OUTCOME_GLYPH.missing} never
            </span>
            <span className="lg-stage">⏱ slowed on purpose, so a fault lands mid-call</span>
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Job queue and Temporal + Nexus, both calling the payments service">
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" className="arrowhead" />
          </marker>
        </defs>

        <rect className="team" x={822} y={4} width={W - 824} height={H - 8} rx={14} />
        <text className="row-label" x={838} y={20}>PAYMENTS TEAM</text>
        <text className="row-label" x={60} y={20}>JOB QUEUE</text>
        <text className="row-label" x={60} y={134}>TEMPORAL + NEXUS · SUPPORT TEAM</text>

        {WIRES.map((w) => (
          <g key={w.id}>
            <line
              className={busy.has(w.id) ? "wire busy" : "wire"}
              x1={w.x1}
              x2={w.x2 - 3}
              y1={mid(w.lane)}
              y2={mid(w.lane)}
              markerEnd="url(#arrow)"
            />
            {w.label && (
              <text className="wire-label" x={(w.x1 + w.x2) / 2} y={mid(w.lane) - 8} textAnchor="middle">{w.label}</text>
            )}
          </g>
        ))}

        {(["lane1", "lane2"] as LaneId[]).map(
          (lane) =>
            latency(lane) > 0 && (
              <text key={lane} className="staged" x={NODES.payments.x - 10} y={mid(lane) + 20} textAnchor="end">
                ⏱ +{latency(lane)}s
              </text>
            ),
        )}

        {dupNow && (
          <>
            <g className="packet" style={{ ["--dx" as string]: "52px" }}>
              <rect x={258} y={mid("lane1") - 11} width={30} height={22} rx={5} />
              <text x={273} y={mid("lane1") + 5} textAnchor="middle">×2</text>
            </g>
            <g className="packet" style={{ ["--dx" as string]: "46px" }}>
              <rect x={6} y={mid("lane2") - 11} width={30} height={22} rx={5} />
              <text x={21} y={mid("lane2") + 5} textAnchor="middle">×2</text>
            </g>
          </>
        )}

        {Object.entries(NODES).map(([id, b]) => {
          const p = b.proc ? snap.processes[b.proc] : undefined;
          const down = p ? !p.alive : false;
          const cls = ["node", down && "down", hitNow.has(id) && "hit", id === "endpoint" && "door"].filter(Boolean).join(" ");
          // Payments' bottom strip holds the Temporal ledger row, so its badge sits under the Job queue row instead.
          const badgeY = id === "payments" ? b.y + 72 : b.y + b.h - 27;
          return (
            <g key={id} className={cls}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={10} />
              <text className="n-title" x={b.x + 14} y={b.y + 22}>{b.title}</text>
              <text className="n-sub" x={b.x + 14} y={b.y + 40}>{b.sub}</text>
              {p && !down && (
                <text className="n-state" x={b.x + b.w - 12} y={b.y + 22} textAnchor="end">UP</text>
              )}
              {/* Down gets its own solid badge on the node's bottom strip: on the title line it ran into the title */}
              {down && (
                <g className="n-down">
                  <rect x={b.x + 14} y={badgeY} width={152} height={21} rx={4} />
                  <text x={b.x + 22} y={badgeY + 15}>DOWN · restarting</text>
                </g>
              )}
              {/* On the node's top border, like a fieldset legend: above it, it ran into the row labels */}
              {marks[id] && (
                <text className="n-mark" x={b.x + b.w - 10} y={b.y + 5} textAnchor="end">{marks[id]}</text>
              )}
              {hitNow.has(id) && (
                <text className="bolt" x={b.x + b.w / 2} y={b.y + b.h / 2 + 12} textAnchor="middle">⚡</text>
              )}
            </g>
          );
        })}

        {stall && stall.remaining > 0 && (
          <text className={hitNow.has("payments") ? "stall now" : "stall"} x={NODES.payments.x + 16} y={(mid("lane1") + mid("lane2")) / 2 + 14}>
            ⏸ commits, then holds the reply {stall.delay_s}s ({stall.remaining} left)
          </text>
        )}
        {scene != null && (
          <>
            <Ledger lane="lane1" label="Queue" dots={flow.lane1} tickets={audit("lane1")} />
            <Ledger lane="lane2" label="Temporal" dots={flow.lane2} tickets={audit("lane2")} />
          </>
        )}

        <Dots lane="lane1" dots={flow.lane1} />
        <Dots lane="lane2" dots={flow.lane2} />
      </svg>
    </section>
  );
}
