import type { ReactNode } from "react";
import { NexusTimeline } from "./NexusTimeline";
import { shortTicket } from "./nexusLinks";
import { ProcTile } from "./Processes";
import type { NexusRow, ProcStatus, SceneRun, ShowEvent, Topology } from "./types";

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
  kills,
}: {
  t: Topology;
  ui: string | null;
  support?: ProcStatus;
  payments?: ProcStatus;
  kills: Record<string, number>;
}) {
  const down = payments !== undefined && !payments.alive;
  return (
    <div className="strip">
      <div className="team">
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
      <div className="endpoint-card">
        <span className="headline-label">
          Team boundary
          <br />
          the only name in support's code
        </span>
        <code>{t.endpoint}</code>
        <code>
          {t.service}.{t.operation}
        </code>
      </div>
      <span className="strip-arrow" aria-hidden="true">
        ▶
      </span>
      <div className={down ? "team down" : "team"}>
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

// The story in four beats, read from the snapshot. Each one lights up when what it says has happened.
function beatsFor(rows: NexusRow[], kill: boolean, back: boolean, done: boolean): { beats: Beat[]; reached: number } {
  const n = rows.length;
  const notAccepted = rows.some((r) => r.peak_attempt > 1);
  const beats = [
    { text: `Support starts ${n || "the"} refund${n === 1 ? "" : "s"} on the endpoint` },
    {
      text: notAccepted
        ? "⚡ Payments worker killed: some operations weren't accepted yet, so support sees those retry"
        : "⚡ Payments worker killed: support still sees STARTED, no error",
    },
    { text: "Worker back: payments retries with the same key" },
    { text: "Each refund paid once; support never saw the outage" },
  ];
  const reached = done ? 4 : back ? 3 : kill ? 2 : n > 0 ? 1 : 0;
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
  events,
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
  events: ShowEvent[];
  now: number;
  ledgerTickets: Record<string, string>; // the ledger's verdict per ticket (audit), every scene since reset
  calls?: { calls: number; booked: number; replays: number }; // this scene's calls to payments, counted by payments
}) {
  const t0 = ran && run ? run.started_at : null;
  const mine = t0 == null ? [] : events.filter((e) => e.ts >= t0 && e.proc === "payments_worker");
  const kill = mine.some((e) => e.kind === "kill");
  const back = kill && mine.some((e) => e.kind === "restart");
  const allClosed = rows.length > 0 && rows.every((r) => !r.live && r.attempts.every((a) => a.outcome !== "running"));
  const { beats, reached } = beatsFor(rows, kill, back, finished && allClosed);

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

  return (
    <section className="nexus" aria-label="Nexus">
      <BoundaryStrip
        t={topology}
        ui={temporalUi}
        support={processes.support_worker}
        payments={processes.payments_worker}
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
          Press Run: 7 tickets, the approved ones go to payments over Nexus, then the payments worker is killed.
        </p>
      )}

      <div className="timeline-wrap">
        <NexusTimeline rows={rows} t0={t0} now={now} events={events} temporalUi={temporalUi} />
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
