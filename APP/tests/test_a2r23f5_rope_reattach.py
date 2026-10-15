"""Repeated Rope Swing attachments through table commits and cold reloads."""

from combat import ext
from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, ROPE, ROPE_SWING, SWING, engine_of, find, play, table_fight,
)


KEEP = {"display_name": "Reattachment keep", "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "rect", "points": [[2, 2], [6, 6]], "filled": False,
                   "blocks": "sight_and_movement", "storeys": 1}],
        "roofs": {"enabled": True, "height_ft": 10},
        "starts": {"team1": [[4, 4]], "team2": [[4, 5]]}}


def rope_table(tmp_path):
    return table_fight(
        tmp_path, [ROPE_SWING], kit=ROPE, map_doc=KEEP,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 4, "y": 5}},
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"})


def attach(table, mid, anchor=None):
    def answer(prompt):
        assert prompt["context"]["reaction_source_id"] == "choice:needle.rope_anchor"
        if anchor is None:
            return {**prompt["context"], "selection": "DECLINE"}
        option = cell_id(anchor)
        assert option in {row["id"] for row in prompt["choice"]["options"]}
        return {**prompt["context"], "selection": "USE", "option_ids": [option]}

    result, prompts = play(table, mid, find(table, mid, ROPE_SWING), answer=answer)
    assert result["status"] == "COMMITTED"
    assert len(prompts) == 1


def next_fighter_turn(table, mid):
    for _ in range(2):
        result, _ = play(table, mid, table.state(mid)["menu"]["end_turn"])
        assert result["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == FIGHTER


def swings(actor):
    return [condition for condition in actor.conditions.values()
            if condition.condition_id == SWING and condition.source_definition_id == ROPE_SWING]


def test_reattach_replaces_anchor_after_reload_and_one_detach_ends_suspension(tmp_path):
    combat, table, mid = rope_table(tmp_path)
    old_anchor = Position(x=3, y=3, z=2)
    new_anchor = Position(x=5, y=3, z=2)
    attach(table, mid, old_anchor)
    next_fighter_turn(table, mid)
    attach(table, mid, new_anchor)

    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    attached = swings(fighter)
    assert len(attached) == 1, "reattaching replaces the previous owned swing"
    assert attached[0].data["anchor"] == [5, 3, 2]
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, fighter)
    result, _ = play(table, mid, find(table, mid, "rope_swing_climb"))
    assert result["status"] == "COMMITTED"
    assert engine_of(combat, mid).state.actors[FIGHTER].position == new_anchor

    result, _ = play(table, mid, find(table, mid, "rope_swing_detach"))
    assert result["status"] == "COMMITTED"
    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert not swings(fighter), "a single detach ends the attachment"
    assert {"flight_suspended": 1} not in ext.run_strict("flight", engine, fighter)
    assert not any("rope_swing_climb" in group["source_definition_id"]
                   or "rope_swing_detach" in group["source_definition_id"]
                   for group in table.state(mid)["menu"]["actions"])


def test_declining_reattach_preserves_the_current_anchor_after_reload(tmp_path):
    combat, table, mid = rope_table(tmp_path)
    anchor = Position(x=3, y=3, z=2)
    attach(table, mid, anchor)
    next_fighter_turn(table, mid)
    attach(table, mid)

    engine = engine_of(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert len(swings(fighter)) == 1
    assert swings(fighter)[0].data["anchor"] == [3, 3, 2]
    assert {"flight_suspended": 1} in ext.run_strict("flight", engine, fighter)
