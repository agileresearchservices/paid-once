import { OUTCOME_GLYPH } from "./outcomes";
import type { LaneAudit } from "./types";

// Ticket outcomes as one whole split into parts: a tall segmented bar. The four reserved status
// colours carry state, and every segment also has an icon and a name so colour is never the only cue.
// "Unapproved" shares the critical colour with "refunded twice", so it gets a striped texture. "Never refunded"
// is solid orange; its name and glyph set it apart from red.
// Segments read "4 duplicated" rather than icon + count: a numeric icon next to a count ("×2 4") read as one number.
// The legend's icons are the diagram's ledger glyphs (outcomes.ts); there the count comes after the label, so they don't merge.
// "Denied, nothing owed" is neutral grey: a denied ticket with no money moved is the correct outcome, not a win
// or a loss.
interface Part {
  key: string;
  label: string;
  short: string;
  icon: string;
  value: number;
  className: string;
}

function parts(a: LaneAudit): Part[] {
  return [
    { key: "ok", label: "Refunded once", short: "once", icon: OUTCOME_GLYPH.ok, value: a.refunded_once, className: "good" },
    { key: "none", label: "Denied, nothing owed", short: "denied", icon: OUTCOME_GLYPH.denied, value: a.rejected + a.declined, className: "neutral" },
    { key: "dup", label: "Refunded more than once", short: "duplicated", icon: OUTCOME_GLYPH.duplicate, value: a.duplicates, className: "critical" },
    { key: "unapproved", label: "Refunded without approval", short: "unapproved", icon: OUTCOME_GLYPH.unapproved, value: a.unapproved, className: "critical striped" },
    { key: "missing", label: "Approved, never refunded", short: "missing", icon: OUTCOME_GLYPH.missing, value: a.missing, className: "serious" },
    { key: "flight", label: "Still settling", short: "settling", icon: OUTCOME_GLYPH.settling, value: a.in_flight, className: "warning" },
  ];
}

const dollars = (cents: number) =>
  (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

// "untested" before the lane has a ticket: an invariant over nothing would otherwise read "Holds".
type Verdict = "holds" | "violated" | "settling" | "untested";

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

// believedDone: what the lane's own records claim, set only where the ledger's answer sits next to it (the scoreboard
// step). The verdicts never read it.
export function Scoreboard({ audit, name, believedDone, note }: { audit: LaneAudit; name: string; believedDone?: number; note?: string }) {
  const ps = parts(audit);
  const total = ps.reduce((n, p) => n + p.value, 0);
  const untested = total === 0;
  const exactlyOnce: Verdict = untested
    ? "untested"
    : audit.duplicates + audit.missing > 0 ? "violated" : audit.in_flight > 0 ? "settling" : "holds";
  const lost: Verdict = untested ? "untested" : audit.missing > 0 ? "violated" : audit.in_flight > 0 ? "settling" : "holds";

  return (
    <section className="scoreboard" aria-label={`${name} scoreboard`}>
      <div className="hero">
        <span className="hero-num">{audit.refunded_once}</span>
        <span className="hero-of">of {audit.approved} approved refunded once</span>
      </div>
      {note && <p className="hero-note">{note}</p>}
      {believedDone !== undefined && (
        <p className="believed">
          Job table says <b>{believedDone}</b> done. Ledger says <b>{audit.refunded_once}</b> paid once.
        </p>
      )}
      {/* Always rendered, so the lane doesn't jump when the first duplicate lands. A clean lane shows its $0.00. */}
      <p className={audit.duplicate_cents > 0 ? "loss" : "loss none"} aria-hidden={untested}>
        {untested ? " " : `${dollars(audit.duplicate_cents)} refunded twice`}
      </p>

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

      <details className="table-view">
        <summary>Table view</summary>
        <table>
          <tbody>
            <tr><th>Submitted</th><td>{audit.submitted}</td></tr>
            <tr><th>Approved</th><td>{audit.approved}</td></tr>
            <tr><th>Refunded once</th><td>{audit.refunded_once}</td></tr>
            <tr><th>Tickets refunded more than once</th><td>{audit.duplicates}</td></tr>
            <tr><th>Extra refunds</th><td>{audit.duplicate_refunds} ({dollars(audit.duplicate_cents)})</td></tr>
            <tr><th>Approved, never refunded</th><td>{audit.missing}</td></tr>
            <tr><th>Still settling</th><td>{audit.in_flight}</td></tr>
            <tr><th>Refunded without approval</th><td>{audit.unapproved}</td></tr>
            <tr><th>Denied by a human, not paid</th><td>{audit.rejected}</td></tr>
            <tr><th>Outside the refund policy, not paid</th><td>{audit.declined}</td></tr>
          </tbody>
        </table>
      </details>
    </section>
  );
}
