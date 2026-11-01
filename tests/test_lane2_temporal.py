"""Integration tests for Lane 2 and Nexus.

Run with `make test-temporal`: it starts a throwaway Temporal server, creates the namespaces and endpoint, then runs
`pytest -m temporal`. Never run them against the show's server: its workers share these task queues.
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from temporalio.worker import Worker

from paidonce import config
from paidonce.lane2.client import connect_temporal
from paidonce.lane2.payments_activities import post_refund
from paidonce.lane2.payments_side import PaymentsServiceHandler, RefundWorkflow
from paidonce.lane2.support_activities import run_agent
from paidonce.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from paidonce.models import ApprovalDecision, Ticket
from paidonce.payments import ledger

pytestmark = pytest.mark.temporal


@pytest.fixture(autouse=True)
def own_temporal_server():
    # scripts/test-temporal.sh names the throwaway server it started. On any other server (the show's, say) another
    # worker may poll these task queues and take the tests' workflows, so refuse rather than fail mysteriously.
    if os.environ.get("PAIDONCE_TEST_TEMPORAL") != config.TEMPORAL_ADDRESS:
        pytest.fail(
            f"refusing to run on {config.TEMPORAL_ADDRESS}: use `make test-temporal`, which starts its own server",
            pytrace=False,
        )


@asynccontextmanager
async def both_teams_running(support, payments_ns):
    """The support team's worker and the payments team's worker (with its Nexus handler), each on its own namespace."""
    async with (
        Worker(
            support,
            task_queue=config.SUPPORT_TASK_QUEUE,
            workflows=[SupportTicketWorkflow],
            activities=[run_agent],
        ),
        Worker(
            payments_ns,
            task_queue=config.PAYMENTS_TASK_QUEUE,
            workflows=[RefundWorkflow],
            activities=[post_refund],
            nexus_service_handlers=[PaymentsServiceHandler()],
        ),
    ):
        yield


@pytest.fixture
async def stack(payments):
    """Both teams' workers on this server; yields the support client and the payments service."""
    support = await connect_temporal(config.SUPPORT_NAMESPACE)
    payments_ns = await connect_temporal(config.PAYMENTS_NAMESPACE)
    async with both_teams_running(support, payments_ns):
        yield support, payments


def new_ticket():
    tid = f"it-{uuid.uuid4().hex[:8]}"
    return Ticket(tid, "c", "o", 4200, "my item arrived broken")


async def test_ticket_flows_through_nexus_to_one_refund(stack):
    support, _ = stack
    t = new_ticket()
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
    outcome = await handle.result()
    assert outcome.status == "done"
    refunds = ledger.all_refunds("lane2")
    assert [r["ticket_id"] for r in refunds] == [t.ticket_id]


async def test_duplicate_approval_signals_do_not_double_refund(stack):
    support, _ = stack
    t = new_ticket()
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    for _ in range(3):
        await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
    await handle.result()
    assert len(ledger.all_refunds("lane2")) == 1
    assert (await handle.query(SupportTicketWorkflow.status))["duplicate_signals"] == 2


async def test_timeout_after_commit_is_one_refund(stack):
    support, pay = stack
    httpx.post(
        f"{pay.url}/admin/fault",
        json={"lane": "lane2", "mode": "commit_then_stall", "count": 1, "delay_s": 3},
    )
    t = new_ticket()
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
    await handle.result()
    assert len(ledger.all_refunds("lane2")) == 1


async def test_approval_before_any_worker_is_picked_up_survives(payments):
    """Signal a workflow while no support worker is running; start the worker afterwards."""
    support = await connect_temporal(config.SUPPORT_NAMESPACE)
    payments_ns = await connect_temporal(config.PAYMENTS_NAMESPACE)
    t = new_ticket()
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
    await asyncio.sleep(1)  # nothing is polling the queue: the signal just sits in history
    async with both_teams_running(support, payments_ns):
        outcome = await asyncio.wait_for(handle.result(), 30)
    assert outcome.status == "done"


async def test_human_rejection_ends_rejected_with_no_refund(stack):
    support, _ = stack
    t = new_ticket()
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(False))
    outcome = await handle.result()
    assert outcome.status == "rejected"
    assert ledger.all_refunds("lane2") == []


async def test_policy_denial_ends_without_a_nexus_operation(stack):
    support, _ = stack
    t = Ticket(f"it-{uuid.uuid4().hex[:8]}", "c", "o", 4200, "my item arrived broken", order_age_days=45)
    handle = await support.start_workflow(
        SupportTicketWorkflow.run,
        t,
        id=ticket_workflow_id(t.ticket_id),
        task_queue=config.SUPPORT_TASK_QUEUE,
    )
    outcome = await handle.result()
    assert outcome.status == "denied"
    assert "30-day window" in outcome.detail
    history = await handle.fetch_history()
    assert not any(e.HasField("nexus_operation_scheduled_event_attributes") for e in history.events)
    assert ledger.all_refunds("lane2") == []
