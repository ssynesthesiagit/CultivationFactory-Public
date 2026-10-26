"""R1: Rope Swing requires current possession, including after table reload."""

import pytest

from combat import carry, ext
from combat.ext import athletics
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, ROPE_SWING, SWING, engine_of, find, move_to, play, table_fight,
)


@pytest.mark.parametrize("item_id,name", [
    ("tianxia.mortal.gear.rope", "Rope"),
    ("tianxia.mortal.weapon.sheng_biao", "Sheng Biao (Rope Dart)"),
])
def test_dropped_rope_cannot_attach_after_reload_and_recovery_restores_it(tmp_path, item_id, name):
    keep = {"display_name": "Rope possession keep", "width_squares": 12, "height_squares": 8,
            "walls": [{"shape": "rect", "points": [[1, 1], [8, 7]], "filled": False,
                       "blocks": "sight_and_movement", "storeys": 1}],
            "roofs": {"enabled": True, "height_ft": 10},
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
    play(table, mid, named("Drop " + name))
    play(table, mid, move_to(table, mid, 2, 4))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    inventory = carry.carrying_of(engine, FIGHTER)["items"]
    assert inventory[0]["item_id"] == item_id, "starting inventory remains after dropping"
    assert carry.dropped(fighter, inventory[0]["key"]) is not None
    # Exercise the actual Bonus Action before asserting the possession query,
    # so the negative control fails at the player-visible table outcome.
    play(table, mid, find(table, mid, ROPE_SWING))
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
    play(table, mid, find(table, mid, ROPE_SWING))
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert any(c.condition_id == SWING for c in fighter.conditions.values())
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, fighter)
    assert find(table, mid, "rope_swing_climb")
