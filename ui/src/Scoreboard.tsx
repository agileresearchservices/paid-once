import type { LaneAudit } from "./types";

// Ticket outcomes as one whole split into parts: a tall segmented bar. The four reserved status
// colours carry state, and every segment is named too, so colour is never the only cue.
// "Unapproved" shares the critical colour with "refunded twice", so it gets a striped texture. "Never refunded"
// is solid orange; its name sets it apart from red.
// Segments read "4 duplicated": the count and its name together.
// "Denied, nothing owed" is neutral grey: a denied ticket with no money moved is the correct outcome, not a win
// or a loss.
interface Part {
  key: string;
  label: string;
  short: string;
  value: number;
  className: string;
}

// The bar's segments, left to right in this order. A part with a zero count is left out of the bar but keeps its place
// here. Each segment grows by its count (`flexGrow`), and its `className` is its colour in styles.css.
function parts(a: LaneAudit): Part[] {
  return [
    { key: "ok", label: "Refunded once", short: "once", value: a.refunded_once, className: "good" },
    { key: "none", label: "Denied, nothing owed", short: "denied", value: a.rejected + a.declined, className: "neutral" },
    { key: "dup", label: "Refunded more than once", short: "duplicated", value: a.duplicates, className: "critical" },
    { key: "unapproved", label: "Refunded without approval", short: "unapproved", value: a.unapproved, className: "critical striped" },
    { key: "missing", label: "Approved, never refunded", short: "missing", value: a.missing, className: "serious" },
    { key: "flight", label: "Still settling", short: "settling", value: a.in_flight, className: "warning" },
  ];
}

// Cents to a US dollar string, for the "refunded twice" figure. The audit counts money in cents (`duplicate_cents`).
const dollars = (cents: number) =>
  (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

// "untested" while no ticket has reached a bar segment (one still waiting for a human is in none): an invariant over
// nothing would otherwise read "Holds".
type Verdict = "holds" | "violated" | "settling" | "untested";

// One row of the invariants list: the icon, the rule in words, the verdict as a pill, and the counts it was judged on.
// The caller works out the verdict; this only draws it.
function Invariant({ text, verdict, detail }: { text: string; verdict: Verdict; detail: string }) {
  const icon = { holds: "✓", violated: "✕", settling: "…", untested: "–" }[verdict];
  const word = { holds: "Holds", violated: "Violated", settling: "Settling", untested: "Not tested yet" }[verdict];
  return (
    <li className={`invariant ${verdict}`}>
      <span className="inv-icon" aria-hidden="true">{icon}</span>
      <span className="inv-text">{text}</span>
      <span className="inv-verdict">{word}</span>
      <span className="inv-detail">{detail}</span>
    </li>
  );
}

// One lane's scoreboard: the refunded-once count against the approved, the bar of outcomes, and the three invariants.
// The numbers come from `audit.compute_all` (audit.py), which reads the payments ledger, never from a lane's own
// records. The verdicts: "Every approved ticket refunded once" is violated by a duplicate or a missing ticket, and
// settles while one is in flight; "No refund without an approval" is violated by an unapproved refund; "No ticket lost
// or stuck" is violated by a missing ticket, and settles while one is in flight. All three read "Not tested yet" while
// no ticket is in a bar segment: an empty lane, or one whose tickets all still wait for a human. `compact` is the
// scene-step layout (App.tsx): smaller type and bar, and the "refunded twice" figure beside the number, so the diagram
// and both scoreboards fit one screen.
// believedDone: what the lane's own records claim, set only where the ledger's answer sits next to it (the scoreboard
// step). The verdicts never read it.
export function Scoreboard({
  audit,
  name,
  believedDone,
  compact,
}: {
  audit: LaneAudit;
  name: string;
  believedDone?: number;
  compact?: boolean; // a scene step: the "refunded twice" amount sits beside the number
}) {
  const ps = parts(audit);
  const total = ps.reduce((n, p) => n + p.value, 0);
  const untested = total === 0;
  const exactlyOnce: Verdict = untested
    ? "untested"
    : audit.duplicates + audit.missing > 0 ? "violated" : audit.in_flight > 0 ? "settling" : "holds";
  const lost: Verdict = untested ? "untested" : audit.missing > 0 ? "violated" : audit.in_flight > 0 ? "settling" : "holds";

  // Always rendered, so the lane doesn't jump when the first duplicate lands. A clean lane shows its $0.00.
  const loss = (
    <p className={audit.duplicate_cents > 0 ? "loss" : "loss none"} aria-hidden={untested}>
      {untested ? " " : `${dollars(audit.duplicate_cents)} refunded twice`}
    </p>
  );

  return (
    <section className="scoreboard" aria-label={`${name} scoreboard`}>
      <div className="hero">
        <span className="hero-num">{audit.refunded_once}</span>
        <span className="hero-of">of {audit.approved} approved refunded once</span>
        {compact && loss}
      </div>
      {believedDone !== undefined && (
        <p className={believedDone !== audit.refunded_once ? "believed differs" : "believed"}>
          Job table says <b>{believedDone}</b> done. Ledger says <b>{audit.refunded_once}</b> paid once.
        </p>
      )}
      {!compact && loss}

      {total === 0 ? (
        <div className="bar empty">No tickets yet</div>
      ) : (
        <div className="bar" role="img" aria-label={ps.filter((p) => p.value).map((p) => `${p.value} ${p.label}`).join(", ")}>
          {ps.filter((p) => p.value > 0).map((p) => (
            <div
              key={p.key}
              className={`seg ${p.className}`}
              style={{ flexGrow: p.value }}
              tabIndex={0}
              data-tip={`${p.label}: ${p.value} of ${total}`}
            >
              {p.value / total > 0.04 && <span>{p.value}{p.value / total > 0.09 && ` ${p.short}`}</span>}
            </div>
          ))}
        </div>
      )}

      <ul className="invariants">
        <Invariant
          text="Every approved ticket refunded once"
          verdict={exactlyOnce}
          detail={`${audit.duplicates} duplicated, ${audit.missing} missing`}
        />
        <Invariant
          text="No refund without an approval"
          verdict={untested ? "untested" : audit.unapproved > 0 ? "violated" : "holds"}
          detail={`${audit.unapproved} unapproved · ${audit.rejected + audit.declined} denied, none paid`}
        />
        <Invariant
          text="No ticket lost or stuck"
          verdict={lost}
          detail={`${audit.missing} lost, ${audit.in_flight} settling`}
        />
      </ul>
    </section>
  );
}
