import type { ReactNode } from "react";
import { NexusTimeline } from "./NexusTimeline";
import { shortTicket } from "./nexusLinks";
import { ProcTile } from "./Processes";
import type { FaultWindow, NexusRow, ProcStatus, SceneRun, Topology } from "./types";

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

// Who owns what, left to right like the architecture diagram: support's code names only the endpoint, and the
// endpoint maps to the payments namespace. Each team's worker sits in its own box, so the kill shows where it lands.
function BoundaryStrip({
  t,
  ui,
  support,
  payments,
  temporal,
  kills,
}: {
  t: Topology;
  ui: string | null;
  support?: ProcStatus;
  payments?: ProcStatus;
  temporal?: ProcStatus;
  kills: Record<string, number>;
}) {
  const isDown = (p?: ProcStatus) => p !== undefined && !p.alive;
  return (
    <div className="strip">
      <div className={isDown(support) ? "team down" : "team"}>
        <div className="team-head">
          <span className="team-name">Support team</span>
          {ui && <Ext href={`${ui}/namespaces/${t.support.namespace}/workflows`}>namespace ↗</Ext>}
        </div>
        <span>
          <code>{t.support.namespace}</code> · {t.support.workflow}
        </span>
        {support && <ProcTile p={support} kills={kills.support_worker} />}
      </div>
      <span className="strip-arrow" aria-hidden="true">
        ▶
      </span>
      <div className={isDown(temporal) ? "endpoint-card down" : "endpoint-card"}>
        <span className="headline-label">
          {isDown(temporal) ? (
            <>
              ⚡ Temporal server down
              <br />
              {kills.temporal ? "killed during this run" : " "}
            </>
          ) : (
            <>
              Team boundary
              <br />
              the only name in support's code
            </>
          )}
        </span>
        <code>{t.endpoint}</code>
        <code>
          {t.service}.{t.operation}
        </code>
      </div>
      <span className="strip-arrow" aria-hidden="true">
        ▶
      </span>
      <div className={isDown(payments) ? "team down" : "team"}>
        <div className="team-head">
          <span className="team-name">Payments team</span>
          {(kills.payments_worker ?? 0) > 0 && (
            <span className="team-kills" title="kill -9 during this scene">
              ⚡ killed {kills.payments_worker === 1 ? "once" : `${kills.payments_worker} times`}
            </span>
          )}
          {ui && <Ext href={`${ui}/namespaces/${t.payments.namespace}/workflows`}>namespace ↗</Ext>}
        </div>
        <span>
          <code>{t.payments.namespace}</code> · {t.payments.workflow} → {t.payments.activity}
        </span>
        {/* The kill count sits in the header, so the tile keeps one line inside the card. */}
        {payments && <ProcTile p={payments} />}
      </div>
    </div>
  );
}

type Beat = { text: string };

// The story in four beats, read from the run's fault windows and the rows. Each lights up when it has happened.
function beatsFor(
  rows: NexusRow[],
  faults: FaultWindow[],
  planned: number,
  done: boolean,
  verdict: string,
): { beats: Beat[]; reached: number } {
  const n = rows.length;
  const on = faults.filter((f) => f.start != null);
  const landed = on.length;
  const latest = on[on.length - 1];
  const allBack = landed > 0 && faults.every((f) => f.start != null && f.end != null);
  const beats = [
    { text: `Support starts ${n || "the"} refund${n === 1 ? "" : "s"} on the endpoint` },
    {
      text:
        landed === 0
          ? `⚡ ${planned} failures while they're in flight`
          : `⚡ Failure ${landed} of ${planned}: ${latest.effect === "stall" ? "payments goes quiet" : `${latest.label} killed`}`,
    },
    { text: "Everything back up: payments retries with the same key" },
    { text: done ? verdict : "The ledger decides: was each refund paid once?" },
  ];
  const reached = done ? 4 : allBack ? 3 : landed > 0 ? 2 : n > 0 ? 1 : 0;
  return { beats, reached };
}

