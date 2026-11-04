import type { ReactNode } from "react";
import { OUTCOME_GLYPH } from "./outcomes";
import { TicketGlyph, type TicketKind } from "./TicketIcon";
import { shortTicket } from "./tickets";
import type { FaultWindow, NexusRow, ProcStatus, RefundAttempt, Topology } from "./types";

// The run, as two teams and the one door between them. Support's box holds each refund's single Nexus call (a check
// once answered); payments' box holds the work behind it (a $ once the ledger has paid it, with its retry count
// underneath). The four failures are chips across the top, and each one also marks where it lands: a worker kill
// reddens its team's box, the payments stall the payments worker line, the Temporal kill the door and the bar under it.
// No time axis: the point is where the failures land and who absorbs them, not when. Per-refund detail is on hover.

// The gauntlet, in order (Engine.scene_nexus_kill). Muted before it lands, red while it's on, then "survived".
const PLANNED: { key: string; label: string }[] = [
  { key: "payments", label: "payments quiet" },
  { key: "support_worker", label: "support worker killed" },
  { key: "payments_worker", label: "payments worker killed" },
  { key: "temporal", label: "Temporal server killed" },
];

type ChipState = "next" | "on" | "survived" | "skipped";

// A chip's state from its fault window. `on` while the window lasts (the chip says "now"), `survived` once it has
// an end, and `next` before it opens. `skipped` when the scene has finished and the window never opened, such as the
// Temporal kill when the show did not start that server. A stall's start is filled in from the ledger once its first
// refund is booked (stall_window in timeline.py), so the payments chip reads `next` until then.
function faultState(f: FaultWindow | undefined, now: number, finished: boolean): ChipState {
  if (f == null || f.start == null) return finished ? "skipped" : "next";
  return f.end == null || now < f.end ? "on" : "survived";
}

// Retries, not attempts: the same sum as the "Payments absorbed" tile (NexusPanel), so the badges add up to it.
export const retriesOf = (r: NexusRow) => Math.max(0, r.attempts.length - 1, (r.handler.peak_activity_attempt ?? 0) - 1);

// What support's workflow sees: its one operation. Not yet accepted by payments shows as in progress, not in flight.
// Its badge: failed; done once the operation has closed; paying (the arrow) once payments has accepted the call
// (STARTED); active (the ring) before that.
function supportKind(r: NexusRow): TicketKind {
  if (r.state === "FAILED") return "failed";
  if (!r.live) return "done";
  return r.state === "STARTED" ? "paying" : "active";
}

// Payments' badge, from the same row: failed; done once the operation has closed and the ledger has booked the refund
// (drawn as the `$` coin, not the check); paying once an attempt has started; active (the ring) while nothing has
// reached payments.
function paymentsKind(r: NexusRow): TicketKind {
  if (r.state === "FAILED") return "failed";
  if (!r.live && r.ledger.booked_at != null) return "done";
  return r.attempts.length ? "paying" : "active";
}

// Support's hover line: the operation's state. A call that has seen an error shows it (`caller_saw_failure` stays set
// once it has), and a scheduled or backing-off call says payments has not accepted it yet.
function supportHover(r: NexusRow): string {
  const id = shortTicket(r.ticket);
  if (r.state === "FAILED") return `${id} · FAILED · ${r.last_failure || "the operation failed"}`;
  if (r.caller_saw_failure) return `${id} · ${r.state} · saw: ${r.last_failure}`;
  if (r.state === "SCHEDULED" || r.state === "BACKING_OFF") return `${id} · ${r.state} · payments hasn't accepted the call yet`;
  return `${id} · ${r.live ? "STARTED, waiting on payments" : "answered"} · no error`;
}

// An attempt whose failure says StartToClose or timeout ran past its limit rather than erroring. merge_attempts
// (timeline.py) keys on StartToClose alone; this also takes any failure text that says timeout.
const timedOut = (a: RefundAttempt) => /StartToClose|timeout/i.test(a.failure);

// Payments' hover text, one line per attempt of the refund activity: a failure (a timeout reads as "timed out"), a
// success (marked "answered from the ledger" when it started after the booking and the ledger counted a replay), or
// "…" while it runs or when its outcome is unknown. The first line names the workflow, the activity and the key every
// attempt sends (refund-<ticket>). Once booked, a last line reads `$ the ledger paid it once`.
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
    booked != null ? "$ the ledger paid it once" : "",
  ]
    .filter(Boolean)
    .join("\n");
}

// The badge for one refund's kind (TicketIcon.tsx), drawn 40 px square (`.tk-glyph`).
function Glyph({ kind }: { kind: TicketKind }) {
  return (
    <svg className="tk-glyph" viewBox="-10 -10 20 20" aria-hidden="true">
      <TicketGlyph kind={kind} />
    </svg>
  );
}

// The team's name, in the header row of its box.
function TeamHead({ name }: { name: string }) {
  return (
    <div className="tbox-head">
      <span className="tbox-name">{name}</span>
    </div>
  );
}

// One plain line per team instead of process pills: red while the worker is down, or while payments is quiet.
function WorkerLine({ p, kills = 0, quiet = false }: { p?: ProcStatus; kills?: number; quiet?: boolean }) {
  if (!p) return <div className="tbox-worker" />;
  if (!p.alive) return <div className="tbox-worker bad">⚡ worker down</div>;
  if (quiet) return <div className="tbox-worker bad">⚡ payments service quiet</div>;
  return <div className="tbox-worker">{kills > 0 ? `worker killed ${kills === 1 ? "once" : `${kills} times`}, back up` : "worker up"}</div>;
}

// The line at the foot of a team box. `cls` sets its colour: bad, calm, ok or busy (`.tbox-status` in styles.css).
function Status({ cls, children }: { cls: string; children: ReactNode }) {
  return <div className={`tbox-status ${cls}`}>{children}</div>;
}

// Draws the run: the four failure chips (`PLANNED`) across the top; the support box and the payments box, one badge
// per refund in each; the Nexus endpoint between them; and the Temporal bar at the foot. Reads `rows` (the scene's
// Nexus operations, snap.nexus), `t` (the topology: the names on the door and in the hovers), `processes` (which
// workers and the Temporal server are alive), `faults` and `kills` (this run's fault windows and kill counts), and
// `now` (for the attempts' times), `finished` and `ran` (for the chip states).
export function NexusTeams({
  rows,
  t,
  processes,
  faults,
  kills,
  now,
  finished,
  ran,
}: {
  rows: NexusRow[];
  t: Topology; // the endpoint, operation and payments names
  processes: Record<string, ProcStatus>; // by name: support_worker, payments_worker, temporal
  faults: FaultWindow[]; // this run's fault windows
  kills: Record<string, number>; // kill -9s this run, by process
  now: number;
  finished: boolean; // this scene's run is over
  ran: boolean; // this scene is the one the engine last ran; otherwise the chips stay next and the boxes empty
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
          <TeamHead name="Support team" />
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
          <TeamHead name="Payments team" />
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
            (open ? <Status cls="busy">retrying until it's paid…</Status> : <Status cls="ok">{OUTCOME_GLYPH.ok} all paid, once each</Status>)}
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
