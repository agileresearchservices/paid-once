import { OUTCOME_GLYPH } from "./outcomes";
import type { FaultWindow, NexusRow, RefundAttempt } from "./types";
import { shortTicket, workflowLink } from "./nexusLinks";

// The Nexus scene over time. x = seconds since the scene started, on an axis fixed at 0-30 s (it only grows if a run
// takes longer), so bars grow into it with the clock and nothing rescales. Two blocks, one word each, so the point reads
// from across a room: SUPPORT SEES (the caller's Nexus operation per refund: one calm bar, stacked) above PAYMENTS DOES
// (the refund activity's attempts per refund: the retries). Above both, one red bar per failure, in the order they land,
// each washing faintly down through everything it hit. Per-refund detail is on hover and in the Temporal UI links.

const W = 1400; // viewBox width; the SVG scales to the panel
const LABEL = 230; // left column: the block names
const RIGHT = 190; // right column: one status per block
const FAULT_ROW = 22;
const TICKS = 26;
const BAR = 15; // one refund's bar
const BAR_GAP = 5;
const BLOCK_GAP = 26;
const MIN_ROWS = 5; // the scene approves five: reserve their height so the page doesn't jump when they arrive
const MIN_SPAN = 30; // seconds on the axis before it ever grows

// The gauntlet, in order. Shown muted before the run, so the audience sees what's coming; each fills as it lands.
const PLANNED: { key: string; label: string }[] = [
  { key: "payments", label: "payments quiet" },
  { key: "support_worker", label: "support worker" },
  { key: "payments_worker", label: "payments worker" },
  { key: "temporal", label: "Temporal server" },
];

type Props = {
  rows: NexusRow[];
  t0: number | null; // when the scene started, or null before it ever ran
  now: number;
  faults: FaultWindow[];
  temporalUi: string | null;
};

export function NexusTimeline({ rows, t0, now, faults, temporalUi }: Props) {
  const start = t0 ?? now;
  const t = (ts: number) => ts - start;
  const ends = rows.flatMap((r) => [r.op_closed_at ?? now, ...r.attempts.map((a) => a.ended_at ?? now)]);
  const latest = Math.max(0, ...ends.map(t));
  const faultEnds = faults.map((f) => (f.end != null ? Math.min(f.end, now) : now)).map(t);
  const span = Math.max(MIN_SPAN, Math.ceil(Math.max(latest, ...faultEnds) / 10) * 10);
  const x = (ts: number) => LABEL + (Math.max(0, Math.min(span, t(ts))) / span) * (W - LABEL - RIGHT);
  const TOP = PLANNED.length * FAULT_ROW + TICKS;
  const n = Math.max(MIN_ROWS, rows.length);
  const BLOCK = n * (BAR + BAR_GAP);
  const ySupport = TOP + 6;
  const yPayments = ySupport + BLOCK + BLOCK_GAP;
  const H = yPayments + BLOCK + 4;
  const byKey = new Map(faults.map((f) => [f.key, f]));
  const first = rows[0];

  const supportErrors = rows.filter((r) => r.caller_saw_failure || r.state === "FAILED").length;
  const open = rows.some((r) => r.live);
  const supportStatus =
    rows.length === 0 ? null : supportErrors ? { cls: "bad", text: `✕ saw ${supportErrors} error${supportErrors === 1 ? "" : "s"}` } : open ? { cls: "calm", text: "no errors" } : { cls: "ok", text: `${OUTCOME_GLYPH.ok} no errors` };
  const paymentsStatus =
    rows.length === 0 ? null : open ? { cls: "running", text: "retrying…" } : { cls: "ok", text: `${OUTCOME_GLYPH.ok} all done` };

  return (
    <svg className="timeline" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Nexus operations over time">
      {Array.from({ length: span / 10 + 1 }, (_, i) => i * 10).map((s) => (
        <g key={s} className="tick">
          <line x1={x(start + s)} x2={x(start + s)} y1={TOP - 6} y2={H} />
          <text x={x(start + s)} y={TOP - 9} textAnchor="middle">
            {s}s
          </text>
        </g>
      ))}

      {PLANNED.map((p, i) => (
        <FaultRow key={p.key} label={p.label} f={byKey.get(p.key)} y={i * FAULT_ROW} washTo={H} top={TOP} x={x} now={now} />
      ))}

      {rows.length === 0 && (
        <text className="empty" x={LABEL + 12} y={ySupport + 3 * BAR}>
          {t0 == null ? "Press Run. Four failures hit refunds in flight." : "Waiting for the first approved refund…"}
        </text>
      )}

      <BlockLabel
        y={ySupport}
        h={BLOCK}
        text="Support sees"
        href={historyLink(temporalUi, first, "caller")}
      />
      <BlockLabel y={yPayments} h={BLOCK} text="Payments does" href={historyLink(temporalUi, first, "handler")} />

      {rows.map((r, i) => (
        <g key={r.ticket}>
          <SupportBar r={r} y={ySupport + i * (BAR + BAR_GAP)} x={x} now={now} />
          <PaymentsBars r={r} y={yPayments + i * (BAR + BAR_GAP)} x={x} now={now} />
        </g>
      ))}

      {supportStatus && <Status y={ySupport} h={BLOCK} {...supportStatus} />}
      {paymentsStatus && <Status y={yPayments} h={BLOCK} {...paymentsStatus} />}
    </svg>
  );
}

