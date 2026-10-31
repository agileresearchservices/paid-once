// The side-by-side page: the same job done two ways. Every row is what the code in this repo does
// (raccoon/lane1/, raccoon/lane2/); keep it that way, the panel will ask.

const ROWS: { q: string; queue: string; temporal: string }[] = [
  {
    q: "Where a ticket's progress lives",
    queue: "A SQLite jobs table, plus the agent's state in the worker's memory (LangGraph MemorySaver)",
    temporal: "The workflow's event history, in the Temporal server",
  },
  {
    q: "Waiting for a human to approve",
    queue: "An interrupt held in worker memory. A restart loses it",
    temporal: "A durable wait in the workflow. A new worker replays to the same point",
  },
  {
    q: "A refund someone says no to",
    queue: "Policy rules deny it in the worker; a human's \"no\" marks the row rejected at the API",
    temporal: "The workflow ends denied or rejected, with the reason in its history",
  },
  {
    q: "A worker dies mid-refund",
    queue: "The job reappears after a 10s visibility timeout and recovery re-drives it",
    temporal: "Temporal retries the activity on its retry policy (1s, growing to 3s)",
  },
  {
    q: "Idempotency key sent to payments",
    queue: "New on every attempt: l1-<ticket>-<random>",
    temporal: "The same on every attempt: refund-<ticket_id>",
  },
  {
    q: "How support reaches payments",
    queue: "Direct HTTP from support's code: support owns the client, timeouts and retries",
    temporal: "One Nexus operation on payments-endpoint: payments owns RefundWorkflow and its retries",
  },
  {
    q: "The same refund started twice",
    queue: "If it is still in flight, the second call carries a new key and the ledger books a second refund",
    temporal: "Workflow ID refund-<ticket_id> joins the run already in flight (USE_EXISTING)",
  },
];

export function Compare() {
  return (
    <section className="compare" aria-label="The two architectures, side by side">
      <table>
        <thead>
          <tr>
            <th />
            <th>Job queue</th>
            <th className="t">Temporal + Nexus</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.q}>
              <th scope="row">{r.q}</th>
              <td>{r.queue}</td>
              <td className="t">{r.temporal}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted fair">
        The queue isn't a strawman: it is a common, competent setup. Deriving its key from the ticket is a one-line fix
        that removed every duplicate in the measured run; the lost approvals remain (docs/scenario-results.md).
      </p>
    </section>
  );
}
