from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_bytes
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary

ROOT = Path(__file__).resolve().parents[1]


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _CrashAfterPrepare:
    def __call__(self, stage: str, context: dict) -> None:
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)


def test_missing_controller_lock_fails_before_any_match_write(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V2-MISSING-CONTROLLER-LOCK",
        maximum_rounds=20,
    )
    lock_path = session.store.match_dir / "ControllerLock.json"
    lock_path.unlink()
    before = _file_hashes(session.store.match_dir)

    with pytest.raises(ValueError, match="CONTROLLER_AUTHORITY_LOCK_INCOMPLETE"):
        Gate4Persistence(ROOT, userdata).load_match(
            session.match_id,
            recover=False,
            rebuild_manifest=False,
        )

    assert not lock_path.exists()
    assert _file_hashes(session.store.match_dir) == before


def test_incomplete_controller_lock_rejects_before_prepare_recovery(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    persistence = Gate4Persistence(ROOT, userdata)
    session = persistence.create_match(
        match_seed="R669-M4V2-PREFLIGHT-ORDER",
        maximum_rounds=20,
    )
    controller = LocalDeterministicController()
    policies = PolicyLibrary(ROOT)
    actor_id = session.engine.legal_candidates()[0].actor_id
    policy, _ = policies.for_actor(actor_id)
    choice = controller.choose_primary_action(build_decision_context(session.engine, policy))

    with pytest.raises(Gate3InjectedCrash):
        session.execute_controller_choice(
            choice,
            controller=controller,
            policy_library=policies,
            failure_injector=_CrashAfterPrepare(),
        )

    lock_path = session.store.match_dir / "ControllerLock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["interface_files"].pop("combat/choice_authority.py")
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")

    before = _file_hashes(session.store.match_dir)
    manifest_before = json.loads(session.store.manifest_path.read_text(encoding="utf-8"))
    journal_before = session.store.journal_path.read_bytes()
    controller_journal_path = session.store.match_dir / "ControllerJournal.ndjson"
    controller_journal_before = controller_journal_path.read_bytes()

    with pytest.raises(ValueError, match="CONTROLLER_AUTHORITY_LOCK_INCOMPLETE"):
        Gate4Persistence(ROOT, userdata).load_match(
            session.match_id,
            recover=True,
            rebuild_manifest=True,
        )

    assert _file_hashes(session.store.match_dir) == before
    assert json.loads(session.store.manifest_path.read_text(encoding="utf-8"))["state_version"] == manifest_before["state_version"]
    assert session.store.journal_path.read_bytes() == journal_before
    assert controller_journal_path.read_bytes() == controller_journal_before


def test_missing_required_policy_identity_fails_before_any_match_write(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V2-MISSING-POLICY-IDENTITY",
        maximum_rounds=20,
    )
    lock_path = session.store.match_dir / "ControllerLock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["policy_sha256"].pop(sorted(lock["policy_sha256"])[0])
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")
    before = _file_hashes(session.store.match_dir)

    with pytest.raises(ValueError, match="CONTROLLER_AUTHORITY_LOCK_INCOMPLETE"):
        Gate4Persistence(ROOT, userdata).load_match(session.match_id)

    assert _file_hashes(session.store.match_dir) == before


def test_controller_hash_mismatch_fails_before_any_match_write(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V2-CONTROLLER-HASH-MISMATCH",
        maximum_rounds=20,
    )
    lock_path = session.store.match_dir / "ControllerLock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["interface_files"]["combat/gate4_controller.py"] = "0" * 64
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")
    before = _file_hashes(session.store.match_dir)

    with pytest.raises(ValueError, match="CONTROLLER_POLICY_INVALID"):
        Gate4Persistence(ROOT, userdata).load_match(session.match_id)

    assert _file_hashes(session.store.match_dir) == before


def test_status_metadata_preserves_m4v2_correction_lineage() -> None:
    from app.core import APP_STATUS, APP_VERSION

    assert APP_VERSION == "0.6.6.9.2-CAT2-CANONICAL-CATALOG"
    assert APP_STATUS == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY_COMBATANT_LIBRARY_PRE_ENCOUNTER"
    version = json.loads((ROOT / "packaging/windows_portable/VERSION.json").read_text(encoding="utf-8"))
    assert version["authoritative_polished_combat_parent_sha256"] == "1896ea1d5ec61f0f8cfc42282bd84f4369ce5605cfb777d5a553efc24dea79ce"
