"""Whole Merit Dice row: real sheet compilation, table spending and cold journeys."""
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.ext.sect_stewardship import MERIT, MERIT_SIZE, merit_maximum
from combat.ext.sect_merit_rest import COMMAND, SOURCE, INSTITUTION_TASKS, TRAVEL_TASKS
from tests.h1_support import ROOT, sheet
from tests.hunt12_support import send, candidate
from tests.test_lock2_persistence import act as table_act
from tests.test_mgr_t16_athletics_continuation import finish

A, B = (FACTORY_ACTOR_PREFIX + name for name in ('steward', 'outsider'))
SPOTS = {A: {'x': 3, 'y': 6}, B: {'x': 8, 'y': 6}}


def game(tmp_path, monkeypatch, *, mode='MANUAL', pb=4):
    def document(self, pid):
        doc = sheet([SOURCE] if pid == 'steward' else [], cl=15, name=pid)
        doc['identity']['proficiency_bonus'] = pb
        return doc
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', document)
    def cold():
        return CombatService(ROOT, tmp_path)
    arena = cold().factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kwargs: {'merit_scene': arena})
    state = cold().create_journey(project_ids=['steward', 'outsider'],
        arena_id='merit_scene', positions=SPOTS,
        base_paces={A: 5, B: 5}, control_modes={A: mode, B: 'MANUAL'})
    jid = state['journey_id']
    def act(kind, payload=None, aid=A):
        before = cold().journey_state(jid)
        after = cold().journey_act(jid, before['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == after
        return after
    return cold, jid, act


def spent_journey(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    state = cold().journey_state(jid)
    assert state['actors'][A]['resources'][MERIT] == 4
    assert state['actors'][A]['resources'][MERIT_SIZE] == 4
    assert MERIT not in state['actors'][B]['resources']
    result = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=2)
    mid = result['match_id']
    # Spend through native paid checks, never seed a depleted resource receipt.
    for _ in range(2):
        service = cold()
        table = TabletopService(service, tmp_path)
        while table.state(mid)['menu']['actor_id'] != A:
            assert table_act(table, mid, 'end')['status'] == 'COMMITTED'
        choices = [c for c in service._load_session(mid).engine.legal_candidates()
                   if c.display_name == 'Sect Stewardship: choose Intelligence']
        if choices:
            assert send(service, table, mid, choices[0])['status'] == 'COMMITTED'
        chosen = candidate(service, mid, lambda c: c.display_name == 'Sect Check (spend 1 Merit Die)')
        assert send(service, table, mid, chosen)['status'] == 'COMMITTED'
        assert table_act(table, mid, 'end')['status'] == 'COMMITTED'
    finish(cold, mid)
    loaded = cold()._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[A].resources[MERIT] == 2
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    assert resumed['actors'][A]['resources'][MERIT] == 2
    assert cold().journey_state(jid) == resumed
    return cold, jid, act


@pytest.mark.parametrize('mode,expected,seconds', [('institution', 4, 29400), ('away', 3, 28800)])
def test_native_spend_rest_recover_and_reenter_combat(tmp_path, monkeypatch, mode, expected, seconds):
    cold, jid, act = spent_journey(tmp_path, monkeypatch)
    # An ordinary rest has no institutional facts and must leave the spent dice alone.
    before = act('long_rest')
    assert before['actors'][A]['resources'][MERIT] == 2
    options = cold().journey_menu(jid, A)['options']
    option = next(o for o in options if o['id'] == f'{COMMAND}:{mode}:0')
    after = act(option['kind'], option['payload'])
    assert after['seconds'] - before['seconds'] == seconds
    assert after['actors'][A]['resources'][MERIT] == expected
    assert after['actors'][A]['long_rests'] == before['actors'][A]['long_rests'] + 1
    receipt = after['events'][-1]
    assert receipt['kind'] == 'MERIT_DICE_RECOVERED'
    assert receipt['owner_confirmed'] == 1 and receipt['recovered'] == expected - 2
    assert after['actors'][B]['resources'] == before['actors'][B]['resources']
    result = cold().journey_start_combat(jid, after['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1)
    loaded = cold()._load_session(result['match_id'])
    assert loaded.engine.state.actors[A].resources[MERIT] == expected
    assert loaded.engine.state.actors[A].resources[MERIT_SIZE] == 4
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_menu_complete_confirmations_and_wrong_owner_boundaries(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    options = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == COMMAND]
    assert {o['payload']['activity'] for o in options} == set(INSTITUTION_TASKS + TRAVEL_TASKS)
    assert all(o['auto_select'] == 0 and 'Merit Dice' in o['label']
               and 'eight-hour Long Rest' in o['label'] and 'Confirm only facts' in o['label'] for o in options)
    assert not [o for o in cold().journey_menu(jid, B)['options'] if o['kind'] == COMMAND]
    payload = options[0]['payload']
    before = cold().journey_state(jid)
    for bad in ({**payload, 'minutes': 9}, {**payload, 'confirmed': 0},
                {**payload, 'confirmed': True}, {**payload, 'minutes': -1},
                {**payload, 'mode': 'unknown'}, {**payload, 'activity': 'buy office'},
                {**payload, 'target': B}):
        with pytest.raises(ValueError):
            act(COMMAND, bad)
        assert cold().journey_state(jid) == before
    with pytest.raises(ValueError, match='Only a character'):
        act(COMMAND, payload, B)
    assert cold().journey_state(jid) == before
    # At maximum, recovery never creates dice above PB or any conversion reward.
    for option in options:
        state = act(COMMAND, option['payload'])
        assert state['actors'][A]['resources'] == before['actors'][A]['resources']
        assert state['events'][-1]['recovered'] == 0
    act('incapacitated', {'value': True})
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='incapacitated'):
        act(COMMAND, payload)
    assert cold().journey_state(jid) == before


def test_automatic_actor_does_not_invent_institutional_facts(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, mode='LOCAL_AUTO')
    state = cold().journey_state(jid)
    after = cold().journey_auto_step(jid, state['revision'], A)
    assert not any(e['kind'] == 'MERIT_DICE_RECOVERED' for e in after['events'])
    assert after['actors'][A]['long_rests'] == 0
    # An explicit owner selection remains reachable even for an automatic seat.
    option = next(o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == COMMAND)
    state = cold().journey_auto_step(jid, after['revision'], A, option['id'])
    assert state['events'][-1]['owner_confirmed'] == 1
    assert cold().journey_state(jid) == state


@pytest.mark.parametrize('pb', [0, -1, 1, 4])
def test_printed_minimum_pool(tmp_path, monkeypatch, pb):
    assert merit_maximum({'pb': pb}) == max(1, pb)
    assert merit_maximum({}) == merit_maximum({'pb': None}) == 2
    # Zero/negative PB are helper boundary controls; native character PB is positive.
    if pb <= 0:
        return
    cold, jid, _ = game(tmp_path, monkeypatch, pb=pb)
    actor = cold().journey_state(jid)['actors'][A]
    assert actor['resources'][MERIT] == max(1, pb)
    pool = next(r for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == MERIT)
    assert pool['maximum'] == max(1, pb)
