"""Seven map/carrying clauses through CombatService, native maps and cold disk."""
import asyncio
import httpx
import pytest

from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, TabletopMapStore, TabletopError
from tests.test_mgr_t16_athletics_travel import game, scene, activate, owner, A, B, SOURCE, FOCUS, ROOT


def terrain(kind, *, support=False, ordinary=True, cost=2, high=0):
    return {'kind': kind, 'cells': [[1, 1]], 'movement_cost': cost,
            'ordinary': ordinary, 'requires_support': support, 'max_z': high}


@pytest.mark.parametrize('kind', ['cliff', 'river', 'forest', 'broken_terrain'])
def test_no_slowing_rows_service_reload(tmp_path, monkeypatch, kind):
    battlefield = {**scene(), 'travel_regions': [terrain(kind)]}
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=battlefield)
    activate(act)
    state = act('move', {'path': [{'x': 1, 'y': 1}]})
    assert state['seconds'] == 360
    assert owner(state)['position'] == {'x': 1, 'y': 1}


def test_ordinary_water_row(tmp_path, monkeypatch):
    battlefield = {**scene(), 'travel_regions': [terrain('water', support=True, cost=1)]}
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=battlefield)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='capability'):
        act('move', {'path': [{'x': 1, 'y': 1}]})
    assert cold().journey_state(jid) == before
    activate(act)
    assert act('move', {'path': [{'x': 1, 'y': 1}]})['seconds'] == 360


def test_vertical_surfaces_row(tmp_path, monkeypatch):
    battlefield = {**scene(), 'travel_regions': [terrain('vertical_surface', support=True, cost=1, high=2)]}
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=battlefield)
    activate(act)
    state = act('move', {'path': [{'x': 1, 'y': 1}, {'x': 1, 'y': 1, 'z': 1}, {'x': 1, 'y': 1, 'z': 2}]})
    assert owner(state)['position'] == {'x': 1, 'y': 1, 'z': 2}
    assert state['seconds'] == 1080
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='support'):
        act('move', {'path': [{'x': 1, 'y': 1, 'z': 3}]})
    assert cold().journey_state(jid) == before


@pytest.mark.parametrize('carrier_mode,target_mode', [('MANUAL', 'MANUAL'), ('LOCAL_AUTO', 'MANUAL'), ('MANUAL', 'LOCAL_AUTO'), ('LOCAL_AUTO', 'LOCAL_AUTO')])
def test_willing_carried_creature_row_player_ai_consent(tmp_path, monkeypatch, carrier_mode, target_mode):
    # Reuse source-admission fixtures but create this party through the service.
    game(tmp_path / 'authority', monkeypatch)
    service = CombatService(ROOT, tmp_path / 'party')
    state = service.create_journey(project_ids=['traveller', 'companion'], arena_id='scene',
            positions={A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}}, base_paces={A: 5, B: 5},
            loaded_paces={A: 1}, control_modes={A: carrier_mode, B: target_mode})
    jid = state['journey_id']
    def cold(): return CombatService(ROOT, service.userdata_root)
    def act(kind, payload=None, aid=A):
        state = cold().journey_state(jid)
        after = cold().journey_act(jid, state['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == after
        return after
    if carrier_mode == 'LOCAL_AUTO':
        state = cold().journey_auto_step(jid, 0, A)
        assert SOURCE in owner(state)['travel_effects']
        state = cold().journey_auto_step(jid, state['revision'], A)
    else:
        activate(act)
        state = act('request_carry', {'target_id': B})
    if target_mode == 'MANUAL':
        assert 'carried_by' not in state['actors'][B]
        if carrier_mode == 'LOCAL_AUTO':
            assert cold().journey_auto_step(jid, state['revision'], A) == state
        answers = [o for o in cold().journey_menu(jid, B)['options'] if o['kind'] == 'carry_reply']
        assert len(answers) == 2
        assert all('Body Beyond Distance' in o['label'] and 'traveller' in o['label'] and 'companion' in o['label'] for o in answers)
        state = act('carry_reply', {'accept': True}, B)
    assert state['actors'][B]['carried_by'] == A
    state = act('move', {'path': [{'x': 1, 'y': 1}]})
    assert state['seconds'] == 360  # Even though the ordinary loaded pace is 1 ft/hour.
    assert state['actors'][B]['position'] == owner(state)['position']
    drops = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'set_down']
    chosen = next(o for o in drops if o['payload']['cell'] == {'x': 2, 'y': 1})
    state = act(chosen['kind'], chosen['payload'])
    assert state['actors'][B]['position'] == {'x': 2, 'y': 1}
    assert 'carried_by' not in state['actors'][B]


def test_declined_and_expired_requests_never_imply_consent(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    activate(act)
    act('request_carry', {'target_id': B})
    assert 'carried_by' not in act('carry_reply', {'accept': False}, B)['actors'][B]
    act('request_carry', {'target_id': B})
    assert 'carry_request' not in act('wait', {'seconds': 61})
    with pytest.raises(ValueError): act('carry_reply', {'accept': True}, B)


def test_carry_requires_sight_and_water_does_not_cross_a_solid_wall(tmp_path, monkeypatch):
    battlefield = scene()
    battlefield['roof_surfaces'] = [{'id': 'ceiling', 'height_ft': 5, 'cells': [{'x': 0, 'y': 1}]}]
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=battlefield)
    # Source a companion standing on the roof above the carrier. Journey
    # admission starts on the ground; this fixture supplies the upper landing.
    session = cold().journeys.load(jid)
    session.state['actors'][B]['position'] = {'x': 0, 'y': 1, 'z': 1}
    with cold().journeys.locked(jid):
        cold().journeys.save(session)
    activate(act)
    # These creatures are adjacent in 3D, with a closed roof between them.
    session = cold().journeys.load(jid)
    from combat.gate2_runtime_models import Position
    assert session.grid.distance_cells(Position(x=0, y=1), Position(x=0, y=1, z=1)) == 1
    assert not session.grid.line_of_sight(Position(x=0, y=1), Position(x=0, y=1, z=1))
    with pytest.raises(ValueError): act('request_carry', {'target_id': B})
    battlefield.pop('roof_surfaces')
    battlefield['terrain_regions'] = [{'region_id': 'solid', 'terrain_type': 'BLOCKED',
                                      'movement_cost': 0, 'cells': [{'x': 1, 'y': 1}]}]
    battlefield['travel_regions'] = [terrain('water', support=True, cost=1)]
    cold, jid, act = game(tmp_path / 'solid', monkeypatch, battlefield=battlefield)
    activate(act)
    with pytest.raises(ValueError, match='wall'): act('move', {'path': [{'x': 1, 'y': 1}]})


def test_magical_water_is_not_ordinary_water(tmp_path, monkeypatch):
    battlefield = {**scene(), 'travel_regions': [terrain('water', support=True, ordinary=False)]}
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=battlefield)
    activate(act)
    with pytest.raises(ValueError, match='capability'): act('move', {'path': [{'x': 1, 'y': 1}]})


