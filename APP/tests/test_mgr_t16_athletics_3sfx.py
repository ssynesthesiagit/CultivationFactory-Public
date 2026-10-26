"""Paid cover and elevated material connectors through table commit/reload."""
import pytest

from combat.ext import athletics
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.athletics_action_support import add_action
from tests.test_mgr_t16_athletics import (
    game, commit, move_at, ROOT, OWNER, MULTIPLE, MOVING, MOBILITY,
    SHARK, GLIDE, FOCUS, reload_identical,
)
from tests.test_mgr_t16_athletics_3sf import select, action


@pytest.mark.parametrize('second_motion,allowed', [(MOBILITY, False), (MOVING, True)])
def test_paid_cover_requires_forty_selected_feet_after_reload(tmp_path, second_motion, allowed):
    def prepare(bundles):
        next(b for b in bundles if b['actor_id'] == OWNER)['actor_template']['speed_ft'] = 60
    service, table, mid = game(tmp_path, [MULTIPLE, MOVING, MOBILITY], prepare=prepare)
    commit(table, mid, move_at(table, mid, 8), select(MOVING))  # 25 selected feet
    commit(table, mid, move_at(table, mid, 11), select(second_motion))  # 15 more
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    options = [o for group in table.state(mid)['menu']['actions'] for o in group['options']
               if o['label'] == athletics.MOVING_TARGET_LABEL]
    assert bool(options) is allowed
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert cold.state.actors[OWNER].resources[FOCUS] == 1
    assert athletics._moving_target(cold, cold.state.actors[OWNER]) == 2
    if allowed:
        commit(table, mid, options[0])
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert cold.state.actors[OWNER].resources[FOCUS] == (0 if allowed else 1)
    assert athletics._moving_target(cold, cold.state.actors[OWNER]) == (5 if allowed else 2)
    reload_identical(service, mid, tmp_path)


@pytest.mark.parametrize('medium,cost', [(False, 10), (True, 5)])
def test_prone_elevated_glide_connector_preview_menu_commit_reload(tmp_path, medium, cost):
    def prepare(bundles):
        add_action(next(b for b in bundles if b['actor_id'] == OWNER), 'Lie down',
                   [{'type': 'condition', 'condition': 'prone', 'applies_to': 'self'}])
    cells = [{'x': x, 'y': y} for x in range(2, 7) for y in range(5, 8)]
    arena = {'roof_surfaces': [{'id': 'dry-roof', 'height_ft': 10, 'cells': cells}]}
    if medium:
        # Water above the roof: genuine in-medium swimming, independently of Prone.
        arena['terrain_regions'] = [{'region_id': 'water', 'terrain_type': 'OPEN',
            'material_only': True, 'material': 'water', 'base_altitude_ft': 10,
            'height_ft': 10, 'cells': cells}]
    service, table, mid = game(tmp_path, [SHARK, GLIDE], prepare=prepare,
                               arena_update=arena, starting_z=2)
    commit(table, mid, action(table, mid, 'Lie down'))
    cold = CombatService(ROOT, tmp_path)._load_session(mid).engine
    owner = cold.state.actors[OWNER]
    assert owner.position.z == 2
    assert any(c.condition_id == 'condition:typed.prone' for c in owner.conditions.values())
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    menu = table.state(mid)['menu']
    path = [{'x': 3, 'y': 6, 'z': 2}, {'x': 4, 'y': 6, 'z': 2}]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, path, 'swim')
    assert quote['candidate']['movement_cost_ft'] == cost
    assert move_at(table, mid, 4, mode='swim', z=2)['cost_ft'] == cost
    result = table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
                                   menu['state_version'], OWNER, path, movement_mode='swim')
    assert result['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].position.model_dump() == path[-1]
    assert fresh.state.actors[OWNER].movement_remaining_ft == owner.movement_remaining_ft - cost
    reload_identical(service, mid, tmp_path)
