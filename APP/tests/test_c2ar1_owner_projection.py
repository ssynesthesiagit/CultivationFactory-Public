from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from app.core import FoundryError, sha256_file, sha256_json
from contracts.canonical import canonical_event_hash
from contracts.registry import SchemaRegistry
from projector.reducer import EffectiveStateReducer
from projector.service import _placeholder_findings, _stage_aware_coverage, _stage_aware_diagnostics
from stage2.formulas import evaluate_formula

ROOT = Path(__file__).resolve().parents[1]


def _sealed(name: str) -> dict:
    path = ROOT / name
    value = json.loads(path.read_text(encoding="utf-8"))
    seal = value.pop("seal_sha256")
    assert seal == sha256_json(value)
    value["seal_sha256"] = seal
    return value


def _proof():
    value = os.environ.get("TIANXIA_C2AR1_PROOF_DIR")
    if not value:
        pytest.skip("TIANXIA_C2AR1_PROOF_DIR is not configured")
    root = Path(value)
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    events = json.loads((root / "events.json").read_text(encoding="utf-8"))
    raw_records = json.loads((root / "locked-records.json").read_text(encoding="utf-8"))
    records = {record["record_id"]: record for record in raw_records}
    fixture = _sealed("authority/Tianxia_C2AR1_Fixture_Selections_R1.json")
    for index, (field, value) in enumerate({
        "character.identity.display_name": fixture["selections"]["display_name"],
        "character.choices.qi_cultivation_skills": fixture["selections"]["qi_cultivation_skills"],
        "character.choices.street_hardened": fixture["selections"]["street_hardened"],
        "character.choices.language": fixture["selections"]["language"],
    }.items(), start=1):
        project["user_locks"].append({"lock_id": f"lock.c2ar1.{index}", "field": field, "value": value, "created_revision": 27, "source": "test-owner-ratification"})
    project["revision"] = 27
    project["name"] = fixture["selections"]["display_name"]
    return project, events, records


def _rechain(events: list[dict]) -> list[dict]:
    result = copy.deepcopy(events)
    previous = "0" * 64
    for sequence, event in enumerate(result, start=1):
        event["sequence"] = sequence
        event["previous_event_hash"] = previous
        event["event_hash"] = "0" * 64
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    return result


def test_owner_amendment_and_baseline_pack_are_sealed_and_distinct():
    amendment = _sealed("authority/Tianxia_Core_Character_Baseline_Owner_Amendment_R1.json")
    baseline = _sealed("authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json")
    assert amendment["authority_classification"] == "OWNER_RATIFIED_RULE_AMENDMENT"
    assert baseline["installable"] is True
    classes = {rule["rule_id"]: rule["authority_classification"] for rule in baseline["rules"]}
    assert classes["tianxia.core.human.species.v1"] == "AUTHENTICATED_CANONICAL_SOURCE"
    assert classes["tianxia.core.unarmored_ac.owner_r1"] == "OWNER_RATIFIED_RULE_AMENDMENT"


def test_owner_ratified_ac_and_initiative_formulas_and_ordering():
    baseline = _sealed("authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json")
    rules = {rule["rule_id"]: rule for rule in baseline["rules"]}
    context = {"ability_scores": {"DEX": 16}, "ability_modifiers": {"DEX": 3}, "cl": 5, "pb": 3}
    ac = evaluate_formula(rules["tianxia.core.unarmored_ac.owner_r1"]["formula"]["root"], context).value
    initiative = evaluate_formula(rules["tianxia.core.initiative.owner_r1"]["formula"]["root"], context).value
    assert ac == 13
    assert initiative == 3
    assert ac + 3 == 16  # Qi Armor is a conditional bonus after selecting the base calculation.
    assert rules["tianxia.core.unarmored_ac.owner_r1"]["applicability"].startswith("Creature not wearing armor")


def test_campaign_language_binding_is_minimal_and_owner_selected():
    language = _sealed("authority/Tianxia_Campaign_Language_Binding_Fire_Qi_Proof_R1.json")
    assert language["authority_classification"] == "OWNER_SELECTED_CAMPAIGN_BINDING"
    assert language["scope"].startswith("Fire/Qi proof fixture campaign only")
    assert language["languages"] == [{"display_name": "Classical", "language_id": "tianxia.language.classical", "owner_selection_anchor": "/languages/0", "selected": True}]


