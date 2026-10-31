"""The payments team's ledger: the independent source of truth for the scoreboard.

It is deliberately well behaved. A refund with a given Idempotency-Key is recorded once;
repeating the key returns the original row. What differs between the lanes is the key
each one sends, not how careful this service is.
"""

from __future__ import annotations

import time
import uuid

from paidonce import config
from paidonce.db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS refunds (
  refund_id    TEXT PRIMARY KEY,
  ticket_id    TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  idem_key     TEXT NOT NULL UNIQUE,
  lane         TEXT NOT NULL,
  created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS refunds_ticket ON refunds (ticket_id);
"""


def init() -> None:
    with connect(config.LEDGER_DB) as conn:
        conn.executescript(SCHEMA)


def record_refund(ticket_id: str, amount_cents: int, idem_key: str, lane: str) -> dict:
    """Insert a refund unless the idempotency key was already used. Returns the stored row."""
    init()
    with connect(config.LEDGER_DB) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM refunds WHERE idem_key = ?", (idem_key,)).fetchone()
        if row is not None:
            conn.execute("COMMIT")
            return {**dict(row), "replayed": True}
        refund_id = f"re_{uuid.uuid4().hex[:12]}"
        now = time.time()
        conn.execute(
            "INSERT INTO refunds (refund_id, ticket_id, amount_cents, idem_key, lane, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (refund_id, ticket_id, amount_cents, idem_key, lane, now),
        )
        conn.execute("COMMIT")
        return {
            "refund_id": refund_id,
            "ticket_id": ticket_id,
            "amount_cents": amount_cents,
            "idem_key": idem_key,
            "lane": lane,
            "created_at": now,
            "replayed": False,
        }


def all_refunds(lane: str | None = None) -> list[dict]:
    init()
    with connect(config.LEDGER_DB) as conn:
        if lane:
            rows = conn.execute("SELECT * FROM refunds WHERE lane = ? ORDER BY created_at", (lane,))
        else:
            rows = conn.execute("SELECT * FROM refunds ORDER BY created_at")
        return [dict(r) for r in rows.fetchall()]


def reset() -> None:
    init()
    with connect(config.LEDGER_DB) as conn:
        conn.execute("DELETE FROM refunds")
