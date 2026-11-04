import { useStill } from "./useStill";

// The opening slide: one idea, stated big. A refund has to be paid exactly once, and its path (customer, agent, human,
// payments) is where it goes wrong. A coin travels the path; three things can hit it on the way; the outcomes below say
// what is at stake. Nothing about either build yet: the next page does that. Static apart from the coin, which stands
// still for anyone who asks for reduced motion. The viewBox is about one unit per CSS px at a 1512 px window.

const W = 1440;
const H = 290;
const CY = 150; // the path's centre line
const R = 46; // node radius
const XS = [150, 530, 910, 1290];
const PATH = `M ${XS[0]} ${CY} H ${XS[3]}`;

const NODES = [
  { title: "Customer", sub: "asks for a refund" },
  { title: "AI agent", sub: "proposes it" },
  { title: "Human", sub: "approves it" },
  { title: "Payments", sub: "moves the money" },
];

// What can hit the refund, and where: above a node, or on a hop.
const HAZARDS = [
  { x: XS[1], label: "workers crash" },
  { x: (XS[2] + XS[3]) / 2, label: "messages repeat" },
  { x: XS[3], label: "replies get lost" },
];

// One icon per node, by index: 0 the customer's chat bubble, 1 the agent's robot, 2 the human, and the default, the
// coin, for payments (3). The cases follow NODES' order.
// Icons are drawn in a -10..10 box, like the ticket icons (TicketIcon.tsx).
function Icon({ i }: { i: number }) {
  switch (i) {
    case 0: // chat bubble
      return (
        <g>
          <path d="M-7,-6 H7 V4 H-1.5 L-5,7.5 V4 H-7 Z" />
          <path d="M-3.5,-1 H3.5" />
        </g>
      );
    case 1: // robot
      return (
        <g>
          <rect x={-7} y={-3.5} width={14} height={11} rx={3} />
          <path d="M0,-3.5 V-7.5" />
          <circle cx={-2.8} cy={1.6} r={1.4} className="fill" />
          <circle cx={2.8} cy={1.6} r={1.4} className="fill" />
        </g>
      );
    case 2: // person
      return (
        <g>
          <circle cx={0} cy={-3.5} r={3.6} />
          <path d="M-7,8 Q-7,1.5 0,1.5 Q7,1.5 7,8" />
        </g>
      );
    default: // coin
      return (
        <g>
          <circle cx={0} cy={0} r={7.5} />
          <path d="M2.8,-3 C1,-4.6 -3,-4 -3,-1.6 C-3,1.2 3,0.2 3,2.8 C3,5 -1.2,5.2 -3,3.4 M0,-6 V6" />
        </g>
      );
  }
}

