"""The scoreboard. Reads the payments ledger and the two records the harness writes (what it planned for each ticket,
and each human decision), never a lane's own state.

Three invariants per lane:
  1. Every approved ticket is refunded exactly once.   (duplicates, missing)
  2. No refund without an approval.                     (unapproved)
  3. No ticket lost or stuck.                           (missing, after a settle window)

A ticket a human denied, or one the harness wrote to break the refund policy, is owed nothing: such a ticket
scores `rejected` or `declined` while no money moved, and `unapproved` if a refund exists. `expect` is the
harness's own note of what it wrote, a test oracle like the decision log, not a lane's state.
"""

from __future__ import annotations

import time

from paidonce import config
from paidonce.db import connect, ensure_schema
from paidonce.models import LANES
from paidonce.payments import ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  lane TEXT NOT NULL, ticket_id TEXT NOT NULL, scene TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, submitted_at REAL NOT NULL, expect TEXT NOT NULL DEFAULT 'refund',
  PRIMARY KEY (lane, ticket_id)
);
CREATE TABLE IF NOT EXISTS decisions (
  lane TEXT NOT NULL, ticket_id TEXT NOT NULL, decided_at REAL NOT NULL,
  approved INTEGER NOT NULL,
  PRIMARY KEY (lane, ticket_id)
);
"""

# An approved ticket with no refund yet counts as "in flight" for this long, and as missing after it.
SETTLE_S = 20.0


def init() -> None:
    """Create the two tables in `AUDIT_DB` if they are missing.

    The show server calls it at startup, and each function here calls it before it touches the tables.
    """
    ensure_schema(config.AUDIT_DB, SCHEMA)


def record_ticket(lane: str, ticket_id: str, scene: str, amount_cents: int, expect: str = "refund") -> None:
    """`expect` is what the harness wrote: "refund", "policy" (breaks the refund policy) or "human_no"."""
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tickets (lane, ticket_id, scene, amount_cents, submitted_at, expect) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (lane, ticket_id, scene, amount_cents, time.time(), expect),
        )


def record_decision(lane: str, ticket_id: str, approved: bool) -> None:
    """A human approved or denied. The first decision stands."""
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO decisions (lane, ticket_id, decided_at, approved) VALUES (?, ?, ?, ?)",
            (lane, ticket_id, time.time(), int(approved)),
        )


def reset() -> None:
    """Empty both tables, so the scoreboard starts from nothing.

    The show's reset calls it after it resets the payments ledger and Lane 1. It clears only the audit tables.
    """
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM decisions")


def compute(
    lane: str,
    settle_s: float = SETTLE_S,
    now: float | None = None,
    exclude_scenes: tuple[str, ...] = (),
    only_scenes: tuple[str, ...] | None = None,
) -> dict:
    """Score one lane. A ticket approved less than settle_s ago is in flight, not missing. `exclude_scenes` and
    `only_scenes` pick tickets by the scene that submitted them (the scoreboard leaves out the walkthrough)."""
    init()
    now = time.time() if now is None else now
    with connect(config.AUDIT_DB) as conn:
        tickets = [dict(r) for r in conn.execute("SELECT * FROM tickets WHERE lane = ?", (lane,))]
        tickets = [
            t
            for t in tickets
            if t["scene"] not in exclude_scenes and (only_scenes is None or t["scene"] in only_scenes)
        ]
        decisions = {r["ticket_id"]: dict(r) for r in conn.execute("SELECT * FROM decisions WHERE lane = ?", (lane,))}
    kept = {t["ticket_id"] for t in tickets}
    decisions = {tid: d for tid, d in decisions.items() if tid in kept}
    approvals = {tid: d for tid, d in decisions.items() if d["approved"]}
    refunds_by_ticket: dict[str, list[dict]] = {}
    for row in ledger.all_refunds(lane):
        refunds_by_ticket.setdefault(row["ticket_id"], []).append(row)

    # Each ticket is in one state, listed in `tickets`: ok, duplicate, unapproved, rejected, declined, waiting,
    # in_flight or missing. `refunded_once` counts ok, and `violations` is duplicates + missing + unapproved.
    out = {
        "lane": lane,
        "submitted": len(tickets),
        "approved": len(approvals),
        "refunded_once": 0,
        "duplicates": 0,
        "duplicate_refunds": 0,
        "duplicate_cents": 0,
        "missing": 0,
        "in_flight": 0,
        "unapproved": 0,
        "rejected": 0,
        "declined": 0,
        "waiting": 0,
        "violations": 0,
        "tickets": {},
        # Approved tickets with no refund yet, and when each stops being "in flight" and counts as lost, so the page
        # can show the wait instead of leaving it unexplained.
        "pending": {},
    }
    for t in tickets:
        tid = t["ticket_id"]
        refunds = refunds_by_ticket.get(tid, [])
        approval = approvals.get(tid)
        if approval is None:
            if refunds:
                state = "unapproved"
            elif tid in decisions:
                state = "rejected"  # a human said no, and no money moved
            elif t["expect"] == "policy":
                state = "declined"  # breaks the refund policy, and no money moved
            else:
                state = "waiting"
            out[state] += 1
        elif len(refunds) == 1:
            state = "ok"
            out["refunded_once"] += 1
        elif len(refunds) > 1:
            state = "duplicate"
            out["duplicates"] += 1
            out["duplicate_refunds"] += len(refunds) - 1
            out["duplicate_cents"] += sum(r["amount_cents"] for r in refunds[1:])
        elif now - approval["decided_at"] < settle_s:
            state = "in_flight"
            out["in_flight"] += 1
            out["pending"][tid] = {"since": approval["decided_at"], "verdict_at": approval["decided_at"] + settle_s}
        else:
            state = "missing"
            out["missing"] += 1
        out["tickets"][tid] = state
    out["violations"] = out["duplicates"] + out["missing"] + out["unapproved"]
    return out


def compute_all(settle_s: float = SETTLE_S, **scenes) -> dict:
    """One `compute` result per lane, keyed by lane id. Keyword arguments such as `exclude_scenes` go to each lane."""
    return {lane: compute(lane, settle_s, **scenes) for lane in LANES}
