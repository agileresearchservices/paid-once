import { useCallback, useEffect, useRef, useState } from "react";
import { Diagram } from "./Diagram";
import { NexusPanel } from "./NexusPanel";
import { Scoreboard } from "./Scoreboard";
import { STEPS } from "./steps";
import { post, useSnapshot } from "./useSnapshot";
import { Walkthrough } from "./Walkthrough";

const LANES = [
  { id: "lane1" as const, name: "Queue + LangGraph", subtitle: "What most teams run today" },
  { id: "lane2" as const, name: "Temporal + Nexus", subtitle: "Durable workflow, payments over Nexus" },
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
      <span className="muted">Payments:</span> <b>{c.calls}</b> calls · <b>{c.booked}</b> booked · <b>{c.replays}</b> replayed
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

  const beat = snap?.beat && snap.beat.scene === step.scene ? snap.beat.id : null;

  // Pressing Run on a scene step: scroll down so the diagram and the scoreboards below it are on screen together, and
  // stop at the diagram's top (the explanation above may scroll away). The first step does its own scrolling (Walkthrough).
  const sceneRunning = !!snap && snap.running && step.scene != null && snap.current === step.scene;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (sceneRunning && !wasRunning.current && !step.arch) {
      const first = document.querySelector<HTMLElement>(".diagram, .nexus");
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      if (first) {
        const target = Math.min(maxScroll, window.scrollY + first.getBoundingClientRect().top - 8);
        if (target > window.scrollY) window.scrollTo({ top: target, behavior: "smooth" });
      }
    }
    wasRunning.current = sceneRunning;
  }, [sceneRunning, step.arch]);

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
  if (finished && run?.ok === false) status = { text: `Scene failed: ${run.error ?? "see the server log"}`, cls: "fail" };
  else if (finished && settling) status = { text: "Done, settling…", cls: "muted" };
  else if (finished) status = { text: "Done ✓", cls: "ok" };

  return (
    <main className={step.arch ? "fill" : undefined}>
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
          {step.watch && <p className="watch"><b>Watch:</b> {step.watch}</p>}
          {/* Shown from the start, next to "Watch", so the viewer knows the outcome while the scene plays and why it happens */}
          {step.result && (
            <p className="result">
              <b>Result:</b> {step.result}
            </p>
          )}
        </div>
        <div className="controls">
          {step.scene && (
            <button className="primary" disabled={running || !!locked} onClick={() => void act(`/api/scenes/${step.scene}/run`)}>
              {locked ? "Locked by the test run" : thisRunning ? `Running ${elapsed}s…` : running ? "Another scene is running" : finished ? "Run again (R)" : `${step.runLabel ?? "Run this scene"} (R)`}
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
          now={snap.now}
          ledgerTickets={snap.audit.lane2.tickets ?? {}}
          calls={onScreen ? snap.payments_calls?.lane2 : undefined}
        />
      )}

      {(step.arch || (step.scene && !step.nexus)) && <Diagram snap={snap} scene={step.scene} />}

      {step.arch ? (
        <Walkthrough beat={beat} flow={onScreen ? snap.flow : undefined} />
      ) : step.nexus ? null : (
        <div className="lanes">
          {LANES.map((l) => (
            <article key={l.id} className={step.scene ? `lane ${l.id} compact` : `lane ${l.id}`}>
              {step.scene ? (
                // A scene step is read from across a room while it runs: name and what the stack believes on one line,
                // so the diagram and both scoreboards fit one screen.
                <div className="lane-head">
                  <h2>{l.name}</h2>
                  <div className="believes">
                    <span className="muted">{l.id === "lane1" ? "Job table:" : "Workflow status:"}</span>{" "}
                    <Chips counts={onScreen ? (l.id === "lane1" ? snap.lane1_view : snap.lane2_view) : {}} empty="nothing yet" />
                    <PaymentsCalls c={onScreen ? snap.payments_calls?.[l.id] : undefined} />
                  </div>
                </div>
              ) : (
                <>
                  <h2>{l.name}</h2>
                  <p className="muted">{l.subtitle}</p>
                </>
              )}
              <Scoreboard
                compact={!!step.scene}
                audit={snap.audit[l.id]}
                name={l.name}
                believedDone={!step.scene && l.id === "lane1" ? (snap.lane1_view_all?.done ?? 0) : undefined}
                note={l.id === "lane2" && snap.scene_runs?.nexus_kill ? "Includes the Nexus scene (Temporal only)." : undefined}
              />
            </article>
          ))}
        </div>
      )}

      {/* Scene steps show faults on the diagram, so the event log only appears on the scoreboard. */}
    </main>
  );
}
