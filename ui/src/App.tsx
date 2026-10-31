import { useCallback, useEffect, useRef, useState } from "react";
import { Compare } from "./Architecture";
import { Diagram } from "./Diagram";
import { NexusPanel } from "./NexusPanel";
import { Scoreboard } from "./Scoreboard";
import { STEPS } from "./steps";
import { Ticker } from "./Ticker";
import { post, useSnapshot } from "./useSnapshot";

const LANES = [
  { id: "lane1" as const, name: "Job queue", subtitle: "What most teams run today: queue, polling worker, in-memory agent state, HTTP to payments" },
  { id: "lane2" as const, name: "Temporal + Nexus", subtitle: "Durable workflow; support calls payments over Nexus" },
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

// What payments saw from this lane in this scene: a retry that reuses the key is answered from the ledger.
function PaymentsCalls({ c }: { c?: { calls: number; booked: number; replays: number } }) {
  if (!c || c.calls === 0) return null;
  return (
    <div className="calls">
      <span className="muted">Payments got</span> <b>{c.calls}</b> calls · booked <b>{c.booked}</b> · answered{" "}
      <b>{c.replays}</b> from the ledger
    </div>
  );
}

// Temporal's wordmark lives in ui/public/brand/, which is gitignored. On a fresh clone it isn't there and the
// header shows text instead.
function Wordmark() {
  const [missing, setMissing] = useState(false);
  if (missing) return <span className="wordmark-text">Temporal ·</span>;
  return <img className="wordmark" src="/brand/temporal-wordmark.svg" alt="Temporal" onError={() => setMissing(true)} />;
}

// The step lives in the URL hash (#1..#8), so a refresh mid-demo stays on the same step.
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
  const locked = snap?.locked ?? null; // `make scenario` owns this server: look, don't touch

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

  // Arrows step, 1-8 jump, R runs this step's scene.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (/^[1-9]$/.test(e.key) && Number(e.key) <= STEPS.length) setIndex(Number(e.key) - 1);
      else if ((e.key === "r" || e.key === "R") && step.scene && !running && !locked) void act(`/api/scenes/${step.scene}/run`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, act, step.scene, running, locked]);

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

  // Scene-scoped views (Nexus rows, workflow status, payments calls) describe the scene the engine last ran,
  // so a step shows them only when that scene is this step's.
  const onScreen = step.scene != null && snap.current === step.scene;
  const thisRunning = running && onScreen;
  const run = step.scene ? snap.scene_runs?.[step.scene] : undefined;
  const finished = !thisRunning && run?.finished_at != null;
  const settling = snap.audit.lane1.in_flight + snap.audit.lane2.in_flight > 0;
  const elapsed = run ? Math.max(0, Math.round(snap.now - run.started_at)) : 0;
  let status: { text: string; cls: string } | null = null;
  if (finished && run?.ok === false) status = { text: "Scene failed: see the ticker", cls: "fail" };
  else if (finished && settling) status = { text: "Done, settling…", cls: "muted" };
  else if (finished) status = { text: "Done ✓", cls: "ok" };

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

      {locked && (
        <p className="locked-banner" role="status">
          <b>This is not the demo.</b> <code>{locked}</code> is running on this server, so Run and Reset are off. The demo
          comes back when it ends.
        </p>
      )}

      <section className="story">
        <div className="story-text">
          <h2>{step.title}</h2>
          <p>{step.story}</p>
          <p className="watch"><b>Watch:</b> {step.watch}</p>
          {/* Laid out before the scene finishes, so the page doesn't jump when the result appears */}
          {step.result && (
            <p className={finished ? "result" : "result pending"} aria-hidden={!finished}>
              <b>Result:</b> {step.result}
            </p>
          )}
        </div>
        <div className="controls">
          {step.scene && (
            <button className="primary" disabled={running || !!locked} onClick={() => void act(`/api/scenes/${step.scene}/run`)}>
              {locked ? "Locked by the test run" : thisRunning ? `Running ${elapsed}s…` : running ? "Another scene is running" : finished ? "Run again (R)" : "Run this scene (R)"}
            </button>
          )}
          {status && <p className={`scene-status ${status.cls}`} role="status">{status.text}</p>}
          <div className="nav">
            <button onClick={() => go(-1)} disabled={index === 0}>← Back</button>
            <button onClick={() => go(1)} disabled={index === STEPS.length - 1}>Next →</button>
          </div>
          <button className={confirmReset ? "danger" : ""} onClick={onReset} disabled={!!locked}>
            {confirmReset ? "Click again to reset" : "Reset scoreboard"}
          </button>
          {error && <p className="fail" role="alert">{error}</p>}
        </div>
      </section>

      {step.nexus && (
        <NexusPanel
          rows={onScreen ? snap.nexus : []}
          ran={onScreen}
          topology={snap.topology}
          temporalUi={snap.temporal_ui}
          processes={snap.processes}
          run={run}
          finished={finished}
          events={snap.events}
          now={snap.now}
          ledgerTickets={snap.audit.lane2.tickets ?? {}}
          calls={onScreen ? snap.payments_calls?.lane2 : undefined}
        />
      )}

      {(step.arch || (step.scene && !step.nexus)) && <Diagram snap={snap} scene={step.scene} />}

      {step.arch ? (
        <Compare />
      ) : step.nexus ? null : (
        <div className="lanes">
          {LANES.map((l) => (
            <article key={l.id} className={`lane ${l.id}`}>
              <h2>{l.name}</h2>
              <p className="muted">{l.subtitle}</p>
              {step.scene && (
                <div className="believes">
                  <span className="muted">{l.id === "lane1" ? "Its own job table (this scene):" : "Temporal workflow status (this scene):"}</span>{" "}
                  <Chips counts={onScreen ? (l.id === "lane1" ? snap.lane1_view : snap.lane2_view) : {}} empty="nothing yet" />
                  <PaymentsCalls c={onScreen ? snap.payments_calls?.[l.id] : undefined} />
                </div>
              )}
              <Scoreboard
                audit={snap.audit[l.id]}
                name={l.name}
                believedDone={!step.scene && l.id === "lane1" ? (snap.lane1_view_all?.done ?? 0) : undefined}
                note={l.id === "lane2" && snap.scene_runs?.nexus_kill ? "Includes the Nexus scene, which runs on Temporal only." : undefined}
              />
            </article>
          ))}
        </div>
      )}

      {/* Scene steps show faults on the diagram, so the event log only appears on the scoreboard. */}
      {!step.scene && !step.arch && <Ticker events={snap.events} />}
    </main>
  );
}
