import { NexusContract } from "./NexusContract";
import { NexusTeams, retriesOf } from "./NexusTeams";
import { NexusWhy } from "./NexusWhy";
import type { NexusRow, ProcStatus, SceneRun, Topology } from "./types";

// Page 6: why Nexus (two static pictures), the contract in one strip, then the run as two teams and the one door between them, then the receipts
// from the ledger. The receipts read the audit, never the lane's own state.

export function NexusPanel({
  rows,
  ran,
  topology,
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
  processes: Record<string, ProcStatus>;
  run?: SceneRun;
  finished: boolean;
  now: number;
  ledgerTickets: Record<string, string>; // the ledger's verdict per ticket (audit), every scene since reset
  calls?: { calls: number; booked: number; replays: number }; // this scene's calls to payments, counted by payments
}) {
  const faults = ran ? (run?.faults ?? []) : [];
  const allClosed = rows.length > 0 && rows.every((r) => !r.live && r.attempts.every((a) => a.outcome !== "running"));

  // This run's tickets, by the ledger (audit), never by the lane's own state.
  const scene = ran ? sceneTickets(ledgerTickets) : [];
  const paidOnce = scene.filter(([, v]) => v === "ok").length;
  const paidTwice = scene.filter(([, v]) => v === "duplicate").length;
  const missing = scene.filter(([, v]) => v === "missing").length;
  const errors = rows.filter((r) => r.caller_saw_failure || r.state === "FAILED").length;
  const retries = rows.reduce((n, r) => n + retriesOf(r), 0);
  const show = finished && allClosed;

  return (
    <section className="nexus" aria-label="Nexus">
      <NexusWhy t={topology} />

      <NexusContract t={topology} />

      <NexusTeams
        rows={rows}
        t={topology}
        processes={processes}
        faults={faults}
        kills={ran && run ? run.kills : {}}
        now={now}
        finished={finished}
        ran={ran}
      />

      <div className="headline payoff">
        <div>
          <span className="headline-label">Support saw</span>
          {show ? (
            <>
              <b className={errors ? "n-bad" : "n-good"}>{errors}</b> error{errors === 1 ? "" : "s"}
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div>
          <span className="headline-label">Payments absorbed</span>
          {show ? (
            <>
              <b>{retries}</b> retr{retries === 1 ? "y" : "ies"}
            </>
          ) : (
            <b className="muted">…</b>
          )}
        </div>
        <div title={calls ? `${calls.calls} calls to payments: ${calls.booked} paid, ${calls.replays} answered from the ledger` : undefined}>
          <span className="headline-label">The ledger</span>
          {show ? (
            <>
              <b className={paidTwice || missing ? "n-bad" : "n-good"}>{paidOnce}</b> paid once
              {paidTwice > 0 && <b className="n-bad"> · {paidTwice} paid twice</b>}
              {missing > 0 && <b className="n-bad"> · {missing} never paid</b>}
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
