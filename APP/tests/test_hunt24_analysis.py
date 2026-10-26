"""Rapid Analysis must use the actual table creation/setup transaction."""
import pytest
from combat.gate5_service import CombatService
from combat.fight_setup import SOURCE
from tests.h1_support import ROOT
from tests.hunt24_support import table_fight, A, D, F
from tests.hunt23_support import action_sender
from tests.test_lock2_persistence import act

RAPID = 'TAL_THE_HIDDEN_EYE_RAPID_ANALYSIS'
BASE = 'TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES'


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('selection', ['USE', 'DECLINE', 'AUTO'])
def test_initiative_choice_before_any_turn_commits_and_reloads(tmp_path, ai_turn, selection):
    svc, table, mid = table_fight(tmp_path, [BASE, RAPID], foes=2)
    saved = svc._load_session(mid)
    assert [t.actor_id for t in saved.engine.state.setup_tasks] == [D]
    assert not any(e.event_type == 'TURN_STARTED' for e in saved.engine.events)
    before = saved.engine.state.model_dump(mode='json')
    if selection == 'AUTO':
        svc.set_controller_mode(mid, actor_id=D, controller_mode='LOCAL_AUTO')
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn)
    answers, prompts = [], []
    for _ in range(4):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']; prompts.append(prompt)
        assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
        assert prompt['context']['reactor_id'] == D
        if 'target' in prompt['reaction'].lower():
            assert {o['id'] for o in prompt['choice']['options']} == {A, F}
            assert 'Initiative' in prompt['trigger'] and 'no Action' in prompt['trigger']
            pick = F
        else:
            pick = 'Perception'
        answers.append({**prompt['context'], 'selection':'DECLINE' if selection == 'DECLINE' else 'USE',
                        'option_ids':[] if selection == 'DECLINE' else [pick]})
    assert result['status'] == 'COMMITTED'
    assert len(prompts) == (0 if selection == 'AUTO' else 1 if selection == 'DECLINE' else 2)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    checks = [e for e in loaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == D]
    assert len(checks) == (selection != 'DECLINE')
    if selection == 'USE':
        assert checks[0].target_ids == (F,)
        assert any('perception' in roll.reason for roll in loaded.engine.rolls if roll.actor_id == D)
    assert not loaded.engine.state.setup_tasks
    assert loaded.engine.state.actors[D].resources == before['actors'][D]['resources']
    assert all(a.action_available and a.reaction_available for a in loaded.engine.state.actors.values())
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    svc.set_controller_mode(mid, actor_id=loaded.engine.state.current_actor_id, controller_mode='MANUAL')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len([e for e in reloaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == D]) == len(checks)


def test_unowned_rapid_has_no_setup_or_new_events(tmp_path):
    svc, _, mid = table_fight(tmp_path)
    loaded = svc._load_session(mid)
    assert not loaded.engine.state.setup_tasks
    assert not any(e.source_definition_id == RAPID for e in loaded.engine.events)


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('ally_only', [False, True])
def test_player_initiative_can_choose_visible_ally_and_reload(tmp_path, ai_turn, ally_only):
    svc, table, mid = table_fight(tmp_path, [BASE, RAPID], foes=2, ally=True,
                                enemy_out_of_range=ally_only)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert {o['id'] for o in prompt['choice']['options']} == ({F} if ally_only else {A, F})
    assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
    answers = [{**prompt['context'], 'selection':'USE', 'option_ids':[F]}]
    result = send(answers)
    assert result['status'] == 'REACTION_REQUIRED'
    answers.append({**result['reaction']['context'], 'selection':'USE', 'option_ids':['Perception']})
    assert send(answers)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    checks = [e for e in loaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == D]
    assert len(checks) == 1 and checks[0].target_ids == (F,)
    assert not loaded.engine.state.setup_tasks
    assert loaded.engine.state.actors[D].resources == before['actors'][D]['resources']
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    svc.set_controller_mode(mid, actor_id=loaded.engine.state.current_actor_id, controller_mode='MANUAL')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len([e for e in reloaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == D]) == 1


@pytest.mark.parametrize('ally_only', [False, True])
def test_automatic_initiative_retains_enemy_preference(tmp_path, ally_only):
    svc, table, mid = table_fight(tmp_path, [BASE, RAPID], foes=2, ally=True,
                                enemy_out_of_range=ally_only)
    svc.set_controller_mode(mid, actor_id=D, controller_mode='LOCAL_AUTO')
    send = action_sender(svc, table, mid, SOURCE)
    assert send([])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    checks = [e for e in loaded.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == D]
    assert len(checks) == (0 if ally_only else 1)
    if checks:
        assert checks[0].target_ids == (A,)
    assert not loaded.engine.state.setup_tasks
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
