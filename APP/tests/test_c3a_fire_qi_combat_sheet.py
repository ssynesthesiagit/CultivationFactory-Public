from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import FoundryError
from combat.character_adapter_service import CharacterCombatAdapter, SOURCE_PACKAGE_SHA256
from combat.character_compilation import CombatSheet, ExecutableMechanicsLock, canonical_sha256
from portable_character.service import PortableCharacterPackageService

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip"
LOCK = ROOT / "combat/character_authority/Tianxia_Fire_Qi_Executable_Mechanics_Lock_R1.json"
REGISTRY = ROOT / "combat/character_authority/Tianxia_Fire_Qi_Combat_Primitive_Registry_R1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_once(tmp_path: Path, name: str = "ready.zip"):
    out = tmp_path / name
    artifacts = tmp_path / f"{name}.artifacts"
    result = CharacterCombatAdapter().compile(SOURCE, output_dir=artifacts, output_package=out)
    return result, out, artifacts


def recalculated_sheet(raw: dict) -> CombatSheet:
    raw = copy.deepcopy(raw)
    raw.pop("sheet_commitment_sha256", None)
    raw["sheet_commitment_sha256"] = canonical_sha256(raw)
    return CombatSheet.model_validate(raw)


def test_lock_and_registry_are_checksum_sealed_and_deterministic():
    adapter = CharacterCombatAdapter()
    assert adapter.lock.readiness == "COMBAT_READY"
    assert adapter.lock.runtime_prose_parsing is False
    assert adapter.lock.counts == {"actions": 13, "augments": 3, "blocked_material_ambiguity": 0, "executable_passive_resource": 30, "nonexecutables": 9, "passives": 9, "reactions": 3, "resources": 2, "total_classified": 39}
    assert adapter.lock.lock_sha256 == json.loads(LOCK.read_text())["lock_sha256"]
    assert adapter.registry.registry_sha256 == json.loads(REGISTRY.read_text())["registry_sha256"]


def test_exact_selected_record_inventory_is_fully_classified():
    adapter = CharacterCombatAdapter()
    files, _ = adapter._read_package(SOURCE)
    adapter._validate_lock_coverage(files)
    sources = {m.source.record_id for m in adapter.lock.mechanics} | {m.source.record_id for m in adapter.lock.classified_nonexecutables}
    assert "tianxia.sphere.fire" in sources
    assert "FIRE_TAL_HEAT_HAZE" in sources
    assert "tianxia.path.qi_cultivation.feature.qi_armor" in sources


def test_combat_sheet_projects_exact_stats_resources_and_typed_none(tmp_path: Path):
    result, _, _ = compile_once(tmp_path)
    sheet = result.combat_sheet
    assert sheet.readiness_status == "COMBAT_READY"
    assert sheet.combatant_stats.model_dump(mode="json") == {
        "cultivation_level": 5, "realm": "Mortal Realm", "species": "Human", "creature_type": "Humanoid", "size": "Medium",
        "ability_scores": {"STR": 8, "DEX": 16, "CON": 14, "INT": 17, "WIS": 12, "CHA": 8}, "proficiency_bonus": 3,
        "hit_points_maximum": 38, "armor_class": 13, "initiative_bonus": 3, "speed_ft": 30, "technique_attack_bonus": 6,
        "technique_save_dc": 14, "saving_throws": {"STR": -1, "DEX": 3, "CON": 2, "INT": 3, "WIS": 1, "CHA": -1},
        "skills": {"Arcana": 6, "Deception": 5, "History": 6, "Sleight of Hand": 6}, "equipped_weapon_ids": [], "equipped_armor_ids": []}
    resources = {x.stable_id: x for x in sheet.resources}
    assert resources["resource:core.qi"].typed_details["maximum"] == 15
    assert resources["resource:core.qi"].typed_details["encounter_start_current"] == "REQUIRED_AT_ENCOUNTER_TIME"
    assert result.unsupported_coverage["material_blockers"] == []


