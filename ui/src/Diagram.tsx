import { useState } from "react";
import { OUTCOME_GLYPH } from "./outcomes";
import type { FlowDot, LaneId, ShowEvent, Snapshot } from "./types";

// One architecture diagram for both stacks. Tickets come in from the helpdesk on the left; a human approves or denies
// at the API / Temporal column; a denied ticket goes back to the helpdesk with no refund. Faults land on the node they
// hit; dots show where each stack thinks each of this scene's tickets is. The payments node is filled from the ledger
// audit, never from a stack.

const W = 1464;
const H = 298;
const ROW: Record<LaneId, number> = { lane1: 30, lane2: 184 }; // node top per row; the gap holds the human
const NODE_H = 90; // three text lines (title, what it is, what the agent does) with the ticket dots below them

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  sub: string;
  note?: string; // a third line, hidden while the node is down (the DOWN badge takes that spot)
  proc?: string; // process name in snap.processes, if a process backs this node
}

const NODES: Record<string, Box> = {
  helpdesk: { x: 2, y: ROW.lane1, w: 116, h: ROW.lane2 + NODE_H - ROW.lane1, title: "Helpdesk", sub: "support tickets" },
  lane1_api: { x: 158, y: ROW.lane1, w: 180, h: NODE_H, title: "Queue API", sub: "jobs table (SQLite)", proc: "lane1_api" },
  lane1_worker: { x: 378, y: ROW.lane1, w: 236, h: NODE_H, title: "Queue worker", sub: "agent · state in memory", note: "policy rules, then Claude", proc: "lane1_worker" },
  temporal: { x: 158, y: ROW.lane2, w: 180, h: NODE_H, title: "Temporal server", sub: "durable history" },
  support_worker: { x: 378, y: ROW.lane2, w: 236, h: NODE_H, title: "Support worker", sub: "agent · SupportTicketWorkflow", note: "policy rules, then Claude", proc: "support_worker" },
  endpoint: { x: 650, y: ROW.lane2, w: 150, h: NODE_H, title: "Nexus endpoint", sub: "payments-endpoint" },
  payments_worker: { x: 860, y: ROW.lane2, w: 210, h: NODE_H, title: "Payments worker", sub: "RefundWorkflow", proc: "payments_worker" },
  payments: { x: 1170, y: ROW.lane1, w: 294, h: ROW.lane2 + NODE_H - ROW.lane1, title: "Payments service + ledger", sub: "the audit reads this ledger", proc: "payments" },
};

const mid = (lane: LaneId) => ROW[lane] + NODE_H / 2;

// The human reviews proposals where approvals actually land: the Queue API and the Temporal server.
const HUMAN = { x: 234, y: 138, w: 28, h: 28 }; // a round badge with a person in it
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

const EFFECT_MARK: Record<string, string> = { duplicate: "⚡ delivered twice", stall: "⚡ goes quiet" };

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

// Where each lane's ledger sits inside the Payments box: its name, the row of boxes, then one line with the result.
const LEDGER_Y: Record<LaneId, { label: number; slots: number; tally: number }> = {
  lane1: { label: 98, slots: 106, tally: 150 },
  lane2: { label: 200, slots: 208, tally: 252 },
};
const SLOT_W = 24;
const SLOT_PITCH = 28;

interface Hint {
  x: number;
  y: number;
  text: string;
}

// What a box means, shown on hover. The boxes carry no key: the presenter points at one and this says what it is.
function slotMeaning(st: string): string {
  if (st === "ok") return "paid once";
  if (st === "duplicate") return "paid twice";
  if (st === "missing") return "owed, never paid";
  if (st === "unapproved") return "paid with no approval";
  if (st === "rejected" || st === "declined") return "denied, nothing owed";
  return "not paid yet";
}

