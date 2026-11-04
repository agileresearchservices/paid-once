"""The payments service, owned by "the payments team". HTTPS with a self-signed certificate (paidonce/tls.py).

Fault injection lives here because a real payments provider is where "committed, then the
response never arrived" happens. The fault injector flips the flag through /admin/fault. Faults are
tracked per lane so one lane's chaos never consumes the other's.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from paidonce.models import LANES
from paidonce.payments import ledger

DEFAULT_STALL_S = 6.0  # how long a stalled response is held after the commit


def _clear() -> dict:
    """The fault state for each lane with nothing injected.

    `mode` is `none` or `commit_then_stall`. `remaining` is how many new refunds are still to be stalled. `delay_s` is
    how long a stalled response is held after its commit, and `latency_s` is extra time before every commit on the lane.
    `FAULT` starts from this, and `/admin/reset` restores it.
    """
    return {lane: {"mode": "none", "remaining": 0, "delay_s": DEFAULT_STALL_S, "latency_s": 0.0} for lane in LANES}


FAULT: dict = _clear()

# Every call per lane and ticket, and how many the ledger answered from an existing key. Observation only, for the
# dashboard: it shows a retry arriving, and whether payments recognised it as the same refund.
CALLS: dict[str, dict[str, dict[str, int]]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the ledger when the server starts.

    Every ledger call makes sure the table exists first, so this only moves that work to startup.
    """
    ledger.init()
    yield


app = FastAPI(title="payments", lifespan=lifespan)


class RefundBody(BaseModel):
    """The body of `POST /refunds`: a ticket and an amount in cents.

    Lane 1's `call_payments` and Lane 2's `post_refund` send it. The idempotency key and the lane come in headers.
    """

    ticket_id: str
    amount_cents: int


class FaultBody(BaseModel):
    """The body of `POST /admin/fault`, which the show and the tests use to inject a fault on one lane or on both.

    `commit_then_stall` commits the next `count` new refunds on the lane, then holds each response for `delay_s`. A
    caller whose timeout is shorter than `delay_s` gives up after the money has moved, so its retry has to be recognised
    as the same refund. A replayed key is never held. `latency_s` delays every refund on the lane before its commit,
    until the next fault for that lane replaces it.
    """

    lane: Literal["lane1", "lane2", "all"] = "all"
    mode: Literal["none", "commit_then_stall"] = "none"
    count: int = 0  # how many refunds the stall applies to
    delay_s: float = DEFAULT_STALL_S  # how long the response is held after the commit
    latency_s: float = 0.0  # extra latency before committing


@app.get("/healthz")
def healthz() -> dict:
    """Answer `{"ok": true}` once the server is up. The test helper polls it before a test sends any traffic."""
    return {"ok": True}


@app.post("/refunds")
async def create_refund(
    body: RefundBody,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_lane: str = Header("unknown", alias="X-Lane"),
) -> dict:
    """Record a refund unless its `Idempotency-Key` is already in the ledger, and return the stored row.

    Lane 1's `call_payments` and Lane 2's `post_refund` call this. The `X-Lane` header picks the lane's fault and names
    its ledger rows. Any value other than `lane1` or `lane2` gets no faults; the default is `unknown`. A key already in
    the ledger returns the original row with `replayed` true, and nothing is written. A missing key, or an amount that
    is not positive, is refused with a 422. Before the commit, the lane's `latency_s` applies. In `commit_then_stall`
    mode a new refund is committed and then its response is held for `delay_s`; a replay is never held. Every accepted
    call is counted for `/admin/calls`.
    """
    if body.amount_cents <= 0:
        raise HTTPException(422, "amount must be positive")
    fault = FAULT.get(x_lane)
    if fault and fault["latency_s"] > 0:
        await asyncio.sleep(fault["latency_s"])
    stored = await asyncio.to_thread(ledger.record_refund, body.ticket_id, body.amount_cents, idempotency_key, x_lane)
    seen = CALLS.setdefault(x_lane, {}).setdefault(body.ticket_id, {"calls": 0, "replays": 0})
    seen["calls"] += 1
    seen["replays"] += stored["replayed"]
    if fault and fault["mode"] == "commit_then_stall" and fault["remaining"] > 0 and not stored["replayed"]:
        fault["remaining"] -= 1
        # The refund is committed above. The client gives up long before this returns.
        await asyncio.sleep(fault["delay_s"])
    return stored


@app.get("/refunds")
def list_refunds(lane: str | None = None) -> list[dict]:
    """Every refund, oldest first, or one lane's with `?lane=`.

    The show reads the Lane 2 rows to place the stall window on its timeline. The audit reads the ledger directly.
    """
    return ledger.all_refunds(lane)


@app.get("/admin/fault")
def get_fault() -> dict:
    """The fault state for both lanes, as `set_fault` and `reset` left it.

    The show reads it to place the stall window.
    """
    return FAULT


@app.post("/admin/fault")
def set_fault(body: FaultBody) -> dict:
    """Replace one lane's fault, or both lanes' with `lane` `all`, and return the whole fault state.

    Each call replaces that lane's state completely, so a field left out takes its default. The show's `clear_faults`
    sends `none` to every lane when a scene ends.
    """
    targets = LANES if body.lane == "all" else (body.lane,)
    for lane in targets:
        FAULT[lane] = {
            "mode": body.mode,
            "remaining": body.count,
            "delay_s": body.delay_s,
            "latency_s": body.latency_s,
        }
    return FAULT


@app.get("/admin/calls")
def get_calls() -> dict:
    """Calls per lane and ticket: `calls` counts every request, `replays` the ones answered from an existing key.

    The show reads this to draw the payments calls, and the tests use it to check that a retry was recognised.
    """
    return CALLS


@app.post("/admin/reset")
def reset() -> dict:
    """Empty the ledger, clear every lane's fault and forget the call counts.

    The show calls it at boot and on reset, and the tests use it to start from zero.
    """
    ledger.reset()
    FAULT.update(_clear())
    CALLS.clear()
    return {"ok": True}