def test_all_selected_executable_mechanic_families_are_present(tmp_path: Path):
    result, _, _ = compile_once(tmp_path)
    ids = {m.stable_id for g in (result.combat_sheet.actions, result.combat_sheet.reactions, result.combat_sheet.augments, result.combat_sheet.passives, result.combat_sheet.resources) for m in g}
    expected = {
        "action:fire.ignite", "action:fire.conflagration", "action:fire.burning_weapon", "action:fire.flame_lash",
        "action:fire.combustive_step", "action:fire.fireball_art", "reaction:fire.fire_ward", "reaction:qi.qi_armor",
        "augment:fire.overheat_ignite", "augment:fire.lingering_conflagration", "augment:fire.heat_haze", "action:qi.meridian_regulation", "passive:fire.core_rules", "passive:cinder.fire_resistance",
        "passive:cinder.touch_damage", "passive:cinder.revealing_ember", "action:scoundrel.dirty_trick", "action:scoundrel.steal"}
    assert expected <= ids
    mechanics = {m.stable_id: m for group in (result.combat_sheet.actions, result.combat_sheet.reactions, result.combat_sheet.augments, result.combat_sheet.passives, result.combat_sheet.resources) for m in group}
    ignite = mechanics["action:fire.ignite"]
    assert ignite.damage["cl_5_10"] == "2d10"
    assert [row["id"] for row in ignite.typed_details["legal_riders"]] == ["push_5_ft", "create_fire_terrain", "increase_burn", "kindled_bonus_damage"]
    assert mechanics["augment:fire.overheat_ignite"].typed_details["self_damage_floor_hp"] == 1
    assert mechanics["augment:fire.lingering_conflagration"].typed_details["action_cost"] == "NONE"
    assert mechanics["passive:fire.core_rules"].typed_details["fire_terrain"]["same_fire_terrain_once_per_turn"] is True


def test_static_execution_validation_checks_all_30_mechanics(tmp_path: Path):
    result, _, _ = compile_once(tmp_path)
    report = result.static_validation
    assert report.status == "PASS"
    assert report.mechanics_checked == 30
    assert report.prose_interpretation_used is False
    assert report.combat_events_committed == 0 and report.dice_rolled == 0


def test_two_forced_compilations_and_reopen_are_byte_identical(tmp_path: Path):
    first, one, _ = compile_once(tmp_path, "one.zip")
    second, two, _ = compile_once(tmp_path, "two.zip")
    assert one.read_bytes() == two.read_bytes()
    assert first.output_package_sha256 == second.output_package_sha256
    reopened = PortableCharacterPackageService.audit(one)
    with zipfile.ZipFile(one) as zf:
        sheet = CombatSheet.model_validate_json(zf.read("combat/Combat_Sheet.json"))
    assert reopened["sha256"] == first.output_package_sha256
    assert sheet.sheet_commitment_sha256 == first.combat_sheet.sheet_commitment_sha256


def test_stale_source_package_hash_fails_closed(tmp_path: Path):
    stale = tmp_path / "stale.zip"
    stale.write_bytes(SOURCE.read_bytes() + b"stale")
    with pytest.raises(FoundryError) as exc:
        CharacterCombatAdapter().compile(stale)
    assert exc.value.code in {"SOURCE_IDENTITY_MISMATCH", "PORTABLE_CHARACTER_PACKAGE_INVALID"}


def test_changed_event_head_fails_closed_without_requiring_outer_hash():
    adapter = CharacterCombatAdapter()
    files, audit = adapter._read_package(SOURCE)
    changed = copy.deepcopy(audit)
    changed["manifest"]["event_head_hash"] = "0" * 64
    with pytest.raises(FoundryError) as exc:
        adapter._verify_source_identity(SOURCE, files, changed, require_exact_source_hash=False)
    assert exc.value.code == "SOURCE_IDENTITY_MISMATCH"


def test_changed_mechanics_lock_fails_checksum_validation(tmp_path: Path):
    raw = json.loads(LOCK.read_text())
    raw["readiness"] = "UNSUPPORTED_MECHANICS"
    bad = tmp_path / "bad_lock.json"; bad.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):
        ExecutableMechanicsLock.model_validate_json(bad.read_text())


def test_missing_primitive_unknown_condition_and_event_fail_static_validation(tmp_path: Path):
    result, _, _ = compile_once(tmp_path)
    raw = result.combat_sheet.model_dump(mode="json")
    raw["actions"][0]["required_primitives"].append("primitive:missing")
    raw["actions"][0]["conditions"].append("condition:missing")
    raw["actions"][0]["event_emission"].append("event:missing")
    sheet = recalculated_sheet(raw)
    with pytest.raises(FoundryError) as exc:
        CharacterCombatAdapter().static_validate(sheet)
    assert exc.value.code == "UNSUPPORTED_MECHANICS"
    codes = {x["code"] for x in exc.value.details["diagnostics"]}
    assert {"UNKNOWN_PRIMITIVE", "UNKNOWN_CONDITION", "UNKNOWN_EVENT_TYPE"} <= codes


