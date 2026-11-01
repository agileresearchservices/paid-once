"""Pure functions that turn what Temporal and payments report into what the page draws: where a ticket is, which
attempts a refund made, the payments-quiet window, and when a scene has settled. No I/O, so they are easy to test."""

from __future__ import annotations

from temporalio.api.enums.v1 import PendingNexusOperationState

from paidonce.lane2.payments_side import REFUND_RETRY
from paidonce.models import TicketOutcome

# Lane 1 ticket status -> (diagram node or wire, what the queue believes). Read from its own table.
LANE1_STAGES = {
    "new": ("lane1_api", "queued for the agent"),
    "deciding": ("lane1_worker", "agent deciding"),
    "awaiting_approval": ("lane1_api", "waiting for a human"),
    "approved": ("lane1_api", "approved, queued to refund"),
    "executing": ("lane1_worker>payments", "calling payments"),
    "done": ("done", "refunded"),
    "failed": ("lane1_worker", "failed"),
    # Closed with no refund: the ticket goes back to the helpdesk with the answer.
    "denied": ("closed", "denied by the agent"),
    "rejected": ("closed", "denied by a human"),
}


# Where a stack leaves a ticket it has given up on: Lane 1's job status, or a closed Lane 2 workflow (lane2_stage).
STOPPED_STATES = {"failed", "terminated", "canceled", "timed out", "continued as new"}


def lane2_stage(
    status: str, activities, ops, decision: bool | None = None, outcome: TicketOutcome | None = None
) -> dict:
    """Where a support workflow is, from describe() and its result: a query would need a live worker.
    `decision` is the human's (True = approve), `outcome` the completed workflow's result."""
    if status == "COMPLETED":
        if outcome is None:
            return {"at": "temporal", "state": "completed, reading the result"}  # for a refresh at most
        if outcome.status == "denied":
            return {"at": "closed", "state": f"denied by the agent: {outcome.detail}"}
        if outcome.status == "rejected":
            return {"at": "closed", "state": "denied by a human"}
        return {"at": "done", "state": "refunded"}
    if status != "RUNNING":
        return {"at": "support_worker", "state": status.lower().replace("_", " ")}
    if ops:
        # STARTED means payments accepted the operation and its RefundWorkflow owns the retries.
        if enum_name(ops[0]) == "STARTED":
            return {"at": "payments_worker", "state": "refund running in payments"}
        return {"at": "endpoint", "state": "Nexus operation starting"}
    if activities:
        return {"at": "support_worker", "state": "agent deciding"}
    if decision is True:
        # Approved but nothing pending: the signal is in history and the support worker is down or not yet polling.
        return {"at": "temporal", "state": "approved, queued in Temporal for a worker"}
    if decision is False:
        return {"at": "temporal", "state": "denied, queued in Temporal for a worker"}
    return {"at": "temporal", "state": "waiting in Temporal"}


def unsettled(
    pairs: list[tuple[str, str]], ledger: dict[str, dict[str, str]], flow: dict[str, list[dict]]
) -> list[str]:
    """Tickets still moving. The ledger must have decided each one (refunded, owed nothing, or missing once the
    settle window has passed), and the stack must have stopped: done, closed with no refund, or a terminal status
    such as Lane 1's "failed"."""
    dots = {lane: {d["ticket"]: d for d in flow.get(lane, [])} for lane in flow}
    out = []
    for lane, tid in pairs:
        dot = dots.get(lane, {}).get(tid)
        decided = ledger.get(lane, {}).get(tid) not in (None, "in_flight", "waiting")
        stopped = dot is not None and (dot["at"] in ("done", "closed") or dot["state"] in STOPPED_STATES)
        if not (decided and stopped):
            out.append(tid)
    return out


