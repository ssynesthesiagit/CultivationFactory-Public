"""Both merge parents' movement laws survive a table commit and cold reload."""
import pytest

from combat.ext import athletics
from combat.gate5_service import CombatService
from tests.auto8f1_table_support import OWNER, reload_identical
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics import GLIDE, MULTIPLE, SHARK, commit, game, move_at

WALL = 'TAL_ATHLETICS_WALL_STUNT'


@pytest.mark.parametrize('medium,shark,cost', [('soil', True, 10), ('water', False, 10), ('water', True, 5)])
def test_wall_and_material_ownership_keep_both_step_prices_after_reload(tmp_path, medium, shark, cost):
    talents = [WALL, MULTIPLE, GLIDE] + ([SHARK] if shark else [])
    terrain = {} if medium == 'soil' else {'arena_update': {'terrain_regions': [{
        'region_id': 'water', 'terrain_type': 'WATER', 'movement_cost': 1,
        'cells': [{'x': 4, 'y': 6}],
    }]}}
    if medium == 'soil':
        terrain['material'] = 'soil'
    service, table, mid = game(tmp_path, talents, **terrain)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert all(athletics.owns(engine, actor, kind)
               for kind in ('wall_stunt', 'multiple_motions', 'terrain_glide'))
    before = actor.movement_remaining_ft
    move = move_at(table, mid, 4, mode='swim' if medium == 'soil' else 'walk')
    assert move['cost_ft'] == cost
    commit(table, mid, move)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = fresh.state.actors[OWNER]
    assert actor.position.x == 4 and actor.movement_remaining_ft == before - cost
    receipt = next(e for e in reversed(fresh.events)
                   if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert receipt.payload['cost_ft'] == cost
    reload_identical(service, mid, tmp_path)
