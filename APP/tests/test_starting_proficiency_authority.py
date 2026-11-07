from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from character_creation.starting_proficiency_authority import (
    CONTRACT_SCHEMA,
    VALIDATED_SCHEMA,
    build_starting_proficiency_choice_contract,
    validate_starting_proficiency_choices,
)


AUTHORITY_ROOT = Path(__file__).parents[1] / "non_sphere_authority" / "authority"
BACKGROUND_SOURCE = AUTHORITY_ROOT / "Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"


def _load_public_authority() -> tuple[dict, dict, str, dict]:
    paths_master = json.loads((AUTHORITY_ROOT / "Tianxia_Path_Index_Master_P2A.json").read_text())
    path_profiles = {
        json.loads((AUTHORITY_ROOT / row["index_file"]).read_text())["canonical_id"]:
        json.loads((AUTHORITY_ROOT / row["index_file"]).read_text())
        for row in paths_master["paths"]
    }
    backgrounds_doc = json.loads((AUTHORITY_ROOT / "Background_Core_Authority_v1.json").read_text())
    backgrounds = {row["background_id"]: row for row in backgrounds_doc["backgrounds"]}
    source_text = BACKGROUND_SOURCE.read_text()
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()
    language_source = {
        "path": "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
        "source_hash": source_hash,
    }
    return path_profiles, backgrounds, source_text, language_source


def _frozen_choices() -> tuple[dict, dict]:
    path_id = "tianxia.path.qi_cultivation"
    background_id = "tianxia.background.abandoned_orphan"
    origin_id = "tianxia.origin_insight.born_under_suspicion"
    choices = {
        "path_choice": {
            path_id: {"choice_id": path_id, "name": "Qi Cultivation"},
        },
        "background_choice": {
            background_id: {"choice_id": background_id, "name": "Abandoned Orphan"},
        },
        "origin_insight_choice": {
            origin_id: {
                "choice_id": origin_id,
                "name": "Born Under Suspicion",
                "summary": (
                    "You gain proficiency in Deception or Insight. "
                    "If you already have proficiency in the chosen skill, gain expertise in it."
                ),
                "source_evidence": [{
                    "source_path": "rules/origins/born-under-suspicion.md",
                    "source_hash": "a" * 64,
                    "source_anchor": "heading:born-under-suspicion",
                }],
            },
        },
    }
    allowed = {
        "path_choice": [path_id],
        "background_choice": [background_id],
        "origin_insight_choice": [origin_id],
    }
    return choices, allowed


def _build(**overrides):
    path_profiles, backgrounds, source_text, language_source = _load_public_authority()
    choices, allowed = _frozen_choices()
    values = {
        "path_profiles": path_profiles,
        "backgrounds": backgrounds,
        "choices_by_slot": choices,
        "allowed_choice_ids_by_slot": allowed,
        "campaign_language_source_text": source_text,
        "campaign_language_source": language_source,
    }
    values.update(overrides)
    return build_starting_proficiency_choice_contract(**values)


def _valid_selection() -> tuple[dict, dict]:
    return (
        {
            "path_choice": ["tianxia.path.qi_cultivation"],
            "background_choice": ["tianxia.background.abandoned_orphan"],
            "origin_insight_choice": ["tianxia.origin_insight.born_under_suspicion"],
        },
        {
            "path_skill_choices_by_path_id": {
                "tianxia.path.qi_cultivation": ["Arcana", "Medicine"],
            },
            "background_language_choices_by_background_id": {
                "tianxia.background.abandoned_orphan": ["Classical"],
            },
            "origin_skill_choices_by_origin_id": {
                "tianxia.origin_insight.born_under_suspicion": ["Deception"],
            },
        },
    )


def test_public_authority_contract_freezes_qi_background_origin_and_languages():
    contract = _build()

    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["contract_sha256"] == _build()["contract_sha256"]

    path = contract["fields"]["path_skill_choices_by_path_id"]["tianxia.path.qi_cultivation"]
    assert path["required_count"] == 2
    assert path["allowed_values"] == [
        "Arcana", "History", "Insight", "Investigation", "Medicine",
        "Nature", "Perception", "Persuasion", "Religion",
    ]

    background = contract["fields"]["background_language_choices_by_background_id"]["tianxia.background.abandoned_orphan"]
    assert background["fixed_skill_names"] == ["Deception", "Sleight of Hand"]
    assert background["fixed_tool_proficiencies"] == ["thieves' tools"]
    assert background["language_choice_count"] == 1
    assert background["allowed_values"] == [
        "Classical", "Trade Pidgin", "gang cant", "military signs",
        "ancestral liturgical language", "regional ritual language",
    ]
    assert background["language_authority"]["offered_set_complete"] is False
    assert "not a complete language registry" in background["language_authority"]["scope"]

    origin = contract["fields"]["origin_skill_choices_by_origin_id"]["tianxia.origin_insight.born_under_suspicion"]
    assert origin["required_count"] == 1
    assert origin["allowed_values"] == ["Deception", "Insight"]
    assert origin["duplicate_result"] == "expertise"
    assert origin["source_evidence"][0]["source_anchor"] == "heading:born-under-suspicion"

    assert "tianxia.path.body_refining" not in contract["fields"]["path_skill_choices_by_path_id"]


