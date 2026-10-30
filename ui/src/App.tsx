import { useCallback, useEffect, useRef, useState } from "react";
import { NexusPanel } from "./NexusPanel";
import { PaymentsStrip, ProcTile } from "./Processes";
import { Scoreboard } from "./Scoreboard";
import { STEPS } from "./steps";
import { Ticker } from "./Ticker";
import { post, useSnapshot } from "./useSnapshot";

const LANES = [
  { id: "lane1" as const, name: "Lane 1", subtitle: "Today: job queue, polling loop, plain HTTP", procs: ["lane1_api", "lane1_worker"] },
  { id: "lane2" as const, name: "Lane 2", subtitle: "Temporal, with the refund exposed over Nexus", procs: ["support_worker", "payments_worker"] },
];

function Chips({ counts, empty }: { counts: Record<string, number>; empty: string }) {
  const entries = Object.entries(counts);
  if (!entries.length) return <span className="muted">{empty}</span>;
  return (
    <>
      {entries.map(([k, v]) => (
        <span className="chip" key={k}>{k.toLowerCase().replace(/_/g, " ")} {v}</span>
      ))}
    </>
  );
}

export function App() {
  const { snap, connected } = useSnapshot();
  const [index, setIndex] = useState(0);
  const [confirmReset, setConfirmReset] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resetTimer = useRef<number | undefined>(undefined);
  const step = STEPS[index];

  const go = useCallback((delta: number) => {
    setIndex((i) => Math.min(STEPS.length - 1, Math.max(0, i + delta)));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1);
      if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  const act = async (path: string) => {
    try {
      setError(null);
      await post(path);
    } catch (e) {
      setError(String(e));
    }
  };

  const onReset = () => {
    if (!confirmReset) {
      setConfirmReset(true);
      window.clearTimeout(resetTimer.current);
      resetTimer.current = window.setTimeout(() => setConfirmReset(false), 3000);
      return;
    }
    setConfirmReset(false);
    void act("/api/reset");
  };

  if (!snap) {
    return <main className="loading">{connected ? "Loading…" : "Waiting for the show server on port 8100…"}</main>;
  }

  const running = snap.running;
  const thisRunning = running && snap.current === step.scene;
  const recentRaccoon = [...snap.events].reverse().find((e) => e.kind === "raccoon" && snap.now - e.ts < 6);

  return (
    <main>
      <header>
        <h1>🦝 refund-raccoon</h1>
        <nav aria-label="Steps">
          {STEPS.map((s, i) => (
            <button key={s.id} className={i === index ? "step on" : "step"} onClick={() => setIndex(i)} aria-current={i === index}>
              <b>{i + 1}</b> {s.short}
            </button>
          ))}
        </nav>
        {!connected && <span className="chip warn">reconnecting…</span>}
      </header>

      <section className="story">
        <div className="story-text">
          <h2>{step.title}</h2>
          <p>{step.story}</p>
          <p className="watch"><b>Watch:</b> {step.watch}</p>
        </div>
        <div className="controls">
          {step.scene && (
            <button className="primary" disabled={running} onClick={() => void act(`/api/scenes/${step.scene}/run`)}>
              {thisRunning ? "Running…" : running ? "Another scene is running" : "Run this scene"}
            </button>
          )}
          <div className="nav">
            <button onClick={() => go(-1)} disabled={index === 0}>← Back</button>
            <button onClick={() => go(1)} disabled={index === STEPS.length - 1}>Next →</button>
          </div>
          <button className={confirmReset ? "danger" : ""} onClick={onReset}>
            {confirmReset ? "Click again to reset" : "Reset scoreboard"}
          </button>
          {error && <p className="fail" role="alert">{error}</p>}
        </div>
      </section>

      {recentRaccoon && <div className="raccoon-banner" role="status">{recentRaccoon.msg}</div>}

      <PaymentsStrip proc={snap.processes.payments} faults={snap.faults} />

      <div className="lanes">
        {LANES.map((l) => (
          <article key={l.id} className="lane">
            <h2>{l.name}</h2>
            <p className="muted">{l.subtitle}</p>
            <div className="tiles">
              {l.procs.map((p) => snap.processes[p] && <ProcTile key={p} p={snap.processes[p]} />)}
            </div>
            <div className="believes">
              <span className="muted">{l.id === "lane1" ? "Its own job table:" : "Temporal workflow status (this scene):"}</span>{" "}
              <Chips counts={l.id === "lane1" ? snap.lane1_view : snap.lane2_view} empty="nothing yet" />
            </div>
            <Scoreboard audit={snap.audit[l.id]} name={l.name} />
          </article>
        ))}
      </div>

      {step.nexus && <NexusPanel rows={snap.nexus} />}

      <Ticker events={snap.events} />
    </main>
  );
}
