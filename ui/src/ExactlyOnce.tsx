import { useStill } from "./useStill";

// The closing slide, in the opening slide's style (Problem.tsx): at-least-once delivery, exactly-once effect. One
// duplicate delivery goes to both builds. What decides the outcome is the idempotency key each attempt carries, so the
// picture draws the payments ledger and the key on every attempt, with a packet travelling each attempt's wire. Then
// the keys side by side, and the call to action. Key formats come from the code (lane1/graph.py,
// lane2/payments_activities.py). The viewBox is about one unit per CSS px at a 1512 px window; the packets stand still
// for reduced motion.

const CARD_W = 700;
const H = 222;
const W = 1440;
const ROW_Y = [98, 144]; // the two attempts' wires
const WIRE_X1 = 150;
const WIRE_X2 = 357;

// One card's content: its title, the Idempotency-Key each attempt sent (`keys`), the rows the payments ledger holds
// afterwards (`rows`), and its caption. The picture draws two of these, one per build.
interface Lane {
  x: number; // the card's left edge in the picture
  good: boolean; // the green card: Temporal + Nexus
  title: string;
  keys: [string, string]; // the Idempotency-Key of attempt 1 and attempt 2
  rows: string[]; // what the ledger holds afterwards
  caption: string;
}

const LANES: Lane[] = [
  {
    x: 0,
    good: false,
    title: "✕  Queue + LangGraph: a key per attempt",
    keys: ["l1-tkt7-a3f9c2", "l1-tkt7-d81e04"],
    rows: ["l1-tkt7-a3f9c2 · $42.00", "l1-tkt7-d81e04 · $42.00"],
    caption: "Two keys look like two refunds. Paid twice.",
  },
  {
    x: W - CARD_W,
    good: true,
    title: "✓  Temporal + Nexus: a key per refund",
    keys: ["refund-tkt7", "refund-tkt7"],
    rows: ["refund-tkt7 · $42.00"],
    caption: "Same key, same refund: attempt 2 gets the stored answer. Paid once.",
  },
];

// Draws one card: a worker box for the duplicate delivery, one wire per attempt with its key, a packet on each wire
// (none with reduced motion), the payments ledger with its rows, and the caption. `good` picks green or red styling.
function LaneCard({ lane, still }: { lane: Lane; still: boolean }) {
  const { x, good } = lane;
  const k = good ? "good" : "bad";
  return (
    <g className={`eo-card ${k}`}>
      <rect className="card" x={x + 1} y={1} width={CARD_W - 2} height={H - 2} rx={16} fill={`url(#eo-card-${k})`} />
      <rect className="gleam" x={x + 18} y={2} width={CARD_W - 36} height={1.5} rx={1} />
      <text className="eo-title" x={x + 22} y={36}>{lane.title}</text>

      <g className="eo-box">
        <rect x={x + 20} y={56} width={130} height={104} rx={12} fill="url(#eo-box)" />
        <text x={x + 85} y={102} textAnchor="middle">Worker</text>
        <text className="sub" x={x + 85} y={126} textAnchor="middle">same message,</text>
        <text className="sub" x={x + 85} y={146} textAnchor="middle">delivered twice</text>
      </g>

      {ROW_Y.map((y, i) => (
        <g key={i}>
          <text className="eo-attempt" x={x + 255} y={y - 31} textAnchor="middle">{`attempt ${i + 1}`}</text>
          <rect className="eo-keypill" x={x + 255 - 92} y={y - 25} width={184} height={22} rx={11} />
          <text className="eo-key" x={x + 255} y={y - 9} textAnchor="middle">{lane.keys[i]}</text>
          <line className="eo-wireglow" x1={x + WIRE_X1} x2={x + WIRE_X2} y1={y} y2={y} />
          <line className="eo-wire" x1={x + WIRE_X1} x2={x + WIRE_X2 - 4} y1={y} y2={y} markerEnd={`url(#eo-arrow-${k})`} />
          {!still && (
            <circle className="eo-packet" r={6} opacity={0}>
              <set attributeName="opacity" to="1" begin={`${i * 1.3}s`} />
              <animateMotion
                dur="2.6s"
                begin={`${i * 1.3}s`}
                repeatCount="indefinite"
                path={`M ${x + WIRE_X1 + 6} ${y} H ${x + WIRE_X2 - 8}`}
              />
            </circle>
          )}
        </g>
      ))}

      <g className="eo-box ledger">
        <rect x={x + 360} y={56} width={322} height={104} rx={12} fill="url(#eo-box)" />
        <text className="eo-ledger-title" x={x + 378} y={80}>Payments ledger</text>
        {lane.rows.map((r, i) => (
          <g key={r} className="eo-row">
            <rect x={x + 376} y={90 + i * 32} width={290} height={26} rx={13} />
            <text x={x + 392} y={108 + i * 32}>{r}</text>
          </g>
        ))}
        {good && <text className="eo-replay" x={x + 378} y={144}>attempt 2 → returns the row above</text>}
      </g>
      <text className="eo-caption" x={x + 22} y={H - 20}>{lane.caption}</text>
    </g>
  );
}

