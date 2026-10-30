"""Support team's worker: runs SupportTicketWorkflow and the agent activity. Run with python -m."""

import asyncio

from temporalio.worker import Worker

from raccoon import config
from raccoon.lane2.client import connect
from raccoon.lane2.support_activities import run_agent
from raccoon.lane2.support_side import SupportTicketWorkflow


async def _run() -> None:
    client = await connect(config.SUPPORT_NAMESPACE)
    worker = Worker(
        client,
        task_queue=config.SUPPORT_TASK_QUEUE,
        workflows=[SupportTicketWorkflow],
        activities=[run_agent],
    )
    await worker.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