@pytest.mark.parametrize(
    "change,field,reason",
    [
        (
            lambda paths: paths["tianxia.path.qi_cultivation"]["path_profile"].update(
                skills="Choose two: Arcana and Medicine"
            ),
            "path_skill_choices_by_path_id",
            "authority_unresolved",
        ),
        (
            lambda choices: choices["origin_insight_choice"]["tianxia.origin_insight.born_under_suspicion"].update(
                summary="Choose Deception or Insight."
            ),
            "origin_skill_choices_by_origin_id",
            "source_grammar_unresolved",
        ),
    ],
)
def test_malformed_skill_authority_is_unresolved_and_not_selectable(change, field, reason):
    path_profiles, _backgrounds, _text, _source = _load_public_authority()
    choices, allowed = _frozen_choices()
    target = path_profiles if field.startswith("path_") else choices
    change(target)
    contract = _build(path_profiles=path_profiles, choices_by_slot=choices, allowed_choice_ids_by_slot=allowed)
    assert field not in contract["fields"] or not contract["fields"][field]
    assert any(row["field"] == field and row["reason"] == reason for row in contract["unresolved"])


def test_selected_unresolved_origin_with_proficiency_mechanics_blocks():
    choices, allowed = _frozen_choices()
    choices = deepcopy(choices)
    choices["origin_insight_choice"][
        "tianxia.origin_insight.born_under_suspicion"
    ]["summary"] = "Choose Deception or Insight; proficiency is granted in the chosen skill."
    contract = _build(choices_by_slot=choices, allowed_choice_ids_by_slot=allowed)
    unresolved = next(
        row for row in contract["unresolved"]
        if row["field"] == "origin_skill_choices_by_origin_id"
    )
    assert unresolved["proficiency_mechanics_present"] is True

    selected, bounded = _valid_selection()
    bounded["origin_skill_choices_by_origin_id"] = {}
    result = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )
    assert result["valid"] is False
    assert any(
        blocker["code"] == "SELECTED_ORIGIN_PROFICIENCY_AUTHORITY_UNRESOLVED"
        for blocker in result["blockers"]
    )


def test_selected_unresolved_non_proficiency_origin_remains_legal_without_map():
    choices, allowed = _frozen_choices()
    choices = deepcopy(choices)
    choices["origin_insight_choice"][
        "tianxia.origin_insight.born_under_suspicion"
    ]["summary"] = "A quiet beginning with no additional benefit."
    contract = _build(choices_by_slot=choices, allowed_choice_ids_by_slot=allowed)
    unresolved = next(
        row for row in contract["unresolved"]
        if row["field"] == "origin_skill_choices_by_origin_id"
    )
    assert unresolved["proficiency_mechanics_present"] is False

    selected, bounded = _valid_selection()
    bounded["origin_skill_choices_by_origin_id"] = {}
    result = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )
    assert result["valid"] is True
    assert result["normalized_mechanics"]["origin"] is None


def test_malformed_authenticated_language_section_fails_closed():
    _paths, _backgrounds, source_text, _source = _load_public_authority()
    contract = _build(campaign_language_source_text=source_text.replace("Classical", "Common", 1))
    assert not contract["fields"]["background_language_choices_by_background_id"]
    assert any(
        row["field"] == "background_language_choices_by_background_id"
        and row["reason"] == "authority_unresolved"
        for row in contract["unresolved"]
    )


def test_mismatched_language_source_hash_fails_closed():
    contract = _build(campaign_language_source={
        "path": "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
        "source_hash": "b" * 64,
    })
    assert not contract["fields"]["background_language_choices_by_background_id"]
    assert any(
        row["field"] == "background_language_choices_by_background_id"
        and row["reason"] == "authority_unresolved"
        for row in contract["unresolved"]
    )


def test_frozen_row_identity_mismatch_is_unresolved_without_guessing():
    choices, allowed = _frozen_choices()
    choices = deepcopy(choices)
    choices["path_choice"]["tianxia.path.qi_cultivation"]["choice_id"] = "tianxia.path.body_refining"
    contract = _build(choices_by_slot=choices, allowed_choice_ids_by_slot=allowed)
    assert not contract["fields"]["path_skill_choices_by_path_id"]
    assert any(
        row["field"] == "path_skill_choices_by_path_id"
        and row["reason"] == "frozen_row_mismatch"
        for row in contract["unresolved"]
    )