// The picture on the slide: the two cards side by side (the queue build on the left, Temporal on the right), with the
// gradients and arrow markers they use. Reads no snapshot field; `still` (reduced motion) is passed to each card.
function Picture() {
  const still = useStill();
  return (
    <svg className="eo" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="The same duplicate delivery, with a key per attempt and a key per refund">
      <defs>
        <linearGradient id="eo-card-bad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3d1612" stopOpacity="0.9" />
          <stop offset="1" stopColor="#141414" />
        </linearGradient>
        <linearGradient id="eo-card-good" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0b3a22" stopOpacity="0.9" />
          <stop offset="1" stopColor="#141414" />
        </linearGradient>
        <linearGradient id="eo-box" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#273248" />
          <stop offset="1" stopColor="#161d2b" />
        </linearGradient>
        <marker id="eo-arrow-bad" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head" />
        </marker>
        <marker id="eo-arrow-good" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="why-head good" />
        </marker>
      </defs>
      {LANES.map((l) => (
        <LaneCard key={l.title} lane={l} still={still} />
      ))}
    </svg>
  );
}

// Where each build gets the key, and what that decides.
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

// The closing slide (step 9): the picture, the table of where each build gets its key (`ROWS`), the half-fix note and
// the next steps (`NEXT`). Reads no snapshot field; it is static.
export function ExactlyOnce() {
  return (
    <section className="eo-page" aria-label="At least once delivery, exactly once effect">
      <div className="eo-hero">
        <p className="pb-eyebrow">The conclusion</p>
        <h2 className="eo-headline">
          Delivered at least once, <em>paid exactly once</em>
        </h2>
        <p className="eo-lede">Neither build can stop a message arriving twice. The difference is whether it can cause a second payment.</p>
      </div>
      <Picture />
      <div className="eo-lower">
        <div className="eo-left">
          <h3>The key decides</h3>
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
          <div className="eo-half">
            <span className="eo-half-mark" aria-hidden="true">½</span>
            <p>
              <b>The key is half of it.</b> Give Queue + LangGraph the stable key (<code>PAIDONCE_L1_STABLE_KEY=1</code>) and its
              duplicates go to zero, but tickets are still lost when a worker dies: the approval lived in its memory. Durable
              execution is the other half.
            </p>
          </div>
        </div>
        <aside className="eo-cta" aria-label="Next steps">
          <h3>Your next steps</h3>
          <ol>
            {NEXT.map((n) => (
              <li key={n.do}>
                <span className="eo-step">
                  <b>{n.do}.</b> <span>{n.why}</span>
                </span>
              </li>
            ))}
          </ol>
          <blockquote className="eo-ask">Pick one call in your system and make it paid once.</blockquote>
        </aside>
      </div>
    </section>
  );
}
