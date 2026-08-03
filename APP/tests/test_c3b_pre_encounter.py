from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest
from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.canonical import sha256_file
from combat.pre_encounter import CombatantLibraryService
from portable_character.service import PortableCharacterPackageService

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"
FIXTURE_SHA = "1bc4142ccda1c51ba9972c5938a50043ee0de0fd0b1e2cd8d62dc838e623fddd"
PROOF_QI = 11
PROOF_FOCUS = 1
PROOF_TEAM = "team:c3b.fire_qi_test"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _reseal(source: Path, target: Path, changes: dict[str, object | bytes]) -> Path:
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir() and info.filename != "SHA256SUMS.txt"}
    for name, value in changes.items():
        files[name] = value if isinstance(value, bytes) else _canonical(value)
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())).encode()
    files["SHA256SUMS.txt"] = sums
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(_zip_info(name), data)
    PortableCharacterPackageService.audit(target)
    return target


def _fixture_audit() -> dict:
    assert sha256_file(FIXTURE) == FIXTURE_SHA
    return PortableCharacterPackageService.audit(FIXTURE)


def _install(data_root: Path, package: Path = FIXTURE, *, directory: str | None = None, pointer_hash: str | None = None, project_id: str | None = None) -> Path:
    audit = PortableCharacterPackageService.audit(package)
    project_id = project_id or audit["manifest"]["project_id"]
    root = data_root / "portable_characters" / (directory or project_id)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package, root / "current.zip")
    pointer = {
        "schema_version": "TianxiaFoundry.PortableCharacterVerificationPointer.v1",
        "project_id": project_id,
        "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
        "package_path": "/untrusted/pointer/path/is/not/followed.zip",
        "package_sha256": pointer_hash or sha256_file(package),
        "combat": audit["readiness"].get("combat"),
        "combat_runtime": audit["readiness"].get("combat_runtime"),
        "combat_ready_semantics": audit["readiness"].get("combat_ready_semantics"),
    }
    (root / "current.json").write_bytes(_canonical(pointer))
    return root


def _service(tmp_path: Path, package: Path = FIXTURE) -> tuple[CombatantLibraryService, Path]:
    data = tmp_path / "data"
    _install(data, package)
    return CombatantLibraryService(ROOT, data), data


def _battlefield() -> dict:
    return json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())


def _proof_participant(entry_id: str) -> dict:
    return {
        "candidate_entry_id": entry_id,
        "team_id": PROOF_TEAM,
        "qi_current": PROOF_QI,
        "martial_focus_current": PROOF_FOCUS,
        "provenance_kind": "TEST_FIXTURE",
        "provenance_id": "pytest:c3b-proof-resources",
    }


def _proof_draft(service: CombatantLibraryService, entry_id: str):
    battlefield = _battlefield()
    return service.preview_draft(
        participants=[_proof_participant(entry_id)],
        battlefield_id=battlefield["stable_id"],
        battlefield_provenance_kind="TEST_FIXTURE",
        battlefield_provenance_id="pytest:c3b-proof-battlefield",
    )


def _tree_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_c3b_exact_fixture_candidate_is_discovered_once_and_deterministic(tmp_path):
    service, _ = _service(tmp_path)
    first = service.inventory()
    second = service.inventory()
    assert first == second
    assert first.accepted_count == 1
    assert first.blocked_count == 0
    entry = first.accepted_candidates[0]
    audit = _fixture_audit()
    assert entry.entry_id == f"combatant-library:{audit['manifest']['project_id']}:{FIXTURE_SHA[:16]}"
    assert entry.source_package_sha256 == FIXTURE_SHA
    assert entry.owner_readiness_label == "Combat Runtime Ready"
    assert entry.owner_encounter_label == "Encounter Not Attempted"
    assert entry.resource_maxima == {"resource:core.qi": 15, "resource:core.martial_focus": 1}
    assert all(row.current_value_required_at_encounter_setup for row in entry.resource_initialization_requirements)
    assert all(not row.package_build_state_is_encounter_authority for row in entry.resource_initialization_requirements)
    assert entry.provenance["display_prose_parsed"] is False
    assert entry.provenance["package_build_state_resource_values_used"] is False


