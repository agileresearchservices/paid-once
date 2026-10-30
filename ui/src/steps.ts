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
}

export const STEPS: Step[] = [
  {
    id: "intro",
    scene: "intro",
    short: "Meet the system",
    title: "Meet the system",
    story:
      "A support agent proposes refunds, a human approves, and the payments team moves the money. Temporal makes it durable; Nexus decides whose failure it is.",
    watch: "Both lanes get the same five tickets, with no trouble yet.",
    result: "Both lanes agree: five approved, five refunded once. The differences only show up under failure.",
  },
  {
    id: "tip_over",
    scene: "tip_over",
    short: "Agent tipped over",
    title: "The raccoon tips over the agent",
    story:
      "Payments saves each refund but answers slowly. Mid-call, the raccoon kills the agent workers (kill -9). Each lane has to pick up where it left off.",
    watch: "How each lane re-drives the refund, and what the ledger records.",
    result:
      "Lane 1 lost its in-memory state and retried with a fresh idempotency key: duplicates and lost tickets. Lane 2's restarted worker replayed from history and retried with a key derived from the ticket.",
  },
  {
    id: "double_delivery",
    scene: "double_delivery",
    short: "Double delivery",
    title: "The same message arrives twice",
    story: "The raccoon replays the same work: Lane 1's queue redelivers its jobs, and Lane 2 receives the approval signal a second time.",
    watch: "The duplicate count, and dollars refunded twice.",
    result: "Lane 1 refunded some tickets twice. Lane 2 counted the second approval and did not act on it again.",
  },
  {
    id: "deploy_wait",
    scene: "deploy_wait",
    short: "Deploy mid-wait",
    title: "A deploy lands during the approval wait",
    story: "Approvals can take days, so a deploy will land while tickets wait. The raccoon restarts both lanes' workers mid-wait.",
    watch: "Tickets a human approved: do they still get refunded?",
    result:
      "Lane 1 kept its place in memory and lost it: approved, never refunded. Lane 2's workflows were waiting in Temporal the whole time.",
  },
  {
    id: "payments_timeout",
    scene: "payments_timeout",
    short: "Payments goes quiet",
    title: "Payments commits, then goes quiet",
    story: "Payments saves the refund, then the response never arrives and the caller times out. Both lanes retry.",
    watch: "Which retries the ledger recognises as the same refund.",
    result:
      "Temporal retries at least once. The retry is safe because the ledger dedupes on a key derived from the ticket; Lane 1's fresh key per attempt pays twice.",
  },
  {
    id: "nexus_kill",
    scene: "nexus_kill",
    short: "Nexus",
    title: "Nexus: kill the payments worker mid-refund",
    story:
      "Support calls one operation on the payments team's endpoint. The raccoon kills the payments worker while refunds are in progress.",
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
      "Everything is scored from the payments ledger, not from either lane's own records. It counts refunds per ticket and compares them with approvals.",
    watch:
      "Three invariants: every approved ticket refunded exactly once, no refund without an approval, no ticket lost or stuck.",
  },
];
