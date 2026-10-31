"""The scoreboard. Reads the payments ledger and the human-decision log, never a lane's own state.

Three invariants per lane:
  1. Every approved ticket is refunded exactly once.   (duplicates, missing)
  2. No refund without an approval.                     (unapproved)
  3. No ticket lost or stuck.                           (missing, after a settle window)

A ticket a human denied, or one the harness wrote to break the refund policy, is owed nothing: no refund for it is
`rejected` or `declined`, and any refund is `unapproved`. `expect` is the harness's own note of what it wrote, a
test oracle like the decision log, not a lane's state.
"""

from __future__ import annotations

import time

from paidonce import config
from paidonce.db import connect
from paidonce.payments import ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  lane TEXT NOT NULL, ticket_id TEXT NOT NULL, scene TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, submitted_at REAL NOT NULL, expect TEXT NOT NULL DEFAULT 'refund',
  PRIMARY KEY (lane, ticket_id)
);
CREATE TABLE IF NOT EXISTS decisions (
  lane TEXT NOT NULL, ticket_id TEXT NOT NULL, decided_at REAL NOT NULL,
  approved INTEGER NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (lane, ticket_id)
);
DROP TABLE IF EXISTS approvals;
"""

LANES = ("lane1", "lane2")


def init() -> None:
    with connect(config.AUDIT_DB) as conn:
        conn.executescript(SCHEMA)
        # data/audit.db outlives code changes: add columns that came after the table was made.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
        if "expect" not in cols:
            conn.execute("ALTER TABLE tickets ADD COLUMN expect TEXT NOT NULL DEFAULT 'refund'")


def record_ticket(lane: str, ticket_id: str, scene: str, amount_cents: int, expect: str = "refund") -> None:
    """`expect` is what the harness wrote: "refund", "policy" (breaks the refund policy) or "human_no"."""
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tickets (lane, ticket_id, scene, amount_cents, submitted_at, expect) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (lane, ticket_id, scene, amount_cents, time.time(), expect),
        )


def record_decision(lane: str, ticket_id: str, approved: bool, delivered: bool) -> None:
    """A human approved or denied. `delivered` says whether the lane acknowledged it. The first decision stands."""
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute(
            "INSERT INTO decisions (lane, ticket_id, decided_at, approved, delivered) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(lane, ticket_id) DO UPDATE SET delivered = MAX(delivered, excluded.delivered)",
            (lane, ticket_id, time.time(), int(approved), int(delivered)),
        )


def reset() -> None:
    init()
    with connect(config.AUDIT_DB) as conn:
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM decisions")


def compute(lane: str, settle_s: float = 25.0, now: float | None = None) -> dict:
    """Score one lane. A ticket approved less than settle_s ago is in flight, not missing."""
    init()
    now = time.time() if now is None else now
    with connect(config.AUDIT_DB) as conn:
        tickets = [dict(r) for r in conn.execute("SELECT * FROM tickets WHERE lane = ?", (lane,))]
        decisions = {r["ticket_id"]: dict(r) for r in conn.execute("SELECT * FROM decisions WHERE lane = ?", (lane,))}
    approvals = {tid: d for tid, d in decisions.items() if d["approved"]}
    refunds_by_ticket: dict[str, list[dict]] = {}
    for row in ledger.all_refunds(lane):
        refunds_by_ticket.setdefault(row["ticket_id"], []).append(row)

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
        else:
            state = "missing"
            out["missing"] += 1
        out["tickets"][tid] = state
    out["violations"] = out["duplicates"] + out["missing"] + out["unapproved"]
    return out


def compute_all(settle_s: float = 25.0) -> dict:
    return {lane: compute(lane, settle_s) for lane in LANES}
