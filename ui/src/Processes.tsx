import type { ProcStatus } from "./types";

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
