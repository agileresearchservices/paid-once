"""The diagram's view of a Lane 2 ticket, from describe() alone, and the per-scene payments call totals."""

from types import SimpleNamespace

from raccoon.show.engine import _lane2_stage, _scene_calls


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
