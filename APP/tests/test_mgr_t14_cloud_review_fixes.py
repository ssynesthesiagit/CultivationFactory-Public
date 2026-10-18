"""Fast regressions for the Sol review findings on the Cloud Walker branch.

Each test is a table-level check that fails without its fix:
  1. Heavenly Leap's impulse search offers vertical destinations.
  2. Feather's distance multiplier enables straight and low-Strength high jumps.
  3. Swimming/unstable-footing segment costs are part of the shared step price.
  4. The stock comparison wrapper pins no private historical commit.
"""
from pathlib import Path

from combat import flight
from combat.ext.qi_subpaths_five import CLOUD
from tests.worker2_support import fixture, reload, OWNER


def test_heavenly_leap_impulse_search_offers_vertical_destinations(tmp_path):
    combat, table, match_id = fixture(
        tmp_path, [], cl=14, owner_features=[CLOUD + 'heavenly_leap'], ask=False)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    routes = flight.reachable(engine, actor, grant_ft=120, mode='impulse')
    vertical = {cell: route for cell, route in routes.items() if cell.z != actor.position.z}
    assert vertical, 'Heavenly Leap must offer destinations above or below its starting altitude'
    for cell, (path, cost, mode) in vertical.items():
        assert mode == 'impulse'
        assert path[0] == actor.position and path[-1] == cell


def test_feather_multiplier_enables_straight_long_jump_without_bonus(tmp_path):
    combat, table, match_id = fixture(
        tmp_path, [], cl=3, owner_features=[CLOUD + 'light_as_a_feather'], owner_speed=30, ask=False)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    assert flight.horizontal_jump_bonus(engine, actor) == 0
    assert flight.jump_distance_multiplier(engine, actor) == 3
    jumps = flight.horizontal_jumps(engine, actor)
    assert jumps, 'Feather alone must enable straight long jumps'
    far = [cell for cell in jumps if engine.grid.distance_ft(actor.position, cell) > engine.grid.square_size_ft]
    assert far, 'the long jump must cross more than one square'
    for cell in far:
        path, cost, mode = jumps[cell]
        assert all(p.z == actor.position.z for p in path), 'a long jump lands level'


def test_feather_low_strength_high_jump_is_not_filtered_out(tmp_path):
    combat, table, match_id = fixture(
        tmp_path, [], cl=3, owner_features=[CLOUD + 'light_as_a_feather'], owner_speed=30, ask=False)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    if flight.jump_score(engine, actor)[0] >= 14:
        # Below the printed Strength 14 gate, but a strength whose tripled standing
        # jump (4 feet -> 12 feet running, 6 standing) still earns a whole square.
        actor.strength_score = 12
    result = flight.jumps(engine, actor, {})
    assert any(cell.z > actor.position.z for cell in result), \
        'a Feather owner below the Strength gate still gets a high jump'


def test_segment_surcharge_is_part_of_the_shared_step_price(tmp_path, monkeypatch):
    combat, table, match_id = fixture(
        tmp_path, [], cl=3, owner_features=[CLOUD + 'light_as_a_feather'], owner_speed=30, ask=False)
    engine = reload(tmp_path, match_id)
    actor = engine.state.actors[OWNER]
    from combat import movement_costs
    start = actor.position
    end = start.model_copy(update={'x': start.x + 1})
    base = flight.step_cost(engine, actor, start, end, 'walk')
    monkeypatch.setattr(movement_costs, 'segment_surcharge', lambda *args: 5)
    assert flight.step_cost(engine, actor, start, end, 'walk') == base + 5 * engine._drag_multiplier(actor)


def test_stock_wrapper_pins_no_private_history():
    source = (Path(__file__).parent / 'test_mgr_t14_cloud_stock.py').read_text()
    assert '8bd818c78df011c2b67145d8e33975468c3e6a75' not in source
    assert "setattr(stock, 'EVIDENCE'" not in source
    assert 'CF_STOCK_EVIDENCE' in source
