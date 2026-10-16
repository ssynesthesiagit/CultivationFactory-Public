"""Thousand-Fold native acquisition, committed choices and cold mechanical replay."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from app.api import create_app
from combat.ext import steel_forms
from combat.gate5_service import CombatService
import zipfile
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests import test_riders_c7 as c7

PARENT='tianxia.subpath.body.thousand_fold_steel_body'
FEATURES=dict(zip((3,6,10,14,18),('body_forged_in_three_forms','quench_the_impact','folded_edge_hidden_spine','ten_thousand_reforgings','body_beyond_the_hammer')))
OWNER='actor:factory.11111111-1111-4111-8111-111111111111'
FOE='actor:factory.22222222-2222-4222-8222-222222222222'
EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-thousand-fold-steel-body-4-evidence')


def acquire(environment,monkeypatch,cl):
    # Retained ACTUAL acquisition from the positive native head probe. Base's
    # unrelated sealed projection-authority identity rejects a fresh compile.
    # No feature/ownership rows are synthesized: replay the acquired document.
    paths=sorted(EVIDENCE.glob('acquisition-cl'+str(cl)+'-*.json'))
    assert paths, 'An actual native source acquisition is required.'
    return json.loads(paths[0].read_text())['document']


def loaded(service,mid):
    session=CombatService(service.source_root,service.userdata_root)._load_session(mid)
    replay=session.mechanical.replay()
    assert replay['status']=='PASS',replay
    engine=session.engine
    state=engine.state.model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
    (EVIDENCE/('reload-'+digest[:16]+'.json')).write_text(json.dumps({'state':state,'replay':replay},sort_keys=True))
    return engine


@pytest.mark.parametrize('cl,count',[(3,1),(6,1),(10,1),(14,2),(18,3)])
def test_native_acquired_progression_and_form_state(catalog_environment,monkeypatch,tmp_path,cl,count):
    doc=acquire(catalog_environment,monkeypatch,cl)
    service,table,mid=game(tmp_path,doc,seed='STEEL-'+str(cl))
    advance(service,table,mid,picks={'choice:needle.tempering_forms':['edge','spine'][:count]})
    engine=loaded(service,mid);actor=engine.state.actors[OWNER]
    scene=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.body_scene' and c.data.get('source')==PARENT]
    assert len(scene)==1
    assert scene[0].data['source_cl']==cl
    # No printed integration procedure has completed: no implicit first weapon.
    assert not any('integrated_con' in str(c.source_definition_id) for c in engine.legal_candidates())
    assert len(steel_forms.forms(actor))==count


def test_native_beyond_keeps_reforged_edge_value(catalog_environment,monkeypatch,tmp_path):
    doc=acquire(catalog_environment,monkeypatch,18)
    service,table,mid=game(tmp_path,doc,seed='STEEL-EDGE')
    advance(service,table,mid)
    engine=loaded(service,mid);pb=engine.state.actors[OWNER].proficiency_bonus
    strike=strike_name(engine,OWNER)
    play(service,table,mid,strike,{'choice:needle.folded_edge':None,'choice:needle.body_beyond_the_hammer':None,
        'choice:needle.reed_form_move':None},target=FOE)
    engine=loaded(service,mid)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER]
    assert any(e.payload.get('hp_damage')==2*pb for e in packets)


def settle(table,mid,cid,picks=None):
    answers=[];prompts=[]
    for _ in range(40):
        state=table.state(mid); menu=state['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']=='COMMITTED':
            pass
            return prompts
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        options=[o['id'] for o in p.get('choice',{}).get('options',[])]
        value=(picks or {}).get(rid,options[:int(p['context'].get('minimum',1))] if options and rid.startswith('choice:') else None)
        answer={**p['context'],'selection':'USE' if value is not None else 'DECLINE'}
        if value is not None and options:answer['option_ids']=value if isinstance(value,list) else [value]
        answers.append(answer)
    raise AssertionError('Unsettled native choices')


def play(service,table,mid,name,picks=None,target=None):
    candidates=service._load_session(mid).engine.legal_candidates()
    found=[c for c in candidates if (c.display_name==name or c.display_name.startswith(name+' at ')) and (not target or target in c.target_ids)]
    assert found,(name,[c.display_name for c in candidates])
    c=found[0]
    return settle(table,mid,c.candidate_id,picks)


def advance(service,table,mid,aid=OWNER,picks=None):
    for _ in range(30):
        state=table.state(mid);menu=state['menu']
        if menu.get('actor_id')==aid and not menu.get('fight_setup') and menu.get('end_turn'):return
        if menu.get('end_turn'):cid=menu['end_turn']
        else:
            cid=next(o['candidate_id'] for group in menu['actions'] for o in group['options'])
        settle(table,mid,cid,picks)
    raise AssertionError('No owner turn')


def installed(root,aid,doc):
    folder=root/'portable_characters'/aid.removeprefix('actor:factory.')
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))

def game(root,doc,seed='BODY-MODES',ask=True,modes=None,foe_doc=None,positions=None,extra_foe_doc=None,maximum_rounds=20,objects=(),foe_hp=1000):
    installed(root,OWNER,doc)
    foe=copy.deepcopy(foe_doc) if foe_doc is not None else c7.sheet([],cl=18,name='Sparring opponent')
    foe['ability_scores_and_statistics']['hit_points']['maximum']=foe_hp
    installed(root,FOE,foe)
    extra='actor:factory.33333333-3333-4333-8333-333333333333'
    if extra_foe_doc is not None:installed(root,extra,extra_foe_doc)
    service=CombatService(ROOT,root)
    if ask:TabletopService(service,root).save_reactions('11111111-1111-4111-8111-111111111111',{'mode':'ask'})
    saved=service.tabletop_maps.save({'display_name':'Body modes native yard','width_squares':14,'height_squares':14,
        'walls':[],'objects':list(objects),'starts':positions or {'team1':[[3,6]],'team2':[[4,6]]}})
    mid=service.create_factory_match(project_ids=['11111111-1111-4111-8111-111111111111'],opponent_actor_ids=[FOE]+([extra] if extra_foe_doc is not None else []),
        control_modes=modes or {OWNER:'MANUAL',FOE:'MANUAL',**({extra:'MANUAL'} if extra_foe_doc is not None else {})},arena_id='battlefield:map.'+saved['map_id'],match_seed=seed,maximum_rounds=maximum_rounds)['match_id']
    return service,TabletopService(service,root),mid

def strike_name(engine,aid):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id==aid and a.economy.value=='ACTION'
                and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in (a.parameters.get('typed') or {}).get('effects',())))


def record_source_result(table,service,mid,*,subject=OWNER,operation='destroy_limb',kind='limb',key='left hand',authority='ordinary',source_cl=1,explicit=0):
    from combat.combat_world_facts import clock
    engine=loaded(service,mid)
    payload={'source':'system:source_consequences','subject':subject,'kind':'apply_result','scope':operation+':'+key,
        'value':{'source_rule':'Table-owner external Source Rule: '+operation.replace('_',' ')+' of the identified physical structure; resolve other consequences separately.',
            'source_cl':source_cl,'explicit_source_cl':explicit,'authority':authority,'source_actor_id':FOE,
            'operation':operation,'target_kind':kind,'target_key':key,'reconstructable':1},
        'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]}
    result=table.world_fact(mid,engine.state.state_version,payload,'source-'+operation+'-'+subject+'-'+key)
    assert result['status']=='COMMITTED'
    # Recording external facts is not applying the result.
    after=loaded(service,mid)
    assert after.state.actors[subject].current_hp==engine.state.actors[subject].current_hp
    play(service,table,mid,'Apply a recorded source consequence')
    return loaded(service,mid)


@pytest.mark.parametrize('cl,protected',[(14,False),(18,True)])
def test_native_anatomy_source_application_and_wrong_tier(catalog_environment,monkeypatch,tmp_path,cl,protected):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,cl),seed='STEEL-ANATOMY-'+str(cl))
    advance(service,table,mid)
    before=loaded(service,mid).state.actors[OWNER].current_hp
    engine=record_source_result(table,service,mid)
    actor=engine.state.actors[OWNER]
    injury=any(c.condition_id=='condition:source.anatomy_loss' for c in actor.conditions.values())
    assert injury is not protected
    rolls=[r for r in engine.rolls if r.reason=='DAMAGE:'+PARENT+'.feature.anatomy_replacement']
    assert bool(rolls) is protected
    if protected:
        assert before-actor.current_hp==rolls[-1].total
        assert rolls[-1].expression.startswith('4d10')
        assert not any(e.event_type=='RESOURCE_SPENT' and e.source_definition_id==PARENT+'.feature.quench_the_impact' for e in engine.events)


def test_native_source_protection_keeps_authority_exceptions(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-AUTHORITY')
    advance(service,table,mid)
    engine=record_source_result(table,service,mid,operation='rust',kind='body',key='body')
    assert not any(c.condition_id=='condition:source.implement_damage' for c in engine.state.actors[OWNER].conditions.values())
    engine=record_source_result(table,service,mid,operation='warp',kind='body',key='body',authority='artifact')
    assert any(c.condition_id=='condition:source.implement_damage' and c.data['operation']=='warp'
        for c in engine.state.actors[OWNER].conditions.values())
    # The same generic producer remains ordinary for a creature without the family.
    engine=record_source_result(table,service,mid,subject=FOE,operation='corrode',kind='body',key='body')
    assert any(c.condition_id=='condition:source.implement_damage' for c in engine.state.actors[FOE].conditions.values())


def journey(service):
    return service.create_journey(project_ids=[OWNER.removeprefix('actor:factory.'),FOE.removeprefix('actor:factory.')],
        arena_id='battlefield:factory_pillar_arena',positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},
        base_paces={OWNER:12000,FOE:12000})


def journey_act(service,state,kind,payload):
    result=service.journey_act(state['journey_id'],state['revision'],OWNER,kind,payload)
    return CombatService(service.source_root,service.userdata_root).journey_state(state['journey_id'])


def test_native_temper_work_is_required_and_survives_combat_entry(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-TEMPER')
    state=journey(service)
    options=service.journey_menu(state['journey_id'],OWNER)['options']
    temper=next(o for o in options if o['id'].startswith('steel:temper:'))
    weapon=temper['payload']['parameters']['weapon']
    state=journey_act(service,state,temper['kind'],temper['payload'])
    row=state['actors'][OWNER]['source_states']['journey:activity']
    assert row['tool_objects']==['smithing'] and row['required_seconds']==600
    state=journey_act(service,state,'activity_work',{'seconds':599})
    assert 'tempered_weapon' not in state['actors'][OWNER]['source_states'].get(PARENT,{})
    state=journey_act(service,state,'activity_work',{'seconds':1})
    assert state['actors'][OWNER]['source_states'][PARENT]['tempered_weapon']==weapon
    result=service.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'team:a',FOE:'team:b'})
    mid=result['match_id'];engine=loaded(service,mid)
    assert steel_forms.tempered_weapon(engine,engine.state.actors[OWNER])==weapon
    from combat.weapon_delivery import attack_materials
    action=engine.action_catalog[weapon]
    assert attack_materials(engine,engine.state.actors[OWNER],action,'weapon')==('adamantine',)
    advance(service,table,mid)
    engine=loaded(service,mid)
    variants=[c for c in engine.legal_candidates() if 'integrated_con' in str(c.source_definition_id)]
    assert variants and all(c.source_definition_id.split('#')[0]==weapon for c in variants)


@pytest.mark.parametrize('pair',[['edge','spine'],['edge','reed'],['spine','reed']])
def test_native_quench_can_retain_or_replace_both_forms(catalog_environment,monkeypatch,tmp_path,pair):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,14),seed='STEEL-QUENCH-'+','.join(pair))
    picks={'choice:needle.tempering_forms':['edge','spine'],'choice:needle.quench_the_impact':['spine'],
        'choice:needle.quench_forms':['_'.join(pair)],'choice:needle.reed_form_move':None}
    advance(service,table,mid,FOE,picks=picks)
    for _ in range(5):
        engine=loaded(service,mid)
        play(service,table,mid,strike_name(engine,FOE),picks,target=OWNER)
        engine=loaded(service,mid)
        reactions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PARENT+'.feature.quench_the_impact']
        if reactions:break
        advance(service,table,mid,OWNER,picks=picks)
        # Let the round pass through a real end-turn intent.
        state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
        advance(service,table,mid,FOE,picks=picks)
    assert reactions
    assert steel_forms.forms(engine.state.actors[OWNER])==pair
    paid=[e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==PARENT+'.feature.quench_the_impact']
    assert len(paid)==1 and paid[0].payload['amount']==1


# Explicit dependencies of the real catalog source-inventory hash. The loader
# assembles these filenames dynamically; CI must retain the real authority.
NATIVE_SOURCE_DEPENDENCIES = (
    'catalog_authority/cat3/source/INSIGHT_TYPE_MAPPING.json',
    'catalog_authority/cat3/source/INSIGHT_GROUPING_INVENTORY.json',
    'catalog_authority/cat3/source/SUPERSESSION_AND_COLLISION_LEDGER.json',
    'catalog_authority/cat3/source/SPHERE_BASE_ABILITY_MATRIX.csv',
    'catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json',
)


def test_native_suppression_retains_a_player_chosen_legal_form(catalog_environment,monkeypatch,tmp_path):
    from combat.combat_world_facts import clock
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-SUPPRESSION')
    advance(service,table,mid)
    engine=loaded(service,mid)
    result=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
        'subject':OWNER,'kind':'cultivation_suppression','scope':'suppression-source',
        'value':{'source_rule':'External equal-authority Realm suppression to effective Body CL13.',
            'source_cl':18,'system':'body','effective_cl':13},'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]},'steel-suppression')
    assert result['status']=='COMMITTED'
    engine=loaded(service,mid)
    assert len(steel_forms.active_forms(engine,engine.state.actors[OWNER]))==1
    play(service,table,mid,'Dodge',{'choice:needle.steel_suppressed_forms':['reed']})
    engine=loaded(service,mid)
    assert steel_forms.active_forms(engine,engine.state.actors[OWNER])==['reed']
    assert set(steel_forms.forms(engine.state.actors[OWNER]))=={'edge','spine','reed'}


def test_native_full_session_completion_offers_every_tempered_weapon(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,3),seed='STEEL-SESSION')
    state=journey(service)
    option=next(o for o in service.journey_menu(state['journey_id'],OWNER)['options'] if o['id']=='cultivation:full_session')
    state=journey_act(service,state,option['kind'],option['payload'])
    state=journey_act(service,state,'activity_work',{'seconds':7199})
    assert not any(e['kind']=='FULL_CULTIVATION_SESSION_FINISHED' for e in state['events'])
    state=journey_act(service,state,'activity_work',{'seconds':1})
    choices=service.journey_menu(state['journey_id'],OWNER)['options']
    assert any(o['payload']['choice']=='retain' for o in choices)
    weapon=next(o for o in choices if o['payload']['choice']!='retain')
    state=journey_act(service,state,weapon['kind'],weapon['payload'])
    assert state['actors'][OWNER]['source_states'][PARENT]['tempered_weapon']==weapon['payload']['choice']
    assert any(e['kind']=='FULL_CULTIVATION_SESSION_FINISHED' and e['worked_seconds']==7200 for e in state['events'])