// The Temporal UI link for the first refund's history (the block's name opens it); null without a UI.
function historyLink(base: string | null, r: NexusRow | undefined, side: "caller" | "handler"): string | null {
  if (!base || !r) return null;
  if (side === "caller") return workflowLink(base, r.caller_namespace, r.caller_workflow_id, r.caller_run_id);
  return r.handler.namespace && r.handler.workflow_id ? workflowLink(base, r.handler.namespace, r.handler.workflow_id, r.handler.run_id) : null;
}

function BlockLabel({ y, h, text, href }: { y: number; h: number; text: string; href: string | null }) {
  const label = (
    <text className={href ? "block-label link" : "block-label"} x={8} y={y + h / 2 + 6}>
      {text}
      {href ? " ↗" : ""}
    </text>
  );
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      <title>Open the first refund's history in the Temporal UI</title>
      {label}
    </a>
  ) : (
    label
  );
}

function Status({ y, h, cls, text }: { y: number; h: number; cls: string; text: string }) {
  return (
    <text className={`status ${cls}`} x={W - RIGHT + 16} y={y + h / 2 + 6}>
      {text}
    </text>
  );
}

// One failure: its label on the left, a solid bar for how long it lasted, and a faint wash down through the refunds.
function FaultRow({
  label,
  f,
  y,
  top,
  washTo,
  x,
  now,
}: {
  label: string;
  f?: FaultWindow;
  y: number;
  top: number;
  washTo: number;
  x: (ts: number) => number;
  now: number;
}) {
  const live = f != null && f.start != null;
  const x0 = live ? x(f.start!) : 0;
  const x1 = live ? x(f.end != null ? Math.min(f.end, now) : now) : 0;
  return (
    <g className={live ? "fault on" : "fault"}>
      <text className="fault-label" x={8} y={y + FAULT_ROW - 6}>
        ⚡ {label}
      </text>
      {live && (
        <>
          <rect className="fault-wash" x={x0} y={top - 6} width={Math.max(2, x1 - x0)} height={washTo - top + 6} />
          <rect className="fault-bar" x={x0} y={y + 3} width={Math.max(2, x1 - x0)} height={FAULT_ROW - 6} rx={3}>
            <title>{f?.effect === "stall" ? `${label} · ${f.hit} booked` : `${label} · ${f?.hit ?? 0} in flight`}</title>
          </rect>
        </>
      )}
    </g>
  );
}

