import { OUTCOME_GLYPH } from "./outcomes";
import type { FaultWindow, NexusRow, RefundAttempt } from "./types";
import { shortTicket, workflowLink } from "./nexusLinks";

// The Nexus scene over time. x = seconds since the scene started, on an axis fixed at 0-30 s (it only grows if a
// run takes longer), so bars grow into it with the clock and nothing rescales. Each approved ticket gets two
// thin tracks: what support's code sees (the caller's Nexus operation: one calm bar) and what payments does about it
// (the refund activity's attempts, with the moment the ledger booked the money). Each track's words sit in a status
// column on the right; the details of an attempt are on hover. Above them, one row per failure the scene
// injects, in the order they land, each washing faintly down through the tickets it hit.

const W = 1400; // viewBox width; the SVG scales to the panel
const LABEL = 196; // left column: ticket number and the two track labels
const RIGHT = 250; // reserved on the right for each track's status text, so it never moves while a bar grows
const FAULT_ROW = 21;
const TICKS = 26;
const TRACK = 14; // thin strips: the story is the shape (one calm bar over a busy strip), the words are in the status column
const TRACK_GAP = 4;
const ROW_GAP = 14;
const ROW = TRACK * 2 + TRACK_GAP + ROW_GAP;
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
  const span = Math.max(MIN_SPAN, Math.ceil(Math.max(latest, ...faultEnds) / 5) * 5);
  const x = (ts: number) => LABEL + (Math.max(0, Math.min(span, t(ts))) / span) * (W - LABEL - RIGHT);
  const TOP = PLANNED.length * FAULT_ROW + TICKS;
  const H = TOP + Math.max(MIN_ROWS, rows.length) * ROW;
  const byKey = new Map(faults.map((f) => [f.key, f]));

  return (
    <svg className="timeline" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Nexus operations over time">
      {Array.from({ length: span / 5 + 1 }, (_, i) => i * 5).map((s) => (
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
        <text className="empty" x={LABEL + 12} y={TOP + ROW}>
          {t0 == null ? "Press Run. Four failures hit refunds in flight." : "Waiting for the first approved refund…"}
        </text>
      )}

      {rows.map((r, i) => (
        <Ticket key={r.ticket} r={r} y={TOP + 8 + i * ROW} x={x} now={now} ui={temporalUi} />
      ))}
    </svg>
  );
}

// One failure: its label on the left, a solid bar for how long it lasted, and a faint wash down through the tickets.
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
  const secs = live ? Math.max(0, Math.round((f.end != null ? Math.min(f.end, now) : now) - f.start!)) : 0;
  const what = f?.effect === "stall" ? `quiet · ${f.hit} booked` : `down${f?.end != null ? ` ${secs} s` : ""} · ${f?.hit ?? 0} in flight`;
  return (
    <g className={live ? "fault on" : "fault"}>
      <text className="fault-label" x={8} y={y + FAULT_ROW - 5}>
        ⚡ {label}
      </text>
      {live && (
        <>
          <rect className="fault-wash" x={x0} y={top - 6} width={Math.max(2, x1 - x0)} height={washTo - top + 6} />
          <rect className="fault-bar" x={x0} y={y + 2} width={Math.max(2, x1 - x0)} height={FAULT_ROW - 4} rx={3} />
          <text className="fault-text" x={x1 + 6} y={y + FAULT_ROW - 5}>
            {what}
          </text>
        </>
      )}
    </g>
  );
}

function Ticket({ r, y, x, now, ui }: { r: NexusRow; y: number; x: (ts: number) => number; now: number; ui: string | null }) {
  const yPay = y + TRACK + TRACK_GAP;
  const h = r.handler;
  return (
    <g className="ticket-row">
      <text className="tnum" x={8} y={y + TRACK + TRACK_GAP + 6}>
        {shortTicket(r.ticket)}
      </text>
      <TrackLabel
        x={64}
        y={y}
        text="support sees"
        href={ui ? workflowLink(ui, r.caller_namespace, r.caller_workflow_id, r.caller_run_id) : null}
      />
      <TrackLabel
        x={64}
        y={yPay}
        text="payments does"
        href={ui && h.namespace && h.workflow_id ? workflowLink(ui, h.namespace, h.workflow_id, h.run_id) : null}
      />
      <SupportTrack r={r} y={y} x={x} now={now} />
      <PaymentsTrack r={r} y={yPay} x={x} now={now} />
    </g>
  );
}

function TrackLabel({ x, y, text, href }: { x: number; y: number; text: string; href: string | null }) {
  const label = (
    <text className={href ? "track-label link" : "track-label"} x={x} y={y + TRACK - 1}>
      {text}
      {href ? " ↗" : ""}
    </text>
  );
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      <title>Open this workflow's history in the Temporal UI</title>
      {label}
    </a>
  ) : (
    label
  );
}

