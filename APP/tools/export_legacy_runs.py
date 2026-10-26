"""Freeze legacy character-creation runs as verified zstd evidence.

The exporter deliberately has no dependency on the application runtime.  It
uses SQLite's immutable URI mode and the system ``zstd`` executable so an
export cannot silently fall back to an uncompressed or fake ``.zst`` file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


_FIELD_NAMES = ("request", "dry_run", "output", "final_plan")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INVENTORY_SCHEMA = "TianxiaFoundry.LegacyRunsEvidenceInventory.v1"
_SQL_NULL_KIND = "SQL_NULL"
_JSON_NULL_KIND = "JSON_NULL"
_VALUE_KIND = "VALUE"
_ZSTD_TIMEOUT_SECONDS = 120


class LegacyRunExportError(RuntimeError):
    """A fail-closed legacy evidence export error."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _absolute_without_symlinks(path: Path, *, label: str) -> Path:
    """Resolve a path while rejecting every existing symlink component."""

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            raise LegacyRunExportError(f"{label} contains a symlink: {current}")
    return absolute


def _require_source_db(path: Path) -> Path:
    source = _absolute_without_symlinks(path, label="source database")
    if not source.exists() or not source.is_file():
        raise LegacyRunExportError(f"source database is not a regular file: {source}")
    return source


def _require_source_root(path: Path) -> Path:
    root = _absolute_without_symlinks(path, label="source data root")
    if not root.exists() or not root.is_dir():
        raise LegacyRunExportError(f"source data root is not a directory: {root}")
    return root


def _prepare_output_root(path: Path) -> Path:
    output = _absolute_without_symlinks(path, label="output root")
    if output.exists() and not output.is_dir():
        raise LegacyRunExportError(f"output root is not a directory: {output}")
    return output


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _open_immutable_database(source: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(source), safe='/:')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise LegacyRunExportError(f"could not open source database read-only: {exc}") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def _find_zstd(explicit: str | Path | None = None) -> str:
    candidate = str(explicit) if explicit is not None else shutil.which("zstd")
    if not candidate:
        raise LegacyRunExportError(
            "zstd executable is unavailable; install zstd or supply --zstd PATH (no fake codec is used)"
        )
    resolved = shutil.which(candidate) if os.path.sep not in candidate else candidate
    if not resolved or not os.access(resolved, os.X_OK):
        raise LegacyRunExportError(f"zstd executable is unavailable or not executable: {candidate}")
    return resolved


