"""The diagram's view of a Lane 2 ticket, the per-scene payments call totals, when a scene has settled, the Nexus
page's attempts and ledger fields, and the engine's scene bookkeeping."""

import re
import time
from pathlib import Path
from types import SimpleNamespace

from temporalio.api.enums.v1 import PendingNexusOperationState

from paidonce.models import TicketOutcome
from paidonce.show import catalog
from paidonce.show.catalog import SCENES, is_demo, ticket_index
from paidonce.show.engine import Engine
from paidonce.show.procs import ProcessManager
from paidonce.show.timeline import (
    LANE1_STAGES,
    backoff_before,
    finish_attempts,
    lane2_stage,
    merge_attempts,
    scene_calls,
    stall_window,
    ticket_ledger,
    unsettled,
)


def test_unapproved_parked_workflow_waits_for_a_human():
    assert lane2_stage("RUNNING", [], [])["state"] == "waiting in Temporal"


def test_approved_parked_workflow_is_not_drawn_as_waiting():
    stage = lane2_stage("RUNNING", [], [], decision=True)
    assert stage["at"] == "temporal"
    assert not stage["state"].startswith("waiting")  # the UI draws "waiting…" as the waiting-for-a-human ring


def test_denied_parked_workflow_is_not_drawn_as_waiting_or_approved():
    stage = lane2_stage("RUNNING", [], [], decision=False)
    assert stage["state"].startswith("denied")


def test_completed_workflow_is_placed_by_its_result():
    assert lane2_stage("COMPLETED", [], [], outcome=TicketOutcome("b", "done", "r1"))["at"] == "done"
    denied = lane2_stage("COMPLETED", [], [], outcome=TicketOutcome("b", "denied", detail="policy: over the limit"))
    assert denied == {"at": "closed", "state": "denied by the agent: policy: over the limit"}
    assert lane2_stage("COMPLETED", [], [], decision=False, outcome=TicketOutcome("b", "rejected"))["at"] == "closed"
    # Until the result is read, a completed workflow is not drawn as refunded.
    assert lane2_stage("COMPLETED", [], [])["at"] != "done"


def test_lane1_denials_are_closed():
    assert LANE1_STAGES["denied"][0] == LANE1_STAGES["rejected"][0] == "closed"


def test_started_operation_sits_with_payments():
    op = SimpleNamespace(state=PendingNexusOperationState.PENDING_NEXUS_OPERATION_STATE_STARTED)
    assert lane2_stage("RUNNING", [], [op], decision=True)["at"] == "payments_worker"


def test_scene_calls_only_sum_this_scenes_tickets():
    calls = {
        "lane1": {"a": {"calls": 2, "replays": 0}, "old": {"calls": 5, "replays": 0}},
        "lane2": {"b": {"calls": 2, "replays": 1}},
    }
    pairs = [("lane1", "a"), ("lane2", "b")]
    assert scene_calls(calls, pairs) == {
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
    assert unsettled(PAIRS, ledger, flow) == []


def test_in_flight_ticket_holds_the_scene_open():
    # Lane 1 gave up, but the ledger's settle window hasn't passed, so "missing" isn't decided yet.
    ledger = {"lane1": {"a": "in_flight"}, "lane2": {"b": "ok"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "lane1_worker", "state": "failed"}],
        "lane2": [{"ticket": "b", "at": "done", "state": "refunded"}],
    }
    assert unsettled(PAIRS, ledger, flow) == ["a"]


def test_refunded_ticket_still_moving_in_its_stack_holds_the_scene_open():
    # Payments booked it, but the workflow hasn't completed: the dot is still on its way.
    ledger = {"lane1": {"a": "ok"}, "lane2": {"b": "ok"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "done", "state": "refunded"}],
        "lane2": [{"ticket": "b", "at": "payments_worker", "state": "refund running in payments"}],
    }
    assert unsettled(PAIRS, ledger, flow) == ["b"]
    assert unsettled(PAIRS, ledger, {"lane1": flow["lane1"], "lane2": []}) == ["b"]


