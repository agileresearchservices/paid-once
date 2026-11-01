"""The diagram's view of a Lane 2 ticket, the per-scene payments call totals, when a scene has settled, and the
Nexus timeline's attempts and ledger fields."""

import asyncio
from types import SimpleNamespace

from paidonce.models import TicketOutcome
from paidonce.show.engine import (
    LANE1_STAGES,
    Engine,
    _backoff_before,
    _finish_attempts,
    _lane2_stage,
    _merge_attempts,
    _scene_calls,
    _stall_window,
    _ticket_index,
    _ticket_ledger,
    _unsettled,
)


def test_unapproved_parked_workflow_waits_for_a_human():
    assert _lane2_stage("RUNNING", [], [])["state"] == "waiting in Temporal"


def test_approved_parked_workflow_is_not_drawn_as_waiting():
    stage = _lane2_stage("RUNNING", [], [], decision=True)
    assert stage["at"] == "temporal"
    assert not stage["state"].startswith("waiting")  # the UI draws "waiting…" as the waiting-for-a-human ring


def test_denied_parked_workflow_is_not_drawn_as_waiting_or_approved():
    stage = _lane2_stage("RUNNING", [], [], decision=False)
    assert stage["state"].startswith("denied")


def test_completed_workflow_is_placed_by_its_result():
    assert _lane2_stage("COMPLETED", [], [], outcome=TicketOutcome("b", "done", "r1"))["at"] == "done"
    denied = _lane2_stage("COMPLETED", [], [], outcome=TicketOutcome("b", "denied", detail="policy: over the limit"))
    assert denied == {"at": "closed", "state": "denied by the agent: policy: over the limit"}
    assert _lane2_stage("COMPLETED", [], [], decision=False, outcome=TicketOutcome("b", "rejected"))["at"] == "closed"
    # Until the result is read, a completed workflow is not drawn as refunded.
    assert _lane2_stage("COMPLETED", [], [])["at"] != "done"


def test_lane1_denials_are_closed():
    assert LANE1_STAGES["denied"][0] == LANE1_STAGES["rejected"][0] == "closed"


def test_started_operation_sits_with_payments():
    op = SimpleNamespace(state=3)  # PENDING_NEXUS_OPERATION_STATE_STARTED
    assert _lane2_stage("RUNNING", [], [op], decision=True)["at"] == "payments_worker"


def test_scene_calls_only_sum_this_scenes_tickets():
    calls = {
        "lane1": {"a": {"calls": 2, "replays": 0}, "old": {"calls": 5, "replays": 0}},
        "lane2": {"b": {"calls": 2, "replays": 1}},
    }
    pairs = [("lane1", "a"), ("lane2", "b")]
    assert _scene_calls(calls, pairs) == {
        "lane1": {"calls": 2, "booked": 2, "replays": 0},
        "lane2": {"calls": 2, "booked": 1, "replays": 1},
    }


PAIRS = [("lane1", "a"), ("lane2", "b")]


def test_scene_settles_once_ledger_and_stacks_agree():
    ledger = {"lane1": {"a": "missing"}, "lane2": {"b": "ok"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "lane1_worker", "state": "failed"}],
        "lane2": [{"ticket": "b", "at": "done", "state": "refunded"}],
    }
    assert _unsettled(PAIRS, ledger, flow) == []


def test_in_flight_ticket_holds_the_scene_open():
    # Lane 1 gave up, but the ledger's settle window hasn't passed, so "missing" isn't decided yet.
    ledger = {"lane1": {"a": "in_flight"}, "lane2": {"b": "ok"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "lane1_worker", "state": "failed"}],
        "lane2": [{"ticket": "b", "at": "done", "state": "refunded"}],
    }
    assert _unsettled(PAIRS, ledger, flow) == ["a"]


def test_refunded_ticket_still_moving_in_its_stack_holds_the_scene_open():
    # Payments booked it, but the workflow hasn't completed: the dot is still on its way.
    ledger = {"lane1": {"a": "ok"}, "lane2": {"b": "ok"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "done", "state": "refunded"}],
        "lane2": [{"ticket": "b", "at": "payments_worker", "state": "refund running in payments"}],
    }
    assert _unsettled(PAIRS, ledger, flow) == ["b"]
    assert _unsettled(PAIRS, ledger, {"lane1": flow["lane1"], "lane2": []}) == ["b"]


