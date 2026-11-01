import { OUTCOME_GLYPH } from "./outcomes";
import type { FlowDot, LaneId, ShowEvent, Snapshot } from "./types";

// One architecture diagram for both stacks. Tickets come in from the helpdesk on the left; a human approves or denies
// at the API / Temporal column; a denied ticket goes back to the helpdesk with no refund. Faults land on the node they
// hit; dots show where each stack thinks each of this scene's tickets is. The payments node is filled from the ledger
// audit, never from a stack.

const W = 1464;
const H = 270;
const ROW: Record<LaneId, number> = { lane1: 30, lane2: 170 }; // node top per row; the gap holds the human
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
  helpdesk: { x: 2, y: ROW.lane1, w: 116, h: ROW.lane2 + NODE_H - ROW.lane1, title: "Helpdesk", sub: "support tickets" },
  lane1_api: { x: 158, y: ROW.lane1, w: 180, h: NODE_H, title: "Queue API", sub: "jobs table (SQLite)", proc: "lane1_api" },
  lane1_worker: { x: 378, y: ROW.lane1, w: 236, h: NODE_H, title: "Queue worker", sub: "agent · state in memory", proc: "lane1_worker" },
  temporal: { x: 158, y: ROW.lane2, w: 180, h: NODE_H, title: "Temporal server", sub: "durable history" },
  support_worker: { x: 378, y: ROW.lane2, w: 236, h: NODE_H, title: "Support worker", sub: "agent · SupportTicketWorkflow", proc: "support_worker" },
  endpoint: { x: 650, y: ROW.lane2, w: 150, h: NODE_H, title: "Nexus endpoint", sub: "payments-endpoint" },
  payments_worker: { x: 860, y: ROW.lane2, w: 210, h: NODE_H, title: "Payments worker", sub: "RefundWorkflow", proc: "payments_worker" },
  payments: { x: 1170, y: ROW.lane1, w: 294, h: ROW.lane2 + NODE_H - ROW.lane1, title: "Payments service + ledger", sub: "the audit reads this ledger", proc: "payments" },
};

const mid = (lane: LaneId) => ROW[lane] + NODE_H / 2;

// The human reviews proposals where approvals actually land: the Queue API and the Temporal server.
const HUMAN = { x: 163, y: 126, w: 170, h: 24 };
const HUMAN_X = HUMAN.x + HUMAN.w / 2;

// Wires: [from x, to x, row, id]. A wire is "busy" while a ticket is on it or in the node it feeds.
const WIRES: { id: string; x1: number; x2: number; lane: LaneId; label?: string }[] = [
  { id: "helpdesk>lane1_api", x1: 118, x2: 158, lane: "lane1" },
  { id: "lane1_api>lane1_worker", x1: 338, x2: 378, lane: "lane1" },
  { id: "lane1_worker>payments", x1: 614, x2: 1170, lane: "lane1", label: "HTTPS" },
  { id: "helpdesk>temporal", x1: 118, x2: 158, lane: "lane2" },
  { id: "temporal>support_worker", x1: 338, x2: 378, lane: "lane2" },
  { id: "support_worker>endpoint", x1: 614, x2: 650, lane: "lane2" },
  { id: "endpoint>payments_worker", x1: 800, x2: 860, lane: "lane2", label: "Nexus" },
  { id: "payments_worker>payments", x1: 1070, x2: 1170, lane: "lane2" },
];

const FLASH_S = 2.5;
const CAPTION_S = 8;

function dotPos(at: string, i: number, lane: LaneId): { x: number; y: number; gone?: boolean } {
  if (at === "done") return { x: NODES.payments.x + 12, y: mid(lane), gone: true };
  // Closed with no refund: back in the helpdesk, in its lane's half.
  if (at === "closed") return { x: NODES.helpdesk.x + 16 + (i % 6) * 15, y: ROW[lane] + NODE_H - 13 - Math.floor(i / 6) * 15 };
  const box = NODES[at];
  if (box) return { x: box.x + 16 + (i % 10) * 15, y: box.y + box.h - 13 - Math.floor(i / 10) * 15 };
  const wire = WIRES.find((w) => w.id === at);
  if (wire) return { x: wire.x1 + 40 + i * 18, y: mid(lane) };
  return { x: 0, y: mid(lane), gone: true };
}

