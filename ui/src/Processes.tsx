import type { FaultState, LaneId, ProcStatus } from "./types";

// `kills` counts only the scene on screen, so a step never shows kills from another scene.
export function ProcTile({ p, kills = 0 }: { p: ProcStatus; kills?: number }) {
  return (
    <div className={`tile ${p.alive ? "up" : "down"}`}>
      <span className="dot" aria-hidden="true" />
      <span className="tile-label">{p.label}</span>
      <span className="tile-state">{p.alive ? "UP" : "DOWN"}</span>
      {kills > 0 && (
        <span className="tile-kills" title="kill -9 during this scene">
          ⚡ killed {kills === 1 ? "once" : `${kills} times`}
        </span>
      )}
    </div>
  );
}

function faultText(f: FaultState | undefined): string | null {
  if (!f) return null;
  const bits: string[] = [];
  if (f.mode === "commit_then_stall" && f.remaining > 0)
    bits.push(`commits, then stalls ${f.delay_s}s (×${f.remaining} left)`);
  if (f.latency_s > 0) bits.push(`${f.latency_s}s added latency`);
  return bits.length ? bits.join(" · ") : null;
}

export function PaymentsStrip({
  proc,
  faults,
}: {
  proc?: ProcStatus;
  faults: Partial<Record<LaneId, FaultState>>;
}) {
  const f1 = faultText(faults.lane1);
  const f2 = faultText(faults.lane2);
  return (
    <div className="payments-strip">
      {proc && <ProcTile p={proc} />}
      <span className="faults">
        {f1 || f2 ? (
          <>
            {f1 && <span className="chip warn">Queue: {f1}</span>}
            {f2 && <span className="chip warn">Temporal: {f2}</span>}
          </>
        ) : (
          <span className="chip">payments healthy</span>
        )}
      </span>
    </div>
  );
}
