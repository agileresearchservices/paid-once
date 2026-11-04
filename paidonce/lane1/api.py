"""Lane 1 HTTP API: stateless, writes to SQLite. It stays up when the worker is killed."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from paidonce import config, tls
from paidonce.lane1 import store
from paidonce.models import DEFAULT_ORDER_AGE_DAYS


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the Lane 1 tables when the server starts. The API and the worker share one SQLite file and do not call
    each other, so whichever starts first creates the tables."""
    store.init()
    yield


app = FastAPI(title="lane1-api", lifespan=lifespan)


class TicketBody(BaseModel):
    """What the helpdesk, or the show harness, posts to `POST /tickets`.

    `order_age_days` comes from the order system and feeds the agent's return-window rule (`agent.check_policy`).
    """

    ticket_id: str
    customer: str
    order_id: str
    amount_cents: int
    message: str
    order_age_days: int = DEFAULT_ORDER_AGE_DAYS


class RedeliverBody(BaseModel):
    """The body for `POST /admin/redeliver`: how many execute jobs to deliver again (`store.redeliver` picks them)."""

    n: int = 3


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe: answers while the server is up, without touching the database or the worker."""
    return {"ok": True}


@app.post("/tickets")
def submit(body: TicketBody) -> dict:
    """Accept a ticket from the helpdesk and queue its decide job.

    Returns `{"created": false}` when the ticket id already exists. Nothing changes then, and no second job is queued.
    """
    created = store.create_ticket(body.model_dump())
    return {"created": created}


@app.get("/tickets")
def tickets() -> list[dict]:
    """Lane 1's own record of every ticket (id, status, refund id, detail), oldest first. The show reads this to draw
    Lane 1; the audit does not."""
    return store.list_tickets()


@app.post("/tickets/{ticket_id}/approve")
def approve(ticket_id: str) -> dict:
    """Called for each human approval (the show's approver bot, in the demo). Queues the execute job that resumes the
    paused graph. A repeat returns `already` and queues nothing. 404 for an unknown ticket. 409 for any other ticket
    that is not awaiting approval: before the model has proposed, or after a denial or a rejection."""
    result = store.approve(ticket_id)
    if result == "unknown":
        raise HTTPException(404, "unknown ticket")
    if result == "not_ready":
        raise HTTPException(409, "no proposal to approve yet")
    return {"result": result}


@app.post("/tickets/{ticket_id}/reject")
def reject(ticket_id: str) -> dict:
    """Called for each human denial (the show's approver bot, in the demo). Marks the row `rejected` and queues no job,
    so redelivery and recovery never see the ticket. A repeat returns `already`. 404 for an unknown ticket. 409 for any
    other ticket that is not awaiting approval, including one already approved."""
    result = store.reject(ticket_id)
    if result == "unknown":
        raise HTTPException(404, "unknown ticket")
    if result == "not_ready":
        raise HTTPException(409, "no proposal to reject yet")
    if result == "approved":
        raise HTTPException(409, "already approved")
    return {"result": result}


@app.get("/admin/queue")
def queue() -> dict:
    """What the show waits on: `{"jobs": n}`, the jobs not yet completed, waiting or claimed. A scene does not end
    until this reaches zero."""
    return {"jobs": store.pending_jobs()}


@app.post("/admin/redeliver")
def redeliver(body: RedeliverBody) -> dict:
    """Chaos, called by the show's fault scenes: the broker delivers up to `n` execute jobs a second time, as
    at-least-once delivery can. The reply counts the jobs queued. A ticket that already finished is skipped by the
    dedupe check in `Worker.handle_execute`."""
    return {"redelivered": store.redeliver(body.n)}


@app.post("/admin/reset")
def reset() -> dict:
    """Empty the Lane 1 tables for the show's reset. Worker checkpoints are not cleared, which is safe: a new run's
    ticket ids never match an old one's (`catalog.ticket_id`)."""
    store.reset()
    return {"ok": True}


def main() -> None:
    """Serve the API on loopback at `LANE1_PORT`: HTTPS with the Lane 1 certificate (`tls.server_ssl_kwargs`), or
    plain HTTP when `PAIDONCE_LANE1_TLS=0`."""
    import uvicorn

    uvicorn.run(
        app, host="127.0.0.1", port=config.LANE1_PORT, log_level="warning", **tls.server_ssl_kwargs("lane1_api")
    )


if __name__ == "__main__":
    main()
