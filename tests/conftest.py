"""The fixtures every test gets: isolated SQLite files under a temp dir, and the stub model. `payments` adds a real
payments service on a free port, for a test that asks for one."""

import importlib

import pytest


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own SQLite files and the stub model."""
    monkeypatch.setenv("PAIDONCE_DATA", str(tmp_path))
    monkeypatch.setenv("PAIDONCE_STUB_LLM", "1")
    from paidonce import config

    importlib.reload(config)
    # Reloaded as well, so nothing in them can hold a value copied from config before the env was set.
    for name in ("paidonce.db", "paidonce.audit", "paidonce.payments.ledger"):
        importlib.reload(importlib.import_module(name))
    yield


@pytest.fixture
def payments(monkeypatch):
    """The real payments service on a free port, with callers pointed at it and a short client timeout."""
    from paidonce import config
    from paidonce.payments.service import app
    from tests.helpers import Server

    with Server(app) as srv:
        monkeypatch.setattr(config, "PAYMENTS_URL", srv.url)
        monkeypatch.setattr(config, "PAYMENTS_CLIENT_TIMEOUT_S", 1.0)
        yield srv
