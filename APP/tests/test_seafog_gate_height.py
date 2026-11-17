"""Gate of the Inner Sea covers the printed 30-foot-high cylinder, not a sphere (SEAFOG).

The Gate is printed as a 25-foot-radius, 30-foot-high cylinder. Its reviewed row once recorded only the radius,
so the engine treated the field as a sphere reaching 25 feet up, and a creature 30 feet up (Guo Yuan) stayed
blind to the field's printed top. The regression casts the Gate through the table, reloads the saved fight, and
checks sight: a viewer on the ground can't see into the field, and above its 30-foot top the field no longer
blocks sight.
"""

from combat import zones
from combat.gate2_runtime_models import Position
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

GATE = "tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea"


def _gate_fight(tmp_path):
    combat, table, mid = fixture(tmp_path, [GATE], ask=False, seed="SEAFOG",
                                 positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 14, "y": 6}})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Gate of the Inner Sea", at=(8, 6)).candidate_id)
    return reload(tmp_path, mid)


def _sight(engine, viewer_at, target_at):
    viewer, target = engine.state.actors[FOE], engine.state.actors[OWNER]
    viewer.position, target.position = Position(**viewer_at), Position(**target_at)
    return zones.hidden_from(engine, viewer, target)


def test_gate_of_the_inner_sea_blocks_sight_only_up_to_its_thirty_foot_top(tmp_path):
    engine = _gate_fight(tmp_path)
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["height_ft"] == 30
    assert _sight(engine, {"x": 2, "y": 6, "z": 0}, {"x": 8, "y": 6, "z": 0})  # on the ground, outside, can't see in
    assert _sight(engine, {"x": 2, "y": 6, "z": 7}, {"x": 8, "y": 6, "z": 0})  # 35 ft up, but the target is inside the column
    assert not _sight(engine, {"x": 2, "y": 6, "z": 7}, {"x": 8, "y": 6, "z": 6})  # 30 ft up in the column: above the top, sight passes
