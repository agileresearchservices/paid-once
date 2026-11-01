import { useEffect } from "react";
import { BEATS, WALKTHROUGH_TICKET } from "./steps";
import { LegendIcon, type TicketKind } from "./TicketIcon";
import type { FlowDot, LaneId } from "./types";

// The walkthrough's panel, under the diagram on step 1: the refund as a support chat that grows one line per step, with the
// step's one-line explanation beside it. The scene is stopped on a step until it is dismissed, so the diagram above shows
// exactly what the chat says. Between steps (and before the first) the panel keeps its place with a hint, so the page
// doesn't jump. This page outlines the flow in general; it does not compare the two stacks.

function Typing() {
  return (
    <span className="typing" aria-label="typing">
      <i /><i /><i />
    </span>
  );
}

function Note({ kind, children }: { kind: TicketKind; children: string }) {
  return (
    <div className="chat-note">
      <LegendIcon kind={kind} /> {children}
    </div>
  );
}

// Whether the agent has handed the ticket on: both stacks show it waiting for a human.
function decided(flow: Record<LaneId, FlowDot[]> | undefined): boolean {
  const dots = flow ? [...flow.lane1, ...flow.lane2] : [];
  return dots.length >= 2 && dots.every((d) => d.state.startsWith("waiting"));
}

export function Walkthrough({
  beat,
  running,
  flow,
  onContinue,
}: {
  beat: string | null;
  running: boolean;
  flow?: Record<LaneId, FlowDot[]>;
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
            : "Press R to walk one ticket through. Space or → moves to the next step."}
        </p>
      </section>
    );
  }
  const { message, amount } = WALKTHROUGH_TICKET;
  const agentDone = i >= 2 || decided(flow);
  return (
    <section className="beat" aria-label={`Step ${i + 1} of ${BEATS.length}: ${b.title}`}>
      <div className="beat-head">
        <span className="beat-n">Step {i + 1} of {BEATS.length}</span>
        <h3>{b.title}</h3>
        <button className="primary" autoFocus onClick={onContinue}>
          {i === BEATS.length - 1 ? "Finish ✓" : "Continue →"} <kbd>space</kbd>
        </button>
      </div>
      <div className="beat-body">
        <div className="chat" role="log" aria-label="Support chat">
          <div className="chat-bar">
            <span className="chat-live" /> Support chat <span className="chat-sub">refund request · {amount}</span>
          </div>
          <div className="chat-msgs">
            <div className="msg customer">
              <span className="avatar">C</span>
              <p>{message}</p>
            </div>
            {i >= 1 && (
              <div className="msg agent">
                <span className="avatar">AI</span>
                <p>{agentDone ? `Within policy. I propose a ${amount} refund.` : <Typing />}</p>
              </div>
            )}
            {i >= 2 && <Note kind="waiting">Waiting for a human to approve</Note>}
            {i >= 3 && (
              <div className="msg human">
                <span className="avatar"><LegendIcon kind="waiting" /></span>
                <p>Approved.</p>
              </div>
            )}
            {i >= 4 && <Note kind="paying">{`Asking payments for ${amount}…`}</Note>}
            {i >= 5 && <Note kind="done">{`Refunded ${amount}. The ledger has it.`}</Note>}
          </div>
        </div>
        <p className="beat-line">{b.line}</p>
      </div>
    </section>
  );
}
