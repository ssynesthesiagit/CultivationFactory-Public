"""Assigned travel clauses through CombatService and fresh disk sessions.

No browser or model servers. The scene and sheets are deterministic authority
fixtures, while compilation, menu admission, payment and persistence are real.
"""
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.ext.athletics_travel import SOURCE, FOCUS
from tests.h1_support import ROOT, sheet

A = FACTORY_ACTOR_PREFIX + 'traveller'
B = FACTORY_ACTOR_PREFIX + 'companion'


def scene():
    return {'stable_id': 'journey:test', 'width_squares': 20, 'height_squares': 5,
            'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}


def game(tmp_path, monkeypatch, *, owner=True, companion_owner=False, pace=5, mode='MANUAL', battlefield=None, positions=None):
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
                        sheet([SOURCE] if owner and (pid == 'traveller' or companion_owner) else [], cl=15, name=pid))
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': battlefield or scene()})
    service = CombatService(ROOT, tmp_path)
    state = service.create_journey(project_ids=['traveller', 'companion'], arena_id='scene',
                                   positions=positions or {A: {'x': 0, 'y': 1}, B: {'x': 0, 'y': 2}},
                                   base_paces={A: pace, B: pace}, control_modes={A: mode})
    jid = state['journey_id']

    def cold():
        return CombatService(ROOT, tmp_path)

    def act(kind, payload=None, aid=A):
        fresh = cold()
        before = fresh.journey_state(jid)
        after = fresh.journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == after
        return after

    return cold, jid, act


def activate(act):
    return act('activate', {'source': SOURCE})


def owner(state):
    return state['actors'][A]


@pytest.mark.parametrize('row', ['action', 'hour-clock', 'focus-cost', 'long-rest-recharge',
                                 'enter-travel', 'pace-tenfold', 'ordinary-travel-exhaustion',
                                 'end-enter-combat', 'end-incapacitated', 'end-stop-minute'])
def test_state_rows_service_cold_reload(tmp_path, monkeypatch, row):
    cold, jid, act = game(tmp_path, monkeypatch)
    state = activate(act)
    assert SOURCE in owner(state)['travel_effects']
    if row == 'action':
        event = state['events'][-1]
        assert event['economy'] == 'ACTION' and event['source'] == SOURCE
        assert 'Action' in event['text'] and 'Martial Focus' in event['text']
    elif row == 'hour-clock':
        assert owner(state)['travel_effects'][SOURCE]['expires_at'] == 3600
        path = [{'x': x, 'y': 1} for x in range(1, 10)]
        state = act('move', {'path': path})
        assert state['seconds'] == 3240 and SOURCE in owner(state)['travel_effects']
        state = act('move', {'path': [{'x': 10, 'y': 1}]})
        assert state['seconds'] == 3600 and SOURCE not in owner(state)['travel_effects']
        assert 'one hour' in state['events'][-2]['text']
    elif row == 'focus-cost':
        assert owner(state)['resources'][FOCUS] == 0
        with pytest.raises(ValueError):
            activate(act)
        assert cold().journey_state(jid) == state
    elif row == 'long-rest-recharge':
        state = act('long_rest')
        assert state['seconds'] == 28800
        assert owner(state)['long_rests'] == 1
        assert owner(state)['travel_uses'][SOURCE] == 0
        # The Long Rest use has recharged; focus still needs its own recovery.
        assert owner(state)['travel_uses'][SOURCE] != owner(state)['long_rests']
    elif row == 'enter-travel':
        assert cold().journey_menu(jid, A)['properties']['pace_multiplier'] == 10
        assert not cold().journey_menu(jid, B)['properties']
    elif row == 'pace-tenfold':
        state = act('move', {'path': [{'x': 1, 'y': 1}]})
        assert state['seconds'] == 360  # 5 feet at 50 feet/hour.
        assert owner(state)['position'] == {'x': 1, 'y': 1}
    elif row == 'ordinary-travel-exhaustion':
        state = act('travel_exhaustion', {'levels': 1, 'ordinary': True})
        assert owner(state)['exhaustion'] == 0
        state = act('travel_exhaustion', {'levels': 1, 'ordinary': False})
        assert owner(state)['exhaustion'] == 1
        state = act('travel_exhaustion', {'levels': 1, 'ordinary': True}, B)
        assert state['actors'][B]['exhaustion'] == 1
    elif row == 'end-enter-combat':
        state = act('enter_combat')
        assert state['phase'] == 'combat' and SOURCE not in owner(state)['travel_effects']
        with pytest.raises(ValueError):
            act('move', {'path': [{'x': 1, 'y': 1}]})
    elif row == 'end-incapacitated':
        state = act('incapacitated', {'value': True})
        assert SOURCE not in owner(state)['travel_effects']
        with pytest.raises(ValueError):
            act('move', {'path': [{'x': 1, 'y': 1}]})
    else:
        state = act('wait', {'seconds': 60})
        assert SOURCE in owner(state)['travel_effects']
        state = act('wait', {'seconds': 1})
        assert SOURCE not in owner(state)['travel_effects']


