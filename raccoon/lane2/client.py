"""Temporal connection and one-time setup: the two namespaces and the Nexus endpoint."""

from __future__ import annotations

import asyncio
import time

from google.protobuf.duration_pb2 import Duration
from temporalio.api.nexus.v1 import EndpointSpec, EndpointTarget
from temporalio.api.operatorservice.v1 import CreateNexusEndpointRequest
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from raccoon import config
from raccoon.lane2.contract import NEXUS_ENDPOINT


async def connect(namespace: str) -> Client:
    return await Client.connect(config.TEMPORAL_ADDRESS, namespace=namespace)


async def _wait_usable(client: Client, namespace: str, timeout_s: float = 15.0) -> None:
    """A fresh namespace takes a moment on the dev server before workers can use it."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=namespace))
            return
        except RPCError:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.5)


async def _ensure_setup() -> list[str]:
    lines: list[str] = []
    client = await connect("default")
    for ns in (config.SUPPORT_NAMESPACE, config.PAYMENTS_NAMESPACE):
        try:
            await client.workflow_service.register_namespace(
                RegisterNamespaceRequest(
                    namespace=ns,
                    workflow_execution_retention_period=Duration(seconds=86400),
                )
            )
            lines.append(f"namespace {ns}: created")
        except RPCError as e:
            if e.status != RPCStatusCode.ALREADY_EXISTS:
                raise
            lines.append(f"namespace {ns}: already there")
        await _wait_usable(client, ns)
    try:
        await client.operator_service.create_nexus_endpoint(
            CreateNexusEndpointRequest(
                spec=EndpointSpec(
                    name=NEXUS_ENDPOINT,
                    target=EndpointTarget(
                        worker=EndpointTarget.Worker(
                            namespace=config.PAYMENTS_NAMESPACE,
                            task_queue=config.PAYMENTS_TASK_QUEUE,
                        )
                    ),
                )
            )
        )
        lines.append(
            f"nexus endpoint {NEXUS_ENDPOINT}: created -> {config.PAYMENTS_NAMESPACE}/{config.PAYMENTS_TASK_QUEUE}"
        )
    except RPCError as e:
        if e.status != RPCStatusCode.ALREADY_EXISTS:
            raise
        lines.append(f"nexus endpoint {NEXUS_ENDPOINT}: already there")
    return lines


def ensure_setup() -> list[str]:
    """Idempotent. Sync so the show server can run it with asyncio.to_thread."""
    return asyncio.run(_ensure_setup())


if __name__ == "__main__":
    for line in ensure_setup():
        print(line)
