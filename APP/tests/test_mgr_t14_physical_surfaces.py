"""Acquired sphere bases through native table intents, cold state and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position
from tests.test_mgr_t14_stock_materials import game, A, B
from tests.h1_support import ROOT
FOUNDATION = 'EARTH_BASE_SET_FOUNDATION'
CLOD = 'EARTH_BASE_WEIGHT_SEEKING_CLOD'
GLASS = 'GLASS_BASE_TEMPER_GLASS_SURFACE'
PUPPET = 'PUPPETRY_BASE_THREAD_THE_OBJECT'
THREAD = 'THREAD_BASE_SPOOL_AND_STRAND'


def start(tmp_path, monkeypatch, features, *, cl=5, objects=None, body=False, facts=()):
    cold,jid,act,admit = game(tmp_path,monkeypatch,features=features,cl=cl,objects=objects,body=body)
    for kind,payload in facts: admit(kind,payload)
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=15)['match_id']
    table=TabletopService(cold(),tmp_path)
    turn(table,mid,A)
    return cold,mid,table


def turn(table,mid,aid):
    for _ in range(4):
        menu=table.state(mid)['menu']
        if menu['actor_id']==aid:return
        assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],0)['status']=='COMMITTED'
    raise AssertionError('Could not reach owner turn')


def choose(table,mid,candidate,picker=None):
    answers=[]
    for _ in range(12):
        r=table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,0,answers)
        if r['status']=='COMMITTED':return r
        assert r['status']=='REACTION_REQUIRED',r
        p=r['reaction']; options=p.get('choice',{}).get('options',[])
        ids=[o['id'] for o in options]
        selected=picker(p,ids) if picker else ids[:1]
        answers.append({**p['context'],'selection':'USE','option_ids':selected})
    raise AssertionError('Too many prompts')


def candidate(cold,mid,name):
    return next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name==name)


def checked(cold,mid):
    loaded=cold()._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


@pytest.mark.parametrize('cl,maximum',[(1,2),(4,2),(5,3),(10,3),(11,4),(16,4),(17,5),(20,5)])
def test_independent_foundation_spaces_and_safe_choice(tmp_path,monkeypatch,cl,maximum):
    cold,mid,table=start(tmp_path,monkeypatch,[FOUNDATION],cl=cl)
    picked=[cell_id(Position(x=x,y=2)) for x in [1,3,5,7,9][:maximum]]
    def answer(prompt,ids):
        if 'foundation_spaces' in prompt['context']['choice_id']:
            assert all(p in ids for p in picked)
            return picked
        if 'foundation_safe' in prompt['context']['choice_id']:return [B]
        return ids[:1]
    before=cold()._load_session(mid).engine.state.actors[A].resources.copy()
    choose(table,mid,candidate(cold,mid,'Set Foundation'),answer)
    engine=checked(cold,mid)
    zones=[z for z in engine.state.zones.values() if z.active and z.owner_id==A]
    assert len(zones)==1 and len(zones[0].affected_cells)==maximum
    assert {(c.x,c.y) for c in zones[0].affected_cells}=={(int(x.split(':')[-1].split(',')[0]),2) for x in picked}
    assert zones[0].trigger_profile['earth_designated_safe']==B
    assert engine.state.actors[A].resources==before
    assert zones[0].duration_rounds==10 and not zones[0].concentration_link


@pytest.mark.parametrize('cl,maximum',[(1,1),(5,2),(11,3),(17,4)])
def test_glass_real_surface_capacity_refresh_and_preserved_stats(tmp_path,monkeypatch,cl,maximum):
    objects=[{'id':i+1,'kind':'custom','name':f'Stone {i+1}','x':1+i%2,'y':1+i//2,
              'weight_lb':1,'material':'stone','blocks':False} for i in range(3)]
    cold,mid,table=start(tmp_path,monkeypatch,[GLASS],cl=cl,objects=objects)
    before=cold()._load_session(mid).engine.state.actors[A]
    hp,ac=before.current_hp,before.armor_class
    choices=['body','ground:1:1:0','object:object:map.1','object:object:map.2'][:maximum]
    for surface in choices:
        turn(table,mid,A)
        def answer(p,ids):
            if 'temper_surface' in p['context']['choice_id']:
                assert surface in ids; return [surface]
            return ids[:1]
        choose(table,mid,candidate(cold,mid,'Temper Glass Surface'),answer)
        engine=checked(cold,mid)
        assert (engine.state.actors[A].current_hp,engine.state.actors[A].armor_class)==(hp,ac)
        menu=table.state(mid)['menu'];table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],0)
    turn(table,mid,A)
    choose(table,mid,candidate(cold,mid,'Temper Glass Surface'),lambda p,ids:['body'] if 'temper_surface' in p['context']['choice_id'] else ids[:1])
    engine=checked(cold,mid)
    held=[c for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.glass_tempered']
    assert len(held)==maximum
    assert len({c.data['surface_identity'] for c in held})==maximum


@pytest.mark.parametrize('operation', ['toggle','signal','pick_up','knock_over','tug'])
def test_thread_object_simple_operations_commit_real_object(tmp_path,monkeypatch,operation):
    obj={'id':1,'kind':'custom','name':'Small mechanism','x':2,'y':1,'weight_lb':10,
         'size':'tiny','blocks':False,'simple_operations':[{'id':'use','name':'Operate the mechanism','kind':operation,'state':1 if operation=='knock_over' else 0}]}
    cold,mid,table=start(tmp_path,monkeypatch,[PUPPET],objects=[obj])
    before=cold()._load_session(mid).engine.state.actors[A].resources.copy()
    choose(table,mid,candidate(cold,mid,'Thread the Object: simple manipulation'))
    engine=checked(cold,mid); actual=engine.state.objects['object:map.1']
    assert actual.component['simple_operations'][0]['state']==(0 if operation=='knock_over' else 1)
    assert engine.state.actors[A].resources==before
    if operation=='pick_up': assert actual.component['suspended_by']==A and not actual.unattended


@pytest.mark.parametrize('projected',[False,True])
def test_body_puppetry_requires_specific_projection_fact(tmp_path,monkeypatch,projected):
    obj={'id':1,'kind':'custom','x':5,'y':1,'weight_lb':1,'blocks':False}
    facts=[('projection_permission',{'feature':PUPPET,'objects':['object:map.1'],'breakthrough':'The GM records a prior external projection breakthrough for this marked object.'})] if projected else []
    cold,mid,table=start(tmp_path,monkeypatch,[PUPPET],body=True,objects=[obj],facts=facts)
    options=[c for c in cold()._load_session(mid).engine.legal_candidates() if 'move object' in c.display_name]
    assert bool(options)==projected
    if projected:
        c=next(c for c in options if 'Projected Puppetry' in c.display_name)
        choose(table,mid,c,lambda p,ids:[cell_id(Position(x=4,y=1))])
        assert checked(cold,mid).state.objects['object:map.1'].position==Position(x=4,y=1)


@pytest.mark.parametrize('cl,dice',[(1,1),(5,2),(11,3),(17,4)])
def test_clod_object_damage_and_owner_mark_on_actual_hit(tmp_path,monkeypatch,cl,dice):
    obj={'id':1,'kind':'custom','x':2,'y':1,'material':'stone','weight_lb':20,'ac':1,'hp':999,'blocks':False}
    cold,mid,table=start(tmp_path,monkeypatch,[CLOD],cl=cl,objects=[obj])
    engine=cold()._load_session(mid).engine
    action=next(a for a in engine.action_catalog.values() if a.owner_id==A and (a.parameters.get('typed') or {}).get('source')==CLOD)
    attack=next(r for r in action.parameters['typed']['effects'] if r['type']=='attack')
    damage=next(r for r in attack['on_hit'] if r['type']=='damage')
    from factory_authoring.typed_mechanics import dice_for_cl
    assert dice_for_cl(damage['dice_by_cl'],cl)=={'count':dice,'sides':8}
    c=next(c for c in engine.legal_candidates() if c.source_definition_id==action.source_definition_id and c.target_ids==('object:map.1',))
    choose(table,mid,c)
    engine=checked(cold,mid); obj=engine.state.objects['object:map.1']
    roll=next(e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==A)
    if roll.payload['natural_result']==1:
        assert obj.current_hp==999 and not obj.component.get('cultivation_marks')
    else:
        assert obj.current_hp<999
        mark=obj.component['cultivation_marks'][0]
        assert mark['owner_id']==A and mark['name']=='Burden Mark'


@pytest.mark.parametrize('origin',['fingertips','breath','weapon','sleeve','hair','blood','dantian pressure'])
def test_qi_strand_printed_origins_and_refresh_native(tmp_path,monkeypatch,origin):
    cold,mid,table=start(tmp_path,monkeypatch,[THREAD])
    engine=cold()._load_session(mid).engine
    pool='resource:core.qi'; before=engine.state.actors[A].resources[pool]
    c=candidate(cold,mid,'Spool and Strand: Qi Thread from '+origin)
    choose(table,mid,c); engine=checked(cold,mid)
    assert engine.state.actors[A].resources[pool]==before-1
    held=[x for x in engine.state.actors[A].conditions.values() if x.condition_id=='condition:typed.qi_thread']
    assert len(held)==1 and held[0].data['origin']==origin
    assert engine.state.actors[A].action_available and engine.state.actors[A].bonus_action_available
    choose(table,mid,candidate(cold,mid,'Spool and Strand: Qi Thread from '+origin))
    assert len([x for x in checked(cold,mid).state.actors[A].conditions.values() if x.condition_id=='condition:typed.qi_thread'])==1