def test_native_map_reload_and_unrelated_surcharge(tmp_path, monkeypatch):
    store = TabletopMapStore(tmp_path / 'maps')
    store.save({'display_name': 'Travel scene', 'width_squares': 20, 'height_squares': 10,
                'terrain': [{'type': 'DIFFICULT', 'travel_kind': 'forest', 'cells': [[1, 1]]}],
                'travel_regions': [terrain('forest')]})
    arena = store.arenas()['battlefield:map.travel-scene']
    assert arena['travel_regions'][0]['kind'] == 'forest'
    assert arena['terrain_regions'][0]['travel_kind'] == 'forest'
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=arena)
    activate(act)
    assert act('move', {'path': [{'x': 1, 'y': 1}]})['seconds'] == 360
    arena['terrain_regions'].append({'region_id': 'unrelated', 'terrain_type': 'OPEN', 'movement_cost': 3, 'cells': [{'x': 1, 'y': 1}]})
    cold, jid, act = game(tmp_path / 'overlap', monkeypatch, battlefield=arena)
    activate(act)
    assert act('move', {'path': [{'x': 1, 'y': 1}]})['seconds'] == 1080
    with pytest.raises(TabletopError): normalize_map({'display_name': 'Bad', 'travel_regions': [terrain('unknown')]})


def test_real_combat_transition_paid_focus_and_cold_replay(tmp_path, monkeypatch):
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=arena)
    activate(act)
    state = cold().journey_state(jid)
    match = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1,
                                       positions={A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}})
    state = cold().journey_state(jid)
    assert state['phase'] == 'combat' and not owner(state)['travel_effects']
    loaded = cold()._load_session(match['match_id'])
    assert loaded.engine.state.actors[A].resources[FOCUS] == 0
    assert SOURCE not in loaded.engine.action_catalog
    assert A in loaded.engine.state.actors and B in loaded.engine.state.actors
    assert loaded.engine._effective_speed(loaded.engine.state.actors[A]) == 30
    assert cold()._load_session(match['match_id']).engine.state.model_dump(mode='json') == loaded.engine.state.model_dump(mode='json')
    with pytest.raises(ValueError, match='Finish'):
        cold().journey_resume(jid, state['revision'])
    from combat.tabletop_service import TabletopService
    from tests.auto8f1_table_support import candidate_id
    for _ in range(6):
        fresh = cold()
        if fresh._load_session(match['match_id']).engine.state.terminal_result is not None:
            break
        table = TabletopService(fresh, fresh.userdata_root)
        menu = table.state(match['match_id'])['menu']
        if menu['actor_id'] == A and fresh._load_session(match['match_id']).engine.state.actors[A].resources[FOCUS] == 0:
            table.act(match['match_id'], candidate_id(menu, 'Dash'), menu['decision_id'], menu['state_version'], 0)
            menu = table.state(match['match_id'])['menu']
        table.act(match['match_id'], menu['end_turn'], menu['decision_id'], menu['state_version'], 0)
    state = cold().journey_resume(jid, state['revision'])
    assert owner(state)['resources'][FOCUS] == 1
    state = act('long_rest')
    state = activate(act)
    assert owner(state)['resources'][FOCUS] == 0 and owner(state)['travel_uses'][SOURCE] == 1