// The caller's operation, exactly as support's workflow sees it: any SCHEDULED or BACKING_OFF stretch (payments hadn't
// accepted yet), then STARTED until it closes. On a normal run that is one calm bar.
function SupportBar({ r, y, x, now }: { r: NexusRow; y: number; x: (ts: number) => number; now: number }) {
  const end = r.op_closed_at ?? now;
  const phases = r.phases.length ? r.phases : [{ state: r.state, at: r.op_scheduled_at }];
  const startAttempts = `${r.peak_attempt} start attempt${r.peak_attempt === 1 ? "" : "s"}`;
  const hover =
    r.state === "FAILED"
      ? `${shortTicket(r.ticket)} · FAILED · ${r.last_failure || "the operation failed"}`
      : r.caller_saw_failure
        ? `${shortTicket(r.ticket)} · ${r.state} · ${startAttempts} · saw: ${r.last_failure}`
        : `${shortTicket(r.ticket)} · STARTED · no error`;
  return (
    <g>
      {phases.map((p, i) => {
        const from = i === 0 ? r.op_scheduled_at : p.at;
        const to = phases[i + 1]?.at ?? end;
        const cls = p.state === "STARTED" ? "seg calm" : "seg waiting";
        return (
          <rect key={i} className={cls} x={x(from)} y={y} width={Math.max(2, x(to) - x(from))} height={BAR} rx={2}>
            <title>{hover}</title>
          </rect>
        );
      })}
    </g>
  );
}

// The refund activity's attempts inside payments, the wait between them, and the moment the money was booked.
function PaymentsBars({ r, y, x, now }: { r: NexusRow; y: number; x: (ts: number) => number; now: number }) {
  const booked = r.ledger.booked_at;
  const atts = r.attempts;
  const last = atts[atts.length - 1];
  // A later attempt that got the stored result back: it ran after the booking and payments counted a replay.
  const replayed = (a: RefundAttempt) => booked != null && r.ledger.replays > 0 && a.started_at > booked && a.outcome === "ok";
  const describe = (a: RefundAttempt) => {
    const secs = Math.round((a.ended_at ?? now) - a.started_at);
    const what =
      a.outcome === "failed"
        ? `✕ attempt ${a.n} ${timedOut(a) ? "timed out" : `failed after ${secs} s`}`
        : a.outcome === "ok"
          ? `${OUTCOME_GLYPH.ok} attempt ${a.n}${replayed(a) ? " · from the ledger" : ""}`
          : `attempt ${a.n}…`;
    return `${shortTicket(r.ticket)} · ${what}${a.failure ? ` · ${a.failure}` : ""}`;
  };
  return (
    <g>
      {atts.slice(1).map((a, i) => {
        const prevEnd = atts[i].ended_at ?? now;
        return <line key={`gap${a.n}`} className="gap" x1={x(prevEnd)} x2={x(a.started_at)} y1={y + BAR / 2} y2={y + BAR / 2} />;
      })}
      {last && last.outcome !== "running" && last.outcome !== "ok" && r.live && (
        <line className="gap" x1={x(last.ended_at ?? now)} x2={x(now)} y1={y + BAR / 2} y2={y + BAR / 2} />
      )}
      {atts.map((a) => (
        <rect key={a.n} className={`seg ${a.outcome}`} x={x(a.started_at)} y={y} width={Math.max(2, x(a.ended_at ?? now) - x(a.started_at))} height={BAR} rx={2}>
          <title>{describe(a)}</title>
        </rect>
      ))}
      {booked != null && (
        <g className="booked">
          <title>{shortTicket(r.ticket)} · the ledger booked this refund (refund-&lt;ticket&gt;)</title>
          <circle cx={x(booked)} cy={y + BAR / 2} r={BAR / 2 + 2} />
          <text x={x(booked)} y={y + BAR / 2 + 4} textAnchor="middle">
            $
          </text>
        </g>
      )}
    </g>
  );
}

const timedOut = (a: RefundAttempt) => /StartToClose|timeout/i.test(a.failure);
