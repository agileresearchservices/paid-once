"""Support team's worker: runs SupportTicketWorkflow and the agent activity. Run with python -m."""

import asyncio

from temporalio.worker import Worker

from paidonce import config
from paidonce.lane2.client import connect_temporal
from paidonce.lane2.support_activities import run_agent
from paidonce.lane2.support_side import SupportTicketWorkflow


async def _run() -> None:
    """Connect to the support namespace and serve the workflow and the agent activity until the process stops."""
    client = await connect_temporal(config.SUPPORT_NAMESPACE)
    worker = Worker(
        client,
        task_queue=config.SUPPORT_TASK_QUEUE,
        workflows=[SupportTicketWorkflow],
        activities=[run_agent],
    )
    await worker.run()


def main() -> None:
    """Entry point for `python -m paidonce.lane2.support_worker`. The show starts it as a child process."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
