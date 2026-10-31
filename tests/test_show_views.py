"""The diagram's view of a Lane 2 ticket, the per-scene payments call totals, and when a scene has settled."""

from types import SimpleNamespace

from raccoon.show.engine import _lane2_stage, _scene_calls, _unsettled


def test_unapproved_parked_workflow_waits_for_a_human():
    assert _lane2_stage("RUNNING", [], [])["state"] == "waiting in Temporal"


def test_approved_parked_workflow_is_not_drawn_as_waiting():
    stage = _lane2_stage("RUNNING", [], [], approved=True)
    assert stage["at"] == "temporal"
    assert not stage["state"].startswith("waiting")  # the UI draws "waiting…" as the waiting-for-a-human ring


def test_started_operation_sits_with_payments():
    op = SimpleNamespace(state=3)  # PENDING_NEXUS_OPERATION_STATE_STARTED
    assert _lane2_stage("RUNNING", [], [op], approved=True)["at"] == "payments_worker"


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
