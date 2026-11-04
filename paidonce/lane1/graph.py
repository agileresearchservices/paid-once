"""Lane 1's agent: LangGraph with an approval interrupt, as most teams ship it today.

decide -> wait for human approval (interrupt) -> call payments.

The checkpointer is LangGraph's MemorySaver, the default in tutorials and in a lot of
production code. It lives in the worker process. That is the realistic part of Lane 1.
"""

from __future__ import annotations

import time
import uuid
from typing import TypedDict

import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from paidonce import agent, config, tls
from paidonce.lane1 import store
from paidonce.models import Proposal, Ticket

ATTEMPTS = 3
BACKOFF_S = 1.0  # attempt n sleeps n x this after it fails, the last attempt included


class State(TypedDict, total=False):
    """The LangGraph state for one ticket. Each node returns only the keys it sets, and the checkpointer keeps the
    whole state under the ticket id. A key is absent until a node sets it."""

    ticket: Ticket  # the row as the worker read it; the decide job passes it in as the input
    proposal: Proposal  # from `_decide`: `action` is "refund" or "deny"; `amount_cents` is the refund amount
    approved: bool  # from the resume value at `_await_approval`; the worker only ever resumes with True
    refund_id: str  # from `_execute`, once payments has answered


def call_payments(ticket_id: str, amount_cents: int) -> str:
    """POST the refund, retrying on failure.

    A typical client: a short timeout, a few retries, and a fresh request ID per attempt.
    Generating the key per attempt rather than per ticket is a very common mistake, and it is
    the one thing that turns every retry into a potential second refund.
    """
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        key = (
            f"l1-{ticket_id}"  # PAIDONCE_L1_STABLE_KEY=1: the one-line fix, measured by `make scenario`
            if config.L1_STABLE_KEY
            else f"l1-{ticket_id}-{uuid.uuid4().hex[:8]}"
        )
        try:
            resp = httpx.post(
                f"{config.PAYMENTS_URL}/refunds",
                json={"ticket_id": ticket_id, "amount_cents": amount_cents},
                headers={"Idempotency-Key": key, "X-Lane": "lane1"},
                timeout=config.PAYMENTS_CLIENT_TIMEOUT_S,
                verify=tls.client_verify(),
            )
            if resp.status_code < 500:
                resp.raise_for_status()  # a 4xx is a refusal, not a blip: no more attempts here; the worker logs it
                return resp.json()["refund_id"]
            last = RuntimeError(f"payments returned {resp.status_code}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
        time.sleep(BACKOFF_S * attempt)  # in-process backoff
    raise RuntimeError(f"payments failed after {ATTEMPTS} attempts: {last}")


def execute_refund(ticket_id: str, amount_cents: int) -> str:
    """Mark the ticket `executing`, call payments, then mark it `done` with the refund id.

    The window between the two writes is where a crash does damage. The row stays at `executing`. If payments had
    already committed, the recovery path in `Worker.handle_execute` calls it again; with a fresh idempotency key,
    payments takes that for a new refund (architecture.md, Lane 1 realism).
    """
    store.set_status(ticket_id, "executing")
    refund_id = call_payments(ticket_id, amount_cents)
    store.set_status(ticket_id, "done", refund_id=refund_id)
    return refund_id


def _decide(state: State) -> State:
    """The agent's decision: the policy rules first, then the model (`agent.decide`). A policy denial makes no model
    call."""
    return {"proposal": agent.decide(state["ticket"])}


def _await_approval(state: State) -> State:
    """Pause for a human. `interrupt` checkpoints the graph and hands control back to the worker. On resume this node
    runs again from the top and `interrupt` returns the resume value, so nothing before the call may have side effects.
    A proposal that is not a refund skips the pause."""
    proposal = state["proposal"]
    if proposal.action != "refund":
        return {"approved": False}  # nothing to approve: the ticket ends here
    decision = interrupt({"ticket_id": state["ticket"].ticket_id, "amount_cents": proposal.amount_cents})
    return {"approved": bool(decision.get("approved"))}


def _execute(state: State) -> State:
    """Refund the approved amount through `execute_refund`. Only an approved ticket reaches this node."""
    ticket, proposal = state["ticket"], state["proposal"]
    return {"refund_id": execute_refund(ticket.ticket_id, proposal.amount_cents)}


def _after_approval(state: State) -> str:
    # The worker only ever resumes with approved=True: a human "no" is handled at the API, which closes the row
    # and queues no job. The END branch is for a proposal that was not a refund.
    return "execute" if state.get("approved") else END


def build_graph() -> CompiledStateGraph:
    """Compile decide, then await_approval (the interrupt), then execute, which runs only after an approval.

    The MemorySaver checkpointer keeps each paused ticket in this process's memory. That is what makes the approval
    wait live in the worker, and it is why a restarted worker has nothing to resume (architecture.md, Lane 1 realism).
    """
    graph = StateGraph(State)
    graph.add_node("decide", _decide)
    graph.add_node("await_approval", _await_approval)
    graph.add_node("execute", _execute)
    graph.add_edge(START, "decide")
    graph.add_edge("decide", "await_approval")
    graph.add_conditional_edges("await_approval", _after_approval, {"execute": "execute", END: END})
    return graph.compile(checkpointer=MemorySaver())
