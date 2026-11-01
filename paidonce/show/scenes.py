"""The scenes, and the fault primitives they use: what happens on stage, in what order.

Mixed into `Engine` (engine.py), whose state it uses: `emit`, `procs`, `scene_runs`, `scene_tickets`, `nexus_seen`,
`decisions`, `beat`, `rng`, and the `http` / `temporal()` clients. `SCENES` (catalog.py) lists them; each has a
`scene_<id>` method here, and a test keeps the two in step.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from paidonce import config
from paidonce.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from paidonce.models import ApprovalDecision
from paidonce.show.catalog import (
    AGENT_WORKERS,
    GAUNTLET_DOWN_S,
    GAUNTLET_LATENCY_S,
    GAUNTLET_REFUNDS,
    GAUNTLET_STALL_S,
    WALKTHROUGH_AMOUNT_CENTS,
    WALKTHROUGH_DWELL_S,
    WALKTHROUGH_END_HOLD_S,
    WALKTHROUGH_LATENCY_S,
    WALKTHROUGH_MESSAGE,
    WORKER_CRASH_COHORT,
    WORKER_CRASH_IN_FLIGHT,
    ticket_index,
)


class SceneMixin:
    def fault(self, scene: str, msg: str, target: list[str], effect: str) -> None:
        """A fault, with where it lands: diagram node ids (process names, or "temporal"), and its effect
        (kill, duplicate or stall)."""
        self.emit("fault", msg, scene=scene, target=target, effect=effect)

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

    def start_beat(self, scene: str, beat: str) -> float:
        """Put a walkthrough step on screen (the snapshot's `beat`); returns when it started."""
        self.beat = {"scene": scene, "id": beat, "at": time.time()}
        return self.beat["at"]

    async def hold_beat(self, started: float, beat: str) -> None:
        """Keep the step on screen for its dwell time, counted from when it started."""
        await asyncio.sleep(max(0.0, started + WALKTHROUGH_DWELL_S[beat] - time.time()))

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
        await self.approve_scene(scene, who="A human", only=lambda tid: ticket_index(tid) < WORKER_CRASH_IN_FLIGHT)
        await asyncio.sleep(1.6)
        self.fault(scene, "Fault: kill -9 on both agent workers", AGENT_WORKERS, "kill")
        self.procs.kill("lane1_worker", restart_after=3.0)
        self.procs.kill("support_worker", restart_after=3.0)
        await asyncio.sleep(6)
        # The rest of the cohort waited through the restart. Now the human gets to them.
        await self.approve_scene(
            scene,
            who="After the restart, the human",
            only=lambda tid: ticket_index(tid) >= WORKER_CRASH_IN_FLIGHT,
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
            "lane2", "commit_then_stall", count=GAUNTLET_REFUNDS, delay_s=GAUNTLET_STALL_S, latency_s=GAUNTLET_LATENCY_S
        )
        await self.submit_cohort(scene, GAUNTLET_REFUNDS, lanes=("lane2",))
        await self.wait_for_proposals(scene)
        await self.approve_scene(scene, then="; each approval becomes a Nexus operation to payments")
        self.fault(scene, "Fault: payments goes quiet after booking", ["payments"], "stall")
        # Filled in from the ledger as the bookings land: see stall_window.
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