@pytest.mark.parametrize("kind", ["static_only", "gm_only"])
def test_c3b_non_runtime_readiness_is_not_promoted(tmp_path, kind):
    audit = _fixture_audit()
    readiness = dict(audit["readiness"])
    if kind == "static_only":
        readiness.update({"combat": "COMBAT_SHEET_READY_STATIC_ONLY", "combat_runtime": "NOT_READY"})
    else:
        readiness.update({"combat": "NOT_ATTEMPTED_OR_CAPABILITY_BLOCKED", "combat_runtime": None, "combat_sheet": None})
    package = _reseal(FIXTURE, tmp_path / f"{kind}.zip", {"READINESS.json": readiness})
    service, _ = _service(tmp_path / kind, package)
    inventory = service.inventory()
    assert inventory.accepted_count == 0
    assert inventory.blocked_count == 1
    assert inventory.blocked_candidates[0].code == "C3B_RUNTIME_READINESS_INCOMPATIBLE"


def test_c3b_stale_and_corrupt_packages_fail_closed(tmp_path):
    data = tmp_path / "data"
    _install(data, pointer_hash="0" * 64)
    service = CombatantLibraryService(ROOT, data)
    stale = service.inventory()
    assert stale.accepted_count == 0
    assert stale.blocked_candidates[0].code == "C3B_INSTALLED_PACKAGE_STALE"

    corrupt_data = tmp_path / "corrupt-data"
    root = _install(corrupt_data)
    (root / "current.zip").write_bytes(b"not a zip")
    pointer = json.loads((root / "current.json").read_text())
    pointer["package_sha256"] = sha256_file(root / "current.zip")
    (root / "current.json").write_bytes(_canonical(pointer))
    corrupt = CombatantLibraryService(ROOT, corrupt_data).inventory()
    assert corrupt.accepted_count == 0
    assert corrupt.blocked_count == 1


def test_c3b_duplicate_identical_deduplicates_and_same_id_different_hash_conflicts(tmp_path):
    audit = _fixture_audit()
    project_id = audit["manifest"]["project_id"]
    duplicate_data = tmp_path / "duplicates"
    _install(duplicate_data, directory="copy-a")
    _install(duplicate_data, directory="copy-b")
    duplicate = CombatantLibraryService(ROOT, duplicate_data).inventory()
    assert duplicate.accepted_count == 1
    assert duplicate.duplicate_identical_count == 1

    consumer = json.loads(zipfile.ZipFile(FIXTURE).read("CONSUMER_VERIFICATION.json"))
    consumer["c3b_harmless_conflict_fixture"] = True
    altered = _reseal(FIXTURE, tmp_path / "same-id-different.zip", {"CONSUMER_VERIFICATION.json": consumer})
    conflict_data = tmp_path / "conflicts"
    _install(conflict_data, directory="copy-a", project_id=project_id)
    _install(conflict_data, altered, directory="copy-b", project_id=project_id)
    inventory = CombatantLibraryService(ROOT, conflict_data).inventory()
    assert inventory.accepted_count == 0
    assert any(row.code == "C3B_SAME_ID_DIFFERENT_PACKAGE_CONFLICT" for row in inventory.blocked_candidates)


