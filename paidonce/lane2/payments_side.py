"""Payments team's side: the refund workflow and the Nexus handler that starts it.

Workflow module: no config, httpx or filesystem access here. The HTTP call is the `post_refund`
activity, called by name.
"""

from datetime import timedelta

import nexusrpc
from temporalio import nexus, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy

with workflow.unsafe.imports_passed_through():
    from paidonce.lane2.contract import PaymentsService
    from paidonce.models import RefundRequest, RefundResult


def refund_workflow_id(ticket_id: str) -> str:
    """The refund workflow's ID, `refund-<ticket_id>`, which the show also reads to draw the Nexus page.

    A retried Nexus start attaches to a refund that is still running. Once that refund has closed, a later start runs
    again, and the ledger's idempotency key is what stops a second refund.
    """
    return f"refund-{ticket_id}"


# 8s on purpose: in the nexus_kill scene an attempt on a killed worker must time out and retry inside the scene
# window. The show's Nexus timeline reads these too, to place the end of a timed-out attempt.
REFUND_START_TO_CLOSE = timedelta(seconds=8)
REFUND_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=3))


@workflow.defn
class RefundWorkflow:
    """The payments team's refund workflow: one activity, `post_refund`, retried with `REFUND_RETRY`.

    The class is deliberately tiny. The idempotency lives in the key the activity sends (`refund-<ticket_id>`), so
    every retry asks the ledger for the same refund, and the workflow needs no state of its own.
    """

    @workflow.run
    async def run(self, req: RefundRequest) -> RefundResult:
        """Run `post_refund` and return what it returns.

        Each attempt has `REFUND_START_TO_CLOSE` to answer, and a timed-out or failed attempt is retried after the
        backoff in `REFUND_RETRY`. There is no attempt cap, so a payments outage is retried until payments either
        succeeds or refuses with a 4xx other than 408 or 429, which is not retried.
        """
        return await workflow.execute_activity(
            "post_refund",
            req,
            result_type=RefundResult,
            start_to_close_timeout=REFUND_START_TO_CLOSE,
            retry_policy=REFUND_RETRY,
        )


@nexusrpc.handler.service_handler(service=PaymentsService)
class PaymentsServiceHandler:
    """Payments' implementation of `PaymentsService`, run by the payments worker.

    Its one operation, `issue_refund`, is a workflow-run operation. It starts the refund workflow and returns that
    workflow's handle, so the support side's call completes when the refund workflow does. It makes no HTTP call
    itself: that happens in the `post_refund` activity.
    """

    @nexus.workflow_run_operation
    async def issue_refund(
        self, ctx: nexus.WorkflowRunOperationContext, req: RefundRequest
    ) -> nexus.WorkflowHandle[RefundResult]:
        """Start the refund workflow for the ticket, or attach to one already running, and return its handle.

        The support side sees the operation as `STARTED` while the refund workflow retries its activity. The attempts
        are in that workflow's history, not on the operation.
        """
        # Second layer of dedup: a retried Nexus start attaches to the running refund workflow.
        # The real guarantee is the ledger's idempotency key (refund-<ticket_id>).
        return await ctx.start_workflow(
            RefundWorkflow.run,
            req,
            id=refund_workflow_id(req.ticket_id),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
