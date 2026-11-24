"""A successful controller append must write its complete canonical record.

The real os.write contract permits a short positive count. Negative controls
truncate the original writer without raising; ordinary recovery tests use full
writes and do not cover this boundary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from combat.canonical import canonical_bytes
from combat.gate4_persistence import Gate4Persistence, _append_jsonl
from combat.gate5_service import CombatService
from tests.persistence_support import end_turn

ROOT = Path(__file__).resolve().parents[1]


def test_controller_append_completes_short_positive_writes(tmp_path):
    path = tmp_path / "ControllerJournal.ndjson"
    document = {"record_type": "CONTROLLER_PREPARE", "transaction_id": "test:short", "text": "雪"}
    write = os.write
    with patch("combat.gate4_persistence.os.write", side_effect=lambda fd, data: write(fd, data[:7])):
        _append_jsonl(path, document)
    assert path.read_bytes() == canonical_bytes(document) + b"\n"
    assert json.loads(path.read_bytes()) == document


def test_controller_append_refuses_zero_progress_and_closes_descriptor(tmp_path):
    descriptors = []
    def no_progress(fd, data):
        descriptors.append(fd)
        return 0
    with patch("combat.gate4_persistence.os.write", side_effect=no_progress), \
            patch("combat.gate4_persistence.os.fsync") as flush:
        with pytest.raises(OSError, match="controller journal"):
            _append_jsonl(tmp_path / "ControllerJournal.ndjson", {"transaction_id": "test:zero"})
        flush.assert_not_called()
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_short_controller_writes_survive_cold_service_reload_and_replay(tmp_path):
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed="CONTROLLER-SHORT-WRITES")
    write = os.write
    with patch("combat.gate4_persistence.os.write", side_effect=lambda fd, data: write(fd, data[:13])):
        end_turn(session)
    cold = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    assert cold.engine.state == session.engine.state
    assert cold.mechanical.replay() == session.mechanical.replay()
    assert cold.verify()["controller_open_transactions"] == []
