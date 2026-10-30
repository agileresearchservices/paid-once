"""The Nexus contract between the support team and the payments team.

This is all the support side knows about payments: one operation, one endpoint. It does not know
the payments namespace, task queue or workflow type behind it. Sandbox-safe: no I/O at import.
"""

import nexusrpc

from raccoon.models import RefundRequest, RefundResult

NEXUS_ENDPOINT = "payments-endpoint"  # mirrored in raccoon/config.py


@nexusrpc.service
class PaymentsService:
    issue_refund: nexusrpc.Operation[RefundRequest, RefundResult]
