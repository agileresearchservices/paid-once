import { useEffect, useRef, type ReactNode } from "react";
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

// One line in a pane: an icon and a sentence.
function Row({ kind, children }: { kind: TicketKind; children: ReactNode }) {
  return (
    <div className="pane-row">
      <LegendIcon kind={kind} /> <span>{children}</span>
    </div>
  );
}

// A pane is one role's window: it shows only what that role sees.
function Pane({ who, avatar, children }: { who: string; avatar: ReactNode; children: ReactNode }) {
  return (
    <div className="pane" role="log" aria-label={who}>
      <div className="pane-bar"><span className="avatar">{avatar}</span> {who}</div>
      <div className="pane-body">{children}</div>
    </div>
  );
}

// Whether the agent has handed the ticket on: both stacks show it waiting for a human.
function decided(flow: Record<LaneId, FlowDot[]> | undefined): boolean {
  const dots = flow ? [...flow.lane1, ...flow.lane2] : [];
  return dots.length >= 2 && dots.every((d) => d.state.startsWith("waiting"));
}

// Whether both stacks show the ticket refunded.
function refunded(flow: Record<LaneId, FlowDot[]> | undefined): boolean {
  const dots = flow ? [...flow.lane1, ...flow.lane2] : [];
  return dots.length >= 2 && dots.every((d) => d.state === "refunded");
}

export function Walkthrough({
  beat,
  flow,
  onContinue,
}: {
  beat: string | null;
  flow?: Record<LaneId, FlowDot[]>;
  onContinue: () => void;
}) {
  // Between steps the chat stays as it was, without a button, so the panel never flashes a message or jumps.
  const last = useRef(-1);
  const at = BEATS.findIndex((b) => b.id === beat);
  if (at >= 0) last.current = at;
  else if (!flow) last.current = -1; // reset, or another scene is on screen: back to the hint
  const i = last.current;
  const b = BEATS[i];
  const shown = at >= 0; // a step is up
  const gated = shown && at < BEATS.length - 1; // all but the last wait for a click; the refund ends the scene on its own

  // When a step opens, bring the diagram and all three panes into view together. The header above may scroll away; the
  // diagram must not be cut off (so the focus below does not scroll by itself, and the scroll stops at the diagram's top).
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!shown) return;
    button.current?.focus({ preventScroll: true });
    const panel = document.querySelector(".beat");
    const diagram = document.querySelector(".diagram");
    if (!panel || !diagram) return;
    const hidden = panel.getBoundingClientRect().bottom - window.innerHeight + 12;
    const room = diagram.getBoundingClientRect().top - 8;
    if (hidden > 0) window.scrollBy({ top: Math.min(hidden, Math.max(room, 0)), behavior: "smooth" });
  }, [shown, at]);

  useEffect(() => {
    if (!gated) return;
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
  }, [gated, onContinue]);

  if (!b) {
    return (
      <section className="beat idle" aria-label="Walkthrough">
        <p>Press R to walk one ticket through. Space or → moves to the next step.</p>
      </section>
    );
  }
  const { message, amount } = WALKTHROUGH_TICKET;
  const agentDone = i >= 2 || decided(flow);
  const done = i >= 4 && refunded(flow);
  return (
    <section className="beat" aria-label={`Step ${i + 1} of ${BEATS.length}: ${b.title}`}>
      <div className="beat-head">
        <span className="beat-n">Step {i + 1} of {BEATS.length}</span>
        <h3>{b.title}</h3>
        {gated && (
          <button ref={button} className="primary" onClick={onContinue}>
            Continue → <kbd>space</kbd>
          </button>
        )}
      </div>
      <div className="panes">
        {/* The customer talks only to the agent: no policy check, proposal or approval, just the answer. */}
        <Pane who="Customer view" avatar="C">
          <div className="msg customer"><p>{message}</p></div>
          {i >= 1 && !done && (
            <div className="msg support"><p><Typing /></p></div>
          )}
          {done && <div className="msg support"><p>{`Your ${amount} refund is on its way.`}</p></div>}
        </Pane>
        <Pane who="Agent view" avatar="AI">
          <Row kind={i >= 1 ? "done" : "active"}>{`New ticket · ${amount}`}</Row>
          {i >= 1 && (agentDone ? <Row kind="done">Policy check passed</Row> : <div className="pane-row"><Typing /></div>)}
          {/* One row for the human: proposed, then approved, in place */}
          {i >= 2 && (i >= 3 ? <Row kind="done">Human approved</Row> : <Row kind="waiting">Proposed it to a human</Row>)}
          {i >= 4 && (done ? <Row kind="done">Refunded. Customer told.</Row> : <Row kind="paying">Asking payments…</Row>)}
        </Pane>
        {/* The human sees the proposal and decides; nothing about payments. */}
        <Pane who="Human view" avatar={<LegendIcon kind="waiting" />}>
          {i < 2 ? (
            <p className="pane-empty">Nothing to review</p>
          ) : (
            <div className="review">
              <div className="review-ask">{`Refund ${amount}?`}</div>
              <div className="review-quote">“{message}”</div>
              <div className="review-actions">
                <span className={i >= 3 ? "act approve on" : "act approve"}>{i >= 3 ? "✓ Approved" : "Approve"}</span>
                <span className="act deny">Deny</span>
              </div>
            </div>
          )}
        </Pane>
      </div>
    </section>
  );
}
