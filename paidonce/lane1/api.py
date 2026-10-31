"""Lane 1 HTTP API: stateless, writes to SQLite. It stays up when the worker is killed."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from paidonce import config
from paidonce.lane1 import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    yield


app = FastAPI(title="lane1-api", lifespan=lifespan)


class TicketBody(BaseModel):
    ticket_id: str
    customer: str
    order_id: str
    amount_cents: int
    message: str
    order_age_days: int = 3


class RedeliverBody(BaseModel):
    n: int = 3


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/tickets")
def submit(body: TicketBody) -> dict:
    created = store.create_ticket(body.model_dump())
    return {"created": created}


@app.get("/tickets")
def tickets() -> list[dict]:
    return store.list_tickets()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(404, "unknown ticket")
    return ticket


@app.post("/tickets/{ticket_id}/approve")
def approve(ticket_id: str) -> dict:
    result = store.approve(ticket_id)
    if result == "unknown":
        raise HTTPException(404, "unknown ticket")
    if result == "not_ready":
        raise HTTPException(409, "no proposal to approve yet")
    return {"result": result}


@app.post("/tickets/{ticket_id}/reject")
def reject(ticket_id: str) -> dict:
    result = store.reject(ticket_id)
    if result == "unknown":
        raise HTTPException(404, "unknown ticket")
    if result == "not_ready":
        raise HTTPException(409, "no proposal to reject yet")
    if result == "approved":
        raise HTTPException(409, "already approved")
    return {"result": result}


@app.post("/admin/redeliver")
def redeliver(body: RedeliverBody) -> dict:
    return {"redelivered": store.redeliver(body.n)}


@app.post("/admin/reset")
def reset() -> dict:
    store.reset()
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=config.LANE1_PORT, log_level="warning")


if __name__ == "__main__":
    main()
