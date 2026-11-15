"""R1: Rope Swing requires current possession, including after table reload."""

import pytest

from combat import carry, ext
from combat.ext import athletics
from combat.ext.teleport_steps import destination_allowed
from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, ROPE_SWING, SWING, engine_of, find, move_to, play, table_fight,
)


@pytest.mark.parametrize("item_id,name", [
    ("tianxia.mortal.gear.rope", "Rope"),
    ("tianxia.mortal.weapon.sheng_biao", "Sheng Biao (Rope Dart)"),
])
def test_dropped_rope_cannot_attach_after_reload_and_recovery_restores_it(tmp_path, item_id, name):
    keep = {"display_name": "Rope possession keep", "width_squares": 12, "height_squares": 8,
            "walls": [],
            # A visible, supported anchor, not a rooftop hidden by its own slab.
            "trees": [{"x": 5, "y": 3, "size": 1, "height_ft": 10,
                       "base_altitude_ft": 20, "occluder": "centerline"}],
            "starts": {"team1": [[4, 4]], "team2": [[4, 5]]}}
    kit = {"items": [{"item_id": item_id, "name": name, "quantity": 1}]}
    combat, table, mid = table_fight(
        tmp_path, [ROPE_SWING], kit=kit, map_doc=keep,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 5}},
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"})

    def named(label):
        return next(option["candidate_id"] for group in table.state(mid)["menu"]["actions"]
                    for option in group["options"] if option["label"] == label)

    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert athletics.rope_swing_gear(engine, fighter) == [name]
    anchor = Position(x=5, y=3, z=6)
    assert destination_allowed(engine, fighter, anchor, 60), "the attach needs a visible, supported anchor"
    play(table, mid, named("Drop " + name))
    play(table, mid, move_to(table, mid, 2, 4))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    inventory = carry.carrying_of(engine, FIGHTER)["items"]
    assert inventory[0]["item_id"] == item_id, "starting inventory remains after dropping"
    assert carry.dropped(fighter, inventory[0]["key"]) is not None
    # Exercise the actual Bonus Action before asserting the possession query,
    # so the negative control fails at the player-visible table outcome.
    _, prompts = play(table, mid, find(table, mid, ROPE_SWING))
    assert not prompts, "a dropped rope cannot reach the anchor choice"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert not any(c.condition_id == SWING for c in fighter.conditions.values())
    assert athletics.rope_swing_gear(engine, fighter) == []
    assert {"flight_suspended": 1} not in ext.run_strict("flight", engine, fighter)
    assert not any("rope_swing_climb" in group["source_definition_id"]
                   for group in table.state(mid)["menu"]["actions"])

    play(table, mid, move_to(table, mid, 4, 4))
    # Weapon recovery also costs a Bonus Action; the refused attach spent it.
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    pickup = (find(table, mid, ".weapon.sheng_biao.pickup")
              if item_id.endswith("sheng_biao") else named("Pick up " + name))
    play(table, mid, pickup)
    engine = engine_of(combat, mid)
    assert athletics.rope_swing_gear(engine, engine.state.actors[FIGHTER]) == [name]
    # Recovery may spend a Bonus Action; attach on the following turn.
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    play(table, mid, table.state(mid)["menu"]["end_turn"])
    def choose_anchor(prompt):
        assert prompt["context"]["reaction_source_id"] == "choice:needle.rope_anchor"
        assert "cell:5,3,6" in {option["id"] for option in prompt["choice"]["options"]}
        return {**prompt["context"], "selection": "USE", "option_ids": ["cell:5,3,6"]}

    _, prompts = play(table, mid, find(table, mid, ROPE_SWING), answer=choose_anchor)
    assert len(prompts) == 1, "the recovered rope reaches the live anchor choice"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    swing = next(c for c in fighter.conditions.values() if c.condition_id == SWING)
    assert swing.data["anchor"] == [anchor.x, anchor.y, anchor.z]
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, fighter)
    assert find(table, mid, "rope_swing_climb")
