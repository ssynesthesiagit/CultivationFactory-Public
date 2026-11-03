"""Agent bridge: let a harness-held agent answer one provider request.

This module owns the durable request mailbox and nothing else.  An *agent* is
any local process that can read a request and post one JSON answer; its own
harness holds whatever model credentials it already uses (subscription OAuth,
DeepSeek, ...).  No key, token or session material enters the application.

The application validates an agent answer through exactly the same schema
validation a configured provider answer goes through, and the waiting caller
completes with the same evidence shape either way.  A slow agent is never an
error: the request stays pending and the caller re-drives the same step with
the same idempotency key.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_bytes, utcnow

AGENT_STATE_PENDING = "PENDING"
AGENT_STATE_CLAIMED = "CLAIMED"
AGENT_STATE_ANSWERED = "ANSWERED"
AGENT_STATE_CONSUMED = "CONSUMED"
AGENT_STATE_REJECTED = "REJECTED"
AGENT_STATE_EXPIRED = "EXPIRED"

AGENT_REQUEST_STATES = frozenset(
    {
        AGENT_STATE_PENDING,
        AGENT_STATE_CLAIMED,
        AGENT_STATE_ANSWERED,
        AGENT_STATE_CONSUMED,
        AGENT_STATE_REJECTED,
        AGENT_STATE_EXPIRED,
    }
)
# A request in one of these states can still be claimed or answered.
AGENT_OPEN_STATES = frozenset({AGENT_STATE_PENDING, AGENT_STATE_CLAIMED})

DEFAULT_AGENT_WAIT_SECONDS = 300
MIN_AGENT_WAIT_SECONDS = 10
MAX_AGENT_WAIT_SECONDS = 3600
DEFAULT_AGENT_LEASE_SECONDS = 300
MIN_AGENT_LEASE_SECONDS = 30
MAX_AGENT_LEASE_SECONDS = 3600
# Poll interval for the waiting caller.  One second is the documented cadence;
# tests may shorten it to keep deterministic timeouts fast.
AGENT_POLL_INTERVAL_SECONDS = 1.0
AGENT_DEFAULT_MAX_OUTPUT_TOKENS = 8192
# The bridge carries the same bounded substantive budget the local ceiling uses
# (the composite/GM 6144 wire plus the Command 4 16384 ceiling), and the same
# purpose-scoped schema budgets, so an agent request is byte-identical to the
# local request each caller already authorized.
AGENT_MAX_OUTPUT_TOKENS = 16384

AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
AGENT_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,99}$")
AGENT_REASON_MAX_LENGTH = 500

_JSON_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*\n?(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)


def response_text_ceiling(max_output_tokens: Any) -> int:
    """Bound one answer body from the request's own completion budget."""

    tokens = max_output_tokens if type(max_output_tokens) is int else 0
    if tokens <= 0:
        tokens = AGENT_DEFAULT_MAX_OUTPUT_TOKENS
    return 8 * tokens


def strip_json_fence(value: str) -> str:
    """Return the answer body without one surrounding Markdown code fence."""

    text = value.strip()
    match = _JSON_FENCE_PATTERN.match(text)
    if match is not None:
        return match.group("body").strip()
    return text


