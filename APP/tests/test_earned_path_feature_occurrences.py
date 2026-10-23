"""Authenticated Path/Subpath feature occurrence projection regressions.

The fixtures below create real locked Path/Subpath records from the configured
Factory, then feed a sealed event history through the production occurrence
producer and Character Sheet consumer.  The event rows are intentionally
small, but their feature IDs, parent records, source locators, and progression
thresholds all come from the real project-locked authority.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.core import FoundryError, sha256_json
from character_builder import CharacterBuilderService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.service import CharacterCreationExecutionService
from character_sheet.service import (
    CharacterSheetService,
    _COMPLETE_CHARACTER_PATH_NESTED_FIELDS,
)
from project_store.service import ProjectStore
from projector.v3_bridge import (
    _authenticated_path_feature_payload,
    _build_earned_feature_occurrences,
    _dynamic_display_contract,
    _record_feature_source,
)
from stage1.service import Stage1ClipboardService


BODY_PATH = "tianxia.path.body_refining"
QI_PATH = "tianxia.path.qi_cultivation"
ONI_BLOOD = "tianxia.subpath.body.oni_blood"
BONE_MONARCH = "tianxia.subpath.body.bone_monarch"
SHARED_CHOICE_RULE_ID = "tianxia.shared.advancement.ability_score_improvement_or_cultivation_insight"
CULTIVATION_INSIGHT_ID = "insight.awakener-of-tools"


def _stage2(record: dict[str, Any]) -> dict[str, Any]:
    return (
        (record.get("compatibility") or {})
        .get("factory", {})
        .get("stage2_authority", {})
        or {}
    )


def _progression_by_cl(record: dict[str, Any], cl: int) -> list[str]:
    progression = _stage2(record).get("progression_by_cl") or {}
    row = progression.get(str(cl)) or progression.get(cl) or {}
    return [
        value
        for value in row.get("feature_record_ids") or []
        if isinstance(value, str) and value
    ]


def _event(
    event_id: str,
    kind: str,
    record: dict[str, Any],
    sequence: int,
    target_cl: int,
    *,
    outputs: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a compact canonical-history row from a real locked record."""

    event = {
        "event_id": event_id,
        "sequence": sequence,
        "subject": {"record_id": record["record_id"]},
        "advancement": {
            "kind": kind,
            "target_cl": target_cl,
            "calculation": {
                "inputs": deepcopy(inputs or {}),
                "outputs": deepcopy(outputs or {}),
            },
        },
    }
    event["event_hash"] = sha256_json(
        {
            "event_id": event_id,
            "sequence": sequence,
            "kind": kind,
            "target_cl": target_cl,
            "record_id": record["record_id"],
        }
    )
    return event


