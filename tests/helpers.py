"""Test helpers: a real service on a free port inside the test process, and polling instead of sleeping."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

import httpx
import uvicorn


def free_port() -> int:
    """A loopback port that is free right now. Another process can take it before the caller binds it, and then the
    server fails to start."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Uvicorn on a free port, on a daemon thread. `__enter__` waits for `/healthz` before the test uses the server.
    Keyword arguments go to `uvicorn.Config`, so `ssl_certfile` and `ssl_keyfile` serve HTTPS. `verify` is not passed
    on: it is how the readiness probe trusts a self-signed certificate."""

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
        """The base URL: https when TLS options were given, else http."""
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def __enter__(self):
        """Start the thread, then poll `/healthz` for about 5 s. Raise if the server never answers."""
        self.thread.start()
        for _ in range(100):
            try:
                httpx.get(f"{self.url}/healthz", timeout=0.5, verify=self.verify)
                return self
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        """Ask uvicorn to stop, then wait up to 5 s for its thread to finish."""
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
