"""The payments service (owned by "the payments team"). Plain HTTP, as it is today.

Fault injection lives here because a real payments provider is where "committed, then the
response never arrived" happens. The raccoon flips the flag through /admin/fault. Faults are
tracked per lane so one lane's chaos never consumes the other's.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from raccoon.payments import ledger

LANES = ("lane1", "lane2")


def _clear() -> dict:
    return {
        lane: {"mode": "none", "remaining": 0, "delay_s": 6.0, "latency_s": 0.0}
        for lane in LANES
    }


FAULT: dict = _clear()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ledger.init()
    yield


app = FastAPI(title="payments", lifespan=lifespan)


class RefundBody(BaseModel):
    ticket_id: str
    amount_cents: int


class FaultBody(BaseModel):
    lane: str = "all"  # lane1 | lane2 | all
    mode: str = "none"  # none | commit_then_stall
    count: int = 0  # how many refunds the stall applies to
    delay_s: float = 6.0  # how long the response is held after the commit
    latency_s: float = 0.0  # extra latency before committing


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/refunds")
async def create_refund(
    body: RefundBody,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_lane: str = Header("unknown", alias="X-Lane"),
) -> dict:
    if body.amount_cents <= 0:
        raise HTTPException(422, "amount must be positive")
    fault = FAULT.get(x_lane)
    if fault and fault["latency_s"] > 0:
        await asyncio.sleep(fault["latency_s"])
    stored = await asyncio.to_thread(
        ledger.record_refund, body.ticket_id, body.amount_cents, idempotency_key, x_lane
    )
    if (
        fault
        and fault["mode"] == "commit_then_stall"
        and fault["remaining"] > 0
        and not stored["replayed"]
    ):
        fault["remaining"] -= 1
        # The refund is committed above. The client gives up long before this returns.
        await asyncio.sleep(fault["delay_s"])
    return stored


@app.get("/refunds")
def list_refunds(lane: str | None = None) -> list[dict]:
    return ledger.all_refunds(lane)


@app.get("/admin/fault")
def get_fault() -> dict:
    return FAULT


@app.post("/admin/fault")
def set_fault(body: FaultBody) -> dict:
    targets = LANES if body.lane == "all" else (body.lane,)
    for lane in targets:
        FAULT[lane] = {
            "mode": body.mode,
            "remaining": body.count,
            "delay_s": body.delay_s,
            "latency_s": body.latency_s,
        }
    return FAULT


@app.post("/admin/reset")
def reset() -> dict:
    ledger.reset()
    FAULT.update(_clear())
    return {"ok": True}
