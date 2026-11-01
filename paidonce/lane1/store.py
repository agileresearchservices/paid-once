"""Lane 1 storage: ticket rows plus a jobs table that behaves like SQS or Pub/Sub.

Delivery is at-least-once with a visibility timeout: a claimed job that is not completed
within the timeout becomes visible again and is handed to the next worker.
"""

from __future__ import annotations

import json
import time

from paidonce import config
from paidonce.db import connect, ensure_schema, transaction
from paidonce.models import DEFAULT_ORDER_AGE_DAYS

# Statuses from which a ticket has been approved: the human's "yes" is in, whether or not the refund has landed.
APPROVED_STATES = ("approved", "executing", "done")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY, customer TEXT, order_id TEXT, amount_cents INTEGER, message TEXT,
  order_age_days INTEGER NOT NULL,
  status TEXT NOT NULL, proposal TEXT, refund_id TEXT, detail TEXT DEFAULT '',
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ticket_id TEXT NOT NULL,
  available_at REAL NOT NULL, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ticket_id TEXT, completed_at REAL
);
"""


def init() -> None:
    ensure_schema(config.LANE1_DB, SCHEMA)


def create_ticket(ticket: dict) -> bool:
    """Insert a ticket and enqueue its first job. Returns False if it already exists."""
    init()
    now = time.time()
    with transaction(config.LANE1_DB) as conn:
        exists = conn.execute("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket["ticket_id"],)).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO tickets (ticket_id, customer, order_id, amount_cents, message, order_age_days, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?)",
            (
                ticket["ticket_id"],
                ticket["customer"],
                ticket["order_id"],
                ticket["amount_cents"],
                ticket["message"],
                ticket.get("order_age_days", DEFAULT_ORDER_AGE_DAYS),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO jobs (kind, ticket_id, available_at) VALUES ('decide', ?, ?)",
            (ticket["ticket_id"], now),
        )
    return True


def get_ticket(ticket_id: str) -> dict | None:
    init()
    with connect(config.LANE1_DB) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["proposal"] = json.loads(out["proposal"]) if out["proposal"] else None
    return out


def list_tickets() -> list[dict]:
    init()
    with connect(config.LANE1_DB) as conn:
        rows = conn.execute("SELECT ticket_id, status, refund_id, detail FROM tickets ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def set_status(
    ticket_id: str,
    status: str,
    *,
    proposal: dict | None = None,
    refund_id: str | None = None,
    detail: str | None = None,
) -> None:
    sets, args = ["status = ?", "updated_at = ?"], [status, time.time()]
    if proposal is not None:
        sets.append("proposal = ?")
        args.append(json.dumps(proposal))
    if refund_id is not None:
        sets.append("refund_id = ?")
        args.append(refund_id)
    if detail is not None:
        sets.append("detail = ?")
        args.append(detail)
    args.append(ticket_id)
    with connect(config.LANE1_DB) as conn:
        conn.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE ticket_id = ?", args)


def approve(ticket_id: str) -> str:
    """Human approval. Returns accepted | not_ready | unknown | already."""
    init()
    now = time.time()
    with transaction(config.LANE1_DB) as conn:
        row = conn.execute("SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            return "unknown"
        if row["status"] != "awaiting_approval":
            return "already" if row["status"] in APPROVED_STATES else "not_ready"
        conn.execute(
            "UPDATE tickets SET status = 'approved', updated_at = ? WHERE ticket_id = ?",
            (now, ticket_id),
        )
        conn.execute(
            "INSERT INTO jobs (kind, ticket_id, available_at) VALUES ('execute', ?, ?)",
            (ticket_id, now),
        )
    return "accepted"


def reject(ticket_id: str) -> str:
    """Human denial. Closes the row at the API: no job is queued, so nothing can re-drive it.
    Returns accepted | not_ready | unknown | already | approved."""
    init()
    with transaction(config.LANE1_DB) as conn:
        row = conn.execute("SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            return "unknown"
        if row["status"] != "awaiting_approval":
            if row["status"] == "rejected":
                return "already"
            return "approved" if row["status"] in APPROVED_STATES else "not_ready"
        conn.execute(
            "UPDATE tickets SET status = 'rejected', detail = 'denied by a human', updated_at = ? WHERE ticket_id = ?",
            (time.time(), ticket_id),
        )
    return "accepted"


_NEXT_JOB = (
    "SELECT * FROM jobs WHERE available_at <= ? AND (lease_until IS NULL OR lease_until < ?) ORDER BY job_id LIMIT 1"
)


def claim_job() -> dict | None:
    """Claim the next visible job and hide it for the visibility timeout."""
    init()
    now = time.time()
    # Four threads poll every fraction of a second: look with a plain read first, and take the write lock only
    # when there is something to claim.
    with connect(config.LANE1_DB) as conn:
        if conn.execute(_NEXT_JOB, (now, now)).fetchone() is None:
            return None
    with transaction(config.LANE1_DB) as conn:
        row = conn.execute(_NEXT_JOB, (now, now)).fetchone()  # another worker may have taken it meanwhile
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET lease_until = ?, attempts = attempts + 1 WHERE job_id = ?",
            (now + config.VISIBILITY_TIMEOUT_S, row["job_id"]),
        )
    return dict(row)


def extend_lease(job_id: int) -> None:
    """Heartbeat: push a claimed job's visibility timeout out again while its worker is still alive."""
    with connect(config.LANE1_DB) as conn:
        conn.execute(
            "UPDATE jobs SET lease_until = ? WHERE job_id = ?",
            (time.time() + config.VISIBILITY_TIMEOUT_S, job_id),
        )


def complete_job(job: dict) -> None:
    with connect(config.LANE1_DB) as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job["job_id"],))
        conn.execute(
            "INSERT INTO job_log (kind, ticket_id, completed_at) VALUES (?, ?, ?)",
            (job["kind"], job["ticket_id"], time.time()),
        )


def pending_jobs() -> int:
    """Jobs still in the queue: waiting, or claimed and not yet finished. The show waits for this to reach zero."""
    init()
    with connect(config.LANE1_DB) as conn:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def redeliver(n: int) -> int:
    """Chaos: the broker delivers some recent execute jobs a second time (at-least-once)."""
    init()
    now = time.time()
    with transaction(config.LANE1_DB) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticket_id FROM jobs WHERE kind = 'execute' "
            "UNION SELECT ticket_id FROM (SELECT ticket_id FROM job_log WHERE kind = 'execute' ORDER BY id DESC LIMIT ?)",
            (n,),
        ).fetchall()
        picked = [r["ticket_id"] for r in rows][:n]
        for ticket_id in picked:
            conn.execute(
                "INSERT INTO jobs (kind, ticket_id, available_at) VALUES ('execute', ?, ?)",
                (ticket_id, now),
            )
    return len(picked)


def reset() -> None:
    init()
    with connect(config.LANE1_DB) as conn:
        for table in ("tickets", "jobs", "job_log"):
            conn.execute(f"DELETE FROM {table}")
