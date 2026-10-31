import { useCallback, useEffect, useRef, useState } from "react";
import { NexusPanel } from "./NexusPanel";
import { PaymentsStrip, ProcTile } from "./Processes";
import { Scoreboard } from "./Scoreboard";
import { STEPS } from "./steps";
import { Ticker } from "./Ticker";
import { post, useSnapshot } from "./useSnapshot";

const LANES = [
  { id: "lane1" as const, name: "Job queue", subtitle: "What most teams run today: queue, polling worker, in-memory agent state, HTTP to payments", procs: ["lane1_api", "lane1_worker"] },
  { id: "lane2" as const, name: "Temporal + Nexus", subtitle: "Durable workflow; support calls payments over Nexus", procs: ["support_worker", "payments_worker"] },
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

// Temporal's wordmark lives in ui/public/brand/, which is gitignored. On a fresh clone it isn't there and the
// header shows text instead.
function Wordmark() {
  const [missing, setMissing] = useState(false);
  if (missing) return <span className="wordmark-text">Temporal ·</span>;
  return <img className="wordmark" src="/brand/temporal-wordmark.svg" alt="Temporal" onError={() => setMissing(true)} />;
}

// The step lives in the URL hash (#1..#7), so a refresh mid-demo stays on the same step.
function stepFromHash(): number {
  const n = Number(window.location.hash.slice(1));
  return Number.isInteger(n) && n >= 1 && n <= STEPS.length ? n - 1 : 0;
}

export function App() {
  const { snap, connected } = useSnapshot();
  const [index, setIndex] = useState(stepFromHash);
  const [confirmReset, setConfirmReset] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resetTimer = useRef<number | undefined>(undefined);
  const step = STEPS[index];
  const running = snap?.running ?? true;

  const go = useCallback((delta: number) => {
    setIndex((i) => Math.min(STEPS.length - 1, Math.max(0, i + delta)));
  }, []);

  useEffect(() => {
    window.history.replaceState(null, "", `#${index + 1}`);
  }, [index]);

  useEffect(() => {
    const onHash = () => setIndex(stepFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const act = useCallback(async (path: string) => {
    try {
      setError(null);
      await post(path);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  // Arrows step, 1-7 jump, R runs this step's scene.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (/^[1-9]$/.test(e.key) && Number(e.key) <= STEPS.length) setIndex(Number(e.key) - 1);
      else if ((e.key === "r" || e.key === "R") && step.scene && !running) void act(`/api/scenes/${step.scene}/run`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, act, step.scene, running]);

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

  const thisRunning = running && snap.current === step.scene;
  const run = step.scene ? snap.scene_runs?.[step.scene] : undefined;
  const finished = !thisRunning && run?.finished_at != null;
  const settling = snap.audit.lane1.in_flight + snap.audit.lane2.in_flight > 0;
  const elapsed = run ? Math.max(0, Math.round(snap.now - run.started_at)) : 0;
  let status: { text: string; cls: string } | null = null;
  if (finished && run?.ok === false) status = { text: "Scene failed: see the ticker", cls: "fail" };
  else if (finished && settling) status = { text: "Done, settling…", cls: "muted" };
  else if (finished) status = { text: "Done ✓", cls: "ok" };
  const recentFault = [...snap.events].reverse().find((e) => e.kind === "fault" && snap.now - e.ts < 6);

  return (
    <main>
      <header>
        <h1>
          <Wordmark /> Paid Once <span className="tagline">Refunds over Nexus</span>
        </h1>
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
          {finished && step.result && <p className="result"><b>Result:</b> {step.result}</p>}
        </div>
        <div className="controls">
          {step.scene && (
            <button className="primary" disabled={running} onClick={() => void act(`/api/scenes/${step.scene}/run`)}>
              {thisRunning ? `Running ${elapsed}s…` : running ? "Another scene is running" : finished ? "Run again (R)" : "Run this scene (R)"}
            </button>
          )}
          {status && <p className={`scene-status ${status.cls}`} role="status">{status.text}</p>}
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

      {recentFault && <div className="fault-banner" role="status">⚡ {recentFault.msg}</div>}

      {step.nexus && (
        <NexusPanel
          rows={snap.nexus}
          topology={snap.topology}
          temporalUi={snap.temporal_ui}
          paymentsWorker={snap.processes.payments_worker}
        />
      )}

      <PaymentsStrip proc={snap.processes.payments} faults={snap.faults} />

      {step.nexus ? (
        // The Nexus scene only runs the Temporal lane, so the lanes shrink to one strip and the panel keeps the screen.
        <div className="lanes compact">
          <article className="lane lane-off">
            <h2>Job queue</h2>
            <span className="muted">not part of this scene</span>
          </article>
          <article className="lane lane2">
            <h2>Temporal + Nexus</h2>
            <div className="tiles">
              {LANES[1].procs.map((p) => snap.processes[p] && <ProcTile key={p} p={snap.processes[p]} kills={run?.kills?.[p]} />)}
            </div>
            <div className="believes">
              <span className="muted">Workflows:</span> <Chips counts={snap.lane2_view} empty="nothing yet" />
            </div>
          </article>
        </div>
      ) : (
        <div className="lanes">
          {LANES.map((l) => (
            <article key={l.id} className={`lane ${l.id}`}>
              <h2>{l.name}</h2>
              <p className="muted">{l.subtitle}</p>
              <div className="tiles">
                {l.procs.map((p) => snap.processes[p] && <ProcTile key={p} p={snap.processes[p]} kills={run?.kills?.[p]} />)}
              </div>
              <div className="believes">
                <span className="muted">{l.id === "lane1" ? "Its own job table:" : "Temporal workflow status (this scene):"}</span>{" "}
                <Chips counts={l.id === "lane1" ? snap.lane1_view : snap.lane2_view} empty="nothing yet" />
              </div>
              <Scoreboard audit={snap.audit[l.id]} name={l.name} />
            </article>
          ))}
        </div>
      )}

      {!step.nexus && <Ticker events={snap.events} />}
    </main>
  );
}
