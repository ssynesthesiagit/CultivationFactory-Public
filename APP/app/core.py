from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

APP_VERSION = "0.6.6.9.2-CAT2-CANONICAL-CATALOG"
APP_STATUS = "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY_COMBATANT_LIBRARY_PRE_ENCOUNTER"
CORE_PACK_ID = "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2"
CORE_PACK_VERSION = "2.9.3"
EXPECTED_FACTORY_HASH = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
from app.authorities import GM_SCREEN_SHA256
EXPECTED_GM_SCREEN_HASH = GM_SCREEN_SHA256
FACTORY_VERSION = "HF05ZVK-R1H"
CANDIDATE_SCHEMA_VERSION = "HF05ZVK-R1F"
GM_SCREEN_VERSION = "HF05ZUI-R2K.3-HF3-W1"
CATALOG_GM_COMPATIBILITY_VERSION = "HF05ZUI-R2K.3-HF3"


def utcnow() -> str:
    deterministic = os.environ.get("TIANXIA_DETERMINISTIC_UTC")
    if deterministic:
        return deterministic
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    db_path: Path
    inbox_dir: Path
    exports_dir: Path
    packs_dir: Path
    vendor_dir: Path
    logs_dir: Path
    backups_dir: Path
    security_dir: Path
    factory_zip: Path | None = None
    fixture_path: Path | None = None

    @classmethod
    def from_env(cls, root_dir: Path | None = None, data_dir: Path | None = None) -> "Settings":
        root = Path(root_dir or Path(__file__).resolve().parents[1]).resolve()
        data = Path(data_dir or os.getenv("TIANXIA_FOUNDRY_DATA", root / "runtime_data")).resolve()
        factory = os.getenv("TIANXIA_FACTORY_ZIP")
        fixture = os.getenv("TIANXIA_FACTORY_FIXTURE")
        return cls(
            root_dir=root,
            data_dir=data,
            db_path=data / "foundry.sqlite3",
            inbox_dir=data / "inbox",
            exports_dir=data / "exports",
            packs_dir=data / "content_packs",
            vendor_dir=data / "vendor",
            logs_dir=data / "logs",
            backups_dir=data / "backups",
            security_dir=data / "security",
            factory_zip=Path(factory).resolve() if factory else None,
            fixture_path=Path(fixture).resolve() if fixture else None,
        )

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.inbox_dir,
            self.exports_dir,
            self.packs_dir,
            self.vendor_dir,
            self.logs_dir,
            self.backups_dir,
            self.security_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


