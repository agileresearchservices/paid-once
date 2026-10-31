import { OUTCOME_GLYPH } from "./outcomes";
import type { NexusRow, RefundAttempt, ShowEvent } from "./types";
import { shortTicket, workflowLink } from "./nexusLinks";

// The Nexus scene over time. x = seconds since the scene started, on an axis fixed at 0-30 s (it only grows if a
// run takes longer), so bars grow into it with the clock and nothing rescales. Each approved ticket gets two
// tracks: what support's code sees (the caller's Nexus operation) and what payments does about it (the refund
// activity's attempts, with the moment the ledger booked the money).

const W = 1400; // viewBox width; the SVG scales to the panel
const LABEL = 172; // left column: ticket number and the two track labels
const RIGHT = 12;
const TOP = 44; // the outage label, then the axis ticks
const TRACK = 18;
const TRACK_GAP = 5;
const ROW_GAP = 13;
const ROW = TRACK * 2 + TRACK_GAP + ROW_GAP;
const MIN_ROWS = 5; // the scene approves five: reserve their height so the page doesn't jump when they arrive
const CHAR = 7.4; // rough width of one 13px character, to decide whether a label fits inside its bar

type Props = {
  rows: NexusRow[];
  t0: number | null; // when the scene started, or null before it ever ran
  now: number;
  events: ShowEvent[];
  temporalUi: string | null;
};

export function NexusTimeline({ rows, t0, now, events, temporalUi }: Props) {
  const start = t0 ?? now;
  const t = (ts: number) => ts - start;
  const ends = rows.flatMap((r) => [r.op_closed_at ?? now, ...r.attempts.map((a) => a.ended_at ?? now)]);
  const latest = Math.max(0, ...ends.map(t));
  const span = Math.max(30, Math.ceil(latest / 5) * 5);
  const x = (ts: number) => LABEL + (Math.max(0, Math.min(span, t(ts))) / span) * (W - LABEL - RIGHT);
  const H = TOP + Math.max(MIN_ROWS, rows.length) * ROW;

  // The outage: from the payments worker's kill to its restart in this run (or to now while it is still down).
  const mine = t0 == null ? [] : events.filter((e) => e.ts >= t0 && e.proc === "payments_worker");
  const kill = mine.find((e) => e.kind === "kill");
  const back = kill && mine.find((e) => e.kind === "restart" && e.ts >= kill.ts);
  const downTo = back ? back.ts : now;

  return (
    <svg className="timeline" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Nexus operations over time">
      <defs>
        <pattern id="outage-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" className="hatch-bg" />
          <line x1="0" y1="0" x2="0" y2="8" className="hatch-line" />
        </pattern>
      </defs>

      {Array.from({ length: span / 5 + 1 }, (_, i) => i * 5).map((s) => (
        <g key={s} className="tick">
          <line x1={x(start + s)} x2={x(start + s)} y1={TOP - 6} y2={H} />
          <text x={x(start + s)} y={TOP - 10} textAnchor="middle">
            {s}s
          </text>
        </g>
      ))}

      {kill && (
        <g className="outage">
          <rect x={x(kill.ts)} y={TOP - 24} width={Math.max(2, x(downTo) - x(kill.ts))} height={H - TOP + 24} />
          <text x={x(kill.ts)} y={TOP - 28} textAnchor="start">
            ⚡ payments worker down{back ? ` · ${Math.round(back.ts - kill.ts)} s` : ""}
          </text>
        </g>
      )}

      {rows.length === 0 && (
        <text className="empty" x={LABEL + 12} y={TOP + ROW}>
          {t0 == null ? "Each approved refund gets two tracks here when the scene runs." : "Waiting for the first approved refund…"}
        </text>
      )}

      {rows.map((r, i) => (
        <Ticket key={r.ticket} r={r} y={TOP + 8 + i * ROW} x={x} now={now} ui={temporalUi} />
      ))}
    </svg>
  );
}