// The result in words, so the outcome reads without decoding the boxes: problems first, or "all N paid once".
function tallyText(statuses: string[]): { text: string; bad: boolean } | null {
  const n = (st: string) => statuses.filter((x) => x === st).length;
  const parts = [
    [n("duplicate"), "paid twice"],
    [n("missing"), "owed"],
    [n("unapproved"), "unapproved"],
  ].filter(([c]) => (c as number) > 0);
  if (parts.length) return { text: parts.map(([c, t]) => `${c} ${t}`).join(" · "), bad: true };
  const ok = n("ok");
  const open = statuses.filter((x) => x === "waiting" || x === "settling").length;
  return ok > 0 && open === 0 ? { text: `all ${ok} paid once`, bad: false } : null;
}

// This scene's refunds as the ledger has them: one box per ticket, filled when the audit sees the refund.
function Ledger({
  lane,
  label,
  dots,
  tickets,
  onHint,
}: {
  lane: LaneId;
  label: string;
  dots: FlowDot[];
  tickets: Record<string, string>;
  onHint: (h: Hint | null) => void;
}) {
  const ids = dots.map((d) => d.ticket).sort();
  const x0 = NODES.payments.x + 16;
  const at = LEDGER_Y[lane];
  const statuses = ids.map((id) => tickets[id] ?? "waiting");
  const tally = tallyText(statuses);
  return (
    <g className="ledger">
      <text x={x0} y={at.label} className="ledger-name">{label}</text>
      {ids.length === 0 && <text x={x0} y={at.slots + 16} className="n-sub">no tickets this scene</text>}
      {ids.map((id, i) => {
        const st = statuses[i];
        const x = x0 + i * SLOT_PITCH;
        // Same colours as the scoreboard: twice and unapproved are critical (red), never refunded is serious (orange).
        // Owed nothing and paid nothing (a denial, or a ticket outside the policy) is neutral.
        const owedNothing = st === "rejected" || st === "declined";
        const cls = st === "ok" ? "slot ok" : st === "duplicate" || st === "unapproved" ? "slot bad" : st === "missing" ? "slot missing" : owedNothing ? "slot none" : "slot";
        const glyph = owedNothing ? OUTCOME_GLYPH.denied : st === "ok" || st === "duplicate" || st === "missing" || st === "unapproved" ? OUTCOME_GLYPH[st] : "";
        return (
          <g
            key={id}
            className={cls}
            onMouseEnter={() => onHint({ x: x + SLOT_W / 2, y: at.slots, text: slotMeaning(st) })}
            onMouseLeave={() => onHint(null)}
          >
            <rect x={x} y={at.slots} width={SLOT_W} height={22} rx={4} />
            <text x={x + SLOT_W / 2} y={at.slots + 16.5} textAnchor="middle">{glyph}</text>
          </g>
        );
      })}
      {tally && (
        <text x={x0} y={at.tally} className={tally.bad ? "tally bad" : "tally good"}>{tally.text}</text>
      )}
    </g>
  );
}

// A large tooltip above the box under the pointer, clamped to the diagram so it never runs off the edge.
function HintBubble({ hint }: { hint: Hint }) {
  const w = hint.text.length * 10.5 + 24;
  const x = Math.min(W - w - 4, Math.max(4, hint.x - w / 2));
  return (
    <g className="hint" pointerEvents="none">
      <rect x={x} y={hint.y - 38} width={w} height={30} rx={6} />
      <text x={x + w / 2} y={hint.y - 17} textAnchor="middle">{hint.text}</text>
    </g>
  );
}

