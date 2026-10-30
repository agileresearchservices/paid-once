"""Support team's activities. Heavy imports (LangGraph, Anthropic) live here, not in the workflow."""

import asyncio

from temporalio import activity

from raccoon import agent
from raccoon.models import Proposal, Ticket


@activity.defn
async def run_agent(ticket: Ticket) -> Proposal:
    # Same decide graph Lane 1 uses; honours RACCOON_STUB_LLM. Off the event loop: it blocks on HTTP.
    return await asyncio.to_thread(agent.run_decide_graph, ticket)