def test_tickets_closed_with_no_refund_let_the_scene_settle():
    ledger = {"lane1": {"a": "declined"}, "lane2": {"b": "rejected"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "closed", "state": "denied by the agent: policy: over the limit"}],
        "lane2": [{"ticket": "b", "at": "closed", "state": "denied by a human"}],
    }
    assert _unsettled(PAIRS, ledger, flow) == []
    # The ledger alone isn't enough: a denial the stack hasn't closed yet still holds the scene open.
    flow["lane2"] = [{"ticket": "b", "at": "temporal", "state": "denied, queued in Temporal for a worker"}]
    assert _unsettled(PAIRS, ledger, flow) == ["b"]


def _pending(state, attempt, scheduled_at=None, started_at=None, retry_interval=0.0, failure="", start_to_close=8.0):
    return {
        "state": state,
        "attempt": attempt,
        "scheduled_at": scheduled_at,
        "started_at": started_at,
        "retry_interval": retry_interval,
        "start_to_close": start_to_close,
        "failure": failure,
    }


def test_attempt_is_recorded_only_once_started():
    assert _merge_attempts([], _pending("SCHEDULED", 1, scheduled_at=100.0), now=100.5) == []
    attempts = _merge_attempts([], _pending("STARTED", 1, scheduled_at=100.0, started_at=101.0), now=101.5)
    assert attempts == [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]


def test_timeout_ends_the_attempt_at_start_plus_start_to_close():
    """What the probe saw: after the 8 s timeout the activity is SCHEDULED again with attempt 2."""
    attempts = _merge_attempts([], _pending("STARTED", 1, started_at=102.4), now=103.0)
    attempts = _merge_attempts(
        attempts,
        _pending("SCHEDULED", 2, scheduled_at=111.4, retry_interval=1.0, failure="activity StartToClose timeout"),
        now=111.6,
    )
    assert attempts == [
        {
            "n": 1,
            "started_at": 102.4,
            "ended_at": 110.4,
            "outcome": "failed",
            "failure": "activity StartToClose timeout",
        }
    ]
    attempts = _merge_attempts(attempts, _pending("STARTED", 2, scheduled_at=111.4, started_at=114.4), now=114.9)
    assert [(a["n"], a["outcome"]) for a in attempts] == [(1, "failed"), (2, "running")]


def test_other_failures_end_at_the_retry_schedule_minus_backoff():
    attempts = _merge_attempts([], _pending("STARTED", 1, started_at=100.0), now=100.5)
    attempts = _merge_attempts(
        attempts, _pending("SCHEDULED", 2, scheduled_at=104.0, retry_interval=1.0, failure="HTTP 500"), now=104.2
    )
    assert attempts[0]["ended_at"] == 103.0 and attempts[0]["failure"] == "HTTP 500"


def test_an_end_is_never_before_the_start_or_after_now():
    attempts = _merge_attempts([], _pending("STARTED", 1, started_at=100.0), now=100.5)
    early = _merge_attempts(attempts, _pending("SCHEDULED", 2, scheduled_at=99.0, retry_interval=5.0), now=101.0)
    assert early[0]["ended_at"] == 100.0
    late = _merge_attempts(attempts, _pending("SCHEDULED", 2, failure="StartToClose timeout"), now=105.0)
    assert late[0]["ended_at"] == 105.0


def test_backoff_follows_the_refund_retry_policy():
    assert [_backoff_before(n) for n in (1, 2, 3, 4)] == [0.0, 1.0, 2.0, 3.0]


def test_repeated_polls_do_not_duplicate_an_attempt():
    attempts = _merge_attempts([], _pending("STARTED", 1, started_at=101.0), now=101.5)
    again = _merge_attempts(attempts, _pending("STARTED", 1, started_at=101.0), now=102.5)
    assert again == attempts


def test_history_supplies_the_final_attempt_even_if_no_poll_saw_it():
    attempts = [{"n": 1, "started_at": 102.4, "ended_at": 110.4, "outcome": "failed", "failure": "timeout"}]
    final = {"n": 2, "started_at": 114.4, "ended_at": 116.4, "ok": True, "failure": ""}
    done = _finish_attempts(attempts, final, now=117.0)
    assert [(a["n"], a["outcome"], a["ended_at"]) for a in done] == [(1, "failed", 110.4), (2, "ok", 116.4)]


