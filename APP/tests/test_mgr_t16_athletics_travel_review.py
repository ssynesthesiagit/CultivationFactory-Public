"""F1–F4: real service transactions and cold reload; no network/model clients."""
import json
import pytest

from combat.gate5_service import CombatService
from tests.test_mgr_t16_athletics_travel import game, activate, owner, scene, A, B, SOURCE, FOCUS, ROOT


def test_f1_two_encounters_preserve_wounds_defeat_and_conditions(tmp_path, monkeypatch):
    from combat.tabletop_service import TabletopService
    from tests.auto8f1_table_support import candidate_id
    from combat.ext.journey_setup import encounter_snapshot
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=arena)
    # A deterministic prior injury. The first encounter must then defeat B
    # through the actual table, rather than importing an edited combat save.
    session = cold().journeys.load(jid)
    condition = {'instance_id': 'injury', 'condition_id': 'prone',
                 'source_definition_id': 'journey:injury', 'source_actor_id': A,
                 'target_id': A, 'stacks': 1, 'applied_sequence': 0, 'expires_on': 'UNTIL_REMOVED', 'data': {}}
    for aid, hp in ((A, 20), (B, 1)):
        session.state['actors'][aid]['encounter_snapshot'] = {
            'maximum_hp': 60, 'current_hp': hp, 'temporary_hp': 7 if aid == A else 0,
            'active': 1, 'life_state': 'CONSCIOUS',
            'conditions': {'injury': json.dumps(condition)} if aid == A else {}}
    with cold().journeys.locked(jid):
        cold().journeys.save(session)
    spots = {A: {'x': 3, 'y': 6}, B: {'x': 4, 'y': 6}}
    match = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=20, positions=spots)
    mid = match['match_id']
    for _ in range(100):
        fresh = cold()
        fight = fresh._load_session(mid)
        if fight.engine.state.terminal_result is not None:
            break
        table = TabletopService(fresh, fresh.userdata_root)
        menu = table.state(mid)['menu']
        if menu['actor_id'] == A:
            try:
                cid = candidate_id(menu, 'Unarmed Strike')
            except AssertionError:
                cid = menu['end_turn']
        else:
            cid = menu['end_turn']
        table.act(mid, cid, menu['decision_id'], menu['state_version'], 0)
    fight = cold()._load_session(mid)
    assert fight.engine.state.terminal_result is not None
    expected = {aid: encounter_snapshot(fight.engine.state.actors[aid]) for aid in (A, B)}
    assert expected[A]['current_hp'] == 20 and expected[A]['temporary_hp'] == 7
    assert expected[B]['current_hp'] == 0 and expected[B]['active'] == 0
    state = cold().journey_state(jid)
    with pytest.raises(ValueError, match='Choose a creature'):
        cold().journey_act(jid, state['revision'], 'unknown', 'finish')
    resumed = cold().journey_resume(jid, state['revision'])
    assert cold().journey_state(jid) == resumed
    assert {aid: resumed['actors'][aid]['encounter_snapshot'] for aid in (A, B)} == expected
    next_match = cold().journey_start_combat(jid, resumed['revision'], {A: 'team:a', B: 'team:b'}, positions=spots)
    second = cold()._load_session(next_match['match_id'])
    for aid in (A, B):
        assert encounter_snapshot(second.engine.state.actors[aid]) == expected[aid]
    assert cold()._load_session(next_match['match_id']).engine.state.model_dump(mode='json') == second.engine.state.model_dump(mode='json')


def test_f1_unsupported_timed_continuation_rejects_before_save(tmp_path, monkeypatch):
    from combat.ext.journey_setup import encounter_snapshot
    from combat.gate2_runtime_models import ConditionInstance
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid, _ = game(tmp_path, monkeypatch, battlefield=arena)
    match = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, positions={A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}})
    actor = cold()._load_session(match['match_id']).engine.state.actors[A]
    actor.conditions['timed'] = ConditionInstance(instance_id='timed', condition_id='poisoned',
        source_definition_id='test', source_actor_id=A, target_id=A, applied_sequence=0,
        expires_on='TURN_END', expires_turn_count=2)
    with pytest.raises(ValueError, match='timed or unsupported'):
        encounter_snapshot(actor)


