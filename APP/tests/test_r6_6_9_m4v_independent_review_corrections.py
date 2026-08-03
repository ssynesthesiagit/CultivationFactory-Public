from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from combat.canonical import canonical_bytes, sha256_file
from combat.gate3_storage import (
    CHOICE_AUTHORITY_RELATIVE_PATH,
    Gate3Persistence,
    _match_lock_deterministic_hash,
)
from combat.gate4_persistence import Gate4Persistence

ROOT = Path(__file__).resolve().parents[1]


def diagnostic_code(exc: BaseException) -> str | None:
    diagnostic = getattr(exc, "diagnostic", None)
    return getattr(diagnostic, "code", None)


def test_choice_authority_is_pinned_by_new_match_and_controller_locks(tmp_path: Path) -> None:
    persistence = Gate4Persistence(ROOT, tmp_path / "UserData")
    session = persistence.create_match(match_seed="R669-M4V-LOCK-PIN", maximum_rounds=20)
    lock = json.loads(session.store.match_lock_path.read_text(encoding="utf-8"))
    identities = {row["relative_path"]: row["sha256"] for row in lock["content_identities"]}
    assert identities[CHOICE_AUTHORITY_RELATIVE_PATH] == sha256_file(ROOT / CHOICE_AUTHORITY_RELATIVE_PATH)

    controller = json.loads((session.store.match_dir / "ControllerLock.json").read_text(encoding="utf-8"))
    assert controller["interface_files"][CHOICE_AUTHORITY_RELATIVE_PATH] == sha256_file(
        ROOT / CHOICE_AUTHORITY_RELATIVE_PATH
    )


def test_choice_authority_only_tamper_rejects_existing_match(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V-CHOICE-TAMPER", maximum_rounds=20
    )
    copied = tmp_path / "tampered-source"
    shutil.copytree(ROOT, copied)
    choice_path = copied / CHOICE_AUTHORITY_RELATIVE_PATH
    choice_path.write_text(choice_path.read_text(encoding="utf-8") + "\n# adversarial mutation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CONTROLLER_POLICY_INVALID"):
        Gate4Persistence(copied, userdata).load_match(session.match_id)


def test_legacy_lock_without_choice_authority_fails_closed(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate3Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V-LEGACY-LOCK", maximum_rounds=20
    )
    lock_path = session.store.match_lock_path
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["content_identities"] = [
        row for row in lock["content_identities"]
        if row.get("relative_path") != CHOICE_AUTHORITY_RELATIVE_PATH
    ]
    lock["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock)
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")

    with pytest.raises(Exception) as caught:
        Gate3Persistence(ROOT, userdata).load_match(session.match_id)
    assert diagnostic_code(caught.value) == "MATCH_CONTENT_AUTHORITY_INCOMPLETE"
    details = caught.value.diagnostic.details
    assert details["missing_relative_paths"] == [CHOICE_AUTHORITY_RELATIVE_PATH]
    assert details["compatibility_policy"] == "FAIL_CLOSED_NO_AUTOMATIC_MIGRATION"


def test_controller_lock_without_choice_authority_fails_closed(tmp_path: Path) -> None:
    userdata = tmp_path / "UserData"
    session = Gate4Persistence(ROOT, userdata).create_match(
        match_seed="R669-M4V-CONTROLLER-LOCK", maximum_rounds=20
    )
    lock_path = session.store.match_dir / "ControllerLock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["interface_files"].pop(CHOICE_AUTHORITY_RELATIVE_PATH)
    lock_path.write_bytes(canonical_bytes(lock) + b"\n")

    with pytest.raises(ValueError, match="CONTROLLER_AUTHORITY_LOCK_INCOMPLETE"):
        Gate4Persistence(ROOT, userdata).load_match(session.match_id)


def test_map_selection_does_not_mutate_independent_inspection_state() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index("function beginCombatMapSelection")
    end = js.index("function completeCombatMapSelection", start)
    body = js[start:end]
    assert "combatSelectedActorId =" not in body
    assert "combatFollowCurrentTurn =" not in body
    assert "combatExpandedSheetSection =" not in body
    assert "combatInteractionDraft =" in body


