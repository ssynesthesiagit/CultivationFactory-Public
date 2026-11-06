"""Realm projection follows the canonical highest-attained cultivation level."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZipFile

import pytest

from app.core import FoundryError, sha256_json
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.starting_proficiency_authority import validate_starting_proficiency_choices
from contracts.canonical import canonical_event_hash, canonical_record_hash
from contracts.registry import SchemaRegistry
from projector.reducer import EffectiveStateReducer


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_FIXTURE = ROOT / "tests" / "fixtures" / "W1" / "INSTALL_THIS_C1A_Clean_Fire_Qi_Proof_Character.zip"
PATH_ID = "tianxia.path.qi_cultivation"
BACKGROUND_ID = "tianxia.background.abandoned_orphan"
ORIGIN_ID = "tianxia.origin_insight.street_hardened"
CONTENT_LOCK_HASH = "334a7fe393e99ea12ecf6db6c1d57e0fa9c220187d8e87f13d068173ed69b0bb"


def _starting_proficiency_lock(project: dict) -> dict:
    contract_unsigned = {
        "schema": "TianxiaFoundry.StartingProficiencyChoiceContract.v1",
        "fields": {
            "path_skill_choices_by_path_id": {
                PATH_ID: {
                    "choice_kind": "path_skill",
                    "choice_id": PATH_ID,
                    "required_count": 2,
                    "allowed_values": ["Arcana", "History"],
                    "source": {"factory_path": "authority/test-path.json", "source_hash": "a" * 64},
                },
            },
            "origin_skill_choices_by_origin_id": {
                ORIGIN_ID: {
                    "choice_kind": "origin_skill",
                    "choice_id": ORIGIN_ID,
                    "required_count": 1,
                    "allowed_values": ["Deception"],
                    "duplicate_result": "expertise",
                    "source_text": "You gain proficiency in Deception.",
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
                    "fixed_skill_names": ["Survival"],
                    "fixed_tool_proficiencies": [],
                    "language_choice_count": 0,
                    "resolved": True,
                    "source": {"path": "authority/test-background.json"},
                    "allowed_values": [],
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
    contract = {**contract_unsigned, "contract_sha256": sha256_json(contract_unsigned)}
    selected = {
        "path_choice": [PATH_ID],
        "background_choice": [BACKGROUND_ID],
        "origin_insight_choice": [ORIGIN_ID],
    }
    response_maps = {
        "path_skill_choices_by_path_id": {PATH_ID: ["Arcana", "History"]},
        "origin_skill_choices_by_origin_id": {ORIGIN_ID: ["Deception"]},
        "background_language_choices_by_background_id": {},
    }
    validated = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices=response_maps,
    )
    assert validated["valid"] is True
    value = {
        "schema": "TianxiaFoundry.ServerDerivedStartingProficiencies.v1",
        "contract": contract,
        "response_maps": response_maps,
        "selected_by_slot": selected,
        "validated": validated,
        "binding": {
            "schema": "TianxiaFoundry.ServerDerivedStartingProficiencies.v1",
            "run_id": "cg1.realm-projection-test",
            "project_id": project["project_id"],
            "starting_revision": project["revision"],
            "content_lock_hash": CONTENT_LOCK_HASH,
            "request_sha256": "e" * 64,
            "response_sha256": "f" * 64,
        },
    }
    return {
        "lock_id": "lock.cg1.character-choices-starting-proficiencies",
        "field": "character.choices.starting_proficiencies",
        "value": value,
        "created_revision": project["revision"],
        "source": f"cg1-starting-proficiencies:{sha256_json(value)}:server-derived",
    }


def _rename_typed_none_strings(value: object) -> object:
    if isinstance(value, str):
        return (
            value.replace("forged_techniques", "immortal_arts")
            .replace("forged-techniques", "immortal-arts")
            .replace("Forged Techniques", "Immortal Arts")
            .replace("forged techniques", "immortal arts")
        )
    if isinstance(value, dict):
        return {
            _rename_typed_none_strings(key): _rename_typed_none_strings(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rename_typed_none_strings(item) for item in value]
    return value


def _append_immortal_art_typed_none(
    records: dict[str, dict],
    events: list[dict],
    target_cl: int,
) -> None:
    """Add the canonical high-realm absence authority to this fixture."""
    if target_cl < 15:
        return
    source_record = records["tianxia.c1a.none.forged_techniques"]
    immortal_record = _rename_typed_none_strings(deepcopy(source_record))
    assert isinstance(immortal_record, dict)
    raw_projection = ((immortal_record.get("compatibility") or {}).get("factory") or {}).get(
        "raw_projection"
    )
    if isinstance(raw_projection, dict):
        raw_projection["record_hash"] = "0" * 64
        raw_projection["record_hash"] = sha256_json({
            key: value
            for key, value in raw_projection.items()
            if key not in {"record_hash", "selected_authority"}
        })
    immortal_record["record_hash"] = "0" * 64
    immortal_record["record_hash"] = canonical_record_hash(immortal_record)
    records[immortal_record["record_id"]] = immortal_record

    source_event = next(
        event
        for event in events
        if (event.get("advancement") or {}).get("kind") == "typed_none"
        and ((event.get("advancement") or {}).get("details") or {}).get("target")
        == "forged_techniques"
    )
    immortal_event = _rename_typed_none_strings(deepcopy(source_event))
    assert isinstance(immortal_event, dict)
    immortal_event["event_id"] = str(
        uuid5(NAMESPACE_URL, f"realm-projection-test:immortal-arts:{target_cl}")
    )
    immortal_event["idempotency_key"] = (
        f"realm-projection-test:immortal-arts:{target_cl}"
    )
    immortal_event["advancement"]["target_cl"] = target_cl
    immortal_event["effective_point"]["character_cl"] = target_cl
    immortal_event["effective_point"]["order"] = 20 + target_cl
    immortal_event["subject"]["record_id"] = immortal_record["record_id"]
    immortal_event["subject"]["display_name"] = immortal_record["display_name"]
    immortal_event["content_binding"]["record_hash"] = immortal_record["record_hash"]
    for binding in immortal_event["advancement"]["authority_bindings"]:
        binding["record_id"] = immortal_record["record_id"]
        binding["record_hash"] = immortal_record["record_hash"]
    events.append(immortal_event)


def _projection_fixture(target_cl: int) -> tuple[dict, list[dict], dict[str, dict]]:
    with ZipFile(TRUSTED_FIXTURE) as archive:
        with ZipFile(BytesIO(archive.read("source/Character_Project.tianxia-project.zip"))) as project_zip:
            project = json_load(project_zip, "project.json")
            events = json_load(project_zip, "events.json")
            records = {row["record_id"]: row for row in json_load(project_zip, "locked-records.json")}
    project = deepcopy(project)
    events = deepcopy(events)
    records = deepcopy(records)
    records["tianxia.subpath.qi.cinder_heart_cultivator"]["owning_path_id"] = PATH_ID

    source_level_event = events[18]
    events = events[:20] + [
        _level_event(source_level_event, cultivation_level)
        for cultivation_level in range(6, target_cl + 1)
    ] + events[20:]
    _append_immortal_art_typed_none(records, events, target_cl)
    previous = "0" * 64
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["project_revision"] = sequence + 1
        event["previous_event_hash"] = previous
        event["event_hash"] = "0" * 64
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    project["revision"] = len(events) + 2
    project["event_stream"] = {
        "path": "events.json",
        "count": len(events),
        "head_hash": events[-1]["event_hash"],
    }
    project["user_locks"].append(_starting_proficiency_lock(project))
    return project, events, records


def json_load(archive: ZipFile, name: str) -> dict | list:
    import json

    return json.loads(archive.read(name))


def _level_event(source: dict, cultivation_level: int) -> dict:
    event = deepcopy(source)
    event["event_id"] = str(uuid5(NAMESPACE_URL, f"realm-projection-test:{cultivation_level}"))
    event["idempotency_key"] = f"realm-projection-test:{cultivation_level}"
    event["advancement"]["target_cl"] = cultivation_level
    event["advancement"]["calculation"]["inputs"]["cl"] = cultivation_level
    event["effective_point"]["character_cl"] = cultivation_level
    event["effective_point"]["order"] = 20 + cultivation_level
    return event


@pytest.mark.parametrize(
    ("target_cl", "expected_realm"),
    [
        (5, "Foundation"),
        (10, "Core Formation"),
        (15, "Nascent Soul"),
        (20, "Immortal"),
    ],
)
def test_v3_projection_character_and_level_rows_use_current_highest_cl(
    target_cl: int,
    expected_realm: str,
) -> None:
    project, events, records = _projection_fixture(target_cl)
    reduced = EffectiveStateReducer(SchemaRegistry(ROOT)).reduce(
        project=project,
        events=events,
        locked_records=records,
        choice_snapshot=materialize_choice_snapshot(project),
    )

    assert reduced.ledger["character"]["cl"] == target_cl
    assert reduced.ledger["character"]["realm"] == expected_realm
    levels = {row["cl"]: row["realm"] for row in reduced.ledger["advancement"]["levels"]}
    assert levels[target_cl] == expected_realm
    assert levels[5] == "Foundation"
    if target_cl >= 10:
        assert levels[10] == "Core Formation"
    if target_cl >= 15:
        assert levels[15] == "Nascent Soul"
    if target_cl >= 20:
        assert levels[20] == "Immortal"
    if target_cl < 15:
        assert "immortal_arts" not in reduced.ledger["typed_none"]
    else:
        assert reduced.ledger["typed_none"]["immortal_arts"]["state"] == "none"


def test_v3_projection_background_summary_uses_accepted_non_dex_change() -> None:
    project, events, records = _projection_fixture(5)
    reducer = EffectiveStateReducer(SchemaRegistry(ROOT))
    baseline = reducer.reduce(
        project=project,
        events=events,
        locked_records=records,
        choice_snapshot=materialize_choice_snapshot(project),
    )
    baseline_total = sum(baseline.ledger["core_stats"]["ability_scores"].values())

    starting_scores = deepcopy(events[0]["advancement"]["calculation"]["outputs"]["ability_scores"])
    background = events[1]
    background_scores = deepcopy(starting_scores)
    background_scores["CHA"] += 2
    background["advancement"]["calculation"]["inputs"]["ability"] = "CHA"
    background["advancement"]["calculation"]["inputs"]["prior_scores"] = deepcopy(starting_scores)
    background["advancement"]["calculation"]["outputs"]["ability_scores"] = background_scores
    background["advancement"]["calculation"]["outputs"]["ability_modifiers"] = {
        ability: (score - 10) // 2 for ability, score in background_scores.items()
    }
    ability_change = next(event for event in events if event["advancement"]["kind"] == "ability_score_change")
    ability_change["advancement"]["calculation"]["inputs"]["prior_scores"] = deepcopy(background_scores)
    final_scores = deepcopy(background_scores)
    final_scores["INT"] += 2
    ability_change["advancement"]["calculation"]["outputs"]["ability_scores"] = final_scores
    ability_change["advancement"]["calculation"]["outputs"]["ability_modifiers"] = {
        ability: (score - 10) // 2 for ability, score in final_scores.items()
    }

    previous = "0" * 64
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["project_revision"] = sequence + 1
        event["previous_event_hash"] = previous
        event["event_hash"] = "0" * 64
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    project["revision"] = len(events) + 2
    project["event_stream"] = {
        "path": "events.json",
        "count": len(events),
        "head_hash": events[-1]["event_hash"],
    }

    reduced = reducer.reduce(
        project=project,
        events=events,
        locked_records=records,
        choice_snapshot=materialize_choice_snapshot(project),
    )
    summary = reduced.ledger["background_origin"]["background"]
    assert summary["background_id"] == BACKGROUND_ID
    assert summary["ability_score_change"] == {"CHA": 2}
    assert "DEX" not in summary["ability_score_change"]
    assert summary["source_packet_ids"]
    assert sum(reduced.ledger["core_stats"]["ability_scores"].values()) == baseline_total


def test_v3_projection_rejects_incomplete_background_score_outputs() -> None:
    project, events, records = _projection_fixture(5)
    incomplete_scores = {"CHA": 10}
    for event in events[:2]:
        event["advancement"]["calculation"]["outputs"]["ability_scores"] = deepcopy(incomplete_scores)
    previous = "0" * 64
    for event in events:
        event["previous_event_hash"] = previous
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    project["event_stream"]["head_hash"] = events[-1]["event_hash"]

    with pytest.raises(FoundryError) as exc_info:
        EffectiveStateReducer(SchemaRegistry(ROOT)).reduce(
            project=project,
            events=events,
            locked_records=records,
            choice_snapshot=materialize_choice_snapshot(project),
        )
    assert exc_info.value.code == "PROJECTION_BACKGROUND_ABILITY_CHANGE_INVALID"