def test_tickets_closed_with_no_refund_let_the_scene_settle():
    ledger = {"lane1": {"a": "declined"}, "lane2": {"b": "rejected"}}
    flow = {
        "lane1": [{"ticket": "a", "at": "closed", "state": "denied by the agent: policy: over the limit"}],
        "lane2": [{"ticket": "b", "at": "closed", "state": "denied by a human"}],
    }
    assert unsettled(PAIRS, ledger, flow) == []
    # The ledger alone isn't enough: a denial the stack hasn't closed yet still holds the scene open.
    flow["lane2"] = [{"ticket": "b", "at": "temporal", "state": "denied, queued in Temporal for a worker"}]
    assert unsettled(PAIRS, ledger, flow) == ["b"]


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
    assert merge_attempts([], _pending("SCHEDULED", 1, scheduled_at=100.0), now=100.5) == []
    attempts = merge_attempts([], _pending("STARTED", 1, scheduled_at=100.0, started_at=101.0), now=101.5)
    assert attempts == [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]


def test_timeout_ends_the_attempt_at_start_plus_start_to_close():
    """What the probe saw: after the 8 s timeout the activity is SCHEDULED again with attempt 2."""
    attempts = merge_attempts([], _pending("STARTED", 1, started_at=102.4), now=103.0)
    attempts = merge_attempts(
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
    attempts = merge_attempts(attempts, _pending("STARTED", 2, scheduled_at=111.4, started_at=114.4), now=114.9)
    assert [(a["n"], a["outcome"]) for a in attempts] == [(1, "failed"), (2, "running")]


def test_other_failures_end_at_the_retry_schedule_minus_backoff():
    attempts = merge_attempts([], _pending("STARTED", 1, started_at=100.0), now=100.5)
    attempts = merge_attempts(
        attempts, _pending("SCHEDULED", 2, scheduled_at=104.0, retry_interval=1.0, failure="HTTP 500"), now=104.2
    )
    assert attempts[0]["ended_at"] == 103.0 and attempts[0]["failure"] == "HTTP 500"


def test_an_end_is_never_before_the_start_or_after_now():
    attempts = merge_attempts([], _pending("STARTED", 1, started_at=100.0), now=100.5)
    early = merge_attempts(attempts, _pending("SCHEDULED", 2, scheduled_at=99.0, retry_interval=5.0), now=101.0)
    assert early[0]["ended_at"] == 100.0
    late = merge_attempts(attempts, _pending("SCHEDULED", 2, failure="StartToClose timeout"), now=105.0)
    assert late[0]["ended_at"] == 105.0


def test_backoff_follows_the_refund_retry_policy():
    assert [backoff_before(n) for n in (1, 2, 3, 4)] == [0.0, 1.0, 2.0, 3.0]


def test_repeated_polls_do_not_duplicate_an_attempt():
    attempts = merge_attempts([], _pending("STARTED", 1, started_at=101.0), now=101.5)
    again = merge_attempts(attempts, _pending("STARTED", 1, started_at=101.0), now=102.5)
    assert again == attempts


def test_history_supplies_the_final_attempt_even_if_no_poll_saw_it():
    attempts = [{"n": 1, "started_at": 102.4, "ended_at": 110.4, "outcome": "failed", "failure": "timeout"}]
    final = {"n": 2, "started_at": 114.4, "ended_at": 116.4, "ok": True, "failure": ""}
    done = finish_attempts(attempts, final, now=117.0)
    assert [(a["n"], a["outcome"], a["ended_at"]) for a in done] == [(1, "failed", 110.4), (2, "ok", 116.4)]


def test_history_replaces_the_polled_copy_of_the_final_attempt():
    attempts = [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]
    final = {"n": 1, "started_at": 101.02, "ended_at": 103.1, "ok": True, "failure": ""}
    assert finish_attempts(attempts, final, now=104.0) == [
        {"n": 1, "started_at": 101.02, "ended_at": 103.1, "outcome": "ok", "failure": ""}
    ]


def test_without_history_a_running_attempt_is_closed_as_unknown():
    attempts = [{"n": 1, "started_at": 101.0, "ended_at": None, "outcome": "running", "failure": ""}]
    assert finish_attempts(attempts, None, now=105.0)[0] == {
        "n": 1,
        "started_at": 101.0,
        "ended_at": 105.0,
        "outcome": "unknown",
        "failure": "",
    }


def test_ticket_ledger_reads_payments_counter_and_booking_time():
    calls = {"lane2": {"t1": {"calls": 2, "replays": 1}}}
    assert ticket_ledger(calls, {"t1": 104.0}, "lane2", "t1") == {"calls": 2, "replays": 1, "booked_at": 104.0}
    assert ticket_ledger(calls, {}, "lane2", "t2") == {"calls": 0, "replays": 0, "booked_at": None}


# The gauntlet's fault windows (step 7, the Nexus page).

STALL = {"mode": "commit_then_stall"}


def test_stall_window_runs_from_first_booking_to_last_held_reply():
    booked = {"a": 10.0, "b": 11.0, "c": 12.5}
    w = stall_window(booked, ["a", "b", "c"], 9.0, {**STALL, "remaining": 2}, 5)
    assert w == {"start": 10.0, "end": 12.5 + 9.0, "hit": 3}


def test_stall_window_ends_at_the_last_booking_the_stall_actually_held():
    # The fault's count ran out after two bookings, so the third booking replied at once.
    booked = {"a": 10.0, "b": 11.0, "c": 12.5}
    w = stall_window(booked, ["a", "b", "c"], 9.0, {**STALL, "remaining": 0}, 2)
    assert w == {"start": 10.0, "end": 11.0 + 9.0, "hit": 2}


def test_stall_window_ignores_other_scenes_bookings():
    w = stall_window({"a": 10.0, "elsewhere": 1.0}, ["a"], 9.0, {**STALL, "remaining": 4}, 5)
    assert w["start"] == 10.0 and w["hit"] == 1


def test_stall_window_is_empty_before_any_booking():
    assert stall_window({}, ["a"], 9.0, {**STALL, "remaining": 5}, 5) == {"start": None, "end": None, "hit": 0}


def test_stall_window_after_the_fault_was_cleared_counts_the_bookings():
    w = stall_window({"a": 10.0, "b": 11.0}, ["a", "b"], 9.0, None, 5)
    assert w == {"start": 10.0, "end": 11.0 + 9.0, "hit": 2}


def _engine_with_window(key: str) -> Engine:
    run = {"kills": {}, "faults": [{"key": key, "effect": "kill", "start": 1.0, "end": None, "hit": 5}]}
    eng = Engine(ProcessManager())  # built outside an event loop, so process events are recorded where they happen
    eng.scene_runs, eng.running, eng.current = {"nexus_kill": run}, True, "nexus_kill"
    return eng


def test_restart_closes_the_killed_process_window():
    eng = _engine_with_window("payments_worker")
    eng.emit_from_procs("restart", "back", proc="payments_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] is not None


def test_restart_of_another_process_leaves_the_window_open():
    # A worker that crash-loops while Temporal is down restarts on its own: that closes nothing.
    eng = _engine_with_window("temporal")
    eng.emit_from_procs("restart", "back", proc="support_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] is None


def test_a_second_restart_does_not_move_a_closed_window():
    eng = _engine_with_window("payments_worker")
    eng.emit_from_procs("restart", "back", proc="payments_worker")
    end = eng.scene_runs["nexus_kill"]["faults"][0]["end"]
    eng.emit_from_procs("restart", "back again", proc="payments_worker")
    assert eng.scene_runs["nexus_kill"]["faults"][0]["end"] == end


async def test_a_walkthrough_step_stays_on_screen_for_its_dwell_time(monkeypatch):
    monkeypatch.setitem(catalog.WALKTHROUGH_DWELL_S, "ticket", 0.3)
    eng = Engine(ProcessManager())
    started = eng.start_beat("walkthrough", "ticket")
    assert eng.beat == {"scene": "walkthrough", "id": "ticket", "at": started}
    t0 = time.time()
    await eng.hold_beat(started, "ticket")
    assert 0.25 <= time.time() - t0 < 1.0
    # Time already spent on the step (the agent was deciding) counts towards its dwell.
    t0 = time.time()
    await eng.hold_beat(started - 5, "ticket")
    assert time.time() - t0 < 0.1


# The worker-crash scene reviews part of a cohort before the fault and the rest after the restart.
def _reviewer() -> Engine:
    eng = Engine(ProcessManager())
    eng.decided = []
    eng.scene_tickets = {"s": []}
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
    assert ticket_index("20261101-run-worker_crash-r2-03-lane1") == 3
    assert ticket_index("a-b-c-r1-11-lane2") == 11


async def test_review_can_cover_only_part_of_the_cohort():
    eng = _reviewer()
    await eng.approve_scene("s", only=lambda tid: ticket_index(tid) < 2, stagger=0)
    assert sorted(i for _, i, _ in eng.decided) == [
        f"run-s-r1-{n:02d}-{lane}" for n in (0, 1) for lane in ("lane1", "lane2")
    ]
    assert all(approved for _, _, approved in eng.decided)
    said = eng.events[-1]["msg"]
    assert "approves 2, denies 0" in said and "policy check closed 1" in said


async def test_the_second_review_gets_the_rest_and_never_the_policy_ticket():
    eng = _reviewer()
    await eng.approve_scene("s", only=lambda tid: ticket_index(tid) >= 2, stagger=0, policy_note=False)
    decided = {(lane, tid.split("-")[-2]): approved for lane, tid, approved in eng.decided}
    assert decided == {
        (lane, n): approved
        for lane in ("lane1", "lane2")
        for n, approved in (("02", True), ("03", True), ("05", False))
    }  # index 04 is the policy ticket: the agent closed it, the human never sees it
    said = eng.events[-1]["msg"]
    assert "approves 2, denies 1" in said and "policy" not in said


def test_every_run_of_the_walkthrough_counts_as_a_demo_ticket():
    assert is_demo("ab12-walkthrough-r1-00-lane1") and is_demo("ab12-walkthrough-r4-00-lane2")
    assert not is_demo("ab12-intro-r1-00-lane1") and not is_demo("ab12-worker_crash-r2-03-lane2")


def test_every_listed_scene_has_a_method_that_plays_it():
    # run_scene looks the method up by name: a scene in SCENES without one would answer "already running".
    assert [s.id for s in SCENES if not hasattr(Engine, f"scene_{s.id}")] == []


def test_a_scenes_tickets_are_found_by_its_id_and_by_its_free_roam_rounds():
    eng = Engine(ProcessManager())
    eng.scene_tickets = {"intro": [("lane1", "a")], "free_roam_0": [("lane2", "b")], "free_roam_1": [("lane1", "c")]}
    assert eng.scene_pairs("intro") == [("lane1", "a")]
    assert eng.scene_pairs("free_roam") == [("lane2", "b"), ("lane1", "c")]
    assert eng.scene_pairs("nothing") == []


def test_the_snapshot_has_exactly_the_keys_the_page_reads():
    # ui/src/types.ts is the page's contract; `locked` is added by the server on top of the engine's snapshot.
    types_ts = (Path(__file__).parent.parent / "ui" / "src" / "types.ts").read_text()
    body = re.search(r"export interface Snapshot \{(.*?)\n\}", types_ts, re.DOTALL).group(1)
    page_keys = set(re.findall(r"^  (\w+)\??:", body, re.MULTILINE))
    assert set(Engine(ProcessManager()).snapshot()) | {"locked"} == page_keys