// The caller's operation, exactly as support's workflow sees it: any SCHEDULED or BACKING_OFF stretch (payments
// hadn't accepted yet), then STARTED until it closes. On a normal run that is one calm bar.
function SupportTrack({ r, y, x, now }: { r: NexusRow; y: number; x: (ts: number) => number; now: number }) {
  const end = r.op_closed_at ?? now;
  const phases = r.phases.length ? r.phases : [{ state: r.state, at: r.op_scheduled_at }];
  const failed = r.state === "FAILED";
  const startAttempts = `${r.peak_attempt} start attempt${r.peak_attempt === 1 ? "" : "s"}`;
  const bad = failed || r.caller_saw_failure;
  const label = failed
    ? `✕ FAILED · ${r.last_failure || "the operation failed"}`
    : r.caller_saw_failure
      ? `${r.state} · ${startAttempts} · saw: ${r.last_failure}`
      : r.live
        ? "STARTED · no error"
        : `${OUTCOME_GLYPH.ok} completed · no error`;
  return (
    <g className="support-track">
      {phases.map((p, i) => {
        const from = i === 0 ? r.op_scheduled_at : p.at;
        const to = phases[i + 1]?.at ?? end;
        const cls = p.state === "STARTED" ? "seg calm" : "seg waiting";
        return <rect key={i} className={cls} x={x(from)} y={y} width={Math.max(2, x(to) - x(from))} height={TRACK} rx={3} />;
      })}
      <StatusText y={y} cls={bad ? (failed ? "bad" : "warn") : r.live ? "calm" : "ok"} text={label} />
    </g>
  );
}

// A track's words, in the column on the right.
function StatusText({ y, cls, text }: { y: number; cls: string; text: string }) {
  return (
    <text className={`status ${cls}`} x={W - RIGHT + 14} y={y + TRACK - 1}>
      <title>{text}</title>
      {text}
    </text>
  );
}

// The refund activity's attempts inside payments, the wait between them, and the moment the money was booked.
function PaymentsTrack({ r, y, x, now }: { r: NexusRow; y: number; x: (ts: number) => number; now: number }) {
  const booked = r.ledger.booked_at;
  const atts = r.attempts;
  const last = atts[atts.length - 1];
  // A later attempt that got the stored result back: it ran after the booking and payments counted a replay.
  const replayed = (a: RefundAttempt) => booked != null && r.ledger.replays > 0 && a.started_at > booked && a.outcome === "ok";
  const describe = (a: RefundAttempt) => {
    const secs = Math.round((a.ended_at ?? now) - a.started_at);
    return a.outcome === "failed"
      ? `✕ attempt ${a.n} ${timedOut(a) ? "timed out" : `failed after ${secs} s`}`
      : a.outcome === "ok"
        ? `${OUTCOME_GLYPH.ok} attempt ${a.n}${replayed(a) ? " · from the ledger" : ""}`
        : `attempt ${a.n}…`;
  };
  return (
    <g className="payments-track">
      {atts.slice(1).map((a, i) => {
        const prevEnd = atts[i].ended_at ?? now;
        return <line key={`gap${a.n}`} className="gap" x1={x(prevEnd)} x2={x(a.started_at)} y1={y + TRACK / 2} y2={y + TRACK / 2} />;
      })}
      {last && last.outcome !== "running" && last.outcome !== "ok" && r.live && (
        <line className="gap" x1={x(last.ended_at ?? now)} x2={x(now)} y1={y + TRACK / 2} y2={y + TRACK / 2} />
      )}
      {atts.map((a) => (
        <rect key={a.n} className={`seg ${a.outcome}`} x={x(a.started_at)} y={y} width={Math.max(2, x(a.ended_at ?? now) - x(a.started_at))} height={TRACK} rx={3}>
          <title>{a.failure ? `${describe(a)} · ${a.failure}` : describe(a)}</title>
        </rect>
      ))}
      {last ? (
        <StatusText y={y} cls={last.outcome === "ok" ? "ok" : last.outcome === "failed" ? "failed" : "running"} text={describe(last)} />
      ) : (
        <StatusText y={y} cls="muted" text="not accepted yet" />
      )}
      {booked != null && (
        <g className="booked">
          <title>The ledger booked this refund (refund-&lt;ticket&gt;)</title>
          <circle cx={x(booked)} cy={y + TRACK / 2} r={TRACK / 2 + 3} />
          <text x={x(booked)} y={y + TRACK / 2 + 4} textAnchor="middle">
            $
          </text>
        </g>
      )}
    </g>
  );
}

const timedOut = (a: RefundAttempt) => /StartToClose|timeout/i.test(a.failure);
