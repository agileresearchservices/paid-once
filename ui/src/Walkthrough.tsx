import { useEffect } from "react";
import { BEATS } from "./steps";

// The walkthrough's "thinking box". The scene is stopped on this step until it is dismissed, so the diagram behind it
// shows exactly what the box describes.
export function Walkthrough({ beat, onContinue }: { beat: string; onContinue: () => void }) {
  const i = BEATS.findIndex((b) => b.id === beat);
  const b = BEATS[i];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation(); // ArrowRight must not also change the page behind the box
        onContinue();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onContinue]);

  if (!b) return null;
  return (
    <aside className="beat" role="dialog" aria-label={`Step ${i + 1} of ${BEATS.length}: ${b.title}`}>
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
    </aside>
  );
}
