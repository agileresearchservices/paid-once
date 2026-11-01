"""The show server's guards: `make scenario` locks the controls, and a second server refuses to start."""

import socket

import pytest
import uvicorn
from fastapi import HTTPException
from fastapi.testclient import TestClient

from paidonce import config
from paidonce.show import server


@pytest.fixture(autouse=True)
def locked(monkeypatch):
    monkeypatch.setattr(config, "SCENARIO_TOKEN", "tok")


@pytest.mark.parametrize("path", ["/api/reset", "/api/scenes/intro/run", "/api/faults/kill/payments"])
def test_locked_server_refuses_controls_without_the_token(path):
    # No lifespan runs here: the guard must answer before anything touches the engine.
    r = TestClient(server.app).post(path)
    assert r.status_code == 423
    assert "make scenario" in r.json()["detail"]


def test_locked_server_refuses_a_wrong_token():
    r = TestClient(server.app).post("/api/reset", headers={server.SCENARIO_HEADER: "nope"})
    assert r.status_code == 423


def test_guard_lets_the_runner_through():
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


@pytest.fixture
def ui_dist(tmp_path):
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<html>app</html>")
    (tmp_path / "ui" / "logo.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for the browser")
    return tmp_path / "ui"


def test_the_page_serves_its_files_and_falls_back_to_index_for_in_page_routes(ui_dist):
    assert server.spa_response(ui_dist, "logo.svg").path == ui_dist / "logo.svg"
    assert server.spa_response(ui_dist, "").path == ui_dist / "index.html"
    assert server.spa_response(ui_dist, "anything-the-router-knows").path == ui_dist / "index.html"


@pytest.mark.parametrize("path", ["../secret.txt", "a/../../secret.txt", "%2e%2e/secret.txt", "/etc/passwd"])
def test_the_page_never_serves_a_file_outside_its_folder(ui_dist, path):
    assert server.spa_response(ui_dist, path).path == ui_dist / "index.html"


@pytest.mark.parametrize("path", ["api/typo", "api/state/extra", "brand/favicon.svg"])
def test_a_missing_api_path_or_brand_file_is_a_404_not_the_page(ui_dist, path):
    with pytest.raises(HTTPException) as err:
        server.spa_response(ui_dist, path)
    assert err.value.status_code == 404