def scene_calls(calls: dict, pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Payments' per-ticket call counts, summed per lane over this scene's tickets."""
    out: dict[str, dict[str, int]] = {}
    for lane, tid in pairs:
        c = calls.get(lane, {}).get(tid)
        if c:
            row = out.setdefault(lane, {"calls": 0, "booked": 0, "replays": 0})
            row["calls"] += c["calls"]
            row["replays"] += c["replays"]
            row["booked"] += c["calls"] - c["replays"]
    return out


def enum_name(op) -> str:
    """A pending Nexus operation's state as a short name: SCHEDULED, STARTED, BACKING_OFF..."""
    try:
        return PendingNexusOperationState.Name(op.state).replace("PENDING_NEXUS_OPERATION_STATE_", "")
    except ValueError:  # a state this client library doesn't know yet
        return str(op.state)


def merge_attempts(prev: list[dict], pending: dict | None, now: float) -> list[dict]:
    """Fold one poll of the refund workflow's pending activity into the attempts seen so far.

    `pending` is {state, attempt, scheduled_at, started_at, retry_interval, start_to_close, failure} or None.
    Attempt N is recorded only once the activity is STARTED with attempt == N: after a timeout it goes back to
    SCHEDULED with attempt N+1, and that poll is what ends attempt N. A StartToClose timeout ended it at its start
    plus the timeout; otherwise at the next attempt's scheduled time minus the backoff, or at `now`.
    """
    attempts = [dict(a) for a in prev]
    if not pending:
        return attempts
    n = pending["attempt"]
    for a in attempts:
        if a["n"] < n and a["outcome"] == "running":
            failure = pending.get("failure", "")
            sched = pending.get("scheduled_at")
            if "StartToClose" in failure and pending.get("start_to_close"):
                end = a["started_at"] + pending["start_to_close"]  # exact: the timeout is what ended it
            elif sched:
                end = sched - pending.get("retry_interval", 0.0)
            else:
                end = now
            a.update(ended_at=min(max(end, a["started_at"]), now), outcome="failed", failure=failure)
    if pending["state"] == "STARTED" and not any(a["n"] == n for a in attempts):
        attempts.append(
            {
                "n": n,
                "started_at": pending.get("started_at") or now,
                "ended_at": None,
                "outcome": "running",
                "failure": "",
            }
        )
    return attempts


def finish_attempts(prev: list[dict], final: dict | None, now: float) -> list[dict]:
    """Close the attempts once the refund workflow has closed, using its history for the last attempt.

    `final` is {n, started_at, ended_at, ok, failure} from the last ActivityTaskStarted and the event that
    closed it. That attempt may have started and finished between two polls, so history is the only exact
    source. Without history, anything still running is closed at `now` with an unknown outcome.
    """
    attempts = [dict(a) for a in prev]
    if final is None:
        for a in attempts:
            if a["outcome"] == "running":
                a.update(ended_at=now, outcome="unknown")
        return attempts
    for a in attempts:
        if a["n"] < final["n"] and a["outcome"] == "running":
            a.update(ended_at=max(final["started_at"], a["started_at"]), outcome="failed")
    attempts = [a for a in attempts if a["n"] != final["n"]]
    attempts.append(
        {
            "n": final["n"],
            "started_at": final["started_at"],
            "ended_at": final["ended_at"],
            "outcome": "ok" if final["ok"] else "failed",
            "failure": final.get("failure", ""),
        }
    )
    return sorted(attempts, key=lambda a: a["n"])


def backoff_before(attempt: int) -> float:
    """The refund retry policy's wait before `attempt` (attempt 2 waits the initial interval)."""
    if attempt <= 1:
        return 0.0
    initial = REFUND_RETRY.initial_interval.total_seconds()
    wait = initial * REFUND_RETRY.backoff_coefficient ** (attempt - 2)
    cap = REFUND_RETRY.maximum_interval.total_seconds() if REFUND_RETRY.maximum_interval else wait
    return min(wait, cap)


def stall_window(booked_at: dict, tickets: list[str], delay_s: float, fault: dict | None, count: int) -> dict:
    """The payments-quiet window, from the ledger: the first stalled booking to the last one's held reply.
    `hit` is how many bookings the stall actually held (the payments fault's count minus what it has left)."""
    times = sorted(booked_at[t] for t in tickets if t in booked_at)
    left = fault.get("remaining", count) if fault and fault.get("mode") == "commit_then_stall" else 0
    hit = min(count - left, len(times)) if fault and fault.get("mode") == "commit_then_stall" else len(times)
    if not times:
        return {"start": None, "end": None, "hit": 0}
    return {"start": times[0], "end": times[min(hit, len(times)) - 1] + delay_s if hit else times[0], "hit": hit}


def ticket_ledger(calls: dict, booked_at: dict, lane: str, ticket_id: str) -> dict:
    """One ticket as payments saw it: calls, calls answered from the ledger, and when the money was booked."""
    c = calls.get(lane, {}).get(ticket_id) or {"calls": 0, "replays": 0}
    return {"calls": c["calls"], "replays": c["replays"], "booked_at": booked_at.get(ticket_id)}


def ts(stamp) -> float | None:
    """A protobuf Timestamp as epoch seconds, or None if unset."""
    if stamp is None or not (stamp.seconds or stamp.nanos):
        return None
    return stamp.seconds + stamp.nanos / 1e9
