import type { ReactNode } from "react";
import { OUTCOME_GLYPH } from "./outcomes";
import { TicketGlyph, type TicketKind } from "./TicketIcon";
import { shortTicket, workflowLink } from "./nexusLinks";
import type { FaultWindow, NexusRow, ProcStatus, RefundAttempt, Topology } from "./types";

// The run, as two teams and the one door between them. Support's box holds each refund's single Nexus call (a check once
// answered); payments' box holds the work behind it (a $ once the ledger books it, with its retry count underneath). The four failures are chips
// across the top, and each one also turns the box it hits red. No time axis: the point is where the failures land and who
// absorbs them, not when. Per-refund detail is on hover, and the team names open the histories in the Temporal UI.

// The gauntlet, in order (Engine.scene_nexus_kill). Muted before it lands, red while it's on, then "survived".
const PLANNED: { key: string; label: string }[] = [
  { key: "payments", label: "payments quiet" },
  { key: "support_worker", label: "support worker killed" },
  { key: "payments_worker", label: "payments worker killed" },
  { key: "temporal", label: "Temporal server killed" },
];

type FaultState = "next" | "on" | "survived" | "skipped";

function faultState(f: FaultWindow | undefined, now: number, finished: boolean): FaultState {
  if (f == null || f.start == null) return finished ? "skipped" : "next";
  return f.end == null || now < f.end ? "on" : "survived";
}

// Retries, not attempts: the same sum as the "Payments absorbed" tile (NexusPanel), so the badges add up to it.
export const retriesOf = (r: NexusRow) => Math.max(0, r.attempts.length - 1, (r.handler.peak_activity_attempt ?? 0) - 1);

// What support's workflow sees: its one operation. Not yet accepted by payments shows as in progress, not in flight.
function supportKind(r: NexusRow): TicketKind {
  if (r.state === "FAILED") return "failed";
  if (!r.live) return "done";
  return r.state === "STARTED" ? "paying" : "active";
}

function paymentsKind(r: NexusRow): TicketKind {
  if (r.state === "FAILED") return "failed";
  if (!r.live && r.ledger.booked_at != null) return "done";
  return r.attempts.length ? "paying" : "active";
}

function supportHover(r: NexusRow): string {
  const id = shortTicket(r.ticket);
  if (r.state === "FAILED") return `${id} · FAILED · ${r.last_failure || "the operation failed"}`;
  if (r.caller_saw_failure) return `${id} · ${r.state} · saw: ${r.last_failure}`;
  if (r.state === "SCHEDULED" || r.state === "BACKING_OFF") return `${id} · ${r.state} · payments hasn't accepted the call yet`;
  return `${id} · ${r.live ? "STARTED, waiting on payments" : "answered"} · no error`;
}

const timedOut = (a: RefundAttempt) => /StartToClose|timeout/i.test(a.failure);

function paymentsHover(r: NexusRow, t: Topology, now: number): string {
  const booked = r.ledger.booked_at;
  const replayed = (a: RefundAttempt) => booked != null && r.ledger.replays > 0 && a.started_at > booked && a.outcome === "ok";
  const lines = r.attempts.map((a) => {
    const secs = Math.round((a.ended_at ?? now) - a.started_at);
    const what =
      a.outcome === "failed"
        ? `✕ attempt ${a.n} ${timedOut(a) ? "timed out" : `failed after ${secs} s`}`
        : a.outcome === "ok"
          ? `${OUTCOME_GLYPH.ok} attempt ${a.n}${replayed(a) ? " · answered from the ledger" : ""}`
          : `attempt ${a.n}…`;
    return `${what}${a.failure ? ` · ${a.failure}` : ""}`;
  });
  return [
    `${shortTicket(r.ticket)} · ${t.payments.workflow} → ${t.payments.activity} · key refund-${r.ticket}`,
    ...lines,
    booked != null ? "$ the ledger booked it once" : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function Glyph({ kind }: { kind: TicketKind }) {
  return (
    <svg className="tk-glyph" viewBox="-10 -10 20 20" aria-hidden="true">
      <TicketGlyph kind={kind} />
    </svg>
  );
}

// The Temporal UI link for the first refund's history on one side, or the team's namespace list before any refund.
function historyLink(ui: string | null, r: NexusRow | undefined, side: "caller" | "handler", ns: string): string | null {
  if (!ui) return null;
  if (r && side === "caller") return workflowLink(ui, r.caller_namespace, r.caller_workflow_id, r.caller_run_id);
  if (r && r.handler.namespace && r.handler.workflow_id) return workflowLink(ui, r.handler.namespace, r.handler.workflow_id, r.handler.run_id);
  return `${ui}/namespaces/${encodeURIComponent(ns)}/workflows`;
}

function TeamHead({ name, ns, href }: { name: string; ns: string; href: string | null }) {
  return (
    <div className="tbox-head">
      <span className="tbox-name">{name}</span>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" title="Open in the Temporal UI">
          namespace <code>{ns}</code> ↗
        </a>
      ) : (
        <span className="muted">
          namespace <code>{ns}</code>
        </span>
      )}
    </div>
  );
}

