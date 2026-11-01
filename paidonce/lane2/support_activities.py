"""Support team's activities. Heavy imports (LangGraph, Anthropic) live here, not in the workflow."""

import asyncio

from temporalio import activity

from paidonce import agent
from paidonce.models import Proposal, Ticket


@activity.defn
async def run_agent(ticket: Ticket) -> Proposal:
    # The same decide() Lane 1 calls, wrapped in a one-node graph; honours PAIDONCE_STUB_LLM. Off the event loop: it blocks on HTTP.
    return await asyncio.to_thread(agent.run_decide_graph, ticket)
