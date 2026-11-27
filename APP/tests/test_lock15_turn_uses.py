"""Usage clocks through real attacks, free counterattacks, OAs and Table reloads."""
import copy
import pytest
from combat import typed_reactions as tr
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT, ALLY, ROOT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install


def attacks(monkeypatch):
    def compile_action(info):
        owner=info['actor_id']
        return [ActionDefinition(source_definition_id='test:practice:'+owner, display_name='Practice blade',owner_id=owner,
            economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='ANY_CREATURE',range_ft=5,
            parameters={'expected_damage':100,'typed':{'numbers':{**info['numbers'],'attack_bonus':100},
                'weapon':{'damage':{'count':1,'sides':2},'fixed_damage':1,'damage_type':'FORCE'},
                'effects':[{'type':'attack','attack_kind':'weapon_melee','count':2,'on_hit':[
                    {'type':'damage','flat':1,'damage_types':['force']},
                    {'type':'damage','flat':2,'damage_types':['cold'],'once_per_turn':'test:extra'},
                    {'type':'damage','flat':3,'damage_types':['fire'],'modifier_once':'test:owner',
                     'modifier_once_period':'owner_turn'}]}]}})]
    install(monkeypatch,'compile_actions',compile_action)
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:fixed-roll','operation':'replace','natural_result':10})


def strike(combat,table,mid,actor,target):
    state=table.state(mid);engine=combat._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.source_definition_id=='test:practice:'+actor and target in c.target_ids)
    reply=table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'])
    assert reply['status']=='COMMITTED',reply


def loaded(combat,tmp_path,mid):
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    assert fresh.engine.state==combat._load_session(mid).engine.state
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'
    return fresh.engine


@pytest.mark.parametrize('period',['turn','round'])
@pytest.mark.parametrize('used_on_owner_turn',[True,False])
def test_actual_free_counterattack_clock_and_owner_only_rider(monkeypatch,tmp_path,period,used_on_owner_turn):
    attacks(monkeypatch)
    original=tr._rows
    def rows(e,who,block):
        found=list(original(e,who,block))
        if who==LEFT and block=='generic':
            found.append({'feature_id':'test:counter','name':'Practice counterattack','block':'generic',
                'kind':'attacked','free':True,'once':period,'subject_relation':'any','range_ft':5,
                'effects':[{'type':'attack','attack_kind':'weapon_melee','count':2,'on_hit':[
                    {'type':'damage','flat':1,'damage_types':['force']},
                    {'type':'damage','flat':2,'damage_types':['cold'],'once_per_turn':'test:extra'},
                    {'type':'damage','flat':3,'damage_types':['fire'],'modifier_once':'test:owner','modifier_once_period':'owner_turn'}]}],
                'numbers':{'attack_bonus':100,'pb':4}})
        return found
    monkeypatch.setattr(tr,'_rows',rows)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    if used_on_owner_turn:
        strike(combat,table,mid,LEFT,RIGHT)
    e=loaded(combat,tmp_path,mid)
    own=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT]
    assert sum(v.payload['damage_type']=='COLD' for v in own)==int(used_on_owner_turn)
    assert sum(v.payload['damage_type']=='FIRE' for v in own)==int(used_on_owner_turn)
    round_before=e.state.round_number
    responses=[]
    for _ in range(2):
        assert act(table,mid,'end')['status']=='COMMITTED'
        who=table.state(mid)['menu']['actor_id'];assert who!=LEFT
        before=len(combat._load_session(mid).engine.events)
        strike(combat,table,mid,who,LEFT)
        e=loaded(combat,tmp_path,mid)
        assert e.state.round_number==round_before
        events=e.events[before:]
        hits=[v for v in events if v.event_type=='ATTACK_ROLLED' and v.source_definition_id=='test:counter']
        responses.append(len(hits))
        damage=[v for v in events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT]
        assert not any(v.payload['damage_type']=='FIRE' for v in damage)
        assert sum(v.payload['damage_type']=='COLD' for v in damage)==bool(hits)
    assert responses==([2,2] if period=='turn' else [2,0])


