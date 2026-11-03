"""Gather Current's chosen Vector alone determines terrain, including after reload."""
import pytest

from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, cell_send, reload, resolve, turn
from tests.test_a2_air_second_pass import fight, move_to

GATHER = "AIR_BASE_GATHER_CURRENT"


@pytest.mark.parametrize("vector", ["Lift", "Scatter", "Carry", "Turn", "Press"])
def test_vector_terrain_and_movement_survive_reload(tmp_path, vector):
    combat, table, match = fight(
        tmp_path, [GATHER], cl=1, ally=True, ally_team="team:opponents",
        positions={LEFT: {"x": 2, "y": 2}, RIGHT: {"x": 6, "y": 6},
                   ALLY: {"x": 6, "y": 7}},
    )
    resolve(cell_send(table, match, f"Gather Current: {vector}", (6, 6)))
    engine = reload(combat, match)
    zone = next(iter(engine.state.zones.values()))
    assert zone.trigger_profile.get("difficult") == ("marked:Air Press" if vector == "Press" else None)

    # Both start within the same Current. Only the first hostile can acquire
    # Press; a subsequent hostile must not inherit its movement penalty.
    for actor, destination, expected in (
        (RIGHT, (7, 6, 0), 10 if vector == "Press" else 5),
        (ALLY, (7, 7, 0), 5),
    ):
        turn(table, match, actor)
        before = reload(combat, match).state.actors[actor].movement_remaining_ft
        resolve(move_to(combat, table, match, destination))
        engine = reload(combat, match)
        assert before - engine.state.actors[actor].movement_remaining_ft == expected
