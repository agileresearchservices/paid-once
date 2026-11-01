"""The process manager: a killed process comes back, and nothing is started once shutdown has begun."""

import sys
import time

from paidonce.show.procs import Proc, ProcessManager


def _manager_with_one_process() -> tuple[ProcessManager, Proc, list]:
    events: list = []
    manager = ProcessManager(emit=lambda kind, msg, **extra: events.append((kind, extra.get("proc"))))
    proc = Proc("sleeper", "Sleeper", [sys.executable, "-c", "import time; time.sleep(60)"])
    manager.procs = {"sleeper": proc}
    manager._spawn(proc)
    return manager, proc, events


def test_a_killed_process_is_restarted_after_its_delay():
    manager, proc, events = _manager_with_one_process()
    try:
        assert manager.kill("sleeper", restart_after=5.0)
        proc.popen.wait(timeout=5)
        manager._restart_dead(time.time())  # too early: the delay has not passed
        assert proc.starts == 1
        manager._restart_dead(time.time() + 10)
        assert proc.starts == 2 and proc.popen.poll() is None
        assert events == [("kill", "sleeper"), ("restart", "sleeper")]
    finally:
        manager.stop_all()
        proc.popen.wait(timeout=5)


def test_nothing_is_restarted_once_shutdown_has_begun():
    manager, proc, _ = _manager_with_one_process()
    manager.stop_all()
    proc.popen.wait(timeout=5)
    manager._restart_dead(time.time() + 60)
    assert proc.starts == 1


def test_killing_a_process_that_is_not_running_does_nothing():
    manager, proc, events = _manager_with_one_process()
    manager.stop_all()
    proc.popen.wait(timeout=5)
    assert manager.kill("sleeper") is False
    assert events == []