def test_c3b_resource_initialization_is_explicit_bounded_and_non_mutating(tmp_path):
    service, data = _service(tmp_path)
    entry = service.inventory().accepted_candidates[0]
    package = next((data / "portable_characters").glob("*/current.zip"))
    before = sha256_file(package)

    for qi, focus in [(0, 0), (15, 1), (PROOF_QI, PROOF_FOCUS)]:
        result = service.validate_resource_initialization(entry.entry_id, qi_current=qi, martial_focus_current=focus, provenance_kind="TEST_FIXTURE", provenance_id="pytest:bounds")
        assert result.valid is True
        assert result.noncanonical_test_fixture is True
        assert result.canonical_owner_choice is False
        assert result.package_current_values_used is False
        assert result.package_mutated is False

    missing_qi = service.validate_resource_initialization(entry.entry_id, qi_current=None, martial_focus_current=1, provenance_kind="TEST_FIXTURE", provenance_id="pytest:missing")
    missing_focus = service.validate_resource_initialization(entry.entry_id, qi_current=2, martial_focus_current=None, provenance_kind="TEST_FIXTURE", provenance_id="pytest:missing")
    missing_provenance = service.validate_resource_initialization(entry.entry_id, qi_current=2, martial_focus_current=1, provenance_kind=None, provenance_id=None)
    assert "Current Qi is required." in missing_qi.unresolved_requirements
    assert "Current Martial Focus is required." in missing_focus.unresolved_requirements
    assert any("provenance" in row.lower() for row in missing_provenance.unresolved_requirements)

    for qi, focus in [(-1, 0), (16, 0), (0, -1), (0, 2)]:
        result = service.validate_resource_initialization(entry.entry_id, qi_current=qi, martial_focus_current=focus, provenance_kind="TEST_FIXTURE", provenance_id="pytest:range")
        assert result.valid is False
        assert result.status == "BLOCKED_RESOURCE_INITIALIZATION"
        assert result.diagnostics

    # The package contains historical build-state Qi 2, but the library entry
    # exposes maxima/requirements only and never imports it as encounter state.
    assert not hasattr(entry, "qi_current")
    assert service.validate_resource_initialization(entry.entry_id, qi_current=None, martial_focus_current=None, provenance_kind=None, provenance_id=None).valid is False
    assert sha256_file(package) == before


def test_c3b_proof_draft_is_stable_committed_and_nonpersistent(tmp_path):
    service, data = _service(tmp_path)
    entry = service.inventory().accepted_candidates[0]
    package = next((data / "portable_characters").glob("*/current.zip"))
    package_before = sha256_file(package)
    watched = {
        "data": _tree_fingerprint(data),
        "gate3": _tree_fingerprint(ROOT / "combat_gate3/retained_match"),
        "gate4": _tree_fingerprint(ROOT / "combat_gate4/retained_match"),
        "history": _tree_fingerprint(data / "combat"),
    }
    first = _proof_draft(service, entry.entry_id)
    second = _proof_draft(service, entry.entry_id)
    assert first == second
    assert first.readiness_state == "DRAFT_VALIDATED_PRE_PLACEMENT"
    assert first.participant_slots[0].team_id == PROOF_TEAM
    assert first.participant_slots[0].resource_initialization["qi_current"] == PROOF_QI
    assert first.participant_slots[0].resource_initialization["martial_focus_current"] == PROOF_FOCUS
    assert first.participant_slots[0].resource_initialization["provenance_kind"] == "TEST_FIXTURE"
    assert first.token_positions == ()
    assert first.initiative_order == ()
    assert first.controller_assignments == ()
    assert first.journal_path is None and first.match_directory is None
    assert first.persisted_event_count == 0 and first.project_events_written == 0
    assert first.is_match is False and first.is_encounter_execution_record is False
    assert first.can_roll_dice is False and first.can_start_turn is False and first.can_invoke_controllers is False
    assert first.persistent is False
    assert any(row.code == "C3B_OPPOSING_TEAM_PARTICIPANTS_REQUIRED" for row in first.unresolved_requirements)
    assert any(row.code == "C3B_TOKEN_PLACEMENT_REQUIRED" for row in first.unresolved_requirements)
    assert sha256_file(package) == package_before
    assert _tree_fingerprint(data) == watched["data"]
    assert _tree_fingerprint(ROOT / "combat_gate3/retained_match") == watched["gate3"]
    assert _tree_fingerprint(ROOT / "combat_gate4/retained_match") == watched["gate4"]
    assert _tree_fingerprint(data / "combat") == watched["history"]


