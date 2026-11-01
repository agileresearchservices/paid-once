"""Tiny SQLite helper. One short-lived connection per call keeps multi-process use simple."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from paidonce import config

BUSY_TIMEOUT_S = 30  # how long a writer waits for the file lock before giving up

_schemas_made: set[tuple[Path, str]] = set()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    config.ensure_data_dir()
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection inside one write transaction: it takes the write lock up front, commits when the block ends
    (a `return` inside the block included) and rolls back if the block raises."""
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def ensure_schema(path: Path, schema: str) -> None:
    """Create the tables in `path` the first time this process asks, and again if the file has been deleted."""
    key = (path, schema)
    if key in _schemas_made and path.exists():
        return
    with connect(path) as conn:
        conn.executescript(schema)
    _schemas_made.add(key)
