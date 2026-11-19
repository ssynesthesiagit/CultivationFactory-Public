"""Checkpoints are disposable hints bound to the saved journal's exact state.

The negative controls rehash a damaged/stale checkpoint, so checking only its
internal checksums cannot satisfy these tests. All matches use disposable data.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from combat import snapshot_read
from combat.gate2_runtime_models import MatchState
from combat.gate3_reducer import canonical_state_sha256
from combat.gate3_storage import Gate3MatchStore, _snapshot_hash
from combat.gate5_service import CombatService
from tests.persistence_support import end_turn, inventory

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def checkpoint_templates(tmp_path_factory):
    data = tmp_path_factory.mktemp("snapshot-authority-live")
    service = CombatService(ROOT, data)
    session = service.persistence.create_match(match_seed="SNAPSHOT-AUTHORITY", maximum_rounds=3)
    service._read_metadata(session.match_id, session)
    templates = {}
    for boundary in ("genesis", "committed"):
        if boundary == "committed":
            end_turn(session)
        path = session.mechanical.explicit_snapshot()
        for older in session.store.snapshots_dir.glob("Snapshot_*.json"):
            if older != path:
                older.unlink()
        target = tmp_path_factory.mktemp(f"snapshot-authority-{boundary}") / "data"
        shutil.copytree(data, target)
        templates[boundary] = (
            target, session.match_id, session.engine.state.model_dump(mode="json"),
            session.engine._commanded_cui_this_turn,
        )
    return templates


def _saved(templates, tmp_path, boundary):
    template, match_id, state, commanded = templates[boundary]
    data = tmp_path / "data"
    shutil.copytree(template, data)
    store = Gate3MatchStore(data, match_id)
    path, = store.snapshots_dir.glob("Snapshot_*.json")
    return data, store, path, state, commanded


def _rewrite(path, mutate):
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    document["canonical_state_sha256"] = canonical_state_sha256(MatchState.model_validate(document["state"]))
    document["snapshot_sha256"] = _snapshot_hash(document)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _assert_fallback(data, store, state, commanded):
    service = CombatService(ROOT, data)
    # The accelerated presentation reader must reject the same checkpoint and
    # leave recovery to the full loader, without writing anything itself.
    before = inventory(store.match_dir)
    assert snapshot_read.load(service, store.match_id) is None
    assert inventory(store.match_dir) == before
    loaded = service._load_session(store.match_id)
    assert loaded.engine.state.model_dump(mode="json") == state
    assert loaded.engine._commanded_cui_this_turn == commanded
    assert any(row["code"] == "MATCH_SNAPSHOT_HASH_MISMATCH_FALLBACK"
               for row in loaded.mechanical.diagnostics)
    assert loaded.verify()["status"] == "PASS"
    expected = loaded.mechanical.replay()
    assert service.replay(store.match_id) == expected
    # A rejected hint must neither be rewritten nor deleted by the loader.
    for name, digest in before.items():
        if name.startswith("Snapshots/"):
            assert inventory(store.match_dir)[name] == digest


@pytest.mark.parametrize("boundary", ["genesis", "committed"])
def test_rehashed_snapshot_cannot_replace_journal_state(checkpoint_templates, tmp_path, boundary):
    data, store, path, state, commanded = _saved(checkpoint_templates, tmp_path, boundary)
    _rewrite(path, lambda doc: doc["state"].update(maximum_rounds=99))
    _assert_fallback(data, store, state, commanded)


@pytest.mark.parametrize("boundary", ["genesis", "committed"])
def test_rehashed_snapshot_cannot_replace_recorded_runtime_control(checkpoint_templates, tmp_path, boundary):
    data, store, path, state, commanded = _saved(checkpoint_templates, tmp_path, boundary)
    _rewrite(path, lambda doc: doc.update(commanded_cui_this_turn=not commanded))
    _assert_fallback(data, store, state, commanded)


def test_snapshot_header_must_name_the_saved_match(checkpoint_templates, tmp_path):
    data, store, path, state, commanded = _saved(checkpoint_templates, tmp_path, "committed")
    _rewrite(path, lambda doc: doc.update(match_id="match:another-fight"))
    _assert_fallback(data, store, state, commanded)


def test_genesis_checkpoint_must_use_the_zero_journal_anchor(checkpoint_templates, tmp_path):
    data, store, path, state, commanded = _saved(checkpoint_templates, tmp_path, "genesis")
    _rewrite(path, lambda doc: doc.update(last_journal_record_sha256="f" * 64))
    _assert_fallback(data, store, state, commanded)


def test_prepare_record_cannot_anchor_a_checkpoint(checkpoint_templates, tmp_path):
    data, store, path, state, commanded = _saved(checkpoint_templates, tmp_path, "committed")
    records, _ = store.read_journal()
    prepare = next(row for row in records if row["record_type"] == "PREPARE")
    _rewrite(path, lambda doc: doc.update(
        journal_record_sequence=prepare["record_sequence"],
        last_journal_record_sha256=prepare["record_sha256"],
    ))
    _assert_fallback(data, store, state, commanded)


def test_valid_checkpoint_preserves_projection_continuation_and_single_replay(
    checkpoint_templates, tmp_path, monkeypatch,
):
    data, store, path, _state, _commanded = _saved(checkpoint_templates, tmp_path, "committed")
    service = CombatService(ROOT, data)
    first = service._load_session(store.match_id)
    end_turn(first)  # leave a valid checkpoint followed by a committed suffix
    expected = first.mechanical.replay()
    state = first.engine.state.model_dump(mode="json")
    cold = CombatService(ROOT, data)
    before = inventory(store.match_dir)
    projection = snapshot_read.load(cold, store.match_id)
    assert projection is not None
    assert projection.engine.state.model_dump(mode="json") == state
    assert inventory(store.match_dir) == before

    reduced = []
    replay = cold.persistence._replay_from

    def counted(state, commits):
        commits = list(commits)
        reduced.extend(record["record_sequence"] for record in commits)
        return replay(state, commits)

    monkeypatch.setattr(cold.persistence, "_replay_from", counted)
    loaded = cold._load_session(store.match_id)
    assert loaded.engine.state.model_dump(mode="json") == state
    committed = [row["record_sequence"] for row in loaded.mechanical._records
                 if row["record_type"] == "COMMIT"]
    assert reduced == committed  # full proof must not replay the suffix twice
    assert not any(row["code"] == "MATCH_SNAPSHOT_HASH_MISMATCH_FALLBACK"
                   for row in loaded.mechanical.diagnostics)
    assert loaded.mechanical.replay() == expected
    end_turn(loaded)
    continued = loaded.mechanical.replay()
    fresh = CombatService(ROOT, data)._load_session(store.match_id)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay() == continued
