"""The SQLite helpers: write transactions, and the schema being made once."""

import pytest

from paidonce import config, db


def _make(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS t (n INTEGER)")


def test_a_transaction_commits_when_the_block_ends_or_returns():
    with db.connect(config.AUDIT_DB) as conn:
        _make(conn)

    def write_and_return():
        with db.transaction(config.AUDIT_DB) as conn:
            conn.execute("INSERT INTO t VALUES (1)")
            return "early"

    assert write_and_return() == "early"
    with db.connect(config.AUDIT_DB) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_a_transaction_rolls_back_when_the_block_raises():
    with db.connect(config.AUDIT_DB) as conn:
        _make(conn)
    with pytest.raises(RuntimeError), db.transaction(config.AUDIT_DB) as conn:
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    with db.connect(config.AUDIT_DB) as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_the_schema_is_made_again_if_the_database_file_is_deleted():
    schema = "CREATE TABLE IF NOT EXISTS t (n INTEGER);"
    db.ensure_schema(config.AUDIT_DB, schema)
    for suffix in ("", "-wal", "-shm"):
        config.AUDIT_DB.with_name(config.AUDIT_DB.name + suffix).unlink(missing_ok=True)
    db.ensure_schema(config.AUDIT_DB, schema)
    with db.connect(config.AUDIT_DB) as conn:
        conn.execute("SELECT * FROM t")  # raises if the table is missing
