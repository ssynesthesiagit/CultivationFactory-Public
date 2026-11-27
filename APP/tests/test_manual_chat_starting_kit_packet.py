from __future__ import annotations

import io
import json
import zipfile

from jsonschema import Draft202012Validator

from character_creation import CharacterCreationExecutionService
from factory_authoring import starting_kits


def test_manual_chat_packet_supplies_the_required_weapon_pick(monkeypatch):
    # Use synthetic equipment with a required Path weapon choice at index 1.
    background = "test.background.traveler"
    path = "tianxia.path.body_refining"
    armor, blade, spear = (f"test.item.{name}" for name in ("armor", "blade", "spear"))
    authority = {
        "background_kits": {background: {"entries": []}},
        "path_kits": {
            path: {
                "option_a": {
                    "entries": [
                        {"kind": "item", "item_id": armor},
                        {"kind": "choice", "printed": "a blade or a spear", "options": [
                            {"kind": "item", "item_id": blade},
                            {"kind": "item", "item_id": spear},
                        ]},
                    ],
                    "coin_cc": 0,
                },
                "option_b": {"entries": [], "coin_cc": 500},
            },
        },
    }
    catalog = {
        armor: {"item_id": armor, "name": "Travel armor", "price_cc": 70, "category": "armor"},
        blade: {"item_id": blade, "name": "Training blade", "price_cc": 40, "category": "weapon"},
        spear: {"item_id": spear, "name": "Training spear", "price_cc": 50, "category": "weapon"},
    }
    monkeypatch.setattr(starting_kits, "_authorities", lambda: (authority, catalog))
    service = object.__new__(CharacterCreationExecutionService)
    service.owner_principal = "test-owner"
    run = {
        "project_id": "test-project",
        "starting_revision": 3,
        "execution_mode": "MANUAL_CHAT",
        "request": {
            "request_sha256": "e" * 64,
            "content_lock_hash": "a" * 64,
            "typed_choice_snapshot": {"snapshot_sha256": "b" * 64},
            "required_components": [],
            "forbidden_planner_fields": [],
            "delegated_choice_envelope": {
                "allowed_choice_ids_by_slot": {"background_choice": [background], "path_choice": [path]},
            },
            "stage1_prompt": {"envelope": {"user_locks": [{
                "field": "character_sheet.ability_point_buy",
                "value": {"fixed_scores": dict(STR=15, DEX=15, CON=15, INT=8, WIS=8, CHA=8), "auto_abilities": False},
            }]}},
        },
    }
    service.get = lambda _run_id: run
    service._locked_records_for_project_ids = lambda _project_id, _record_ids: {}

    _, payload = service.complete_request_zip("test-run")
    with zipfile.ZipFile(io.BytesIO(payload)) as packet:
        model = json.loads(packet.read("AI_CHOICE_MODEL.json"))
        schema = json.loads(packet.read("RESPONSE_SCHEMA.json"))["preferred_response"]
        instructions = packet.read("AI_INSTRUCTIONS.md").decode("utf-8")
    assert "starting_kit_menus" in instructions
    assert "counting from zero" in instructions
    offered = model["starting_kit_menus"][background][path]
    row, = offered["option_a"]["choices"]
    assert row["required"] is True
    assert offered["option_b"]["choices"] == []

    # Author the response pick using only the ID and ordered options from the
    # ZIP, not from the interactive walk or from a direct authority lookup.
    decision = {"path_option": "option_a", "picks": {row["choice_id"]: row["options"].index("Training spear")}}
    response = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": model["request_sha256"],
        "selection_intent": {"by_slot": {"background_choice": [background], "path_choice": [path]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
            "starting_kit": decision,
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "Traveling cultivator"}},
    }
    Draft202012Validator(schema).validate(response)

    resolved = starting_kits.resolve_starting_kit(background, path, **decision)
    assert {item["item_id"] for item in resolved["items"]} == {armor, spear}
    assert resolved["choices"][0]["fallback_used"] is False
