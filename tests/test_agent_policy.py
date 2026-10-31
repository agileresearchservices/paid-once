import pytest

from paidonce import agent
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
