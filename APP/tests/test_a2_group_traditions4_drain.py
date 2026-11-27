"""Soul Drain's printed CP veto uses the existing native gain gate."""
import copy

import pytest

from combat.gate5_service import CombatService
from test_riders_c8 import ROOT, ME, MIND_SPIKE, SW_ALL, bundle, held
from test_a2_group_traditions4 import ENEMY, act, advance, reload


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('failed', [True, False])
def test_soul_drain_cp_recovery_veto_and_target_turn_expiry(tmp_path, control, failed):
    service = CombatService(ROOT, tmp_path)
    owner = bundle(SW_ALL, resonance=100, dc=40 if failed else 1)
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY, cl=5)
    if not failed:
        enemy['actor_template']['saving_throws']['CON'] = 100
    for doc in (owner, enemy):
        doc['actor_template']['maximum_hp'] = 1000
    for resource in enemy['actor_template']['resources']:
        if resource['resource_id'] == 'resource:core.resonance':
            resource['initial'] = 20
    recovery = copy.deepcopy(next(a for a in enemy['action_catalog'] if a['display_name'] == 'Mind Spike'))
    recovery.update(source_definition_id=recovery['source_definition_id'] + '.test_recovery',
                    display_name='Test CP recovery', target_kind='SELF', range_ft=0, costs=[])
    recovery['parameters']['typed']['effects'] = [{'type': 'gain_resource', 'resource_id': 'resource:core.resonance',
                                                  'flat': 5, 'applies_to': 'self'}]
    enemy['action_catalog'].append(recovery)
    enemy['actor_template']['action_ids'].append(recovery['source_definition_id'])
    session = service.persistence.create_match(
        match_seed='A2GTRA4-DRAIN', maximum_rounds=20, typed_bundles=(owner, enemy),
        roster_setup={'primary_actor_ids': [ME, ENEMY], 'team_by_actor': {ME: 'team:a', ENEMY: 'team:b'},
                      'starting_positions': {ME: {'x': 6, 'y': 6}, ENEMY: {'x': 8, 'y': 6}}})
    metadata = {'participant_control_modes': {ME: control, ENEMY: 'MANUAL'}}
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Soul Drain and Death Custody: Necrotic', ENEMY)
    session = reload(service, session)
    assert bool(held(session.engine.state.actors[ENEMY], 'condition:typed.no_cp_regain')) == failed
    advance(service, session, metadata, ENEMY)
    before = session.engine.state.actors[ENEMY].resources['resource:core.resonance']
    events, _, _ = act(service, session, metadata, 'Test CP recovery')
    session = reload(service, session)
    assert session.engine.state.actors[ENEMY].resources['resource:core.resonance'] == before + (0 if failed else 5)
    assert any(e.event_type == 'GM_RIDER' and e.payload.get('automated') for e in events) == failed
    act(service, session, metadata, 'End turn')
    session = reload(service, session)
    assert not held(session.engine.state.actors[ENEMY], 'condition:typed.no_cp_regain')
    advance(service, session, metadata, ENEMY)
    before = session.engine.state.actors[ENEMY].resources['resource:core.resonance']
    act(service, session, metadata, 'Test CP recovery')
    session = reload(service, session)
    assert session.engine.state.actors[ENEMY].resources['resource:core.resonance'] == before + 5
