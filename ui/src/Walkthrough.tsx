import { useEffect, useRef, type ReactNode } from "react";
import { BEATS, WALKTHROUGH_TICKET } from "./steps";
import { LegendIcon, type TicketKind } from "./TicketIcon";
import type { FlowDot, LaneId } from "./types";

// The walkthrough's panel, under the diagram on step 1: the refund as three role panes that fill in as the scene plays on its
// own. Each step stays up for a few seconds (the engine's WALKTHROUGH_DWELL_S), so the diagram above shows what the panes
// say. Before the scene runs the panel keeps its place with a hint, so the page doesn't jump. This page outlines the flow
// in general; it does not compare the two stacks.

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

// The panes' role icons, drawn like the ticket icons (TicketIcon.tsx): a chat bubble for the customer, a robot for the agent.
function RoleIcon({ role }: { role: "customer" | "agent" }) {
  return (
    <svg className="lg-icon role-icon" viewBox="-10 -10 20 20" aria-hidden="true">
      {role === "customer" ? (
        <g>
          <path d="M-6.5,-5.5 H6.5 V3.5 H-1.5 L-5,6.5 V3.5 H-6.5 Z" />
          <path d="M-3.4,-1 H3.4" />
        </g>
      ) : (
        <g>
          <rect x={-6.5} y={-3.5} width={13} height={10} rx={2.6} />
          <path d="M0,-3.5 V-6.8" />
          <circle cx={-2.6} cy={1.4} r={1.35} className="role-eye" />
          <circle cx={2.6} cy={1.4} r={1.35} className="role-eye" />
        </g>
      )}
    </svg>
  );
}

// A pane is one role's window: it shows only what that role sees.
function Pane({ who, avatar, chat, children }: { who: string; avatar: ReactNode; chat?: boolean; children: ReactNode }) {
  return (
    <div className="pane" role="log" aria-label={who}>
      <div className="pane-bar"><span className="avatar">{avatar}</span> {who}</div>
      <div className={chat ? "pane-body chat" : "pane-body"}>{children}</div>
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

export function Walkthrough({ beat, flow }: { beat: string | null; flow?: Record<LaneId, FlowDot[]> }) {
  // Once the scene has finished the chat stays as it was, so the panel never flashes a message or jumps.
  const last = useRef(-1);
  const at = BEATS.findIndex((b) => b.id === beat);
  if (at >= 0) last.current = at;
  else if (!flow) last.current = -1; // reset, or another scene is on screen: back to the hint
  const i = last.current;
  const b = BEATS[i];
  const shown = at >= 0; // a step is up

  // When a step opens, bring the diagram and all three panes into view together. The header above may scroll away; the
  // diagram must not be cut off (the scroll stops at the diagram's top).
  useEffect(() => {
    if (!shown) return;
    const panel = document.querySelector(".beat");
    const diagram = document.querySelector(".diagram");
    if (!panel || !diagram) return;
    const hidden = panel.getBoundingClientRect().bottom - window.innerHeight + 12;
    const room = diagram.getBoundingClientRect().top - 8;
    if (hidden > 0) window.scrollBy({ top: Math.min(hidden, Math.max(room, 0)), behavior: "smooth" });
  }, [shown, at]);

  if (!b) {
    return (
      <section className="beat idle" aria-label="Walkthrough">
        <p>Press R to walk one ticket through. It plays on its own.</p>
      </section>
    );
  }
  const { message, amount } = WALKTHROUGH_TICKET;
  const agentDone = i >= 2 || decided(flow);
  const done = i >= 4 && refunded(flow);
  // The agent's answer to the customer on each step, kept as the chat goes on. It says what the customer needs to know,
  // not how: no policy check, proposal or approval. The last one waits for the money, then says it is on its way.
  const replies = [
    "Thanks! I'm looking into it now.",
    "I'm checking with a teammate.",
    "Good news, it's approved!",
    done ? `Your ${amount} refund is on its way.` : "Sending your refund now…",
  ].slice(0, i);
  return (
    <section className="beat" aria-label={`Step ${i + 1} of ${BEATS.length}: ${b.title}`}>
      <div className="beat-head">
        <span className="beat-n">Step {i + 1} of {BEATS.length}</span>
        <h3>{b.title}</h3>
      </div>
      <div className="panes">
        {/* The customer talks only to the agent: a short answer per step, never the policy check or the approval. */}
        <Pane who="Customer view" avatar={<RoleIcon role="customer" />} chat>
          <div className="msg customer"><p>{message}</p></div>
          {replies.map((r, n) => (
            <div className="msg support" key={n}><p>{r}</p></div>
          ))}
        </Pane>
        <Pane who="Agent view" avatar={<RoleIcon role="agent" />}>
          <Row kind={i >= 1 ? "done" : "active"}>{`New ticket · ${amount}`}</Row>
          {i >= 1 && (agentDone ? <Row kind="done">Policy check passed</Row> : <div className="pane-row"><Typing /></div>)}
          {/* One row for the human: proposed, then approved, in place */}
          {i >= 2 && (i >= 3 ? <Row kind="done">Human approved</Row> : <Row kind="waiting">Proposed it to a human</Row>)}
          {i >= 4 && (done ? <Row kind="done">Refunded, customer notified.</Row> : <Row kind="paying">Asking payments…</Row>)}
        </Pane>
        {/* The human sees the proposal and decides; nothing about payments. */}
        <Pane who="Human in the loop" avatar={<LegendIcon kind="waiting" />}>
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
