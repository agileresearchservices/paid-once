"""The show server's guards: `make scenario` locks the controls, and a second server refuses to start."""

import socket

import pytest
import uvicorn
from fastapi.testclient import TestClient

from paidonce import config
from paidonce.show import server


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(config, "SCENARIO_TOKEN", "tok")


@pytest.mark.parametrize("path", ["/api/reset", "/api/scenes/intro/run", "/api/faults/kill/payments"])
def test_locked_server_refuses_controls_without_the_token(locked, path):
    # No lifespan runs here: the guard must answer before anything touches the engine.
    r = TestClient(server.app).post(path)
    assert r.status_code == 423
    assert "make scenario" in r.json()["detail"]


def test_locked_server_refuses_a_wrong_token(locked):
    r = TestClient(server.app).post("/api/reset", headers={server.SCENARIO_HEADER: "nope"})
    assert r.status_code == 423


def test_guard_lets_the_runner_through(locked):
    req = server.Request({"type": "http", "headers": [(server.SCENARIO_HEADER.encode(), b"tok")]})
    server.guard(req)  # does not raise


def test_guard_is_open_without_a_scenario(monkeypatch):
    monkeypatch.setattr(config, "SCENARIO_TOKEN", None)
    server.guard(server.Request({"type": "http", "headers": []}))  # does not raise


def test_second_server_refuses_to_start(monkeypatch):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        monkeypatch.setattr(config, "SHOW_PORT", busy.getsockname()[1])

        def must_not_run(*_, **__):
            raise AssertionError("uvicorn started on a busy port")

        monkeypatch.setattr(uvicorn, "run", must_not_run)
        with pytest.raises(SystemExit, match="already serving"):
            server.main()
