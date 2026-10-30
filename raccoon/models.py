"""Plain data shared by both lanes. Dataclasses only, so Temporal can serialize them."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ticket:
    ticket_id: str
    customer: str
    order_id: str
    amount_cents: int
    message: str


@dataclass
class Proposal:
    action: str  # "refund" or "deny"
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
    replayed: bool = False


@dataclass
class ApprovalDecision:
    approved: bool
    approver: str = "human"


@dataclass
class TicketOutcome:
    ticket_id: str
    status: str
    refund_id: str | None = None
    detail: str = ""
    events: list[str] = field(default_factory=list)