class FoundryError(Exception):
    def __init__(self, code: str, message: str, *, details: Any = None, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_dirs()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _split_sql_script(text: str) -> list[str]:
        statements: list[str] = []
        buffer = ""
        for line in text.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                buffer = ""
                if statement and not statement.startswith("--"):
                    statements.append(statement)
                elif statement:
                    # Comments may precede a real statement. Keep the non-comment suffix.
                    stripped = "\n".join(row for row in statement.splitlines() if not row.lstrip().startswith("--")).strip()
                    if stripped:
                        statements.append(stripped)
        if buffer.strip():
            raise RuntimeError("Incomplete SQL statement in migration script")
        return statements

    @staticmethod
    def _normalize_sql(value: str) -> str:
        value = re.sub(r"--[^\n]*", " ", value or "")
        value = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip().rstrip(";")
        return value.casefold()

    @staticmethod
    def _alter_add_column(statement: str) -> tuple[str, str, str] | None:
        match = re.match(r'\s*ALTER\s+TABLE\s+([\w"]+)\s+ADD\s+COLUMN\s+([\w"]+)\s+(.+?)\s*;?\s*$', statement, re.I | re.S)
        if not match:
            return None
        return tuple(part.strip('"') for part in match.groups())  # type: ignore[return-value]

    @staticmethod
    def _default_normalized(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        while len(text) >= 2 and text[0] == "(" and text[-1] == ")":
            text = text[1:-1].strip()
        return text.casefold()

    def _verify_or_skip_existing_column(self, conn: sqlite3.Connection, statement: str) -> bool:
        parsed = self._alter_add_column(statement)
        if not parsed:
            return False
        table, column, definition = parsed
        rows = {row[1]: row for row in conn.execute(f'PRAGMA table_info("{table}")')}
        if column not in rows:
            return False
        row = rows[column]
        expected_type_match = re.match(r"([A-Za-z0-9_]+)", definition)
        expected_type = expected_type_match.group(1).upper() if expected_type_match else ""
        expected_notnull = bool(re.search(r"\bNOT\s+NULL\b", definition, re.I))
        default_match = re.search(r"\bDEFAULT\s+(.+?)(?:\s+CHECK\b|\s+REFERENCES\b|$)", definition, re.I | re.S)
        expected_default = self._default_normalized(default_match.group(1)) if default_match else None
        actual = {"type": str(row[2] or "").upper(), "notnull": bool(row[3]), "default": self._default_normalized(row[4])}
        expected = {"type": expected_type, "notnull": expected_notnull, "default": expected_default}
        if actual != expected:
            raise FoundryError(
                "MIGRATION_NONCONVERGENT_SCHEMA",
                "A partially applied migration contains a column with the wrong shape.",
                details={"table": table, "column": column, "expected": expected, "actual": actual},
                status_code=500,
            )
        return True

    def _ensure_migration_journal(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migration_journal(
               version TEXT PRIMARY KEY, script_sha256 TEXT NOT NULL, status TEXT NOT NULL,
               next_statement_index INTEGER NOT NULL, statement_count INTEGER NOT NULL,
               backup_path TEXT, started_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_json TEXT)"""
        )

    def restore_migration_backup(self, version: str) -> Path:
        with self.connection() as conn:
            self._ensure_migration_journal(conn)
            row = conn.execute("SELECT backup_path FROM schema_migration_journal WHERE version=?", (version,)).fetchone()
        if not row or not row[0]:
            raise FoundryError("MIGRATION_BACKUP_NOT_FOUND", "No durable pre-migration backup is recorded.", details={"version": version}, status_code=404)
        backup = Path(row[0])
        if not backup.is_file():
            raise FoundryError("MIGRATION_BACKUP_NOT_FOUND", "The recorded pre-migration backup is missing.", details={"version": version, "path": str(backup)}, status_code=404)
        failed = self.settings.backups_dir / f"failed_before_restore_{Path(version).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        if self.settings.db_path.exists():
            shutil.copy2(self.settings.db_path, failed)
        temporary = self.settings.db_path.with_name(self.settings.db_path.name + ".restore")
        shutil.copy2(backup, temporary)
        os.replace(temporary, self.settings.db_path)
        return backup

    def migrate(self) -> None:
        migrations = sorted((self.settings.root_dir / "migrations").glob("*.sql"))
        with self.connection() as conn:
            self._ensure_migration_journal(conn)
        for path in migrations:
            script = path.read_text(encoding="utf-8")
            script_hash = sha256_text(script)
            statements = self._split_sql_script(script)
            with self.connection() as conn:
                self._ensure_migration_journal(conn)
                applied = conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (path.name,)).fetchone()
                journal = conn.execute("SELECT * FROM schema_migration_journal WHERE version=?", (path.name,)).fetchone()
                if applied:
                    # A crash after the atomic marker transaction may leave an old
                    # journal view only on filesystems/backups restored at different
                    # WAL boundaries.  Reconcile only when the complete script identity
                    # and every statement boundary are already durable.
                    if journal is not None:
                        if journal["script_sha256"] != script_hash or int(journal["statement_count"]) != len(statements):
                            raise FoundryError("MIGRATION_SCRIPT_CHANGED", "An applied migration marker disagrees with its durable journal.", details={"version": path.name}, status_code=500)
                        if int(journal["next_statement_index"]) != len(statements):
                            raise FoundryError("MIGRATION_MARKER_PREMATURE", "A migration is marked applied before every journaled statement boundary.", details={"version": path.name}, status_code=500)
                        if journal["status"] != "applied":
                            conn.execute(
                                "UPDATE schema_migration_journal SET status='applied',updated_at=?,error_json=NULL WHERE version=?",
                                (utcnow(), path.name),
                            )
                    continue
                if journal and (journal["script_sha256"] != script_hash or int(journal["statement_count"]) != len(statements)):
                    raise FoundryError("MIGRATION_SCRIPT_CHANGED", "A migration changed after an interrupted application.", details={"version": path.name}, status_code=500)
                if journal is None:
                    backup = self.settings.backups_dir / f"pre_migration_{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
                    if self.settings.db_path.exists() and self.settings.db_path.stat().st_size:
                        src = sqlite3.connect(self.settings.db_path)
                        dst = sqlite3.connect(backup)
                        src.backup(dst); dst.close(); src.close()
                    now = utcnow()
                    conn.execute(
                        "INSERT INTO schema_migration_journal(version,script_sha256,status,next_statement_index,statement_count,backup_path,started_at,updated_at,error_json) VALUES(?,?,?,?,?,?,?,?,NULL)",
                        (path.name, script_hash, "in_progress", 0, len(statements), str(backup) if backup.exists() else None, now, now),
                    )
                    next_index = 0
                else:
                    next_index = int(journal["next_statement_index"])
            for index in range(next_index, len(statements)):
                statement = statements[index]
                try:
                    with self.transaction() as conn:
                        self._ensure_migration_journal(conn)
                        journal = conn.execute("SELECT * FROM schema_migration_journal WHERE version=?", (path.name,)).fetchone()
                        if not journal or int(journal["next_statement_index"]) != index:
                            raise FoundryError("MIGRATION_JOURNAL_DIVERGED", "The migration journal does not match the next DDL boundary.", details={"version": path.name, "expected_index": index}, status_code=500)
                        skipped = self._verify_or_skip_existing_column(conn, statement)
                        if not skipped:
                            conn.execute(statement)
                        conn.execute(
                            "UPDATE schema_migration_journal SET next_statement_index=?,updated_at=?,status='in_progress',error_json=NULL WHERE version=?",
                            (index + 1, utcnow(), path.name),
                        )
                except Exception as exc:
                    with self.connection() as conn:
                        self._ensure_migration_journal(conn)
                        conn.execute(
                            "UPDATE schema_migration_journal SET status='failed',updated_at=?,error_json=? WHERE version=?",
                            (utcnow(), canonical_json({"type": type(exc).__name__, "message": str(exc), "statement_index": index}), path.name),
                        )
                    raise
            with self.transaction() as conn:
                journal = conn.execute("SELECT * FROM schema_migration_journal WHERE version=?", (path.name,)).fetchone()
                if not journal or int(journal["next_statement_index"]) != len(statements):
                    raise FoundryError("MIGRATION_JOURNAL_INCOMPLETE", "A migration cannot be marked applied before every DDL boundary is durable.", details={"version": path.name}, status_code=500)
                conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)", (path.name, utcnow()))
                conn.execute("UPDATE schema_migration_journal SET status='applied',updated_at=?,error_json=NULL WHERE version=?", (utcnow(), path.name))
        from migration.service import reconcile_database
        reconcile_database(self)

    def record_error(self, code: str, message: str, details: Any = None) -> None:
        try:
            with self.connection() as conn:
                conn.execute(
                    "INSERT INTO recent_errors(created_at, code, message, details_json) VALUES(?,?,?,?)",
                    (utcnow(), code, message, canonical_json(details) if details is not None else None),
                )
        except Exception:
            pass


def safe_basename(value: str) -> str:
    p = Path(value)
    if p.name != value or value in {"", ".", ".."}:
        raise FoundryError("UNSAFE_FILENAME", "Only a plain filename is allowed.", details={"value": value})
    return value


def resolve_inside(base: Path, name: str) -> Path:
    safe_basename(name)
    target = (base / name).resolve()
    base_resolved = base.resolve()
    if target.parent != base_resolved:
        raise FoundryError("PATH_OUTSIDE_ALLOWED_ROOT", "The requested file is outside the allowed directory.")
    return target
