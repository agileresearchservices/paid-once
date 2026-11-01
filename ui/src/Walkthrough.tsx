import { useEffect, useId, useRef, type ReactNode } from "react";
import { BEATS, WALKTHROUGH_TICKET } from "./steps";
import { LegendIcon, type TicketKind } from "./TicketIcon";
import type { FlowDot, LaneId } from "./types";

// The walkthrough's panel, above the diagram on step 1: the refund as three role panes that fill in as the scene plays on its
// own. Each step stays up for a few seconds (the engine's WALKTHROUGH_DWELL_S), so the diagram below shows what the panes
// say. Before the scene runs the three panes are already there, empty, so the roles are on screen and nothing jumps. This page outlines the flow
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

// The customer's photo of the damaged mug, sent with their message: one mug whose handle has snapped off, the handle lying
// on the table beside it. There is no image file: this is a drawn "photo" that reads as one at this size, with a soft-focus
// tabletop and wall, a glazed red mug with cylinder shading and specular highlights, pale bare ceramic where the handle
// broke, soft contact shadows and a vignette. Fixed colours, so it looks the same on either theme. Gradient ids carry a
// useId() prefix because the photo appears twice on the page (customer and human panes).
function BrokenMug() {
  const id = useId().replace(/:/g, "");
  const u = (n: string) => `url(#${id}${n})`;
  const body = "M36,23 V62 Q36,69 44,69 H68 Q76,69 76,62 V23 Z";
  return (
    <svg className="mug-photo" viewBox="0 0 120 84" role="img" aria-label="Photo: the mug with its handle broken off">
      <defs>
        <linearGradient id={`${id}wall`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9d2c6" /><stop offset="1" stopColor="#b7ad9d" />
        </linearGradient>
        <linearGradient id={`${id}table`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#a67c55" /><stop offset="0.5" stopColor="#8a6542" /><stop offset="1" stopColor="#5f432b" />
        </linearGradient>
        <linearGradient id={`${id}glaze`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#5e1c12" /><stop offset="0.22" stopColor="#c4402b" /><stop offset="0.45" stopColor="#e2634a" />
          <stop offset="0.72" stopColor="#b53a27" /><stop offset="1" stopColor="#4d160e" />
        </linearGradient>
        <linearGradient id={`${id}core`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f6efe2" /><stop offset="1" stopColor="#d3c6b0" />
        </linearGradient>
        <radialGradient id={`${id}vig`} cx="0.5" cy="0.55" r="0.75">
          <stop offset="0.55" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity="0.5" />
        </radialGradient>
        <filter id={`${id}soft`} x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="2.2" /></filter>
        <filter id={`${id}blur`}><feGaussianBlur stdDeviation="0.5" /></filter>
        <clipPath id={`${id}clip`}><path d={body} /></clipPath>
      </defs>
      {/* soft-focus room: back wall, tabletop edge, a few wood grain lines */}
      <rect width="120" height="84" fill={u("wall")} />
      <rect y="30" width="120" height="54" fill={u("table")} />
      <rect y="29" width="120" height="2" fill="#6b4c31" opacity="0.6" />
      <g stroke="#5a3d26" strokeWidth="0.5" opacity="0.35" filter={u("blur")}>
        <path d="M0,44 H120" /><path d="M0,55 H120" /><path d="M0,67 H120" /><path d="M0,77 H120" />
      </g>
      {/* contact shadows: the mug, and the handle lying beside it */}
      <ellipse cx="58" cy="70" rx="26" ry="4.5" fill="#1a0f08" opacity="0.55" filter={u("soft")} />
      <ellipse cx="99" cy="76" rx="13" ry="3" fill="#1a0f08" opacity="0.5" filter={u("soft")} />
      {/* the mug: one body, rim, dark inside */}
      <path d={body} fill={u("glaze")} />
      <g clipPath={u("clip")}>
        <path d="M41,27 V63" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" opacity="0.38" filter={u("blur")} />
        <rect x="34" y="63" width="44" height="8" fill="#000" opacity="0.28" />
      </g>
      <path d="M36,23 Q56,16.5 76,23 Q56,29.5 36,23 Z" fill="#2c120b" stroke="#f1b9a6" strokeWidth="0.9" />
      {/* where the handle was: two glazed stubs ending in jagged, pale bare ceramic, and a pale scar between them */}
      <path d="M76,32 C80,32 82,34 82.5,37" fill="none" stroke="#5e1c12" strokeWidth="5.6" strokeLinecap="butt" />
      <path d="M76,32 C80,32 82,34 82.5,37" fill="none" stroke={u("glaze")} strokeWidth="4.2" strokeLinecap="butt" />
      <path d="M76,56 C80,56 82,54 82.5,51" fill="none" stroke="#5e1c12" strokeWidth="5.6" strokeLinecap="butt" />
      <path d="M76,56 C80,56 82,54 82.5,51" fill="none" stroke={u("glaze")} strokeWidth="4.2" strokeLinecap="butt" />
      <polygon points="80.2,36.6 83,34.4 85,37.6 82.6,39.8 80.6,38.6" fill={u("core")} />
      <polygon points="80.2,51.4 83,53.6 85,50.4 82.6,48.2 80.6,49.4" fill={u("core")} />
      <path d="M75.6,33 L77.2,37 L75.8,41 L77.4,46 L75.8,50 L77,55" fill="none" stroke={u("core")} strokeWidth="1" strokeLinejoin="round" opacity="0.8" />
      {/* the handle, snapped off and lying on the table: a glazed arc with a pale break at each end */}
      <g transform="rotate(-6 98 72)">
        <path d="M88,74 C90,62 108,62 110,74" fill="none" stroke="#5e1c12" strokeWidth="6.6" strokeLinecap="butt" />
        <path d="M88,74 C90,62 108,62 110,74" fill="none" stroke={u("glaze")} strokeWidth="5" strokeLinecap="butt" />
        <path d="M91,70 C94,65 100,64 104,65.5" fill="none" stroke="#fff" strokeWidth="0.9" strokeLinecap="round" opacity="0.45" />
        <polygon points="85.4,74 91,73.6 91.2,76.2 86,76.6" fill={u("core")} />
        <polygon points="107,73.6 112.6,74 112,76.8 106.8,76.2" fill={u("core")} />
      </g>
      {/* a couple of loose chips */}
      <g strokeLinejoin="round">
        <polygon points="84,67 88,65.6 87.6,69" fill="#c4402b" stroke="#f6efe2" strokeWidth="0.7" />
        <polygon points="70,76 74,74.6 74.4,78" fill="#d3c6b0" stroke="#8a7a62" strokeWidth="0.4" />
      </g>
      <rect width="120" height="84" fill={u("vig")} />
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

  // When a step opens, bring all three panes into view. The header above may scroll away; the panel's own top must not
  // (the scroll stops there). The diagram sits below the panel. The target is an absolute page position, not a scrollBy:
  // a smooth scrollBy issued while the last step's scroll is still moving adds to that scroll's destination, so steps
  // a few seconds apart stacked up and pushed the step title off the top.
  useEffect(() => {
    if (!shown) return;
    const panel = document.querySelector(".beat");
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const top = window.scrollY + r.top - 8; // never scroll past this
    const fit = window.scrollY + r.bottom + 12 - window.innerHeight; // enough to show the panel's bottom
    const target = Math.min(top, fit);
    if (target > window.scrollY + 1) window.scrollTo({ top: target, behavior: "smooth" });
  }, [shown, at]);

  const { message, amount } = WALKTHROUGH_TICKET;
  const agentDone = i >= 2 || decided(flow);
  const done = i >= 4 && refunded(flow);
  // The agent's answer to the customer on each step, kept as the chat goes on. It says what the customer needs to know,
  // not how: no policy check, proposal or approval. The last one waits for the money, then says it is on its way.
  const replies = [
    "So sorry about your mug! Looking into it now.",
    "I'm checking with a teammate.",
    "Good news, it's approved!",
    done ? `Your ${amount} refund is on its way.` : "Sending your refund now…",
  ].slice(0, Math.max(i, 0)); // none before the run (i is -1)
  return (
    <section className="beat" aria-label={b ? `Step ${i + 1} of ${BEATS.length}: ${b.title}` : "Walkthrough"}>
      <div className="beat-head">
        {/* Before the run the headline row stays (blank) so the panes don't move when step 1 starts. */}
        <span className="beat-n">{b ? `Step ${i + 1} of ${BEATS.length}` : "\u00a0"}</span>
        <h3>{b ? b.title : "\u00a0"}</h3>
      </div>
      <div className="panes">
        {/* The customer talks only to the agent: a short answer per step, never the policy check or the approval. */}
        <Pane who="Customer view" avatar={<RoleIcon role="customer" />} chat>
          {/* The photo rides in the message's own bubble, so it costs the short chat pane almost no height */}
          {b && <div className="msg customer"><p className="with-photo"><span>{message}</span><BrokenMug /></p></div>}
          {replies.map((r, n) => (
            <div className="msg support" key={n}><p>{r}</p></div>
          ))}
        </Pane>
        <Pane who="Agent view" avatar={<RoleIcon role="agent" />}>
          {b ? <Row kind={i >= 1 ? "done" : "active"}>{`New ticket · ${amount}`}</Row> : <p className="pane-empty">No ticket yet</p>}
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
              <div className="review-quote"><span>“{message}”</span><BrokenMug /></div>
              {/* The agent hands the proposal over with its policy check result, so the human knows why it was proposed */}
              <div className="review-note"><b>Agent:</b> Policy check passed.</div>
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
