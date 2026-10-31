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
}

export const STEPS: Step[] = [
  {
    id: "architecture",
    scene: null,
    short: "Two architectures",
    title: "Two ways to build the same refund",
    story:
      "A support agent proposes refunds, a human approves, and the payments team moves the money. Both stacks run that flow and call the same payments service.",
    watch: "Where each one keeps a ticket's progress, and how it reaches payments.",
    arch: true,
  },
  {
    id: "intro",
    scene: "intro",
    short: "Happy path",
    title: "Happy path: nothing goes wrong",
    story:
      "Both stacks get the same five tickets and a human approves them all. Temporal makes the flow durable; Nexus decides whose failure it is.",
    watch: "Both lanes get the same five tickets, with no trouble yet.",
    result: "Both lanes agree: five approved, five refunded once. The differences only show up under failure.",
  },
  {
    id: "tip_over",
    scene: "tip_over",
    short: "Agent crash",
    title: "The agent workers crash",
    story:
      "Payments saves each refund but answers slowly. Mid-call, the agent workers are killed (kill -9). Each lane has to pick up where it left off.",
    watch: "How each lane re-drives the refund, and what the ledger records.",
    result:
      "The queue lost its in-memory state and retried with a fresh idempotency key: duplicates and lost tickets. Temporal's restarted worker replayed from history and retried with a key derived from the ticket.",
  },
  {
    id: "double_delivery",
    scene: "double_delivery",
    short: "Double delivery",
    title: "The same message arrives twice",
    story: "The same work is delivered twice: the queue redelivers its jobs, and Temporal receives the approval signal a second time.",
    watch: "The duplicate count, and dollars refunded twice.",
    result: "The queue refunded some tickets twice. Temporal counted the second approval and did not act on it again.",
  },
  {
    id: "deploy_wait",
    scene: "deploy_wait",
    short: "Deploy mid-wait",
    title: "A deploy lands during the approval wait",
    story: "Approvals can take days, so a deploy will land while tickets wait. Both lanes' workers restart mid-wait.",
    watch: "Tickets a human approved: do they still get refunded?",
    result:
      "The queue kept its place in memory and lost it: approved, never refunded. Temporal's workflows were waiting in Temporal the whole time.",
  },
  {
    id: "payments_timeout",
    scene: "payments_timeout",
    short: "Payments goes quiet",
    title: "Payments commits, then goes quiet",
    story: "Payments saves the refund, then the response never arrives and the caller times out. Both lanes retry.",
    watch: "Which retries the ledger recognises as the same refund.",
    result:
      "Temporal retries at least once. The retry is safe because the ledger dedupes on a key derived from the ticket; the queue's fresh key per attempt pays twice.",
  },
  {
    id: "nexus_kill",
    scene: "nexus_kill",
    short: "Nexus",
    title: "Nexus: kill the payments worker mid-refund",
    story:
      "Support calls one operation on the payments team's endpoint. The payments worker is killed while refunds are in progress.",
    watch: "The caller's view on the left, the payments namespace on the right. Where does the failure show up?",
    result:
      "Once payments accepts the operation, the caller shows STARTED while payments retries, for up to the 10-minute schedule-to-close timeout. A retry after the ledger commit gets the stored result back.",
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
