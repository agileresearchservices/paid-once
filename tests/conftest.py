import importlib

import pytest


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own SQLite files and the stub model."""
    monkeypatch.setenv("RACCOON_DATA", str(tmp_path))
    monkeypatch.setenv("RACCOON_STUB_LLM", "1")
    from raccoon import config

    importlib.reload(config)
    # Modules that copied config values at import time need the reloaded module.
    for name in ("raccoon.db", "raccoon.audit", "raccoon.payments.ledger"):
        importlib.reload(importlib.import_module(name))
    yield