def test_history_replaces_the_polled_copy_of_the_final_attempt():
    attempts = [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]
    final = {"n": 1, "started_at": 101.02, "ended_at": 103.1, "ok": True, "failure": ""}
    assert _finish_attempts(attempts, final, now=104.0) == [
        {"n": 1, "started_at": 101.02, "ended_at": 103.1, "outcome": "ok", "failure": ""}
    ]


def test_without_history_a_running_attempt_is_closed_as_unknown():
    attempts = [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]
    assert _finish_attempts(attempts, None, now=105.0)[0] == {
        "n": 1,
        "started_at": 101.0,
        "ended_at": 105.0,
        "outcome": "unknown",
        "failure": "",
    }


def test_ticket_ledger_reads_payments_counter_and_booking_time():
    calls = {"lane2": {"t1": {"calls": 2, "replays": 1}}}
    assert _ticket_ledger(calls, {"t1": 104.0}, "lane2", "t1") == {"calls": 2, "replays": 1, "booked_at": 104.0}
    assert _ticket_ledger(calls, {}, "lane2", "t2") == {"calls": 0, "replays": 0, "booked_at": None}


# The gauntlet's fault windows (step 7).

STALL = {"mode": "commit_then_stall"}


def test_stall_window_runs_from_first_booking_to_last_held_reply():
    booked = {"a": 10.0, "b": 11.0, "c": 12.5}
    w = _stall_window(booked, ["a", "b", "c"], 9.0, {**STALL, "remaining": 2}, 5)
    assert w == {"start": 10.0, "end": 12.5 + 9.0, "hit": 3}


def test_stall_window_ends_at_the_last_booking_the_stall_actually_held():
    # The fault's count ran out after two bookings, so the third booking replied at once.
    booked = {"a": 10.0, "b": 11.0, "c": 12.5}
    w = _stall_window(booked, ["a", "b", "c"], 9.0, {**STALL, "remaining": 0}, 2)
    assert w == {"start": 10.0, "end": 11.0 + 9.0, "hit": 2}


def test_stall_window_ignores_other_scenes_bookings():
    w = _stall_window({"a": 10.0, "elsewhere": 1.0}, ["a"], 9.0, {**STALL, "remaining": 4}, 5)
    assert w["start"] == 10.0 and w["hit"] == 1


def test_stall_window_is_empty_before_any_booking():
    assert _stall_window({}, ["a"], 9.0, {**STALL, "remaining": 5}, 5) == {"start": None, "end": None, "hit": 0}


def test_stall_window_after_the_fault_was_cleared_counts_the_bookings():
    w = _stall_window({"a": 10.0, "b": 11.0}, ["a", "b"], 9.0, None, 5)
    assert w == {"start": 10.0, "end": 11.0 + 9.0, "hit": 2}


def _engine_with_window(key: str) -> SimpleNamespace:
    run = {"kills": {}, "faults": [{"key": key, "effect": "kill", "start": 1.0, "end": None, "hit": 5}]}
    return SimpleNamespace(
        scene_runs={"nexus_kill": run}, running=True, current="nexus_kill", emit=lambda *a, **k: None
    )


