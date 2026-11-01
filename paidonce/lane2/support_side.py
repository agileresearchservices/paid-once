"""Support team's workflow: decide, wait for a human, then ask payments for the refund over Nexus.

Workflow module: deterministic, and nothing here touches config, httpx or the filesystem. The agent
runs in an activity that is called by name, so this file never imports paidonce.agent.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from paidonce.lane2.contract import NEXUS_ENDPOINT, PaymentsService
    from paidonce.models import (
        ApprovalDecision,
        Proposal,
        RefundRequest,
        Ticket,
        TicketOutcome,
    )

# One model call has to finish well inside this (see LLM_TIMEOUT_S in paidonce/agent.py).
AGENT_START_TO_CLOSE = timedelta(seconds=60)
# How long support waits for payments to answer the Nexus operation, retries included.
NEXUS_SCHEDULE_TO_CLOSE = timedelta(minutes=10)


def ticket_workflow_id(ticket_id: str) -> str:
    return f"ticket-{ticket_id}"


@workflow.defn
class SupportTicketWorkflow:
    def __init__(self) -> None:
        self._ticket_id = ""
        self._state = "starting"
        self._decision: ApprovalDecision | None = None
        self._duplicate_signals = 0
        self._proposal: Proposal | None = None
        self._refund_id: str | None = None
        self._events: list[str] = []

    @workflow.run
    async def run(self, ticket: Ticket) -> TicketOutcome:
        self._ticket_id = ticket.ticket_id
        self._state = "deciding"
        self._proposal = await workflow.execute_activity(
            "run_agent",
            ticket,
            result_type=Proposal,
            start_to_close_timeout=AGENT_START_TO_CLOSE,
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
        )
        proposal = self._proposal
        self._events.append(f"agent proposed {proposal.action}")
        if proposal.action != "refund":
            self._state = "denied"
            return TicketOutcome(ticket.ticket_id, "denied", detail=proposal.reason, events=self._events)

        # The approval can take days. No timeout: the workflow just waits, and survives deploys.
        self._state = "awaiting_approval"
        await workflow.wait_condition(lambda: self._decision is not None)
        assert self._decision is not None
        if not self._decision.approved:
            self._state = "rejected"
            return TicketOutcome(ticket.ticket_id, "rejected", detail="human said no", events=self._events)
        self._events.append("approved by a human")

        self._state = "refunding"
        nexus = workflow.create_nexus_client(service=PaymentsService, endpoint=NEXUS_ENDPOINT)
        result = await nexus.execute_operation(
            PaymentsService.issue_refund,
            RefundRequest(ticket.ticket_id, proposal.amount_cents),
            schedule_to_close_timeout=NEXUS_SCHEDULE_TO_CLOSE,
        )
        self._refund_id = result.refund_id
        self._events.append(f"refund {result.refund_id} issued")
        self._state = "done"
        return TicketOutcome(ticket.ticket_id, "done", refund_id=result.refund_id, events=self._events)

    @workflow.signal
    def approve(self, decision: ApprovalDecision) -> None:
        # Works before run() reaches the wait, and a redelivered signal is counted, not applied twice.
        if self._decision is None:
            self._decision = decision
        else:
            self._duplicate_signals += 1

    @workflow.query
    def status(self) -> dict:
        p = self._proposal
        return {
            "ticket_id": self._ticket_id,
            "state": self._state,
            "duplicate_signals": self._duplicate_signals,
            "proposal": {"action": p.action, "amount_cents": p.amount_cents} if p else None,
            "refund_id": self._refund_id,
        }
