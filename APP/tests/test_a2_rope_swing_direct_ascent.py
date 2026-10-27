"""A clear same-column Rope Swing climb survives a table commit and reload."""
from combat.gate2_runtime_models import Position
from tests.test_a2_athletics_table_reloads import setup, fresh
from tests.test_a2r23_athletics_map import (
    FIGHTER, FOE, ROPE, ROPE_SWING, events, find, play, table_fight,
)


def test_direct_ascent_spends_only_its_climb_allowance(tmp_path):
    arena = {"display_name": "Clear ascent", "width_squares": 12, "height_squares": 8,
             "trees": [{"x": 9, "y": 2, "size": 1, "height_ft": 10,
                        "occluder": "centerline"}],
             "starts": {"team1": [[4, 4]], "team2": [[8, 6]]}}
    combat, table, mid = table_fight(
        tmp_path, [ROPE_SWING], kit=ROPE, map_doc=arena,
        where={FIGHTER: {"x": 4, "y": 4}, FOE: {"x": 8, "y": 6}},
        control_modes={FIGHTER: "MANUAL", FOE: "MANUAL"},
        bundle_transform=lambda bundles: setup(bundles, fly=30, climb=10))

    def anchor(prompt):
        option = next(row for row in prompt["choice"]["options"] if row["id"] == "cell:4,4,2")
        return {**prompt["context"], "selection": "USE", "option_ids": [option["id"]]}

    play(table, mid, find(table, mid, ROPE_SWING), answer=anchor)
    assert fresh(combat, mid).state.actors[FIGHTER].position == Position(x=4, y=4, z=0)
    play(table, mid, find(table, mid, "rope_swing_climb"))
    engine = fresh(combat, mid)
    assert engine.state.actors[FIGHTER].position == Position(x=4, y=4, z=2)
    move = events(engine, "MOVEMENT_COMMITTED", FIGHTER)[-1]
    assert move.payload["cost_ft"] == 10
    assert move.payload["path"] == [{"x": 4, "y": 4, "z": z} for z in range(3)]
