"""Plain data shared by both lanes. Dataclasses only, so Temporal can serialize them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LANES = ("lane1", "lane2")  # the two stacks, as they are named in the code, the ledger and ticket IDs
DEFAULT_ORDER_AGE_DAYS = 3  # a recent order: inside the 30-day return window


@dataclass
class Ticket:
    ticket_id: str
    customer: str
    order_id: str
    amount_cents: int
    message: str
    order_age_days: int = DEFAULT_ORDER_AGE_DAYS  # from the order system; the agent's return-window rule reads it


@dataclass
class Proposal:
    action: Literal["refund", "deny"]
    amount_cents: int
    reason: str


@dataclass
class RefundRequest:
    """What the support team sends to the payments team. The Nexus contract carries this."""

    ticket_id: str
    amount_cents: int


@dataclass
class RefundResult:
    refund_id: str
    ticket_id: str
    amount_cents: int


@dataclass
class ApprovalDecision:
    approved: bool


@dataclass
class TicketOutcome:
    ticket_id: str
    status: Literal["done", "denied", "rejected"]
    refund_id: str | None = None
    detail: str = ""
    events: list[str] = field(default_factory=list)
