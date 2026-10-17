"""Public-safe checks for the generic starting-proficiency ledger bridge."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.core import FoundryError, sha256_json
from character_creation.starting_proficiency_authority import (
    validate_starting_proficiency_choices,
)
from projector.v3_bridge import (
    _project_starting_proficiency_skills,
    _validated_starting_proficiency_lock,
)


PATH_ID = "tianxia.path.test_qi"
BACKGROUND_ID = "tianxia.background.test_orphan"
ORIGIN_ID = "tianxia.origin_insight.test_suspicion"
PROJECT_ID = "project.test.starting-proficiency-projection"
CONTENT_LOCK_HASH = "c" * 64


def _contract() -> dict:
    unsigned = {
        "schema": "TianxiaFoundry.StartingProficiencyChoiceContract.v1",
        "fields": {
            "path_skill_choices_by_path_id": {
                PATH_ID: {
                    "choice_kind": "path_skill",
                    "choice_id": PATH_ID,
                    "required_count": 2,
                    "allowed_values": [
                        "Arcana", "History", "Insight", "Investigation", "Medicine",
                        "Nature", "Perception", "Persuasion", "Religion",
                    ],
                    "source": {"factory_path": "authority/test-path.json", "source_hash": "a" * 64},
                },
            },
            "origin_skill_choices_by_origin_id": {
                ORIGIN_ID: {
                    "choice_kind": "origin_skill",
                    "choice_id": ORIGIN_ID,
                    "required_count": 1,
                    "allowed_values": ["Deception", "Insight"],
                    "duplicate_result": "expertise",
                    "source_text": "You gain proficiency in Deception or Insight.",
                    "source_evidence": [{
                        "source_path": "authority/test-origin.md",
                        "source_hash": "b" * 64,
                        "source_anchor": "heading:test-origin",
                    }],
                },
            },
            "background_language_choices_by_background_id": {
                BACKGROUND_ID: {
                    "choice_kind": "background_language",
                    "choice_id": BACKGROUND_ID,
                    "fixed_skill_names": ["Deception", "Sleight of Hand"],
                    "fixed_tool_proficiencies": ["thieves' tools"],
                    "language_choice_count": 1,
                    "resolved": True,
                    "source": {"path": "authority/test-background.json"},
                    "allowed_values": ["Classical"],
                    "language_authority": {
                        "offered_set_complete": False,
                        "offered_display_names": ["Classical"],
                        "scope": "source-backed offered display set; not a complete language registry",
                        "source": {"source_hash": "d" * 64},
                    },
                },
            },
        },
        "unresolved": [],
        "policy": {
            "fixed_background_grants_server_owned": True,
            "planner_prose_is_authority": False,
            "language_registry_complete": False,
            "origin_duplicate_proficiency_result": "expertise",
        },
    }
    return {**unsigned, "contract_sha256": sha256_json(unsigned)}


def _lock() -> tuple[dict, dict, dict, dict]:
    selected = {
        "path_choice": [PATH_ID],
        "background_choice": [BACKGROUND_ID],
        "origin_insight_choice": [ORIGIN_ID],
    }
    response_maps = {
        "path_skill_choices_by_path_id": {PATH_ID: ["Arcana", "Medicine"]},
        "origin_skill_choices_by_origin_id": {ORIGIN_ID: ["Deception"]},
        "background_language_choices_by_background_id": {BACKGROUND_ID: ["Classical"]},
    }
    contract = _contract()
    validated = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=response_maps,
    )
    assert validated["valid"] is True
    value = {
        "schema": "TianxiaFoundry.ServerDerivedStartingProficiencies.v1",
        "contract": deepcopy(contract),
        "response_maps": deepcopy(response_maps),
        "selected_by_slot": deepcopy(selected),
        "validated": deepcopy(validated),
        "binding": {
            "schema": "TianxiaFoundry.ServerDerivedStartingProficiencies.v1",
            "run_id": "cg1.test.starting-proficiency-projection",
            "project_id": PROJECT_ID,
            "starting_revision": 4,
            "content_lock_hash": CONTENT_LOCK_HASH,
            "request_sha256": "e" * 64,
            "response_sha256": "f" * 64,
        },
    }
    value_hash = sha256_json(value)
    lock = {
        "lock_id": "lock.cg1.character-choices-starting-proficiencies",
        "field": "character.choices.starting_proficiencies",
        "value": value,
        "created_revision": 4,
        "source": f"cg1-starting-proficiencies:{value_hash}:server-derived",
    }
    project = {
        "project_id": PROJECT_ID,
        "revision": 4,
        "content_lock": {"lock_hash": CONTENT_LOCK_HASH},
        "user_locks": [lock],
    }
    return project, lock, selected, response_maps


def _events() -> tuple[list[dict], dict, dict]:
    return (
        [{"subject": {"record_id": PATH_ID}}],
        {"subject": {"record_id": BACKGROUND_ID}},
        {"subject": {"record_id": ORIGIN_ID}},
    )


def test_generic_starting_lock_projects_complete_skills_and_numeric_bonuses():
    project, _lock_row, _selected, _maps = _lock()
    path_events, background, origin = _events()
    authority = _validated_starting_proficiency_lock(
        project,
        path_events=path_events,
        background_event=background,
        origin_event=origin,
        choice_snapshot=None,
    )
    result = _project_starting_proficiency_skills(
        authority["normalized_mechanics"],
        path_ids=[PATH_ID],
        background_id=BACKGROUND_ID,
        origin_id=ORIGIN_ID,
        final_mods={"STR": 0, "DEX": 2, "CON": 1, "INT": 4, "WIS": 3, "CHA": 5},
        final_pb=5,
    )

    assert result["path_skill_choices_by_path_id"] == {PATH_ID: ["Arcana", "Medicine"]}
    assert result["background_skills"] == ["Deception", "Sleight of Hand"]
    assert result["background_tools"] == ["thieves' tools"]
    assert result["selected_languages"] == ["Classical"]
    assert result["origin_skill"] == "Deception"
    assert result["origin_result"] == "expertise"
    assert result["proficient_skills"] == ["Arcana", "Deception", "Medicine", "Sleight of Hand"]
    assert result["skill_ability_map"] == {
        "Arcana": "INT",
        "Deception": "CHA",
        "Medicine": "WIS",
        "Sleight of Hand": "DEX",
    }
    assert result["skill_proficiency_multipliers"] == {
        "Arcana": 1,
        "Deception": 2,
        "Medicine": 1,
        "Sleight of Hand": 1,
    }
    assert result["skills"] == {
        "Arcana": 9,
        "Deception": 15,
        "Medicine": 8,
        "Sleight of Hand": 7,
    }
    assert result["skill_sources"] == {
        "Arcana": [PATH_ID],
        "Deception": [BACKGROUND_ID, ORIGIN_ID],
        "Medicine": [PATH_ID],
        "Sleight of Hand": [BACKGROUND_ID],
    }


@pytest.mark.parametrize("tamper", ["source", "project", "background", "expertise", "missing"])
def test_generic_starting_lock_tampering_or_event_mismatch_fails_closed(tamper):
    project, lock_row, _selected, _maps = _lock()
    path_events, background, origin = _events()
    if tamper == "source":
        lock_row["source"] = "cg1-starting-proficiencies:" + ("0" * 64) + ":server-derived"
    elif tamper == "project":
        lock_row["value"]["binding"]["project_id"] = "project.other"
        lock_row["source"] = f"cg1-starting-proficiencies:{sha256_json(lock_row['value'])}:server-derived"
    elif tamper == "background":
        background = {"subject": {"record_id": "tianxia.background.other"}}
    elif tamper == "expertise":
        lock_row["value"]["validated"]["normalized_mechanics"]["origin"]["result"] = "proficiency"
        lock_row["source"] = f"cg1-starting-proficiencies:{sha256_json(lock_row['value'])}:server-derived"
    elif tamper == "missing":
        project["user_locks"] = []

    with pytest.raises(FoundryError) as raised:
        _validated_starting_proficiency_lock(
            project,
            path_events=path_events,
            background_event=background,
            origin_event=origin,
            choice_snapshot=None,
        )
    assert raised.value.code in {
        "PROJECTION_STARTING_PROFICIENCY_LOCK_REQUIRED",
        "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
        "PROJECTION_STARTING_PROFICIENCY_SELECTION_MISMATCH",
    }
