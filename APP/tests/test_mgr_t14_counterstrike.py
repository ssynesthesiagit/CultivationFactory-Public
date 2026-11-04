"""Counterstrike's complete preparation menu through the native table transport.

Weapons come from the ordinary starting inventory compiler; no synthetic ability
effects, action-catalog edits, or direct plugin calls supply the preparation.
"""
import hashlib
import json

from factory_authoring.treasure_weapons import chassis_options
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload
from tests.h1_support import ROOT

BASE = "RETRIBUTION_BASE_COUNTERSTRIKE"


def test_counterstrike_all_inventory_attacks_remain_selectable_and_persist(tmp_path):
    kit = {"items": [{"item_id": row["item_id"], "name": row["name"], "quantity": 1}
                     for row in chassis_options()]}
    combat, table, mid = fight(tmp_path, [BASE], left_kit=kit)
    engine = combat._load_session(mid).engine
    # The opponent did not acquire the ability. Inventory cannot grant it.
    assert not any(action.owner_id == RIGHT and
                   action.parameters.get("typed", {}).get("source") == BASE
                   for action in engine.action_catalog.values())
    result = act(table, mid, "Counterstrike")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.counterstrike"
    options = prompt["choice"]["options"]
    # Each native melee weapon/Unarmed Strike contributes four ordinary triggers.
    # The old provider silently clipped this menu at 64, losing legal attacks.
    weapons = [action for action in engine.action_catalog.values()
               if action.owner_id == LEFT and action.parameters.get("typed", {}).get("weapon")
               and "#" not in action.source_definition_id
               and not action.source_definition_id.endswith(".pickup")
               and ".improvised." not in action.source_definition_id
               and not action.parameters["typed"].get("range_ft")
               and not action.parameters["typed"].get("opportunity_of")
               and action.resolution_kind == "TYPED" and action.target_kind == "HOSTILE_ENTITY"
               and any(row.get("type") == "attack" and row.get("attack_kind") in
                       ("weapon", "melee weapon", "unarmed", "melee")
                       for row in action.parameters["typed"].get("effects", []))]
    assert len(weapons) * 4 > 64
    assert len(options) == len(weapons) * 4
    assert len({option["id"] for option in options}) == len(options)
    chosen = options[-1]
    assert "Unarmed Strike" in " ".join(option["label"] for option in options)
    result = act(table, mid, "Counterstrike", [
        {**prompt["context"], "selection": "USE", "option_ids": [chosen["id"]]}])
    assert result["status"] == "COMMITTED", result
    loaded = reload(combat, mid)
    actor = loaded.state.actors[LEFT]
    held = next(condition for condition in actor.conditions.values()
                if condition.source_definition_id == "ready:retribution.counterstrike")
    assert held.data["option_id"] == chosen["id"]
    assert held.expires_on == "START_OF_SELF_NEXT_TURN"
    assert not actor.action_available
    assert actor.reaction_available


def test_intercepting_strike_options_past_sixteen_remain_selectable_and_persist(tmp_path):
    kit = {"items": [{"item_id": row["item_id"], "name": row["name"], "quantity": 1}
                     for row in chassis_options()]}
    combat, table, mid = fight(tmp_path, [BASE, "TAL_RETRIBUTION_INTERCEPTING_STRIKE"], left_kit=kit)
    engine = combat._load_session(mid).engine
    result = act(table, mid, "Counterstrike")
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    options = prompt["choice"]["options"]
    intercepts = [option for option in options if option["id"].startswith("intercept:")]
    weapons = [action for action in engine.action_catalog.values()
               if action.owner_id == LEFT and action.parameters.get("typed", {}).get("weapon")
               and "#" not in action.source_definition_id
               and not action.source_definition_id.endswith(".pickup")
               and ".improvised." not in action.source_definition_id
               and not action.parameters["typed"].get("range_ft")
               and not action.parameters["typed"].get("opportunity_of")
               and action.resolution_kind == "TYPED" and action.target_kind == "HOSTILE_ENTITY"
               and any(row.get("type") == "attack" and row.get("attack_kind") in
                       ("weapon", "melee weapon", "unarmed", "melee")
                       for row in action.parameters["typed"].get("effects", []))]
    # Each melee weapon offers two interception triggers. The provider once clipped the whole menu at 16 entries,
    # which left intercepts past index 16 unreachable.
    assert len(intercepts) == len(weapons) * 2
    assert len(intercepts) > 16
    chosen = intercepts[-1]
    assert options.index(chosen) >= 16
    result = act(table, mid, "Counterstrike", [
        {**prompt["context"], "selection": "USE", "option_ids": [chosen["id"]]}])
    assert result["status"] == "COMMITTED", result
    loaded = reload(combat, mid)
    actor = loaded.state.actors[LEFT]
    held = next(condition for condition in actor.conditions.values()
                if condition.source_definition_id == "ready:retribution.counterstrike")
    assert held.data["option_id"] == chosen["id"]
    assert held.expires_on == "START_OF_SELF_NEXT_TURN"


def test_counterstrike_controlling_text_provenance():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[BASE]
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "6f8a852e92164db5436a034280c5a545c77b9ab260c351b7da381f2adf2c307d")
