"""Merged Afterimage uses committed steps and preserves Motion receipts."""
import pytest

from combat import motion
from tests.test_a2r23_athletics_map import FIGHTER, FOE, ONE_BREATH, find, play, table_fight
from tests.test_a2_athletics_table_reloads import athletics_receipt, fresh, route, setup


@pytest.mark.parametrize("one_breath", [False, True])
def test_afterimage_crossing_is_once_per_turn_and_records_owned_motion_after_reload(tmp_path, one_breath):
    talents = ["TAL_ATHLETICS_AFTERIMAGE"] + ([ONE_BREATH] if one_breath else [])
    combat, table, mid = table_fight(tmp_path, talents, bundle_transform=setup,
                                   where={FIGHTER: {"x": 3, "y": 4}, FOE: {"x": 10, "y": 7}})
    if one_breath:
        play(table, mid, find(table, mid, ONE_BREATH))
    # Exactly 20 feet does not cross the printed threshold.
    route(table, mid, [{"x": x, "y": 4} for x in range(3, 8)])
    assert not motion.has_afterimage(fresh(combat, mid).state.actors[FIGHTER])
    route(table, mid, [{"x": 7, "y": 4}, {"x": 8, "y": 4}])
    engine = fresh(combat, mid)
    actor = engine.state.actors[FIGHTER]
    assert motion.has_afterimage(actor)
    assert actor.turn_flags["athletics_afterimage_distance_ft"] == 25
    assert actor.turn_flags["athletics_afterimage_created"] == 1
    assert athletics_receipt(engine, "TAL_ATHLETICS_AFTERIMAGE") is one_breath
    play(table, mid, find(table, mid, "review.clear_afterimage"))
    route(table, mid, [{"x": 8, "y": 4}, {"x": 9, "y": 4}])
    assert not motion.has_afterimage(fresh(combat, mid).state.actors[FIGHTER])
