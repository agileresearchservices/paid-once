"""Process manager: starts every service and lets the fault injector kill them.

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
from dataclasses import dataclass

from paidonce import config


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """True when something accepts a TCP connection on `host:port`, within a short timeout. It does not say which
    program answered. Readiness checks use it, and so do the Temporal check and the guard against a second show."""
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


@dataclass
class Proc:
    """One child process the manager runs. `ProcessManager` creates these, and only its methods change `popen` and the
    restart fields."""

    name: str  # the key in `ProcessManager.procs`; fault events and the page's diagram use the same name
    label: str
    cmd: list[str]
    popen: subprocess.Popen | None = None  # the running child, or None before its first start
    restart_at: float | None = None  # None = not scheduled; an unplanned exit gets one from the watcher
    starts: int = 0  # how many times it has been spawned, the first start included


class ProcessManager:
    """Runs the show's services as child processes, and kills and restarts them on request.

    It owns five services (payments, the Lane 1 API and worker, the support and payments workers), plus the Temporal
    dev server when `ensure_temporal` starts one. Each child runs in its own session, so a kill or a stop reaches
    everything the child started, not only the child itself. A watcher thread restarts whatever has died."""

    def __init__(self, emit=lambda *a, **k: None) -> None:
        """`emit(kind, msg, **fields)` receives the kill, restart and watcher-error events. The default discards them;
        `Engine` replaces it, so the page's event log shows them."""
        self.emit = emit
        py = sys.executable
        self.procs: dict[str, Proc] = {
            "payments": Proc("payments", "Payments service", [py, "-m", "paidonce.payments"]),
            "lane1_api": Proc("lane1_api", "Queue API", [py, "-m", "paidonce.lane1.api"]),
            "lane1_worker": Proc("lane1_worker", "Queue worker", [py, "-m", "paidonce.lane1.worker"]),
            "support_worker": Proc(
                "support_worker",
                "Support team worker",
                [py, "-m", "paidonce.lane2.support_worker"],
            ),
            "payments_worker": Proc(
                "payments_worker",
                "Payments team worker + Nexus handler",
                [py, "-m", "paidonce.lane2.payments_worker"],
            ),
        }
        self._stop = threading.Event()
        self._lock = threading.Lock()  # the watcher thread restarts processes while the loop kills and stops them
        self._thread = threading.Thread(target=self._watch, daemon=True)

    # -- lifecycle ---------------------------------------------------------
    def ensure_temporal(self) -> str:
        """Start a Temporal dev server, unless one is already listening. Only one we started can be killed: a server
        someone else runs is not ours to kill, so it never appears as a process here."""
        port = config.TEMPORAL_ADDRESS.rpartition(":")[2]
        if port_open(int(port)):
            return "using the Temporal server already running on " + config.TEMPORAL_ADDRESS
        exe = shutil.which("temporal")
        if exe is None:
            raise RuntimeError(
                f"No Temporal server on {config.TEMPORAL_ADDRESS} and no `temporal` CLI on PATH "
                "(brew install temporal)."
            )
        config.ensure_data_dir()
        # The SQLite file is what lets the server die and come back with every workflow where it was.
        cmd = [
            exe,
            "server",
            "start-dev",  # with its Web UI (:8233), for opening both namespaces by hand during Q&A
            "--port",
            port,
            "--db-filename",
            str(config.DATA_DIR / "temporal.db"),
        ]
        temporal = Proc("temporal", "Temporal server", cmd)
        self._spawn(temporal)
        self.procs["temporal"] = temporal
        for _ in range(60):
            if port_open(int(port)):
                time.sleep(1.5)
                return "started a Temporal dev server"
            time.sleep(0.5)
        raise RuntimeError("Temporal dev server did not start")

    @property
    def owns_temporal(self) -> bool:
        """True when this manager started the Temporal server, and so may kill it. Someone else's server is not ours."""
        return "temporal" in self.procs

    def _spawn(self, p: Proc) -> None:
        """Start `p` in its own session, so `os.killpg` reaches its whole group, and discard its output.
        `PYTHONUNBUFFERED` is set anyway, so a child whose output is sent to a log file while debugging keeps its last
        lines through a kill -9."""
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        p.popen = subprocess.Popen(
            p.cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        p.starts += 1
        p.restart_at = None

    def start_all(self) -> None:
        """Start every service that is not running yet, then the watcher thread. A Temporal server that is already up
        (ours, from `ensure_temporal`) is skipped."""
        for p in self.procs.values():
            if p.popen is None:  # Temporal, if ours, is already up
                self._spawn(p)
        self._thread.start()

    def stop_all(self) -> None:
        """SIGTERM every child's process group. The stop flag is set first, under the lock, so the watcher starts
        nothing while they exit. It does not wait for them to exit."""
        with self._lock:  # after this, the watcher can no longer start anything
            self._stop.set()
            for p in self.procs.values():
                self._terminate(p)

    @staticmethod
    def _terminate(p: Proc) -> None:
        """SIGTERM the process group of `p`, if it is still running. A group that has already gone is not an error."""
        if p.popen and p.popen.poll() is None:
            try:
                os.killpg(p.popen.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    # -- chaos -------------------------------------------------------------
    def kill(self, name: str, restart_after: float = 4.0) -> bool:
        """kill -9 a process. It comes back after `restart_after` seconds."""
        p = self.procs[name]
        with self._lock:
            if p.popen is None or p.popen.poll() is not None:
                return False
            try:
                os.killpg(p.popen.pid, signal.SIGKILL)
            except ProcessLookupError:
                return False
            p.restart_at = time.time() + restart_after
        self.emit("kill", f"kill -9 {p.label}", proc=name)
        return True

    def _watch(self) -> None:
        """The watcher thread's body: restart the dead every 0.25 s until `stop_all` sets the stop flag. An error is
        reported as an event, and the loop goes on."""
        while not self._stop.is_set():
            try:
                self._restart_dead(time.time())
            except Exception as exc:  # the watcher is the only thing that restarts a process: it must not die
                self.emit("error", f"process watcher: {exc!r}"[:160])
            time.sleep(0.25)

    def _restart_dead(self, now: float) -> None:
        """Restart each dead child whose `restart_at` has passed.

        A planned kill sets `restart_at` itself, with the delay its caller chooses. An unplanned exit gets `now + 2.0`
        here, the way an orchestrator restarts a crashed pod. Nothing restarts once the stop flag is set."""
        restarted = []
        with self._lock:
            if self._stop.is_set():
                return
            for p in self.procs.values():
                dead = p.popen is None or p.popen.poll() is not None
                if dead and p.restart_at is None:
                    p.restart_at = now + 2.0  # an unplanned exit: restart like an orchestrator would
                if dead and p.restart_at is not None and now >= p.restart_at:
                    self._spawn(p)
                    restarted.append(p)
        for p in restarted:
            self.emit("restart", f"{p.label} restarted", proc=p.name)

    # -- views -------------------------------------------------------------
    def status(self) -> dict:
        """The label, liveness and start count of each service. The snapshot carries it as `processes`, which the
        page reads."""
        out = {}
        for name, p in self.procs.items():
            alive = p.popen is not None and p.popen.poll() is None
            out[name] = {
                "label": p.label,
                "alive": alive,
                "starts": p.starts,
            }
        return out

    def wait_ready(self, timeout: float = 60.0) -> bool:
        """Poll until the payments and Lane 1 API ports both accept connections, or `timeout` seconds pass.

        Returns False on timeout. The workers listen on no port, so this does not wait for them."""
        end = time.time() + timeout
        while time.time() < end:
            if port_open(config.PAYMENTS_PORT) and port_open(config.LANE1_PORT):
                return True
            time.sleep(0.3)
        return False
