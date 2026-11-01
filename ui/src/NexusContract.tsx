import type { Topology } from "./types";

// The Nexus contract, in one strip between the two pictures and the run: what support sends, what payments answers,
// and that nothing else crosses. Field names come from the topology, which reads them off the dataclasses
// (paidonce/models.py RefundRequest / RefundResult), so the strip can't drift from the code.

// A plain-English gloss per field, for the hover. Unknown fields (a contract change) just show their name.
const MEANING: Record<string, string> = {
  ticket_id: "which ticket this refund is for",
  amount_cents: "how much, in cents",
  refund_id: "the payments ledger's ID for the refund",
};

function Fields({ names }: { names: string[] }) {
  return (
    <span className="ct-fields">
      {names.map((n) => (
        <code key={n} className="ct-field" title={MEANING[n] ?? n}>
          {n}
        </code>
      ))}
    </span>
  );
}

export function NexusContract({ t }: { t: Topology }) {
  return (
    <section
      className="contract"
      aria-label="The Nexus contract"
      title={`${t.service}.${t.operation}: the contract both teams share (paidonce/lane2/contract.py)`}
    >
      <div className="ct-row">
        <span className="ct-label">The contract</span>
        <span className="ct-side">Support sends</span>
        <Fields names={t.sends} />
        <span className="ct-arrow">→</span>
        <code className="ct-op">{t.operation}</code>
        <span className="ct-arrow">→</span>
        <span className="ct-side">Payments answers</span>
        <Fields names={t.returns} />
      </div>
      <div className="ct-plain">
        “Refund this ticket this much.” → “Done, here's the refund ID.” Nothing else crosses: no namespace, task queue,
        workflow or retry settings.
      </div>
    </section>
  );
}