// The animated picture: four nodes on one route, the three hazards (HAZARDS), and the coin that travels the route from
// the customer to payments (an `animateMotion` along `#pb-route`). Under reduced motion the coin sits on the customer.
function Path() {
  const still = useStill();
  return (
    <svg className="pb-path" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="A refund passes from the customer to the agent, a human and payments; workers can crash, messages repeat and replies get lost on the way">
      <defs>
        <linearGradient id="pb-line" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#444ce7" />
          <stop offset="1" stopColor="#b664ff" />
        </linearGradient>
        <radialGradient id="pb-gloss" cx="0.35" cy="0.25" r="0.9">
          <stop offset="0" stopColor="#3a4ac8" />
          <stop offset="0.55" stopColor="#222a6e" />
          <stop offset="1" stopColor="#151a3d" />
        </radialGradient>
        <radialGradient id="pb-coin" cx="0.35" cy="0.3" r="0.8">
          <stop offset="0" stopColor="#ffe28a" />
          <stop offset="1" stopColor="#e5a50a" />
        </radialGradient>
        <filter id="pb-glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9" /></filter>
        <marker id="pb-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="8" markerHeight="8" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#b664ff" />
        </marker>
      </defs>

      <path id="pb-route" d={PATH} className="pb-glowline" />
      <path d={PATH} className="pb-line" />
      {XS.slice(0, -1).map((x, i) => (
        <line key={i} className="pb-hop" x1={x + R + 8} x2={XS[i + 1] - R - 10} y1={CY} y2={CY} markerEnd="url(#pb-arrow)" />
      ))}

      {NODES.map((n, i) => (
        <g key={n.title} className="pb-node" transform={`translate(${XS[i]} ${CY})`}>
          <circle r={R + 10} className="halo" />
          <circle r={R} className="disc" />
          <path d={`M ${-R + 9} -14 A ${R - 4} ${R - 4} 0 0 1 ${R - 9} -14`} className="shine" />
          <g className="icon" transform="scale(3.1)"><Icon i={i} /></g>
          <text className="title" y={R + 36} textAnchor="middle">{n.title}</text>
          <text className="sub" y={R + 60} textAnchor="middle">{n.sub}</text>
        </g>
      ))}

      {HAZARDS.map((h) => (
        <g key={h.label} className="pb-hazard">
          <text className="label" x={h.x} y={30} textAnchor="middle">{h.label}</text>
          <line x1={h.x} x2={h.x} y1={78} y2={CY - R - 16} />
          <circle className="glow" cx={h.x} cy={60} r={22} />
          <circle className="dot" cx={h.x} cy={60} r={19} />
          <path className="bolt" d={`M ${h.x + 3} 48 L ${h.x - 7} 62 H ${h.x - 1} L ${h.x - 3} 72 L ${h.x + 7} 57 H ${h.x + 1} Z`} />
        </g>
      ))}

      {/* the refund: a coin that sets off from the customer and arrives at payments */}
      <g className="pb-coin">
        <circle r={20} fill="#ffcf4a" opacity="0.55" filter="url(#pb-glow)" />
        <circle r={14} fill="url(#pb-coin)" stroke="#fff2c2" strokeWidth="1.5" />
        <text y={6} textAnchor="middle">$</text>
        {still ? (
          <animateTransform attributeName="transform" type="translate" values={`${XS[0]} ${CY}`} dur="1s" />
        ) : (
          <animateMotion dur="5.5s" repeatCount="indefinite" calcMode="spline" keyPoints="0;1" keyTimes="0;1" keySplines="0.45 0 0.55 1">
            <mpath href="#pb-route" />
          </animateMotion>
        )}
      </g>
    </svg>
  );
}

// The three tiles under the picture: the two ways a refund goes wrong (the ledger marks ×2 and ∅ in the diagram, see
// OUTCOME_GLYPH in outcomes.ts) and the one right answer (✓). `cls` picks the colours.
const OUTCOMES = [
  { cls: "bad", mark: "✕", title: "Paid twice", sub: "Money out the door, twice" },
  { cls: "bad", mark: "✕", title: "Never paid", sub: "A customer left waiting" },
  { cls: "good", mark: "✓", title: "Paid once", sub: "The only right answer" },
];

// The opening slide (step 1): the hero, the Path picture, the three outcomes, and the button that starts step 2.
// It reads no snapshot field; `onStart` moves the deck on.
export function Problem({ onStart }: { onStart: () => void }) {
  return (
    <section className="pb-page" aria-label="The problem">
      <div className="pb-hero">
        <p className="pb-eyebrow">Refunds, with an AI agent in the loop</p>
        <h2 className="pb-headline">
          Pay the customer <em>exactly once</em>
        </h2>
        <p className="pb-lede">An agent proposes the refund, a human approves it, and payments moves the money.</p>
      </div>
      <Path />
      <div className="pb-outcomes" role="list">
        {OUTCOMES.map((o) => (
          <div key={o.title} role="listitem" className={`pb-outcome ${o.cls}`}>
            <span className="mark" aria-hidden="true">{o.mark}</span>
            <span className="txt">
              <b>{o.title}</b>
              <span>{o.sub}</span>
            </span>
          </div>
        ))}
      </div>
      <p className="pb-foot">Same tickets. Same failures. Two builds. The payments ledger decides which one pays once.</p>
      <button type="button" className="primary pb-start" onClick={onStart}>Start the demo →</button>
    </section>
  );
}
