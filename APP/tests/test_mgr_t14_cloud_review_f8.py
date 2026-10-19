"""Journey reaction clocks use consumption, never another creature's landing."""
import json
import zipfile
from fractions import Fraction

from combat.ext.altitude_abilities import FEATHER
from combat.ext.cloud_walker import WIND
from combat.gate5_service import CombatService
from combat.journey_falling import engine_for
from tests.h1_support import ROOT, sheet


A = 'actor:factory.walker'
B = 'actor:factory.traveller'


def scene(tmp_path, height, *, companion_hp=60):
    for pid, features, cl in [('walker', [WIND, FEATHER], 10), ('traveller', [], 1)]:
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        doc = sheet(features, cl=cl, name=pid)
        if pid == 'traveller':
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = companion_hp
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',
                             json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Reaction recovery', 'width_squares': 12,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    state = service.create_journey(project_ids=['walker', 'traveller'],
        arena_id='battlefield:map.reaction-recovery',
        positions={A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}},
        base_paces={A: 18000, B: 18000}, control_modes={A: 'MANUAL', B: 'MANUAL'})
    jid = state['journey_id']

    def act(aid, kind, payload=None):
        cold = CombatService(ROOT, tmp_path)
        before = cold.journey_state(jid)
        after = cold.journey_act(jid, before['revision'], aid, kind, payload or {})
        assert CombatService(ROOT, tmp_path).journey_state(jid) == after
        assert cold.journey_verify(jid)['status'] == 'PASS'
        return after

    act(A, 'cloud_wind_begin')
    act(A, 'wait', {'seconds': 600})
    act(A, 'cloud_wind_invite', {'target_id': B})
    act(B, 'cloud_wind_reply', {'caster_id': A, 'accept': True})
    act(A, 'cloud_wind_finish')
    for aid, x in [(A, 3), (B, 4)]:
        act(aid, 'move', {'path': [{'x': x, 'y': 6, 'z': z} for z in range(1, height + 1)]})
    state = service.journey_state(jid)
    assert all(state['actors'][aid]['position'].get('z', 0) == height for aid in (A, B))
    native = engine_for(state)
    assert any(row.get('kind') == 'featherfall' for row in native.typed_passive_rows[A]), native.typed_passive_rows[A]
    return service, jid, act


def protect(act, state, target):
    """Answer the actual owner's native Featherfall choice, with a finite guard."""
    assert state.get('journey_fall_pending'), {
        'actors': {aid: {key: actor.get(key) for key in ('position', 'travel_effects', 'encounter_snapshot')}
                   for aid, actor in state['actors'].items()},
        'falls': [e for e in state['events'] if e['kind'] == 'JOURNEY_FALL_RESOLVED']}
    for _ in range(4):
        pending = state.get('journey_fall_pending')
        if not pending:
            return state
        assert pending['request']['reactor_id'] == A
        if target not in pending['selected']:
            state = act(A, 'journey_fall_select', {'option_id': target})
        else:
            state = act(A, 'journey_fall_reply', {'selection': 'USE'})
    raise AssertionError('Featherfall did not resolve after its selection and confirmation')


def test_unrelated_fall_preserves_spent_reaction_deadline_through_replay_and_reopen(tmp_path):
    service, jid, act = scene(tmp_path, 2)
    before = service.journey_state(jid)
    consumed_at = Fraction(before['seconds'])
    qi = before['actors'][A]['resources']['resource:core.qi']
    state = protect(act, act(B, 'cloud_wind_end'), B)
    deadline = consumed_at + 6
    assert Fraction(state['actors'][A]['journey_reaction_ready']) == deadline
    assert state['actors'][A]['resources']['resource:core.qi'] == qi - 1
    act(A, 'wait', {'seconds': 1})
    state = act(A, 'cloud_wind_end')
    assert not state.get('journey_fall_pending')
    assert Fraction(state['actors'][A]['journey_reaction_ready']) == deadline
    assert not engine_for(state).state.actors[A].reaction_available
    act(A, 'finish')
    cold = CombatService(ROOT, tmp_path)
    state = cold.create_journey(project_ids=['walker', 'traveller'],
        arena_id='battlefield:map.reaction-recovery',
        positions={A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}},
        base_paces={A: 18000, B: 18000}, control_modes={A: 'MANUAL', B: 'MANUAL'})
    new_jid = state['journey_id']
    assert Fraction(state['actors'][A]['journey_reaction_ready']) == 5
    assert not engine_for(state).state.actors[A].reaction_available
    state = cold.journey_act(new_jid, state['revision'], B, 'wait', {'seconds': 5})
    assert engine_for(state).state.actors[A].reaction_available
    assert CombatService(ROOT, tmp_path).journey_verify(new_jid)['status'] == 'PASS'


def test_long_descent_recovers_from_consumption_time_instead_of_landing(tmp_path):
    service, jid, act = scene(tmp_path, 25)
    before = service.journey_state(jid)
    consumed_at = Fraction(before['seconds'])
    state = protect(act, act(B, 'cloud_wind_end'), B)
    fall = next(e for e in reversed(state['events']) if e['kind'] == 'JOURNEY_FALL_RESOLVED')
    assert fall['elapsed_seconds'] == 12
    assert state['seconds'] == before['seconds'] + 12
    assert Fraction(state['actors'][A]['journey_reaction_ready']) == consumed_at + 6
    assert engine_for(state).state.actors[A].reaction_available
    assert state['actors'][B]['encounter_snapshot']['current_hp'] == before['actors'][B]['bundle']['actor_template']['maximum_hp']


def test_unprotected_injury_does_not_count_as_a_consumed_reaction(tmp_path):
    service, jid, act = scene(tmp_path, 2, companion_hp=1)
    state = act(B, 'cloud_wind_end')
    assert state.get('journey_fall_pending')
    state = act(A, 'journey_fall_reply', {'selection': 'DECLINE'})
    assert not state.get('journey_fall_pending')
    assert state['actors'][B]['encounter_snapshot']['current_hp'] == 0
    assert Fraction(state['actors'][A].get('journey_reaction_ready', '0')) == 0
