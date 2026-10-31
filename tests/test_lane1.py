import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from raccoon import audit, config
from raccoon.lane1 import api, store
from raccoon.lane1.worker import Worker
from raccoon.payments import ledger
from raccoon.payments.service import app as payments_app
from tests.helpers import Server, drain


@pytest.fixture
def payments(monkeypatch):
    with Server(payments_app) as srv:
        monkeypatch.setattr(config, "PAYMENTS_URL", srv.url)
        monkeypatch.setattr(config, "PAYMENTS_CLIENT_TIMEOUT_S", 1.0)
        yield srv


def submit(tid="t1", amount=2500):
    store.create_ticket(
        {
            "ticket_id": tid,
            "customer": "c",
            "order_id": "o",
            "amount_cents": amount,
            "message": "broken",
        }
    )
    audit.record_ticket("lane1", tid, "test", amount)


def test_happy_path_refunds_once(payments):
    submit()
    worker = Worker()
    drain(worker)
    assert store.get_ticket("t1")["status"] == "awaiting_approval"
    assert store.approve("t1") == "accepted"
    drain(worker)
    assert store.get_ticket("t1")["status"] == "done"
    assert len(ledger.all_refunds("lane1")) == 1


def test_policy_denies_an_old_order_sent_through_the_api(payments):
    """The order's age has to reach the agent, or Lane 1 would refund what Lane 2 denies."""
    body = {"ticket_id": "t1", "customer": "c", "order_id": "o", "amount_cents": 2500, "message": "broken"}
    with TestClient(api.app) as client:
        assert client.post("/tickets", json={**body, "order_age_days": 45}).json() == {"created": True}
    audit.record_ticket("lane1", "t1", "test", 2500)
    drain(Worker())
    row = store.get_ticket("t1")
    assert row["status"] == "denied"
    assert "45 days" in row["detail"]
    assert store.approve("t1") == "not_ready"
    assert ledger.all_refunds("lane1") == []


def test_approve_before_proposal_is_not_ready(payments):
    submit()
    assert store.approve("t1") == "not_ready"


def test_timeout_retry_double_refunds(payments):
    """Commit-then-stall plus a fresh idempotency key per attempt is two refunds."""
    httpx.post(
        f"{payments.url}/admin/fault",
        json={"lane": "lane1", "mode": "commit_then_stall", "count": 1, "delay_s": 3},
    )
    submit()
    worker = Worker()
    drain(worker)
    store.approve("t1")
    drain(worker)
    refunds = ledger.all_refunds("lane1")
    assert len(refunds) == 2
    assert {r["ticket_id"] for r in refunds} == {"t1"}


def test_restart_while_awaiting_approval_loses_the_ticket(payments):
    submit()
    drain(Worker())  # first worker proposes, then "dies"
    assert store.approve("t1") == "accepted"
    drain(Worker())  # replacement worker has no in-memory checkpoint
    ticket = store.get_ticket("t1")
    assert ticket["status"] == "failed"
    assert ledger.all_refunds("lane1") == []


def test_crash_after_commit_then_recovery_double_refunds(payments, monkeypatch):
    """Worker dies after payments commits but before the ticket is marked done."""
    monkeypatch.setattr(config, "VISIBILITY_TIMEOUT_S", 0.5)
    httpx.post(
        f"{payments.url}/admin/fault",
        json={"lane": "lane1", "mode": "commit_then_stall", "count": 1, "delay_s": 5},
    )
    submit()
    first = Worker()
    drain(first)
    store.approve("t1")

    # Run the execute job on a thread we then abandon, the way kill -9 abandons a process.
    t = threading.Thread(target=first.run_one, daemon=True)
    t.start()
    time.sleep(0.4)  # payments has committed; the client is still waiting on the stalled response
    assert len(ledger.all_refunds("lane1")) == 1
    time.sleep(0.4)  # lease expires; a fresh worker (empty memory) picks the job up
    restarted = Worker()
    restarted.run_one()
    assert store.get_ticket("t1")["status"] == "done"
    assert len(ledger.all_refunds("lane1")) == 2


def test_redelivery_of_finished_ticket_is_a_noop(payments):
    submit()
    worker = Worker()
    drain(worker)
    store.approve("t1")
    drain(worker)
    store.redeliver(1)
    drain(worker)
    assert len(ledger.all_refunds("lane1")) == 1
