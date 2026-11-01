"""The show engine: the state of the running show, and the runner that plays one scene at a time.

A scene runs the same story against Lane 1 (Queue + LangGraph) and Lane 2 (Temporal + Nexus) at the same
time, so the audience watches two systems take identical hits. The exceptions are the walkthrough (one ticket)
and the Nexus gauntlet (Lane 2 only). Scoring comes from the payments ledger (paidonce.audit), never from
what either lane reports about itself.

The work is split by concern, and `Engine` mixes the pieces together over one shared state:
  catalog.py   the scenes and their numbers, the Nexus topology, the ticket-ID convention
  harness.py   submitting tickets, and the approver bot that plays the human
  scenes.py    the scenes themselves and the fault primitives
  views.py     reading each stack's state in the background
  timeline.py  pure functions that turn that state into what the page draws
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid

import httpx
from temporalio.client import Client

from paidonce import audit, config, tls
from paidonce.lane2.client import connect_temporal
from paidonce.models import TicketOutcome
from paidonce.show.catalog import DEMO_SCENES, SCENE_QUIET_S, SCENE_SETTLE_MAX_S, SCENES, TOPOLOGY
from paidonce.show.harness import HarnessMixin
from paidonce.show.procs import ProcessManager
from paidonce.show.scenes import SceneMixin
from paidonce.show.timeline import unsettled
from paidonce.show.views import ViewsMixin


class Engine(HarnessMixin, SceneMixin, ViewsMixin):
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
        self.lane1_jobs: int | None = None  # jobs left in Lane 1's queue (None until read): a scene waits for zero
        self.lane1_view_all: dict[str, int] = {}  # every ticket since reset: the scoreboard compares it with the ledger
        # Every Lane 2 ticket's last-seen workflow status since reset, so the card header accumulates like the
        # scoreboard.
        self.lane2_status: dict[str, str] = {}
        self.lane2_view_all: dict[str, int] = {}
        # How each completed Lane 2 workflow ended (done, denied or rejected), read once from its result.
        self.lane2_outcomes: dict[str, TicketOutcome] = {}
        self.faults: dict = {}  # payments' fault state per lane, as payments reports it
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
        try:  # the process watcher runs on its own thread and hands its events to this loop
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:  # built outside a running loop (a test): events are recorded where they happen
            self._loop = None
        self.procs.emit = self.emit_from_procs

    # -- plumbing ------------------------------------------------------------
    def emit(self, kind: str, msg: str, **extra) -> None:
        self.events.append({"ts": time.time(), "kind": kind, "msg": msg, **extra})
        del self.events[:-200]

    def emit_from_procs(self, kind: str, msg: str, **extra) -> None:
        """The process manager's events (kill, restart). The watcher thread calls this, so it hands the event to the
        event loop: the run's kill counts and fault windows are read and changed there."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: self._record_proc_event(kind, msg, extra))
        else:
            self._record_proc_event(kind, msg, extra)

    def _record_proc_event(self, kind: str, msg: str, extra: dict) -> None:
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

    # -- scene runner -----------------------------------------------------------------
    def _scene_keys(self, scene_id: str) -> list[str]:
        """The keys a scene files its tickets under: its own id, and for free roam its rounds (free_roam_0..3)."""
        return [k for k in self.scene_tickets if k == scene_id or k.startswith(f"{scene_id}_")]

    def scene_pairs(self, scene_id: str) -> list[tuple[str, str]]:
        """(lane, ticket) for every ticket the scene submitted."""
        return [pair for key in self._scene_keys(scene_id) for pair in self.scene_tickets[key]]

    async def settle(self, scene_id: str) -> None:
        """Hold the scene open until each ticket has landed: the ledger has decided it, its stack has stopped moving
        it, and Lane 1's queue is empty (a redelivered job still waiting for a worker would otherwise be missed).
        That must hold for SCENE_QUIET_S, so the scene ends as soon as nothing is moving, not after a fixed wait."""
        pairs = self.scene_pairs(scene_id)
        end = time.time() + SCENE_SETTLE_MAX_S
        quiet_since: float | None = None
        while time.time() < end:
            board = await asyncio.to_thread(audit.compute_all)
            ledger = {lane: board[lane]["tickets"] for lane in board}
            if unsettled(pairs, ledger, self.flow) or self.lane1_jobs:
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
        for key in self._scene_keys(scene_id):
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
                await self.clear_faults()  # held until now, so a retry in the scene still meets the fault
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
        self.lane1_jobs = None
        self.lane2_view_all = {}
        self.booked_at = {}
        self.nexus_seen = {}
        self.flow = {"lane1": [], "lane2": []}
        self.beat = None
        self.scene_runs = {}  # a cancelled scene's finally block then updates a run nobody shows
        self.events.clear()
        self.current = None
        self.emit("reset", "Scoreboard reset")

    # -- snapshot ------------------------------------------------------------------------
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