def test_display_only_utility_never_becomes_action_and_does_not_block():
    adapter = CharacterCombatAdapter()
    action_sources = {m.source.record_id for m in adapter.lock.mechanics if m.mechanic_kind == "ACTION"}
    display = {m.source.record_id: m.classification for m in adapter.lock.classified_nonexecutables}
    assert "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE" not in action_sources
    assert display["TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"] == "NONCOMBAT_DISPLAY_ONLY"
    assert display["tianxia.path.qi_cultivation.feature.qi_sensing"] == "NONCOMBAT_DISPLAY_ONLY"


def test_unresolved_material_mechanic_blocks_lock():
    raw = json.loads(LOCK.read_text())
    blocked = copy.deepcopy(raw["classified_nonexecutables"][0])
    blocked["stable_id"] = "blocked:material"
    blocked["classification"] = "BLOCKED_MATERIAL_AMBIGUITY"
    blocked["reason"] = "test"
    raw["classified_nonexecutables"].append(blocked)
    raw["classified_nonexecutables"] = sorted(raw["classified_nonexecutables"], key=lambda x: x["stable_id"])
    raw["counts"]["nonexecutables"] += 1; raw["counts"]["total_classified"] += 1; raw["counts"]["blocked_material_ambiguity"] = 1
    raw.pop("lock_sha256"); raw["lock_sha256"] = canonical_sha256(raw)
    with pytest.raises(ValidationError):
        ExecutableMechanicsLock.model_validate(raw)


def test_resource_costs_are_nonnegative_and_underflow_is_rejected():
    adapter = CharacterCombatAdapter()
    costs = [m.resource_cost for m in adapter.lock.mechanics if m.resource_cost]
    assert costs and all(int(c["amount"]) >= 0 and c["underflow"] == "REJECT" for c in costs)


def test_duplicate_action_ids_fail_combat_sheet_validation(tmp_path: Path):
    result, _, _ = compile_once(tmp_path)
    raw = result.combat_sheet.model_dump(mode="json")
    raw["actions"].append(copy.deepcopy(raw["actions"][0]))
    raw.pop("sheet_commitment_sha256"); raw["sheet_commitment_sha256"] = canonical_sha256(raw)
    with pytest.raises(ValidationError):
        CombatSheet.model_validate(raw)


def test_combat_ready_package_preserves_character_and_gm_payloads(tmp_path: Path):
    _, ready, _ = compile_once(tmp_path)
    with zipfile.ZipFile(SOURCE) as src, zipfile.ZipFile(ready) as out:
        changed_allowed = {"PACKAGE_MANIFEST.json", "READINESS.json", "Release_Gate_Manifest.json", "SHA256SUMS.txt"}
        added = {n for n in out.namelist() if n.startswith("combat/")}
        assert {"combat/Combat_Sheet.json", "combat/Combat_Readiness.json", "combat/Executable_Mechanics_Lock.json", "combat/Execution_Provenance.json", "combat/Unsupported_Coverage.json", "combat/Combat_Build_Manifest.json"} <= added
        for name in src.namelist():
            if name not in changed_allowed:
                assert out.read(name) == src.read(name), name
        assert out.read("Tianxia_Owner_Character_Sheet_v1.json") == src.read("Tianxia_Owner_Character_Sheet_v1.json")
        assert out.read("Tianxia_GM_Character_Model_v1.json") == src.read("Tianxia_GM_Character_Model_v1.json")


def test_no_encounter_controller_combat_events_or_cpk1_registration(tmp_path: Path):
    result, ready, _ = compile_once(tmp_path)
    assert result.combat_sheet.encounter_created is False
    assert result.combat_sheet.controller_selected is False
    assert result.combat_sheet.combat_events_committed == 0
    assert result.combat_sheet.dice_rolled == 0
    with zipfile.ZipFile(ready) as zf:
        readiness = json.loads(zf.read("READINESS.json"))
        manifest = json.loads(zf.read("PACKAGE_MANIFEST.json"))
    assert readiness["encounter"] == "NOT_ATTEMPTED"
    assert readiness["controller_selection"] == "NOT_ATTEMPTED"
    assert readiness["cpk1_schemas_registered"] is False
    assert manifest["cpk1_schemas_registered"] is False
    registry = (ROOT / "contracts/registry.py").read_text(encoding="utf-8")
    assert "c3a" not in registry.lower() and "combat_sheet.v1" not in registry.lower()
