"""The show engine: submits tickets to both lanes, plays the human approver, and injects the faults.

Every scene runs the same story against Lane 1 (job queue) and Lane 2 (Temporal + Nexus) at the same time, so the audience watches
two systems take identical hits. Scoring comes from the payments ledger (raccoon.audit), never from
what either lane reports about itself.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from temporalio.client import Client

from raccoon import audit, config
from raccoon.lane2.client import connect
from raccoon.lane2.contract import NEXUS_ENDPOINT, PaymentsService
from raccoon.lane2.payments_side import RefundWorkflow, refund_workflow_id
from raccoon.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from raccoon.models import ApprovalDecision, Ticket
from raccoon.show.procs import ProcessManager

SETTLE_S = 20.0

# How the show names each lane on screen; the code, ledger and ticket IDs keep lane1/lane2.
LANE_NAMES = {"lane1": "the job queue", "lane2": "Temporal + Nexus"}

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
    SceneInfo("intro", "Happy path"),
    SceneInfo("tip_over", "The agent workers crash"),
    SceneInfo("double_delivery", "Double-delivered mail"),
    SceneInfo("deploy_wait", "Deploy during the approval wait"),
    SceneInfo("payments_timeout", "Payments commits, then goes quiet"),
    SceneInfo("nexus_kill", "Nexus: the payments worker dies mid-refund"),
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
        self.temporal_ui: str | None = None
        self._ui_probed_at = 0.0
        self.lane1_view: dict[str, int] = {}
        self.lane2_view: dict[str, int] = {}
        self.faults: dict = {}
        self._task: asyncio.Task | None = None
        self.procs.emit = self.emit_from_procs

    # -- plumbing ------------------------------------------------------------
    def emit(self, kind: str, msg: str, **extra) -> None:
        self.events.append({"ts": time.time(), "kind": kind, "msg": msg, **extra})
        del self.events[:-200]

    def emit_from_procs(self, kind: str, msg: str, **extra) -> None:
        # Kills count against the scene that made them, so a step never shows kills from an earlier scene.
        if kind == "kill" and self.running and self.current in self.scene_runs:
            kills = self.scene_runs[self.current]["kills"]
            kills[extra["proc"]] = kills.get(extra["proc"], 0) + 1
        self.emit(kind, msg, **extra)

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=5.0)
        return self._http

    async def temporal(self) -> Client:
        if self._temporal is None:
            self._temporal = await connect(config.SUPPORT_NAMESPACE)
        return self._temporal

    async def payments_temporal(self) -> Client:
        if self._payments_temporal is None:
            self._payments_temporal = await connect(config.PAYMENTS_NAMESPACE)
        return self._payments_temporal

    # -- tickets and approvals --------------------------------------------------
    def _make_ticket(self, scene: str, i: int, lane: str, amount: int, message: str) -> Ticket:
        tid = f"{self.run_id}-{scene}-r{self.run_no}-{i:02d}-{lane}"
        return Ticket(tid, f"cust-{i:02d}", f"ord-{self.run_id}-r{self.run_no}-{i:02d}", amount, message)

    async def submit_ticket(self, lane: str, scene: str, ticket: Ticket) -> None:
        audit.record_ticket(lane, ticket.ticket_id, scene, ticket.amount_cents)
        self.scene_tickets.setdefault(scene, []).append((lane, ticket.ticket_id))
        if lane == "lane1":
            body = {
                "ticket_id": ticket.ticket_id,
                "customer": ticket.customer,
                "order_id": ticket.order_id,
                "amount_cents": ticket.amount_cents,
                "message": ticket.message,
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

    async def submit_cohort(self, scene: str, n: int, lanes=("lane1", "lane2")) -> list[tuple[int, int, str]]:
        specs = [(i, self.rng.randrange(1500, 9500, 100), self.rng.choice(MESSAGES)) for i in range(n)]
        jobs = []
        for lane in lanes:
            for i, amount, msg in specs:
                jobs.append(self.submit_ticket(lane, scene, self._make_ticket(scene, i, lane, amount, msg)))
        await asyncio.gather(*jobs)
        self.emit(
            "submit",
            f"{n} refund tickets submitted to {' and '.join(LANE_NAMES[lane] for lane in lanes)}",
            scene=scene,
        )
        return specs

    async def approve_ticket(self, lane: str, ticket_id: str) -> None:
        """A human clicks Approve. The decision is recorded the moment it is made, delivered or not."""
        audit.record_approval(lane, ticket_id, delivered=False)
        if lane == "lane1":
            for _ in range(80):
                try:
                    r = await self.http.post(f"{config.LANE1_URL}/tickets/{ticket_id}/approve")
                    if r.status_code == 200:
                        audit.record_approval(lane, ticket_id, delivered=True)
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)  # 409 = no proposal yet, or the API is down: click again
        else:
            for _ in range(80):
                try:
                    client = await self.temporal()
                    handle = client.get_workflow_handle(ticket_workflow_id(ticket_id))
                    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
                    audit.record_approval(lane, ticket_id, delivered=True)
                    return
                except Exception:
                    await asyncio.sleep(0.5)

    async def approve_scene(self, scene: str, stagger: float = 0.05) -> None:
        pairs = list(self.scene_tickets.get(scene, []))
        tasks = []
        for lane, tid in pairs:
            tasks.append(asyncio.create_task(self.approve_ticket(lane, tid)))
            await asyncio.sleep(stagger)
        await asyncio.gather(*tasks)

    async def wait_for_proposals(self, scene: str, timeout: float = 45.0) -> None:
        """Wait until every ticket in the scene has an agent proposal waiting for a human."""
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
                    ready += l1.get(tid) == "awaiting_approval"
                else:
                    try:
                        st = await client.get_workflow_handle(ticket_workflow_id(tid)).query(
                            SupportTicketWorkflow.status
                        )
                        ready += st["state"] == "awaiting_approval"
                    except Exception:
                        pass
            if ready >= len(pairs):
                return
            await asyncio.sleep(0.5)
        self.emit("note", "timed out waiting for every proposal", scene=scene)

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
        client = await self.temporal()
        for lane, tid in self.scene_tickets.get(scene, []):
            if lane != "lane2":
                continue
            handle = client.get_workflow_handle(ticket_workflow_id(tid))
            for _ in range(times):
                try:
                    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
                except Exception:
                    pass

    # -- scenes ---------------------------------------------------------------------
    async def scene_intro(self) -> None:
        self.emit(
            "scene",
            "Happy path: both stacks handle 5 refunds with nothing going wrong",
            scene="intro",
        )
        await self.submit_cohort("intro", 5)
        await self.wait_for_proposals("intro")
        self.emit("human", "A human approves all 5 in both stacks", scene="intro")
        await self.approve_scene("intro")

    async def scene_tip_over(self) -> None:
        self.emit(
            "scene",
            "The agent workers will be killed right after payments commits",
            scene="tip_over",
        )
        await self.set_fault("all", "commit_then_stall", count=6, delay_s=9.0)
        await self.submit_cohort("tip_over", 6)
        await self.wait_for_proposals("tip_over")
        self.emit("human", "A human approves all 6", scene="tip_over")
        await self.approve_scene("tip_over")
        await asyncio.sleep(1.6)
        self.emit(
            "fault",
            "Fault: kill -9 on both agent workers",
            scene="tip_over",
        )
        self.procs.kill("lane1_worker", restart_after=3.0)
        self.procs.kill("support_worker", restart_after=3.0)
        await asyncio.sleep(25)
        await self.clear_faults()

    async def scene_double_delivery(self) -> None:
        self.emit("scene", "The broker delivers the same work twice", scene="double_delivery")
        await self.set_fault("all", "none", latency_s=2.5)
        await self.submit_cohort("double_delivery", 5)
        await self.wait_for_proposals("double_delivery")
        self.emit("human", "A human approves all 5", scene="double_delivery")
        await self.approve_scene("double_delivery")
        await asyncio.sleep(1.0)
        self.emit(
            "fault",
            "Fault: the same work is delivered twice (queue: redelivery, Temporal: replayed approval signals)",
            scene="double_delivery",
        )
        await self.redeliver_lane1(5)
        await self.replay_approvals_lane2("double_delivery", 3)
        await asyncio.sleep(14)
        await self.clear_faults()

    async def scene_deploy_wait(self) -> None:
        self.emit(
            "scene",
            "Tickets are waiting for a human. A deploy restarts the workers.",
            scene="deploy_wait",
        )
        await self.submit_cohort("deploy_wait", 5)
        await self.wait_for_proposals("deploy_wait")
        self.emit(
            "fault",
            "Fault: both agent workers restart while approvals are pending",
            scene="deploy_wait",
        )
        self.procs.kill("lane1_worker", restart_after=3.0)
        self.procs.kill("support_worker", restart_after=3.0)
        await asyncio.sleep(6)
        self.emit("human", "The human finally clicks Approve on all 5", scene="deploy_wait")
        await self.approve_scene("deploy_wait")
        await asyncio.sleep(10)

    async def scene_payments_timeout(self) -> None:
        self.emit(
            "scene",
            "Payments commits the refund, then the response never arrives",
            scene="payments_timeout",
        )
        await self.set_fault("all", "commit_then_stall", count=5, delay_s=9.0)
        await self.submit_cohort("payments_timeout", 5)
        await self.wait_for_proposals("payments_timeout")
        self.emit("human", "A human approves all 5", scene="payments_timeout")
        await self.approve_scene("payments_timeout")
        self.emit(
            "fault",
            "Fault: payments holds its response after the commit",
            scene="payments_timeout",
        )
        await asyncio.sleep(20)
        await self.clear_faults()

    async def scene_nexus_kill(self) -> None:
        self.emit(
            "scene",
            "Temporal only: the payments team's worker dies in the middle of Nexus operations",
            scene="nexus_kill",
        )
        await self.set_fault("lane2", "none", latency_s=2.0)
        await self.submit_cohort("nexus_kill", 5, lanes=("lane2",))
        await self.wait_for_proposals("nexus_kill")
        self.emit(
            "human",
            "A human approves all 5; each becomes a Nexus operation to payments",
            scene="nexus_kill",
        )
        await self.approve_scene("nexus_kill")
        await asyncio.sleep(1.2)
        self.emit(
            "fault",
            "Fault: the payments team's worker is down for 10 seconds; support keeps waiting, the retries happen inside payments",
            scene="nexus_kill",
        )
        self.procs.kill("payments_worker", restart_after=10.0)
        await asyncio.sleep(22)
        await self.clear_faults()

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
        self.emit("fault", "Fault: kill -9 on the agent workers", scene=scene)
        self.procs.kill("lane1_worker", 3.0)
        self.procs.kill("support_worker", 3.0)

    async def _roam_stall(self, scene: str) -> None:
        self.emit("fault", "Fault: payments goes quiet after committing", scene=scene)
        await self.set_fault("all", "commit_then_stall", count=3, delay_s=8.0)

    async def _roam_redeliver(self, scene: str) -> None:
        self.emit("fault", "Fault: the same work is delivered twice", scene=scene)
        await self.redeliver_lane1(3)
        await self.replay_approvals_lane2(scene, 2)

    async def _roam_kill_payments_worker(self, scene: str) -> None:
        self.emit("fault", "Fault: kill -9 on the payments worker", scene=scene)
        self.procs.kill("payments_worker", 6.0)

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
        run = {"started_at": time.time(), "finished_at": None, "ok": None, "kills": {}}
        self.scene_runs[scene_id] = run

        async def go() -> None:
            ok = True
            try:
                await fn()
            except Exception as exc:
                ok = False
                self.emit("error", f"scene {scene_id} failed: {exc!r}", scene=scene_id)
            finally:
                self.running = False
                run.update(finished_at=time.time(), ok=ok)
                self.emit("scene_done", f"{title}: finished", scene=scene_id, ok=ok)

        self._task = asyncio.create_task(go())
        return True

    async def reset(self) -> None:
        if self.running and self._task:
            self._task.cancel()
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
        self.nexus_seen = {}
        self.scene_runs = {}  # a cancelled scene's finally block then updates a run nobody shows
        self.events.clear()
        self.current = None
        self.emit("reset", "Scoreboard reset")

    # -- views -------------------------------------------------------------------------
    async def refresh_views(self) -> None:
        """Background: what each lane believes, and the live Nexus operations (Lane 2)."""
        try:
            r = await self.http.get(f"{config.LANE1_URL}/tickets")
            counts: dict[str, int] = {}
            for t in r.json():
                counts[t["status"]] = counts.get(t["status"], 0) + 1
            self.lane1_view = counts
        except Exception:
            pass
        try:
            r = await self.http.get(f"{config.PAYMENTS_URL}/admin/fault")
            self.faults = r.json()
        except Exception:
            pass
        try:
            client = await self.temporal()
        except Exception:
            return
        await self._probe_temporal_ui()
        seen = self.nexus_seen  # run_scene swaps in a new dict; never write a stale scene into it
        states: dict[str, int] = {}
        lane2 = [tid for lane, tid in self.scene_tickets.get(self.current or "", []) if lane == "lane2"]
        for tid in lane2:
            # One ticket's failed describe must not freeze the whole view (the payments worker may be dead).
            desc = await self._describe(client, ticket_workflow_id(tid))
            if desc is None:
                continue
            status = desc.status.name if desc.status else "UNKNOWN"
            states[status] = states.get(status, 0) + 1
            ops = desc.raw_description.pending_nexus_operations
            row = seen.get(tid)
            if ops:
                op = ops[0]
                failure = (
                    op.last_attempt_failure.message[:120]
                    if op.last_attempt_failure and op.last_attempt_failure.message
                    else ""
                )
                handler = await self._handler_view(tid)
                prev = row or {}
                handler["peak_activity_attempt"] = max(
                    handler.get("activity_attempt", 0),
                    prev.get("handler", {}).get("peak_activity_attempt", 0),
                )
                seen[tid] = {
                    "ticket": tid,
                    "live": True,
                    "caller_workflow_id": ticket_workflow_id(tid),
                    "caller_run_id": desc.run_id,
                    "caller_namespace": config.SUPPORT_NAMESPACE,
                    "handler": handler,
                    "endpoint": op.endpoint,
                    "service": op.service,
                    "operation": op.operation,
                    "state": _enum_name(op),
                    "attempt": op.attempt,
                    "peak_attempt": max(op.attempt, prev.get("peak_attempt", 0)),
                    "last_failure": failure,
                    "caller_saw_failure": bool(failure) or prev.get("caller_saw_failure", False),
                }
            elif row is not None and row["live"]:
                # The operation closed since the last refresh: keep the row, with its final state.
                handler = await self._handler_view(tid) or dict(row["handler"])
                handler["peak_activity_attempt"] = row["handler"].get("peak_activity_attempt", 0)
                handler["activity_attempt"] = 0
                closed_badly = status in ("FAILED", "TIMED_OUT", "TERMINATED", "CANCELED")
                row.update(live=False, state="FAILED" if closed_badly else "COMPLETED", handler=handler)
        if seen is self.nexus_seen:
            self.lane2_view = states

    @staticmethod
    async def _describe(client: Client, workflow_id: str):
        try:
            return await client.get_workflow_handle(workflow_id).describe()
        except Exception:
            return None

    async def _probe_temporal_ui(self) -> None:
        """Is the Temporal Web UI up? Links to it are shown only if it answers. Re-checked every 10s."""
        if time.time() - self._ui_probed_at < 10:
            return
        self._ui_probed_at = time.time()
        try:
            r = await self.http.get(config.TEMPORAL_UI_URL, timeout=1.0)
            self.temporal_ui = config.TEMPORAL_UI_URL if r.status_code < 500 else None
        except httpx.HTTPError:
            self.temporal_ui = None

    def snapshot(self) -> dict:
        board = audit.compute_all(SETTLE_S)
        return {
            "now": time.time(),
            "running": self.running,
            "current": self.current,
            "scene_runs": self.scene_runs,
            "scenes": [{"id": s.id, "title": s.title} for s in SCENES],
            "audit": board,
            "processes": self.procs.status(),
            "events": self.events[-60:],
            "nexus": list(self.nexus_seen.values()),
            "lane1_view": self.lane1_view,
            "lane2_view": self.lane2_view,
            "faults": self.faults,
            "temporal_ui": self.temporal_ui,
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
                "workflow_id": refund_workflow_id(ticket_id),
                "run_id": desc.run_id,
                "namespace": config.PAYMENTS_NAMESPACE,
                "status": desc.status.name if desc.status else "UNKNOWN",
                "activity_attempt": act.attempt if act else 0,
                "activity_failure": (
                    act.last_failure.message[:120] if act and act.last_failure and act.last_failure.message else ""
                ),
            }
        except Exception:
            return {}


def _enum_name(op) -> str:
    try:
        from temporalio.api.enums.v1 import PendingNexusOperationState  # type: ignore

        return PendingNexusOperationState.Name(op.state).replace("PENDING_NEXUS_OPERATION_STATE_", "")
    except Exception:
        return str(op.state)
