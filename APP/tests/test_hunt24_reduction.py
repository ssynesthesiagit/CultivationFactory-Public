"""One rolled hit's reduction budget covers every attached damage packet."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.hunt24_support import table_fight, A, D, F
from tests.hunt23_support import action_sender, turn

GUARD = 'tianxia.path.body_refining.feature.stamina_guard'
WARD = 'TAL_DEATH_BONE_WARD'
SOURCE = 'action:test.h24.mixed'


def attack_bundle(bundle, *, small=False, count=1, owner=A, same_type=False, standalone=False):
    if bundle['actor_id'] != owner:
        return
    action = next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED')
    bundle['action_catalog'].append({**action, 'source_definition_id':SOURCE, 'display_name':'Mixed strike',
        'target_kind':'HOSTILE_ENTITY', 'range_ft':5, 'economy':'ACTION', 'costs':[],
        'parameters':{'typed':{'numbers':{'cl':15, 'pb':4, 'attack_bonus':100, 'save_dc':100},
            'effects':[{'type':'attack', 'attack_kind':'unarmed', 'count':count, 'on_hit':[
                {'type':'damage', 'dice':{'count':1,'sides':2,'bonus':0 if small else 7}, 'damage_types':['bludgeoning']},
                *([] if small else [{'type':'damage', 'flat':7, 'damage_types':['force']}])]}],
            'duration':{'kind':'instant'}, 'riders':[]}}})
    typed = bundle['action_catalog'][-1]['parameters']['typed']
    if same_type:
        typed['effects'][0]['on_hit'][0]['damage_types'] = ['force']
    if standalone:
        typed['effects'].append({'type':'damage', 'flat':3, 'damage_types':['force']})
    bundle['actor_template']['action_ids'].append(SOURCE)


@pytest.mark.parametrize('feature', [GUARD, WARD])
@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('selection', ['USE', 'DECLINE', 'AUTO'])
@pytest.mark.parametrize('same_type', [False, True])
def test_mixed_attack_reduction_one_payment_after_reload(tmp_path, feature, ai_turn, selection, same_type):
    svc, table, mid = table_fight(tmp_path, [feature], primary='Stamina' if feature == GUARD else 'Qi',
        prepare=lambda b: attack_bundle(b, count=2, same_type=same_type, standalone=True))
    turn(table, mid, A)
    if selection == 'AUTO':
        svc.set_controller_mode(mid, actor_id=D, controller_mode='LOCAL_AUTO')
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn, target_id=D)
    answers, prompts = [], []
    for _ in range(6):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']; prompts.append(prompt)
        assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
        answers.append({**prompt['context'], 'selection':'DECLINE' if selection == 'DECLINE' else 'USE',
                        'option_ids':['4'] if feature == GUARD and selection == 'USE' else []})
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    packets = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == SOURCE]
    assert len(packets) == 5
    resolutions = [e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == feature]
    if selection == 'DECLINE':
        assert not resolutions
        assert sum(e.payload['hp_damage'] for e in packets) == sum(e.payload['rolled_or_pending_damage'] for e in packets)
    else:
        assert len(resolutions) == 1
        rolls = [r for r in loaded.engine.rolls if r.reason in (f'DAMAGE_SOAK:{feature}', f'REACTION:{feature}')]
        if not rolls:
            rolls = [r for r in loaded.engine.rolls if feature in r.reason]
        assert len(rolls) == 1
        reduction = rolls[0].total
        assert sum(e.payload['hp_damage'] for e in packets[:2]) == max(0, sum(e.payload['rolled_or_pending_damage'] for e in packets[:2]) - reduction)
        assert sum(e.payload['hp_damage'] for e in packets[2:]) == sum(e.payload['rolled_or_pending_damage'] for e in packets[2:])  # a separate attack and standalone damage get no surplus
        assert not loaded.engine.state.actors[D].reaction_available
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('feature', [WARD, 'tianxia.talent.chains.iron_link_guard'])
def test_reduction_protects_ally_with_one_shared_budget(tmp_path, ai_turn, feature):
    svc, table, mid = table_fight(tmp_path, [feature], foes=2, ally=True, prepare=attack_bundle)
    turn(table, mid, A)
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn, target_id=F)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == D
    assert send([{**prompt['context'], 'selection':'USE'}])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    packets = [e.payload for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and F in e.target_ids]
    roll = next(r for r in loaded.engine.rolls if feature in r.reason)
    assert len(packets) == 2
    assert sum(p['hp_damage'] for p in packets) == max(0, sum(p['rolled_or_pending_damage'] for p in packets) - roll.total)
    assert not loaded.engine.state.actors[D].reaction_available
    assert loaded.engine.state.actors[D].resources['resource:core.qi'] == 29
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('feature', [GUARD, WARD])
@pytest.mark.parametrize('ai_turn', [False, True])
def test_late_bonus_from_another_ability_uses_originating_hit(tmp_path, feature, ai_turn):
    bonus_source = 'action:test.h24.extra_damage'
    def prepare(bundle):
        attack_bundle(bundle, small=True)
        if bundle['actor_id'] == A:
            action = bundle['action_catalog'][-1]
            bundle['action_catalog'].append({**action, 'source_definition_id':bonus_source,
                'display_name':'Charge strike', 'economy':'NONE', 'target_kind':'SELF',
                'parameters':{'typed':{'numbers':{'cl':15,'pb':4}, 'effects':[
                    {'type':'extra_damage', 'flat':7, 'damage_types':['force'], 'deferred':True,
                     'evidence':'The next time you hit with an Unarmed Strike, deal an additional 7 force damage.'}],
                    'duration':{'kind':'minutes','amount':1}, 'riders':[]}}})
            bundle['actor_template']['action_ids'].append(bonus_source)
    svc, table, mid = table_fight(tmp_path, [feature], primary='Stamina' if feature == GUARD else 'Qi', prepare=prepare)
    turn(table, mid, A)
    assert action_sender(svc, table, mid, bonus_source)([])['status'] == 'COMMITTED'
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn, target_id=D)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert send([{**prompt['context'], 'selection':'USE', 'option_ids':['4'] if feature == GUARD else []}])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    packets = [e.payload for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and D in e.target_ids]
    assert len(packets) == 2
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == bonus_source for e in loaded.engine.events)
    roll = next(r for r in loaded.engine.rolls if feature in r.reason)
    assert sum(p['hp_damage'] for p in packets) == max(0, sum(p['rolled_or_pending_damage'] for p in packets) - roll.total)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('ai_turn', [False, True])
def test_guard_offers_spend_on_two_damage(tmp_path, ai_turn):
    svc, table, mid = table_fight(tmp_path, [GUARD], primary='Stamina', prepare=lambda b: attack_bundle(b, small=True))
    turn(table, mid, A)
    send = action_sender(svc, table, mid, SOURCE, ai=ai_turn, target_id=D)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert [o['id'] for o in prompt['choice']['options']] == ['1','2','3','4']
    assert send([{**prompt['context'], 'selection':'USE', 'option_ids':['1']}])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[D].resources['resource:core.stamina'] == 29
    assert loaded.mechanical.replay()['status'] == 'PASS'