def test_restart_closes_the_killed_process_window():
    eng = _engine_with_window("payments_worker")
    Engine.emit_from_procs(eng, "restart", "back", proc="payments_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] is not None


def test_restart_of_another_process_leaves_the_window_open():
    # A worker that crash-loops while Temporal is down restarts on its own: that closes nothing.
    eng = _engine_with_window("temporal")
    Engine.emit_from_procs(eng, "restart", "back", proc="support_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] is None


def test_a_second_restart_does_not_move_a_closed_window():
    eng = _engine_with_window("payments_worker")
    Engine.emit_from_procs(eng, "restart", "back", proc="payments_worker")
    end = eng.scene_runs["nexus_kill"]["faults"][0]["end"]
    Engine.emit_from_procs(eng, "restart", "back again", proc="payments_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] == end


def _stepper() -> SimpleNamespace:
    return SimpleNamespace(beat=None, _beat_gate=None)


def test_walkthrough_waits_on_a_step_until_its_box_is_dismissed():
    async def go() -> list[str]:
        eng = _stepper()
        log: list[str] = []

        async def scene() -> None:
            await Engine.await_beat(eng, "walkthrough", "ticket")
            log.append("after ticket")
            await Engine.await_beat(eng, "walkthrough", "agent")
            log.append("after agent")

        task = asyncio.create_task(scene())
        await asyncio.sleep(0.05)
        assert eng.beat["id"] == "ticket" and log == []
        assert Engine.continue_beat(eng, "ticket") is True
        await asyncio.sleep(0.05)
        assert eng.beat["id"] == "agent" and log == ["after ticket"]
        assert Engine.continue_beat(eng, "agent") is True
        await task
        assert eng.beat is None
        return log

    assert asyncio.run(go()) == ["after ticket", "after agent"]


def test_a_late_click_for_an_earlier_step_does_not_skip_the_next_one():
    async def go() -> None:
        eng = _stepper()

        async def scene() -> None:
            await Engine.await_beat(eng, "walkthrough", "ticket")
            await Engine.await_beat(eng, "walkthrough", "agent")

        task = asyncio.create_task(scene())
        await asyncio.sleep(0.05)
        assert Engine.continue_beat(eng, "ticket") is True
        await asyncio.sleep(0.05)
        assert Engine.continue_beat(eng, "ticket") is False  # a double-click lands on the next step's box
        assert eng.beat["id"] == "agent"
        assert not task.done()
        Engine.continue_beat(eng, "agent")
        await task

    asyncio.run(go())


def test_continue_with_no_step_waiting_does_nothing():
    assert Engine.continue_beat(_stepper(), "ticket") is False


def test_cancelling_the_scene_clears_the_step():
    async def go() -> None:
        eng = _stepper()
        task = asyncio.create_task(Engine.await_beat(eng, "walkthrough", "ticket"))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert eng.beat is None and eng._beat_gate is None

    asyncio.run(go())


# The worker-crash scene reviews part of a cohort before the fault and the rest after the restart.
def _reviewer() -> SimpleNamespace:
    eng = SimpleNamespace(events=[], decided=[])
    eng.emit = lambda kind, msg, **extra: eng.events.append((kind, msg))
    eng.scene_tickets = {"s": []}
    eng.plan = {}
    plans = ["refund", "refund", "refund", "refund", "policy", "human_no"]
    for lane in ("lane1", "lane2"):
        for i, plan in enumerate(plans):
            tid = f"run-s-r1-{i:02d}-{lane}"
            eng.scene_tickets["s"].append((lane, tid))
            eng.plan[tid] = plan

    async def decide(lane: str, tid: str, approved: bool) -> None:
        eng.decided.append((lane, tid, approved))

    eng.decide_ticket = decide
    return eng


def test_ticket_index_is_the_position_in_the_cohort():
    assert _ticket_index("20261101-run-worker_crash-r2-03-lane1") == 3
    assert _ticket_index("a-b-c-r1-11-lane2") == 11


def test_review_can_cover_only_part_of_the_cohort():
    async def go() -> None:
        eng = _reviewer()
        await Engine.approve_scene(eng, "s", only=lambda tid: _ticket_index(tid) < 2, stagger=0)
        assert sorted(i for _, i, _ in eng.decided) == [
            f"run-s-r1-{n:02d}-{lane}" for n in (0, 1) for lane in ("lane1", "lane2")
        ]
        assert all(approved for _, _, approved in eng.decided)
        assert "approves 2, denies 0" in eng.events[0][1] and "policy check closed 1" in eng.events[0][1]

    asyncio.run(go())


def test_the_second_review_gets_the_rest_and_never_the_policy_ticket():
    async def go() -> None:
        eng = _reviewer()
        await Engine.approve_scene(eng, "s", only=lambda tid: _ticket_index(tid) >= 2, stagger=0, policy_note=False)
        decided = {(lane, tid.split("-")[-2]): approved for lane, tid, approved in eng.decided}
        assert decided == {
            (lane, n): approved
            for lane in ("lane1", "lane2")
            for n, approved in (("02", True), ("03", True), ("05", False))
        }  # index 04 is the policy ticket: the agent closed it, the human never sees it
        assert "approves 2, denies 1" in eng.events[0][1] and "policy" not in eng.events[0][1]

    asyncio.run(go())
