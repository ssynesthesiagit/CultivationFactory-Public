"""Source-backed Ninpo imports -> native table intents -> cold reload/replay.

No runtime conditions, successful receipts or fixture-only actions are installed.
The starting sheets explicitly own the printed CL14 Ninpo source features.
"""
import hashlib
import json
from pathlib import Path

import pytest

from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, FOE

NINPO = "tianxia.subpath.qi.ninpo_adept.feature."
VANISH = NINPO + "vanishing_technique"
FEATURES = [NINPO + "shadow_step", NINPO + "smoke_veil", NINPO + "hidden_strike", VANISH]
TRUE_SIGHT_FEATURES = ["TAL_THE_HIDDEN_EYE_DISCERN_ILLUSIONS",
                       "TAL_THE_HIDDEN_EYE_PIERCING_SENSES", "TAL_THE_HIDDEN_EYE_TRUE_SIGHT"]
ROOT = Path(__file__).resolve().parents[1]


def held(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed." + name]


def setup(tmp_path, talents=(), **kwargs):
    combat, table, mid = fixture(tmp_path, talents, cl=14, owner_features=FEATURES,
        owner_path="Qi Cultivation", foe_position={"x": 4, "y": 5},
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]), **kwargs)
    # Keep the complete CL14 progression. Choose the printed non-displacing
    # rider through a native setting, so attack tests keep the foe's Reactions.
    settle(table, mid, candidate(combat, mid, "Hidden Strike: Vanishing Posture").candidate_id)
    return combat, table, mid


def names(combat, mid):
    engine = combat._load_session(mid).engine
    return {engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog}


def activate(combat, table, mid):
    settle(table, mid, candidate(combat, mid, "Vanishing Technique").candidate_id)


def test_source_and_dynamic_runtime_dependencies():
    source = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[VANISH]
    assert hashlib.sha256(source.encode()).hexdigest() == "677c8ae7d7399e3567a85e8333c0debf1168e005a8c162b64009d41b4e69adec"
    # Literal declarations for the publication export's dynamic compiler inputs.
    for path in ("authority/Tianxia_Typed_Mechanics_Authority_R1.json",
                 "combat/rules/feature_blocks.json", "combat/rules/feature_blocks.d/tabik.json",
                 "combat/rules/typed_conditions.json", "combat/rules/concentration.json",
                 "combat/rules/senses.json", "combat/rules/terrain.json"):
        assert isinstance(json.loads((ROOT / path).read_text()), dict)


@pytest.mark.parametrize("ask", [True, False])
def test_activation_attack_reveal_turn_end_and_scene_reset(tmp_path, ask):
    combat, table, mid = setup(tmp_path / "first", ask=ask)
    before = reload(tmp_path / "first", mid)
    qi = before.state.actors[OWNER].resources["resource:core.qi"]
    activate(combat, table, mid)
    active = reload(tmp_path / "first", mid)
    actor = active.state.actors[OWNER]
    assert actor.resources["resource:core.qi"] == qi - 5
    assert not actor.bonus_action_available
    assert held(actor, "invisible") and held(actor, "vanishing_state")
    from combat.typed_executor import check_mode
    assert check_mode(actor, "DEX", "Stealth", engine=active) == "ADVANTAGE"
    # Select a real weapon/unarmed attack from the native compiled catalogue.
    attack = next(c for c in active.legal_candidates() if c.target_ids == (FOE,)
        and c.source_definition_id in active.action_catalog
        and (active.action_catalog[c.source_definition_id].resolution_kind == "ATTACK"
             or any(e.get("type") == "attack" for e in
                 (active.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("effects", []))))
    settle(table, mid, attack.candidate_id, choices={})
    revealed = reload(tmp_path / "first", mid)
    assert held(revealed.state.actors[OWNER], "vanishing_state")
    assert not held(revealed.state.actors[OWNER], "invisible")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert held(reload(tmp_path / "first", mid).state.actors[OWNER], "invisible")
    turn(table, mid, OWNER)
    assert "Vanishing Technique" not in names(combat, mid)
    # A new native encounter starts a new scene; reloading the old one doesn't.
    fresh, fresh_table, other = setup(tmp_path / "second", ask=ask)
    activate(fresh, fresh_table, other)
    assert held(reload(tmp_path / "second", other).state.actors[OWNER], "invisible")


def test_smoke_step_and_movement_do_not_reveal(tmp_path):
    combat, table, mid = setup(tmp_path)
    # Center the concealment between both teleport endpoints; Shadow Step needs
    # its ordinary qualifying concealment, not just the extended range.
    settle(table, mid, candidate(combat, mid, "Smoke Veil", at=(5, 6)).candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    activate(combat, table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    # The bound square is only the menu's default: the player's own destination answer decides where Shadow Step lands.
    settle(table, mid, candidate(combat, mid, "Shadow Step (Vanishing: 30 feet)", at=(7, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": "cell:7,6"})
    settle(table, mid, candidate(combat, mid, "Smoke Veil: move (Vanishing: 30 feet)", at=(11, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": "cell:11,6"})
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].position.x == 7
    assert any(z.active and z.center.x == 11 for z in after.state.zones.values())
    assert held(after.state.actors[OWNER], "invisible")


def test_harmful_field_reveals_without_waiting_for_damage(tmp_path):
    combat, table, mid = setup(tmp_path, ["FIRE_TAL_CROWN_OF_INFERNO"])
    activate(combat, table, mid)
    mark = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Crown of the Inferno", at=(12, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == "ZONE_CREATED" for e in engine.events[mark:])
    assert not held(engine.state.actors[OWNER], "invisible")
    assert held(engine.state.actors[OWNER], "vanishing_state")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")


def test_minute_expires_without_restoring_invisible(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    # Actual table turn producers, with no direct clock/state mutation.
    for _ in range(10):
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
        turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not held(engine.state.actors[OWNER], "vanishing_state")
    assert not held(engine.state.actors[OWNER], "invisible")
    assert "Vanishing Technique" not in names(combat, mid)


def test_below_cl14_cannot_activate(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=13, owner_features=[VANISH], owner_path="Qi Cultivation")
    assert "Vanishing Technique" not in names(combat, mid)


@pytest.mark.parametrize("name", ["Shove: Prone", "Shove: Push 5 ft", "Grapple"])
def test_hostile_save_condition_and_unwilling_manipulation(tmp_path, name):
    combat, table, mid = setup(tmp_path, owner_dc=100)
    activate(combat, table, mid)
    mark = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, name, target=FOE).candidate_id)
    after = reload(tmp_path, mid)
    assert any(e.event_type == "SAVE_ROLLED" for e in after.events[mark:])
    assert not held(after.state.actors[OWNER], "invisible")
    assert held(after.state.actors[OWNER], "vanishing_state")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")
