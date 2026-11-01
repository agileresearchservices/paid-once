"""The approver bot and the cohorts: submit tickets to both lanes and play the human who reviews them.

Mixed into `Engine` (engine.py), whose state it uses: `run_id`, `run_no`, `rng`, `plan`, `decisions`,
`scene_tickets`, `flow`, and the `http` / `temporal()` clients.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from temporalio.client import WorkflowExecutionStatus

from paidonce import agent, audit, config
from paidonce.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from paidonce.models import DEFAULT_ORDER_AGE_DAYS, ApprovalDecision, Ticket
from paidonce.show.catalog import LANE_NAMES, MESSAGES, ticket_id


class HarnessMixin:
    def _make_ticket(
        self, scene: str, i: int, lane: str, amount: int, message: str, age: int = DEFAULT_ORDER_AGE_DAYS
    ) -> Ticket:
        tid = ticket_id(self.run_id, scene, self.run_no, i, lane)
        return Ticket(tid, f"cust-{i:02d}", f"ord-{self.run_id}-r{self.run_no}-{i:02d}", amount, message, age)

    async def submit_ticket(self, lane: str, scene: str, ticket: Ticket, expect: str = "refund") -> None:
        audit.record_ticket(lane, ticket.ticket_id, scene, ticket.amount_cents, expect)
        self.plan[ticket.ticket_id] = expect
        self.scene_tickets.setdefault(scene, []).append((lane, ticket.ticket_id))
        if lane == "lane1":
            body = {
                "ticket_id": ticket.ticket_id,
                "customer": ticket.customer,
                "order_id": ticket.order_id,
                "amount_cents": ticket.amount_cents,
                "message": ticket.message,
                "order_age_days": ticket.order_age_days,
            }
            for _ in range(60):  # a helpdesk webhook retries until the API answers
                try:
                    r = await self.http.post(f"{config.LANE1_URL}/tickets", json=body)
                    if r.status_code < 500:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        else:
            client = await self.temporal()
            await client.start_workflow(
                SupportTicketWorkflow.run,
                ticket,
                id=ticket_workflow_id(ticket.ticket_id),
                task_queue=config.SUPPORT_TASK_QUEUE,
            )

    async def submit_cohort(self, scene: str, n: int, lanes=("lane1", "lane2")) -> None:
        """n refunds the human will approve, then two the money must never reach: one that breaks the refund
        policy (over the limit, or past the return window, alternating by scene run) and one a human denies."""
        recent, ordinary = DEFAULT_ORDER_AGE_DAYS, (1500, 9500)
        over_the_limit = (agent.POLICY_LIMIT_CENTS + 4000, 60000)
        past_the_window = agent.RETURN_WINDOW_DAYS + 15
        specs = [(i, self.rng.randrange(*ordinary, 100), self.rng.choice(MESSAGES), recent, "refund") for i in range(n)]
        if self.run_no % 2:
            specs.append((n, self.rng.randrange(*over_the_limit, 100), self.rng.choice(MESSAGES), recent, "policy"))
        else:
            specs.append((n, self.rng.randrange(*ordinary, 100), self.rng.choice(MESSAGES), past_the_window, "policy"))
        specs.append((n + 1, self.rng.randrange(*ordinary, 100), self.rng.choice(MESSAGES), recent, "human_no"))
        jobs = []
        for lane in lanes:
            for i, amount, msg, age, expect in specs:
                ticket = self._make_ticket(scene, i, lane, amount, msg, age)
                jobs.append(self.submit_ticket(lane, scene, ticket, expect))
        await asyncio.gather(*jobs)
        self.emit(
            "submit",
            f"{len(specs)} support tickets asking for refunds submitted to "
            f"{' and '.join(LANE_NAMES[lane] for lane in lanes)}",
            scene=scene,
        )

    async def decide_ticket(self, lane: str, ticket_id: str, approved: bool) -> None:
        """A human clicks Approve or Deny. The decision is recorded the moment it is made, delivered or not."""
        audit.record_decision(lane, ticket_id, approved)
        self.decisions[ticket_id] = approved
        if lane == "lane1":
            action = "approve" if approved else "reject"
            for _ in range(80):
                try:
                    r = await self.http.post(f"{config.LANE1_URL}/tickets/{ticket_id}/{action}")
                    if r.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)  # 409 = no proposal yet, or the API is down: click again
        else:
            for _ in range(80):
                try:
                    client = await self.temporal()
                    handle = client.get_workflow_handle(ticket_workflow_id(ticket_id))
                    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(approved))
                    return
                except Exception:
                    await asyncio.sleep(0.5)

    async def approve_scene(
        self,
        scene: str,
        who: str = "A human",
        then: str = "",
        stagger: float = 0.05,
        only=None,
        policy_note: bool = True,
    ) -> None:
        """The human reviews the agent's proposals: approves the refunds, denies one. Policy tickets never reach
        the human; the agent's policy check already closed them. `only` (a ticket id -> bool) limits the review to
        part of the cohort, for a scene where the human gets to some tickets before a fault and the rest after."""
        pairs = [
            (lane, tid)
            for lane, tid in self.scene_tickets.get(scene, [])
            if self.plan[tid] != "policy" and (only is None or only(tid))
        ]
        first_lane = pairs[0][0] if pairs else None  # the summary counts one lane: both get the same cohort
        reviewed = [tid for lane, tid in pairs if lane == first_lane]
        yes = sum(self.plan[tid] == "refund" for tid in reviewed)
        no = sum(self.plan[tid] == "human_no" for tid in reviewed)
        closed = sum(
            self.plan[tid] == "policy" for lane, tid in self.scene_tickets.get(scene, []) if lane == first_lane
        )
        tail = f" The agent's policy check closed {closed} before review." if policy_note else ""
        self.emit("human", f"{who} reviews {yes + no} proposals: approves {yes}, denies {no}{then}.{tail}", scene=scene)
        tasks = []
        for lane, tid in pairs:
            tasks.append(asyncio.create_task(self.decide_ticket(lane, tid, self.plan[tid] == "refund")))
            await asyncio.sleep(stagger)
        await asyncio.gather(*tasks)

    async def wait_for_proposals(self, scene: str, timeout: float = 45.0) -> None:
        """Wait until the agent has handled every ticket in the scene: a proposal waiting for a human, or denied."""
        end = time.time() + timeout
        pairs = list(self.scene_tickets.get(scene, []))
        while time.time() < end:
            ready = 0
            try:
                r = await self.http.get(f"{config.LANE1_URL}/tickets")
                l1 = {t["ticket_id"]: t["status"] for t in r.json()}
            except Exception:
                l1 = {}
            client = await self.temporal()
            for lane, tid in pairs:
                if lane == "lane1":
                    ready += l1.get(tid) in ("awaiting_approval", "denied")
                else:
                    handle = client.get_workflow_handle(ticket_workflow_id(tid))
                    try:
                        st = await handle.query(SupportTicketWorkflow.status)
                        ready += st["state"] in ("awaiting_approval", "denied")
                    except Exception:
                        try:  # a denied workflow has completed; describe() needs no worker
                            ready += (await handle.describe()).status == WorkflowExecutionStatus.COMPLETED
                        except Exception:
                            pass
            if ready >= len(pairs):
                return
            await asyncio.sleep(0.5)
        self.emit("note", "timed out waiting for every proposal", scene=scene)

    async def wait_for_stage(self, scene: str, lane1: set[str], lane2: set[str], timeout: float = 20.0) -> None:
        """Until each lane's ticket in `scene` is at one of the given diagram spots (see LANE1_STAGES, lane2_stage)."""
        want = {"lane1": lane1, "lane2": lane2}
        pairs = self.scene_tickets.get(scene, [])
        end = time.time() + timeout
        while time.time() < end:
            at = {(lane, d["ticket"]): d["at"] for lane in self.flow for d in self.flow[lane]}
            if pairs and all(at.get((lane, tid)) in want[lane] for lane, tid in pairs):
                return
            await asyncio.sleep(0.25)
        self.emit("note", f"timed out waiting for the tickets to reach {sorted(lane1 | lane2)}", scene=scene)