function Ticket({ r, y, x, now, ui }: { r: NexusRow; y: number; x: (ts: number) => number; now: number; ui: string | null }) {
  const yPay = y + TRACK + TRACK_GAP;
  const h = r.handler;
  return (
    <g className="ticket-row">
      <text className="tnum" x={8} y={y + TRACK + 3}>
        {shortTicket(r.ticket)}
      </text>
      <TrackLabel
        x={56}
        y={y}
        text="support sees"
        href={ui ? workflowLink(ui, r.caller_namespace, r.caller_workflow_id, r.caller_run_id) : null}
      />
      <TrackLabel
        x={56}
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
    <text className={href ? "track-label link" : "track-label"} x={x} y={y + TRACK - 4}>
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
  const label = failed
    ? `FAILED · ${r.last_failure || "the operation failed"}`
    : r.caller_saw_failure
      ? `${r.state} · ${startAttempts} · saw: ${r.last_failure}`
      : `STARTED · ${startAttempts} · no error`;
  const x0 = x(r.op_scheduled_at);
  const x1 = x(end);
  return (
    <g className="support-track">
      {phases.map((p, i) => {
        const from = i === 0 ? r.op_scheduled_at : p.at;
        const to = phases[i + 1]?.at ?? end;
        const cls = p.state === "STARTED" ? "seg calm" : "seg waiting";
        return <rect key={i} className={cls} x={x(from)} y={y} width={Math.max(2, x(to) - x(from))} height={TRACK} rx={4} />;
      })}
      {/* Always anchored at the bar's start: the bar grows under it, so the label never jumps while live. */}
      <text className={`seg-text inside ${failed || r.caller_saw_failure ? "warn" : ""}`} x={x0 + 8} y={y + TRACK - 4}>
        {label}
      </text>
      {!r.live && (
        <text className={failed ? "end bad" : "end ok"} x={x1 + 6} y={y + TRACK - 4}>
          {failed ? "✕ failed" : `${OUTCOME_GLYPH.ok} completed`}
        </text>
      )}
    </g>
  );
}

// The refund activity's attempts inside payments, the wait between them, and the moment the money was booked.
function PaymentsTrack({ r, y, x, now }: { r: NexusRow; y: number; x: (ts: number) => number; now: number }) {
  const booked = r.ledger.booked_at;
  const atts = r.attempts;
  const last = atts[atts.length - 1];
  // A later attempt that got the stored result back: it ran after the booking and payments counted a replay.
  const replayed = (a: RefundAttempt) => booked != null && r.ledger.replays > 0 && a.started_at > booked && a.outcome === "ok";
  return (
    <g className="payments-track">
      {atts.slice(1).map((a, i) => {
        const prevEnd = atts[i].ended_at ?? now;
        return <line key={`gap${a.n}`} className="gap" x1={x(prevEnd)} x2={x(a.started_at)} y1={y + TRACK / 2} y2={y + TRACK / 2} />;
      })}
      {last && last.outcome !== "running" && last.outcome !== "ok" && r.live && (
        <line className="gap" x1={x(last.ended_at ?? now)} x2={x(now)} y1={y + TRACK / 2} y2={y + TRACK / 2} />
      )}
      {atts.map((a) => {
        const x0 = x(a.started_at);
        const x1 = x(a.ended_at ?? now);
        const text =
          a.outcome === "failed"
            ? `✕ attempt ${a.n} ${timedOut(a) ? `timed out (${Math.round((a.ended_at ?? now) - a.started_at)} s)` : `failed: ${a.failure || "error"}`}`
            : a.outcome === "ok"
              ? `${OUTCOME_GLYPH.ok} attempt ${a.n}${replayed(a) ? " · answered from the ledger, not paid again" : ""}`
              : `attempt ${a.n}…`;
        // Keep the label clear of the $ marker when the booking falls inside this attempt.
        const bx = booked != null ? x(booked) : null;
        const from = bx != null && bx >= x0 && bx <= x1 ? bx + TRACK / 2 + 6 : x0 + 8;
        return (
          <g key={a.n}>
            <rect className={`seg ${a.outcome}`} x={x0} y={y} width={Math.max(2, x1 - x0)} height={TRACK} rx={4} />
            <FittedLabel from={from} x1={x1} y={y} text={text} cls={a.outcome} after={a.outcome === "ok"} />
          </g>
        );
      })}
      {atts.length === 0 && (
        <text className="seg-text muted" x={x(r.op_scheduled_at) + 4} y={y + TRACK - 4}>
          not accepted yet
        </text>
      )}
      {booked != null && (
        <g className="booked">
          <title>The ledger booked this refund (refund-&lt;ticket&gt;)</title>
          <circle cx={x(booked)} cy={y + TRACK / 2} r={TRACK / 2 + 1} />
          <text x={x(booked)} y={y + TRACK / 2 + 4} textAnchor="middle">
            $
          </text>
        </g>
      )}
    </g>
  );
}

const timedOut = (a: RefundAttempt) => /StartToClose|timeout/i.test(a.failure);

// A label inside its bar (from `from`) if it fits, otherwise just after the bar's end. `after` always puts it after.
function FittedLabel({ from, x1, y, text, cls, after }: { from: number; x1: number; y: number; text: string; cls: string; after?: boolean }) {
  const fits = !after && x1 - from > text.length * CHAR + 4;
  return (
    <text className={`seg-text ${cls} ${fits ? "inside" : "outside"}`} x={fits ? from : x1 + 6} y={y + TRACK - 4}>
      {text}
    </text>
  );
}
