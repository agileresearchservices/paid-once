"""Plain data shared by both lanes. Dataclasses only, so Temporal can serialize them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LANES = ("lane1", "lane2")  # the two stacks, as they are named in the code, the ledger and ticket IDs
DEFAULT_ORDER_AGE_DAYS = 3  # a recent order: inside the 30-day return window


@dataclass
class Ticket:
    """One refund request from the helpdesk, with the order fields the policy rules read.

    The show harness builds these. Lane 1 posts the fields to its API and rebuilds one in its worker. Lane 2 passes
    one to the workflow. `agent.decide` reads it in both lanes.
    """

    ticket_id: str
    customer: str
    order_id: str
    amount_cents: int
    message: str  # customer-written, so untrusted: agent.py wraps it before the model reads it
    order_age_days: int = DEFAULT_ORDER_AGE_DAYS  # from the order system; the agent's return-window rule reads it


@dataclass
class Proposal:
    """The agent's recommendation for one ticket, made before any human looks at it.

    `agent.decide` returns it. Both lanes branch on `action`: a refund waits for approval, and a deny ends the ticket.
    """

    action: Literal["refund", "deny"]  # "refund" waits for a human; "deny" closes the ticket with no refund
    amount_cents: int  # 0 for a policy deny; a model deny keeps whatever amount the model sent
    reason: str


@dataclass
class RefundRequest:
    """What the support team sends to the payments team. The Nexus contract carries this."""

    ticket_id: str
    amount_cents: int


@dataclass
class RefundResult:
    """What payments returns for a committed refund.

    Lane 2 only. `post_refund` builds it from the HTTP reply, and the Nexus operation hands it back to
    `SupportTicketWorkflow`.
    """

    refund_id: str
    ticket_id: str
    amount_cents: int


@dataclass
class ApprovalDecision:
    """A human's answer to a proposed refund.

    The approver in the show sends it to `SupportTicketWorkflow` as the `approve` signal. Lane 1 takes the same
    answer through its API, so only Lane 2 uses this type.
    """

    approved: bool


@dataclass
class TicketOutcome:
    """Where one Lane 2 ticket ended, as `SupportTicketWorkflow` returns it to the show.

    `done` means refunded. `denied` means the agent's policy check or the model said no, and `rejected` means a human
    said no.
    """

    ticket_id: str
    status: Literal["done", "denied", "rejected"]  # done: refunded; denied: policy or model no; rejected: human no
    refund_id: str | None = None  # set only when done
    detail: str = ""  # why it was denied or rejected; empty when done
    events: list[str] = field(default_factory=list)  # a human-readable trail the workflow appends to
