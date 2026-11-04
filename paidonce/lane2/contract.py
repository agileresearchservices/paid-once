"""The Nexus contract between the support team and the payments team.

This is all the support side knows about payments: one operation, one endpoint. It does not know
the payments namespace, task queue or workflow type behind it. Sandbox-safe: no I/O at import.
"""

import nexusrpc

from paidonce.models import RefundRequest, RefundResult

# The name support calls. client.py points it at the payments namespace and task queue.
NEXUS_ENDPOINT = "payments-endpoint"


@nexusrpc.service
class PaymentsService:
    """The one operation payments offers: `issue_refund`, from a `RefundRequest` to a `RefundResult`.

    Those two types are the only things that cross the team boundary. `SupportTicketWorkflow` calls the
    operation, and `PaymentsServiceHandler` implements it on the payments side.
    """

    issue_refund: nexusrpc.Operation[RefundRequest, RefundResult]
