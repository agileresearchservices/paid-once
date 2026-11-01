"""Test helpers: a real service on a free port inside the test process, and polling instead of sleeping."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

import httpx
import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, app, **ssl_kwargs) -> None:
        self.port = free_port()
        self.scheme = "https" if ssl_kwargs else "http"
        self.verify = ssl_kwargs.pop("verify", True)  # how the readiness probe checks a self-signed certificate
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error", **ssl_kwargs)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            try:
                httpx.get(f"{self.url}/healthz", timeout=0.5, verify=self.verify)
                return self
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def drain(worker, max_jobs: int = 50) -> int:
    """Run queued jobs on the calling thread until none are visible."""
    n = 0
    while n < max_jobs and worker.run_one():
        n += 1
    return n


def wait_until(condition: Callable[[], object], timeout: float = 5.0, interval: float = 0.05) -> None:
    """Poll until `condition()` is truthy. A fixed sleep either wastes time or flakes on a loaded machine."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        time.sleep(interval)