class AgentRequestBridge:
    """Durable PENDING/CLAIMED/ANSWERED/CONSUMED mailbox for agent answers."""

    # The exact audited column set of ``ai_provider_runs`` after this rebuild.
    # Any other column means a newer schema added data this rebuild would drop,
    # so the rebuild must refuse rather than silently lose it.
    _REBUILD_COLUMNS = frozenset(
        {
            "run_id", "provider_id", "project_id", "prompt_id", "call_key",
            "idempotency_key", "prompt_sha256", "model", "endpoint", "request_bytes",
            "request_sha256", "started_at", "completed_at", "status", "http_status",
            "provider_response_bytes", "provider_response_sha256",
            "provider_response_bytes_count", "completion_content_sha256",
            "finish_reason", "prompt_tokens", "completion_tokens", "total_tokens",
            "stage1_attempt_id", "error_code", "error_message",
        }
    )
    # Exact index definitions this rebuild recreates, expressed as metadata
    # signatures: (unique, partial-predicate, ((column, collation, descending), ...)).
    _EXPECTED_INDEXES = {
        "idx_ai_provider_runs_project": (False, None, (("project_id", "BINARY", 0), ("started_at", "BINARY", 0), ("run_id", "BINARY", 0))),
        "idx_ai_provider_runs_prompt": (False, None, (("prompt_id", "BINARY", 0), ("started_at", "BINARY", 0), ("run_id", "BINARY", 0))),
        "idx_ai_provider_runs_idempotency": (True, None, (("provider_id", "BINARY", 0), ("prompt_id", "BINARY", 0), ("idempotency_key", "BINARY", 0))),
        "idx_ai_provider_runs_call_key": (True, "call_key IS NOT NULL", (("call_key", "BINARY", 0),)),
    }

    # The two audited column lists this rebuild may replace, taken verbatim
    # from the applied migration (010_optional_ai_provider.sql) and from the
    # CREATE statement below.  The shape check below is an exact template match
    # against these constants — not a parser — and it only tolerates the audited
    # nullability and ``call_key`` variants.  Any other column, column-level
    # constraint, table-level UNIQUE/CHECK, DEFAULT, collation, generated
    # column, or outgoing foreign key fails closed.
    _PRE_BRIDGE_COLUMNS = (
        "run_id TEXT PRIMARY KEY",
        "provider_id TEXT NOT NULL",
        "project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT",
        "prompt_id TEXT NOT NULL REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE RESTRICT",
        "idempotency_key TEXT NOT NULL",
        "prompt_sha256 TEXT NOT NULL",
        "model TEXT NOT NULL",
        "endpoint TEXT NOT NULL",
        "request_bytes BLOB NOT NULL",
        "request_sha256 TEXT NOT NULL",
        "started_at TEXT NOT NULL",
        "completed_at TEXT",
        "status TEXT NOT NULL CHECK(status IN ('started','provider_error','response_rejected','validated'))",
        "http_status INTEGER",
        "provider_response_bytes BLOB",
        "provider_response_sha256 TEXT",
        "provider_response_bytes_count INTEGER",
        "completion_content_sha256 TEXT",
        "finish_reason TEXT",
        "prompt_tokens INTEGER",
        "completion_tokens INTEGER",
        "total_tokens INTEGER",
        "stage1_attempt_id TEXT",
        "error_code TEXT",
        "error_message TEXT",
    )
    _BRIDGE_COLUMNS = (
        "run_id TEXT PRIMARY KEY",
        "provider_id TEXT NOT NULL",
        "project_id TEXT REFERENCES projects(project_id) ON DELETE RESTRICT",
        "prompt_id TEXT REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE RESTRICT",
        "call_key TEXT",
        "idempotency_key TEXT NOT NULL",
        "prompt_sha256 TEXT NOT NULL",
        "model TEXT NOT NULL",
        "endpoint TEXT NOT NULL",
        "request_bytes BLOB NOT NULL",
        "request_sha256 TEXT NOT NULL",
        "started_at TEXT NOT NULL",
        "completed_at TEXT",
        "status TEXT NOT NULL CHECK(status IN ('started','provider_error','response_rejected','validated'))",
        "http_status INTEGER",
        "provider_response_bytes BLOB",
        "provider_response_sha256 TEXT",
        "provider_response_bytes_count INTEGER",
        "completion_content_sha256 TEXT",
        "finish_reason TEXT",
        "prompt_tokens INTEGER",
        "completion_tokens INTEGER",
        "total_tokens INTEGER",
        "stage1_attempt_id TEXT",
        "error_code TEXT",
        "error_message TEXT",
    )

    # The only accepted CREATE TABLE prefixes.  Anything else (a different table
    # name form, a TEMP/TEMPORARY table, a schema-qualified name) is refused.
    _TABLE_QUOTE = '"'
    _TABLE_PREFIX_RE = re.compile(
        "^CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?"
        + _TABLE_QUOTE
        + "?ai_provider_runs"
        + _TABLE_QUOTE
        + "?\\s*(?=\\()",
        re.IGNORECASE,
    )

    @staticmethod
    def _quoted_identifier(name: Any) -> str:
        """Quote one SQLite identifier so a name containing quotes is safe."""

        return '"' + str(name).replace('"', '""') + '"'

    @staticmethod
    def _pragma_value(row: Any, key: str, index: int) -> Any:
        """Read one PRAGMA column by name, or by position on a raw connection."""

        try:
            return row[key]
        except (IndexError, KeyError, TypeError):
            return row[index]

    @classmethod
    def _index_signature(cls, conn: sqlite3.Connection, name: str) -> tuple:
        """Read one index's full audited metadata signature."""

        index_rows = conn.execute(
            f"PRAGMA index_list({cls._quoted_identifier('ai_provider_runs')})"
        ).fetchall()
        current = next(
            (
                row
                for row in index_rows
                if str(cls._pragma_value(row, "name", 1)).casefold() == name.casefold()
            ),
            None,
        )
        if current is None:
            raise sqlite3.OperationalError("index not found")
        unique = bool(int(cls._pragma_value(current, "unique", 2) or 0))
        try:
            partial = int(cls._pragma_value(current, "partial", 4) or 0)
        except (IndexError, KeyError, TypeError, ValueError):
            # Older SQLite builds do not report ``partial``; the predicate regex
            # below still finds a WHERE clause.
            partial = 0
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone()
        sql_text = (
            " ".join((cls._pragma_value(sql_row, "sql", 0) or "").split()) if sql_row else ""
        )
        # Case-insensitive and never an index error: an unreadable predicate
        # compares as ``None`` and is refused as an altered index.
        match = re.search(r"\bwhere\b", sql_text, re.IGNORECASE)
        predicate = sql_text[match.end():].strip() if match else None
        if not predicate:
            predicate = None
        columns: list[tuple[str, str, int]] = []
        for row in conn.execute(f"PRAGMA index_xinfo({cls._quoted_identifier(name)})").fetchall():
            if int(cls._pragma_value(row, "key", 5) or 0) != 1:
                continue
            # SQLite preserves declared identifier case; index identity is
            # case-insensitive, so signatures compare casefolded.
            columns.append(
                (
                    str(cls._pragma_value(row, "name", 2)).casefold(),
                    str(cls._pragma_value(row, "coll", 4) or "BINARY").upper(),
                    int(cls._pragma_value(row, "desc", 3) or 0),
                )
            )
        return (unique, predicate, tuple(columns))

    @staticmethod
    def _normalized_table_text(text: str) -> str:
        """Normalize CREATE TABLE text while preserving quoted literals.

        Outside quotes: whitespace runs collapse to one space and unquoted words
        are casefolded, so keyword/identifier case and layout do not matter.
        Inside quotes (single, double, bracket, or backtick delimited): every
        byte, including case and internal spacing, is preserved verbatim.
        """

        output: list[str] = []
        index = 0
        length = len(text)
        pending_space = False
        while index < length:
            character = text[index]
            if character in "'\"`[":
                closer = "]" if character == "[" else character
                end = index + 1
                while end < length:
                    if text[end] == closer:
                        end += 1
                        break
                    end += 1
                if pending_space and output:
                    output.append(" ")
                pending_space = False
                output.append(text[index:end])
                index = end
                continue
            if character.isspace():
                pending_space = True
                index += 1
                continue
            if character in ",()":
                while output and output[-1] == " ":
                    output.pop()
                output.append(character)
                pending_space = False
                index += 1
                continue
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(character.casefold())
            index += 1
        return "".join(output)

    @classmethod
    def _table_column_definitions(cls, ddl: str) -> tuple[str, ...] | None:
        """Split CREATE TABLE text into a normalized set of column definitions.

        The prefix must be exactly ``CREATE TABLE [IF NOT EXISTS] ai_provider_runs``
        and the balanced column list must be the whole statement: an unrecognized
        prefix, a table option or any other suffix, or an unreadable body all
        return ``None``.  Quoted literals keep their exact bytes, so a CHECK
        literal is never compared case-insensitively.
        """

        # Raw outer trim only: the quote-aware normalizer below must see the
        # literal bytes exactly as SQLite stored them (no whitespace collapsing
        # before quoted regions are recognized).
        text = (ddl or "").strip()
        pattern = cls._TABLE_PREFIX_RE.match(text)
        if pattern is None:
            return None
        opener = text.find("(", pattern.end())
        if opener < 0:
            return None
        closed_at = text.rfind(")")
        if closed_at <= opener:
            return None
        if text[closed_at + 1:].strip():
            # A trailing table option (STRICT, WITHOUT ROWID) or any other
            # suffix is not an audited layout.  SQLite guarantees the DDL it
            # reported is syntactically valid, so the last ")" closes the table
            # body and a non-empty tail is always unrecognized syntax.
            return None
        body = text[opener + 1: closed_at]
        pieces: list[str] = []
        depth = 0
        current: list[str] = []
        position = 0
        while position < len(body):
            character = body[position]
            if character in "'\"`[":
                # Copy the quoted region verbatim so its bytes (case, spacing,
                # punctuation) survive into the comparison.
                closer = "]" if character == "[" else character
                end = position + 1
                while end < len(body) and body[end] != closer:
                    end += 1
                end = min(end + 1, len(body))
                current.append(body[position:end])
                position = end
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    return None
            if character == "," and depth == 0:
                pieces.append("".join(current))
                current = []
                position += 1
                continue
            current.append(character)
            position += 1
        pieces.append("".join(current))
        if depth != 0:
            return None
        if any(not piece.strip() for piece in pieces):
            # An empty definition means the body had a stray or doubled comma.
            return None
        definitions = tuple(cls._normalized_table_text(piece) for piece in pieces)
        if len(definitions) != len(pieces):
            return None
        return definitions

    @classmethod
    def _audited_table_shape(cls, ddl: str) -> str | None:
        """Name the audited shape this DDL is, or ``None`` when unaudited.

        Audited shapes: the pre-bridge column list, that list with the two
        foreign keys relaxed, either of those with ``call_key`` added, and the
        bridge list.  Comparison is over the exact set of column definitions, so
        column order does not matter but any other column, column-level or
        table-level constraint, DEFAULT, collation, generated column, or
        outgoing foreign key this table does not declare refuses the rebuild.
        """

        definitions = cls._table_column_definitions(ddl)
        if definitions is None:
            return None
        if any(
            definition.startswith(("unique ", "check ", "constraint ", "primary key ", "foreign key "))
            or definition in {"unique", "check", "primary key", "foreign key"}
            for definition in definitions
        ):
            # Table-level constraints are not part of an audited shape.
            return None
        pre = cls._PRE_BRIDGE_COLUMNS
        relaxed = tuple(
            column.replace(" TEXT NOT NULL REFERENCES", " TEXT REFERENCES") for column in pre
        )
        candidates = {
            "pre_bridge": pre,
            "pre_bridge_relaxed": relaxed,
            "pre_bridge_with_call_key": pre[:4] + ("call_key TEXT",) + pre[4:],
            # The relaxed list with call_key IS the bridge list; one label keeps
            # the reported shape unambiguous.
            "bridge": cls._BRIDGE_COLUMNS,
        }
        current = set(definitions)
        for label, columns in candidates.items():
            # Templates go through the same literal-preserving normalizer so a
            # quoted CHECK literal compares byte-for-byte with the table's own.
            if current == {cls._normalized_table_text(column) for column in columns}:
                return label
        return None

    # Declared types of the columns whose payload identity this rebuild owns.
    # A different declared type is a partially upgraded or hand-edited table,
    # and converting it silently could change stored values.
    _REBUILD_COLUMN_TYPES = {
        "run_id": "TEXT",
        "provider_id": "TEXT",
        "call_key": "TEXT",
        "idempotency_key": "TEXT",
        "request_bytes": "BLOB",
        "request_sha256": "TEXT",
        "status": "TEXT",
    }

    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- schema
    def ensure_schema(self) -> None:
        """Create the agent mailbox and the wait setting if they are absent.

        The application ordinarily evolves its schema through ``migrations/``.
        This job deliberately does not add a migration file: every unapplied
        migration makes ``Database.migrate()`` copy the whole live
        ``foundry.sqlite3`` to ``backups/`` first, and the owner forbade copying
        that 11.2 GB database.  Both statements below are additive and
        idempotent, matching the runtime ``_ensure_schema`` pattern already used
        by ``character_library_archive/service.py``.
        """

        with self.db.transaction() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ai_agent_requests(
                   request_id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   provider_id TEXT NOT NULL,
                   project_id TEXT NOT NULL,
                   prompt_id TEXT NOT NULL,
                   idempotency_key TEXT NOT NULL,
                   purpose TEXT NOT NULL,
                   schema_name TEXT NOT NULL,
                   request_json TEXT NOT NULL,
                   request_sha256 TEXT NOT NULL,
                   max_output_tokens INTEGER NOT NULL,
                   state TEXT NOT NULL CHECK(state IN
                     ('PENDING','CLAIMED','ANSWERED','CONSUMED','REJECTED','EXPIRED')),
                   agent_id TEXT,
                   agent_model TEXT,
                   response_text TEXT,
                   response_sha256 TEXT,
                   validation_json TEXT,
                   rejection_json TEXT,
                   created_at TEXT NOT NULL,
                   claimed_at TEXT,
                   claimed_until TEXT,
                   answered_at TEXT,
                   consumed_at TEXT,
                   expires_at TEXT)"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_ai_agent_requests_state
                   ON ai_agent_requests(state, created_at, request_id)"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_ai_agent_requests_key
                   ON ai_agent_requests(provider_id, prompt_id, idempotency_key, created_at)"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_agent_requests_active
                   ON ai_agent_requests(provider_id, prompt_id, idempotency_key)
                   WHERE state IN ('PENDING','CLAIMED','ANSWERED')"""
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(ai_provider_settings)").fetchall()
            }
            if "agent_wait_seconds" not in columns:
                conn.execute(
                    "ALTER TABLE ai_provider_settings ADD COLUMN agent_wait_seconds INTEGER NOT NULL DEFAULT 300"
                )
            # ``table_info`` hides generated and other hidden columns, which a
            # rebuild would silently drop; ``table_xinfo`` reports them.
            try:
                run_column_rows = conn.execute(
                    f"PRAGMA table_xinfo({self._quoted_identifier('ai_provider_runs')})"
                ).fetchall()
            except sqlite3.Error as exc:
                raise FoundryError(
                    "AI_AGENT_SCHEMA_REBUILD_BLOCKED",
                    "The provider run table columns could not be inspected; no schema change was made.",
                    details={"table": "ai_provider_runs", "reason": type(exc).__name__},
                    status_code=500,
                ) from exc
            run_column_info = {
                self._pragma_value(row, "name", 1): str(self._pragma_value(row, "type", 2) or "").upper().strip()
                for row in run_column_rows
            }
            run_columns = set(run_column_info)
            hidden_columns = sorted(
                self._pragma_value(row, "name", 1)
                for row in run_column_rows
                if int(self._pragma_value(row, "hidden", 6) or 0) != 0
            )
            run_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_provider_runs'"
            ).fetchone()
            prompt_id_required = bool(
                run_sql
                and "prompt_id TEXT NOT NULL" in (run_sql["sql"] or "")
            )
            project_id_required = bool(
                run_sql
                and "project_id TEXT NOT NULL" in (run_sql["sql"] or "")
            )
            import os as _oq
            if _oq.environ.get("GUARDDBG"):
                print("GUARDDBG pid", hex(id(self)), "prompt_required", prompt_id_required,
                      "project_required", project_id_required, "call_key", "call_key" in run_columns,
                      "cols", len(run_columns), flush=True)
            if prompt_id_required or project_id_required or "call_key" not in run_columns:
                # ``ai_provider_runs.prompt_id`` references the Stage 1 prompt
                # exchange, but the factory authoring steps are not Stage 1
                # prompts, and the optional debrief/connection-test probes are
                # project-free.  Rebuild the table once so those runs keep their
                # recorded step identity in ``call_key`` while ``prompt_id`` and
                # ``project_id`` stay NULL instead of pointing at unrelated
                # records.  The table holds bounded audit rows (a live database
                # currently holds none), so this rebuild copies no game data.
                #
                # Fail closed before any destructive step.  This rebuild only
                # preserves the table's own four indexes and its exact audited
                # column set, so anything else attached to the table must be
                # reported instead of silently dropped.  Detection uses SQLite
                # metadata where SQLite defines it (PRAGMA foreign_key_list for
                # incoming keys, PRAGMA table_info for columns) and a
                # conservative SQL-text scan for views/triggers, which have no
                # metadata link back to the referenced table and may be written
                # with quoted identifiers or newlines.
                blocked: list[dict[str, Any]] = []

                # Incoming foreign keys: SQLite's own metadata, covering quoted
                # and multi-line reference forms that a LIKE over DDL misses.
                # Identifiers are case-insensitive, so the target comparison is
                # casefolded; a table whose PRAGMA cannot be read is refused
                # rather than skipped, because an uninspected table may hold the
                # dependency this rebuild would break.
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
                ).fetchall():
                    table_name = row["name"]
                    if str(table_name).casefold() == "ai_provider_runs":
                        continue
                    try:
                        keys = conn.execute(
                            f"PRAGMA foreign_key_list({self._quoted_identifier(table_name)})"
                        ).fetchall()
                    except sqlite3.Error as exc:
                        blocked.append(
                            {
                                "type": "foreign_key_inspection_failed",
                                "table": table_name,
                                "reason": type(exc).__name__,
                            }
                        )
                        continue
                    for key in keys:
                        if str(key["table"]).casefold() == "ai_provider_runs":
                            blocked.append(
                                {
                                    "type": "incoming_foreign_key",
                                    "table": table_name,
                                    "from": key["from"],
                                    "to": key["to"],
                                }
                            )

                # Views and triggers: conservative text scan over objects whose
                # SQL names the table in any identifier form.
                reference = re.compile(r"ai_provider_runs", re.IGNORECASE)
                for row in conn.execute(
                    """SELECT type, name, sql FROM sqlite_master
                       WHERE type IN ('trigger','view') AND sql IS NOT NULL"""
                ).fetchall():
                    if reference.search(row["sql"] or ""):
                        blocked.append({"type": row["type"], "name": row["name"]})

                # Extra or unknown columns on the table (metadata, not DDL text).
                # The table shape must be one this rebuild may replace: the
                # pre-bridge column list (with or without a stray call_key) or
                # the bridge column list.  A table-level UNIQUE/CHECK, a DEFAULT,
                # a generated column, a different outgoing foreign key, or an
                # unknown column all fail closed here.
                ddl_row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    ("ai_provider_runs",),
                ).fetchone()
                if _oq.environ.get("GUARDDBG"):
                    _shape = None if ddl_row is None else self._audited_table_shape(ddl_row["sql"])
                    print("GUARDDBG ddl_row", ddl_row is not None, "shape", _shape,
                          "tail", repr(" ".join(str(ddl_row["sql"]).split())[-45:]) if ddl_row else None, flush=True)
                if ddl_row is None or not ddl_row["sql"]:
                    blocked.append({"type": "table_shape_unreadable"})
                elif self._audited_table_shape(ddl_row["sql"]) is None:
                    if _oq.environ.get("GUARDDBG"):
                        print("GUARDDBG unaudited tail", repr(" ".join(str(ddl_row["sql"]).split())[-45:]),
                              "| len", len(str(ddl_row["sql"])), flush=True)
                    blocked.append(
                        {
                            "type": "unaudited_table_shape",
                            "ddl": " ".join(str(ddl_row["sql"]).split())[:600],
                        }
                    )

                if hidden_columns:
                    # Generated/other hidden columns are invisible to
                    # ``table_info`` and would be dropped by the rebuild.
                    blocked.append({"type": "hidden_columns", "columns": hidden_columns})

                unknown_columns = sorted(set(run_columns) - self._REBUILD_COLUMNS)
                if unknown_columns:
                    blocked.append({"type": "unknown_columns", "columns": unknown_columns})

                # Partially upgraded or hand-edited columns: same name, different
                # declared type (for example an INTEGER call_key).
                for column, expected in self._REBUILD_COLUMN_TYPES.items():
                    actual = run_column_info.get(column)
                    if actual is None:
                        continue
                    if actual != expected:
                        blocked.append(
                            {
                                "type": "partial_upgrade",
                                "column": column,
                                "declared_type": actual,
                                "expected_type": expected,
                            }
                        )

                # Known-name indexes whose definition differs from the one this
                # rebuild recreates: recreating would silently change them.
                # Indexes are compared through SQLite's own index metadata
                # (uniqueness, partial predicate, per-column collation and sort
                # order), never through a DDL substring: a definition can keep
                # the same columns while changing UNIQUE or its WHERE clause,
                # and the rebuild would silently replace it.
                existing_indexes = [
                    row["name"]
                    for row in conn.execute(
                        """SELECT name FROM sqlite_master
                           WHERE tbl_name='ai_provider_runs' AND type='index'
                             AND name NOT LIKE 'sqlite_autoindex_%'"""
                    ).fetchall()
                ]
                for name in sorted(set(existing_indexes) - set(self._EXPECTED_INDEXES)):
                    blocked.append({"type": "unknown_index", "name": name})
                for name, expected in self._EXPECTED_INDEXES.items():
                    if name not in existing_indexes:
                        continue
                    try:
                        actual = self._index_signature(conn, name)
                    except sqlite3.Error as exc:
                        # An index this code cannot inspect cannot be certified
                        # safe to replace.
                        blocked.append(
                            {"type": "index_inspection_failed", "name": name, "reason": type(exc).__name__}
                        )
                        continue
                    if actual != expected:
                        blocked.append(
                            {
                                "type": "altered_index",
                                "name": name,
                                "actual": actual,
                                "expected": expected,
                            }
                        )

                if _oq.environ.get("GUARDDBG"):
                    print("GUARDDBG blocked", [row.get("type") for row in blocked], flush=True)
                if blocked:
                    raise FoundryError(
                        "AI_AGENT_SCHEMA_REBUILD_BLOCKED",
                        "The provider run table has dependent or altered schema objects this rebuild does not preserve; no schema change was made.",
                        details={"table": "ai_provider_runs", "dependents": blocked},
                        status_code=500,
                    )
                conn.execute(
                    """CREATE TABLE ai_provider_runs_rebuild(
                       run_id TEXT PRIMARY KEY,
                       provider_id TEXT NOT NULL,
                       project_id TEXT REFERENCES projects(project_id) ON DELETE RESTRICT,
                       prompt_id TEXT REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE RESTRICT,
                       call_key TEXT,
                       idempotency_key TEXT NOT NULL,
                       prompt_sha256 TEXT NOT NULL,
                       model TEXT NOT NULL,
                       endpoint TEXT NOT NULL,
                       request_bytes BLOB NOT NULL,
                       request_sha256 TEXT NOT NULL,
                       started_at TEXT NOT NULL,
                       completed_at TEXT,
                       status TEXT NOT NULL CHECK(status IN ('started','provider_error','response_rejected','validated')),
                       http_status INTEGER,
                       provider_response_bytes BLOB,
                       provider_response_sha256 TEXT,
                       provider_response_bytes_count INTEGER,
                       completion_content_sha256 TEXT,
                       finish_reason TEXT,
                       prompt_tokens INTEGER,
                       completion_tokens INTEGER,
                       total_tokens INTEGER,
                       stage1_attempt_id TEXT,
                       error_code TEXT,
                       error_message TEXT)"""
                )
                # ``call_key`` is carried over verbatim when the column is
                # already present (a nullability-only rebuild must not discard
                # recorded step identity); it is NULL only for rows written
                # before the column existed.
                call_key_source = "call_key" if "call_key" in run_columns else "NULL"
                conn.execute(
                    f"""INSERT INTO ai_provider_runs_rebuild(
                       run_id,provider_id,project_id,prompt_id,call_key,idempotency_key,prompt_sha256,
                       model,endpoint,request_bytes,request_sha256,started_at,completed_at,status,
                       http_status,provider_response_bytes,provider_response_sha256,
                       provider_response_bytes_count,completion_content_sha256,finish_reason,
                       prompt_tokens,completion_tokens,total_tokens,stage1_attempt_id,error_code,error_message)
                       SELECT run_id,provider_id,project_id,prompt_id,{call_key_source},idempotency_key,prompt_sha256,
                       model,endpoint,request_bytes,request_sha256,started_at,completed_at,status,
                       http_status,provider_response_bytes,provider_response_sha256,
                       provider_response_bytes_count,completion_content_sha256,finish_reason,
                       prompt_tokens,completion_tokens,total_tokens,stage1_attempt_id,error_code,error_message
                       FROM ai_provider_runs"""
                )
                conn.execute("DROP TABLE ai_provider_runs")
                conn.execute("ALTER TABLE ai_provider_runs_rebuild RENAME TO ai_provider_runs")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_project
                   ON ai_provider_runs(project_id, started_at, run_id)"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_prompt
                   ON ai_provider_runs(prompt_id, started_at, run_id)"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_runs_idempotency
                   ON ai_provider_runs(provider_id, prompt_id, idempotency_key)"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_runs_call_key
                   ON ai_provider_runs(call_key) WHERE call_key IS NOT NULL"""
            )

    # ------------------------------------------------------------ public rows
    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "run_id": row["run_id"],
            "provider_id": row["provider_id"],
            "project_id": row["project_id"],
            "prompt_id": row["prompt_id"],
            "idempotency_key": row["idempotency_key"],
            "purpose": row["purpose"],
            "schema_name": row["schema_name"],
            "request_sha256": row["request_sha256"],
            "request_bytes": len(row["request_json"].encode("utf-8")),
            "max_output_tokens": row["max_output_tokens"],
            "state": row["state"],
            "agent_id": row["agent_id"],
            "agent_model": row["agent_model"],
            "response_sha256": row["response_sha256"],
            "created_at": row["created_at"],
            "claimed_at": row["claimed_at"],
            "claimed_until": row["claimed_until"],
            "answered_at": row["answered_at"],
            "consumed_at": row["consumed_at"],
            "expires_at": row["expires_at"],
            "has_validation_errors": row["validation_json"] is not None,
        }

    @classmethod
    def _document(cls, row: sqlite3.Row) -> dict[str, Any]:
        """Full request document: exactly what a model would have received."""

        request_json = json.loads(row["request_json"])
        document = cls._summary(row)
        document["request_json"] = request_json
        document["schema"] = (
            request_json.get("response_format", {}).get("json_schema", {}).get("schema")
            if isinstance(request_json, dict)
            else None
        )
        document["response_text"] = row["response_text"]
        document["validation"] = json.loads(row["validation_json"]) if row["validation_json"] else None
        document["rejection"] = json.loads(row["rejection_json"]) if row["rejection_json"] else None
        return document

    def _row(self, request_id: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row:
        if conn is None:
            with self.db.connection() as own:
                return self._row(request_id, own)
        row = conn.execute(
            "SELECT * FROM ai_agent_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise FoundryError(
                "AI_AGENT_REQUEST_NOT_FOUND",
                "No agent bridge request has that ID.",
                details={"request_id": request_id},
                status_code=404,
            )
        return row

    # -------------------------------------------------------------- enqueue
    def find_latest(self, *, provider_id: str, prompt_id: str, idempotency_key: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT * FROM ai_agent_requests
                   WHERE provider_id=? AND prompt_id=? AND idempotency_key=?
                   ORDER BY created_at DESC, request_id DESC LIMIT 1""",
                (provider_id, prompt_id, idempotency_key),
            ).fetchone()
        return self._document(row) if row is not None else None

    def enqueue(
        self,
        *,
        request_payload: dict[str, Any],
        purpose: str,
        schema_name: str,
        run_id: str,
        provider_id: str,
        project_id: str,
        prompt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Return the open request for this step, creating one only if needed."""

        request_bytes = canonical_json(request_payload).encode("utf-8")
        request_sha256 = sha256_bytes(request_bytes)
        max_output_tokens = request_payload.get("max_tokens")
        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            max_output_tokens = AGENT_DEFAULT_MAX_OUTPUT_TOKENS
        now = utcnow()
        with self.db.transaction() as conn:
            existing = conn.execute(
                """SELECT * FROM ai_agent_requests
                   WHERE provider_id=? AND prompt_id=? AND idempotency_key=?
                   ORDER BY created_at DESC, request_id DESC LIMIT 1""",
                (provider_id, prompt_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["state"] in AGENT_OPEN_STATES:
                    # Re-drive of a step whose agent has not answered yet: wait
                    # on the same request instead of prompting twice.
                    return self._document(existing)
                if existing["state"] == AGENT_STATE_REJECTED:
                    rejection = json.loads(existing["rejection_json"]) if existing["rejection_json"] else {}
                    raise self._rejected_error(existing["request_id"], rejection)
            request_id = "ai.agent." + uuid.uuid4().hex
            conn.execute(
                """INSERT INTO ai_agent_requests(
                   request_id,run_id,provider_id,project_id,prompt_id,idempotency_key,
                   purpose,schema_name,request_json,request_sha256,max_output_tokens,
                   state,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    run_id,
                    provider_id,
                    project_id,
                    prompt_id,
                    idempotency_key,
                    purpose,
                    schema_name,
                    request_bytes.decode("utf-8"),
                    request_sha256,
                    max_output_tokens,
                    AGENT_STATE_PENDING,
                    now,
                ),
            )
            row = self._row(request_id, conn)
        return self._document(row)

    @staticmethod
    def _rejected_error(request_id: str, rejection: dict[str, Any]) -> FoundryError:
        reason = rejection.get("reason") if isinstance(rejection, dict) else None
        agent_id = rejection.get("agent_id") if isinstance(rejection, dict) else None
        return FoundryError(
            "AI_AGENT_REQUEST_REJECTED",
            f"The agent declined this step: {reason}" if reason else "The agent declined this step.",
            details={
                "request_id": request_id,
                "agent_id": agent_id,
                "reason": reason,
            },
            status_code=409,
        )

    # ---------------------------------------------------------------- reads
    def list_requests(self, *, state: str | None = None, limit: int = 50) -> dict[str, Any]:
        normalized = str(state or "").strip().upper() or None
        if normalized is not None and normalized not in AGENT_REQUEST_STATES:
            raise FoundryError(
                "AI_AGENT_STATE_INVALID",
                "state must be one of PENDING, CLAIMED, ANSWERED, CONSUMED, REJECTED, EXPIRED.",
                details={"state": state},
            )
        bounded = max(1, min(int(limit), 200))
        with self.db.connection() as conn:
            if normalized is None:
                rows = conn.execute(
                    """SELECT * FROM ai_agent_requests
                       ORDER BY created_at DESC, request_id DESC LIMIT ?""",
                    (bounded,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM ai_agent_requests WHERE state=?
                       ORDER BY created_at DESC, request_id DESC LIMIT ?""",
                    (normalized, bounded),
                ).fetchall()
            counts = {
                row["state"]: row["total"]
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS total FROM ai_agent_requests GROUP BY state"
                ).fetchall()
            }
        return {
            "requests": [self._summary(row) for row in rows],
            "state": normalized,
            "counts": {state: int(counts.get(state, 0)) for state in sorted(AGENT_REQUEST_STATES)},
        }

    def get(self, request_id: str) -> dict[str, Any]:
        return self._document(self._row(request_id))

    def counts(self) -> dict[str, Any]:
        with self.db.connection() as conn:
            counts = {
                row["state"]: int(row["total"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS total FROM ai_agent_requests GROUP BY state"
                ).fetchall()
            }
            oldest = conn.execute(
                "SELECT MIN(created_at) AS oldest FROM ai_agent_requests WHERE state='PENDING'"
            ).fetchone()
        result = {state: counts.get(state, 0) for state in sorted(AGENT_REQUEST_STATES)}
        result["pending"] = result[AGENT_STATE_PENDING]
        result["claimed"] = result[AGENT_STATE_CLAIMED]
        result["answered"] = result[AGENT_STATE_ANSWERED]
        result["oldest_pending_at"] = oldest["oldest"] if oldest is not None else None
        return result

    # ------------------------------------------------------------ transitions
    def claim(self, request_id: str, *, agent_id: str, lease_seconds: int | None = None) -> dict[str, Any]:
        agent = self._validated_agent_id(agent_id)
        lease = self._validated_lease(lease_seconds)
        now = utcnow()
        claimed_until = _shift_seconds(now, lease)
        with self.db.transaction() as conn:
            row = self._row(request_id, conn)
            if row["state"] not in AGENT_OPEN_STATES:
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_CLAIMABLE",
                    f"An agent request in state {row['state']} cannot be claimed.",
                    details={"request_id": request_id, "state": row["state"], "agent_id": row["agent_id"]},
                    status_code=409,
                )
            # One conditional UPDATE is the whole lease protocol: exactly one
            # competing claimer can move an open, unheld request to CLAIMED.
            cursor = conn.execute(
                """UPDATE ai_agent_requests
                   SET state=?, agent_id=?, claimed_at=?, claimed_until=?
                   WHERE request_id=? AND state IN (?,?)
                     AND (claimed_until IS NULL OR claimed_until <= ?
                          OR (agent_id=? AND state=?))""",
                (
                    AGENT_STATE_CLAIMED,
                    agent,
                    now,
                    claimed_until,
                    request_id,
                    AGENT_STATE_PENDING,
                    AGENT_STATE_CLAIMED,
                    now,
                    agent,
                    AGENT_STATE_CLAIMED,
                ),
            )
            if cursor.rowcount != 1:
                current = self._row(request_id, conn)
                raise FoundryError(
                    "AI_AGENT_REQUEST_CLAIMED",
                    "Another agent holds the live lease for this request.",
                    details={
                        "request_id": request_id,
                        "state": current["state"],
                        "agent_id": current["agent_id"],
                        "claimed_until": current["claimed_until"],
                    },
                    status_code=409,
                )
            claimed = self._document(self._row(request_id, conn))
        claimed["lease_seconds"] = lease
        return claimed

    def answer(
        self,
        request_id: str,
        *,
        agent_id: str,
        agent_model: str,
        request_sha256: str,
        response_text: str,
        validator: Any,
    ) -> dict[str, Any]:
        """Validate one agent answer exactly like a provider answer.

        ``validator`` is called with the parsed JSON object and must return a
        list of bounded error strings (empty when the object is valid).  A
        failed answer stores its errors, returns the request to PENDING and
        raises 422 so the agent can retry; nothing is consumed.
        """

        agent = self._validated_agent_id(agent_id)
        model = self._validated_agent_model(agent_model)
        if not isinstance(response_text, str) or not response_text.strip():
            raise FoundryError(
                "AI_AGENT_RESPONSE_EMPTY",
                "An agent answer requires non-empty response_text.",
                status_code=422,
            )
        with self.db.connection() as conn:
            row = self._row(request_id, conn)
        if row["state"] not in AGENT_OPEN_STATES:
            raise FoundryError(
                "AI_AGENT_REQUEST_NOT_ANSWERABLE",
                f"An agent request in state {row['state']} cannot be answered.",
                details={"request_id": request_id, "state": row["state"]},
                status_code=409,
            )
        if row["agent_id"] != agent:
            raise FoundryError(
                "AI_AGENT_CLAIM_OWNER_MISMATCH",
                "Only the agent that claimed this request may answer it; claim it first.",
                details={"request_id": request_id, "agent_id": row["agent_id"], "provided_agent_id": agent},
                status_code=409,
            )
        if request_sha256 != row["request_sha256"]:
            raise FoundryError(
                "AI_AGENT_REQUEST_HASH_MISMATCH",
                "The answer was authored against different request bytes; re-read the request and answer again.",
                details={
                    "request_id": request_id,
                    "expected_request_sha256": row["request_sha256"],
                    "provided_request_sha256": request_sha256,
                },
                status_code=409,
            )
        body = strip_json_fence(response_text)
        ceiling = response_text_ceiling(row["max_output_tokens"])
        body_bytes = len(body.encode("utf-8"))
        if body_bytes > ceiling:
            raise FoundryError(
                "AI_AGENT_RESPONSE_TOO_LARGE",
                "The agent answer exceeds the bounded answer size for this request.",
                details={"request_id": request_id, "response_bytes": body_bytes, "max_response_bytes": ceiling},
                status_code=413,
            )
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError) as exc:
            errors = [{"path": [], "message": f"response_text is not one JSON object: {type(exc).__name__}"}]
            self._store_validation_errors(request_id, agent, errors, body)
            raise FoundryError(
                "AI_AGENT_RESPONSE_INVALID_JSON",
                "The agent answer is not one JSON object.",
                details={"request_id": request_id, "errors": errors},
                status_code=422,
            ) from exc
        if not isinstance(parsed, dict):
            errors = [{"path": [], "message": "response_text is not one JSON object."}]
            self._store_validation_errors(request_id, agent, errors, body)
            raise FoundryError(
                "AI_AGENT_RESPONSE_INVALID_JSON",
                "The agent answer is not one JSON object.",
                details={"request_id": request_id, "errors": errors},
                status_code=422,
            )
        errors = validator(parsed)
        if errors:
            self._store_validation_errors(request_id, agent, errors, body)
            raise FoundryError(
                "AI_AGENT_RESPONSE_SCHEMA_INVALID",
                "The agent answer failed the requested response schema.",
                details={"request_id": request_id, "errors": errors},
                status_code=422,
            )
        response_sha256 = sha256_bytes(body.encode("utf-8"))
        now = utcnow()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """UPDATE ai_agent_requests
                   SET state=?, agent_id=?, agent_model=?, response_text=?, response_sha256=?,
                       validation_json=?, answered_at=?
                   WHERE request_id=? AND agent_id=? AND state IN (?,?)""",
                (
                    AGENT_STATE_ANSWERED,
                    agent,
                    model,
                    body,
                    response_sha256,
                    canonical_json({"valid": True, "errors": []}),
                    now,
                    request_id,
                    agent,
                    AGENT_STATE_PENDING,
                    AGENT_STATE_CLAIMED,
                ),
            )
            if cursor.rowcount != 1:
                current = self._row(request_id, conn)
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_ANSWERABLE",
                    f"An agent request in state {current['state']} cannot be answered.",
                    details={"request_id": request_id, "state": current["state"]},
                    status_code=409,
                )
            answered = self._document(self._row(request_id, conn))
        answered["value"] = parsed
        return answered

    def reject(self, request_id: str, *, agent_id: str, reason: str) -> dict[str, Any]:
        agent = self._validated_agent_id(agent_id)
        text = str(reason or "").strip()
        if not text:
            raise FoundryError(
                "AI_AGENT_REJECTION_REASON_REQUIRED",
                "A rejection requires a short reason for the waiting caller.",
                status_code=422,
            )
        if len(text) > AGENT_REASON_MAX_LENGTH:
            text = text[:AGENT_REASON_MAX_LENGTH]
        now = utcnow()
        with self.db.transaction() as conn:
            row = self._row(request_id, conn)
            if row["state"] not in AGENT_OPEN_STATES:
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_REJECTABLE",
                    f"An agent request in state {row['state']} cannot be rejected.",
                    details={"request_id": request_id, "state": row["state"]},
                    status_code=409,
                )
            rejection = {"agent_id": agent, "reason": text, "rejected_at": now}
            conn.execute(
                """UPDATE ai_agent_requests
                   SET state=?, agent_id=?, rejection_json=?, answered_at=?
                   WHERE request_id=?""",
                (AGENT_STATE_REJECTED, agent, canonical_json(rejection), now, request_id),
            )
            rejected = self._document(self._row(request_id, conn))
        # Surface the decline to a caller that is already waiting on this id.
        rejected["error"] = self._rejected_error(request_id, rejection).to_dict()["error"]
        return rejected

    def consume(self, request_id: str, *, run_id: str) -> dict[str, Any]:
        now = utcnow()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """UPDATE ai_agent_requests SET state=?, consumed_at=?
                   WHERE request_id=? AND state=? AND run_id=?""",
                (AGENT_STATE_CONSUMED, now, request_id, AGENT_STATE_ANSWERED, run_id),
            )
            if cursor.rowcount != 1:
                current = self._row(request_id, conn)
                if current["state"] == AGENT_STATE_CONSUMED:
                    return self._document(current)
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_CONSUMABLE",
                    f"An agent request in state {current['state']} cannot be consumed.",
                    details={"request_id": request_id, "state": current["state"]},
                    status_code=409,
                )
            return self._document(self._row(request_id, conn))

    # ------------------------------------------------------------- waiting
    def wait_for_answer(
        self,
        request_id: str,
        *,
        wait_seconds: int,
        poll_interval: float = AGENT_POLL_INTERVAL_SECONDS,
        agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Poll one request until it is answered, rejected, or the wait ends.

        Returns the answered document, raises the caller-visible rejection, or
        returns ``None`` when the request is still open.  A slow agent leaves
        the request pending: the caller re-drives the same step later.
        """

        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        interval = max(0.01, float(poll_interval))
        while True:
            with self.db.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_agent_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
            if row is None:
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_FOUND",
                    "The waiting agent bridge request disappeared.",
                    details={"request_id": request_id},
                    status_code=404,
                )
            if row["state"] == AGENT_STATE_ANSWERED:
                return self._document(row)
            if row["state"] == AGENT_STATE_REJECTED:
                rejection = json.loads(row["rejection_json"]) if row["rejection_json"] else {}
                raise self._rejected_error(request_id, rejection)
            if row["state"] not in AGENT_OPEN_STATES:
                raise FoundryError(
                    "AI_AGENT_REQUEST_NOT_ANSWERABLE",
                    f"An agent request in state {row['state']} can no longer be answered.",
                    details={"request_id": request_id, "state": row["state"]},
                    status_code=409,
                )
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(interval, max(0.01, deadline - time.monotonic())))

    # ------------------------------------------------------------ validation
    @staticmethod
    def _validated_agent_id(value: Any) -> str:
        agent = str(value or "").strip()
        if not AGENT_ID_PATTERN.fullmatch(agent):
            raise FoundryError(
                "AI_AGENT_ID_INVALID",
                "agent_id must be 1-100 portable identifier characters.",
                details={"agent_id": value},
            )
        return agent

    @staticmethod
    def _validated_agent_model(value: Any) -> str:
        model = str(value or "").strip()
        if not AGENT_MODEL_PATTERN.fullmatch(model):
            raise FoundryError(
                "AI_AGENT_MODEL_INVALID",
                "agent_model must be 1-100 portable model characters.",
                details={"agent_model": value},
            )
        return model

    @staticmethod
    def _validated_lease(value: Any) -> int:
        if value is None:
            return DEFAULT_AGENT_LEASE_SECONDS
        if type(value) is not int or not MIN_AGENT_LEASE_SECONDS <= value <= MAX_AGENT_LEASE_SECONDS:
            raise FoundryError(
                "AI_AGENT_LEASE_INVALID",
                f"lease_seconds must be an integer between {MIN_AGENT_LEASE_SECONDS} and {MAX_AGENT_LEASE_SECONDS}.",
                details={"lease_seconds": value},
            )
        return value

    def _store_validation_errors(
        self,
        request_id: str,
        agent_id: str,
        errors: list[dict[str, Any]],
        body: str,
    ) -> None:
        """Record a failed answer without consuming the request."""

        document = canonical_json(
            {
                "valid": False,
                "errors": errors[:20],
                "response_sha256": sha256_bytes(body.encode("utf-8")),
                "response_bytes": len(body.encode("utf-8")),
            }
        )
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE ai_agent_requests
                   SET validation_json=?, agent_id=?, state=?
                   WHERE request_id=? AND agent_id=? AND state IN (?,?)""",
                (
                    document,
                    agent_id,
                    AGENT_STATE_PENDING,
                    request_id,
                    agent_id,
                    AGENT_STATE_PENDING,
                    AGENT_STATE_CLAIMED,
                ),
            )


def _shift_seconds(timestamp: str, seconds: int) -> str:
    """Return ``timestamp`` (UTC 'Z' text) plus ``seconds`` in the same form."""

    from datetime import datetime, timedelta, timezone

    parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
