"""Payments team's worker: RefundWorkflow, the HTTP activity and the Nexus handler. Run with python -m."""

import asyncio

from temporalio.worker import Worker

from raccoon import config
from raccoon.lane2.client import connect
from raccoon.lane2.payments_activities import post_refund
from raccoon.lane2.payments_side import PaymentsServiceHandler, RefundWorkflow


async def _run() -> None:
    client = await connect(config.PAYMENTS_NAMESPACE)
    worker = Worker(
        client,
        task_queue=config.PAYMENTS_TASK_QUEUE,
        workflows=[RefundWorkflow],
        activities=[post_refund],
        nexus_service_handlers=[PaymentsServiceHandler()],
    )
    await worker.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
