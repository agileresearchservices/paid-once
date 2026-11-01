"""The payments team's ledger: the independent source of truth for the scoreboard.

It is deliberately well behaved. A refund with a given Idempotency-Key is recorded once;
repeating the key returns the original row. What differs between the lanes is the key
each one sends, not how careful this service is.
"""

from __future__ import annotations

import time
import uuid

from paidonce import config
from paidonce.db import connect, ensure_schema, transaction

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
    ensure_schema(config.LEDGER_DB, SCHEMA)


def record_refund(ticket_id: str, amount_cents: int, idem_key: str, lane: str) -> dict:
    """Insert a refund unless the idempotency key was already used.

    Returns the stored row, plus `replayed`: True when the key was already there and nothing new was written.
    """
    init()
    with transaction(config.LEDGER_DB) as conn:
        row = conn.execute("SELECT * FROM refunds WHERE idem_key = ?", (idem_key,)).fetchone()
        if row is not None:
            return {**dict(row), "replayed": True}
        refund_id = f"re_{uuid.uuid4().hex[:12]}"
        now = time.time()
        conn.execute(
            "INSERT INTO refunds (refund_id, ticket_id, amount_cents, idem_key, lane, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (refund_id, ticket_id, amount_cents, idem_key, lane, now),
        )
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
        where, args = ("WHERE lane = ?", (lane,)) if lane else ("", ())
        return [dict(r) for r in conn.execute(f"SELECT * FROM refunds {where} ORDER BY created_at", args)]


def reset() -> None:
    init()
    with connect(config.LEDGER_DB) as conn:
        conn.execute("DELETE FROM refunds")
