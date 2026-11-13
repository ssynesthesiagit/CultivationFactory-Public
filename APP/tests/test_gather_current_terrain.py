"""Gather Current's chosen Vector alone determines terrain, including after reload."""
import pytest

from tests.auto_worker1_support import ALLY, LEFT, RIGHT, cell_send, reload, resolve, turn
from tests.test_a2_air_second_pass import fight, move_to

GATHER = "AIR_BASE_GATHER_CURRENT"
AIM = (6, 6)
# A 10-foot cube aimed at (6, 6) covers squares 5-6 on both axes (combat/typed_executor.py in_area keeps the
# negative edge), so both hostiles start inside the Current and both step into a square inside it: an area that
# charged everyone, or nobody, still shows up in the price.
POSITIONS = {LEFT: {"x": 2, "y": 2}, RIGHT: {"x": 5, "y": 6}, ALLY: {"x": 6, "y": 5}}
STEPS = {RIGHT: (6, 6, 0), ALLY: (5, 5, 0)}
PRESS_MARK = "condition:typed.mark.air_press."


@pytest.mark.parametrize("vector", ["Lift", "Scatter", "Carry", "Turn", "Press"])
def test_vector_terrain_and_movement_survive_reload(tmp_path, vector):
    combat, table, match = fight(
        tmp_path, [GATHER], cl=1, ally=True, ally_team="team:opponents", positions=POSITIONS)
    resolve(cell_send(table, match, f"Gather Current: {vector}", AIM))
    engine = reload(combat, match)
    zone = next(iter(engine.state.zones.values()))
    assert zone.trigger_profile.get("difficult") == ("marked:Air Press" if vector == "Press" else None)

    # Both hostiles start inside the same Current. Press reaches only the first of them to start its turn
    # there, so that one pays double and the next one does not inherit the penalty: follow the fight's own
    # initiative order instead of assuming which hostile that is.
    order = [aid for aid in engine.state.initiative_order if aid in STEPS]
    assert len(order) == 2, order
    first, second = order
    for actor, expected in ((first, 10 if vector == "Press" else 5), (second, 5)):
        turn(table, match, actor)
        before = reload(combat, match)
        assert before.state.zones[zone.zone_id].active, "the Current lasts until the start of the caster's next turn"
        marked = any(c.condition_id.startswith(PRESS_MARK)
                     for c in before.state.actors[actor].conditions.values())
        assert marked == (vector == "Press" and actor == first)
        remaining = before.state.actors[actor].movement_remaining_ft
        resolve(move_to(combat, table, match, STEPS[actor]))
        after = reload(combat, match)
        assert remaining - after.state.actors[actor].movement_remaining_ft == expected
