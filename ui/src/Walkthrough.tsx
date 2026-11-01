import { useEffect } from "react";
import { BEATS } from "./steps";

// The walkthrough's explanation panel, under the diagram on step 1. The scene is stopped on a step until it is
// dismissed, so the diagram above shows exactly what the panel describes. Between steps (and before the first) the
// panel keeps its place with a hint, so the page doesn't jump.
export function Walkthrough({
  beat,
  running,
  onContinue,
}: {
  beat: string | null;
  running: boolean;
  onContinue: () => void;
}) {
  const i = BEATS.findIndex((b) => b.id === beat);
  const b = BEATS[i];

  useEffect(() => {
    if (!b) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation(); // ArrowRight must not also change the page behind the panel
        onContinue();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [b, onContinue]);

  if (!b) {
    return (
      <section className="beat idle" aria-label="Walkthrough">
        <p>
          {running
            ? "Working on the next step…"
            : "Walk through one ticket (R) sends a single approved refund through both stacks and stops at each step. The explanation appears here; Space or → moves on."}
        </p>
      </section>
    );
  }
  return (
    <section className="beat" aria-label={`Step ${i + 1} of ${BEATS.length}: ${b.title}`}>
      <div className="beat-head">
        <span className="beat-n">Step {i + 1} of {BEATS.length}</span>
        <h3>{b.title}</h3>
        <button className="primary" autoFocus onClick={onContinue}>
          {i === BEATS.length - 1 ? "Finish ✓" : "Continue →"} <kbd>space</kbd>
        </button>
      </div>
      <p className="beat-intro">{b.intro}</p>
      <div className="beat-cols">
        <div>
          <b>Queue + LangGraph</b>
          <p>{b.queue}</p>
        </div>
        <div className="t">
          <b>Temporal + Nexus</b>
          <p>{b.temporal}</p>
        </div>
      </div>
    </section>
  );
}
