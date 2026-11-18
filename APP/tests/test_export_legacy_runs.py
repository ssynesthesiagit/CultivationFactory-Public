from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tools import export_legacy_runs as exporter


ZSTD = shutil.which("zstd")
pytestmark = pytest.mark.skipif(ZSTD is None, reason="system zstd executable is required")


def _make_database(path: Path, rows: list[tuple[object, ...]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE character_creation_runs(
            run_id TEXT PRIMARY KEY,
            project_id TEXT,
            status TEXT,
            request_json TEXT,
            dry_run_json TEXT,
            output_json TEXT,
            final_plan_json TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO character_creation_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def _decompress(path: Path) -> bytes:
    completed = subprocess.run(
        [str(ZSTD), "-q", "-d", "-c", str(path)],
        check=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


def _inventory(output: Path) -> dict[str, object]:
    return json.loads((output / "evidence/runs/inventory.json").read_text(encoding="utf-8"))


def test_exports_all_four_json_fields_and_distinguishes_null_kinds(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "foundry.sqlite3"
    _make_database(
        source,
        [
            (
                "cg1.run.0002",
                "project-b",
                "READY_FOR_REVIEW",
                '{"greeting":"你好"}',
                "null",
                "[1,2,3]",
                '{"plan":true}',
            ),
            (
                "cg1.run.0001",
                "project-a",
                "CANCELLED",
                None,
                '{"dry":true}',
                None,
                "{}",
            ),
        ],
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "evidence-root"

    result = exporter.export_legacy_runs(source, output, source_data_root=source_root)

    assert result["row_count"] == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    inventory = _inventory(output)
    assert inventory["row_count"] == 2
    assert [run["run_id"] for run in inventory["runs"]] == ["cg1.run.0001", "cg1.run.0002"]
    first = inventory["runs"][0]
    second = inventory["runs"][1]
    assert first["project_id"] == "project-a"
    assert first["status"] == "CANCELLED"
    assert first["fields"]["request"]["null_kind"] == "SQL_NULL"
    assert first["fields"]["output"]["null_kind"] == "SQL_NULL"
    assert second["fields"]["dry_run"]["null_kind"] == "JSON_NULL"
    assert second["fields"]["request"]["null_kind"] == "VALUE"
    for run in inventory["runs"]:
        for field in exporter._FIELD_NAMES:
            path = output / "evidence/runs" / run["run_id"] / f"{field}.json.zst"
            raw = _decompress(path)
            details = run["fields"][field]
            assert len(raw) == details["uncompressed_bytes"]
            assert hashlib.sha256(raw).hexdigest() == details["uncompressed_sha256"]
            compressed = path.read_bytes()
            assert len(compressed) == details["compressed_bytes"]
            assert hashlib.sha256(compressed).hexdigest() == details["compressed_sha256"]
            json.loads(raw.decode("utf-8"))


def test_rejects_malformed_json_without_finalizing_output(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "foundry.sqlite3"
    _make_database(source, [("run-safe", "project", "BAD", "{malformed", "{}", "{}", "{}")])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "output"

    with pytest.raises(exporter.LegacyRunExportError, match="malformed JSON"):
        exporter.export_legacy_runs(source, output, source_data_root=source_root)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not (output / "evidence/runs/inventory.json").exists()


def test_rejects_source_output_overlap_symlink_escape_and_unsafe_run_id(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "foundry.sqlite3"
    _make_database(source, [("run-safe", "project", "OK", "{}", "{}", "{}", "{}")])

    with pytest.raises(exporter.LegacyRunExportError, match="overlaps"):
        exporter.export_legacy_runs(source, source_root / "output", source_data_root=source_root)
    assert "allow_source_overlap" not in inspect.signature(exporter.export_legacy_runs).parameters
    assert "--allow-source-overlap" not in exporter.build_argument_parser().format_help()

    symlink_target = tmp_path / "real-output"
    symlink_target.mkdir()
    symlink_output = tmp_path / "symlink-output"
    symlink_output.symlink_to(symlink_target, target_is_directory=True)
    with pytest.raises(exporter.LegacyRunExportError, match="symlink"):
        exporter.export_legacy_runs(source, symlink_output, source_data_root=source_root)

    unsafe_source = source_root / "unsafe.sqlite3"
    _make_database(unsafe_source, [("../escape", "project", "OK", "{}", "{}", "{}", "{}")])
    with pytest.raises(exporter.LegacyRunExportError, match="filesystem-safe"):
        exporter.export_legacy_runs(unsafe_source, tmp_path / "unsafe-output", source_data_root=source_root)


def test_is_idempotent_and_fails_closed_on_conflicting_existing_content(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "foundry.sqlite3"
    _make_database(source, [("run-safe", "project", "OK", "{}", "{}", "{}", "{}")])
    output = tmp_path / "output"

    first = exporter.export_legacy_runs(source, output, source_data_root=source_root)
    inventory_before = (output / "evidence/runs/inventory.json").read_bytes()
    second = exporter.export_legacy_runs(source, output, source_data_root=source_root)
    assert first == second
    assert (output / "evidence/runs/inventory.json").read_bytes() == inventory_before

    conflict = output / "evidence/runs/run-safe/request.json.zst"
    conflict.write_bytes(b"not-the-original-zstd-frame")
    with pytest.raises(exporter.LegacyRunExportError, match="conflicting existing evidence"):
        exporter.export_legacy_runs(source, output, source_data_root=source_root)
    assert conflict.read_bytes() == b"not-the-original-zstd-frame"


def test_cli_reports_missing_zstd_without_creating_fake_codec(tmp_path, monkeypatch, capsys):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "foundry.sqlite3"
    _make_database(source, [])
    output = tmp_path / "output"
    monkeypatch.setattr(exporter, "_find_zstd", lambda _explicit=None: (_ for _ in ()).throw(exporter.LegacyRunExportError("zstd unavailable")))

    assert exporter.main(["--source-db", str(source), "--output-root", str(output)]) == 2
    assert "zstd unavailable" in capsys.readouterr().err
    assert not (output / "evidence/runs").exists()