def test_no_owner_no_offer_or_payment_and_stale_revision(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, owner=False)
    before = cold().journey_state(jid)
    menu = cold().journey_menu(jid, A)
    # Basic mapped Actions are available without this travel talent. Their
    # presence must not grant Body Beyond Distance's owned activation.
    assert all(row['kind'] in ('move', 'map_action_declare') for row in menu['options'])
    assert all(row['payload']['source'] in ('system:combat.dash', 'system:combat.disengage')
               for row in menu['options'] if row['kind'] == 'map_action_declare')
    assert menu['properties'] == {}
    with pytest.raises(ValueError):
        activate(act)
    assert cold().journey_state(jid) == before
    act('wait', {'seconds': 1})
    with pytest.raises(ValueError, match='refresh'):
        cold().journey_act(jid, 0, A, 'wait', {'seconds': 1})


def test_stop_clock_resets_on_real_map_movement(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, pace=1800)
    activate(act)
    act('wait', {'seconds': 60})
    act('move', {'path': [{'x': 1, 'y': 1}]})
    state = act('wait', {'seconds': 60})
    assert SOURCE in owner(state)['travel_effects']
    state = act('wait', {'seconds': 1})
    assert SOURCE not in owner(state)['travel_effects']


def test_hour_boundary_prices_remaining_route_at_ordinary_pace(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    activate(act)
    act('move', {'path': [{'x': x, 'y': 1} for x in range(1, 10)]})
    act('wait', {'seconds': 60})
    # 300 seconds of the final square are boosted, the remaining 5/6 foot
    # takes 600 seconds at the ordinary five-feet-per-hour scene pace.
    state = act('move', {'path': [{'x': 10, 'y': 1}]})
    assert state['seconds'] == 4200
    assert SOURCE not in owner(state)['travel_effects']


def test_new_journey_cannot_reset_focus_or_long_rest_use(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    activate(act)
    with pytest.raises(ValueError, match='already in'):
        cold().create_journey(project_ids=['traveller'], arena_id='scene',
                              positions={A: {'x': 1, 'y': 1}}, base_paces={A: 5})
    act('enter_combat')
    with pytest.raises(ValueError, match='already in'):
        cold().create_journey(project_ids=['traveller'], arena_id='scene',
                              positions={A: {'x': 1, 'y': 1}}, base_paces={A: 5})
    act('finish')  # Explicitly release this unbound journey, retaining balances.
    fresh = cold().create_journey(project_ids=['traveller'], arena_id='scene',
                                  positions={A: {'x': 1, 'y': 1}}, base_paces={A: 5})
    assert owner(fresh)['resources'][FOCUS] == 0
    assert owner(fresh)['travel_uses'][SOURCE] == 0
