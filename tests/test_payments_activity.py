"""Lane 2's post_refund: which payments answers Temporal should retry, and which it should give up on."""

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from paidonce import config
from paidonce.lane2 import payments_activities
from paidonce.models import RefundRequest


def _payments_answers(monkeypatch, status: int, body: dict | None = None) -> None:
    monkeypatch.setattr(config, "PAYMENTS_URL", "http://payments.test")  # plain http: no certificate to trust
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body or {}))
    real = httpx.AsyncClient
    monkeypatch.setattr(payments_activities.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))


async def test_a_refund_payments_accepts_returns_the_contract_fields(monkeypatch):
    _payments_answers(monkeypatch, 200, {"refund_id": "r1", "ticket_id": "t1", "amount_cents": 2500, "replayed": True})
    result = await payments_activities.post_refund(RefundRequest("t1", 2500))
    assert (result.refund_id, result.ticket_id, result.amount_cents) == ("r1", "t1", 2500)


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_a_refusal_is_final(monkeypatch, status):
    _payments_answers(monkeypatch, status)
    with pytest.raises(ApplicationError) as err:
        await payments_activities.post_refund(RefundRequest("t1", 2500))
    assert err.value.non_retryable


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_a_try_later_or_a_server_error_is_retried(monkeypatch, status):
    _payments_answers(monkeypatch, status)
    with pytest.raises(httpx.HTTPStatusError):
        await payments_activities.post_refund(RefundRequest("t1", 2500))
