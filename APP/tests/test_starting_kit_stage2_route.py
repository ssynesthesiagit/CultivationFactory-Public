"""Starting kit through Stage 2: constructed record, projector row shape, final projection."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import factory_authoring.final_character_materializer as materializer
from app.core import FoundryError
from character_creation.constructed_arts.records import (
    STARTING_KIT_PACK_ID,
    build_starting_kit_record,
    construct_starting_kit,
    validate_constructed_art_record,
)

ORPHAN = "tianxia.background.abandoned_orphan"
QI = "tianxia.path.qi_cultivation"


def _kit() -> dict:
    from weapon_requirements import owned_weapon_requirements
    return construct_starting_kit(
        background_id=ORPHAN, path_id=QI, path_option="option_a", picks={"path:1": 1}, seed="intent-hash",
        weapon_requirements=owned_weapon_requirements(spheres=["tianxia.sphere.barrage"]),
    )


def test_kit_record_rederives_and_rejects_tampering() -> None:
    record = build_starting_kit_record(_kit())
    assert record["content_type"] == "item" and record["content_binding"]["pack_id"] == STARTING_KIT_PACK_ID
    assert record["compatibility"]["factory"]["stage2_authority"]["allowed_kinds"] == ["equipment_acquisition"]
    assert validate_constructed_art_record(record, root_dir=Path("."))["kit_id"] == record["record_id"]
    tampered = deepcopy(record)
    tampered["compatibility"]["factory"]["constructed_art"]["kit"]["resolved"]["coin_cc"] += 1000
    with pytest.raises(FoundryError):
        validate_constructed_art_record(tampered, root_dir=Path("."))


def _projector_row(kit: dict) -> dict:
    resolved = kit["resolved"]
    return {
        "record_id": kit["kit_id"], "name": "Starting kit", "content_type": "item", "gained_at_cl": 1,
        "acquisition_event_id": "event.kit",
        "starting_kit": {
            "kit_id": kit["kit_id"], "background_id": kit["background_id"], "path_id": kit["path_id"],
            "path_option": kit["path_option"], "picks": kit["picks"], "seed": kit["seed"],
            "weapon_requirements": kit.get("weapon_requirements", []),
            "items": resolved["items"], "trinkets": resolved["trinkets"], "coin_cc": resolved["coin_cc"],
            "printed_coin_rolls": resolved["printed_coin_rolls"], "choices": resolved["choices"],
        },
    }


def _with_kit(workspace: Path, row: dict) -> None:
    """Write synthetic sealed equipment inputs, without private test-module imports."""
    background_origin = {
        "background": {"background_id": ORPHAN, "name": "Abandoned Orphan"},
        "origin_insight": {"origin_insight_id": "tianxia.origin_insight.born_under_suspicion"},
    }
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "equipment": [row],
        "typed_none": {},
        "background_origin": background_origin,
    }
    surfaces = {
        materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE: ledger,
        "Build/Character_Master_Ledger.json": ledger,
        "Build/Background_Origin_Ledger.json": {
            "schema_version": "TianxiaFoundry.CharacterGMBackgroundOrigin.v1",
            "background_origin": background_origin,
        },
        "Build/Equipment_Ledger.json": {
            "schema_version": "TianxiaFoundry.CharacterGMEquipment.v1",
            "source": "Character_Master_Ledger.json",
            "equipment": [row],
            "none_state": None,
        },
        "Build/Equipment_Ledger_Legacy.json": {
            "schema_version": "TianxiaFoundry.CharacterGMEquipmentLegacy.v1",
            "source": "Character_Master_Ledger.json",
            "equipment": [row],
            "none_state": None,
        },
        "Build/Item_Execution_Coverage.json": {
            "schema_version": "TianxiaFoundry.ItemExecutionCoverage.v1",
            "coverage": [],
            "items": [],
            "status": "SOURCE_EXPLICIT_NONE",
        },
        "Build/Selected_Item_GM_Projection.json": {
            "schema_version": "TianxiaFoundry.ItemGMScreenSelectedProjection.v1",
            "items": [],
            "status": "SOURCE_EXPLICIT_NONE",
        },
    }
    for relative, value in surfaces.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_final_projection_keeps_a_rederived_starting_kit(tmp_path: Path) -> None:
    workspace = tmp_path / "starting-kit-workspace"
    row = _projector_row(_kit())
    _with_kit(workspace, row)
    projection = materializer._project_background_equipment_for_compiler(workspace)
    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    assert projection["inventory_state"] == "SOURCE_STARTING_KIT"
    assert ledger["starting_kit"] == row and ledger["equipment"] == []
    assert ledger["starting_kit"]["starting_kit"]["weapon_requirements"] == _kit()["weapon_requirements"]
    reconciliation = ledger["background_origin"]["background"]["equipment_reconciliation"]
    assert reconciliation["ledger_equipment_ids"] == [row["record_id"]] and reconciliation["missing_items"] == []


def test_existing_generated_character_weapon_gap_metric() -> None:
    # Catalog-only projection of the persisted Q59-CL5-P0-V1 generated build:
    # the same owned ability IDs, kit choices and baseline carried item IDs,
    # without the unrelated recipes and rule prose in the original archive.
    from character_creation.service import CharacterCreationExecutionService
    from factory_authoring.starting_kits import item_definition
    from weapon_requirements import item_fits_requirement

    fixture_path = Path(__file__).parents[1] / "tests/fixtures/starting_kit_catalog_case.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    intent = fixture["canonical_selection_intent"]
    kit, _ = CharacterCreationExecutionService._starting_kit_construction(
        intent, fixture["intent_hash"], intent["target_cl"], run={"request": fixture["request"]},
    )
    needs = [need for need in kit.get("weapon_requirements", []) if "unarmed" not in need.get("kinds", ())]

    def missing(resolved):
        item_ids = [row["item_id"] for row in resolved["items"]]
        if resolved.get("treasure_weapon"):
            item_ids.append(resolved["treasure_weapon"]["chassis"]["item_id"])
        return int(any(not any(item_fits_requirement(item_definition(item_id), need)
                               for item_id in item_ids) for need in needs))

    assert needs, "The generated fixture must exercise at least one weapon requirement."
    assert missing(fixture["baseline_resolved"]) == 0  # main fixture: one character, zero gaps
    assert missing(kit["resolved"]) == 0       # candidate reconstruction: zero gaps


def test_final_projection_rejects_a_tampered_kit(tmp_path: Path) -> None:
    workspace = tmp_path / "starting-kit-workspace"
    row = _projector_row(_kit())
    row["starting_kit"]["items"][0]["quantity"] = 99
    _with_kit(workspace, row)
    with pytest.raises(FoundryError) as error:
        materializer._project_background_equipment_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID"