@pytest.mark.parametrize('used_on_owner_turn',[True,False])
def test_actual_opportunity_attack_reopens_extra_damage_after_owner_turn(monkeypatch,tmp_path,used_on_owner_turn):
    attacks(monkeypatch)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[],ask=True)
    if used_on_owner_turn:
        strike(combat,table,mid,LEFT,RIGHT)
    while table.state(mid)['menu']['actor_id']!=RIGHT:assert act(table,mid,'end')['status']=='COMMITTED'
    state=table.state(mid);engine=combat._load_session(mid).engine;before=len(engine.events)
    c=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.x==5 and c.destination.y==4)
    response=table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'])
    assert response['status']=='REACTION_REQUIRED'
    answers=[{**response['reaction']['context'],'selection':'USE'}]
    response=table.act(mid,c.candidate_id,c.decision_id,c.state_version,state['last_sequence'],answers)
    assert response['status']=='COMMITTED',response
    e=loaded(combat,tmp_path,mid)
    hits=[v for v in e.events[before:] if v.event_type=='ATTACK_ROLLED' and v.actor_id==LEFT]
    assert len(hits)==1 and hits[0].source_definition_id.endswith('.opportunity_attack')
    damage=[v for v in e.events[before:] if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==LEFT]
    assert sum(v.payload['damage_type']=='COLD' for v in damage)==1
    assert not any(v.payload['damage_type']=='FIRE' for v in damage)


def test_printed_owner_qualification_and_shared_table_refresh_text(monkeypatch,tmp_path):
    from combat.turn_uses import modifier_period, usage_explanations
    import json
    authority=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    for key in ('METAL_BASE_SHARPEN','METAL_BASE_WEIGHT'):
        row=authority['mechanics'][key]
        # These Metal abilities now use the reviewed expression menu rather
        # than a modifier row; their printed owner-turn qualification remains.
        assert modifier_period(row, {'limit': 'once_per_turn'})=='owner_turn'
    assert modifier_period({'activation':{'trigger':'Once per turn when you hit'}},{'limit':'once_per_turn'})=='turn'
    assert 'next round' in usage_explanations({'once':'round'})
    attacks(monkeypatch)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    group=next(g for g in table.state(mid)['menu']['actions'] if g['source_definition_id']=='test:practice:'+LEFT)
    assert "next creature's turn" in group['description']
    assert 'your turn only' in group['description']
    assert 'roll 1d20' in group['description']
    assert 'Cold damage bonus' in group['description'] and 'Fire damage bonus' in group['description']
    assert 'underlying action keeps its normal action and reaction rules' in group['description']


def test_named_riders_preserve_original_weapon_and_explicit_descriptions():
    from combat.tabletop import engine_button_description,auto_buttons
    row={'source_definition_id':'action:typed.weapon.blade','display_name':'Training blade',
         'owner_id':LEFT,'economy':'ACTION','target_kind':'HOSTILE_ENTITY','range_ft':5,
         'parameters':{'typed':{'numbers':{'attack_bonus':4},'effects':[{'type':'attack','count':2,'on_hit':[
             {'type':'damage','flat':1,'source_modifier':'METAL_BASE_SHARPEN','modifier_once_period':'owner_turn'},
             {'type':'damage','flat':1,'name':'Frost','once_per_turn':'test:frost'},
             {'type':'damage','flat':1,'name':'Ember','once':'round'}]}]}}}
    text=engine_button_description(row)
    assert 'roll 1d20+4' in text and '2 attacks per Action' in text
    assert 'Sharpen bonus: Once on your turn only' in text
    assert 'Frost bonus: Once per turn' in text and 'Ember bonus: Once per round' in text
    button=auto_buttons({'action_catalog':[row]}, {})[0]
    assert text in button['description']
    row['parameters']['description']='Strike one creature within 5 feet with your blade.'
    assert engine_button_description(row).startswith(row['parameters']['description'])
