"""Process manager: starts every service and lets the raccoon kill them.

This is the demo's stand-in for Kubernetes. A killed process comes back after a short delay,
the way a restarted pod would.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from raccoon import config


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


@dataclass
class Proc:
    name: str
    label: str
    cmd: list[str]
    popen: subprocess.Popen | None = None
    restart_at: float | None = None
    starts: int = 0
    kills: int = 0
    external: bool = False  # not ours to start or kill (e.g. a Temporal server already running)
    started_at: float = 0.0
    log: list[str] = field(default_factory=list)


class ProcessManager:
    def __init__(self, emit=lambda *a, **k: None) -> None:
        self.emit = emit
        py = sys.executable
        self.procs: dict[str, Proc] = {
            "payments": Proc("payments", "Payments service", [py, "-m", "raccoon.payments"]),
            "lane1_api": Proc("lane1_api", "Lane 1 API", [py, "-m", "raccoon.lane1.api"]),
            "lane1_worker": Proc("lane1_worker", "Lane 1 worker", [py, "-m", "raccoon.lane1.worker"]),
            "support_worker": Proc(
                "support_worker",
                "Support worker (Temporal)",
                [py, "-m", "raccoon.lane2.support_worker"],
            ),
            "payments_worker": Proc(
                "payments_worker",
                "Payments worker + Nexus handler",
                [py, "-m", "raccoon.lane2.payments_worker"],
            ),
        }
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self.temporal: subprocess.Popen | None = None

    # -- lifecycle ---------------------------------------------------------
    def ensure_temporal(self) -> str:
        port = config.TEMPORAL_ADDRESS.rpartition(":")[2]
        if port_open(int(port)):
            return "using the Temporal server already running on " + config.TEMPORAL_ADDRESS
        exe = shutil.which("temporal")
        if exe is None:
            raise RuntimeError(
                f"No Temporal server on {config.TEMPORAL_ADDRESS} and no `temporal` CLI on PATH (brew install temporal)."
            )
        config.ensure_data_dir()
        self.temporal = subprocess.Popen(
            [
                exe,
                "server",
                "start-dev",  # with its Web UI: the demo links both namespaces from the Nexus panel
                "--port",
                port,
                "--db-filename",
                str(config.DATA_DIR / "temporal.db"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            if port_open(int(port)):
                time.sleep(1.5)
                return "started a Temporal dev server"
            time.sleep(0.5)
        raise RuntimeError("Temporal dev server did not start")

    def _spawn(self, p: Proc) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        p.popen = subprocess.Popen(
            p.cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        p.starts += 1
        p.started_at = time.time()
        p.restart_at = None

    def start_all(self) -> None:
        for p in self.procs.values():
            self._spawn(p)
        self._thread.start()

    def stop_all(self) -> None:
        self._stop.set()
        for p in self.procs.values():
            self._terminate(p)
        if self.temporal is not None:
            self.temporal.terminate()

    @staticmethod
    def _terminate(p: Proc) -> None:
        if p.popen and p.popen.poll() is None:
            try:
                os.killpg(p.popen.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    # -- chaos -------------------------------------------------------------
    def kill(self, name: str, restart_after: float = 4.0) -> bool:
        """kill -9 a process. It comes back after `restart_after` seconds."""
        p = self.procs[name]
        if p.popen is None or p.popen.poll() is not None:
            return False
        try:
            os.killpg(p.popen.pid, signal.SIGKILL)
        except ProcessLookupError:
            return False
        p.kills += 1
        p.restart_at = time.time() + restart_after
        self.emit("kill", f"kill -9 {p.label}", proc=name)
        return True

    def _watch(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            for p in self.procs.values():
                dead = p.popen is None or p.popen.poll() is not None
                if dead and p.restart_at is None:
                    p.restart_at = now + 2.0  # an unplanned exit: restart like an orchestrator would
                if dead and p.restart_at is not None and now >= p.restart_at:
                    self._spawn(p)
                    self.emit("restart", f"{p.label} restarted", proc=name_of(p))
            time.sleep(0.25)

    # -- views -------------------------------------------------------------
    def status(self) -> dict:
        out = {}
        for name, p in self.procs.items():
            alive = p.popen is not None and p.popen.poll() is None
            out[name] = {
                "label": p.label,
                "alive": alive,
                "starts": p.starts,
                "kills": p.kills,
            }
        return out

    def wait_ready(self, timeout: float = 60.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if port_open(config.PAYMENTS_PORT) and port_open(config.LANE1_PORT):
                return True
            time.sleep(0.3)
        return False


def name_of(p: Proc) -> str:
    return p.name