export function NexusPanel({
  rows,
  ran,
  topology,
  temporalUi,
  processes,
  run,
  finished,
  now,
  ledgerTickets,
  calls,
}: {
  rows: NexusRow[];
  ran: boolean; // this scene is the one the engine last ran; otherwise rows is empty because nothing ran yet
  topology: Topology;
  temporalUi: string | null;
  processes: Record<string, ProcStatus>;
  run?: SceneRun;
  finished: boolean;
  now: number;
  ledgerTickets: Record<string, string>; // the ledger's verdict per ticket (audit), every scene since reset
  calls?: { calls: number; booked: number; replays: number }; // this scene's calls to payments, counted by payments
}) {
  const t0 = ran && run ? run.started_at : null;
  const faults = ran ? (run?.faults ?? []) : [];
  const allClosed = rows.length > 0 && rows.every((r) => !r.live && r.attempts.every((a) => a.outcome !== "running"));

  // This run's tickets, by the ledger (audit), never by the lane's own state.
  const scene = ran ? sceneTickets(ledgerTickets) : [];
  const denied = scene.filter(([, v]) => v === "declined" || v === "rejected");
  const paidOnce = scene.filter(([, v]) => v === "ok").length;
  const paidTwice = scene.filter(([, v]) => v === "duplicate").length;
  const missing = scene.filter(([, v]) => v === "missing").length;
  const errors = rows.filter((r) => r.caller_saw_failure || r.state === "FAILED").length;
  const maxStarts = Math.max(0, ...rows.map((r) => r.peak_attempt));
  const retries = rows.reduce((n, r) => n + Math.max(0, r.attempts.length - 1, (r.handler.peak_activity_attempt ?? 0) - 1), 0);
  const show = finished && allClosed;
  const landed = faults.filter((f) => f.start != null);
  const verdict =
    paidTwice || missing || errors
      ? `⚠ ${[paidTwice && `${paidTwice} paid twice`, missing && `${missing} never paid`, errors && `support saw ${errors} error${errors === 1 ? "" : "s"}`].filter(Boolean).join(", ")}`
      : "Each refund paid once; support's code saw no errors";
  const planned = processes.temporal ? 4 : 3; // the Temporal kill needs a server the show started itself
  const { beats, reached } = beatsFor(rows, faults, planned, show, verdict);

  return (
    <section className="nexus" aria-label="Nexus">
      <BoundaryStrip
        t={topology}
        ui={temporalUi}
        support={processes.support_worker}
        payments={processes.payments_worker}
        temporal={processes.temporal}
        kills={ran && run ? run.kills : {}}
      />
      <p className="without">
        <b>Without Nexus,</b> support's code would name payments' namespace, task queue and workflow, and own their
        retries.
      </p>

      {ran ? (
        <ol className="beats">
          {beats.map((b, i) => (
            <li key={i} className={i + 1 < reached ? "done" : i + 1 === reached ? "now" : ""}>
              <b>{i + 1}</b> {b.text}
            </li>
          ))}
        </ol>
      ) : (
        <p className="beats-pre">
          Press Run: 7 tickets, the approved ones go to payments over Nexus. Then, while they're in flight, payments
          goes quiet and the support worker, the payments worker and the Temporal server itself are killed.
        </p>
      )}

      <div className="timeline-wrap">
        <NexusTimeline rows={rows} t0={t0} now={now} faults={faults} temporalUi={temporalUi} />
        <div className="timeline-notes">
          <span>
            {denied.length > 0
              ? `${denied.map(([k, v]) => `${shortTicket(k)} denied ${v === "declined" ? "by policy" : "by a human"}`).join(" · ")} · no Nexus call made`
              : " "}
          </span>
          <span>
            <i className="key-dollar">$</i> the ledger booked the refund · support would only see a failure after the
            10-minute schedule-to-close timeout
          </span>
        </div>
      </div>

      <div className="headline payoff">
        <div>
          <span className="headline-label">Failures</span>
          {show ? (
            <>
              <b>{landed.length}</b> <span className="muted">· each with {Math.min(...landed.map((f) => f.hit))}+ refunds in flight</span>
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div>
          <span className="headline-label">Support's code saw</span>
          {show ? (
            <>
              <b className={errors ? "n-bad" : "n-good"}>{errors}</b> error{errors === 1 ? "" : "s"}{" "}
              <span className="muted">
                · {rows.length} operations, {maxStarts === 1 ? "1 start attempt each" : `up to ${maxStarts} start attempts`}
              </span>
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div>
          <span className="headline-label">Payments absorbed</span>
          {show ? (
            <>
              <b>{retries}</b> retr{retries === 1 ? "y" : "ies"} <span className="muted">· inside its own namespace</span>
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div>
          <span className="headline-label">The ledger</span>
          {show ? (
            <>
              <b className={paidTwice || missing ? "n-bad" : "n-good"}>{paidOnce}</b> refund{paidOnce === 1 ? "" : "s"}, each
              paid once
              {paidTwice > 0 && <b className="n-bad"> · {paidTwice} paid twice</b>}
              {missing > 0 && <b className="n-bad"> · {missing} never paid</b>}
              {calls && (
                <span className="muted">
                  {" "}
                  · {calls.calls} calls: {calls.booked} booked, {calls.replays} answered from the ledger by{" "}
                  <code>refund-&lt;ticket&gt;</code>
                </span>
              )}
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
      </div>
    </section>
  );
}

// The ledger keys of the latest nexus_kill run: <run>-nexus_kill-r<n>-<i>-lane2, highest n since the last reset.
function sceneTickets(tickets: Record<string, string>): [string, string][] {
  const all = Object.entries(tickets).filter(([k]) => k.includes("-nexus_kill-r"));
  const runNo = (k: string) => Number(k.match(/-nexus_kill-r(\d+)-/)?.[1] ?? 0);
  const latest = Math.max(0, ...all.map(([k]) => runNo(k)));
  return all.filter(([k]) => runNo(k) === latest).sort(([a], [b]) => a.localeCompare(b));
}
