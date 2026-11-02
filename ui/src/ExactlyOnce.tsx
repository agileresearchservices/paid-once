// The closing page: at-least-once delivery, exactly-once effect. One duplicate delivery goes to both stacks. What
// decides the outcome is the idempotency key each attempt carries, so the picture draws the payments ledger and the key on
// every attempt. Static: nothing here moves with a run. Key formats come from the code (lane1/graph.py,
// lane2/payments_activities.py). The viewBox is about one unit per CSS px at a 1512 px window.

const CARD_W = 700;
const H = 224;
const W = 1440;
const ROW_Y = [100, 146]; // the two attempts' arrows

interface Lane {
  x: number;
  good: boolean;
  title: string;
  keys: [string, string]; // the Idempotency-Key of attempt 1 and attempt 2
  rows: string[]; // what the ledger holds afterwards
  caption: string;
}

const LANES: Lane[] = [
  {
    x: 0,
    good: false,
    title: "✕ Queue + LangGraph: a key per attempt",
    keys: ["l1-tkt7-a3f9c2", "l1-tkt7-d81e04"],
    rows: ["l1-tkt7-a3f9c2 · $42.00", "l1-tkt7-d81e04 · $42.00"],
    caption: "Two keys look like two refunds. Paid twice.",
  },
  {
    x: W - CARD_W,
    good: true,
    title: "✓ Temporal + Nexus: a key per refund",
    keys: ["refund-tkt7", "refund-tkt7"],
    rows: ["refund-tkt7 · $42.00"],
    caption: "Same key, same refund: attempt 2 gets the stored answer. Paid once.",
  },
];

function LaneCard({ lane }: { lane: Lane }) {
  const { x, good } = lane;
  const marker = good ? "url(#eo-arrow-good)" : "url(#eo-arrow-bad)";
  return (
    <g className={`eo-card ${good ? "good" : "bad"}`}>
      <rect className="card" x={x + 1} y={1} width={CARD_W - 2} height={H - 2} rx={12} />
      <text className="eo-title" x={x + 20} y={34}>
        {lane.title}
      </text>
      <g className="eo-box">
        <rect x={x + 20} y={52} width={130} height={104} rx={10} />
        <text x={x + 85} y={98} textAnchor="middle">Worker</text>
        <text className="sub" x={x + 85} y={122} textAnchor="middle">same message,</text>
        <text className="sub" x={x + 85} y={142} textAnchor="middle">delivered twice</text>
      </g>
      {ROW_Y.map((y, i) => (
        <g key={i}>
          <text className="eo-attempt" x={x + 255} y={y - 24} textAnchor="middle">{`attempt ${i + 1}`}</text>
          <line className="eo-wire" x1={x + 150} x2={x + 357} y1={y} y2={y} markerEnd={marker} />
          <text className="eo-key" x={x + 255} y={y - 6} textAnchor="middle">{lane.keys[i]}</text>
        </g>
      ))}
      <g className="eo-box ledger">
        <rect x={x + 360} y={52} width={320} height={104} rx={10} />
        <text className="eo-ledger-title" x={x + 376} y={76}>Payments ledger</text>
        {lane.rows.map((r, i) => (
          <g key={r} className="eo-row">
            <rect x={x + 376} y={88 + i * 32} width={288} height={26} rx={6} />
            <text x={x + 388} y={106 + i * 32}>{r}</text>
          </g>
        ))}
        {good && (
          <text className="eo-replay" x={x + 376} y={142}>attempt 2 → returns the row above</text>
        )}
      </g>
      <text className="eo-caption" x={x + 20} y={H - 22}>{lane.caption}</text>
    </g>
  );
}

function Picture() {
  return (
    <svg className="eo" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="The same duplicate delivery, with a key per attempt and a key per refund">
      <defs>
        <marker id="eo-arrow-bad" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head" />
        </marker>
        <marker id="eo-arrow-good" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head good" />
        </marker>
      </defs>
      {LANES.map((l) => (
        <LaneCard key={l.title} lane={l} />
      ))}
    </svg>
  );
}

// Where each stack gets the key, and what that decides.
const ROWS: { what: string; queue: string; temporal: string }[] = [
  { what: "The key comes from", queue: "The attempt: ticket + a random suffix", temporal: "The business operation: refund-<ticket>" },
  { what: "A retry sends", queue: "A new key", temporal: "The same key" },
  { what: "Payments' ledger", queue: "Books it again", temporal: "Returns the stored refund" },
  { what: "Crash, redelivery, quiet payments", queue: "Refunded twice", temporal: "Refunded once" },
];

// The call to action. Each step starts with a verb.
const NEXT: { do: string; why: string }[] = [
  { do: "Pick one refund-like call", why: "Anything with a side effect you can't take back: a refund, a charge, an email." },
  { do: "Derive its key from the business operation", why: "refund-<ticket>, not a fresh value per attempt. Make the receiver return the stored result on a repeat." },
  { do: "Use the same ID for the workflow", why: "A duplicate start is then rejected, not run twice." },
  { do: "Move the approval wait and the retries into a workflow", why: "Nothing waits in worker memory, so a crash loses nothing." },
  { do: "Put the call behind Nexus", why: "The team that owns the money owns the retries; callers see one durable call." },
  { do: "Score it from the downstream ledger", why: "Count what the receiver booked, not what your own service believes." },
  { do: "Rerun these drills against yours", why: "Kill the workers, redeliver every message, make the receiver go quiet." },
];

export function ExactlyOnce() {
  return (
    <section className="eo-page" aria-label="At least once delivery, exactly once effect">
      <Picture />
      <div className="eo-lower">
        <div className="eo-left">
          <h3>Delivery is at least once. The effect can be exactly once.</h3>
          <table className="eo-table">
            <thead>
              <tr>
                <th />
                <th>Queue + LangGraph</th>
                <th>Temporal + Nexus</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr key={r.what}>
                  <th scope="row">{r.what}</th>
                  <td className="no">{r.queue}</td>
                  <td className="yes">{r.temporal}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="eo-half">
            <b>The key is half of it.</b> Give Queue + LangGraph the stable key (<code>PAIDONCE_L1_STABLE_KEY=1</code>) and its
            duplicates go to zero, but tickets are still lost when a worker dies: the approval lived in its memory. Durable
            execution is the other half.
          </p>
        </div>
        <aside className="eo-cta" aria-label="Next steps">
          <h3>Your next steps</h3>
          <ol>
            {NEXT.map((n) => (
              <li key={n.do}>
                <b>{n.do}.</b> <span>{n.why}</span>
              </li>
            ))}
          </ol>
          <blockquote className="eo-ask">Pick one call in your system and make it paid once.</blockquote>
        </aside>
      </div>
    </section>
  );
}