// One plain line per team instead of process pills: red only while something is actually down.
function WorkerLine({ p, kills = 0, quiet = false }: { p?: ProcStatus; kills?: number; quiet?: boolean }) {
  if (!p) return <div className="tbox-worker" />;
  if (!p.alive) return <div className="tbox-worker bad">⚡ worker down</div>;
  if (quiet) return <div className="tbox-worker bad">⚡ payments service quiet</div>;
  return <div className="tbox-worker">{kills > 0 ? `worker killed ${kills === 1 ? "once" : `${kills} times`}, back up` : "worker up"}</div>;
}

function Status({ cls, children }: { cls: string; children: ReactNode }) {
  return <div className={`tbox-status ${cls}`}>{children}</div>;
}

export function NexusTeams({
  rows,
  t,
  ui,
  processes,
  faults,
  kills,
  now,
  finished,
  ran,
}: {
  rows: NexusRow[];
  t: Topology;
  ui: string | null;
  processes: Record<string, ProcStatus>;
  faults: FaultWindow[];
  kills: Record<string, number>;
  now: number;
  finished: boolean;
  ran: boolean;
}) {
  const sorted = [...rows].sort((a, b) => a.ticket.localeCompare(b.ticket));
  const byKey = new Map(faults.map((f) => [f.key, f]));
  const state = (key: string) => faultState(byKey.get(key), now, finished && ran);
  const down = (p?: ProcStatus) => p !== undefined && !p.alive;
  const open = rows.some((r) => r.live);
  const errors = rows.filter((r) => r.caller_saw_failure || r.state === "FAILED").length;
  const temporalDown = down(processes.temporal);
  const stalling = state("payments") === "on";

  return (
    <div className="teams">
      <div className="fchips" aria-label="The four failures, in order">
        {PLANNED.map((p) => {
          const s = state(p.key);
          return (
            <span key={p.key} className={`fchip ${s}`}>
              <span>⚡ {p.label}</span>
              <span className="fchip-state">{s === "on" ? "now" : s === "survived" ? "✓ survived" : s === "skipped" ? "skipped" : ""}</span>
            </span>
          );
        })}
      </div>

      <div className="teams-row">
        <div className={down(processes.support_worker) ? "tbox down" : "tbox"}>
          <TeamHead name="Support team" ns={t.support.namespace} href={historyLink(ui, sorted[0], "caller", t.support.namespace)} />
          <WorkerLine p={processes.support_worker} kills={kills.support_worker} />
          <div className="tickets">
            {sorted.length === 0 ? (
              <span className="tickets-empty">Press Run: five refunds start here.</span>
            ) : (
              sorted.map((r) => (
                <span key={r.ticket} className="tk" title={supportHover(r)}>
                  <Glyph kind={supportKind(r)} />
                </span>
              ))
            )}
          </div>
          {rows.length > 0 &&
            (errors ? (
              <Status cls="bad">✕ saw {errors} error{errors === 1 ? "" : "s"}</Status>
            ) : open ? (
              <Status cls="calm">waiting on one call each</Status>
            ) : (
              <Status cls="ok">{OUTCOME_GLYPH.ok} every call answered, no errors</Status>
            ))}
        </div>

        <div className="door-col">
          <span className={open ? "dwire busy" : "dwire"} aria-hidden="true" />
          <div className={temporalDown ? "door down" : "door"} title={`Endpoint ${t.endpoint}: the Temporal server routes ${t.operation} to the ${t.payments.namespace} namespace. Support knows only this name.`}>
            <span className="door-label">Nexus endpoint</span>
            <span className="door-op">
              <code>{t.operation}</code>
            </span>
          </div>
          <span className={open ? "dwire busy" : "dwire"} aria-hidden="true" />
        </div>

        <div className={down(processes.payments_worker) ? "tbox down" : "tbox"}>
          <TeamHead name="Payments team" ns={t.payments.namespace} href={historyLink(ui, sorted[0], "handler", t.payments.namespace)} />
          <WorkerLine p={processes.payments_worker} kills={kills.payments_worker} quiet={stalling} />
          <div className="tickets">
            {sorted.length === 0 ? (
              <span className="tickets-empty">…and each is paid here, once.</span>
            ) : (
              sorted.map((r) => {
                const n = retriesOf(r);
                const kind = paymentsKind(r);
                return (
                  <span key={r.ticket} className="tk" title={paymentsHover(r, t, now)}>
                    {kind === "done" ? <span className="tk-coin">$</span> : <Glyph kind={kind} />}
                    <span className="tk-retry">{n > 0 ? `↻${n}` : ""}</span>
                  </span>
                );
              })
            )}
          </div>
          {rows.length > 0 &&
            (open ? <Status cls="busy">retrying until it's booked…</Status> : <Status cls="ok">{OUTCOME_GLYPH.ok} all booked, once each</Status>)}
        </div>
      </div>

      <div className={temporalDown ? "tbar down" : "tbar"}>
        {temporalDown ? (
          <>⚡ Temporal server down: both sides pause, then resume where they were</>
        ) : (
          <>
            Temporal server · hosts both namespaces and the endpoint
            {(kills.temporal ?? 0) > 0 && <span className="tbar-kills"> · ⚡ killed during this run, both sides resumed</span>}
          </>
        )}
      </div>
    </div>
  );
}
