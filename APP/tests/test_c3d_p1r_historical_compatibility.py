from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from combat.gate5_service import CombatService, CombatServiceError
from combat.historical_match_compat import (
    EXPECTED_CONTROLLER_LOCK_SHA256,
    EXPECTED_FINAL_STATE_SHA256,
    EXPECTED_FINAL_SUMMARY_SHA256,
    EXPECTED_MATCH_LOCK_SHA256,
    HISTORICAL_MATCH_ID,
    validate_exact_completed_predecessor,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/C3D_P1R/C3C_P3_Completed_Historical_Match_Fixture.zip"


def _install_fixture(tmp_path: Path) -> tuple[Path, Path]:
    unpacked = tmp_path / "fixture"
    with zipfile.ZipFile(FIXTURE) as archive:
        archive.extractall(unpacked)
    source = unpacked / "C3C_P3_Completed_Historical_Match_Fixture/UserData"
    data = tmp_path / "UserData"
    shutil.copytree(source, data)
    match_dir = next((data / "Combat/Matches").iterdir())
    return data, match_dir


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _expect_complete_rejection(call) -> None:
    with pytest.raises(CombatServiceError) as caught:
        call()
    assert caught.value.status_code == 409
    assert caught.value.diagnostic.code == "COMBAT_MATCH_ALREADY_COMPLETE"


def test_exact_historical_match_reopens_verifies_replays_exports_without_mutation(tmp_path: Path) -> None:
    data, match_dir = _install_fixture(tmp_path)
    before = _hashes(match_dir)
    service = CombatService(ROOT, data)

    view = service.get_match(HISTORICAL_MATCH_ID)
    summary = service.final_summary(HISTORICAL_MATCH_ID)
    verification = service.verify(HISTORICAL_MATCH_ID)
    replay = service.replay(HISTORICAL_MATCH_ID)
    export_path = service.export(HISTORICAL_MATCH_ID)

    assert view["state"]["terminal_result"] == summary["terminal_result"]
    assert view["final_summary"] == summary
    assert hashlib.sha256((match_dir / "FinalSummary.json").read_bytes()).hexdigest() == EXPECTED_FINAL_SUMMARY_SHA256
    assert hashlib.sha256((match_dir / "ControllerLock.json").read_bytes()).hexdigest() == EXPECTED_CONTROLLER_LOCK_SHA256
    assert hashlib.sha256((match_dir / "MatchLock.json").read_bytes()).hexdigest() == EXPECTED_MATCH_LOCK_SHA256
    assert verification["status"] == "PASS"
    assert verification["canonical_state_sha256"] == EXPECTED_FINAL_STATE_SHA256
    assert replay["status"] == "PASS"
    assert replay["canonical_state_sha256"] == EXPECTED_FINAL_STATE_SHA256
    assert replay["terminal_result"] == summary["terminal_result"]
    assert summary.get("portable_character_authority") is None

    with zipfile.ZipFile(export_path) as archive:
        assert archive.testzip() is None
        assert archive.read("FinalSummary.json") == (match_dir / "FinalSummary.json").read_bytes()
        assert archive.read("ControllerLock.json") == (match_dir / "ControllerLock.json").read_bytes()
        assert archive.read("MatchLock.json") == (match_dir / "MatchLock.json").read_bytes()
    assert _hashes(match_dir) == before


def test_completed_historical_match_rejects_every_control_path_without_mutation(tmp_path: Path) -> None:
    data, match_dir = _install_fixture(tmp_path)
    before = _hashes(match_dir)
    service = CombatService(ROOT, data)
    actor_id = "an_eui_early_book1_cl5"
    dummy_intent = {"decision_id": "historical", "state_version": 14, "candidate_id": "historical", "actor_id": actor_id}

    calls = (
        lambda: service.resume(HISTORICAL_MATCH_ID),
        lambda: service.pause(HISTORICAL_MATCH_ID),
        lambda: service.decision(HISTORICAL_MATCH_ID),
        lambda: service.preview(HISTORICAL_MATCH_ID, dummy_intent, []),
        lambda: service.submit_intent(HISTORICAL_MATCH_ID, dummy_intent, [], None),
        lambda: service.suggest(HISTORICAL_MATCH_ID),
        lambda: service.local_step(HISTORICAL_MATCH_ID),
        lambda: service.local_run(HISTORICAL_MATCH_ID),
        lambda: service.auto_step(HISTORICAL_MATCH_ID),
        lambda: service.provider_step(HISTORICAL_MATCH_ID),
        lambda: service.set_controller_mode(HISTORICAL_MATCH_ID, actor_id=actor_id, controller_mode="LOCAL_AUTO"),
        lambda: service.ai_frame(HISTORICAL_MATCH_ID),
        lambda: service.ai_validate(HISTORICAL_MATCH_ID, dummy_intent),
        lambda: service.ai_execute(HISTORICAL_MATCH_ID, dummy_intent, "invalid"),
    )
    for call in calls:
        _expect_complete_rejection(call)
    assert _hashes(match_dir) == before


@pytest.mark.parametrize(
    ("relative_path", "mutation"),
    [
        ("ControllerLock.json", b"\n"),
        ("MatchLock.json", b"\n"),
        ("Journal.ndjson", b"{}\n"),
        ("FinalSummary.json", b"\n"),
        ("Manifest.json", b"\n"),
        ("ControllerJournal.ndjson", b"{}\n"),
    ],
)
def test_historical_tamper_fails_closed(tmp_path: Path, relative_path: str, mutation: bytes) -> None:
    data, match_dir = _install_fixture(tmp_path)
    target = match_dir / relative_path
    target.write_bytes(target.read_bytes() + mutation)
    service = CombatService(ROOT, data)
    with pytest.raises(CombatServiceError) as caught:
        service.get_match(HISTORICAL_MATCH_ID)
    assert caught.value.diagnostic.code == "COMBAT_CONTENT_NOT_READY"


def test_exact_validator_rejects_nonterminal_missing_finalization_open_controller_and_unknown_identity(tmp_path: Path) -> None:
    _, match_dir = _install_fixture(tmp_path)
    validate_exact_completed_predecessor(match_dir, HISTORICAL_MATCH_ID)

    manifest = json.loads((match_dir / "Manifest.json").read_text())
    manifest["status"] = "ACTIVE"
    (match_dir / "Manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        validate_exact_completed_predecessor(match_dir, HISTORICAL_MATCH_ID)

    _, match_dir = _install_fixture(tmp_path / "second")
    journal = (match_dir / "Journal.ndjson").read_text().splitlines()
    (match_dir / "Journal.ndjson").write_text("\n".join(journal[:-1]) + "\n")
    with pytest.raises(ValueError):
        validate_exact_completed_predecessor(match_dir, HISTORICAL_MATCH_ID)

    _, match_dir = _install_fixture(tmp_path / "third")
    with (match_dir / "ControllerJournal.ndjson").open("a", encoding="utf-8") as handle:
        handle.write('{"record_type":"CONTROLLER_PREPARE","transaction_id":"open"}\n')
    with pytest.raises(ValueError):
        validate_exact_completed_predecessor(match_dir, HISTORICAL_MATCH_ID)

    _, match_dir = _install_fixture(tmp_path / "fourth")
    with pytest.raises(ValueError):
        validate_exact_completed_predecessor(match_dir, "match:000000000000000000000000")
