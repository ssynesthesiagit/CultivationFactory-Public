from __future__ import annotations

import copy
import gc
import json
import os
import shutil
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.gate2_scripted import _matches, load_script
from combat.gate3_reducer import (
    GATE2_EVENT_TYPES,
    Gate3EventReducer,
    reducer_coverage_document,
)
from combat.gate3_scripted import execute_persistent_script
from combat.gate3_storage import (
    Gate3InjectedCrash,
    Gate3MatchStore,
    Gate3Persistence,
    _match_lock_deterministic_hash,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "combat_gate2/scripted/Gate2_Scripted_Fight_Input.json"
SEED = "TIANXIA-GATE2-MANUAL-0001"


@pytest.fixture(autouse=True)
def _collect_gate3_test_garbage():
    """Keep the deliberately large crash fixtures independent in one pytest process."""
    gc.collect()
    yield
    gc.collect()


class CrashAt:
    def __init__(self, stage: str):
        self.stage = stage
        self.hit = False

    def __call__(self, stage: str, context: dict) -> None:
        if stage == self.stage and not self.hit:
            self.hit = True
            raise Gate3InjectedCrash(stage)


def exact_intent(session, step_index: int) -> ActionIntent:
    script = load_script(SCRIPT_PATH)
    step = script.steps[step_index - 1]
    matches = [candidate for candidate in session.engine.legal_candidates() if _matches(candidate, step)]
    assert len(matches) == 1
    candidate = matches[0]
    return ActionIntent(
        intent_id=f"intent:script:{step_index:04d}",
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
        destination=candidate.destination,
        option_ids=step.option_ids,
        reaction_decisions=step.reaction_decisions,
    )


def run_prefix(persistence: Gate3Persistence, count: int):
    session = persistence.create_match(match_seed=SEED, maximum_rounds=20)
    for index in range(1, count + 1):
        session.execute_intent(exact_intent(session, index))
    return session


def state_identity(session) -> tuple[str, str, str, object]:
    replay = session.replay()
    return (
        replay["canonical_state_sha256"],
        replay["canonical_event_log_sha256"],
        replay["canonical_roll_log_sha256"],
        replay["terminal_result"],
    )


def strip_gate3_fields(event: dict) -> dict:
    row = copy.deepcopy(event)
    payload = row.get("payload") or {}
    row["payload"] = {
        key: value for key, value in payload.items() if not key.startswith("gate3_")
    }
    return row


def diagnostic_code(exc: BaseException) -> str | None:
    diagnostic = getattr(exc, "diagnostic", None)
    return getattr(diagnostic, "code", None)


def test_replay_completeness_declares_every_gate2_event_type() -> None:
    doc = reducer_coverage_document()
    assert doc["status"] == "PASS"
    assert doc["declared_gate2_event_type_count"] == 38
    assert doc["handled_event_type_count"] == 38
    assert doc["missing_event_types"] == []
    assert Gate3EventReducer().handled_event_types == GATE2_EVENT_TYPES
    assert doc["generic_state_patch_supported"] is False


def test_persistent_retained_fight_replays_exact_gate2_mechanics(tmp_path: Path) -> None:
    session, decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    assert len(decisions) == 31
    verify = session.verify()
    assert verify["status"] == "PASS"
    assert verify["journal_record_count"] == 63
    assert verify["commit_count"] == 31
    assert verify["event_count"] == 193
    assert verify["roll_count"] == 38

    retained_state = json.loads((ROOT / "combat_gate2/final/Gate2_Final_State.json").read_text())
    retained_events = json.loads((ROOT / "combat_gate2/final/Gate2_Final_Event_Log.json").read_text())["events"]
    retained_rolls = json.loads((ROOT / "combat_gate2/final/Gate2_Final_Roll_Log.json").read_text())["rolls"]
    replay = session.replay()
    assert replay["state"] == retained_state
    assert [strip_gate3_fields(event) for event in replay["events"]] == retained_events
    assert replay["rolls"] == retained_rolls
    assert replay["events"][-1]["event_type"] == "MATCH_ENDED"

    loaded = Gate3Persistence(ROOT, tmp_path / "UserData").load_match(session.match_id)
    assert loaded.engine.state == session.engine.state
    assert loaded.verify()["canonical_state_sha256"] == replay["canonical_state_sha256"]


@pytest.mark.parametrize(
    "stage,prefix_count,target_step",
    [
        # The terminal fixture is the largest; run it first to avoid allocator
        # fragmentation from the six smaller crash copies in constrained runners.
        ("after_terminal_commit", 30, 31),
        ("before_prepare", 4, 5),
        ("after_prepare_flush", 4, 5),
        ("during_resolution", 4, 5),
        ("after_commit_flush_before_manifest", 4, 5),
        ("during_manifest_temporary_write", 4, 5),
        ("during_snapshot_temporary_write", 9, 10),
    ],
)
def test_declared_crash_points_converge(
    tmp_path: Path, stage: str, prefix_count: int, target_step: int
) -> None:
    baseline_persistence = Gate3Persistence(ROOT, tmp_path / "baseline")
    baseline = run_prefix(baseline_persistence, target_step)
    baseline_identity = state_identity(baseline)
    # Release the deliberately large live engine before constructing the crash copy.
    del baseline
    gc.collect()

    crash_persistence = Gate3Persistence(ROOT, tmp_path / "crash")
    crashed = run_prefix(crash_persistence, prefix_count)
    injector = CrashAt(stage)
    with pytest.raises(Gate3InjectedCrash):
        crashed.execute_intent(exact_intent(crashed, target_step), failure_injector=injector)
    assert injector.hit

    recovered = crash_persistence.load_match(crashed.match_id)
    if stage == "before_prepare":
        expected = run_prefix(Gate3Persistence(ROOT, tmp_path / "before-expected"), prefix_count)
        assert state_identity(recovered) == state_identity(expected)
    else:
        assert state_identity(recovered) == baseline_identity
    if stage in {"after_prepare_flush", "during_resolution"}:
        assert any(
            row.get("code") == "MATCH_RECOVERY_PREPARED_TRANSACTION_COMPLETED"
            for row in recovered.diagnostics
        )


def test_snapshot_fallback_and_genesis_replay(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 31)
    expected = state_identity(session)
    snapshot_paths = sorted(session.store.snapshots_dir.glob("Snapshot_*.json"))
    assert len(snapshot_paths) == 3

    snapshot_paths[-1].write_text("damaged latest snapshot\n", encoding="utf-8")
    fallback = persistence.load_match(session.match_id)
    assert state_identity(fallback) == expected
    assert any(
        row.get("code") == "MATCH_SNAPSHOT_HASH_MISMATCH_FALLBACK"
        for row in fallback.diagnostics
    )

    for path in snapshot_paths:
        path.write_text("damaged snapshot\n", encoding="utf-8")
    genesis = persistence.load_match(session.match_id)
    assert state_identity(genesis) == expected
    assert any(
        row.get("code") == "MATCH_SNAPSHOT_NONE_VALID_REPLAY_FROM_GENESIS"
        for row in genesis.diagnostics
    )


def test_missing_and_stale_manifest_are_rebuilt(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 3)
    session.store.manifest_path.unlink()
    loaded = persistence.load_match(session.match_id)
    assert session.store.manifest_path.is_file()
    assert any(row.get("code") == "MATCH_MANIFEST_REBUILT" for row in loaded.diagnostics)

    doc = json.loads(session.store.manifest_path.read_text())
    doc["state_version"] = 999
    session.store.manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    loaded2 = persistence.load_match(session.match_id)
    assert loaded2.engine.state.state_version != 999
    assert any(row.get("code") == "MATCH_MANIFEST_REBUILT" for row in loaded2.diagnostics)


def test_trailing_partial_record_recovers_and_is_preserved(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 3)
    expected = state_identity(session)
    with session.store.journal_path.open("ab") as handle:
        handle.write(b'{"schema":"partial"')
        handle.flush()
        os.fsync(handle.fileno())
    loaded = persistence.load_match(session.match_id)
    assert state_identity(loaded) == expected
    assert (session.store.diagnostics_dir / "TrailingPartialRecord.bin").read_bytes() == b'{"schema":"partial"'
    assert any(
        row.get("code") == "MATCH_JOURNAL_TRAILING_PARTIAL_RECORD"
        for row in loaded.diagnostics
    )


def test_partial_commit_line_recovers_last_prepare(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 4)
    baseline = run_prefix(Gate3Persistence(ROOT, tmp_path / "baseline"), 5)
    injector = CrashAt("after_prepare_flush")
    with pytest.raises(Gate3InjectedCrash):
        session.execute_intent(exact_intent(session, 5), failure_injector=injector)
    with session.store.journal_path.open("ab") as handle:
        handle.write(b'{"schema":"TianxiaCombatJournalRecord.v1","record_type":"COM')
        handle.flush()
        os.fsync(handle.fileno())
    recovered = persistence.load_match(session.match_id)
    assert state_identity(recovered) == state_identity(baseline)


def test_middle_record_corruption_blocks(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 3)
    lines = session.store.journal_path.read_bytes().splitlines()
    row = json.loads(lines[1])
    row["post_state_sha256"] = "f" * 64
    lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    session.store.journal_path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(Exception) as exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_JOURNAL_RECORD_HASH_MISMATCH"


def test_journal_chain_mismatch_blocks(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 3)
    lines = session.store.journal_path.read_bytes().splitlines()
    row = json.loads(lines[1])
    row["previous_record_sha256"] = "a" * 64
    row["record_sha256"] = ""
    from combat.gate3_storage import _record_hash

    row["record_sha256"] = _record_hash(row)
    lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    session.store.journal_path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(Exception) as exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_JOURNAL_CHAIN_MISMATCH"


def test_missing_record_sequence_blocks(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 3)
    lines = session.store.journal_path.read_bytes().splitlines()
    session.store.journal_path.write_bytes(b"\n".join([lines[0], *lines[2:]]) + b"\n")
    with pytest.raises(Exception) as exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_JOURNAL_SEQUENCE_GAP"


def test_missing_and_mismatched_content_block(tmp_path: Path) -> None:
    source_copy = tmp_path / "source"
    shutil.copytree(ROOT, source_copy)
    persistence = Gate3Persistence(source_copy, tmp_path / "UserData")
    session = run_prefix(persistence, 2)
    target = source_copy / "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json"
    original = target.read_bytes()
    target.unlink()
    with pytest.raises(Exception) as missing:
        persistence.load_match(session.match_id)
    assert diagnostic_code(missing.value) == "MATCH_CONTENT_MISSING"
    target.write_bytes(original + b"\n")
    with pytest.raises(Exception) as mismatched:
        persistence.load_match(session.match_id)
    assert diagnostic_code(mismatched.value) == "MATCH_CONTENT_VERSION_MISMATCH"


def test_unsupported_reducer_version_blocks(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 1)
    doc = json.loads(session.store.match_lock_path.read_text())
    doc["reducer_version"] = "UnsupportedReducer.v999"
    doc["deterministic_payload_sha256"] = _match_lock_deterministic_hash(doc)
    session.store.match_lock_path.write_text(
        json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with pytest.raises(Exception) as exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_CONTENT_VERSION_MISMATCH"


def test_concurrent_writer_is_rejected(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 1)
    competing = Gate3MatchStore(tmp_path / "UserData", session.match_id)
    with competing.writer_lock():
        with pytest.raises(Exception) as exc:
            persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_STORAGE_LOCKED"


def test_path_confinement_and_match_id_validation(tmp_path: Path) -> None:
    with pytest.raises(Exception) as exc:
        Gate3MatchStore(tmp_path / "UserData", "../escape")
    assert diagnostic_code(exc.value) == "MATCH_STORAGE_PATH_REJECTED"


def test_completed_match_rejects_new_intent(tmp_path: Path) -> None:
    session = run_prefix(Gate3Persistence(ROOT, tmp_path / "UserData"), 31)
    with pytest.raises(Exception) as exc:
        session.execute_intent(
            ActionIntent(
                intent_id="intent:postterminal",
                decision_id="decision:none",
                candidate_id="candidate:none",
                state_version=session.engine.state.state_version,
                actor_id=session.engine.state.current_actor_id,
            )
        )
    assert diagnostic_code(exc.value) == "MATCH_ALREADY_COMPLETE"


def test_explicit_snapshot_and_export_use_same_layer(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 5)
    snapshot = session.explicit_snapshot()
    assert snapshot.is_file()
    hashes = session.export()
    assert sorted(hashes) == [
        "Gate3_Current_State.json",
        "Gate3_Event_Log.json",
        "Gate3_Replay_Result.json",
        "Gate3_Roll_Log.json",
    ]
    assert all((session.store.exports_dir / name).is_file() for name in hashes)
    assert persistence.list_matches()[0]["match_id"] == session.match_id


def test_fsync_is_exercised_for_prepare_and_commit(tmp_path: Path, monkeypatch) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed=SEED)
    calls = []
    real = os.fsync

    def recording(fd: int) -> None:
        calls.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", recording)
    session.execute_intent(exact_intent(session, 1))
    assert len(calls) >= 4


def test_match_lock_and_genesis_are_immutable_authority(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 1)

    lock_doc = json.loads(session.store.match_lock_path.read_text())
    lock_doc["mechanics_lock_sha256"] = "f" * 64
    session.store.match_lock_path.write_text(
        json.dumps(lock_doc, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception) as lock_exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(lock_exc.value) == "MATCH_LOCK_HASH_MISMATCH"

    # Restore the exact lock, then alter Genesis while preserving its internal
    # per-section hashes; the MatchLock payload binding must still reject it.
    lock_doc["mechanics_lock_sha256"] = session.match_lock.mechanics_lock_sha256
    lock_doc["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock_doc)
    session.store.match_lock_path.write_text(
        json.dumps(lock_doc, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    genesis_doc = json.loads(session.store.genesis_path.read_text())
    genesis_doc["commanded_cui_this_turn"] = not genesis_doc["commanded_cui_this_turn"]
    session.store.genesis_path.write_text(
        json.dumps(genesis_doc, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception) as genesis_exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(genesis_exc.value) == "MATCH_GENESIS_HASH_MISMATCH"


def test_malformed_last_complete_record_blocks(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 2)
    with session.store.journal_path.open("ab") as handle:
        handle.write(b'{"schema":"malformed-complete"}\n')
        handle.flush()
        os.fsync(handle.fileno())
    with pytest.raises(Exception) as exc:
        persistence.load_match(session.match_id)
    assert diagnostic_code(exc.value) == "MATCH_JOURNAL_RECORD_HASH_MISMATCH"


def test_abort_record_keeps_sequence_and_state_continuous(tmp_path: Path, monkeypatch) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed=SEED)
    before = state_identity(session)
    original = session.engine.execute_intent

    def deterministic_reject(intent):
        raise RuntimeError("forced deterministic reject")

    monkeypatch.setattr(session.engine, "execute_intent", deterministic_reject)
    with pytest.raises(RuntimeError):
        session.execute_intent(exact_intent(session, 1))
    assert state_identity(session) == before
    records, _ = session.store.scan_journal()
    assert [row["record_type"] for row in records] == ["PREPARE", "ABORT"]

    monkeypatch.setattr(session.engine, "execute_intent", original)
    session.execute_intent(exact_intent(session, 1))
    records2, _ = session.store.scan_journal()
    assert [row["record_sequence"] for row in records2] == [1, 2, 3, 4]
    assert [row["record_type"] for row in records2] == ["PREPARE", "ABORT", "PREPARE", "COMMIT"]


def test_commit_append_failure_does_not_advance_live_state(tmp_path: Path, monkeypatch) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed=SEED)
    expected = run_prefix(Gate3Persistence(ROOT, tmp_path / "baseline"), 1)
    before = state_identity(session)
    real_append = session.store.append_record

    def fail_commit(document):
        if document.get("record_type") == "COMMIT":
            raise OSError("forced COMMIT append failure")
        return real_append(document)

    monkeypatch.setattr(session.store, "append_record", fail_commit)
    with pytest.raises(OSError):
        session.execute_intent(exact_intent(session, 1))
    assert state_identity(session) == before

    monkeypatch.setattr(session.store, "append_record", real_append)
    recovered = persistence.load_match(session.match_id)
    assert state_identity(recovered) == state_identity(expected)
    assert any(
        row.get("code") == "MATCH_RECOVERY_PREPARED_TRANSACTION_COMPLETED"
        for row in recovered.diagnostics
    )


def test_stale_writer_metadata_is_diagnosed_and_replaced(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    session = run_prefix(persistence, 1)
    assert session.store.lock_path.read_bytes() == b""
    session.store.lock_path.write_text(
        json.dumps({"match_id": session.match_id, "pid": 999999, "opened_at": "stale"}) + "\n",
        encoding="utf-8",
    )
    loaded = persistence.load_match(session.match_id)
    assert loaded.match_id == session.match_id
    diagnostic = session.store.diagnostics_dir / "StaleWriterLockRecovered.json"
    assert diagnostic.is_file()
    assert json.loads(diagnostic.read_text())["code"] == "MATCH_STORAGE_STALE_LOCK_RECOVERED"
    assert session.store.lock_path.read_bytes() == b""


def test_gate3_generated_artifacts_rebuild_byte_identically(tmp_path: Path) -> None:
    from combat.gate3_artifacts import build_gate3_artifacts

    rebuilt = tmp_path / "combat_gate3"
    manifest = build_gate3_artifacts(rebuilt)
    assert manifest["replay_coverage_status"] == "PASS"
    expected_files = sorted(
        p.relative_to(ROOT / "combat_gate3").as_posix()
        for p in (ROOT / "combat_gate3/generated").rglob("*")
        if p.is_file()
    )
    actual_files = sorted(
        p.relative_to(rebuilt).as_posix()
        for p in rebuilt.rglob("*")
        if p.is_file()
    )
    assert actual_files == expected_files
    for rel in expected_files:
        assert (rebuilt / rel).read_bytes() == (ROOT / "combat_gate3" / rel).read_bytes()
