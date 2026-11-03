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


def test_forest_hermit_bitter_root_tool_expertise_reaches_ledger_and_sheet(catalog_environment, tmp_path):
    """Authenticate the real tool choice and project it through reduce_v3 and the sheet."""
    import json
    from pathlib import Path

    from character_creation.choice_snapshot import materialize_choice_snapshot
    from character_builder.service import CharacterBuilderService
    from contracts.canonical import canonical_event_hash
    from contracts.registry import SchemaRegistry
    from projector.reducer import EffectiveStateReducer
    from project_store.service import ProjectStore
    from projector.service import _stage_aware_coverage, _stage_aware_diagnostics
    from tests.test_character_sheet_complete_character import _service
    from tests.test_projector_realm_projection import _projection_fixture
    from tests.test_tool_proficiency_registry import HERMIT, PATH_ID as QI_PATH, _build

    root = Path(__file__).resolve().parents[1]
    origin_id = "tianxia.origin_insight.bitter_root_wisdom"
    project, events, records = _projection_fixture(5)
    catalog = catalog_environment["service"]
    # Use the same immutable Background/Origin authority resolution as the
    # creation service; raw catalog rows alone do not carry Stage 2 authority.
    created = CharacterBuilderService(catalog_environment["db"]).create_project(
        working_name="Origin tool projection regression", concept="Forest herb keeper",
        target_cl=5, power_band="heroic", source_reference=None,
        creation_mode="detailed", ability_scores={"STR": 15, "CON": 14, "WIS": 12},
        selections={"background_choice": [HERMIT], "origin_insight_choice": [origin_id]},
    )
    store = ProjectStore(catalog_environment["db"])
    origin_record = catalog.get(origin_id)
    contract = _build(HERMIT, origin_id, origin_record["display_name"], origin_record["summary"])
    selected = {
        "path_choice": [QI_PATH],
        "background_choice": [HERMIT],
        "origin_insight_choice": [origin_id],
    }
    response_maps = {
        "path_skill_choices_by_path_id": {QI_PATH: ["Arcana", "Medicine"]},
        "origin_skill_choices_by_origin_id": {origin_id: ["herbalism kit"]},
        "background_language_choices_by_background_id": {},
    }
    validated = validate_starting_proficiency_choices(
        contract=contract, selected_by_slot=selected, bounded_choices=response_maps,
    )
    assert validated["valid"] is True, validated["blockers"]
    lock = next(row for row in project["user_locks"] if row["field"] == "character.choices.starting_proficiencies")
    lock["value"].update(
        contract=contract, selected_by_slot=selected, response_maps=response_maps, validated=validated,
    )
    lock["source"] = f"cg1-starting-proficiencies:{sha256_json(lock['value'])}:server-derived"

    for kind, record_id in (("background_acquisition", HERMIT), ("origin_insight_acquisition", origin_id)):
        with catalog_environment["db"].connection() as conn:
            resolver = (
                store._resolve_project_locked_background_after_proof
                if kind == "background_acquisition"
                else store._resolve_project_locked_origin_insight_after_proof
            )
            record = resolver(conn, created["project"]["project_id"], record_id)
        assert record is not None
        records[record_id] = record
        event = next(row for row in events if row["advancement"]["kind"] == kind)
        event["subject"].update(record_id=record_id, display_name=record["display_name"])
        event["content_binding"].update({
            key: record["content_binding"][key] for key in ("pack_id", "pack_version", "pack_hash")
        }, record_hash=record["record_hash"])
        for binding in event["advancement"]["authority_bindings"]:
            binding.update(record_id=record_id, record_hash=record["record_hash"])
        pack = record["content_binding"]
        project["content_lock"]["packs"].append({
            "pack_id": pack["pack_id"], "version": pack["pack_version"], "content_hash": pack["pack_hash"],
        })
    previous = "0" * 64
    for event in events:
        event["previous_event_hash"] = previous
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    project["event_stream"]["head_hash"] = previous
    registry = SchemaRegistry(root)
    for event in events:
        report = registry.report(event, "TianxiaFoundry.AdvancementEvent.v3")
        assert report["valid"], report["diagnostics"]

    reduced = EffectiveStateReducer(registry).reduce(
        project=project, events=events, locked_records=records,
        choice_snapshot=materialize_choice_snapshot(project),
    )
    ledger = reduced.ledger
    assert ledger["readiness"]["advancement"] == "ADVANCEMENT_READY"
    background = ledger["background_origin"]["background"]
    origin = ledger["background_origin"]["origin_insight"]
    assert background["tool_proficiencies"] == ["the herbalism kit"]
    assert origin["selected_tool"] == "herbalism kit"
    assert origin["result"] == "expertise"
    assert origin["tool_expertise"] == ["herbalism kit"]

    diagnostics = _stage_aware_diagnostics(ledger, reduced.rules_selection_packets, reduced)
    assert diagnostics == []
    artifacts = {
        "Character_Master_Ledger.json": ledger,
        "Rules_Selection_Packets.json": reduced.rules_selection_packets,
        "Projection_Provenance_Map.json": {
            "mappings": reduced.provenance,
            "typed_choice_snapshot": reduced.typed_choice_snapshot,
            "project_display_contract": reduced.project_display_contract,
        },
        "Projection_Coverage_Report.json": _stage_aware_coverage(ledger, reduced.rules_selection_packets, reduced),
        "Projection_Diagnostics.json": {"valid": not diagnostics, "diagnostics": diagnostics},
    }
    snapshot, artifact = _service(tmp_path)._build_snapshot(
        project=project, artifacts=artifacts,
        projection_status={"status": "READY", "projection_id": "origin-tool-regression"},
    )
    persisted_sheet = json.loads(Path(artifact["path"]).read_text())
    assert persisted_sheet == snapshot
    sheet_origin = persisted_sheet["background_and_origin"]["origin_insight"]
    assert sheet_origin["selected_tool"] == "herbalism kit"
    assert sheet_origin["result"] == "expertise"
    assert sheet_origin["tool_expertise"] == ["herbalism kit"]
