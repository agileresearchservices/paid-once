// The deck: one step per scene, in order, then the scoreboard. `scene` is the show-server scene id.

export interface Step {
  id: string;
  scene: string | null;
  title: string;
  short: string; // label on the step button
  story: string; // what happens
  watch: string; // what to look at
  nexus?: boolean; // show the Nexus panel
}

export const STEPS: Step[] = [
  {
    id: "intro",
    scene: "intro",
    short: "Meet the system",
    title: "Meet the system",
    story:
      "A support agent proposes refunds, a human approves, and the payments team's service moves the money. Both lanes get the same five tickets.",
    watch:
      "With no trouble, both lanes agree: five approved, five refunded once. The difference only shows up under failure.",
  },
  {
    id: "tip_over",
    scene: "tip_over",
    short: "Agent tipped over",
    title: "The raccoon tips over the agent",
    story:
      "Payments has saved each refund but is slow to answer. At that moment the raccoon kills the agent workers (kill -9). Lane 1 loses its in-memory state and re-drives the work with a fresh idempotency key. Lane 2's workflows live in Temporal, so the restarted worker carries on and retries with a key derived from the ticket.",
    watch: "Lane 1: duplicated refunds and lost tickets. Lane 2: every ticket refunded once.",
  },
  {
    id: "double_delivery",
    scene: "double_delivery",
    short: "Double delivery",
    title: "The same message arrives twice",
    story:
      "The raccoon replays the same work. Lane 1's queue redelivers the jobs, as at-least-once brokers do. Lane 2 receives the approval signal again and counts it instead of acting on it twice.",
    watch: "Lane 1's duplicate count and the dollars refunded twice.",
  },
  {
    id: "deploy_wait",
    scene: "deploy_wait",
    short: "Deploy mid-wait",
    title: "A deploy lands during the approval wait",
    story:
      "Approvals can take days, so a deploy will happen while tickets wait. The raccoon restarts both lanes' workers. Lane 1 kept its place in memory and loses it. Lane 2's workflows were waiting in Temporal the whole time.",
    watch: "Lane 1's missing tickets: approved by a human, never refunded.",
  },
  {
    id: "payments_timeout",
    scene: "payments_timeout",
    short: "Payments goes quiet",
    title: "Payments commits, then goes quiet",
    story:
      "The refund is saved, then the response never arrives and the caller times out. Lane 1 retries with a fresh idempotency key each time. Lane 2 retries with a key derived from the ticket, so the ledger recognises it.",
    watch:
      "Temporal made the retry safe only because the key comes from the business operation. Durable execution alone is not exactly-once.",
  },
  {
    id: "nexus_kill",
    scene: "nexus_kill",
    short: "Nexus",
    title: "Nexus: kill the payments worker mid-refund",
    story:
      "The support team calls one operation on the payments team's contract. The raccoon kills the payments worker. The support workflow keeps waiting; the retry happens inside the payments namespace, where the failure belongs.",
    watch:
      "The caller's operation stays STARTED. The payments-side refund workflow shows the activity timing out and retrying. The refund may already be in the ledger by then, so the retry gets the stored result back instead of paying twice.",
    nexus: true,
  },
  {
    id: "scoreboard",
    scene: null,
    short: "Scoreboard",
    title: "The scoreboard",
    story:
      "Everything above is scored from the payments ledger, not from either lane's own records. It counts refunds per ticket and compares them with approvals.",
    watch:
      "Three invariants: every approved ticket refunded exactly once, no refund without an approval, no ticket lost or stuck.",
  },
];
