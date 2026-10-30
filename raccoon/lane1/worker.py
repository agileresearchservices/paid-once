"""Lane 1 worker: a few threads pulling jobs from the table and running the graph."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict

from langgraph.types import Command

from raccoon.lane1 import store
from raccoon.lane1.graph import build_graph, execute_refund
from raccoon.models import Ticket

log = logging.getLogger("lane1.worker")
THREADS = 4


class Worker:
    def __init__(self) -> None:
        # In-process checkpoints. They disappear when this process does.
        self.graph = build_graph()

    @staticmethod
    def _cfg(ticket_id: str) -> dict:
        return {"configurable": {"thread_id": ticket_id}}

    def handle_decide(self, row: dict) -> None:
        ticket = store.get_ticket(row["ticket_id"])
        if ticket is None or ticket["status"] not in ("new", "deciding"):
            return
        store.set_status(ticket["ticket_id"], "deciding")
        cfg = self._cfg(ticket["ticket_id"])
        result = self.graph.invoke(
            {
                "ticket": Ticket(
                    ticket["ticket_id"],
                    ticket["customer"],
                    ticket["order_id"],
                    ticket["amount_cents"],
                    ticket["message"],
                )
            },
            cfg,
        )
        state = self.graph.get_state(cfg).values
        proposal = state["proposal"]
        if "__interrupt__" in result:
            store.set_status(
                ticket["ticket_id"], "awaiting_approval", proposal=asdict(proposal)
            )
        else:
            store.set_status(
                ticket["ticket_id"],
                "denied",
                proposal=asdict(proposal),
                detail=proposal.reason,
            )

    def handle_execute(self, row: dict) -> None:
        ticket_id = row["ticket_id"]
        ticket = store.get_ticket(ticket_id)
        if ticket is None or ticket["status"] == "done":
            return  # a careful dedupe check: finished tickets are not run again
        cfg = self._cfg(ticket_id)
        if self.graph.get_state(cfg).next:
            self.graph.invoke(Command(resume={"approved": True}), cfg)
        elif ticket["status"] == "executing" and ticket["proposal"]:
            # Recovery path added after the first incident: the checkpoint is gone but the row says we
            # were mid-flight, so drive the stored proposal again.
            execute_refund(ticket_id, ticket["proposal"]["amount_cents"])
        elif ticket["status"] == "approved":
            store.set_status(
                ticket_id,
                "failed",
                detail="approved, but the in-memory graph state was lost on restart",
            )

    def run_one(self) -> bool:
        job = store.claim_job()
        if job is None:
            return False
        try:
            if job["kind"] == "decide":
                self.handle_decide(job)
            else:
                self.handle_execute(job)
            store.complete_job(job)
        except Exception:
            log.exception("job %s failed", job["job_id"])
        return True

    def loop(self) -> None:
        while True:
            if not self.run_one():
                time.sleep(0.3)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s lane1.worker %(message)s"
    )
    store.init()
    worker = Worker()
    log.info("lane1 worker started with %d threads", THREADS)
    threads = [
        threading.Thread(target=worker.loop, daemon=True) for _ in range(THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