export function Diagram({ snap, scene }: { snap: Snapshot; scene: string | null }) {
  const [hint, setHint] = useState<Hint | null>(null);
  const run = scene ? snap.scene_runs?.[scene] : undefined;
  const onScreen = scene != null && snap.current === scene;
  const flow: Record<LaneId, FlowDot[]> = onScreen && snap.flow ? snap.flow : { lane1: [], lane2: [] };

  // Faults from this scene's latest run: where they landed, and whether they just happened.
  const faults: ShowEvent[] = run
    ? snap.events.filter((e) => e.kind === "fault" && e.ts >= run.started_at && (e.scene === scene || e.scene?.startsWith(`${scene}_`)))
    : [];
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
  const audit = (lane: LaneId) => snap.audit[lane]?.tickets ?? {};

  return (
    <section className="diagram" aria-label="Architecture, with where each fault lands">
      <div className="diagram-head">
        {scene == null ? (
          <span className="legend">
            <span>Same tickets, same approver, same payments. Only the architecture differs.</span>
          </span>
        ) : (
          <span className="legend">
            {/* The dots are where each stack thinks a ticket is. The ledger boxes explain themselves on hover. */}
            <span className="lg-group">
              <b>Ticket</b>
              <span><i className="lg active" /> in progress</span>
              <span><i className="lg waiting" /> waiting for a human</span>
              <span><i className="lg paying" /> refund in flight</span>
              <span><i className="lg failed" /> job failed</span>
              <span><i className="lg closed" /> denied</span>
              <span className="lg-stage">⏱ slowed on purpose</span>
            </span>
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
        {/* Under its row, lined up with the Queue label above its own: the human's bubble sits between the rows */}
        <text className="row-label" x={158} y={ROW.lane2 + NODE_H + 18}>TEMPORAL + NEXUS</text>

        <g className={humanNow ? "human now" : "human"} role="img" aria-label="A human approves or denies">
          <line className="wire" x1={HUMAN_X} x2={HUMAN_X} y1={HUMAN.y} y2={ROW.lane1 + NODE_H + 3} markerEnd="url(#arrow)" />
          <line className="wire" x1={HUMAN_X} x2={HUMAN_X} y1={HUMAN.y + HUMAN.h} y2={ROW.lane2 - 3} markerEnd="url(#arrow)" />
          <circle className="badge" cx={HUMAN_X} cy={HUMAN.y + HUMAN.h / 2} r={HUMAN.w / 2} />
          {/* A person: head and shoulders */}
          <circle className="glyph" cx={HUMAN_X} cy={HUMAN.y + 10} r={4.2} />
          <path
            className="glyph"
            d={`M${HUMAN_X - 7.5},${HUMAN.y + 22} Q${HUMAN_X - 7.5},${HUMAN.y + 15} ${HUMAN_X},${HUMAN.y + 15} Q${HUMAN_X + 7.5},${HUMAN.y + 15} ${HUMAN_X + 7.5},${HUMAN.y + 22} Z`}
          />
          <title>Human: approve / deny</title>
        </g>

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
              <rect x={HUMAN_X + 20} y={HUMAN.y + 3} width={30} height={22} rx={5} />
              <text x={HUMAN_X + 35} y={HUMAN.y + 19} textAnchor="middle">×2</text>
            </g>
          </>
        )}

        {Object.entries(NODES).map(([id, b]) => {
          const p = b.proc ? snap.processes[b.proc] : undefined;
          const down = p ? !p.alive : false;
          const cls = ["node", down && "down", hitNow.has(id) && "hit", id === "endpoint" && "door"].filter(Boolean).join(" ");
          // Payments' bottom strip holds the Temporal ledger, so its badge sits in the gap between the two ledgers instead.
          const badgeY = id === "payments" ? b.y + 128 : b.y + b.h - 27;
          return (
            <g key={id} className={cls}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={10} />
              <text className="n-title" x={b.x + 14} y={b.y + 22}>{b.title}</text>
              <text className="n-sub" x={b.x + 14} y={b.y + 40}>{b.sub}</text>
              {b.note && !down && <text className="n-sub" x={b.x + 14} y={b.y + 60}>{b.note}</text>}
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

        {scene != null && (
          <>
            <Ledger lane="lane1" label="Queue" dots={flow.lane1} tickets={audit("lane1")} onHint={setHint} />
            <Ledger lane="lane2" label="Temporal" dots={flow.lane2} tickets={audit("lane2")} onHint={setHint} />
          </>
        )}

        <Dots lane="lane1" dots={flow.lane1} />
        <Dots lane="lane2" dots={flow.lane2} />
        {hint && <HintBubble hint={hint} />}
      </svg>
    </section>
  );
}