def _run_zstd(executable: str, args: list[str], payload: bytes) -> bytes:
    try:
        completed = subprocess.run(
            [executable, *args],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=_ZSTD_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LegacyRunExportError("zstd failed while processing an evidence field") from exc
    return completed.stdout


def _compress_zstd(executable: str, payload: bytes) -> bytes:
    return _run_zstd(executable, ["-q", "-T1", "-c"], payload)


def _decompress_zstd(executable: str, payload: bytes) -> bytes:
    return _run_zstd(executable, ["-q", "-d", "-c"], payload)


def _validate_run_id(run_id: Any) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise LegacyRunExportError(
            "run_id is not a reversible filesystem-safe identifier: "
            f"{run_id!r}"
        )
    return run_id


def _parse_json_field(raw: Any, *, run_id: str, field: str) -> tuple[Any, str]:
    if raw is None:
        # The artifact stores canonical JSON null; inventory metadata retains
        # the distinction from a SQL TEXT value containing the JSON literal
        # ``null``.
        return None, _SQL_NULL_KIND
    if not isinstance(raw, str):
        raise LegacyRunExportError(f"{run_id}/{field} is not TEXT or SQL NULL")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LegacyRunExportError(f"malformed JSON in {run_id}/{field}") from exc
    return value, _JSON_NULL_KIND if value is None else _VALUE_KIND


def _field_payload(
    executable: str,
    *,
    run_id: str,
    field: str,
    raw: Any,
    relative_path: str,
) -> tuple[bytes, dict[str, Any]]:
    value, null_kind = _parse_json_field(raw, run_id=run_id, field=field)
    uncompressed = _canonical_json(value).encode("utf-8")
    compressed = _compress_zstd(executable, uncompressed)
    # Verify the actual codec output before anything is made visible under
    # evidence/runs.  This also proves canonical JSON and UTF-8 round-trip.
    if _decompress_zstd(executable, compressed) != uncompressed:
        raise LegacyRunExportError(f"zstd round-trip mismatch in {run_id}/{field}")
    try:
        decoded = json.loads(uncompressed.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover - encoder invariant
        raise LegacyRunExportError(f"internal JSON round-trip failure in {run_id}/{field}") from exc
    if _canonical_json(decoded).encode("utf-8") != uncompressed:
        raise LegacyRunExportError(f"canonical JSON round-trip mismatch in {run_id}/{field}")
    return compressed, {
        "path": relative_path,
        "null_kind": null_kind,
        "compressed_sha256": _sha256_bytes(compressed),
        "compressed_bytes": len(compressed),
        "uncompressed_sha256": _sha256_bytes(uncompressed),
        "uncompressed_bytes": len(uncompressed),
    }


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _existing_tree_matches(target: Path, expected: dict[str, bytes]) -> bool:
    _absolute_without_symlinks(target, label="existing output")
    if target.is_symlink() or not target.is_dir():
        raise LegacyRunExportError(f"existing run output is not a directory: {target}")
    actual: dict[str, bytes] = {}
    for candidate in target.rglob("*"):
        if candidate.is_symlink():
            raise LegacyRunExportError(f"existing output contains a symlink: {candidate}")
        if candidate.is_dir():
            raise LegacyRunExportError(f"existing output contains an unexpected directory: {candidate}")
        if candidate.is_file():
            actual[candidate.relative_to(target).as_posix()] = candidate.read_bytes()
    return actual == expected


def _existing_file_matches(path: Path, expected: bytes) -> bool:
    _absolute_without_symlinks(path, label="existing inventory")
    if path.is_symlink() or not path.is_file():
        raise LegacyRunExportError(f"existing inventory is not a regular file: {path}")
    return path.read_bytes() == expected


def _rows(connection: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    try:
        return connection.execute(
            """
            SELECT run_id, project_id, status,
                   request_json, dry_run_json, output_json, final_plan_json
            FROM character_creation_runs
            ORDER BY run_id COLLATE BINARY
            """
        )
    except sqlite3.Error as exc:
        raise LegacyRunExportError(
            "source database does not expose the expected character_creation_runs JSON columns"
        ) from exc


def export_legacy_runs(
    source_db: str | Path,
    output_root: str | Path,
    *,
    source_data_root: str | Path | None = None,
    zstd_executable: str | Path | None = None,
) -> dict[str, Any]:
    """Export every legacy run from ``source_db`` into ``output_root``.

    ``output_root`` is a separate evidence root; files land beneath its
    ``evidence/runs`` child.  Existing identical evidence is accepted as an
    idempotent rerun, while any conflicting byte is rejected before it can be
    overwritten.
    """

    source = _require_source_db(Path(source_db))
    source_root = _require_source_root(Path(source_data_root) if source_data_root is not None else source.parent)
    output = _prepare_output_root(Path(output_root))
    if _paths_overlap(source_root, output) or _paths_overlap(source.parent, output):
        raise LegacyRunExportError(
            "output root overlaps the source database/data root; P0-4 always requires "
            "a separate evidence root"
        )
    executable = _find_zstd(zstd_executable)
    source_sha256_before, source_bytes = _sha256_file(source)

    output.mkdir(parents=True, exist_ok=True)
    evidence_root = output / "evidence"
    runs_root = evidence_root / "runs"
    _absolute_without_symlinks(evidence_root, label="evidence output")
    _absolute_without_symlinks(runs_root, label="runs output")
    evidence_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)
    inventory_path = runs_root / "inventory.json"

    staging = Path(tempfile.mkdtemp(prefix=".legacy-runs-", dir=str(runs_root)))
    inventory_runs: list[dict[str, Any]] = []
    staged_payloads: dict[str, dict[str, bytes]] = {}
    connection: sqlite3.Connection | None = None
    try:
        connection = _open_immutable_database(source)
        for row in _rows(connection):
            run_id = _validate_run_id(row["run_id"])
            if any(item["run_id"] == run_id for item in inventory_runs):
                raise LegacyRunExportError(f"duplicate run_id in source database: {run_id}")
            run_directory = staging / run_id
            run_directory.mkdir()
            fields: dict[str, Any] = {}
            payloads: dict[str, bytes] = {}
            for field in _FIELD_NAMES:
                payload, details = _field_payload(
                    executable,
                    run_id=run_id,
                    field=field,
                    raw=row[f"{field}_json"],
                    relative_path=f"evidence/runs/{run_id}/{field}.json.zst",
                )
                payloads[f"{field}.json.zst"] = payload
                _write_atomic(run_directory / f"{field}.json.zst", payload)
                fields[field] = details
            staged_payloads[run_id] = payloads
            inventory_runs.append(
                {
                    "run_id": run_id,
                    "project_id": row["project_id"],
                    "status": row["status"],
                    "fields": fields,
                }
            )
    except sqlite3.Error as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise LegacyRunExportError("source database read failed") from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if connection is not None:
            connection.close()

    source_sha256_after, source_bytes_after = _sha256_file(source)
    if source_sha256_after != source_sha256_before or source_bytes_after != source_bytes:
        shutil.rmtree(staging, ignore_errors=True)
        raise LegacyRunExportError("source database changed during export; no evidence was finalized")

    inventory = {
        "schema": _INVENTORY_SCHEMA,
        "source_db_sha256": source_sha256_before,
        "source_db_bytes": source_bytes,
        "row_count": len(inventory_runs),
        "runs": inventory_runs,
    }
    inventory_bytes = _canonical_json(inventory).encode("utf-8")
    preexisting_targets: set[Path] = set()
    try:
        if inventory_path.exists() or inventory_path.is_symlink():
            if not _existing_file_matches(inventory_path, inventory_bytes):
                raise LegacyRunExportError(f"conflicting existing inventory: {inventory_path}")

        # Validate every pre-existing run before committing any new directory.
        # This makes a conflict fail closed instead of overwriting one field.
        for run_id, payloads in staged_payloads.items():
            target = runs_root / run_id
            if target.exists() or target.is_symlink():
                if not _existing_tree_matches(target, payloads):
                    raise LegacyRunExportError(f"conflicting existing evidence for run: {run_id}")
                preexisting_targets.add(target)

        for run_id in staged_payloads:
            target = runs_root / run_id
            if target in preexisting_targets:
                continue
            # Create the target directory exclusively.  A target that appears
            # after the preflight is a conflict, never a merge or replacement.
            try:
                target.mkdir()
            except FileExistsError as exc:
                raise LegacyRunExportError(
                    f"conflicting existing evidence for run: {run_id}"
                ) from exc
            for filename in sorted(staged_payloads[run_id]):
                source_file = staging / run_id / filename
                destination = target / filename
                try:
                    # Hard-link then unlink is a stdlib no-replace install on
                    # the same filesystem; unlike rename, it cannot replace a
                    # destination file created by a concurrent exporter.
                    os.link(source_file, destination)
                except FileExistsError as exc:
                    raise LegacyRunExportError(
                        f"conflicting existing evidence for run: {run_id}"
                    ) from exc
                except OSError as exc:
                    raise LegacyRunExportError(
                        f"could not atomically install evidence for run: {run_id}"
                    ) from exc
                source_file.unlink()
            (staging / run_id).rmdir()
        if not inventory_path.exists():
            _write_atomic(inventory_path, inventory_bytes)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {
        "schema": _INVENTORY_SCHEMA,
        "inventory_path": str(inventory_path),
        "source_db_sha256": source_sha256_before,
        "source_db_bytes": source_bytes,
        "row_count": len(inventory_runs),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--source-data-root", type=Path)
    parser.add_argument("--zstd", dest="zstd_executable", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        result = export_legacy_runs(
            args.source_db,
            args.output_root,
            source_data_root=args.source_data_root,
            zstd_executable=args.zstd_executable,
        )
    except LegacyRunExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke tests
    raise SystemExit(main())
