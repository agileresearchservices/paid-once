import time

import pytest
from fastapi.testclient import TestClient

from raccoon import audit
from raccoon.payments import ledger
from raccoon.payments.service import app


def post(client, key, ticket="t1", amount=1500, lane="lane1"):
    return client.post(
        "/refunds",
        json={"ticket_id": ticket, "amount_cents": amount},
        headers={"Idempotency-Key": key, "X-Lane": lane},
    )


def test_same_key_is_recorded_once():
    with TestClient(app) as client:
        first = post(client, "k1").json()
        second = post(client, "k1").json()
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["refund_id"] == first["refund_id"]
    assert len(ledger.all_refunds()) == 1


def test_different_keys_for_one_ticket_double_refund():
    with TestClient(app) as client:
        post(client, "attempt-1")
        post(client, "attempt-2")
    assert len(ledger.all_refunds()) == 2


def test_audit_scores_each_invariant():
    now = time.time()
    for tid in ("ok", "dup", "gone", "late", "waiting", "rogue"):
        audit.record_ticket("lane1", tid, "s", 1000)
    for tid in ("ok", "dup", "gone", "late"):
        audit.record_approval("lane1", tid, delivered=True)
    ledger.record_refund("ok", 1000, "a", "lane1")
    ledger.record_refund("dup", 1000, "b", "lane1")
    ledger.record_refund("dup", 1000, "c", "lane1")
    ledger.record_refund("rogue", 1000, "d", "lane1")

    # "late" and "gone" were both approved just now; with a long settle window they are in flight.
    in_flight = audit.compute("lane1", settle_s=60, now=now)
    assert in_flight["refunded_once"] == 1
    assert in_flight["duplicates"] == 1 and in_flight["duplicate_cents"] == 1000
    assert in_flight["in_flight"] == 2 and in_flight["missing"] == 0
    assert in_flight["unapproved"] == 1

    # After the settle window those two count as lost.
    settled = audit.compute("lane1", settle_s=60, now=now + 120)
    assert settled["missing"] == 2 and settled["in_flight"] == 0
    assert settled["violations"] == 4  # dup + 2 missing + rogue
    assert settled["tickets"]["waiting"] == "waiting"


def test_commit_then_stall_still_commits():
    with TestClient(app) as client:
        client.post(
            "/admin/fault",
            json={"mode": "commit_then_stall", "count": 1, "delay_s": 0.2},
        )
        resp = post(client, "k-stall")
        assert resp.status_code == 200
    assert len(ledger.all_refunds()) == 1


@pytest.mark.parametrize("amount", [0, -5])
def test_rejects_bad_amounts(amount):
    with TestClient(app) as client:
        assert post(client, "k", amount=amount).status_code == 422


def test_calls_count_replays_per_ticket():
    with TestClient(app) as client:
        client.post("/admin/reset")
        post(client, "same", ticket="t1", lane="lane2")
        post(client, "same", ticket="t1", lane="lane2")
        post(client, "fresh-1", ticket="t2", lane="lane1")
        post(client, "fresh-2", ticket="t2", lane="lane1")
        calls = client.get("/admin/calls").json()
        assert calls["lane2"]["t1"] == {"calls": 2, "replays": 1}
        assert calls["lane1"]["t2"] == {"calls": 2, "replays": 0}
        client.post("/admin/reset")
        assert client.get("/admin/calls").json() == {}
