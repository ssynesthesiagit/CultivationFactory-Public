"""Post-merge Athletics contracts through real table commits and cold reloads."""
import json
import pytest

from combat import flight
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import teleport_reach
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, FLASH_STEP, ONE_BREATH, ROPE_SWING, ROOT,
    table_fight, find, play, events,
)
from tests.test_a2_athletics_table_reloads import fresh


@pytest.mark.parametrize("mode", ["attack", "thrown"])
def test_native_improvised_grant_keeps_possession_and_consumption_after_reload(tmp_path, mode):
    where = {FIGHTER: {"x": 3, "y": 4}, FOE: {"x": 4 if mode == "attack" else 7, "y": 4}}
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH], kit={"items": []}, where=where)
    play(table, mid, find(table, mid, ONE_BREATH))
    engine = fresh(combat, mid)
    grant = next(row for row in engine.action_catalog.values() if row.owner_id == FIGHTER
                 and (row.parameters.get("typed") or {}).get("delivered_by", "").endswith(".improvised." + mode))
    if mode == "thrown":
        assert "thrown attack" in grant.parameters["description"]
    with pytest.raises(AssertionError):
        find(table, mid, grant.source_definition_id, target=FOE)
    play(table, mid, find(table, mid, ".improvised.grab"))
    assert any(c.condition_id == "condition:typed.improvised"
               for c in fresh(combat, mid).state.actors[FIGHTER].conditions.values())
    play(table, mid, find(table, mid, grant.source_definition_id, target=FOE))
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert str(actor.turn_flags["athletics_one_breath_strike"]) == "1"
    assert bool([c for c in actor.conditions.values() if c.condition_id == "condition:typed.improvised"]) == (mode == "attack")
    assert events(engine, "ATTACK_ROLLED", FIGHTER)
    assert not any("one_breath_strike" in group["source_definition_id"] or
                   "one_breath_unarmed" in group["source_definition_id"]
                   for group in table.state(mid)["menu"]["actions"])


def test_native_iron_fist_grant_retains_die_ability_and_shared_receipt(tmp_path):
    combat, table, mid = table_fight(tmp_path, [ONE_BREATH, "TAL_IRON_FIST_IRON_FIST_TRAINING"], kit={"items": []})
    play(table, mid, find(table, mid, ONE_BREATH))
    engine = fresh(combat, mid)
    native = next(row for row in engine.action_catalog.values() if row.owner_id == FIGHTER
                  and row.source_definition_id.endswith(".natural.iron_fist_sphere"))
    grant = next(row for row in engine.action_catalog.values() if row.owner_id == FIGHTER
                 and (row.parameters.get("typed") or {}).get("delivered_by") == native.source_definition_id)
    assert grant.parameters["typed"]["weapon"] == native.parameters["typed"]["weapon"]
    assert grant.parameters["typed"]["numbers"]["attack_bonus"] == native.parameters["typed"]["numbers"]["attack_bonus"]
    assert grant.parameters["typed"]["weapon"]["damage"]["sides"] > 1
    assert "Iron Fist" in grant.display_name
    play(table, mid, find(table, mid, grant.source_definition_id, target=FOE))
    assert str(fresh(combat, mid).state.actors[FIGHTER].turn_flags["athletics_one_breath_strike"]) == "1"


def test_dash_reach_menu_and_execution_agree_without_unused_allowance(tmp_path):
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP])
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    action = next(row for row in engine.action_catalog.values() if row.owner_id == FIGHTER
                  and row.source_definition_id.endswith(".flash_step"))
    assert teleport_reach(engine, actor, action) == flight.dash_reach(engine, actor)
    before = actor.movement_remaining_ft
    _, prompts = play(table, mid, find(table, mid, "flash_step"))
    actor = fresh(combat, mid).state.actors[FIGHTER]
    assert prompts
    assert actor.movement_remaining_ft == before
    assert not actor.turn_flags.get("flight_typed_dashes")


def test_dash_bound_teleport_is_unavailable_when_dash_is_forbidden(tmp_path):
    def prepare(bundles):
        bundle = next(row for row in bundles if row["actor_id"] == FIGHTER)
        action = ActionDefinition(source_definition_id="action:test.f3.no_dash", display_name="Test Dash prohibition",
            owner_id=FIGHTER, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"free_primary": True, "typed": {"effects": [{"type": "condition", "condition": "no_dash", "applies_to": "self"}],
                                                       "duration": {"kind": "instant"}, "numbers": {}, "riders": []}})
        bundle["action_catalog"].append(action.model_dump(mode="json"))
        bundle["actor_template"]["action_ids"].append(action.source_definition_id)
    combat, table, mid = table_fight(tmp_path, [FLASH_STEP], bundle_transform=prepare)
    play(table, mid, find(table, mid, "f3.no_dash"))
    assert any(c.condition_id == "condition:typed.no_dash" for c in fresh(combat, mid).state.actors[FIGHTER].conditions.values())
    with pytest.raises(AssertionError):
        find(table, mid, "flash_step")


def test_shipped_authority_matches_reviewed_rope_and_deferred_attack():
    shipped = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    reviewed = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/auto8-athletics.json").read_text())["mechanics"]
    for owner in (ONE_BREATH, ROPE_SWING):
        assert shipped[owner]["effects"] == reviewed[owner]["effects"]
        assert shipped[owner]["riders"] == reviewed[owner]["riders"]
    rider = " ".join(shipped[ONE_BREATH]["riders"])
    assert "for each native weapon delivery" in rider
    assert "best-fitting" not in rider


def test_dash_receipt_documentation_distinguishes_completion_from_grants():
    docs = (ROOT / "combat/ext/__init__.py").read_text()
    completion = docs.split("Dash-completion receipt seam", 1)[1].split("Map altitude ceiling", 1)[0]
    assert "without granting unused movement or a typed" in completion
    assert "never a replacement" in completion
    assert "records it for a Dash-bound teleport" not in completion
    rope = docs.split("Rope anchor point choice", 1)[1].split("\n\n", 1)[0]
    assert "An AI combatant automatically chooses the nearest legal square" in rope
