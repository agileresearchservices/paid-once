import type { ReactNode } from "react";
import { NexusTimeline } from "./NexusTimeline";
import { shortTicket } from "./nexusLinks";
import { ProcTile } from "./Processes";
import type { NexusRow, ProcStatus, SceneRun, Topology } from "./types";

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

// The claim, left to right like the architecture diagram: support's code names one endpoint and one operation, and
// everything behind it belongs to payments. The snippet and the list are built from the topology the server sends, so they
// can't drift from support_side.py / the payments side. Each team's worker sits in its own box, so a kill shows where it lands.
function ClaimCard({
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
    <>
      <div className="strip">
        <div className={isDown(support) ? "team down" : "team"}>
          <div className="team-head">
            <span className="team-name">Support team</span>
            {ui && <Ext href={`${ui}/namespaces/${t.support.namespace}/workflows`}>namespace ↗</Ext>}
          </div>
          <span className="claim-label">Support's code knows only:</span>
          <pre className="code">{`nexus = workflow.create_nexus_client(
    service=${t.service},
    endpoint="${t.endpoint}")
await nexus.execute_operation(
    ${t.service}.${t.operation}, request)`}</pre>
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
              <>Team boundary</>
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
          <span className="claim-label">Payments owns:</span>
          <ul className="owns">
            <li>
              namespace <code>{t.payments.namespace}</code> · task queue <code>{t.payments.task_queue}</code>
            </li>
            <li>
              <code>{t.payments.workflow}</code> → <code>{t.payments.activity}</code>
            </li>
            <li>its own retries and timeouts</li>
            <li>
              idempotency key <code>refund-&lt;ticket&gt;</code>
            </li>
          </ul>
          {payments && <ProcTile p={payments} />}
        </div>
      </div>
      <p className="claim-note">
        Support names one endpoint and one operation. The endpoint maps to payments' namespace and queue in its own config,
        not in support's code.
      </p>
    </>
  );
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
  const retries = rows.reduce((n, r) => n + Math.max(0, r.attempts.length - 1, (r.handler.peak_activity_attempt ?? 0) - 1), 0);
  const show = finished && allClosed;

  return (
    <section className="nexus" aria-label="Nexus">
      <ClaimCard
        t={topology}
        ui={temporalUi}
        support={processes.support_worker}
        payments={processes.payments_worker}
        temporal={processes.temporal}
        kills={ran && run ? run.kills : {}}
      />

      <div className="timeline-wrap">
        <NexusTimeline rows={rows} t0={t0} now={now} faults={faults} temporalUi={temporalUi} />
        <div className="timeline-notes">
          <span>
            {denied.length > 0
              ? `${denied.map(([k, v]) => `${shortTicket(k)} denied ${v === "declined" ? "by policy" : "by a human"}`).join(" · ")} · no Nexus call made`
              : " "}
          </span>
          <span>
            <i className="key-dollar">$</i> booked in the ledger · support sees an error only after the 10-minute timeout
          </span>
        </div>
      </div>

      <div className="headline payoff">
        <div>
          <span className="headline-label">Support saw</span>
          {show ? (
            <>
              <b className={errors ? "n-bad" : "n-good"}>{errors}</b> error{errors === 1 ? "" : "s"}{" "}
              <span className="muted">
                · {rows.length} operations
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
              <b>{retries}</b> retr{retries === 1 ? "y" : "ies"} <span className="muted">· on its own</span>
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div>
          <span className="headline-label">The ledger</span>
          {show ? (
            <>
              <b className={paidTwice || missing ? "n-bad" : "n-good"}>{paidOnce}</b> paid once
              {paidTwice > 0 && <b className="n-bad"> · {paidTwice} paid twice</b>}
              {missing > 0 && <b className="n-bad"> · {missing} never paid</b>}
              {calls && (
                <span className="muted">
                  {" "}
                  · {calls.calls} calls: {calls.booked} booked, {calls.replays} replayed
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
