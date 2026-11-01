"""Payments team's activity: the one place the HTTPS call to the payments service happens."""

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from paidonce import config, tls
from paidonce.models import RefundRequest, RefundResult


@activity.defn
async def post_refund(req: RefundRequest) -> RefundResult:
    # Same client timeout as Lane 1, so the comparison is fair. The difference is the key: it is
    # derived from the ticket, so every retry of this activity (or of the whole workflow) is the
    # same request as far as the ledger is concerned.
    async with httpx.AsyncClient(timeout=config.PAYMENTS_CLIENT_TIMEOUT_S, verify=tls.client_verify()) as client:
        resp = await client.post(
            f"{config.PAYMENTS_URL}/refunds",
            json={"ticket_id": req.ticket_id, "amount_cents": req.amount_cents},
            headers={
                "Idempotency-Key": f"refund-{req.ticket_id}",
                "X-Lane": "lane2",
            },
        )
    if 400 <= resp.status_code < 500:
        raise ApplicationError(
            f"payments rejected the refund: {resp.status_code} {resp.text}",
            non_retryable=True,
        )
    resp.raise_for_status()  # 5xx: let Temporal retry
    d = resp.json()
    # Whether the ledger answered from an existing key stays inside payments: the contract carries the refund only.
    return RefundResult(d["refund_id"], d["ticket_id"], d["amount_cents"])