def test_f2_bound_combat_keeps_exclusive_ownership_then_explicit_release(tmp_path, monkeypatch):
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=arena)
    activate(act)
    old = cold().journeys.load(jid)
    state = cold().journey_state(jid)
    match = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1,
        positions={A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}})
    with pytest.raises(ValueError, match='already in'):
        cold().create_journey(project_ids=['traveller'], arena_id='scene', positions={A: {'x': 1, 'y': 1}}, base_paces={A: 5})
    with pytest.raises(ValueError, match='Resume'):
        act('finish')
    from combat.tabletop_service import TabletopService
    for _ in range(6):
        fresh = cold()
        if fresh._load_session(match['match_id']).engine.state.terminal_result is not None:
            break
        table = TabletopService(fresh, fresh.userdata_root)
        menu = table.state(match['match_id'])['menu']
        table.act(match['match_id'], menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
    state = cold().journey_state(jid)
    cold().journey_resume(jid, state['revision'])
    act('finish')
    fresh = cold().create_journey(project_ids=['traveller'], arena_id='scene', positions={A: {'x': 1, 'y': 1}}, base_paces={A: 5})
    assert owner(fresh)['resources'][FOCUS] == 0 and owner(fresh)['travel_uses'][SOURCE] == 0
    with cold().journeys.locked(jid), pytest.raises(ValueError, match='finished'):
        cold().journeys.save(old)
    with pytest.raises(ValueError):
        cold().journey_resume(jid, cold().journey_state(jid)['revision'])
    assert cold().journey_state(fresh['journey_id']) == fresh


def test_f3_carried_owner_moves_for_elapsed_clock_after_reload(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, companion_owner=True)
    def commit(aid, kind, payload):
        before = cold().journey_state(jid)
        result = cold().journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == result
        return result
    for aid in (A, B): commit(aid, 'activate', {'source': SOURCE})
    commit(A, 'request_carry', {'target_id': B})
    commit(B, 'carry_reply', {'accept': True})
    state = commit(A, 'move', {'path': [{'x': 1, 'y': 1}]})
    assert state['seconds'] == 360
    for aid in (A, B):
        assert state['actors'][aid]['travel_effects'][SOURCE]['stopped_seconds'] == 0
    assert state['actors'][A]['position'] == state['actors'][B]['position']


@pytest.mark.parametrize('trapped', [False, True])
def test_f4_auto_decline_moves_after_reload_but_request_remains_selectable(tmp_path, monkeypatch, trapped):
    battlefield = {**scene(), 'width_squares': 2, 'height_squares': 1} if trapped else scene()
    cold, jid, act = game(tmp_path, monkeypatch, mode='LOCAL_AUTO', pace=1800,
        battlefield=battlefield, positions={A: {'x': 0, 'y': 0}, B: {'x': 1, 'y': 0}})
    state = cold().journey_auto_step(jid, 0, A)
    state = cold().journey_auto_step(jid, state['revision'], A)
    assert state['carry_request']['target'] == B
    state = act('carry_reply', {'accept': False}, B)
    requests = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'request_carry']
    assert len(requests) == 1
    after = cold().journey_auto_step(jid, state['revision'], A)
    if trapped:
        assert after == state  # No move is legal; do not re-prompt the refusal.
    else:
        assert after['seconds'] > state['seconds'] and 'carry_request' not in after
    assert cold().journey_state(jid) == after
    if not trapped:
        act('move', {'path': [{'x': 0, 'y': 0}]})
    after = cold().journey_state(jid)
    # Refusal changes automatic preference, never the legal option catalogue.
    request = next(o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'request_carry')
    explicit = cold().journey_auto_step(jid, after['revision'], A, request['id'])
    assert explicit['carry_request']['target'] == B
