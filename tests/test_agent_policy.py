import sys
from types import SimpleNamespace

import pytest

from paidonce import agent, config
from paidonce.lane2.support_side import AGENT_START_TO_CLOSE
from paidonce.models import Ticket


def ticket(amount=2500, age=3):
    return Ticket("t1", "c", "o", amount, "arrived broken", age)


def test_amount_over_the_limit_breaks_policy():
    assert "limit" in agent.check_policy(ticket(amount=agent.POLICY_LIMIT_CENTS + 100))


def test_order_past_the_return_window_breaks_policy():
    assert "45 days" in agent.check_policy(ticket(age=45))


def test_in_policy_ticket_passes():
    assert agent.check_policy(ticket(amount=agent.POLICY_LIMIT_CENTS, age=agent.RETURN_WINDOW_DAYS)) is None


def test_policy_deny_never_reaches_the_model(monkeypatch):
    # Tests run with the stub model, so the stub stands in for the Anthropic call.
    def no_model(_):
        pytest.fail("the model was called for a ticket the policy already denies")

    monkeypatch.setattr(agent, "_stub_decide", no_model)
    proposal = agent.decide(ticket(age=45))
    assert proposal.action == "deny"
    assert proposal.amount_cents == 0
    assert proposal.reason.startswith("policy: ")


def _model_replies(monkeypatch, **tool_input):
    """Stand in for the Anthropic client: it answers every call with this propose_action tool use."""
    block = SimpleNamespace(type="tool_use", name="propose_action", input=tool_input)
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: SimpleNamespace(content=[block])))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **_: client))
    monkeypatch.setattr(config, "STUB_LLM", False)


def test_a_refund_of_nothing_becomes_the_full_order_amount(monkeypatch):
    _model_replies(monkeypatch, action="refund", amount_cents=0, reason="damaged")
    proposal = agent.decide(ticket(amount=4200))
    assert (proposal.action, proposal.amount_cents) == ("refund", 4200)


def test_a_refund_is_never_more_than_the_order(monkeypatch):
    _model_replies(monkeypatch, action="refund", amount_cents=99999, reason="damaged")
    assert agent.decide(ticket(amount=4200)).amount_cents == 4200


def test_the_model_call_finishes_inside_the_lane2_activity_timeout():
    # The workflow gives run_agent AGENT_START_TO_CLOSE; the model client must give up before that.
    assert (agent.LLM_MAX_RETRIES + 1) * agent.LLM_TIMEOUT_S < AGENT_START_TO_CLOSE.total_seconds()
