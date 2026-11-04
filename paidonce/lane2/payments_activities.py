"""Payments team's activity: the one place the HTTPS call to the payments service happens."""

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from paidonce import config, tls
from paidonce.models import RefundRequest, RefundResult

RETRYABLE_4XX = frozenset({408, 429})  # "try later" responses: retried like a 5xx


@activity.defn
async def post_refund(req: RefundRequest) -> RefundResult:
    """Send one refund to the payments service and return the refund that payments stored.

    The key is `refund-<ticket_id>`, derived from the ticket, so every retry is the same request to the ledger. A
    replayed answer looks like a first answer, because the contract carries the refund only. A 4xx other than 408 and
    429 means payments refused the request, so it raises a non-retryable `ApplicationError`. Everything else, a timeout,
    a 408, a 429 or a 5xx, raises an ordinary error that Temporal retries under the workflow's `REFUND_RETRY`.
    """
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
    # A 4xx means payments understood the request and refused it: retrying cannot change that. Except "try
    # later" (408, 429), which is a transient condition like a 5xx.
    if 400 <= resp.status_code < 500 and resp.status_code not in RETRYABLE_4XX:
        raise ApplicationError(
            f"payments rejected the refund: {resp.status_code} {resp.text}",
            non_retryable=True,
        )
    resp.raise_for_status()  # 5xx and 408/429: let Temporal retry
    d = resp.json()
    # Whether the ledger answered from an existing key stays inside payments: the contract carries the refund only.
    return RefundResult(d["refund_id"], d["ticket_id"], d["amount_cents"])
