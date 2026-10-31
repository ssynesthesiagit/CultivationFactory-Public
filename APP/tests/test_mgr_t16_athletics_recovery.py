"""ATH5RBF1: travel flags cannot undo persisted encounter incapacitation."""
import pytest

from tests.test_mgr_t16_athletics_continuation import party, seed, condition, finish, SPOTS
from tests.test_mgr_t16_athletics_strict_journey import disk_files
from tests.test_mgr_t16_athletics_travel import game, A, B


@pytest.mark.parametrize('hp,life,cid', [
    (0, 'STABLE', 'unconscious'),
    (20, 'CONSCIOUS', 'stunned'),
], ids=['zero-hp-survivor', 'permanent-incapacitation'])
def test_f1_cannot_clear_encounter_incapacitation_after_cold_resume(tmp_path, monkeypatch, hp, life, cid):
    cold, jid, act = party(tmp_path, monkeypatch)
    seed(cold, jid, B, hp=hp, life=life, conditions={
        'persistent': condition(B, 'persistent', cid)})
    first = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'},
                                        maximum_rounds=1, positions=SPOTS)['match_id']
    finish(cold, first)
    terminal = cold()._load_session(first).engine.state.model_dump(mode='json')
    bound = cold().journey_state(jid)
    resumed = cold().journey_resume(jid, bound['revision'])
    assert resumed['actors'][B]['incapacitated'] == 1
    before = cold().journey_state(jid)
    disk = disk_files(tmp_path)
    with pytest.raises(ValueError, match='saved encounter'):
        act('incapacitated', {'value': False}, B)
    assert cold().journey_state(jid) == before
    assert disk_files(tmp_path) == disk
    with pytest.raises(ValueError, match='cannot travel'):
        act('move', {'path': [{'x': 9, 'y': 6}]}, B)
    assert cold().journey_state(jid) == before
    assert not any(o['kind'] == 'move' for o in cold().journey_menu(jid, B)['options'])
    # The healthy party member keeps every adjacent legal travel option.
    assert any(o['kind'] == 'move' for o in cold().journey_menu(jid, A)['options'])
    second = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                         positions=SPOTS)['match_id']
    survivor = cold()._load_session(second).engine.state.actors[B]
    assert survivor.current_hp == hp and survivor.life_state == life
    assert survivor.conditions['persistent'].condition_id == cid
    assert survivor.conditions['persistent'].expires_on == 'UNTIL_REMOVED'
    assert cold()._load_session(first).engine.state.model_dump(mode='json') == terminal


@pytest.mark.parametrize('with_snapshot', [False, True], ids=['new-journey', 'healthy-survivor'])
def test_independent_travel_incapacitation_can_still_be_cleared(tmp_path, monkeypatch, with_snapshot):
    if with_snapshot:
        cold, jid, act = party(tmp_path, monkeypatch)
        seed(cold, jid, B, conditions={'injury': condition(B, 'injury', 'prone')})
        first = cold().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'},
                                            maximum_rounds=1, positions=SPOTS)['match_id']
        finish(cold, first)
        bound = cold().journey_state(jid)
        cold().journey_resume(jid, bound['revision'])
    else:
        cold, jid, act = game(tmp_path, monkeypatch)
    before = cold().journey_state(jid)['actors'][B].get('encounter_snapshot')
    act('incapacitated', {'value': True}, B)
    cleared = act('incapacitated', {'value': False}, B)
    assert cleared['actors'][B]['incapacitated'] == 0
    assert cleared['actors'][B].get('encounter_snapshot') == before
    assert any(o['kind'] == 'move' for o in cold().journey_menu(jid, B)['options'])
