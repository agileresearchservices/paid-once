"""The show engine: submits tickets to both lanes, plays the human approver, and injects the faults.

A scene runs the same story against Lane 1 (Queue + LangGraph) and Lane 2 (Temporal + Nexus) at the same
time, so the audience watches two systems take identical hits. The exceptions are the walkthrough (one ticket)
and the Nexus gauntlet (Lane 2 only). Scoring comes from the payments ledger (paidonce.audit), never from
what either lane reports about itself.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields

import httpx
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.client import Client, WorkflowExecutionStatus

from paidonce import audit, config, tls
from paidonce.lane2.client import connect_temporal
from paidonce.lane2.contract import NEXUS_ENDPOINT, PaymentsService
from paidonce.lane2.payments_side import REFUND_RETRY, REFUND_START_TO_CLOSE, RefundWorkflow, refund_workflow_id
from paidonce.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from paidonce.models import ApprovalDecision, RefundRequest, RefundResult, Ticket, TicketOutcome
from paidonce.show.procs import ProcessManager

# A scene stays "running" after its script until every ticket has landed, so Run again never appears mid-flight.
SCENE_SETTLE_MAX_S = 45.0
SCENE_QUIET_S = 3.0

# How the show names each lane on screen; the code, ledger and ticket IDs keep lane1/lane2.
LANE_NAMES = {"lane1": "Queue + LangGraph", "lane2": "Temporal + Nexus"}

AGENT_WORKERS = ["lane1_worker", "support_worker"]

# The worker-crash scene (step 3): the first few approved refunds are in flight at payments when the workers die;
# the rest of the cohort is still waiting for a human.
WORKER_CRASH_COHORT = 6
WORKER_CRASH_IN_FLIGHT = 3

# Scored on their own and left out of the scoreboard totals: the walkthrough is a demonstration, and Nexus is its own step.
DEMO_SCENES = ("walkthrough", "nexus_kill")

# The Nexus gauntlet (step 7): four failures, each landing on refunds still in flight.
GAUNTLET_STALL_S = 9.0  # payments holds its reply this long after booking: past the activity's 8 s timeout
GAUNTLET_LATENCY_S = 2.0  # every payments call takes this long, so a kill lands mid-call
GAUNTLET_DOWN_S = {"support_worker": 5.0, "payments_worker": 6.0, "temporal": 5.0}

# The walkthrough (step 1): one ticket, with the refund slowed a little so it is visible in flight. Stays under Lane 1's
# 3 s payments client timeout, or its retry would book the refund twice on the happy path.
WALKTHROUGH_LATENCY_S = 2.5
# How long each walkthrough step stays on screen before the scene moves on, so a viewer can follow it unprompted. The
# "agent" step is also held until the agent has decided; this is its minimum.
WALKTHROUGH_END_HOLD_S = 2.5
WALKTHROUGH_DWELL_S = {"ticket": 3.5, "agent": 4.0, "waiting": 4.5, "approve": 4.0}
WALKTHROUGH_AMOUNT_CENTS = 4200
WALKTHROUGH_MESSAGE = "The mug arrived in pieces. Please refund me."

MESSAGES = [
    "The mug arrived in pieces. Please refund me.",
    "I was charged twice for the same order, please refund the duplicate.",
    "My package never arrived and tracking says delivered to the wrong city.",
    "The headphones are dead on arrival, I would like my money back.",
    "Wrong size shipped and the box was crushed. I want a refund.",
    "The blender leaks from the base and cracked on first use. Refund please.",
]


@dataclass
class SceneInfo:
    id: str
    title: str


SCENES = [
    SceneInfo("walkthrough", "Walkthrough: one ticket"),
    SceneInfo("intro", "Happy path"),
    SceneInfo("worker_crash", "The agent workers go down (crash or deploy)"),
    SceneInfo("double_delivery", "Double-delivered mail"),
    SceneInfo("payments_timeout", "Payments commits, then goes quiet"),
    SceneInfo("nexus_kill", "Nexus: four failures mid-refund"),
    SceneInfo("free_roam", "Free roam"),
]


# Who owns what across the Nexus boundary, from the same config and contract the workers use.
TOPOLOGY = {
    "support": {
        "namespace": config.SUPPORT_NAMESPACE,
        "task_queue": config.SUPPORT_TASK_QUEUE,
        "workflow": SupportTicketWorkflow.__name__,
    },
    "endpoint": NEXUS_ENDPOINT,
    "service": PaymentsService.__name__,
    "operation": "issue_refund",
    # The contract's two messages, field by field, read off the dataclasses so step 7 can't drift from the code.
    "sends": [f.name for f in fields(RefundRequest)],
    "returns": [f.name for f in fields(RefundResult)],
    "payments": {
        "namespace": config.PAYMENTS_NAMESPACE,
        "task_queue": config.PAYMENTS_TASK_QUEUE,
        "workflow": RefundWorkflow.__name__,
        "activity": "post_refund",
    },
}


class Engine:
    def __init__(self, procs: ProcessManager, seed: int = 7) -> None:
        self.procs = procs
        self.seed = seed
        self.rng = random.Random(seed)
        self.run_id = uuid.uuid4().hex[:4]
        self.events: list[dict] = []
        self.current: str | None = None
        self.running = False
        self.scene_tickets: dict[str, list[tuple[str, str]]] = {}
        self.run_no = 0  # bumped per scene run, so a re-run never reuses ticket or workflow IDs
        self.scene_runs: dict[str, dict] = {}  # last run of each scene: started_at, finished_at, ok, kills
        self._temporal: Client | None = None
        self._payments_temporal: Client | None = None
        self._http: httpx.AsyncClient | None = None
        # Every Nexus operation seen in the current scene, kept after it completes so the evidence stays on screen.
        self.nexus_seen: dict[str, dict] = {}
        self.lane1_view_all: dict[str, int] = {}  # every ticket since reset: the scoreboard compares it with the ledger
        # Every Lane 2 ticket's last-seen workflow status since reset, so the card header accumulates like the scoreboard.
        self.lane2_status: dict[str, str] = {}
        self.lane2_view_all: dict[str, int] = {}
        # How each completed Lane 2 workflow ended (done, denied or rejected), read once from its result.
        self.lane2_outcomes: dict[str, TicketOutcome] = {}
        self.faults: dict = {}
        # What the harness wrote each ticket to be: "refund", "policy" (breaks the refund policy) or "human_no".
        self.plan: dict[str, str] = {}
        # The approver bot's decision per ticket (True = approve), so a parked workflow isn't drawn as waiting for
        # a human.
        self.decisions: dict[str, bool] = {}
        # This scene's calls to payments per lane, from payments' own counter: calls, booked, replays.
        self.payments_calls: dict[str, dict[str, int]] = {}
        # The same counter per ticket ({lane: {ticket: {calls, replays}}}), and when each Lane 2 refund was booked.
        self.payments_calls_by_ticket: dict[str, dict[str, dict[str, int]]] = {}
        self.payments_calls_all: dict[str, dict[str, int]] = {}  # the same counter, every ticket since reset
        self.booked_at: dict[str, float] = {}
        # Where each stack thinks each of this scene's tickets is, for the architecture diagram.
        self.flow: dict[str, list[dict]] = {"lane1": [], "lane2": []}
        # The walkthrough beat on screen: {scene, id, at}, or None. It advances on its own dwell timers.
        self.beat: dict | None = None
        self._task: asyncio.Task | None = None
        self.procs.emit = self.emit_from_procs

    # -- plumbing ------------------------------------------------------------
    def emit(self, kind: str, msg: str, **extra) -> None:
        self.events.append({"ts": time.time(), "kind": kind, "msg": msg, **extra})
        del self.events[:-200]

    def fault(self, scene: str, msg: str, target: list[str], effect: str) -> None:
        """A fault, with where it lands: diagram node ids (process names, or "temporal") and kill | duplicate | stall."""
        self.emit("fault", msg, scene=scene, target=target, effect=effect)

    def emit_from_procs(self, kind: str, msg: str, **extra) -> None:
        # Kills count against the scene that made them, so a step never shows kills from an earlier scene.
        run = self.scene_runs.get(self.current) if self.running and self.current else None
        if kind == "kill" and run is not None:
            kills = run["kills"]
            kills[extra["proc"]] = kills.get(extra["proc"], 0) + 1
        if kind == "restart" and run is not None:
            # Only a kill the scene injected has a window; an unplanned exit's restart closes nothing.
            for w in run["faults"]:
                if w["key"] == extra.get("proc") and w["end"] is None:
                    w["end"] = time.time()
        self.emit(kind, msg, **extra)

    def kill_window(self, scene: str, proc: str, label: str, down_s: float) -> bool:
        """kill -9 a process mid-scene and record its outage window, with how many refunds were in flight."""
        hit = sum(1 for r in self.nexus_seen.values() if r.get("live"))
        self.fault(scene, f"Fault: kill -9 on the {label}", [proc], "kill")
        run = self.scene_runs[scene]
        window = {"key": proc, "label": label, "effect": "kill", "start": time.time(), "end": None, "hit": hit}
        run["faults"].append(window)
        if not self.procs.kill(proc, down_s):
            run["faults"].remove(window)
            self.emit("error", f"could not kill {proc}: it was not running", scene=scene)
            return False
        return True

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=5.0, verify=tls.client_verify("payments", "lane1_api"))
        return self._http

    async def temporal(self) -> Client:
        if self._temporal is None:
            self._temporal = await connect_temporal(config.SUPPORT_NAMESPACE)
        return self._temporal

    async def payments_temporal(self) -> Client:
        if self._payments_temporal is None:
            self._payments_temporal = await connect_temporal(config.PAYMENTS_NAMESPACE)
        return self._payments_temporal

    # -- tickets and approvals --------------------------------------------------
    def _make_ticket(self, scene: str, i: int, lane: str, amount: int, message: str, age: int = 3) -> Ticket:
        tid = f"{self.run_id}-{scene}-r{self.run_no}-{i:02d}-{lane}"
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
        specs = [(i, self.rng.randrange(1500, 9500, 100), self.rng.choice(MESSAGES), 3, "refund") for i in range(n)]
        if self.run_no % 2:
            specs.append((n, self.rng.randrange(24000, 60000, 100), self.rng.choice(MESSAGES), 3, "policy"))
        else:
            specs.append((n, self.rng.randrange(1500, 9500, 100), self.rng.choice(MESSAGES), 45, "policy"))
        specs.append((n + 1, self.rng.randrange(1500, 9500, 100), self.rng.choice(MESSAGES), 3, "human_no"))
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
        one_lane = [tid for lane, tid in pairs if lane == pairs[0][0]] if pairs else []  # what this review covers
        yes = sum(self.plan[tid] == "refund" for tid in one_lane)
        no = sum(self.plan[tid] == "human_no" for tid in one_lane)
        lane_tickets = [tid for lane, tid in self.scene_tickets.get(scene, []) if lane == pairs[0][0]] if pairs else []
        closed = sum(self.plan[tid] == "policy" for tid in lane_tickets)
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

    # -- walkthrough steps -----------------------------------------------------------
    def start_beat(self, scene: str, beat: str) -> float:
        """Put a walkthrough step on screen (the snapshot's `beat`); returns when it started."""
        self.beat = {"scene": scene, "id": beat, "at": time.time()}
        return self.beat["at"]

    async def hold_beat(self, started: float, beat: str) -> None:
        """Keep the step on screen for its dwell time, counted from when it started."""
        await asyncio.sleep(max(0.0, started + WALKTHROUGH_DWELL_S[beat] - time.time()))

    async def wait_for_stage(self, scene: str, lane1: set[str], lane2: set[str], timeout: float = 20.0) -> None:
        """Until each lane's ticket in `scene` is at one of the given diagram spots (see LANE1_STAGES, _lane2_stage)."""
        want = {"lane1": lane1, "lane2": lane2}
        pairs = self.scene_tickets.get(scene, [])
        end = time.time() + timeout
        while time.time() < end:
            at = {(lane, d["ticket"]): d["at"] for lane in self.flow for d in self.flow[lane]}
            if pairs and all(at.get((lane, tid)) in want[lane] for lane, tid in pairs):
                return
            await asyncio.sleep(0.25)
        self.emit("note", f"timed out waiting for the tickets to reach {sorted(lane1 | lane2)}", scene=scene)

    # -- chaos primitives ----------------------------------------------------------
    async def set_fault(
        self,
        lane: str = "all",
        mode: str = "none",
        count: int = 0,
        delay_s: float = 8.0,
        latency_s: float = 0.0,
    ) -> None:
        await self.http.post(
            f"{config.PAYMENTS_URL}/admin/fault",
            json={
                "lane": lane,
                "mode": mode,
                "count": count,
                "delay_s": delay_s,
                "latency_s": latency_s,
            },
        )

    async def clear_faults(self) -> None:
        await self.set_fault("all", "none", 0, 0.0, 0.0)

    async def redeliver_lane1(self, n: int) -> None:
        try:
            await self.http.post(f"{config.LANE1_URL}/admin/redeliver", json={"n": n})
        except httpx.HTTPError:
            pass

    async def replay_approvals_lane2(self, scene: str, times: int = 3) -> None:
        """Redeliver the human's decision signals. Each replay repeats the decision the human made: replaying an
        approval onto a denied ticket would be a forged message, not a duplicate one."""
        client = await self.temporal()
        for lane, tid in self.scene_tickets.get(scene, []):
            if lane != "lane2" or tid not in self.decisions:
                continue
            handle = client.get_workflow_handle(ticket_workflow_id(tid))
            for _ in range(times):
                try:
                    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(self.decisions[tid]))
                except Exception:
                    pass

    # -- scenes ---------------------------------------------------------------------
    async def scene_walkthrough(self) -> None:
        """One approved ticket through both stacks, a step at a time: each stays on screen long enough to follow."""
        scene = "walkthrough"
        self.emit("scene", "Walkthrough: one ticket, approved, through both stacks", scene=scene)
        await self.set_fault("all", "none", latency_s=WALKTHROUGH_LATENCY_S)
        try:
            await self.hold_beat(self.start_beat(scene, "ticket"), "ticket")
            lanes = ("lane1", "lane2")
            tickets = {
                lane: self._make_ticket(scene, 0, lane, WALKTHROUGH_AMOUNT_CENTS, WALKTHROUGH_MESSAGE) for lane in lanes
            }
            await asyncio.gather(*(self.submit_ticket(lane, scene, tickets[lane]) for lane in lanes))
            self.emit("submit", "1 support ticket asking for a refund submitted to both stacks", scene=scene)
            started = self.start_beat(scene, "agent")
            await self.wait_for_proposals(scene)
            await self.wait_for_stage(scene, {"lane1_api"}, {"temporal"})  # both drawn waiting for a human
            await self.hold_beat(started, "agent")
            await self.hold_beat(self.start_beat(scene, "waiting"), "waiting")
            await self.hold_beat(self.start_beat(scene, "approve"), "approve")
            self.emit("human", "A human reviews the proposal and approves it in both stacks", scene=scene)
            await asyncio.gather(*(self.decide_ticket(lane, tickets[lane].ticket_id, True) for lane in lanes))
            # Both calls start within a moment and stay in flight for the 2.5 s of latency: show the box now, not after
            # the diagram has caught up, or the refund may already be booked by the time it appears.
            await asyncio.sleep(0.6)
            # The last step has no dwell: it shows while the refund lands, and the scene ends when the ledger has it.
            self.start_beat(scene, "refund")
            await self.wait_for_stage(scene, {"done"}, {"done"}, timeout=30.0)
            await asyncio.sleep(WALKTHROUGH_END_HOLD_S)  # let the finished chat sit before the scene is marked done
        finally:
            self.beat = None
            await self.clear_faults()

    async def scene_intro(self) -> None:
        self.emit(
            "scene",
            "Happy path: both stacks handle 7 tickets with nothing going wrong",
            scene="intro",
        )
        await self.submit_cohort("intro", 5)
        await self.wait_for_proposals("intro")
        await self.approve_scene("intro", then=" in both stacks")

    async def scene_worker_crash(self) -> None:
        """One kill, two kinds of ticket. Some refunds are already in flight at payments (it booked them and went
        quiet) and the rest still wait for a human. The agent workers die, as in a crash or a deploy, and come back;
        only then does the human review the waiting tickets."""
        scene = "worker_crash"
        self.emit("scene", "Some refunds are in flight, others wait for a human. The agent workers die.", scene=scene)
        await self.set_fault("all", "commit_then_stall", count=WORKER_CRASH_IN_FLIGHT, delay_s=9.0)
        await self.submit_cohort(scene, WORKER_CRASH_COHORT)
        await self.wait_for_proposals(scene)
        # The human reaches the first few tickets before the fault: their refunds are the ones in flight.
        await self.approve_scene(scene, who="A human", only=lambda tid: _ticket_index(tid) < WORKER_CRASH_IN_FLIGHT)
        await asyncio.sleep(1.6)
        self.fault(scene, "Fault: kill -9 on both agent workers", AGENT_WORKERS, "kill")
        self.procs.kill("lane1_worker", restart_after=3.0)
        self.procs.kill("support_worker", restart_after=3.0)
        await asyncio.sleep(6)
        # The rest of the cohort waited through the restart. Now the human gets to them.
        await self.approve_scene(
            scene,
            who="After the restart, the human",
            only=lambda tid: _ticket_index(tid) >= WORKER_CRASH_IN_FLIGHT,
            policy_note=False,
        )
        await asyncio.sleep(20)
        await self.clear_faults()

    async def scene_double_delivery(self) -> None:
        self.emit("scene", "The broker delivers the same work twice", scene="double_delivery")
        await self.set_fault("all", "none", latency_s=2.5)
        await self.submit_cohort("double_delivery", 5)
        await self.wait_for_proposals("double_delivery")
        await self.approve_scene("double_delivery")
        await asyncio.sleep(1.0)
        self.fault(
            "double_delivery",
            "Fault: every message delivered twice",
            ["lane1_api", "temporal"],
            "duplicate",
        )
        await self.redeliver_lane1(5)
        await self.replay_approvals_lane2("double_delivery", 3)
        await asyncio.sleep(14)
        await self.clear_faults()

    async def scene_payments_timeout(self) -> None:
        self.emit(
            "scene",
            "Payments commits the refund, then the response never arrives",
            scene="payments_timeout",
        )
        await self.set_fault("all", "commit_then_stall", count=5, delay_s=9.0)
        await self.submit_cohort("payments_timeout", 5)
        await self.wait_for_proposals("payments_timeout")
        await self.approve_scene("payments_timeout")
        self.fault("payments_timeout", "Fault: payments goes quiet after booking", ["payments"], "stall")
        await asyncio.sleep(20)
        await self.clear_faults()

    async def scene_nexus_kill(self) -> None:
        """The Nexus gauntlet: while the refunds are in flight, payments goes quiet after booking, then the support
        worker, the payments worker and the Temporal server itself are killed. Each fault is timed to land on
        refunds still open, and records how many it hit."""
        scene = "nexus_kill"
        self.emit(
            "scene",
            "Temporal only: four failures while the refunds are in flight over Nexus",
            scene=scene,
        )
        await self.set_fault(
            "lane2", "commit_then_stall", count=5, delay_s=GAUNTLET_STALL_S, latency_s=GAUNTLET_LATENCY_S
        )
        await self.submit_cohort(scene, 5, lanes=("lane2",))
        await self.wait_for_proposals(scene)
        await self.approve_scene(scene, then="; each approval becomes a Nexus operation to payments")
        self.fault(scene, "Fault: payments goes quiet after booking", ["payments"], "stall")
        # Filled in from the ledger as the bookings land: see _stall_window.
        self.scene_runs[scene]["faults"].append(
            {
                "key": "payments",
                "label": "payments quiet after booking",
                "effect": "stall",
                "start": None,
                "end": None,
                "hit": 0,
            }
        )
        await asyncio.sleep(3.0)
        self.kill_window(scene, "support_worker", "support worker", GAUNTLET_DOWN_S["support_worker"])
        # Payments' second try is a replay of a booked refund; kill its worker while that call is under way.
        await self._wait_for_attempt(2, timeout=15.0)
        await asyncio.sleep(0.5)
        self.kill_window(scene, "payments_worker", "payments worker", GAUNTLET_DOWN_S["payments_worker"])
        await asyncio.sleep(3.0)
        if self.procs.owns_temporal:
            self.kill_window(scene, "temporal", "Temporal server", GAUNTLET_DOWN_S["temporal"])
        else:
            self.emit(
                "note", "the Temporal server is not the show's to kill (it was already running): skipped", scene=scene
            )
        await self._wait_for_rows_closed(timeout=40.0)
        await self.clear_faults()

    async def _wait_for_attempt(self, n: int, timeout: float) -> None:
        """Until every Nexus row of the scene shows payments' attempt n (or the timeout)."""
        end = time.time() + timeout
        while time.time() < end:
            rows = list(self.nexus_seen.values())
            if rows and all(any(a["n"] >= n for a in r.get("attempts", [])) for r in rows):
                return
            await asyncio.sleep(0.25)

    async def _wait_for_rows_closed(self, timeout: float) -> None:
        end = time.time() + timeout
        while time.time() < end:
            rows = list(self.nexus_seen.values())
            if rows and not any(r.get("live") for r in rows):
                return
            await asyncio.sleep(0.5)

    async def scene_free_roam(self) -> None:
        self.emit("scene", "Free roam: faults picked at random", scene="free_roam")
        actions: list[Callable[[str], Awaitable[None]]] = [
            self._roam_kill_agents,
            self._roam_stall,
            self._roam_redeliver,
            self._roam_kill_payments_worker,
        ]
        for round_no in range(4):
            scene = f"free_roam_{round_no}"
            await self.submit_cohort(scene, 3)
            await self.wait_for_proposals(scene)
            await self.approve_scene(scene)
            await asyncio.sleep(self.rng.uniform(0.5, 1.5))
            await self.rng.choice(actions)(scene)
            await asyncio.sleep(self.rng.uniform(6, 10))
        await self.clear_faults()

    async def _roam_kill_agents(self, scene: str) -> None:
        self.fault(scene, "Fault: kill -9 on the agent workers", AGENT_WORKERS, "kill")
        self.procs.kill("lane1_worker", 3.0)
        self.procs.kill("support_worker", 3.0)

    async def _roam_stall(self, scene: str) -> None:
        self.fault(scene, "Fault: payments goes quiet after committing", ["payments"], "stall")
        await self.set_fault("all", "commit_then_stall", count=3, delay_s=8.0)

    async def _roam_redeliver(self, scene: str) -> None:
        self.fault(scene, "Fault: the same work is delivered twice", ["lane1_api", "temporal"], "duplicate")
        await self.redeliver_lane1(3)
        await self.replay_approvals_lane2(scene, 2)

    async def _roam_kill_payments_worker(self, scene: str) -> None:
        self.fault(scene, "Fault: kill -9 on the payments worker", ["payments_worker"], "kill")
        self.procs.kill("payments_worker", 6.0)

    async def settle(self, scene_id: str) -> None:
        """Hold the scene open until each ticket has landed: the ledger has decided it and its stack has stopped
        moving it. Settled must hold for SCENE_QUIET_S, so a redelivered job still in the queue gets its chance."""
        pairs = [
            p for key, ps in self.scene_tickets.items() if key == scene_id or key.startswith(f"{scene_id}_") for p in ps
        ]
        end = time.time() + SCENE_SETTLE_MAX_S
        quiet_since: float | None = None
        while time.time() < end:
            board = await asyncio.to_thread(audit.compute_all)
            ledger = {lane: board[lane]["tickets"] for lane in board}
            if _unsettled(pairs, ledger, self.flow):
                quiet_since = None
            elif quiet_since is None:
                quiet_since = time.time()
            elif time.time() - quiet_since >= SCENE_QUIET_S:
                return
            await asyncio.sleep(0.5)
        self.emit("note", f"some tickets were still moving {SCENE_SETTLE_MAX_S:.0f}s after the scene", scene=scene_id)

    # -- scene runner -----------------------------------------------------------------
    async def run_scene(self, scene_id: str) -> bool:
        if self.running:
            return False
        fn = getattr(self, f"scene_{scene_id}", None)
        if fn is None:
            return False
        self.running = True
        self.current = scene_id
        self.run_no += 1
        for key in [k for k in self.scene_tickets if k == scene_id or k.startswith(f"{scene_id}_")]:
            del self.scene_tickets[key]
        self.nexus_seen = {}  # a new dict, so a refresh still in flight writes to the old one
        title = next((s.title for s in SCENES if s.id == scene_id), scene_id)
        run = {"started_at": time.time(), "finished_at": None, "ok": None, "kills": {}, "faults": []}
        self.scene_runs[scene_id] = run

        async def go() -> None:
            ok = True
            error = None
            try:
                await fn()
                await self.settle(scene_id)
            except Exception as exc:
                ok = False
                error = f"{exc!r}"[:120]  # shown on the scene's status line
                self.emit("error", f"scene {scene_id} failed: {exc!r}", scene=scene_id)
            finally:
                self.running = False
                run.update(finished_at=time.time(), ok=ok, error=error)
                self.emit("scene_done", f"{title}: finished", scene=scene_id, ok=ok)

        self._task = asyncio.create_task(go())
        return True

    async def reset(self) -> None:
        if self.running and self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)  # let its finally block run before we wipe state
            self.running = False
        await self.clear_faults()
        for url in (
            f"{config.PAYMENTS_URL}/admin/reset",
            f"{config.LANE1_URL}/admin/reset",
        ):
            try:
                await self.http.post(url)
            except httpx.HTTPError:
                pass
        audit.reset()
        self.run_id = uuid.uuid4().hex[:4]
        self.rng = random.Random(self.seed)
        self.scene_tickets.clear()
        self.plan.clear()
        self.decisions.clear()
        self.lane2_outcomes.clear()
        self.payments_calls = {}
        self.payments_calls_all = {}
        self.payments_calls_by_ticket = {}
        self.lane2_status.clear()
        self.lane1_view_all = {}
        self.lane2_view_all = {}
        self.booked_at = {}
        self.nexus_seen = {}
        self.flow = {"lane1": [], "lane2": []}
        self.beat = None
        self.scene_runs = {}  # a cancelled scene's finally block then updates a run nobody shows
        self.events.clear()
        self.current = None
        self.emit("reset", "Scoreboard reset")

    # -- views -------------------------------------------------------------------------
    async def refresh_views(self) -> None:
        """Background: what each lane believes, and the live Nexus operations (Lane 2)."""
        pairs = self._current_pairs()
        try:
            r = await self.http.get(f"{config.LANE1_URL}/tickets")
            counts_all: dict[str, int] = {}
            ours = {tid for lane, tid in pairs if lane == "lane1"}
            flow1 = []
            for t in r.json():
                if not _is_demo(t["ticket_id"]):
                    counts_all[t["status"]] = counts_all.get(t["status"], 0) + 1
                if t["ticket_id"] in ours:
                    at, state = LANE1_STAGES.get(t["status"], ("lane1_api", t["status"]))
                    if t["status"] == "denied" and t.get("detail"):
                        state = f"{state}: {t['detail']}"
                    flow1.append({"ticket": t["ticket_id"], "at": at, "state": state})
            self.lane1_view_all = counts_all
            self.flow["lane1"] = flow1
        except Exception:
            pass
        try:
            r = await self.http.get(f"{config.PAYMENTS_URL}/admin/fault")
            self.faults = r.json()
            r = await self.http.get(f"{config.PAYMENTS_URL}/admin/calls")
            self.payments_calls_by_ticket = r.json()
            self.payments_calls = _scene_calls(self.payments_calls_by_ticket, pairs)
            self.payments_calls_all = _scene_calls(
                self.payments_calls_by_ticket,
                [
                    (lane, tid)
                    for lane, per in self.payments_calls_by_ticket.items()
                    for tid in per
                    if not _is_demo(tid)
                ],
            )
            r = await self.http.get(f"{config.PAYMENTS_URL}/refunds", params={"lane": "lane2"})
            self.booked_at = {row["ticket_id"]: row["created_at"] for row in r.json()}
            run = self.scene_runs.get(self.current) if self.current else None
            for w in run["faults"] if run else []:
                if w["effect"] == "stall":
                    lane2 = [tid for lane, tid in pairs if lane == "lane2"]
                    w.update(_stall_window(self.booked_at, lane2, GAUNTLET_STALL_S, self.faults.get("lane2"), 5))
        except Exception:
            pass
        try:
            client = await self.temporal()
        except Exception:
            return
        seen = self.nexus_seen  # run_scene swaps in a new dict; never write a stale scene into it
        lane2 = [tid for lane, tid in pairs if lane == "lane2"]
        flow2 = []
        for tid in lane2:
            # One ticket's failed describe must not freeze the whole view (the payments worker may be dead).
            desc = await self._describe(client, ticket_workflow_id(tid))
            if desc is None:
                continue
            status = desc.status.name if desc.status else "UNKNOWN"
            if not _is_demo(tid):
                self.lane2_status[tid] = status
            ops = desc.raw_description.pending_nexus_operations
            if status == "COMPLETED" and tid not in self.lane2_outcomes:
                # describe() can't tell a refund from a denial. The result can, and reading it needs no worker.
                outcome = await self._outcome(client, ticket_workflow_id(tid))
                if outcome is not None:
                    self.lane2_outcomes[tid] = outcome
            stage = _lane2_stage(
                status,
                desc.raw_description.pending_activities,
                ops,
                self.decisions.get(tid),
                self.lane2_outcomes.get(tid),
            )
            flow2.append({"ticket": tid, **stage})
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
                    "state": _enum_name(op),
                    "attempts": _merge_attempts(prev.get("attempts", []), pending, time.time()),
                    "last_failure": failure,
                    "caller_saw_failure": bool(failure) or prev.get("caller_saw_failure", False),
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
                attempts = _merge_attempts(row.get("attempts", []), pending, now)
                if handler.get("status") not in (None, "RUNNING"):
                    attempts = _finish_attempts(attempts, await self._final_attempt(tid), now)
                row.update(live=False, state=final_state, handler=handler, attempts=attempts)
            elif row is not None and row.get("attempts") and any(a["outcome"] == "running" for a in row["attempts"]):
                # Closed earlier, but the refund workflow hadn't finished then: try its history again.
                if (await self._handler_view(tid)).get("status") not in (None, "RUNNING"):
                    row["attempts"] = _finish_attempts(row["attempts"], await self._final_attempt(tid), time.time())
            if tid in seen:
                seen[tid]["ledger"] = _ticket_ledger(self.payments_calls_by_ticket, self.booked_at, "lane2", tid)
        if seen is self.nexus_seen:
            self.lane2_view_all = dict(Counter(self.lane2_status.values()))
            self.flow["lane2"] = flow2

    def _current_pairs(self) -> list[tuple[str, str]]:
        """(lane, ticket) for the scene on screen. Free roam files its rounds under free_roam_0..3."""
        cur = self.current or ""
        return [p for key, ps in self.scene_tickets.items() if key == cur or key.startswith(f"{cur}_") for p in ps]

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

    def snapshot(self) -> dict:
        # The scoreboard leaves out the walkthrough (a demonstration) and the Nexus scene (a page of its own, Temporal
        # only): the Lane 1 vs Lane 2 scenes are what add up. They are still scored on their own (`demo_audit`) so the
        # headless run and those pages can read them.
        board = audit.compute_all(exclude_scenes=DEMO_SCENES)
        demo = audit.compute_all(only_scenes=DEMO_SCENES)
        return {
            "now": time.time(),
            "running": self.running,
            "current": self.current,
            "scene_runs": self.scene_runs,
            "audit": board,
            "demo_audit": demo,
            "processes": self.procs.status(),
            "events": self.events[-60:],
            "nexus": list(self.nexus_seen.values()),
            "lane1_view_all": self.lane1_view_all,
            "lane2_view_all": self.lane2_view_all,
            "faults": self.faults,
            "payments_calls": self.payments_calls,
            "payments_calls_all": self.payments_calls_all,
            "flow": self.flow,
            "beat": self.beat,
            "topology": TOPOLOGY,
        }

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
                        "scheduled_at": _ts(act.scheduled_time),
                        "started_at": _ts(act.last_started_time),
                        # The server's current_retry_interval isn't usable (garbage or unset), so the backoff
                        # before this attempt comes from the refund workflow's own retry policy.
                        "retry_interval": _backoff_before(act.attempt),
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
                        "started_at": _ts(e.event_time),
                        "ended_at": None,
                        "ok": False,
                        "failure": "",
                    }
                elif final is not None and kind == "activity_task_completed_event_attributes":
                    final.update(ended_at=_ts(e.event_time), ok=True)
                elif final is not None and kind in (
                    "activity_task_failed_event_attributes",
                    "activity_task_timed_out_event_attributes",
                ):
                    attrs = getattr(e, kind)
                    final.update(ended_at=_ts(e.event_time), failure=attrs.failure.message[:120])
            return final if final and final["ended_at"] else None
        except Exception:
            return None


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