def test_v3_projection_is_ready_stage_aware_and_deterministic():
    project, events, records = _proof()
    reducer = EffectiveStateReducer(SchemaRegistry(ROOT))
    first = reducer.reduce(project=project, events=events, locked_records=records)
    second = reducer.reduce(project=copy.deepcopy(project), events=copy.deepcopy(events), locked_records=copy.deepcopy(records))
    assert sha256_json(first.ledger) == sha256_json(second.ledger)
    assert sha256_json(first.rules_selection_packets) == sha256_json(second.rules_selection_packets)
    assert first.ledger["readiness"] == {
        "active_profile": "ADVANCEMENT_READY",
        "advancement": "ADVANCEMENT_READY",
        "character_sheet": "NOT_ATTEMPTED",
        "gm_screen": "NOT_ATTEMPTED",
        "combat": "NOT_ATTEMPTED",
        "profile_id": "tianxia.projection.advancement_ready.c2ar1",
        "profile_sha256": sha256_file(ROOT / "projector/contracts/C2AR1_Stage_Aware_Validation_Profile.json"),
    }
    assert first.ledger["core_stats"]["ac_base"] == 13
    assert first.ledger["core_stats"]["initiative_bonus"] == 3
    assert first.ledger["core_stats"]["hp_max"] == 38
    assert first.ledger["core_stats"]["primary_resource_max"] == 15
    assert first.ledger["core_stats"]["skill_proficiency_multipliers"]["Deception"] == 2
    assert _stage_aware_diagnostics(first.ledger, first.rules_selection_packets, first) == []
    assert _stage_aware_coverage(first.ledger, first.rules_selection_packets, first)["required_provenance_complete"] is True
    assert _placeholder_findings(first.ledger, "/ledger") == []


def test_v3_capability_coverage_preserves_display_execution_boundary():
    project, events, records = _proof()
    reduced = EffectiveStateReducer(SchemaRegistry(ROOT)).reduce(project=project, events=events, locked_records=records)
    by_id = {entry["record_id"]: entry for entry in reduced.capability_coverage}
    for record_id in ["FIRE_TAL_FLAME_LASH", "FIRE_TAL_BURNING_WEAPON", "FIRE_TAL_FIRE_WARD", "FIRE_TAL_COMBUSTIVE_STEP", "FIRE_TAL_HEAT_HAZE", "FIRE_TAL_FIREBALL_ART", "tianxia.path.qi_cultivation.feature.qi_armor"]:
        assert by_id[record_id]["coverage"]["advancement"] == "SUPPORTED"
        assert by_id[record_id]["coverage"]["combat_execution"] == "UNSUPPORTED"
        assert by_id[record_id]["display_only_not_execution_authority"] is True
    assert "BURN" in by_id["FIRE_TAL_BURNING_WEAPON"]["demonstrated_surfaces"]
    assert "REACTION" in by_id["tianxia.path.qi_cultivation.feature.qi_armor"]["demonstrated_surfaces"]


def test_mixed_schema_unsupported_kind_and_record_fail_closed():
    project, events, records = _proof()
    reducer = EffectiveStateReducer(SchemaRegistry(ROOT))
    mixed = copy.deepcopy(events)
    mixed[0]["schema_version"] = "TianxiaFoundry.AdvancementEvent.v1"
    with pytest.raises(FoundryError) as exc:
        reducer.reduce(project=project, events=mixed, locked_records=records)
    assert exc.value.code == "PROJECTION_EVENT_SCHEMA_MIXED"
    unsupported_kind = copy.deepcopy(events)
    unsupported_kind[6]["advancement"]["kind"] = "sect_trial_sphere_acquisition"
    with pytest.raises(FoundryError) as exc:
        reducer.reduce(project=project, events=_rechain(unsupported_kind), locked_records=records)
    assert exc.value.code == "PROJECTION_V3_KIND_UNSUPPORTED"
    supported = set(_sealed("projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json")["supported_record_ids"])
    unknown_record = next(record_id for record_id in sorted(records) if record_id not in supported)
    unsupported_record = copy.deepcopy(events)
    unsupported_record[6]["subject"]["record_id"] = unknown_record
    with pytest.raises(FoundryError) as exc:
        reducer.reduce(project=project, events=_rechain(unsupported_record), locked_records=records)
    assert exc.value.code == "PROJECTION_V3_RECORD_AUTHORITY_MISSING"