function dotClass(d: FlowDot): string {
  if (d.at === "done") return "tdot done";
  if (d.at === "closed") return "tdot closed";
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
        const x = x0 + 82 + i * 24;
        // Same colours as the scoreboard: twice and unapproved are critical (red), never refunded is serious (orange).
        // Owed nothing and paid nothing (a denial, or a ticket outside the policy) is neutral.
        const owedNothing = st === "rejected" || st === "declined";
        const cls = st === "ok" ? "slot ok" : st === "duplicate" || st === "unapproved" ? "slot bad" : st === "missing" ? "slot missing" : owedNothing ? "slot none" : "slot";
        const glyph = owedNothing ? OUTCOME_GLYPH.denied : st === "ok" || st === "duplicate" || st === "missing" || st === "unapproved" ? OUTCOME_GLYPH[st] : "";
        const what = st === "ok" ? "refunded once" : st === "duplicate" ? "refunded more than once" : owedNothing ? "denied, nothing owed" : st;
        return (
          <g key={id} className={cls}>
            <rect x={x} y={y} width={22} height={18} rx={4} />
            <text x={x + 11} y={y + 13.5} textAnchor="middle">{glyph}</text>
            <title>{`${id}: ${what}`}</title>
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
  const humanNow =
    run != null &&
    snap.events.some((e) => e.kind === "human" && e.ts >= run.started_at && snap.now - e.ts < FLASH_S + 1 && (e.scene === scene || e.scene?.startsWith(`${scene}_`)));

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
            {/* Two keys, two sources: the dots are where each stack thinks a ticket is; the boxes are what the payments
                ledger actually paid. Each ledger key is a small copy of the real slot, so it reads as the same mark. */}
            <span className="lg-group">
              <b>Ticket</b>
              <span><i className="lg active" /> in progress</span>
              <span><i className="lg waiting" /> waiting for a human</span>
              <span><i className="lg paying" /> refund in flight</span>
              <span><i className="lg failed" /> job failed</span>
              <span><i className="lg closed" /> denied</span>
            </span>
            <span className="lg-group">
              <b>Ledger</b>
              <span><i className="lg-slot ok">{OUTCOME_GLYPH.ok}</i> paid once</span>
              <span><i className="lg-slot bad">{OUTCOME_GLYPH.duplicate}</i> paid twice</span>
              <span><i className="lg-slot missing">{OUTCOME_GLYPH.missing}</i> owed, never paid</span>
              <span><i className="lg-slot none">{OUTCOME_GLYPH.denied}</i> denied, nothing owed</span>
            </span>
            <span className="lg-stage">⏱ slowed on purpose, so a fault lands mid-call</span>
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Queue + LangGraph and Temporal + Nexus, both calling the payments service">
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" className="arrowhead" />
          </marker>
        </defs>

        <rect className="team" x={822} y={4} width={W - 824} height={H - 8} rx={14} />
        <text className="row-label" x={838} y={20}>PAYMENTS TEAM</text>
        <text className="row-label" x={158} y={20}>QUEUE + LANGGRAPH</text>
        <text className="row-label" x={HUMAN.x + HUMAN.w + 18} y={ROW.lane2 - 9}>TEMPORAL + NEXUS · SUPPORT TEAM</text>

        <g className={humanNow ? "human now" : "human"}>
          <line className="wire" x1={HUMAN_X} x2={HUMAN_X} y1={HUMAN.y} y2={ROW.lane1 + NODE_H + 3} markerEnd="url(#arrow)" />
          <line className="wire" x1={HUMAN_X} x2={HUMAN_X} y1={HUMAN.y + HUMAN.h} y2={ROW.lane2 - 3} markerEnd="url(#arrow)" />
          <rect x={HUMAN.x} y={HUMAN.y} width={HUMAN.w} height={HUMAN.h} rx={12} />
          <text x={HUMAN_X} y={HUMAN.y + 16.5} textAnchor="middle">Human: approve / deny</text>
        </g>
        <text className="n-sub" x={NODES.lane1_worker.x + 14} y={HUMAN.y + 17}>both agents: policy rules, then Claude</text>

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
            <g className="packet" style={{ ["--dx" as string]: "32px" }}>
              <rect x={336} y={mid("lane1") - 11} width={30} height={22} rx={5} />
              <text x={351} y={mid("lane1") + 5} textAnchor="middle">×2</text>
            </g>
            {/* Temporal's duplicate is the human's decision signal, replayed: it comes down from the review */}
            <g className="packet" style={{ ["--dx" as string]: "0px", ["--dy" as string]: "24px" }}>
              <rect x={HUMAN_X + 8} y={HUMAN.y + 2} width={30} height={22} rx={5} />
              <text x={HUMAN_X + 23} y={HUMAN.y + 18} textAnchor="middle">×2</text>
            </g>
          </>
        )}

        {Object.entries(NODES).map(([id, b]) => {
          const p = b.proc ? snap.processes[b.proc] : undefined;
          const down = p ? !p.alive : false;
          const cls = ["node", down && "down", hitNow.has(id) && "hit", id === "endpoint" && "door"].filter(Boolean).join(" ");
          // Payments' bottom strip holds the Temporal ledger row, so its badge sits under the Queue + LangGraph row instead.
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
