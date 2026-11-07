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
from tests.test_final_character_materializer import _public_background_origin_grant_workspace

ORPHAN = "tianxia.background.abandoned_orphan"
QI = "tianxia.path.qi_cultivation"


def _kit() -> dict:
    return construct_starting_kit(background_id=ORPHAN, path_id=QI, path_option="option_a", picks={"path:1": 1}, seed="intent-hash")


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
            "items": resolved["items"], "trinkets": resolved["trinkets"], "coin_cc": resolved["coin_cc"],
            "printed_coin_rolls": resolved["printed_coin_rolls"], "choices": resolved["choices"],
        },
    }


def _with_kit(workspace: Path, row: dict) -> None:
    for relative in (materializer._PATH_PROJECTION_RAW_PROVENANCE_RELATIVE, "Build/Character_Master_Ledger.json"):
        path = workspace / relative
        ledger = json.loads(path.read_text(encoding="utf-8"))
        ledger["equipment"] = [row]
        ledger["typed_none"].pop("equipment", None)
        path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    for relative in ("Build/Equipment_Ledger.json", "Build/Equipment_Ledger_Legacy.json"):
        path = workspace / relative
        surface = json.loads(path.read_text(encoding="utf-8"))
        surface["equipment"] = [row]
        surface["none_state"] = None
        path.write_text(json.dumps(surface, sort_keys=True) + "\n", encoding="utf-8")


def test_final_projection_keeps_a_rederived_starting_kit(tmp_path: Path) -> None:
    workspace, _original, _ability = _public_background_origin_grant_workspace(tmp_path)
    row = _projector_row(_kit())
    _with_kit(workspace, row)
    projection = materializer._project_background_equipment_for_compiler(workspace)
    ledger = json.loads((workspace / "Build/Character_Master_Ledger.json").read_text(encoding="utf-8"))
    assert projection["inventory_state"] == "SOURCE_STARTING_KIT"
    assert ledger["starting_kit"] == row and ledger["equipment"] == []
    reconciliation = ledger["background_origin"]["background"]["equipment_reconciliation"]
    assert reconciliation["ledger_equipment_ids"] == [row["record_id"]] and reconciliation["missing_items"] == []


def test_final_projection_rejects_a_tampered_kit(tmp_path: Path) -> None:
    workspace, _original, _ability = _public_background_origin_grant_workspace(tmp_path)
    row = _projector_row(_kit())
    row["starting_kit"]["items"][0]["quantity"] = 99
    _with_kit(workspace, row)
    with pytest.raises(FoundryError) as error:
        materializer._project_background_equipment_for_compiler(workspace)
    assert error.value.code == "FINAL_CHARACTER_BACKGROUND_EQUIPMENT_PROJECTION_INVALID"
