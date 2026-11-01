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
  title: string;
  intro: string;
  queue: string;
  temporal: string;
}

export const BEATS: Beat[] = [
  {
    id: "ticket",
    title: "A customer asks for a refund",
    intro: "One ticket: a $42.00 refund request.",
    queue: "A row in the jobs table, and a queued job.",
    temporal: "A workflow starts. Its history is the record.",
  },
  {
    id: "agent",
    title: "The agent decides",
    intro: "Policy rules first, then Claude proposes.",
    queue: "A worker runs a LangGraph graph. State lives in worker memory.",
    temporal: "An activity runs the agent. The result goes into history.",
  },
  {
    id: "waiting",
    title: "Waiting for a human",
    intro: "The agent only proposes. A human decides.",
    queue: "The pause is held in worker memory. A restart loses it.",
    temporal: "The workflow waits durably. A new worker replays to here.",
  },
  {
    id: "approve",
    title: "The human approves",
    intro: "The $42.00 refund is approved.",
    queue: "The API marks the row approved and queues a job.",
    temporal: "A signal wakes the workflow. Repeats are ignored.",
  },
  {
    id: "refund",
    title: "Asking payments for the money",
    intro: "Slowed 2.5 s so you can see it in flight.",
    queue: "HTTPS call to payments. A new idempotency key every try.",
    temporal: "One Nexus operation. Payments retries with key refund-<ticket>.",
  },
  {
    id: "ledger",
    title: "The ledger decides",
    intro: "The scoreboard reads payments' ledger, not either stack.",
    queue: "The row says done.",
    temporal: "The workflow completed with the refund ID.",
  },
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
    id: "tip_over",
    scene: "tip_over",
    short: "Crash",
    title: "The agent workers crash",
    story: "Payments is slow to answer. Mid-refund, we kill the agent workers.",
    watch: "Does each refund still land once?",
    result: "Queue + LangGraph: duplicates and lost tickets. Temporal: replayed, same key, paid once.",
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
    id: "deploy_wait",
    scene: "deploy_wait",
    short: "Deploy",
    title: "A deploy lands during the approval wait",
    story: "Approvals take days, so deploys land mid-wait. Both workers restart.",
    watch: "Are approved tickets still refunded?",
    result: "Queue + LangGraph: approved, never refunded. Temporal: still waiting, nothing lost.",
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
