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
    return f"refund-{ticket_id}"


@workflow.defn
class RefundWorkflow:
    @workflow.run
    async def run(self, req: RefundRequest) -> RefundResult:
        # 8s on purpose: in the nexus_kill scene an attempt on a killed worker must time out and
        # retry inside the scene window.
        return await workflow.execute_activity(
            "post_refund",
            req,
            result_type=RefundResult,
            start_to_close_timeout=timedelta(seconds=8),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=3),
            ),
        )


@nexusrpc.handler.service_handler(service=PaymentsService)
class PaymentsServiceHandler:
    @nexus.workflow_run_operation
    async def issue_refund(
        self, ctx: nexus.WorkflowRunOperationContext, req: RefundRequest
    ) -> nexus.WorkflowHandle[RefundResult]:
        # Second layer of dedup: a retried Nexus start attaches to the running refund workflow.
        # The real guarantee is the ledger's idempotency key (refund-<ticket_id>).
        return await ctx.start_workflow(
            RefundWorkflow.run,
            req,
            id=refund_workflow_id(req.ticket_id),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