def _history(
    case: dict[str, Any],
    *,
    body_level: int,
    qi_level: int,
    include_subpath: bool = True,
    event_target_cl: int | None = None,
    choice_path_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build an ordered history using actual selected progression rows."""

    records = case["records"]
    body = records[BODY_PATH]
    qi = records[QI_PATH]
    subpath_id = case["subpath_id"]
    subpath = records[subpath_id]
    events: list[dict[str, Any]] = []
    level_events: list[dict[str, Any]] = []
    score_changes: list[dict[str, Any]] = []
    insight_events: list[dict[str, Any]] = []
    subpath_events: list[dict[str, Any]] = []
    path_events: list[dict[str, Any]] = []
    event_records: dict[str, dict[str, Any]] = {}
    sequence = 0
    choice_ordinal = 0
    insight_record = records.get(CULTIVATION_INSIGHT_ID)
    assert isinstance(insight_record, dict)
    assert insight_record.get("content_type") == "cultivation_insight"

    def append(
        kind: str,
        record: dict[str, Any],
        target_cl: int,
        *,
        outputs: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        event = _event(
            f"item6.{case['subpath_id'].split('.')[-1]}.{sequence}",
            kind,
            record,
            sequence,
            target_cl,
            outputs=outputs,
            inputs=inputs,
        )
        events.append(event)
        event_records[event["event_id"]] = record
        return event

    for path in (body, qi):
        path_event = append("path_acquisition", path, 1)
        path_events.append(path_event)

    for cl in range(1, max(body_level, qi_level) + 1):
        for path_id, limit, path in (
            (BODY_PATH, body_level, body),
            (QI_PATH, qi_level, qi),
        ):
            if cl > limit:
                continue
            feature_ids = _progression_by_cl(path, cl)
            assert feature_ids, (path_id, cl)
            effective_target_cl = event_target_cl if event_target_cl is not None else cl
            automatic = append(
                "level_advance",
                records[feature_ids[0]],
                effective_target_cl,
                outputs={
                    "path_progression_authority": {"path_id": path_id, "cl": cl},
                    "automatic_feature_record_ids": deepcopy(feature_ids),
                },
                inputs={"cl": cl},
            )
            level_events.append(automatic)

            # Use the real sealed choice feature when a milestone is present.
            # Some unequal-Path tests intentionally isolate the selected Path's
            # choice event while the other Path supplies the authenticated
            # character CL; this keeps the shared choice unambiguous without
            # dropping either Path's automatic progression rows.
            if choice_path_ids is not None and path_id not in choice_path_ids:
                continue
            for feature_id in feature_ids:
                feature = records[feature_id]
                allowed = set(_stage2(feature).get("allowed_kinds") or [])
                raw_record = _authenticated_path_feature_payload(feature)
                is_shared_choice = (
                    isinstance(raw_record, dict)
                    and raw_record.get("feature_kind") == "advancement_choice"
                    and raw_record.get("shared_rule_id") == SHARED_CHOICE_RULE_ID
                    and cl in {
                        value for value in raw_record.get("granted_at_cl") or []
                        if type(value) is int
                    }
                )
                if not ({"ability_score_change", "cultivation_insight_acquisition"} & allowed) and not is_shared_choice:
                    continue
                choice_ordinal += 1
                # The published CL4 milestone is the normal ASI choice; the
                # real selected Insight used below is only available from CL8.
                if cl == 4 and ("ability_score_change" in allowed or is_shared_choice):
                    choice = append(
                        "ability_score_change",
                        feature,
                        effective_target_cl,
                        inputs={"deltas": {"CHA": 1, "CON": 1}},
                        outputs={
                            "ability_scores": {
                                "STR": 10,
                                "DEX": 10,
                                "CON": 11,
                                "INT": 10,
                                "WIS": 10,
                                "CHA": 11,
                            }
                        },
                    )
                    score_changes.append(choice)
                elif is_shared_choice:
                    choice_event_id = f"item6.{case['subpath_id'].split('.')[-1]}.{sequence + 1}"
                    choice = append(
                        "cultivation_insight_acquisition",
                        insight_record,
                        effective_target_cl,
                        inputs={"repeat_index": choice_ordinal},
                        outputs={
                            "insight_occurrence": {
                                "event_id": choice_event_id,
                                "record_id": CULTIVATION_INSIGHT_ID,
                                "acquisition_cl": effective_target_cl,
                                "repeat_index": choice_ordinal,
                                "ability": None,
                                "amount": None,
                                "content_binding": {
                                    "pack_id": insight_record["content_binding"]["pack_id"],
                                    "pack_version": insight_record["content_binding"]["pack_version"],
                                    "pack_hash": insight_record["content_binding"]["pack_hash"],
                                    "record_hash": insight_record["record_hash"],
                                },
                                "source_evidence": [deepcopy(insight_record["source"])],
                            }
                        },
                    )
                    insight_events.append(choice)
                break

            if (
                include_subpath
                and path_id == BODY_PATH
                and cl == 3
                and body_level >= 3
            ):
                parent = append(
                    "subpath_acquisition",
                    subpath,
                    3,
                    outputs={
                        "granted_feature_record_ids": [
                            row.get("canonical_id")
                            for row in (
                                _stage2(subpath).get("feature_progression") or []
                            )
                            if isinstance(row, dict) and row.get("canonical_id")
                        ]
                    },
                )
                subpath_events.append(parent)

    packet_by_event = {
        event["event_id"]: f"packet.item6.{event['sequence']:03d}"
        for event in events
    }
    packets = []
    mappings = {}
    for event in events:
        record = event_records[event["event_id"]]
        packet_id = packet_by_event[event["event_id"]]
        packets.append(
            {
                "packet_id": packet_id,
                "event_id": event["event_id"],
                "event_hash": event["event_hash"],
                "sequence": event["sequence"],
                "target_cl": event["advancement"]["target_cl"],
                "advancement_kind": event["advancement"]["kind"],
                "record_id": record["record_id"],
                "record_hash": record["record_hash"],
            }
        )
        mappings[event["event_id"]] = {
            "provenance_unit": "canonical_advancement_event",
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "event_sequence": event["sequence"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
        }

    return {
        "events": events,
        "level_events": level_events,
        "score_changes": score_changes,
        "insight_events": insight_events,
        "subpath_events": subpath_events,
        "path_events": path_events,
        "event_records": event_records,
        "packet_by_event": packet_by_event,
        "packets": packets,
        "provenance": {
            "event_ids": [event["event_id"] for event in events],
            "event_head_hash": events[-1]["event_hash"],
            "mappings": mappings,
        },
    }


def _occurrences(
    case: dict[str, Any],
    *,
    body_level: int,
    qi_level: int,
    include_subpath: bool = True,
    event_target_cl: int | None = None,
    choice_path_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    history = _history(
        case,
        body_level=body_level,
        qi_level=qi_level,
        include_subpath=include_subpath,
        event_target_cl=event_target_cl,
        choice_path_ids=choice_path_ids,
    )
    occurrences = _build_earned_feature_occurrences(
        path_events=history["path_events"],
        level_events=history["level_events"],
        score_change_events=history["score_changes"],
        insight_events=history["insight_events"],
        subpath_events=history["subpath_events"],
        event_records=history["event_records"],
        locked_records=case["records"],
        packet_by_event=history["packet_by_event"],
        selected_path_ids=[BODY_PATH, QI_PATH],
        factory_root=case["factory_root"],
    )
    return occurrences, history


@pytest.fixture(scope="module")
def occurrence_cases(catalog_environment) -> dict[str, dict[str, Any]]:
    db = catalog_environment["db"]
    cases: dict[str, dict[str, Any]] = {}
    for name, subpath_id in (("oni", ONI_BLOOD), ("bone", BONE_MONARCH)):
        created = CharacterBuilderService(db).create_project(
            working_name=f"Item 6 earned occurrence {name}",
            concept="Authenticated Path and Subpath occurrence projection regression.",
            target_cl=10,
            power_band="standard",
            source_reference=None,
            creation_mode="detailed",
            ability_scores={},
            selections={
                "path_choice": [BODY_PATH, QI_PATH],
                "subpath_choice": [subpath_id],
                # Keep the Insight subject in the same authenticated project
                # snapshot as the Path milestones.  It remains a planning
                # preference here; the synthetic event history below is what
                # proves the actual milestone occurrence.
                "insight_priorities": [CULTIVATION_INSIGHT_ID],
            },
            generation_route="ai_bootstrap",
        )
        project_id = created["project_id"]
        creator = CharacterCreationExecutionService(
            db,
            stage1=Stage1ClipboardService(db),
            provider=None,
            project_store=ProjectStore(db),
        )
        # The occurrence fixture only needs the authenticated project snapshot.
        # Completing this deliberately two-Path blueprint would ask the real
        # initial-creation compiler to select a Method that is not present in
        # the pinned fixture corpus; that is unrelated to the event-history
        # projection under test.  create_project has already sealed the choice
        # snapshot, so use the same proof-bound read as the production path.
        project = ProjectStore(db).get_project(project_id)["project"]
        records = creator._locked_records_for_project(project_id)
        assert BODY_PATH in records and QI_PATH in records and subpath_id in records
        cases[name] = {
            "project": project,
            "records": records,
            "subpath_id": subpath_id,
            "factory_root": catalog_environment["root"],
        }
    return cases


def _display_payload(case: dict[str, Any], occurrences: list[dict[str, Any]], history: dict[str, Any]) -> dict[str, Any]:
    project = case["project"]
    records = case["records"]
    snapshot = materialize_choice_snapshot(project)
    parent_packet_id = next(
        (
            packet["packet_id"]
            for packet in history["packets"]
            if packet["record_id"] == case["subpath_id"]
        ),
        None,
    )
    level_feature_sources: dict[str, list[dict[str, Any]]] = {}
    for event in history["level_events"]:
        packet_id = history["packet_by_event"][event["event_id"]]
        outputs = (event.get("advancement") or {}).get("calculation", {}).get("outputs") or {}
        automatic_ids = [
            value
            for value in outputs.get("automatic_feature_record_ids") or []
            if isinstance(value, str) and value
        ]
        for feature_id in automatic_ids:
            level_feature_sources.setdefault(feature_id, []).append(
                {
                    "event_id": event["event_id"],
                    "packet_id": packet_id,
                    "target_cl": event["advancement"]["target_cl"],
                }
            )
    contract = _dynamic_display_contract(
        project,
        snapshot,
        records,
        history["packets"],
        [],
        parent_packet_id,
        level_feature_sources=level_feature_sources,
        earned_feature_occurrences=occurrences,
    )
    path_level_by_id = {
        path_id: max(
            (
                int((event.get("advancement") or {}).get("calculation", {}).get("outputs", {})
                    .get("path_progression_authority", {}).get("cl"))
                for event in history["level_events"]
                if (event.get("advancement") or {}).get("calculation", {}).get("outputs", {})
                .get("path_progression_authority", {}).get("path_id") == path_id
            ),
            default=0,
        )
        for path_id in (BODY_PATH, QI_PATH)
    }
    path_rows = [
        {
            "path_id": path_id,
            "display_name": records[path_id]["display_name"],
            "effective_cl": path_level_by_id[path_id],
        }
        for path_id in (BODY_PATH, QI_PATH)
    ]
    subpath_rows = [
        {
            "subpath_id": case["subpath_id"],
            "name": records[case["subpath_id"]]["display_name"],
            "owning_path_id": BODY_PATH,
            "selected_at_cl": 3,
            "source_packet_ids": [parent_packet_id],
        }
    ] if parent_packet_id else []
    level_rows = [
        {
            "event_id": event["event_id"],
            "cl": event["advancement"]["target_cl"],
            "feature_record_id": event["subject"]["record_id"],
        }
        for event in history["level_events"]
    ]
    ledger = {
        "character": {"cl": 10},
        "advancement": {
            "event_count": len(history["events"]),
            "event_head_hash": history["events"][-1]["event_hash"],
            "levels": level_rows,
        },
        "path_selections": path_rows,
        "subpaths": subpath_rows,
        "earned_feature_occurrences": deepcopy(occurrences),
    }
    return {
        "contract": contract,
        "ledger": ledger,
        "packets": {"packets": deepcopy(history["packets"])},
        "provenance": history["provenance"],
        "path_rows": path_rows,
        "subpath_rows": subpath_rows,
    }


def test_body3_qi10_uses_owning_path_levels_and_keeps_all_automatic_ids(occurrence_cases):
    case = occurrence_cases["oni"]
    occurrences, _history_rows = _occurrences(case, body_level=3, qi_level=10)
    by_name = {row["display_name"]: row for row in occurrences}
    assert "Oni Mask" in by_name
    assert "Blood Drinker" not in by_name
    assert any(row["display_name"] == "Iron Fist" for row in occurrences)
    assert all(row["owning_path_id"] == QI_PATH or row["acquired_at_path_level"] <= 3 for row in occurrences)

    # The first Body milestone has multiple authenticated automatic IDs; the
    # representative level subject alone would omit Iron Fist and its peers.
    body_level_one = [
        row for row in occurrences
        if row["owning_path_id"] == BODY_PATH and row["acquired_at_path_level"] == 1
    ]
    assert len(body_level_one) >= 3
    assert {row["feature_id"] for row in body_level_one} == set(
        _progression_by_cl(case["records"][BODY_PATH], 1)
    )


def test_body0_has_no_body_or_future_subpath_occurrences(occurrence_cases):
    case = occurrence_cases["oni"]
    occurrences, _history_rows = _occurrences(
        case,
        body_level=0,
        qi_level=10,
        include_subpath=False,
    )
    assert occurrences
    assert all(row["owning_path_id"] == QI_PATH for row in occurrences)
    assert not any(row["parent_kind"] == "subpath" for row in occurrences)
    assert not {row["display_name"] for row in occurrences} & {"Oni Mask", "Blood Drinker"}


def test_body6_adds_late_oni_feature_with_actual_level_event(occurrence_cases):
    case = occurrence_cases["oni"]
    occurrences, history = _occurrences(case, body_level=6, qi_level=10)
    blood = next(row for row in occurrences if row["display_name"] == "Blood Drinker")
    assert blood["required_path_level"] == 6
    assert blood["acquired_at_path_level"] == 6
    assert blood["attainment_event"]["kind"] == "level_advance"
    assert blood["acquisition_event"]["event_id"] == blood["attainment_event"]["event_id"]
    parent_packet = next(
        packet for packet in history["packets"] if packet["record_id"] == ONI_BLOOD
    )
    assert parent_packet["packet_id"] in blood["source_packet_ids"]


@pytest.mark.parametrize(
    ("body_level", "expected_choice_kind"),
    [
        (4, "ability_score_change"),
        (8, "cultivation_insight_acquisition"),
    ],
)
def test_shared_choice_uses_owning_path_level_before_later_character_cl(
    occurrence_cases,
    body_level,
    expected_choice_kind,
):
    case = occurrence_cases["oni"]
    occurrences, history = _occurrences(
        case,
        body_level=body_level,
        qi_level=10,
        event_target_cl=10,
        choice_path_ids={BODY_PATH},
    )
    selected = [row for row in occurrences if row.get("selection")]
    assert selected
    body_choices = {
        row["acquired_at_path_level"]: row
        for row in selected
        if row["owning_path_id"] == BODY_PATH
    }
    assert 4 in body_choices
    assert body_choices[4]["selection"]["choice_kind"] == "ability_score_change"
    assert body_choices[4]["selection"]["event"]["target_cl"] == 10
    assert body_choices[4]["attainment_event"]["sequence"] < body_choices[4]["selection"]["event"]["sequence"]
    if body_level >= 8:
        assert 8 in body_choices
        assert body_choices[8]["selection"]["choice_kind"] == "cultivation_insight_acquisition"
        assert body_choices[8]["selection"]["event"]["target_cl"] == 10
        assert body_choices[8]["attainment_event"]["sequence"] < body_choices[8]["selection"]["event"]["sequence"]
        assert body_choices[4]["selection"]["event"]["event_id"] != body_choices[8]["selection"]["event"]["event_id"]
    choice = body_choices[body_level if expected_choice_kind == "cultivation_insight_acquisition" else 4]
    if expected_choice_kind == "cultivation_insight_acquisition":
        assert choice["selection"]["insight_occurrence"]["record_id"] == CULTIVATION_INSIGHT_ID
        assert history["event_records"][choice["selection"]["event"]["event_id"]]["content_type"] == "cultivation_insight"
    else:
        assert choice["selection"]["deltas"] == {"CHA": 1, "CON": 1}


def test_bone_guard_keeps_full_source_backed_subactions_and_late_parent_shape(occurrence_cases):
    case = occurrence_cases["bone"]
    occurrences, history = _occurrences(case, body_level=10, qi_level=0)
    guard = next(row for row in occurrences if row["display_name"] == "Bone Guard Manifestation")
    assert "Bone Strike" in guard["source_text"]
    assert "Guard the Sovereign" in guard["source_text"]
    assert guard["source_text"] == guard["full_description"]
    assert guard["acquired_at_path_level"] == 10
    assert guard["acquisition_event"]["kind"] == "level_advance"
    assert guard["attainment_event"]["event_id"] == guard["acquisition_event"]["event_id"]
    parent_packet = next(
        packet for packet in history["packets"] if packet["record_id"] == BONE_MONARCH
    )
    assert parent_packet["packet_id"] in guard["source_packet_ids"]


def test_occurrences_bind_repeated_choices_to_real_events_and_consumer(occurrence_cases):
    case = occurrence_cases["oni"]
    # Keep the inspected choice milestones on one owning Path.  The second
    # Path is still selected and projected, while an Insight subject without a
    # Path ID remains deliberately ambiguous when two Paths share a milestone.
    occurrences, history = _occurrences(case, body_level=3, qi_level=10)
    selected = [row for row in occurrences if row.get("selection")]
    assert len(selected) >= 2
    selection_ids = {
        row["selection"]["event"]["event_id"]
        for row in selected
    }
    assert len(selection_ids) == len(selected)
    assert any(row["selection"]["choice_kind"] == "ability_score_change" for row in selected)
    assert any(row["selection"]["choice_kind"] == "cultivation_insight_acquisition" for row in selected)
    for row in selected:
        if row["selection"]["choice_kind"] == "ability_score_change":
            assert row["selection"]["deltas"] == {"CHA": 1, "CON": 1}
            assert row["selection"]["ability_scores_after"]["CHA"] == 11

    asi = next(
        row for row in occurrences
        if row["feature_id"].endswith("ability_score_improvement_or_cultivation_insight")
    )
    asi_record = case["records"][asi["feature_id"]]
    asi_factory_raw = (
        asi_record.get("compatibility", {})
        .get("factory", {})
        .get("raw_projection", {})
    )
    assert isinstance(asi_factory_raw.get("path_feature"), dict)
    asi_raw = _authenticated_path_feature_payload(asi_record)
    assert isinstance(asi_raw, dict)
    assert len(asi_raw["effective_rules_text"]) == 906
    assert asi["source_text"] == asi_raw["effective_rules_text"]
    assert asi["source_text"] != asi_raw["source_rules_text"]

    iron_fist = case["records"][f"{BODY_PATH}.feature.iron_fist"]
    iron_factory_raw = (
        case["records"][f"{BODY_PATH}.feature.iron_fist"]
        .get("compatibility", {})
        .get("factory", {})
        .get("raw_projection", {})
    )
    assert isinstance(iron_factory_raw.get("path_feature"), dict)
    iron_fist_source = _record_feature_source(iron_fist)
    iron_fist_raw = _authenticated_path_feature_payload(iron_fist)
    assert isinstance(iron_fist_raw, dict)
    assert iron_fist_source["source_text"] == iron_fist_raw["effective_rules_text"]
    assert "1d8 + Strength or Constitution modifier" in iron_fist_source["source_text"]

    payload = _display_payload(case, occurrences, history)
    validated = CharacterSheetService._validate_earned_feature_occurrences(**payload, factory_root=case["factory_root"])
    assert validated == occurrences

    filtered = CharacterSheetService._complete_character_project_value(
        {"earned_feature_occurrences": occurrences, "selection": selected[0]["selection"]},
        _COMPLETE_CHARACTER_PATH_NESTED_FIELDS,
    )
    assert filtered["earned_feature_occurrences"][0]["source_text"]
    choice = next(row for row in filtered["earned_feature_occurrences"] if row.get("selection"))
    assert choice["selection"]["deltas"] == {"CHA": 1, "CON": 1}
    assert choice["selection"]["ability_scores_after"]["CHA"] == 11


@pytest.mark.parametrize("mutation", ["source", "parent", "causal_event"])
def test_consumer_rejects_source_parent_and_resealed_nonexistent_event(occurrence_cases, mutation):
    case = occurrence_cases["oni"]
    occurrences, history = _occurrences(case, body_level=6, qi_level=10)
    payload = _display_payload(case, occurrences, history)
    tampered = deepcopy(payload)
    row_index = next(
        index for index, row in enumerate(tampered["ledger"]["earned_feature_occurrences"])
        if row["parent_kind"] == "subpath"
    )
    contract_row = tampered["contract"]["earned_feature_occurrences"][row_index]
    ledger_row = tampered["ledger"]["earned_feature_occurrences"][row_index]
    if mutation == "source":
        contract_row["source_text"] += "\nforged"
        ledger_row["source_text"] += "\nforged"
    elif mutation == "parent":
        contract_row["parent_record_hash"] = "0" * 64
        ledger_row["parent_record_hash"] = "0" * 64
    else:
        fake = "event.item6.resealed.nonexistent"
        contract_row["acquisition_event_id"] = fake
        contract_row["event_id"] = fake
        contract_row["acquisition_event_hash"] = "f" * 64
        contract_row["event_hash"] = "f" * 64
        ledger_row["acquisition_event_id"] = fake
        ledger_row["event_id"] = fake
        ledger_row["acquisition_event_hash"] = "f" * 64
        ledger_row["event_hash"] = "f" * 64

    with pytest.raises(FoundryError) as rejected:
        CharacterSheetService._validate_earned_feature_occurrences(
            **tampered,
            factory_root=case["factory_root"],
        )
    assert rejected.value.code == "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID"


def test_consumer_rejects_reusing_an_earlier_choice_for_a_later_grant(occurrence_cases):
    case = occurrence_cases["oni"]
    occurrences, history = _occurrences(
        case,
        body_level=8,
        qi_level=10,
        event_target_cl=10,
        choice_path_ids={BODY_PATH},
    )
    payload = _display_payload(case, occurrences, history)
    body_choices = {
        row["acquired_at_path_level"]: row
        for row in payload["ledger"]["earned_feature_occurrences"]
        if row["owning_path_id"] == BODY_PATH and row.get("selection")
    }
    assert {4, 8}.issubset(body_choices)
    earlier_selection = deepcopy(body_choices[4]["selection"])
    earlier_packet_id = earlier_selection["event"]["packet_id"]
    for rows in (
        payload["contract"]["earned_feature_occurrences"],
        payload["ledger"]["earned_feature_occurrences"],
    ):
        later = next(
            row
            for row in rows
            if row["owning_path_id"] == BODY_PATH
            and row["acquired_at_path_level"] == 8
        )
        later["selection"] = deepcopy(earlier_selection)
        later["source_packet_ids"].append(earlier_packet_id)

    with pytest.raises(FoundryError) as rejected:
        CharacterSheetService._validate_earned_feature_occurrences(
            **payload,
            factory_root=case["factory_root"],
        )
    assert rejected.value.code == "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID"
