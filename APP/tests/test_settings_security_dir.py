from pathlib import Path
import sqlite3

import pytest

from app.core import Database, Settings
from security.integrity import IntegrityService


def test_settings_allow_operator_owned_security_directory(monkeypatch, tmp_path) -> None:
    security = tmp_path / "private-security"
    monkeypatch.setenv("TIANXIA_FOUNDRY_SECURITY_DIR", str(security))
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data")
    assert settings.security_dir == security.resolve()
    assert settings.db_path == (tmp_path / "data" / "foundry.sqlite3").resolve()
    integrity = IntegrityService.for_database(Database(settings))
    assert integrity.provider.directory == security.resolve()


def test_transaction_preserves_begin_failure_without_invalid_rollback() -> None:
    class FailingConnection:
        def __init__(self) -> None:
            self.statements = []
            self.closed = False

        def execute(self, statement: str):
            self.statements.append(statement)
            if statement == "BEGIN IMMEDIATE":
                raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            self.closed = True

    connection = FailingConnection()
    database = object.__new__(Database)
    database.connect = lambda: connection
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        with database.transaction():
            raise AssertionError("transaction body must not run")
    assert connection.statements == ["BEGIN IMMEDIATE"]
    assert connection.closed is True