def test_c3b_invalid_candidate_and_incomplete_fields_fail_closed(tmp_path):
    service, _ = _service(tmp_path)
    battlefield = _battlefield()
    invalid = service.preview_draft(
        participants=[{"candidate_entry_id": "not-installed", "team_id": PROOF_TEAM, "qi_current": 1, "martial_focus_current": 0, "provenance_kind": "TEST_FIXTURE", "provenance_id": "pytest"}],
        battlefield_id=battlefield["stable_id"], battlefield_provenance_kind="TEST_FIXTURE", battlefield_provenance_id="pytest",
    )
    assert invalid.readiness_state == "BLOCKED_INVALID_CANDIDATE"
    assert invalid.participant_slots == ()
    entry = service.inventory().accepted_candidates[0]
    incomplete = service.preview_draft(
        participants=[{"candidate_entry_id": entry.entry_id, "team_id": None, "qi_current": None, "martial_focus_current": None, "provenance_kind": None, "provenance_id": None}],
        battlefield_id=None, battlefield_provenance_kind=None, battlefield_provenance_id=None,
    )
    assert incomplete.readiness_state in {"BLOCKED_RESOURCE_INITIALIZATION", "BLOCKED_TEAM_ASSIGNMENT"}
    messages = [row.message for row in incomplete.unresolved_requirements]
    assert any("resource" in message.lower() for message in messages)
    assert any("team" in message.lower() for message in messages)
    assert any("battlefield" in message.lower() for message in messages)


def test_c3b_api_preview_and_discard_create_no_state(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "api-data")
    _install(settings.data_dir)
    original_check_schema = Draft202012Validator.check_schema
    Draft202012Validator.check_schema = classmethod(lambda cls, schema, format_checker=None: None)
    try:
        app = create_app(settings)
    finally:
        Draft202012Validator.check_schema = original_check_schema
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Foundry-Token": token}
        inventory = client.get("/api/combat/candidates").json()
        assert inventory["accepted_count"] == 1
        entry = inventory["accepted_candidates"][0]
        detail = client.get(f"/api/combat/candidates/{quote(entry['entry_id'], safe='')}").json()
        assert detail["source_package_sha256"] == FIXTURE_SHA
        before = _tree_fingerprint(settings.data_dir)
        battlefield = _battlefield()
        payload = {
            "participants": [_proof_participant(entry["entry_id"])],
            "battlefield_id": battlefield["stable_id"],
            "battlefield_provenance_kind": "TEST_FIXTURE",
            "battlefield_provenance_id": "pytest:c3b-api-battlefield",
        }
        response = client.post("/api/combat/pre-encounter-drafts/preview", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        draft = response.json()
        assert draft["readiness_state"] == "DRAFT_VALIDATED_PRE_PLACEMENT"
        assert draft["persistent"] is False and draft["is_match"] is False
        discard = client.post("/api/combat/pre-encounter-drafts/discard", headers=headers, json={"draft_id": draft["draft_id"]})
        assert discard.status_code == 200
        assert discard.json()["state_deleted"] is False
        assert _tree_fingerprint(settings.data_dir) == before


def test_c3b_owner_ui_separates_candidates_demo_drafts_and_matches():
    html = (ROOT / "static/index.html").read_text()
    js = (ROOT / "static/app.js").read_text()
    for required in [
        "Installed runtime-ready Character candidates",
        "Accepted demonstration encounter",
        "combatPreEncounterDraftResult",
        "Active / persisted matches",
        "The existing four-character demo remains separate and unchanged.",
    ]:
        assert required in html
    for label in [
        "Character ready", "GM ready", "Combat runtime ready", "Encounter setup required",
        "Current Qi required", "Current Martial Focus required", "Opponent / team completion required",
        "Battlefield owner choice not committed", "Token placement not committed",
        "Initiative not attempted", "Controllers not selected",
    ]:
        assert label in js
    assert 'qi.placeholder = "Required"' in js
    assert 'focus.placeholder = "Required"' in js
    assert 'qi.value = "2"' not in js
    assert 'api("/api/combat/pre-encounter-drafts/preview"' in js
    # Unrelated W1 owner surfaces remain present.
    for surface in ["screen-projects", "screen-catalog", "screen-packs", "screen-status", "characterZipDropZone"]:
        assert surface in html


def test_c3b_demo_authority_remains_four_characters_and_excludes_fire_qi():
    encounter = json.loads((ROOT / "combat_gate1/generated/Encounter.json").read_text())
    serialized = json.dumps(encounter, sort_keys=True)
    for stable_fragment in ["an_eui", "lee_jia", "bai_meizhen", "ling_qi"]:
        assert stable_fragment in serialized
    assert "c1a" not in serialized.lower()
    participants = [participant for team in encounter.get("teams", []) for participant in team.get("participant_ids", [])]
    assert len(participants) == 4
