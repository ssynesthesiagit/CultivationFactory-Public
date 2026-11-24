"""Current saves use their data and journals, with no source-approval lifecycle."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.canonical import canonical_sha256, sha256_file
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_storage import Gate3MatchStore, _match_lock_deterministic_hash, _record_hash
from combat.gate5_service import CombatService, CombatServiceError
from combat.saved_fight_format import UNSUPPORTED_CODE, UNSUPPORTED_MESSAGE
from combat.tabletop_service import TabletopService
from tests.persistence_support import inventory

ROOT = Path(__file__).resolve().parents[1]


def _execute_end_turn(session):
    candidate = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"p06:{candidate.state_version}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=candidate.option_ids,
    ))


@pytest.fixture(scope="module")
def current_template(tmp_path_factory):
    data = tmp_path_factory.mktemp("p06-current-template")
    service = CombatService(ROOT, data)
    session = service.persistence.create_match(match_seed="P06-CURRENT", maximum_rounds=3)
    service._read_metadata(session.match_id, session)
    _execute_end_turn(service._load_session(session.match_id))
    assert service.verify(session.match_id)["status"] == "PASS"
    return data, session.match_id


@pytest.fixture
def saved(current_template, tmp_path):
    template, match_id = current_template
    data = tmp_path / "UserData"
    shutil.copytree(template, data)
    return data, match_id, Gate3MatchStore(data, match_id)


def _replace_lock(store, change):
    document = json.loads(store.match_lock_path.read_text(encoding="utf-8"))
    change(document)
    document["deterministic_payload_sha256"] = _match_lock_deterministic_hash(document)
    store.match_lock_path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def test_current_session_execute_and_cold_reload_replay_exactly(saved):
    data, match_id, store = saved
    service = CombatService(ROOT, data)
    before = service._load_session(match_id)
    version = before.engine.state.state_version
    _execute_end_turn(before)
    expected = before.mechanical.replay()
    del before, service

    cold = CombatService(ROOT, data)
    session = cold._load_session(match_id)
    assert session.engine.state.state_version > version
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay() == expected
    assert cold.replay(match_id) == expected
    lock = json.loads(store.match_lock_path.read_text(encoding="utf-8"))
    assert "engine_version" not in lock
    assert "mechanics_lock_sha256" not in lock
    assert all(row["authority_scope"] == "MATCH" for row in lock["content_identities"])
    assert not (store.match_dir / "ControllerLock.json").exists()
    assert not (store.match_dir / "SavedFightCompatibility.json").exists()


def test_engine_edit_and_obsolete_source_pins_need_no_approval(saved, tmp_path):
    data, match_id, store = saved
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "UserData"))
    engine = source / "combat/gate2_engine.py"
    original_sha = sha256_file(engine)
    _replace_lock(store, lambda doc: doc.update(
        engine_version="retired-version-description",
        content_identities=[*doc["content_identities"], {
            "identity_id": "source:gate2_engine", "authority_scope": "SOURCE",
            "relative_path": "combat/gate2_engine.py", "sha256": original_sha,
        }],
    ))
    engine.write_text(engine.read_text(encoding="utf-8") + "\n# A normal source revision.\n", encoding="utf-8")
    retired = {
        "ControllerLock.json": b"obsolete controller pin bytes\n",
        "SavedFightCompatibility.json": b"obsolete continuation approval bytes\n",
    }
    for name, content in retired.items():
        (store.match_dir / name).write_bytes(content)

    service = CombatService(source, data)
    loaded = service._load_session(match_id)
    _execute_end_turn(loaded)
    cold = CombatService(source, data)._load_session(match_id)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay() == loaded.mechanical.replay()
    assert sha256_file(engine) != original_sha
    for name, content in retired.items():
        assert (store.match_dir / name).read_bytes() == content


@pytest.mark.parametrize("damage", [
    "missing-lock", "old-lock-schema", "malformed-lock", "old-genesis-schema",
    "missing-journal", "unsupported-reducer", "invalid-control-metadata",
    "missing-targeting-settings", "old-character-bundle", "old-arena", "old-runtime-authority",
    "unknown-saved-policy", "unknown-saved-event",
])
def test_unsupported_save_is_unchanged_addressable_and_manually_deletable(saved, damage):
    data, match_id, store = saved
    if damage == "missing-lock":
        store.match_lock_path.unlink()
    elif damage == "old-lock-schema":
        store.match_lock_path.write_text('{"schema":"RetiredMatch.v0"}', encoding="utf-8")
    elif damage == "malformed-lock":
        store.match_lock_path.write_text("[", encoding="utf-8")
    elif damage == "old-genesis-schema":
        store.genesis_path.write_text('{"schema":"RetiredGenesis.v0"}', encoding="utf-8")
    elif damage == "missing-journal":
        store.journal_path.unlink()
    elif damage == "unsupported-reducer":
        _replace_lock(store, lambda doc: doc.update(reducer_version="RetiredReducer.v0"))
    elif damage == "invalid-control-metadata":
        path = store.match_dir / "FactoryIntegration.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["participant_control_modes"] = ["a retired layout"]
        path.write_text(json.dumps(document), encoding="utf-8")
    elif damage == "old-character-bundle":
        (store.match_dir / "Typed_Character_Bundles.json").write_text('[{"actor_template": []}]', encoding="utf-8")
    elif damage == "old-arena":
        (store.match_dir / "Arena_Battlefield.json").write_text("[]", encoding="utf-8")
    elif damage == "old-runtime-authority":
        from combat.portable_runtime_authority import RUNTIME_AUTHORITY_FILE
        (store.match_dir / RUNTIME_AUTHORITY_FILE).write_text('{"schema":"RetiredRuntime.v0"}', encoding="utf-8")
    else:
        # Internally consistent old data still cannot guess missing fight rules.
        document = json.loads(store.genesis_path.read_text(encoding="utf-8"))
        if damage == "unknown-saved-policy":
            document["initial_events"][0]["payload"]["ai_search_policy"] = 999
        elif damage == "unknown-saved-event":
            document["initial_events"][-1]["event_type"] = "RetiredContinuation.v0"
        else:
            document["initial_events"][0]["payload"].pop("targeting_policy")
        document["initial_event_log_sha256"] = canonical_sha256(document["initial_events"])
        store.genesis_path.write_text(json.dumps(document), encoding="utf-8")
        _replace_lock(store, lambda doc: doc.update(genesis_payload_sha256=canonical_sha256(document)))

    before = inventory(store.match_dir)
    service = CombatService(ROOT, data)
    for load in (service.get_match, lambda identity: TabletopService(service, data).state(identity)):
        with pytest.raises(CombatServiceError) as caught:
            load(match_id)
        assert caught.value.status_code == 409
        assert caught.value.diagnostic.code == UNSUPPORTED_CODE
        assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before
    assert any(row["match_id"] == match_id for row in service.list_matches())
    assert inventory(store.match_dir) == before
    TabletopService(service, data).delete_match(match_id)
    assert not store.match_dir.exists()
    assert service.list_matches() == []


def _rewrite_journal(store, mutate):
    """Rewrite the journal with a valid hash chain, so scanning reaches the payload."""
    records = [json.loads(line) for line in store.journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mutate(records)
    previous = "0" * 64
    lines = []
    for index, record in enumerate(records, start=1):
        record["record_sequence"] = index
        record["previous_record_sha256"] = previous
        record["record_sha256"] = _record_hash(record)
        previous = record["record_sha256"]
        lines.append(json.dumps(record))
    store.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _torn_tail(store):
    """Leave an incomplete trailing journal fragment that recovery would truncate."""
    with store.journal_path.open("ab") as handle:
        handle.write(b'{"schema":"TianxiaCombatJournalRecord.v1","record_type":"COM')


def _both_open_paths(data, match_id):
    service = CombatService(ROOT, data)
    return service, (service.get_match, lambda identity: TabletopService(service, data).state(identity))


def _assert_unsupported_and_unchanged(data, match_id, store):
    """Every open path returns the plain unsupported notice and changes no saved byte."""
    before = inventory(store.match_dir)
    service, loads = _both_open_paths(data, match_id)
    for load in loads:
        with pytest.raises(CombatServiceError) as caught:
            load(match_id)
        assert caught.value.status_code == 409
        assert caught.value.diagnostic.code == UNSUPPORTED_CODE
        assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before


def _interrupted_controller_save(data: Path) -> str:
    """Leave a save whose mechanical journal ends mid-PREPARE with its controller PREPARE recorded."""
    from combat.gate3_storage import Gate3InjectedCrash
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate4_policy import PolicyLibrary

    session = Gate4Persistence(ROOT, data).create_match(match_seed="P06-INTERRUPTED")

    def crash(stage, context):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)

    policy, _ = PolicyLibrary(ROOT).for_actor(session.engine.state.current_actor_id)
    with pytest.raises(Gate3InjectedCrash):
        session.execute_controller_choice(
            LocalDeterministicController().choose_primary_action(
                build_decision_context(session.engine, policy, for_ai=True)
            ),
            controller=LocalDeterministicController(),
            policy_library=PolicyLibrary(ROOT),
            failure_injector=crash,
        )
    return session.match_id


def _controller_rows(store):
    path = store.match_dir / "ControllerJournal.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_controller_prepare_with_unreadable_decision_is_rejected_without_touching_the_save(tmp_path):
    data = tmp_path / "UserData"
    match_id = _interrupted_controller_save(data)
    store = Gate3MatchStore(data, match_id)
    rows = _controller_rows(store)
    for row in rows:
        if row.get("record_type") == "CONTROLLER_PREPARE":
            row["primary_decision_record"] = {"explanation": "malformed"}
    (store.match_dir / "ControllerJournal.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    _torn_tail(store)
    _assert_unsupported_and_unchanged(data, match_id, store)


def test_controller_record_with_unreadable_settings_policy_is_rejected_without_touching_the_save(tmp_path):
    data = tmp_path / "UserData"
    match_id = _interrupted_controller_save(data)
    store = Gate3MatchStore(data, match_id)
    rows = _controller_rows(store)
    rows.insert(0, {"record_type": "CONTROLLER_PREPARE", "transaction_id": "orphan", "settings_policy": "bad"})
    (store.match_dir / "ControllerJournal.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    _torn_tail(store)
    _assert_unsupported_and_unchanged(data, match_id, store)


def test_known_event_with_incompatible_payload_is_rejected_without_touching_the_save(saved):
    data, match_id, store = saved

    def damage(records):
        commit = next(r for r in reversed(records) if r["record_type"] == "COMMIT" and r.get("events"))
        commit["events"][-1]["event_type"] = "ROUND_STARTED"
        commit["events"][-1]["payload"] = {}

    _rewrite_journal(store, damage)
    _torn_tail(store)
    _assert_unsupported_and_unchanged(data, match_id, store)


def test_known_event_under_a_covering_snapshot_is_rejected_without_touching_the_save(tmp_path):
    from combat.gate3_storage import _snapshot_hash

    data = tmp_path / "UserData"
    service = CombatService(ROOT, data)
    session = service.persistence.create_match(match_seed="P06-COVERED")
    _execute_end_turn(service._load_session(session.match_id))
    _execute_end_turn(service._load_session(session.match_id))
    service._load_session(session.match_id).mechanical.explicit_snapshot()
    store = Gate3MatchStore(data, session.match_id)

    def damage(records):
        commit = next(r for r in records if r["record_type"] == "COMMIT" and r.get("events"))
        commit["events"][-1]["event_type"] = "ROUND_STARTED"
        commit["events"][-1]["payload"] = {}

    _rewrite_journal(store, damage)
    # Re-anchor the snapshot to the rewritten chain so it still covers the bad commit.
    snapshot_path = next(store.snapshots_dir.glob("Snapshot_*.json"))
    document = json.loads(snapshot_path.read_text(encoding="utf-8"))
    records = [json.loads(line) for line in store.journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    anchor = next(r for r in records if r["record_sequence"] == document["journal_record_sequence"])
    document["last_journal_record_sha256"] = anchor["record_sha256"]
    document["snapshot_sha256"] = _snapshot_hash(document)
    snapshot_path.write_text(json.dumps(document) + "\n", encoding="utf-8")

    _assert_unsupported_and_unchanged(data, session.match_id, store)


def test_valid_save_with_a_torn_tail_still_opens_and_is_repaired(saved):
    data, match_id, store = saved
    complete_journal = store.journal_path.read_bytes()
    _torn_tail(store)

    service = CombatService(ROOT, data)
    session = service._load_session(match_id)
    assert session.verify()["status"] == "PASS"
    assert service.get_match(match_id)
    # Only the trailing fragment was removed; the fragment itself is preserved.
    assert store.journal_path.read_bytes() == complete_journal
    assert (store.diagnostics_dir / "TrailingPartialRecord.bin").read_bytes() == (
        b'{"schema":"TianxiaCombatJournalRecord.v1","record_type":"COM'
    )



def test_semantically_unsupported_commit_is_rejected_without_touching_the_save(saved):
    data, match_id, store = saved
    def damage(records):
        commit = next(r for r in reversed(records) if r["record_type"] == "COMMIT" and r.get("events"))
        commit["events"][-1]["event_type"] = "RetiredContinuation.v0"
    _rewrite_journal(store, damage)
    _torn_tail(store)
    before = inventory(store.match_dir)
    service, loads = _both_open_paths(data, match_id)
    for load in loads:
        with pytest.raises(CombatServiceError) as caught:
            load(match_id)
        assert caught.value.status_code == 409
        assert caught.value.diagnostic.code == UNSUPPORTED_CODE
        assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before


def test_malformed_controller_record_is_rejected_without_touching_the_save(saved):
    data, match_id, store = saved
    (store.match_dir / "ControllerJournal.ndjson").write_text("{}\n", encoding="utf-8")
    _torn_tail(store)
    before = inventory(store.match_dir)
    service, loads = _both_open_paths(data, match_id)
    for load in loads:
        with pytest.raises(CombatServiceError) as caught:
            load(match_id)
        assert caught.value.status_code == 409
        assert caught.value.diagnostic.code == UNSUPPORTED_CODE
        assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before


def test_unsupported_save_is_listed_with_a_readable_name_not_its_internal_id(saved):
    data, match_id, store = saved
    store.match_lock_path.write_text('{"schema":"RetiredMatch.v0"}', encoding="utf-8")
    row = next(r for r in CombatService(ROOT, data).list_matches() if r["match_id"] == match_id)
    assert row["status"] == "UNSUPPORTED"
    assert row["display_name"]
    assert row["display_name"] != match_id
    assert "match:" not in row["display_name"]


def test_unreadable_save_without_metadata_is_listed_with_a_plain_fallback_name(saved):
    data, match_id, store = saved
    (store.match_dir / "FactoryIntegration.json").unlink()
    store.match_lock_path.write_text('{"schema":"RetiredMatch.v0"}', encoding="utf-8")
    row = next(r for r in CombatService(ROOT, data).list_matches() if r["match_id"] == match_id)
    assert row["status"] == "UNSUPPORTED"
    assert row["display_name"].startswith("Unreadable older fight")
    assert "match:" not in row["display_name"]


def test_http_old_save_message_and_explicit_delete_without_approval_routes(saved):
    data, match_id, store = saved
    store.match_lock_path.write_text('{"schema":"RetiredMatch.v0"}', encoding="utf-8")
    before = inventory(store.match_dir)
    with TestClient(create_app(Settings.from_env(ROOT, data))) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        routes = {route.path for route in client.app.routes}
        assert not any(path.endswith(("/compatibility", "/continue-saved")) and "/combat/matches/" in path for path in routes)
        for path in (f"/api/combat/matches/{match_id}", f"/api/tabletop/matches/{match_id}/state"):
            response = client.get(path)
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == UNSUPPORTED_CODE
            assert response.json()["error"]["message"] == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before
        listed = client.get("/api/combat/matches").json()
        assert any(row["match_id"] == match_id for row in listed)
        assert store.match_dir.exists()
        response = client.delete(f"/api/tabletop/matches/{match_id}", headers=headers)
        assert response.status_code == 200, response.text
        assert not store.match_dir.exists()
