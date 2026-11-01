"""What the page shows about each stack, read in the background: Lane 1's job table, payments' counters and
ledger, the Lane 2 workflows, and the live Nexus operations between them.

Mixed into `Engine` (engine.py), which owns the state these methods fill in (`flow`, `nexus_seen`, `faults`,
`payments_calls*`, `lane1_view_all`, `lane2_status`, ...). The decisions about what a status means are the pure
functions in timeline.py.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter

from temporalio.api.enums.v1 import PendingActivityState
from temporalio.client import Client

from paidonce import config
from paidonce.lane2.payments_side import REFUND_START_TO_CLOSE, refund_workflow_id
from paidonce.lane2.support_side import ticket_workflow_id
from paidonce.models import TicketOutcome
from paidonce.show.catalog import GAUNTLET_REFUNDS, GAUNTLET_STALL_S, is_demo
from paidonce.show.timeline import (
    LANE1_STAGES,
    backoff_before,
    enum_name,
    finish_attempts,
    lane2_stage,
    merge_attempts,
    scene_calls,
    stall_window,
    ticket_ledger,
    ts,
)


class ViewsMixin:
    async def refresh_views(self) -> None:
        """Background: what each lane believes, and the live Nexus operations (Lane 2)."""
        pairs = self.scene_pairs(self.current) if self.current else []
        await self._refresh_lane1(pairs)
        await self._refresh_payments(pairs)
        await self._refresh_lane2(pairs)

    async def _refresh_lane1(self, pairs: list[tuple[str, str]]) -> None:
        """Lane 1's own job table: where the queue thinks each of this scene's tickets is."""
        try:
            r = await self.http.get(f"{config.LANE1_URL}/tickets")
            counts_all: dict[str, int] = {}
            ours = {tid for lane, tid in pairs if lane == "lane1"}
            flow1 = []
            for t in r.json():
                if not is_demo(t["ticket_id"]):
                    counts_all[t["status"]] = counts_all.get(t["status"], 0) + 1
                if t["ticket_id"] in ours:
                    at, state = LANE1_STAGES.get(t["status"], ("lane1_api", t["status"]))
                    if t["status"] == "denied" and t.get("detail"):
                        state = f"{state}: {t['detail']}"
                    flow1.append({"ticket": t["ticket_id"], "at": at, "state": state})
            self.lane1_view_all = counts_all
            self.flow["lane1"] = flow1
            self.lane1_jobs = (await self.http.get(f"{config.LANE1_URL}/admin/queue")).json()["jobs"]
        except Exception:
            pass

    async def _refresh_payments(self, pairs: list[tuple[str, str]]) -> None:
        """Payments' own counters and ledger: calls per ticket, when Lane 2's refunds were paid, the stall window."""
        try:
            r = await self.http.get(f"{config.PAYMENTS_URL}/admin/fault")
            self.faults = r.json()
            r = await self.http.get(f"{config.PAYMENTS_URL}/admin/calls")
            self.payments_calls_by_ticket = r.json()
            self.payments_calls = scene_calls(self.payments_calls_by_ticket, pairs)
            self.payments_calls_all = scene_calls(
                self.payments_calls_by_ticket,
                [(lane, tid) for lane, per in self.payments_calls_by_ticket.items() for tid in per if not is_demo(tid)],
            )
            r = await self.http.get(f"{config.PAYMENTS_URL}/refunds", params={"lane": "lane2"})
            self.booked_at = {row["ticket_id"]: row["created_at"] for row in r.json()}
            run = self.scene_runs.get(self.current) if self.current else None
            for w in run["faults"] if run else []:
                if w["effect"] == "stall":
                    lane2 = [tid for lane, tid in pairs if lane == "lane2"]
                    w.update(
                        stall_window(
                            self.booked_at, lane2, GAUNTLET_STALL_S, self.faults.get("lane2"), GAUNTLET_REFUNDS
                        )
                    )
        except Exception:
            pass

    async def _refresh_lane2(self, pairs: list[tuple[str, str]]) -> None:
        """Every Lane 2 workflow of this scene: its place on the diagram, and its Nexus operation if it has one."""
        try:
            client = await self.temporal()
        except Exception:
            return
        seen = self.nexus_seen  # run_scene swaps in a new dict; never write a stale scene into it
        flow2 = []
        for lane, tid in pairs:
            if lane != "lane2":
                continue
            # One ticket's failed describe must not freeze the whole view (the payments worker may be dead).
            stage = await self._track_lane2_ticket(client, tid, seen)
            if stage is not None:
                flow2.append({"ticket": tid, **stage})
        if seen is self.nexus_seen:
            self.lane2_view_all = dict(Counter(self.lane2_status.values()))
            self.flow["lane2"] = flow2

    async def _track_lane2_ticket(self, client: Client, tid: str, seen: dict[str, dict]) -> dict | None:
        """Read one support workflow and keep its Nexus operation row up to date in `seen`. Returns the ticket's
        place on the diagram, or None if the workflow could not be described."""
        desc = await self._describe(client, ticket_workflow_id(tid))
        if desc is None:
            return None
        status = desc.status.name if desc.status else "UNKNOWN"
        if not is_demo(tid):
            self.lane2_status[tid] = status
        ops = desc.raw_description.pending_nexus_operations
        if status == "COMPLETED" and tid not in self.lane2_outcomes:
            # describe() can't tell a refund from a denial. The result can, and reading it needs no worker.
            outcome = await self._outcome(client, ticket_workflow_id(tid))
            if outcome is not None:
                self.lane2_outcomes[tid] = outcome
        stage = lane2_stage(
            status,
            desc.raw_description.pending_activities,
            ops,
            self.decisions.get(tid),
            self.lane2_outcomes.get(tid),
        )
        row = seen.get(tid)
        if ops:
            op = ops[0]
            failure = (
                op.last_attempt_failure.message[:120]
                if op.last_attempt_failure and op.last_attempt_failure.message
                else ""
            )
            handler = await self._handler_view(tid)
            pending = handler.pop("pending", None)
            prev = row or {}
            handler["peak_activity_attempt"] = max(
                handler.get("activity_attempt", 0),
                prev.get("handler", {}).get("peak_activity_attempt", 0),
            )
            seen[tid] = {
                "ticket": tid,
                "live": True,
                "handler": handler,
                "state": enum_name(op),
                "attempts": merge_attempts(prev.get("attempts", []), pending, time.time()),
                "last_failure": failure,
                "caller_saw_failure": bool(failure) or prev.get("caller_saw_failure", False),
                # How many times support's own start of the operation was attempted. Not drawn: `make scenario`
                # reads it, to show that payments' retries never reached the caller.
                "attempt": op.attempt,
                "peak_attempt": max(op.attempt, prev.get("peak_attempt", 0)),
            }
        elif row is not None and row["live"]:
            # The operation closed since the last refresh: keep the row, with its final state.
            now = time.time()
            handler = await self._handler_view(tid) or dict(row["handler"])
            pending = handler.pop("pending", None)
            handler["peak_activity_attempt"] = row["handler"].get("peak_activity_attempt", 0)
            handler["activity_attempt"] = 0
            closed_badly = status in ("FAILED", "TIMED_OUT", "TERMINATED", "CANCELED")
            final_state = "FAILED" if closed_badly else "COMPLETED"
            attempts = merge_attempts(row.get("attempts", []), pending, now)
            if handler.get("status") not in (None, "RUNNING"):
                attempts = finish_attempts(attempts, await self._final_attempt(tid), now)
            row.update(live=False, state=final_state, handler=handler, attempts=attempts)
        elif row is not None and row.get("attempts") and any(a["outcome"] == "running" for a in row["attempts"]):
            # Closed earlier, but the refund workflow hadn't finished then: try its history again.
            if (await self._handler_view(tid)).get("status") not in (None, "RUNNING"):
                row["attempts"] = finish_attempts(row["attempts"], await self._final_attempt(tid), time.time())
        if tid in seen:
            seen[tid]["ledger"] = ticket_ledger(self.payments_calls_by_ticket, self.booked_at, "lane2", tid)
        return stage

    @staticmethod
    async def _describe(client: Client, workflow_id: str):
        try:
            return await client.get_workflow_handle(workflow_id).describe()
        except Exception:
            return None

    @staticmethod
    async def _outcome(client: Client, workflow_id: str) -> TicketOutcome | None:
        try:
            handle = client.get_workflow_handle(workflow_id, result_type=TicketOutcome)
            return await asyncio.wait_for(handle.result(), timeout=2.0)
        except Exception:
            return None

    async def _handler_view(self, ticket_id: str) -> dict:
        """The payments side of one Nexus operation: the refund workflow and its pending activity.

        Once payments has accepted the operation, the caller's side shows STARTED while the handler retries,
        so this is where the retries show. The dashboard reads it directly; the support side never does.
        """
        try:
            client = await self.payments_temporal()
            desc = await client.get_workflow_handle(refund_workflow_id(ticket_id)).describe()
            acts = desc.raw_description.pending_activities
            act = acts[0] if acts else None
            return {
                "status": desc.status.name if desc.status else "UNKNOWN",
                "activity_attempt": act.attempt if act else 0,
                # Raw timings for the attempt timeline; refresh_views pops this before it reaches the UI.
                "pending": (
                    {
                        "state": PendingActivityState.Name(act.state).replace("PENDING_ACTIVITY_STATE_", ""),
                        "attempt": act.attempt,
                        "scheduled_at": ts(act.scheduled_time),
                        "started_at": ts(act.last_started_time),
                        # The server's current_retry_interval isn't usable (garbage or unset), so the backoff
                        # before this attempt comes from the refund workflow's own retry policy.
                        "retry_interval": backoff_before(act.attempt),
                        "start_to_close": REFUND_START_TO_CLOSE.total_seconds(),
                        "failure": act.last_failure.message[:120]
                        if act.last_failure and act.last_failure.message
                        else "",
                    }
                    if act
                    else None
                ),
            }
        except Exception:
            return {}

    async def _final_attempt(self, ticket_id: str) -> dict | None:
        """The refund workflow's last activity attempt, exactly, from its history."""
        try:
            client = await self.payments_temporal()
            final: dict | None = None
            async for e in client.get_workflow_handle(refund_workflow_id(ticket_id)).fetch_history_events():
                kind = e.WhichOneof("attributes")
                if kind == "activity_task_started_event_attributes":
                    final = {
                        "n": e.activity_task_started_event_attributes.attempt,
                        "started_at": ts(e.event_time),
                        "ended_at": None,
                        "ok": False,
                        "failure": "",
                    }
                elif final is not None and kind == "activity_task_completed_event_attributes":
                    final.update(ended_at=ts(e.event_time), ok=True)
                elif final is not None and kind in (
                    "activity_task_failed_event_attributes",
                    "activity_task_timed_out_event_attributes",
                ):
                    attrs = getattr(e, kind)
                    final.update(ended_at=ts(e.event_time), failure=attrs.failure.message[:120])
            return final if final and final["ended_at"] else None
        except Exception:
            return None
