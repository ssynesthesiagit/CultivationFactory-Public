"""A durable append must either write its complete record or report failure."""
import os
from types import SimpleNamespace

import pytest

from combat import commit_diagnostics, gate4_persistence
from combat.canonical import canonical_bytes

try:
    from combat import durable_append
except ImportError:
    # On the original implementation each caller owns its own os binding.
    durable_append = None


def _diagnostic(path):
    return commit_diagnostics.record_commit_divergence(
        path, match_id="match", actor_id="actor", decision_id="decision",
        state_version=1, preview_id="preview",
        preview_post_state_sha256="before", authoritative_post_state_sha256="after",
    )


def _patch_write(monkeypatch, module, write):
    # Replace only the shared appender's module binding, not process-wide os.write.
    operations = {name: getattr(os, name) for name in
                  ("open", "fsync", "close", "O_WRONLY", "O_CREAT", "O_APPEND")}
    operations["write"] = write
    monkeypatch.setattr(module, "os", SimpleNamespace(**operations))


def test_short_writes_complete_both_records(tmp_path, monkeypatch):
    def short_write(fd, data):
        return os.write(fd, data[:3])

    _patch_write(monkeypatch, durable_append or gate4_persistence, short_write)
    if durable_append is None:
        _patch_write(monkeypatch, commit_diagnostics, short_write)
    journal = tmp_path / "ControllerJournal.ndjson"
    document = {"record_type": "CONTROLLER_COMMIT", "name": "long record"}
    gate4_persistence._append_jsonl(journal, document)
    record = _diagnostic(tmp_path)
    assert journal.read_bytes() == canonical_bytes(document) + b"\n"
    assert commit_diagnostics.diagnostic_path(tmp_path).read_bytes() == canonical_bytes(record) + b"\n"


def test_zero_progress_reports_failure_for_both_records(tmp_path, monkeypatch):
    _patch_write(monkeypatch, durable_append or gate4_persistence, lambda fd, data: 0)
    if durable_append is None:
        _patch_write(monkeypatch, commit_diagnostics, lambda fd, data: 0)
    with pytest.raises(OSError, match="no progress"):
        gate4_persistence._append_jsonl(tmp_path / "ControllerJournal.ndjson", {"record": 1})
    record = _diagnostic(tmp_path)
    assert record["persistence_error"] == "COMMIT_DIAGNOSTIC_WRITE_FAILED"
