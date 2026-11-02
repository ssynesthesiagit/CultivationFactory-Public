"""Regressions for the Riverway travel round: cost seams, water price, supported arrivals.

The suspended-cost hooks are strict providers: every subscriber must accept
exactly the documented argument list, and an authored water space costs one
extra square exactly once per entered edge. Travel commits settle on support,
so a route may cross open air but never end in it.
"""
import inspect

import pytest

from combat import ext, movement_costs
from combat.ext.riverway_passage import _cell_ok, _gap_ok
from combat.gate2_runtime_models import Position
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.test_mgr_t14_riverway_journey import A, game
from tests.test_mgr_t14_riverway_native import acquired  # noqa: F401  (module fixture shared by the journey table)
from tests.worker2_support import OWNER, fixture

SEAMS = {'movement_step_surcharge': 3, 'movement_segment_surcharge': 5}


def flat_map(tmp_path, *, route_regions=()):
    maps = TabletopMapStore(tmp_path / 'maps')
    maps.save({'map_id': 'riverway-flat', 'display_name': 'Open riverbank', 'width_squares': 12,
               'height_squares': 12, 'route_regions': list(route_regions)})
    return to_battlefield(maps.get('riverway-flat'))


def fight(tmp_path, *, route_regions=(), cl=3, seed='RIVERWAY-TRAVEL'):
    combat, _table, mid = fixture(tmp_path, [], cl=cl, battlefield=flat_map(tmp_path, route_regions=route_regions),
                                  seed=seed)
    return combat._load_session(mid).engine


def test_every_movement_cost_subscriber_matches_its_documented_arguments():
    """A subscriber with one extra parameter crashed every priced movement step."""
    for point, arity in SEAMS.items():
        assert ext.has(point), point
        for function in ext.subscribers(point):
            parameters = inspect.signature(function).parameters
            assert len(parameters) == arity, (point, function.__name__, list(parameters))


def test_authored_water_charges_one_square_when_a_walker_enters_it(tmp_path):
    """Entering authored water costs one extra square, once; leaving it costs nothing."""
    engine = fight(tmp_path, route_regions=[{'id': 'ford-water', 'kind': 'water', 'cells': [{'x': 5, 'y': 6}]}])
    actor = engine.state.actors[OWNER]
    bank, water = Position(x=4, y=6, z=0), Position(x=5, y=6, z=0)
    # The three-argument step seam must raise nothing (the round's blocked crash).
    assert movement_costs.surcharge(engine, actor) == 0
    assert movement_costs.segment_surcharge(engine, actor, bank, water, 'walk') == engine.grid.square_size_ft
    assert movement_costs.segment_surcharge(engine, actor, water, bank, 'walk') == 0


def test_a_passage_occupies_supported_visible_spaces_and_may_only_cross_gaps_when_greater(tmp_path):
    """Open air is never a Passage space; a Greater Passage crosses at most 10 feet of gap."""
    engine = fight(tmp_path)
    actor = engine.state.actors[OWNER]
    ground, air = Position(x=3, y=6, z=0), Position(x=3, y=6, z=1)
    assert _cell_ok(engine, actor, ground)
    assert not _cell_ok(engine, actor, air)
    assert _gap_ok(engine, air, 0, True)
    assert not _gap_ok(engine, air, 2, True)
    assert not _gap_ok(engine, air, 0, False)


def test_travel_route_cannot_stop_in_unsupported_air(tmp_path, monkeypatch, acquired):
    """Travel settles arrivals: a route that would end in open air is refused, not suspended."""
    _cold, _jid, act = game(tmp_path, monkeypatch, acquired, cl=14)
    with pytest.raises(ValueError, match='supported space'):
        act('move', {'path': [{'x': 4, 'y': 7, 'z': 1}]})
    assert act('move', {'path': [{'x': 4, 'y': 7}]})['actors'][A]['position'] == {'x': 4, 'y': 7, 'z': 0}
