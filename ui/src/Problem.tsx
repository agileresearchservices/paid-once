// The opening page: what the demo is about. The refund's path (customer, agent, human, payments) with the three things that
// go wrong on it, numbered; the numbers are the cards below and match scenes 4-6 (steps.ts). Then how the demo tests two builds
// against them. Static: nothing here moves with a run. The viewBox is about one unit per CSS px at a 1512 px window.

const W = 1440;
const H = 168;
const NODE_Y = 64;
const NODE_H = 64;
const NODE_W = 220;
const XS = [10, 410, 810, 1210];

const NODES = [
  { title: "Customer", sub: "asks for a refund" },
  { title: "Support agent", sub: "proposes it" },
  { title: "Human", sub: "approves it" },
  { title: "Payments", sub: "moves the money" },
];

// Where each failure lands on the path: a node's top centre, or the middle of a hop.
const FAILURES = [
  { n: 1, x: XS[1] + NODE_W / 2, label: "workers crash or restart" },
  { n: 2, x: (XS[2] + NODE_W + XS[3]) / 2, label: "message arrives twice" },
  { n: 3, x: XS[3] + NODE_W / 2, label: "reply never arrives" },
];

function Path() {
  const mid = NODE_Y + NODE_H / 2;
  return (
    <svg className="pb-path" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="A refund's path: customer, agent, human, payments, with three failures along it">
      <defs>
        <marker id="pb-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="pb-head" />
        </marker>
      </defs>
      {XS.slice(0, -1).map((x, i) => (
        <line key={i} className="pb-wire" x1={x + NODE_W} x2={XS[i + 1] - 3} y1={mid} y2={mid} markerEnd="url(#pb-arrow)" />
      ))}
      {NODES.map((n, i) => (
        <g key={n.title} className="pb-node">
          <rect x={XS[i]} y={NODE_Y} width={NODE_W} height={NODE_H} rx={10} />
          <text x={XS[i] + NODE_W / 2} y={NODE_Y + 28} textAnchor="middle">{n.title}</text>
          <text className="sub" x={XS[i] + NODE_W / 2} y={NODE_Y + 50} textAnchor="middle">{n.sub}</text>
        </g>
      ))}
      {FAILURES.map((f) => (
        <g key={f.n} className="pb-fail">
          <line x1={f.x} x2={f.x} y1={42} y2={NODE_Y - 4} />
          <circle cx={f.x} cy={26} r={17} />
          <text className="n" x={f.x} y={33} textAnchor="middle">{f.n}</text>
          <text className="label" x={f.x} y={NODE_Y + NODE_H + 30} textAnchor="middle">{f.label}</text>
        </g>
      ))}
    </svg>
  );
}

const CARDS = [
  {
    n: 1,
    title: "The workers die",
    what: "Refunds are in flight and approvals are waiting for a human when a worker crashes or a deploy restarts it.",
    risk: "A refund paid twice, or an approved ticket forgotten.",
  },
  {
    n: 2,
    title: "The same message arrives twice",
    what: "Queues deliver at least once. A retry or a lost acknowledgement hands the same approval to a worker again.",
    risk: "The same refund paid twice.",
  },
  {
    n: 3,
    title: "Payments goes quiet",
    what: "Payments books the refund, then the reply never arrives. The caller can't tell paid from not paid, so it retries.",
    risk: "A retry that pays again.",
  },
];

const CHECKS = ["Every approved ticket refunded once", "No refund without an approval", "No ticket lost or stuck"];

export function Problem() {
  return (
    <section className="pb-page" aria-label="The problem">
      <div className="pb-top">
        <Path />
      </div>
      <div className="pb-cards">
        {CARDS.map((c) => (
          <article key={c.n} className="pb-card">
            <h3><span className="pb-n">{c.n}</span> {c.title}</h3>
            <p>{c.what}</p>
            <p className="pb-risk"><b>At stake:</b> {c.risk}</p>
          </article>
        ))}
      </div>
      <div className="pb-test">
        <h3>How the demo tests it</h3>
        <p>
          The same tickets and the same failures, run against two builds: <b>Queue + LangGraph</b> and <b>Temporal + Nexus</b>. An
          audit reads the payments ledger, never either stack's own records, and checks three things:
        </p>
        <ul>
          {CHECKS.map((c) => (
            <li key={c}>✓ {c}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
