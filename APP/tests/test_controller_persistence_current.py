"""Current controller replay and recovery are independent of source-file pins."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from combat.gate3_storage import Gate3InjectedCrash, Gate3MatchStore
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import POLICY_FILENAMES, PolicyLibrary
from combat.gate5_service import CombatService, CombatServiceError
from combat.saved_fight_format import UNSUPPORTED_CODE, UNSUPPORTED_MESSAGE
from tests.persistence_support import inventory

ROOT = Path(__file__).resolve().parents[1]


def _choice(session, policies):
    policy, _ = policies.for_actor(session.engine.state.current_actor_id)
    return LocalDeterministicController().choose_primary_action(
        build_decision_context(session.engine, policy, for_ai=True)
    )


def _execute(session, policies, *, failure_injector=None):
    session.execute_controller_choice(
        _choice(session, policies),
        controller=LocalDeterministicController(),
        policy_library=policies,
        failure_injector=failure_injector,
    )


def _crash_after_prepare(stage, context):
    if stage == "after_prepare_flush":
        raise Gate3InjectedCrash(stage)


def test_controller_source_and_policy_edits_need_no_saved_fight_approval(tmp_path):
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(match_seed="CURRENT-POLICY")
    controller_lock = session.store.match_dir / "ControllerLock.json"
    assert not controller_lock.exists()

    source = tmp_path / "source"
    shutil.copytree(
        ROOT, source,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "UserData"),
    )
    controller_path = source / "combat/gate4_controller.py"
    controller_path.write_text(controller_path.read_text(encoding="utf-8") + "\n# Current source revision.\n", encoding="utf-8")
    policy_path = source / "combat_gate4/policies" / POLICY_FILENAMES[session.engine.state.current_actor_id]
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["policy_version"] = "current-revision"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    # Retired files in an existing save are ignored and never deleted implicitly.
    controller_lock.write_bytes(b"retired source-pin metadata\n")
    loaded = Gate4Persistence(source, userdata).load_match(session.match_id)
    policies = PolicyLibrary(source)
    assert _choice(loaded, policies).record.policy_version == "current-revision"
    _execute(loaded, policies)
    reloaded = Gate4Persistence(source, userdata).load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay() == loaded.mechanical.replay()
    assert controller_lock.read_bytes() == b"retired source-pin metadata\n"


def test_controller_prepare_recovery_matches_uninterrupted_current_run(tmp_path):
    policies = PolicyLibrary(ROOT)
    uninterrupted = Gate4Persistence(ROOT, tmp_path / "normal").create_match(match_seed="CURRENT-RECOVERY")
    interrupted = Gate4Persistence(ROOT, tmp_path / "interrupted").create_match(match_seed="CURRENT-RECOVERY")
    _execute(uninterrupted, policies)
    with pytest.raises(Gate3InjectedCrash):
        _execute(interrupted, policies, failure_injector=_crash_after_prepare)

    recovered = Gate4Persistence(ROOT, tmp_path / "interrupted").load_match(interrupted.match_id)
    assert recovered.verify()["controller_open_transactions"] == []
    assert recovered.mechanical.replay() == uninterrupted.mechanical.replay()
    assert not (recovered.store.match_dir / "ControllerLock.json").exists()


def test_controller_recovery_still_rejects_changed_recorded_decision(tmp_path):
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="CURRENT-DECISION-INTEGRITY")
    with pytest.raises(Gate3InjectedCrash):
        _execute(session, PolicyLibrary(ROOT), failure_injector=_crash_after_prepare)
    journal = session.controller_journal_path
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    rows[0]["primary_decision_record"]["explanation"] += " Changed after preparation."
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    mechanical_before = session.store.journal_path.read_bytes()

    with pytest.raises(ValueError, match="CONTROLLER_DECISION_NONDETERMINISTIC"):
        Gate4Persistence(ROOT, tmp_path).load_match(session.match_id)
    assert session.store.journal_path.read_bytes() == mechanical_before


@pytest.fixture(scope="module")
def current_journal_template(tmp_path_factory):
    data = tmp_path_factory.mktemp("current-journal-template")
    session = Gate4Persistence(ROOT, data).create_match(match_seed="CURRENT-JOURNAL-FORMAT")
    return data, session.match_id


@pytest.mark.parametrize("journal_name", ["Journal.ndjson", "ControllerJournal.ndjson"])
@pytest.mark.parametrize("contents", [b"null\n", b"[]\n", b"17\n", b'[]\n{"schema":"partial"'])
def test_malformed_journal_returns_plain_error_without_changing_saved_bytes(
    current_journal_template, tmp_path, journal_name, contents,
):
    template, match_id = current_journal_template
    data = tmp_path / "UserData"
    shutil.copytree(template, data)
    store = Gate3MatchStore(data, match_id)
    (store.match_dir / journal_name).write_bytes(contents)
    before = inventory(store.match_dir)

    service = CombatService(ROOT, data)
    with pytest.raises(CombatServiceError) as caught:
        service.get_match(match_id)
    assert caught.value.status_code == 409
    assert caught.value.diagnostic.code == UNSUPPORTED_CODE
    assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
    assert inventory(store.match_dir) == before
    assert not (store.diagnostics_dir / "TrailingPartialRecord.bin").exists()