def test_normal_pace_is_exactly_tenfold_without_step_rounding(tmp_path, monkeypatch):
    from fractions import Fraction
    clocks = []
    for owns in (False, True):
        cold, jid, act = game(tmp_path / str(owns), monkeypatch, owner=owns, pace=15840)
        if owns: activate(act)
        state = act('move', {'path': [{'x': 1, 'y': 1}]})
        clocks.append(Fraction(state['seconds']) + Fraction(state['subsecond_num'], state['subsecond_den']))
        if owns:
            assert all(type(v) is int for v in owner(state)['travel_effects'][SOURCE].values())
    assert clocks[0] == clocks[1] * 10


def test_carry_size_limit_and_exactly_one_companion(tmp_path, monkeypatch):
    from tests.h1_support import sheet
    game(tmp_path / 'authority', monkeypatch)
    third = 'actor:factory.third'
    def sheets(self, pid):
        value = sheet([SOURCE] if pid == 'traveller' else [], cl=15, name=pid)
        if pid == 'companion': value['identity']['size'] = 'Large'
        return value
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', sheets)
    service = CombatService(ROOT, tmp_path / 'party')
    state = service.create_journey(project_ids=['traveller', 'companion', 'third'], arena_id='scene',
              positions={A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}, third: {'x': 1, 'y': 2}},
              base_paces={A: 5, B: 5, third: 5})
    jid = state['journey_id']
    def act(kind, payload, aid=A):
        fresh = CombatService(ROOT, service.userdata_root)
        state = fresh.journey_state(jid)
        after = fresh.journey_act(jid, state['revision'], aid, kind, payload)
        assert CombatService(ROOT, service.userdata_root).journey_state(jid) == after
        return after
    activate(act)
    with pytest.raises(ValueError): act('request_carry', {'target_id': B})
    act('request_carry', {'target_id': third})
    state = act('carry_reply', {'accept': True}, third)
    assert state['actors'][third]['carried_by'] == A
    with pytest.raises(ValueError): act('request_carry', {'target_id': B})


def test_fractional_activation_deadline_is_a_full_hour(tmp_path, monkeypatch):
    from fractions import Fraction
    cold, jid, act = game(tmp_path, monkeypatch, pace=15840)
    before = act('move', {'path': [{'x': 1, 'y': 1}]})
    started = Fraction(before['seconds']) + Fraction(before['subsecond_num'], before['subsecond_den'])
    state = activate(act)
    effect = owner(state)['travel_effects'][SOURCE]
    assert Fraction(effect['expiry_num'], effect['expiry_den']) == started + 3600
    assert SOURCE in owner(act('wait', {'seconds': 60}))['travel_effects']
    assert SOURCE not in owner(act('wait', {'seconds': 1}))['travel_effects']


def test_combat_binding_preserves_sourced_incapacitation_and_exhaustion(tmp_path, monkeypatch):
    from combat.ext.forged_exhaustion import level
    arena = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    cold, jid, act = game(tmp_path, monkeypatch, battlefield=arena)
    activate(act)
    act('travel_exhaustion', {'levels': 1, 'ordinary': False})
    state = act('incapacitated', {'value': True})
    match = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'},
                                       positions={A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}})
    actor = cold()._load_session(match['match_id']).engine.state.actors[A]
    assert any(c.condition_id == 'incapacitated' for c in actor.conditions.values())
    assert level(actor) == 1
    assert cold()._load_session(match['match_id']).engine.state.actors[A].model_dump(mode='json') == actor.model_dump(mode='json')


def test_api_create_menu_commit_and_get(tmp_path, monkeypatch):
    from app.api import create_app
    from app.core import Settings
    game(tmp_path / 'authority', monkeypatch)
    app = create_app(Settings.from_env(ROOT, tmp_path / 'api'))
    app.state.agent_seats.background = False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            token = (await client.get('/api/session')).json()['token']
            headers = {'x-foundry-token': token}
            reply = await client.post('/api/combat/journeys', headers=headers,
                    json={'project_ids': ['traveller', 'companion'], 'arena_id': 'scene',
                          'positions': {A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}}, 'base_paces': {A: 5, B: 5}})
            assert reply.status_code == 200, reply.text
            jid = reply.json()['journey_id']
            menu = (await client.get(f'/api/combat/journeys/{jid}/menu/{A}')).json()
            assert any(o['source'] == SOURCE for o in menu['options'] if o['kind'] == 'activate')
            committed = await client.post(f'/api/combat/journeys/{jid}/act', headers=headers,
                    json={'revision': 0, 'actor_id': A, 'kind': 'activate', 'payload': {'source': SOURCE}})
            assert committed.status_code == 200, committed.text
            assert (await client.get(f'/api/combat/journeys/{jid}')).json() == committed.json()
            invalid = await client.post(f'/api/combat/journeys/{jid}/act', headers=headers,
                    json={'revision': 0, 'actor_id': A, 'kind': 'activate', 'payload': {'source': SOURCE}})
            assert invalid.status_code == 400
    asyncio.run(exercise())
