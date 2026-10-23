"""Printed recovery cadence through native journey intents and cold replay."""
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH, RECOVERY = BASE + 'kindled_hearth', BASE + 'homefire_recovery'
A, B = (FACTORY_ACTOR_PREFIX + n for n in ('hearthkeeper', 'guest'))


def game(tmp_path, monkeypatch, *, owned=True):
    def document(self, pid):
        doc = sheet([], cl=18, name=pid)
        doc['identity']['proficiency_bonus'] = 6
        doc['path_and_subpath'] = {'path_feature_record_ids': [HEARTH, RECOVERY] if owned and pid == 'hearthkeeper' else []}
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        return doc
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', document)
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self: {'scene': {
        'stable_id': 'journey:hearth', 'width_squares': 20, 'height_squares': 5,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}})
    def cold():
        return CombatService(ROOT, tmp_path)
    initial = cold().create_journey(project_ids=['hearthkeeper', 'guest'], arena_id='scene',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 2, 'y': 1}}, base_paces={A: 18000, B: 18000})
    jid = initial['journey_id']
    def act(kind, payload=None, aid=A):
        old = cold().journey_state(jid)
        state = cold().journey_act(jid, old['revision'], aid, kind, payload)
        assert cold().journey_state(jid) == state
        assert cold().journey_replay(jid)['status'] == 'PASS'
        return state
    return cold, jid, act


def kindle(act):
    return act('hearth_kindle', {'position': {'x': 1, 'y': 2}, 'recipients': [A, B]})


def recover(act, benefit='exhaustion'):
    return act('hearth_short_rest', {'owner_id': A, 'benefit': benefit}, B)


def test_travel_exhaustion_recovery_consumes_current_levels_not_historical_exposure(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    act('travel_exhaustion', {'levels': 2, 'ordinary': True}, B)
    kindle(act)
    first = recover(act)
    assert first['actors'][B]['exhaustion'] == 1
    assert first['seconds'] == 3606
    # A second pulse is unavailable, including after leaving and reentering.
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='long rest'):
        recover(act)
    assert cold().journey_state(jid) == before
    act('long_rest', aid=B)
    kindle(act)
    assert recover(act)['actors'][B]['exhaustion'] == 0
    act('long_rest', aid=B)
    kindle(act)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='Exhaustion'):
        recover(act)
    assert cold().journey_state(jid) == before
    # A new exposure, unlike old receipts, is recoverable.
    act('travel_exhaustion', {'levels': 1, 'ordinary': True}, B)
    assert recover(act)['actors'][B]['exhaustion'] == 0


def test_recovery_recipient_chooses_and_cadence_survives_new_journey(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    kindle(act)
    state = recover(act, 'temp_hp')
    assert state['actors'][B]['encounter_snapshot']['temporary_hp'] == 12
    act('finish')
    fresh = cold().create_journey(project_ids=['hearthkeeper', 'guest'], arena_id='scene',
        positions={A: {'x': 1, 'y': 1}, B: {'x': 2, 'y': 1}}, base_paces={A: 18000, B: 18000})
    jid2 = fresh['journey_id']
    cold().journey_act(jid2, 0, A, 'hearth_kindle', {'position': {'x': 1, 'y': 2}, 'recipients': [B]})
    with pytest.raises(ValueError, match='long rest'):
        cold().journey_act(jid2, 1, B, 'hearth_short_rest', {'owner_id': A, 'benefit': 'temp_hp'})


def test_short_rest_outside_or_after_hearth_expiry_rolls_back(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch)
    kindle(act)
    act('move', {'path': [{'x': x, 'y': 1} for x in range(3, 8)]}, B)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='inside'):
        recover(act, 'temp_hp')
    assert cold().journey_state(jid) == before
    act('move', {'path': [{'x': x, 'y': 1} for x in range(6, 1, -1)]}, B)
    act('wait', {'seconds': 26000})
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='expired'):
        recover(act, 'temp_hp')
    assert cold().journey_state(jid) == before


def test_wrong_owner_cannot_grant_recovery(tmp_path, monkeypatch):
    cold, jid, act = game(tmp_path, monkeypatch, owned=False)
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        kindle(act)
    assert cold().journey_state(jid) == before
    assert not any(o['kind'].startswith('hearth_') for o in cold().journey_menu(jid, A)['options'])
