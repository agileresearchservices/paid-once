import type { ShowEvent } from "./types";

const ICON: Record<string, string> = {
  fault: "⚡",
  human: "🙋",
  scene: "▶",
  scene_done: "■",
  error: "✕",
  reset: "↺",
  boot: "·",
  note: "·",
};

export function Ticker({ events }: { events: ShowEvent[] }) {
  const shown = events.slice(-8).reverse();
  return (
    <ol className="ticker" aria-label="Event log">
      {shown.map((e, i) => (
        <li key={`${e.ts}-${i}`} className={e.kind}>
          <time>{new Date(e.ts * 1000).toLocaleTimeString([], { hour12: false })}</time>
          <span aria-hidden="true">{ICON[e.kind] ?? "·"}</span> {e.msg}
        </li>
      ))}
    </ol>
  );
}