def test_validated_choices_normalize_server_owned_grants_and_expertise():
    contract = _build()
    selected, bounded = _valid_selection()
    result = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )

    assert result["schema"] == VALIDATED_SCHEMA
    assert result["valid"] is True
    assert result["blockers"] == []
    assert result["contract_sha256"] == contract["contract_sha256"]
    assert result["validation_sha256"]
    normalized = result["normalized_mechanics"]
    assert normalized["path_skill_choices_by_path_id"] == bounded["path_skill_choices_by_path_id"]
    assert normalized["background"] == {
        "background_id": "tianxia.background.abandoned_orphan",
        "fixed_skill_names": ["Deception", "Sleight of Hand"],
        "fixed_tool_proficiencies": ["thieves' tools"],
        "selected_languages": ["Classical"],
    }
    assert normalized["origin"] == {
        "origin_id": "tianxia.origin_insight.born_under_suspicion",
        "selected_skill": "Deception",
        "result": "expertise",
    }
    assert normalized["proficiencies"] == {
        "skills": ["Arcana", "Medicine", "Deception", "Sleight of Hand"],
        "tools": ["thieves' tools"],
        "languages": ["Classical"],
        "expertise": ["Deception"],
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing_path_value",
        "extra_path_id",
        "duplicate_path_value",
        "illegal_path_value",
        "missing_origin_value",
        "unselected_origin_id",
        "fixed_grant_in_bounded_choices",
        "invalid_selected_shape",
        "unknown_nested_map_key",
        "unknown_selected_id",
    ],
)
def test_model_invalid_starting_choices_fail_closed(case):
    contract = _build()
    selected, bounded = _valid_selection()
    if case == "missing_path_value":
        bounded["path_skill_choices_by_path_id"].pop("tianxia.path.qi_cultivation")
    elif case == "extra_path_id":
        bounded["path_skill_choices_by_path_id"]["tianxia.path.body_refining"] = [
            "Arcana", "Medicine",
        ]
    elif case == "duplicate_path_value":
        bounded["path_skill_choices_by_path_id"]["tianxia.path.qi_cultivation"] = [
            "Arcana", "Arcana",
        ]
    elif case == "illegal_path_value":
        bounded["path_skill_choices_by_path_id"]["tianxia.path.qi_cultivation"] = [
            "Arcana", "Stealth",
        ]
    elif case == "missing_origin_value":
        bounded["origin_skill_choices_by_origin_id"].pop(
            "tianxia.origin_insight.born_under_suspicion"
        )
    elif case == "unselected_origin_id":
        bounded["origin_skill_choices_by_origin_id"] = {"origin.unselected": ["Deception"]}
    elif case == "fixed_grant_in_bounded_choices":
        bounded["fixed_skill_names"] = ["Athletics"]
    elif case == "invalid_selected_shape":
        selected["path_choice"] = "tianxia.path.qi_cultivation"
    elif case == "unknown_nested_map_key":
        bounded["path_skill_choices_by_path_id"]["path.unselected"] = [
            "Arcana", "Medicine",
        ]
    elif case == "unknown_selected_id":
        selected["path_choice"] = ["path.unselected"]

    result = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )
    assert result["valid"] is False, case
    assert result["blockers"], case
    assert all(isinstance(blocker.get("code"), str) for blocker in result["blockers"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["policy"].update({"planner_prose_is_authority": True}),
        lambda value: value.update({"schema": "forged.schema"}),
        lambda value: value["fields"]["path_skill_choices_by_path_id"].update({
            "tianxia.path.qi_cultivation": {
                "choice_kind": "path_skill",
                "choice_id": "tianxia.path.qi_cultivation",
                "required_count": 1,
                "allowed_values": ["Arcana"],
                "source": {
                    "factory_path": "forged",
                    "source_hash": "a" * 64,
                },
            },
        }),
    ],
)
def test_tampered_or_schema_invalid_contract_is_a_blocker(mutation):
    contract = deepcopy(_build())
    mutation(contract)
    selected, bounded = _valid_selection()
    result = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )
    assert result["valid"] is False
    assert result["blockers"]
    assert any(
        blocker["code"].startswith("CONTRACT_")
        for blocker in result["blockers"]
    )


def test_invalid_shapes_never_raise_and_hashes_are_stable():
    contract = _build()
    selected, bounded = _valid_selection()
    first = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=bounded,
    )
    second = validate_starting_proficiency_choices(
        contract=deepcopy(contract),
        selected_by_slot=deepcopy(selected),
        bounded_choices=deepcopy(bounded),
    )
    assert first == second

    altered = deepcopy(bounded)
    altered["path_skill_choices_by_path_id"]["tianxia.path.qi_cultivation"] = [
        "History", "Medicine",
    ]
    changed = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=altered,
    )
    assert changed["valid"] is True
    assert changed["validation_sha256"] != first["validation_sha256"]

    for invalid_contract, invalid_selected, invalid_bounded in (
        (None, selected, bounded),
        ([], selected, bounded),
        (contract, None, bounded),
        (contract, selected, None),
        (contract, selected, {"path_skill_choices_by_path_id": []}),
    ):
        result = validate_starting_proficiency_choices(
            contract=invalid_contract,
            selected_by_slot=invalid_selected,
            bounded_choices=invalid_bounded,
        )
        assert result["valid"] is False
        assert result["validation_sha256"]
        assert result["blockers"]
