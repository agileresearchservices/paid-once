// The deck: one step per scene, in order, then the scoreboard. `scene` is the show-server scene id.
// Talk-track material that doesn't fit on screen lives in drafts/talk-track.md (private).

export interface Step {
  id: string;
  scene: string | null;
  title: string;
  short: string; // label on the step button
  story: string; // what happens: one or two short sentences (this is read from a projector)
  watch: string; // what to look at, without giving the outcome away
  result?: string; // what it showed; appears once this step's scene has finished
  nexus?: boolean; // show the Nexus panel
  arch?: boolean; // the architecture page: the diagram and the walkthrough, no lane scoreboards
  runLabel?: string; // the run button, when "Run this scene" doesn't say what it does
}

// The walkthrough on step 1 stops at each of these until the presenter dismisses the box. `id` is the engine's beat id
// (Engine.scene_walkthrough). Every line says what this repo's code does (paidonce/lane1/, paidonce/lane2/).
export interface Beat {
  id: string;
  title: string; // the walkthrough's three panes (Walkthrough.tsx) tell the story; this is its headline
}

// The ticket the walkthrough sends. Mirrors WALKTHROUGH_MESSAGE and WALKTHROUGH_AMOUNT_CENTS in paidonce/show/engine.py.
export const WALKTHROUGH_TICKET = { message: "The mug arrived in pieces. Please refund me.", amount: "$42.00" };

export const BEATS: Beat[] = [
  { id: "ticket", title: "A customer asks for a refund" },
  { id: "agent", title: "The agent decides" },
  { id: "waiting", title: "Handed to a human" },
  { id: "approve", title: "The human approves" },
  { id: "refund", title: "Payments moves the money" },
];

export const STEPS: Step[] = [
  {
    id: "architecture",
    scene: "walkthrough",
    runLabel: "Walk through one ticket",
    short: "Architectures",
    title: "Two ways to build the same refund",
    story: "An agent proposes, a human approves, payments moves the money. Built twice.",
    watch: "Where each stack keeps a ticket's progress.",
    result: "One ticket, refunded once in both stacks.",
    arch: true,
  },
  {
    id: "intro",
    scene: "intro",
    short: "Happy path",
    title: "Happy path: nothing goes wrong",
    story: "Seven tickets per stack. The agent denies one, the human denies one, five are refunded.",
    watch: "Denied tickets go back to the helpdesk.",
    result: "Both stacks: five refunded once, two denied, no money on the denials.",
  },
  {
    id: "worker_crash",
    scene: "worker_crash",
    short: "Crash",
    title: "Crash or deploy: the agent workers die",
    story: "Three refunds are in flight, the rest wait for a human. We kill the agent workers.",
    watch: "In-flight refunds paid once? Waiting tickets still refunded?",
    result: "Queue + LangGraph: paid twice, tickets lost. Temporal: paid once, nothing lost.",
  },
  {
    id: "double_delivery",
    scene: "double_delivery",
    short: "Redelivery",
    title: "The same message arrives twice",
    story: "The queue redelivers jobs. Temporal gets each approval again.",
    watch: "Dollars refunded twice.",
    result: "Queue + LangGraph: some refunded twice. Temporal: the first decision wins.",
  },
  {
    id: "payments_timeout",
    scene: "payments_timeout",
    short: "Payments quiet",
    title: "Payments books it, then goes quiet",
    story: "Payments saves the refund, but the reply never arrives. Both stacks retry.",
    watch: "Which retries does the ledger recognise?",
    result: "Temporal reuses the ticket's key: answered from the ledger. Queue + LangGraph sends a new key: booked again.",
  },
  {
    id: "nexus_kill",
    scene: "nexus_kill",
    short: "Nexus",
    title: "Nexus: four failures mid-refund",
    story: "Support calls payments over Nexus. Payments goes quiet, then we kill three processes.",
    watch: "Top track: what support sees. Bottom: what payments does.",
    result: "Support saw no errors. Payments retried with the same key. Each refund paid once.",
    nexus: true,
  },
  {
    id: "scoreboard",
    scene: null,
    short: "Scoreboard",
    title: "The scoreboard",
    story: "Scored from the payments ledger, never from either stack's own records.",
    watch: "Refunded once. Nothing unapproved. Nothing lost.",
  },
];
