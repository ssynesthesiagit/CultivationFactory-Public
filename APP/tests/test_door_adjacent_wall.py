"""Wall-mounted ordinary doors use the real table menu, commit and cold reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_door_interaction import ROOT, ME, FOE, DOOR, cold
from tests.test_zones import SHEET


@pytest.mark.parametrize('axis', ['h', 'v'])
@pytest.mark.parametrize('side', [-1, 1])
def test_adjacent_wall_door_open_close_table_commit_reload(tmp_path, axis, side):
    door_xy = {'x': 6, 'y': 6}
    cross = 'y' if axis == 'h' else 'x'
    origin = {**door_xy, cross: 6 + side}
    wall = {'shape': 'line', 'points': [[0, 6], [11, 6]] if axis == 'h'
            else [[6, 0], [6, 11]]}
    arena = to_battlefield(normalize_map({'width_squares': 12, 'height_squares': 12,
        'walls': [wall], 'objects': [{'id': 1, 'kind': 'door', 'name': 'Reading room door',
            **door_xy, 'mount_axis': axis, 'mount_line': 600, 'height_ft': 10,
            'interaction': 'simple_door', 'door_open': 0, 'door_locked': 0, 'door_jammed': 0}]}))
    sheet = {**SHEET, 'spheres_and_talents': {}}
    service = CombatService(ROOT, tmp_path)
    bundles = [compile_character(sheet, actor_id=actor) for actor in (ME, FOE)]
    mid = service._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: origin, FOE: {'x': 1, 'y': 1}}, arena, [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed=f'DOORFIX-{axis}-{side}',
        display_name='Adjacent wall door', maximum_rounds=5)['match_id']
    table = TabletopService(service, tmp_path)

    def act(candidate_id, menu):
        return table.act(mid, candidate_id, menu['decision_id'], menu['state_version'], 0, [])

    menu = table.state(mid)['menu']
    if menu['actor_id'] != ME:
        # Selecting a nearby fighter cannot grant it an interaction off-turn.
        assert not any(ME == c.actor_id for c in service._load_session(mid).engine.legal_candidates())
        assert act(menu['end_turn'], menu)['status'] == 'COMMITTED'
    for operation, payment, opened in [('open', 'free', 1), ('close', 'utilize', 0)]:
        menu = table.state(mid)['menu']
        assert menu['actor_id'] == ME
        group, = [g for g in menu['actions']
                  if g['source_definition_id'] == f'system:door.{operation}.{payment}']
        option, = [o for o in group['options'] if o['target_ids'] == [DOOR]]
        assert act(option['candidate_id'], menu)['status'] == 'COMMITTED'
        session = cold(tmp_path, service._load_session(mid))
        assert session.engine.state.objects[DOOR].component['door_open'] == opened
        assert ((6, 6) in session.engine.grid.blocked) is not bool(opened)
        service = CombatService(ROOT, tmp_path)
        table = TabletopService(service, tmp_path)
        token, = [o for o in table.state(mid)['objects'] if o['id'] == DOOR]
        assert token['open'] is bool(opened)


def test_spent_action_does_not_spend_free_door_interaction(tmp_path):
    from tests.test_door_interaction import setup
    service, session = setup(tmp_path)
    table = TabletopService(service, tmp_path)
    menu = table.state(session.match_id)['menu']
    dodge, = [g for g in menu['actions'] if g['source_definition_id'] == 'system:combat.dodge']
    assert table.act(session.match_id, dodge['options'][0]['candidate_id'],
        menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    session = cold(tmp_path, service._load_session(session.match_id))
    assert not session.engine.state.actors[ME].action_available
    menu = table.state(session.match_id)['menu']
    opening, = [g for g in menu['actions'] if g['source_definition_id'] == 'system:door.open.free']
    assert table.act(session.match_id, opening['options'][0]['candidate_id'],
        menu['decision_id'], menu['state_version'], 0, [])['status'] == 'COMMITTED'
    session = cold(tmp_path, service._load_session(session.match_id))
    assert session.engine.state.objects[DOOR].component['door_open'] == 1