# Where a stack leaves a ticket it has given up on: Lane 1's job status, or a closed Lane 2 workflow (_lane2_stage).
STOPPED_STATES = {"failed", "terminated", "canceled", "timed out", "continued as new"}


def _lane2_stage(
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
        if _enum_name(ops[0]) == "STARTED":
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


def _unsettled(
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


def _ticket_index(ticket_id: str) -> int:
    """The ticket's position in its cohort: ids end in `...-<index>-<lane>` (see Engine._make_ticket)."""
    return int(ticket_id.rsplit("-", 2)[1])


def _is_demo(ticket_id: str) -> bool:
    """A walkthrough ticket, from any run of it: ids read `<run>-<scene>-r<n>-<i>-<lane>` (Engine._make_ticket)."""
    return any(f"-{scene}-r" in ticket_id for scene in DEMO_SCENES)


def _scene_calls(calls: dict, pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
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


def _enum_name(op) -> str:
    try:
        from temporalio.api.enums.v1 import PendingNexusOperationState  # type: ignore

        return PendingNexusOperationState.Name(op.state).replace("PENDING_NEXUS_OPERATION_STATE_", "")
    except Exception:
        return str(op.state)


def _merge_attempts(prev: list[dict], pending: dict | None, now: float) -> list[dict]:
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


def _finish_attempts(prev: list[dict], final: dict | None, now: float) -> list[dict]:
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


def _backoff_before(attempt: int) -> float:
    """The refund retry policy's wait before `attempt` (attempt 2 waits the initial interval)."""
    if attempt <= 1:
        return 0.0
    initial = REFUND_RETRY.initial_interval.total_seconds()
    wait = initial * REFUND_RETRY.backoff_coefficient ** (attempt - 2)
    cap = REFUND_RETRY.maximum_interval.total_seconds() if REFUND_RETRY.maximum_interval else wait
    return min(wait, cap)


def _stall_window(booked_at: dict, tickets: list[str], delay_s: float, fault: dict | None, count: int) -> dict:
    """The payments-quiet window, from the ledger: the first stalled booking to the last one's held reply.
    `hit` is how many bookings the stall actually held (the payments fault's count minus what it has left)."""
    times = sorted(booked_at[t] for t in tickets if t in booked_at)
    left = fault.get("remaining", count) if fault and fault.get("mode") == "commit_then_stall" else 0
    hit = min(count - left, len(times)) if fault and fault.get("mode") == "commit_then_stall" else len(times)
    if not times:
        return {"start": None, "end": None, "hit": 0}
    return {"start": times[0], "end": times[min(hit, len(times)) - 1] + delay_s if hit else times[0], "hit": hit}


def _ticket_ledger(calls: dict, booked_at: dict, lane: str, ticket_id: str) -> dict:
    """One ticket as payments saw it: calls, calls answered from the ledger, and when the money was booked."""
    c = calls.get(lane, {}).get(ticket_id) or {"calls": 0, "replays": 0}
    return {"calls": c["calls"], "replays": c["replays"], "booked_at": booked_at.get(ticket_id)}


def _ts(stamp) -> float | None:
    """A protobuf Timestamp as epoch seconds, or None if unset."""
    if stamp is None or not (stamp.seconds or stamp.nanos):
        return None
    return stamp.seconds + stamp.nanos / 1e9
