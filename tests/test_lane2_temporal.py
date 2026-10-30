"""Integration tests: need `temporal server start-dev` running and `python -m raccoon.lane2.client` run once.

Run with: pytest -m temporal
"""

import asyncio
import uuid

import httpx
import pytest
from temporalio.worker import Worker

from raccoon import config
from raccoon.lane2.client import connect
from raccoon.lane2.payments_activities import post_refund
from raccoon.lane2.payments_side import PaymentsServiceHandler, RefundWorkflow
from raccoon.lane2.support_activities import run_agent
from raccoon.lane2.support_side import SupportTicketWorkflow, ticket_workflow_id
from raccoon.models import ApprovalDecision, Ticket
from raccoon.payments import ledger
from raccoon.payments.service import app as payments_app
from tests.helpers import Server

pytestmark = pytest.mark.temporal


@pytest.fixture
async def stack(monkeypatch):
    with Server(payments_app) as pay:
        monkeypatch.setattr(config, "PAYMENTS_URL", pay.url)
        monkeypatch.setattr(config, "PAYMENTS_CLIENT_TIMEOUT_S", 1.0)
        support = await connect(config.SUPPORT_NAMESPACE)
        payments = await connect(config.PAYMENTS_NAMESPACE)
        async with (
            Worker(
                support,
                task_queue=config.SUPPORT_TASK_QUEUE,
                workflows=[SupportTicketWorkflow],
                activities=[run_agent],
            ),
            Worker(
                payments,
                task_queue=config.PAYMENTS_TASK_QUEUE,
                workflows=[RefundWorkflow],
                activities=[post_refund],
                nexus_service_handlers=[PaymentsServiceHandler()],
            ),
        ):
            yield support, pay


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


async def test_approval_before_any_worker_is_picked_up_survives():
    """Signal a workflow while no support worker is running; start the worker afterwards."""
    with Server(payments_app) as pay:
        config.PAYMENTS_URL = pay.url
        support = await connect(config.SUPPORT_NAMESPACE)
        payments = await connect(config.PAYMENTS_NAMESPACE)
        t = new_ticket()
        handle = await support.start_workflow(
            SupportTicketWorkflow.run,
            t,
            id=ticket_workflow_id(t.ticket_id),
            task_queue=config.SUPPORT_TASK_QUEUE,
        )
        await handle.signal(SupportTicketWorkflow.approve, ApprovalDecision(True))
        await asyncio.sleep(1)
        async with (
            Worker(
                support,
                task_queue=config.SUPPORT_TASK_QUEUE,
                workflows=[SupportTicketWorkflow],
                activities=[run_agent],
            ),
            Worker(
                payments,
                task_queue=config.PAYMENTS_TASK_QUEUE,
                workflows=[RefundWorkflow],
                activities=[post_refund],
                nexus_service_handlers=[PaymentsServiceHandler()],
            ),
        ):
            outcome = await asyncio.wait_for(handle.result(), 30)
        assert outcome.status == "done"
