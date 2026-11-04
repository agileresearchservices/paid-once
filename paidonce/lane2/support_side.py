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

# One model call, the SDK's retry included, has to finish well inside this (LLM_TIMEOUT_S and LLM_MAX_RETRIES in
# paidonce/agent.py; a test checks the sum fits).
AGENT_START_TO_CLOSE = timedelta(seconds=60)
# How long support waits for payments to answer the Nexus operation, retries included.
NEXUS_SCHEDULE_TO_CLOSE = timedelta(minutes=10)


def ticket_workflow_id(ticket_id: str) -> str:
    """The support workflow's ID is the ticket, so a second start for a ticket is rejected while the first one runs.

    The show and the tests start, signal and query a ticket through this ID.
    """
    return f"ticket-{ticket_id}"


@workflow.defn
class SupportTicketWorkflow:
    """A refund ticket on the support side: decide, wait for a human, then ask payments for the refund over Nexus.

    `_state` goes `starting`, then `deciding` while the `run_agent` activity runs. A proposal that is not a refund
    ends at `denied` without waiting. A refund proposal waits in `awaiting_approval`, then ends at `rejected`, or
    moves to `refunding` while the Nexus call runs and ends at `done`. The `approve` signal carries the human's
    decision, and the `status` query reports the state. The show and the tests use both. Nothing here does I/O: the
    model and payments calls go through an activity and a Nexus operation.
    """

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
        """Decide, wait for a human if the agent proposed a refund, then ask payments for it over Nexus.

        The model call runs in the `run_agent` activity. Each attempt may take `AGENT_START_TO_CLOSE`, and an attempt
        that takes longer is timed out and retried. The retry policy backs off from 1 s up to 10 s with no attempt cap,
        so a model that keeps failing keeps the ticket in `deciding` until it answers. `NEXUS_SCHEDULE_TO_CLOSE` bounds
        the Nexus call in total, retries included, and it is the only bound on the wait for payments, because the refund
        workflow's retries have no attempt cap either. If the time runs out, the call raises. `run` does not catch it,
        so the workflow fails with `_state` still `refunding`. The outcome is `denied`, `rejected` or `done`.
        """
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
        """The human's decision. The first signal sets it, and a repeat only increments `duplicate_signals`."""
        # Works before run() reaches the wait, and a redelivered signal is counted, not applied twice.
        if self._decision is None:
            self._decision = decision
        else:
            self._duplicate_signals += 1

    @workflow.query
    def status(self) -> dict:
        """The state the show and the tests read: `state`, `proposal`, `refund_id` and `duplicate_signals`.

        A query is answered by a running support worker, so this needs one. The proposal is None until the agent
        answers. Once the workflow has completed, the show reads its result or `describe()` instead, and neither needs
        a worker.
        """
        p = self._proposal
        return {
            "ticket_id": self._ticket_id,
            "state": self._state,
            "duplicate_signals": self._duplicate_signals,
            "proposal": {"action": p.action, "amount_cents": p.amount_cents} if p else None,
            "refund_id": self._refund_id,
        }
