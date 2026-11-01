// The deck: one step per scene, in order, then the scoreboard. `scene` is the show-server scene id.
// Talk-track material that doesn't fit on screen lives in drafts/talk-track.md (private).

export interface Step {
  id: string;
  scene: string | null;
  title: string;
  short: string; // label on the step button
  story: string; // what happens, about 25 words
  watch: string; // what to look at, without giving the outcome away
  result?: string; // what it showed; appears once this step's scene has finished
  nexus?: boolean; // show the Nexus panel
  arch?: boolean; // the side-by-side architecture page
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
    intro:
      "The helpdesk sends one ticket: a $42.00 order and a message asking for the money back. Both stacks get the same ticket, the same human and the same payments service. Only the plumbing differs.",
    queue: "The API writes a row in a SQLite jobs table and queues a decide job.",
    temporal: "The helpdesk starts a SupportTicketWorkflow, ID ticket-<id>. Its event history in the Temporal server is the ticket's record.",
  },
  {
    id: "agent",
    title: "The agent decides",
    intro: "Two layers, the same in both stacks: deterministic policy rules (amount limit, return window), then Claude proposes a refund or a denial with a reason.",
    queue:
      "A worker thread claims the job under a 10 s visibility timeout and runs a LangGraph graph. Its state is checkpointed in MemorySaver, inside the worker process.",
    temporal: "The agent runs as an activity, run_agent, with a timeout and retry policy. Its proposal is written into the workflow's history.",
  },
  {
    id: "waiting",
    title: "Waiting for a human",
    intro: "The agent only proposes. No money moves until a person approves, and that can take days.",
    queue: "The graph stopped at interrupt(). The proposal is held in the worker's memory and the row says awaiting_approval. If this worker restarts, the interrupt is gone.",
    temporal: "The workflow is parked on wait_condition, with no timeout and no worker holding it. After a deploy, a new worker replays the history to this point.",
  },
  {
    id: "approve",
    title: "The human approves",
    intro: "A reviewer approves the $42.00 refund. This is the only moment the human acts.",
    queue: "POST /tickets/<id>/approve marks the row approved and queues an execute job. The worker resumes the graph from memory.",
    temporal: "An approve signal reaches the workflow and releases the wait. A repeated signal is counted, not applied twice.",
  },
  {
    id: "refund",
    title: "Asking payments for the money",
    intro: "Payments is the payments team's service with its own ledger. The call is slowed 2.5 s on purpose so you can see it in flight.",
    queue:
      "The worker POSTs to payments over plain HTTP: a 3 s timeout, 3 tries, and a new Idempotency-Key each try (l1-<ticket>-<random>). Support owns that client.",
    temporal:
      "Support starts one Nexus operation, issue_refund, on payments-endpoint. Payments' handler starts RefundWorkflow, ID refund-<ticket_id>, and its activity sends the same key (refund-<ticket_id>) on every retry. Payments owns the retries.",
  },
  {
    id: "ledger",
    title: "The ledger decides",
    intro: "Payments booked one refund for the ticket in each stack. The scoreboard counts rows in that ledger. It never asks either stack what it believes.",
    queue: "The row says done, with the refund ID payments returned.",
    temporal: "The workflow completed, with the refund ID in its result. The next pages show what happens when something breaks.",
  },
];

export const STEPS: Step[] = [
  {
    id: "architecture",
    scene: "walkthrough",
    runLabel: "Walk through one ticket",
    short: "Architectures",
    title: "Two ways to build the same refund",
    story:
      "Helpdesk tickets ask for refunds. The agent checks the refund policy, proposes the rest, a human approves or denies, and the payments team moves the money. Both stacks run that flow against the same payments service.",
    watch: "Where each one keeps a ticket's progress, and how it reaches payments. Walk through one ticket to see it step by step.",
    result: "One ticket, approved, refunded exactly once in both stacks. The ledger, not either stack, says so.",
    arch: true,
  },
  {
    id: "intro",
    scene: "intro",
    short: "Happy path",
    title: "Happy path: nothing goes wrong",
    story:
      "Both stacks get the same seven tickets. The agent's policy check denies one, and the human approves five and denies one. Temporal keeps each ticket's progress through crashes; Nexus is how support calls payments without owning payments' retries.",
    watch: "Both lanes get the same seven tickets, with no trouble yet. The two denied tickets go back to the helpdesk.",
    result:
      "Both lanes agree: five approved, five refunded once, and the two denied tickets got no money. The differences only show up under failure.",
  },
  {
    id: "tip_over",
    scene: "tip_over",
    short: "Crash",
    title: "The agent workers crash",
    story:
      "Payments saves each refund but answers slowly. Mid-call, the agent workers are killed (kill -9). Each lane has to pick up where it left off.",
    watch: "How each lane re-drives the refund, and what the ledger records.",
    result:
      "Queue + LangGraph lost the agent's in-memory state and retried with a fresh idempotency key: duplicates and lost tickets. Temporal's restarted worker replayed from history and retried with a key derived from the ticket.",
  },
  {
    id: "double_delivery",
    scene: "double_delivery",
    short: "Redelivery",
    title: "The same message arrives twice",
    story: "The same work is delivered twice: the queue redelivers its jobs, and Temporal receives each human decision signal again.",
    watch: "The duplicate count, and dollars refunded twice.",
    result:
      "Queue + LangGraph refunded some tickets twice. Each workflow took the first decision and counted the repeats without acting on them.",
  },
  {
    id: "deploy_wait",
    scene: "deploy_wait",
    short: "Deploy",
    title: "A deploy lands during the approval wait",
    story: "Approvals can take days, so a deploy will land while tickets wait. Both lanes' workers restart mid-wait.",
    watch: "Tickets a human approved: do they still get refunded?",
    result:
      "Queue + LangGraph kept its place in memory and lost it: approved, never refunded. Temporal's workflows were waiting in Temporal the whole time.",
  },
  {
    id: "payments_timeout",
    scene: "payments_timeout",
    short: "Payments quiet",
    title: "Payments commits, then goes quiet",
    story: "Payments saves the refund, then the response never arrives and the caller times out. Both lanes retry.",
    watch: "Which retries the ledger recognises as the same refund.",
    result:
      "Both lanes retried. Temporal's retry reused the ticket's key, so payments answered it from the ledger. Queue + LangGraph made a fresh key for each attempt, so payments booked the refund again.",
  },
  {
    id: "nexus_kill",
    scene: "nexus_kill",
    short: "Nexus",
    title: "Nexus: four failures mid-refund",
    story:
      "Support asks payments for each approved refund through one Nexus operation. While they're in flight, payments goes quiet after booking, then we kill the support worker, the payments worker and the Temporal server itself.",
    watch: "Each ticket's top track is all support sees. The bottom track is what payments does about it. The red rows are the failures.",
    result:
      "Once payments accepts an operation, support sees STARTED and no error while payments retries, for up to the 10-minute schedule-to-close timeout. Every retry reuses the ticket's key, so a refund already booked is answered from the ledger, not paid again. The Temporal server came back from its database with every workflow where it left off.",
    nexus: true,
  },
  {
    id: "scoreboard",
    scene: null,
    short: "Scoreboard",
    title: "The scoreboard",
    story:
      "Everything is scored from the payments ledger, not from either stack's own records. It counts refunds per ticket and compares them with approvals.",
    watch:
      "Three invariants: every approved ticket refunded exactly once, no refund without an approval, no ticket lost or stuck.",
  },
];
