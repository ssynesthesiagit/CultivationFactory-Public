"""A failed connection setup still owns and must release its SQLite handle."""
import sqlite3
from pathlib import Path

import pytest

from app.core import Database, Settings


class SetupStopped(BaseException):
    pass


class TrackedConnection(sqlite3.Connection):
    closed = False

    def close(self):
        self.closed = True
        return super().close()


def database(tmp_path):
    return Database(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path))


@pytest.mark.parametrize("statement", [
    "PRAGMA foreign_keys=ON", "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL", "PRAGMA busy_timeout=30000",
])
@pytest.mark.parametrize("failure_type", [sqlite3.OperationalError, SetupStopped])
def test_failed_setup_closes_handle_while_exception_is_retained(tmp_path, monkeypatch, statement, failure_type):
    db = database(tmp_path)
    opened = []
    original_connect = sqlite3.connect
    failure = failure_type("injected setup failure")

    class FailedSetup(TrackedConnection):
        def execute(self, sql, *args, **kwargs):
            if sql == statement:
                raise failure
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs, factory=FailedSetup)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with pytest.raises(failure_type) as retained:
            db.connect()
        assert retained.value is failure
        assert len(opened) == 1
        assert opened[0].closed
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")
    finally:
        for conn in opened:
            conn.close()


@pytest.mark.parametrize("entry", ["connection", "transaction"])
def test_real_locked_database_setup_is_closed_before_context_entry(tmp_path, monkeypatch, entry):
    db = database(tmp_path)
    original_connect = sqlite3.connect
    opened = []
    blocker = original_connect(db.settings.db_path, timeout=0, isolation_level=None)
    blocker.execute("CREATE TABLE existing(value INTEGER)")
    blocker.execute("BEGIN EXCLUSIVE")

    def connect(*args, **kwargs):
        kwargs["timeout"] = 0  # exercise the same lock failure without waiting 30 seconds
        conn = original_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked") as retained:
            with getattr(db, entry)():
                pytest.fail("setup must fail before yielding")
        assert retained.value.__traceback__ is not None
        assert len(opened) == 1
        assert opened[0].closed
    finally:
        blocker.close()
        for conn in opened:
            conn.close()


def test_successful_connection_retains_configuration_and_caller_ownership(tmp_path):
    conn = database(tmp_path).connect()
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert conn.execute("SELECT 1 AS value").fetchone()["value"] == 1
    finally:
        conn.close()
