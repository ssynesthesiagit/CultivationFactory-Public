"""White Heron native learning -> table commit -> cold mechanical replay."""
import json
import zipfile
import pytest
from functools import lru_cache
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, settle, reload, candidate, turn, OWNER, FOE
SCHOOL='tianxia.subpath.body.white_heron_crescent_body'
PREFIX=SCHOOL+'.feature.'
FEATURES=['crescent_body_integration','one_legged_guard','crescent_reaping_circle','white_wing_crosses_the_reed_field','moon_over_the_reed_sea']
PID='0badc0de-0000-4000-8000-000000000059'
STAFF='tianxia.mortal.weapon.ji'
KIT={'starting_kit':{'items':[{'item_id':STAFF}]}}


@lru_cache(maxsize=1)
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def native_table(combat,tmp_path):
    table=TabletopService(combat,tmp_path)
    table.canonical_catalog=catalog()
    return table


def acquired(tmp_path,cl=18,path='Body Refining',dc=50,learn=True):
    doc=sheet([],cl=cl,primary='Stamina',kit=KIT,dc=dc)
    doc['identity']['path']=path
    doc['identity']['name']='White Heron practitioner'
    doc['identity']['path_ids']=['tianxia.path.body_refining'] if path=='Body Refining' else ['tianxia.path.qi_cultivation']
    doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
    folder=tmp_path/'portable_characters'/PID;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    if learn:table.add_advancement(PID,'subpath',SCHOOL)
    return CombatService(ROOT,tmp_path)._factory_owner_sheet(PID)


def game(tmp_path,cl=18,**kwargs):
    doc=acquired(tmp_path/'learning',cl,dc=kwargs.pop('source_dc',50),learn=cl>=3)
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    return fixture(tmp_path/'fight',[],owner_bundle=bundle,owner_path='Body Refining',primary='Stamina',
        owner_kit=KIT,cl=cl,seed='HERON58',foe_position=kwargs.pop('foe_position',{'x':4,'y':6}),
        ally_position={'x':3,'y':7},named=True,**kwargs)


@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_progression_cold(tmp_path,cl,count):
    doc=acquired(tmp_path,cl)
    ids=doc.get('path_and_subpath',{}).get('path_feature_record_ids',[])
    assert [mid for mid in ids if mid.startswith(PREFIX)]==[PREFIX+f for f in FEATURES[:count]]
    assert not doc.get('spheres_and_talents',{}).get('sphere_record_ids')
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    (EVIDENCE/('native-acquisition-cl'+str(cl)+'.json')).write_text(json.dumps(doc,sort_keys=True))


def test_native_acquisition_rejects_wrong_path(tmp_path):
    from combat.tabletop_service import TabletopError
    with pytest.raises((ValueError,TabletopError)):
        acquired(tmp_path,path='Qi Cultivation')

from pathlib import Path
from combat.canonical import canonical_sha256
EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-white-heron-crescent-body-4-evidence')
STAMINA='resource:core.stamina'


def cold(tmp_path,mid,label):
    engine=reload(tmp_path/'fight',mid)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    doc={'label':label,'state_sha256':canonical_sha256(engine.state.model_dump(mode='json')),
         'state':engine.state.model_dump(mode='json'),'events':[e.model_dump(mode='json') for e in engine.events],
         'rolls':[r.model_dump(mode='json') for r in engine.rolls],'mechanical_replay':'PASS'}
    (EVIDENCE/(label+'.json')).write_text(json.dumps(doc,sort_keys=True))
    return engine


def polearm(combat,mid,target=FOE):
    engine=combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if target in c.target_ids
                and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
                and a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')


def choices(**kwargs):
    return {'choice:needle.white_wing_move':None,'choice:needle.herons_passing_cut':None,
            **{'choice:needle.'+k:v for k,v in kwargs.items()}}


def move(combat,table,mid,x,y):
    c=next(c for c in combat._load_session(mid).engine.legal_candidates()
           if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(x,y,0))
    settle(table,mid,c.candidate_id)


@pytest.mark.parametrize('cl,count',[(3,1),(11,2),(17,3)])
def test_native_passing_cut_movement_scaling_and_cost(tmp_path,monkeypatch,cl,count):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    from combat import ext
    ext.effects();paid=[]
    def observe_paid(engine,actor,receipt):
        if receipt['source']==PREFIX+FEATURES[0]:paid.append(dict(receipt))
    monkeypatch.setitem(ext._HOOKS,'paid_activation_resolved',[*ext._HOOKS.get('paid_activation_resolved',[]),observe_paid])
    combat,table,mid=game(tmp_path,cl,foe_position={'x':6,'y':6})
    move(combat,table,mid,5,6)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,
        choices=choices(herons_passing_cut=['damage'],heron_damage_type=['FORCE']))
    engine=cold(tmp_path,mid,'passing-'+str(cl))
    assert engine.state.actors[OWNER].resources[STAMINA]==before-1
    assert any(p['context']['reaction_source_id']=='choice:needle.herons_passing_cut' for p in prompts)
    assert any(r.expression.startswith(str(count)+'d8') for r in engine.rolls)
    assert engine.state.actors[OWNER].turn_flags.get('_round_passing_cut')
    real_payments={e.sequence for e in engine.events if e.event_type=='RESOURCE_SPENT'
        and e.source_definition_id==PREFIX+FEATURES[0]}
    assert any(r['paid']==1 and set(r['payment_sequences'])==real_payments for r in paid)
    (EVIDENCE/('passing-native-settlement-'+str(cl)+'.json')).write_text(json.dumps(paid,sort_keys=True))



@pytest.mark.parametrize('outcome',['push','prone','ac','attack'])
def test_native_white_wing_every_result(tmp_path,monkeypatch,outcome):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=game(tmp_path,14,extra_foes=1)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    picks=choices(white_wing_move=['cell:5,6'],white_wing_result=[outcome],white_wing_target='first')
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,choices=picks)
    engine=cold(tmp_path,mid,'wing-'+outcome);actor=engine.state.actors[OWNER];foe=engine.state.actors[FOE]
    assert (actor.position.x,actor.position.y)==(5,6)
    assert actor.resources[STAMINA]==before
    assert any(p['context']['reaction_source_id']=='choice:needle.white_wing_result' for p in prompts)
    if outcome=='ac':assert any(m.value==2 and m.source_definition_id==PREFIX+FEATURES[3] for m in actor.modifiers.values())
    elif outcome=='push':assert foe.position.x<4
    elif outcome=='prone':assert any(c.condition_id.endswith('.prone') for c in foe.conditions.values())
    else:assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==2


@pytest.mark.parametrize('save_roll',[1,20])
def test_native_reaping_save_cost_and_no_attack_hit_riders(tmp_path,monkeypatch,save_roll):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=save_roll)
    combat,table,mid=game(tmp_path,10,source_dc=10 if save_roll==20 else 50)
    engine=combat._load_session(mid).engine;before=engine.state.actors[OWNER].resources[STAMINA]
    c=next(c for c in engine.legal_candidates() if c.display_name.startswith('Crescent Reaping Circle'))
    settle(table,mid,c.candidate_id,choices=choices(reaping_circle_rider=['deny'],reaping_circle_move=None,heron_damage_type=['FORCE']))
    engine=cold(tmp_path,mid,'reaping-'+str(save_roll))
    assert engine.state.actors[OWNER].resources[STAMINA]==before-2
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)
    assert any(r.expression.startswith('3d8') for r in engine.rolls)
    assert not any(c.display_name.startswith('Crescent Reaping Circle') for c in engine.legal_candidates())
    assert engine.state.actors[FOE].current_hp<60
    denied=any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    assert denied is (save_roll==1)


@pytest.mark.parametrize('outcome',['minus','push','deny','move'])
def test_native_guard_commits_before_attack_and_reloads(tmp_path,monkeypatch,outcome):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    from combat import ext
    from combat.ext import white_heron
    from combat.attack_declaration import current_pending
    ext.effects();diagnostics=[];original=white_heron.guard_needs_reach
    def trace_guard(engine,actor,row):
        result=original(engine,actor,row)
        if row.get('feature_id')==PREFIX+FEATURES[1]:
            diagnostics.append({'pending':dict(current_pending(engine) or {}),'result':result,
                'ready':list(white_heron._ready(engine,actor)),
                'available':white_heron._available(engine,actor,PREFIX+FEATURES[1]),
                'current':engine.state.current_actor_id})
        return result
    monkeypatch.setitem(ext._HOOKS,'row_allowed',[trace_guard if hook is original else hook for hook in ext._HOOKS['row_allowed']])
    combat,table,mid=game(tmp_path,6)
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine;before=engine.state.actors[OWNER].resources[STAMINA]
    c=next(c for c in engine.legal_candidates() if OWNER in c.target_ids
        and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
        and a.owner_id==FOE and any(e.get('type')=='attack' for e in a.parameters.get('typed',{}).get('effects',[])))
    prompts=settle(table,mid,c.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first',
        'choice:needle.one_legged_guard':[outcome],
        'choice:needle.one_legged_guard_move':['cell:2,6']})
    engine=cold(tmp_path,mid,'guard-'+outcome)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED']
    (EVIDENCE/('guard-diagnostic-'+outcome+'.json')).write_text(json.dumps(diagnostics,sort_keys=True))
    assert rolls and rolls[0].actor_id==OWNER,diagnostics
    assert engine.state.actors[OWNER].resources[STAMINA]==before-1
    assert not engine.state.actors[OWNER].reaction_available
    if outcome in ('push','move'):assert len(rolls)==1
    elif outcome=='deny':assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    assert any(p['context']['reaction_source_id']=='choice:needle.one_legged_guard' for p in prompts)


def test_native_moon_commit_stance_and_scene_limit(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=game(tmp_path,18,foe_position={'x':7,'y':6})
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    c=candidate(combat,mid,'Moon over the Reed Sea',at=(8,6))
    settle(table,mid,c.candidate_id,choices=choices(moon_push_distance=['0']))
    engine=cold(tmp_path,mid,'moon-scene');actor=engine.state.actors[OWNER]
    assert actor.resources[STAMINA]==before-7
    assert (actor.position.x,actor.position.y)==(8,6)
    assert any(c.condition_id=='condition:typed.state.moon_reed_stance' for c in actor.conditions.values())
    assert any(m.value==2 and m.source_definition_id==PREFIX+FEATURES[4] for m in actor.modifiers.values())
    assert not any(c.display_name.startswith('Moon over the Reed Sea') for c in engine.legal_candidates())
    assert len([r for r in engine.rolls if r.expression.startswith('10d8')])==1


def test_native_stow_dormancy_and_default_inert(tmp_path):
    combat,table,mid=game(tmp_path,18)
    settle(table,mid,candidate(combat,mid,'Stow Ji (Halberd) (frees 1 hand; no Action)').candidate_id)
    engine=cold(tmp_path,mid,'stowed')
    assert not any(c.display_name.startswith(('Crescent Reaping Circle','Moon over the Reed Sea')) for c in engine.legal_candidates())
    assert not any(r.get('kind')=='heron' for r in engine.typed_passive_rows[FOE])


from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    from tests.test_a2_glass_stock import test_six_stock_captures_equal_main
    monkeypatch.setenv('CF_REPLAY_BASE','224183aa0820a83cee6069328add3c2ad954adfa')
    monkeypatch.setenv('CF_STOCK_EVIDENCE',str(EVIDENCE/'stock'))
    test_six_stock_captures_equal_main(tmp_path,seed)


def test_builder_created_body_heron_native_all_features(catalog_environment,monkeypatch,tmp_path):
    """Fresh printed Path/Subpath progression, real granted implement, table commit and replay."""
    from pathlib import Path
    from app.api import create_app
    from app.core import sha256_json
    from factory_authoring.owner_items import OwnerItemStore, weapon_choices
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(catalog_environment['settings'])
    builder=app.state.character_builder
    project=builder.create_project(working_name='White Heron source practitioner',concept='Body Refiner of the Open School of White Heron',
        source_reference=None,target_cl=18,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='HERON-SOURCE-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],'subpath_choice':[SCHOOL]},method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='heron-native-source-18',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'),run
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==SCHOOL]
    assert {r['feature_id'] for r in earned}=={PREFIX+name for name in FEATURES}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    for name in ('refined_iron_fist','heavenly_fist'):
        assert any(r['feature_id']=='tianxia.path.body_refining.feature.'+name and r['source_backed']
                   for r in doc['path_and_subpath']['earned_feature_occurrences'])
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-white-heron-crescent-body-4-evidence')
    (evidence/'native-body-heron-acquisition.json').write_text(json.dumps({'document':doc,'document_sha256':sha256_json(doc),
        'project_id':project['project_id'],'run_id':run['run_id'],'status':run['status'],'blockers':run.get('blockers',[])},sort_keys=True))

    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=1)
    item_choices=weapon_choices(STAFF,'Spiritual',None,[])
    profile={'source_rule':'Item Book: Ji (Halberd), Spiritual Treasure; table owner assigned Source CL 3',
        'authority':'native table owner','source_cl':3,'kind':'weapon','weight_lb':6,'cube_ft':6,
        'flags':{'magical':1,'cultivated':1,'prerequisites_met':1},'properties':[]}
    store=OwnerItemStore(tmp_path/'real_items')
    entry=store.give(PID,{'kind':'weapon','chassis_id':STAFF,'grade':'Spiritual',
        'material_id':item_choices['material_id'],'enchantment_ids':[],'name':'Recorded Heron Polearm','runtime_profile':profile})
    bundle=compile_character(doc,actor_id=OWNER,owner_items=store.items(PID),reaction_plan={'ask':True})
    map_service=CombatService(ROOT,tmp_path/'map_source')
    arena=map_service.tabletop_maps.save({'display_name':'Heron sourced practice','width_squares':14,'height_squares':14,
        'walls':[],'objects':[{'id':i,'x':4,'y':6-i,'kind':'custom','name':'Sourced practice pillar '+str(i),
            'hp':999,'ac':1,'blocks':False,'threshold':100,'resist':['SLASHING','FORCE'],'source_cl':level,
            'source_rule':'Native owner: unattended practice pillar, Source CL '+str(level)} for i,level in ((1,3),(2,20))],
        'starts':{'team1':[[3,6]],'team2':[[7,6]]}})
    battlefield=map_service.factory_arenas()['battlefield:map.'+arena['map_id']]
    combat,table,mid=fixture(tmp_path/'fight',[],owner_bundle=bundle,cl=18,primary='Stamina',named=True,battlefield=battlefield,
        foe_position={'x':7,'y':6},ally_position={'x':3,'y':7},seed='HERON-BUILDER-NATIVE')
    from combat.acquisition_inventory import read
    engine=combat._load_session(mid).engine
    assert read(engine.state.actors[OWNER])[entry['item_uid']]['acquisition']['route']=='owner_gift'
    def ready_gift(c,t,m):
        # Readiness is committed by the same free Draw/Stow actions as players.
        for _ in range(16):
            eng=c._load_session(m).engine
            stow=next((o for o in eng.legal_candidates() if o.display_name.startswith('Stow ')),None)
            if stow is None:break
            settle(t,m,stow.candidate_id)
        eng=c._load_session(m).engine
        draw=next(o for o in eng.legal_candidates() if o.display_name.startswith('Draw Recorded Heron Polearm'))
        settle(t,m,draw.candidate_id)
    ready_gift(combat,table,mid)
    engine=combat._load_session(mid).engine
    for object_id,damaged in (('object:map.1',True),('object:map.2',False)):
        strike=next(c for c in engine.legal_candidates() if c.target_ids==(object_id,)
            and engine.action_catalog[c.source_definition_id].parameters.get('object_source_weapon')
            and 'Recorded Heron Polearm' in engine.action_catalog[c.source_definition_id].display_name)
        settle(table,mid,strike.candidate_id,choices={'choice:needle.heron_heavenly_type':['FORCE']})
        engine=cold(tmp_path,mid,'builder-object-'+object_id.rsplit('.',1)[-1])
        assert (engine.state.objects[object_id].current_hp<999) is damaged
        turn(table,mid,FOE);turn(table,mid,OWNER)
        engine=combat._load_session(mid).engine
    before=engine.state.actors[OWNER].resources[STAMINA]
    c=candidate(combat,mid,'Moon over the Reed Sea',at=(3,6))
    settle(table,mid,c.candidate_id,choices={'choice:needle.moon_over_the_reed_sea':['all'],
        'choice:needle.moon_push_distance':['0'],'choice:needle.heron_damage_type':['FORCE']})
    engine=cold(tmp_path,mid,'builder-body-inventory-moon')
    assert engine.state.actors[OWNER].resources[STAMINA]<=before-7
    assert any(c.condition_id=='condition:typed.state.moon_reed_stance' for c in engine.state.actors[OWNER].conditions.values())

    # Each exact row also commits from this same builder-earned Path/Subpath
    # document and the same actual gifted implement, in independent matches.
    def learned_fight(label,foe_position):
        root=tmp_path/label
        actual=compile_character(doc,actor_id=OWNER,owner_items=store.items(PID),reaction_plan={'ask':True})
        c,t,m=fixture(root/'fight',[],owner_bundle=actual,cl=18,primary='Stamina',named=True,
            foe_position=foe_position,ally_position={'x':3,'y':7},seed='HERON-ACQUIRED-'+label)
        ready_gift(c,t,m)
        return root,c,t,m
    def actual_polearm(c,m):
        eng=c._load_session(m).engine
        return next(option for option in eng.legal_candidates() if FOE in option.target_ids
            and (action:=eng.action_catalog.get(option.source_definition_id)) is not None
            and action.owner_id==OWNER and action.parameters.get('typed',{}).get('source')==STAFF
            and any(e.get('type')=='attack' for e in action.parameters['typed'].get('effects',[])))
    root,c,t,m=learned_fight('passing',{'x':6,'y':6})
    move(c,t,m,5,6);before=c._load_session(m).engine.state.actors[OWNER].resources[STAMINA]
    settle(t,m,actual_polearm(c,m).candidate_id,choices=choices(herons_passing_cut=['damage'],heron_damage_type=['FORCE']))
    eng=cold(root,m,'builder-passing');assert eng.state.actors[OWNER].resources[STAMINA]==before-1
    assert any(r.expression.startswith('3d8') for r in eng.rolls)
    root,c,t,m=learned_fight('wing',{'x':4,'y':6})
    settle(t,m,actual_polearm(c,m).candidate_id,choices=choices(white_wing_move=['cell:5,6'],white_wing_result=['ac']))
    eng=cold(root,m,'builder-wing');assert eng.state.actors[OWNER].position.x==5
    assert any(mod.source_definition_id==PREFIX+FEATURES[3] and mod.value==2 for mod in eng.state.actors[OWNER].modifiers.values())
    root,c,t,m=learned_fight('reaping',{'x':4,'y':6})
    eng=c._load_session(m).engine;before=eng.state.actors[OWNER].resources[STAMINA]
    sweep=next(option for option in eng.legal_candidates() if option.display_name.startswith('Crescent Reaping Circle'))
    settle(t,m,sweep.candidate_id,choices=choices(reaping_circle_rider=['deny'],reaping_circle_move=None,heron_damage_type=['FORCE']))
    eng=cold(root,m,'builder-reaping');assert eng.state.actors[OWNER].resources[STAMINA]==before-2
    assert any(r.expression.startswith('3d8') for r in eng.rolls)
    root,c,t,m=learned_fight('guard',{'x':4,'y':6});turn(t,m,FOE)
    eng=c._load_session(m).engine;before=eng.state.actors[OWNER].resources[STAMINA]
    attack=next(option for option in eng.legal_candidates() if OWNER in option.target_ids
        and (action:=eng.action_catalog.get(option.source_definition_id)) is not None and action.owner_id==FOE
        and any(e.get('type')=='attack' for e in action.parameters.get('typed',{}).get('effects',[])))
    settle(t,m,attack.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first','choice:needle.one_legged_guard':['push']})
    eng=cold(root,m,'builder-guard');assert eng.state.actors[OWNER].resources[STAMINA]==before-1
    assert [e.actor_id for e in eng.events if e.event_type=='ATTACK_ROLLED']==[OWNER]


def journey_game(tmp_path,monkeypatch,cl=18,party=False):
    root=tmp_path/'journey'
    acquired(root,cl)
    service=CombatService(ROOT,root)
    arena=service.tabletop_maps.save({'display_name':'White Heron admitted road','width_squares':8,'height_squares':8,
        'walls':[],'objects':[],'starts':{'team1':[[2,2]],'team2':[[6,6]]}})
    aid='actor:factory.'+PID
    ids=[PID];positions={aid:{'x':2,'y':2}};paces={aid:5}
    if party:
        other='0badc0de-0000-4000-8000-000000000060';ids.append(other)
        folder=root/'portable_characters'/other;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([],cl=18)))
        positions['actor:factory.'+other]={'x':3,'y':2};paces['actor:factory.'+other]=5
    state=service.create_journey(project_ids=ids,arena_id='battlefield:map.'+arena['map_id'],
        positions=positions,base_paces=paces)
    return service,state,aid


def test_native_journey_moon_readiness_paid_route_expiry_scene_cold(tmp_path,monkeypatch):
    service,state,aid=journey_game(tmp_path,monkeypatch)
    jid=state['journey_id'];before=state['actors'][aid]['resources'][STAMINA]
    menu=service.journey_menu(jid,aid)
    options=menu['options']
    stow=next(o for o in options if o['kind']=='equipment_grip' and 'Stow Ji' in o['label'])
    state=service.journey_act(jid,state['revision'],aid,stow['kind'],stow['payload'])
    assert not any(o['kind']=='heron_moon' for o in service.journey_menu(jid,aid)['options'])
    draw=next(o for o in service.journey_menu(jid,aid)['options'] if o['kind']=='equipment_grip' and 'Draw Ji' in o['label'])
    state=service.journey_act(jid,state['revision'],aid,draw['kind'],draw['payload'])
    state=service.journey_act(jid,state['revision'],aid,'heron_moon',{'path':[{'x':2,'y':2},{'x':3,'y':2},{'x':4,'y':2}]})
    service=CombatService(ROOT,tmp_path/'journey')
    assert service.journey_state(jid)==state
    actor=state['actors'][aid];assert actor['resources'][STAMINA]==before-7
    assert actor['position']['x']==4
    managed=actor['source_states']['system:body_modes_scene_resources']
    assert managed['effects'][0]['remaining_num']==6
    assert any(e['kind']=='ACTIVATION_RESOLVED' and e.get('source')==PREFIX+FEATURES[4] for e in state['events'])
    with pytest.raises(ValueError):service.journey_act(jid,state['revision'],aid,'heron_moon',{'path':[actor['position']]})
    state=service.journey_act(jid,state['revision'],aid,'wait',{'seconds':6})
    assert not state['actors'][aid]['source_states']['system:body_modes_scene_resources']['effects']
    state=service.journey_end_scene(jid,state['revision'],'The practice finishes and the caravan departs.')
    state=service.journey_act(jid,state['revision'],aid,'heron_moon',{'path':[state['actors'][aid]['position']]})
    assert state['actors'][aid]['resources'][STAMINA]==before-14
    (EVIDENCE/'journey-moon.json').write_text(json.dumps(state,sort_keys=True))


@pytest.mark.parametrize('cl,own_reach',[(3,15),(13,15),(14,20),(18,20)])
def test_native_wielded_turn_reach_and_cold_boundary(tmp_path,cl,own_reach):
    from combat.ext.reach_bonus import current_reach
    combat,table,mid=game(tmp_path,cl)
    engine=combat._load_session(mid).engine;actor=engine.state.actors[OWNER]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
    assert current_reach(engine,actor,action)==own_reach
    assert current_reach(engine,actor,action,opportunity=True)==10
    assert any(c.condition_id=='condition:typed.heron_integrated_weapon' for c in actor.conditions.values())
    turn(table,mid,FOE)
    engine=cold(tmp_path,mid,'reach-'+str(cl))
    assert current_reach(engine,engine.state.actors[OWNER],action)==10


@pytest.mark.parametrize('outcome',['move','push','pull'])
def test_native_passing_cut_every_movement_result(tmp_path,monkeypatch,outcome):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,3,foe_position={'x':7,'y':6})
    move(combat,table,mid,5,6)
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,
        choices=choices(herons_passing_cut=[outcome],passing_cut_move=['cell:5,5'],passing_cut_pull=['cell:6,6']))
    engine=cold(tmp_path,mid,'passing-'+outcome)
    actor,foe=engine.state.actors[OWNER],engine.state.actors[FOE]
    assert actor.resources[STAMINA]==29
    if outcome=='move':assert (actor.position.x,actor.position.y)==(5,5)
    elif outcome=='push':
        # The arena's central solid pillar blocks the second push square.
        assert foe.position.x==8
        assert not engine.grid.volume_legal(foe.position.model_copy(update={'x':9}),footprint=engine._footprint(foe))
    else:assert (foe.position.x,foe.position.y)==(6,6)
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id!=OWNER for e in engine.events)


def test_native_no_completed_movement_no_passing_cut(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,3)
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,choices=choices())
    engine=cold(tmp_path,mid,'no-movement')
    assert engine.state.actors[OWNER].resources[STAMINA]==30
    assert not any(p['context']['reaction_source_id']=='choice:needle.herons_passing_cut' for p in prompts)


@pytest.mark.parametrize('guard',['missing_owner','wrong_schema','malformed','authority'])
def test_native_world_body_guards_atomic(tmp_path,guard):
    combat,table,mid=game(tmp_path,2 if guard=='missing_owner' else 14)
    engine=combat._load_session(mid).engine;before=engine.state.model_dump(mode='json')
    payload={'source':'system:body_modes_scene_resources','subject':OWNER,'kind':'cultivation_suppression','scope':'pressure',
        'value':{'source_rule':'Body Refining R8','source_cl':20,'system':'body','effective_cl':2},'expires_at':60,'readers':[OWNER]}
    if guard=='wrong_schema':payload['source']='unowned-source'
    if guard=='malformed':payload['value']={'effective_cl':2}
    if guard=='authority':payload['authority']='actor'
    with pytest.raises(ValueError):table.world_fact(mid,engine.state.state_version,payload,'bad-'+guard)
    assert reload(tmp_path/'fight',mid).state.model_dump(mode='json')==before


def test_native_source_suppression_cl_gates_consumers_cold(tmp_path):
    from combat.ext.reach_bonus import current_reach
    combat,table,mid=game(tmp_path,18)
    engine=combat._load_session(mid).engine
    table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources','subject':OWNER,
        'kind':'cultivation_suppression','scope':'pressure','value':{'source_rule':'Body Refining R8','source_cl':20,
        'system':'body','effective_cl':2},'expires_at':60,'readers':[OWNER]},'heron-suppression')
    engine=cold(tmp_path,mid,'suppressed')
    action=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
    assert current_reach(engine,engine.state.actors[OWNER],action)==10
    assert not any(c.display_name.startswith(('Crescent Reaping Circle','Moon over the Reed Sea')) for c in engine.legal_candidates())


@pytest.mark.parametrize('reply',[False,3,[-1],['not-a-position']])
def test_general_cell_destinations_reject_malformed_providers(tmp_path,monkeypatch,reply):
    from combat import ext
    combat,table,mid=game(tmp_path,18)
    engine=combat._load_session(mid).engine
    action=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('moon_reed'))
    actor=engine.state.actors[OWNER]
    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'cell_action_destinations',[lambda *args:reply])
    with pytest.raises(ValueError):engine._any_cell_candidates(actor,action)


def test_general_pending_attack_scope_restores_enclosing_declaration(tmp_path):
    from combat.attack_declaration import pending_attack,current_pending
    combat,table,mid=game(tmp_path,3)
    engine=combat._load_session(mid).engine
    assert current_pending(engine) is None
    outer={'attacker':FOE,'target':OWNER};inner={'attacker':OWNER,'target':FOE}
    with pending_attack(engine,outer):
        assert current_pending(engine)==outer
        with pytest.raises(TypeError):current_pending(engine)['target']='someone-else'
        with pending_attack(engine,inner):assert current_pending(engine)==inner
        assert current_pending(engine)==outer
    assert current_pending(engine) is None


@pytest.mark.parametrize('components',['bad',[{'count':True,'sides':8}],[{'count':0,'sides':8}],
    [{'count':1,'sides':1}],[{'count':1,'sides':8,'modifier':2}]])
def test_general_mixed_dice_rejects_bad_fields_before_rolling(tmp_path,components):
    from combat import typed_executor as te
    combat,table,mid=game(tmp_path,3)
    engine=combat._load_session(mid).engine;actor=engine.state.actors[OWNER];target=engine.state.actors[FOE]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
    ctx=te.Context(engine,actor,action,None,action.parameters['typed'],[target],target,{})
    before=(engine.roller.counter,len(engine.events),len(engine.rolls))
    with pytest.raises(ValueError):te._damage_roll(ctx,{'type':'damage','dice':{'count':1,'sides':10},
        'damage_types':['SLASHING'],'additional_dice':components})
    assert (engine.roller.counter,len(engine.events),len(engine.rolls))==before



def test_native_moon_physical_entry_free_attack_with_spent_reaction_once_and_expiry(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,18,foe_position={'x':5,'y':6},foe_kit=KIT)
    settle(table,mid,candidate(combat,mid,'Moon over the Reed Sea',at=(3,6)).candidate_id,
        choices=choices(moon_over_the_reed_sea=None))
    engine=cold(tmp_path,mid,'stance-expansion-no-entry')
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine
    attack=next(c for c in engine.legal_candidates() if OWNER in c.target_ids
        and engine.action_catalog.get(c.source_definition_id)
        and engine.action_catalog[c.source_definition_id].display_name=='Ji (Halberd) attack')
    settle(table,mid,attack.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first','choice:needle.one_legged_guard':['minus']})
    engine=cold(tmp_path,mid,'stance-reaction-spent')
    assert not engine.state.actors[OWNER].reaction_available
    move(combat,table,mid,7,6)
    engine=combat._load_session(mid).engine
    move_in=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(6,6,0))
    prompts=settle(table,mid,move_in.candidate_id,choices={'choice:needle.heron_polearm_attack':'first'})
    engine=cold(tmp_path,mid,'stance-entry-free-attack')
    assert any(p['context']['reaction_source_id']=='choice:needle.heron_polearm_attack' for p in prompts)
    assert not engine.state.actors[OWNER].reaction_available
    assert not engine.state.actors[OWNER].turn_flags.get('_round_moon_free_strike')
    count=len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])
    assert count==2
    move(combat,table,mid,7,6);move(combat,table,mid,6,6)
    engine=cold(tmp_path,mid,'stance-second-entry-inert')
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==count
    turn(table,mid,OWNER)
    engine=cold(tmp_path,mid,'stance-expired')
    assert not any(c.condition_id=='condition:typed.state.moon_reed_stance' for c in engine.state.actors[OWNER].conditions.values())
    assert not any(m.source_definition_id==PREFIX+FEATURES[4] for m in engine.state.actors[OWNER].modifiers.values())



def test_native_guard_protects_adjacent_enemy_preserves_its_decline_and_alternate(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    from tests.worker2_support import ALLY
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,6)
    engine=combat._load_session(mid).engine
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':ALLY,'relation':'ENEMY'},
        expected_state_version=engine.state.state_version)
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine
    attack=next(c for c in engine.legal_candidates() if ALLY in c.target_ids
        and (a:=engine.action_catalog.get(c.source_definition_id)) is not None and a.owner_id==FOE
        and any(e.get('type')=='attack' for e in a.parameters.get('typed',{}).get('effects',[])))
    before=engine.state.actors[ALLY].position
    prompts=settle(table,mid,attack.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first',
        'choice:needle.one_legged_guard':['move'],'choice:needle.one_legged_guard_move':None,
        'choice:needle.one_legged_guard_alternate':['push']})
    engine=cold(tmp_path,mid,'guard-any-creature-consent')
    move_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.one_legged_guard_move')
    assert move_prompt['context']['reactor_id']==ALLY
    assert engine.state.actors[ALLY].position==before
    assert engine.state.actors[FOE].position.x==5
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED'])==1



def test_native_journey_moon_party_transit_difficult_endpoint_atomic_and_reload(tmp_path,monkeypatch):
    service,state,aid=journey_game(tmp_path,monkeypatch,party=True)
    jid=state['journey_id'];before=json.loads(json.dumps(state))
    with pytest.raises(ValueError,match='Another creature occupies'):
        service.journey_act(jid,state['revision'],aid,'move',{'path':[{'x':3,'y':2}]})
    assert service.journey_state(jid)==before
    with pytest.raises(ValueError):service.journey_act(jid,state['revision'],aid,'heron_moon',
        {'path':[{'x':2,'y':2},{'x':3,'y':2}]})
    assert service.journey_state(jid)==before
    state=service.journey_act(jid,state['revision'],aid,'heron_moon',
        {'path':[{'x':2,'y':2},{'x':3,'y':2},{'x':4,'y':2}]})
    event=next(e for e in state['events'] if e['kind']=='GRANTED_MOVEMENT_COMMITTED')
    assert event['distance_ft']==10 and event['movement_cost_ft']==15
    assert state['actors'][aid]['position']['x']==4
    other=next(a for a in state['actors'] if a!=aid)
    assert state['actors'][other]['position']==before['actors'][other]['position']
    assert CombatService(ROOT,tmp_path/'journey').journey_state(jid)==state
    (EVIDENCE/'journey-party-route.json').write_text(json.dumps(state,sort_keys=True))


@pytest.mark.parametrize('bad',[False,3,{'cost':'free'},'teleport'])
def test_native_general_journey_passage_bad_provider_is_atomic(tmp_path,monkeypatch,bad):
    from combat import ext
    service,state,aid=journey_game(tmp_path,monkeypatch,party=True)
    jid=state['journey_id'];before=json.loads(json.dumps(state))
    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'journey_granted_passage',[lambda *args:bad])
    with pytest.raises(ValueError,match='passage must be free or difficult'):
        service.journey_act(jid,state['revision'],aid,'heron_moon',{'path':[{'x':2,'y':2},{'x':3,'y':2},{'x':4,'y':2}]})
    assert service.journey_state(jid)==before



def test_native_subpath_learning_rejects_below_cl3(tmp_path):
    from combat.tabletop_service import TabletopError
    with pytest.raises(TabletopError):acquired(tmp_path,cl=2)


@pytest.mark.parametrize('first,second',[(SCHOOL,'tianxia.subpath.body.bojutsu'),('tianxia.subpath.body.bojutsu',SCHOOL)])
def test_native_body_one_subpath_source_policy_both_orders_atomic(tmp_path,first,second):
    from combat.tabletop_service import TabletopError
    acquired(tmp_path,cl=18,learn=False)
    combat=CombatService(ROOT,tmp_path);table=native_table(combat,tmp_path)
    table.add_advancement(PID,'subpath',first)
    before=combat._factory_owner_sheet(PID)
    assert first in before['path_and_subpath']['subpath_record_ids']
    for gm in (False,True):
        with pytest.raises(TabletopError,match='one Subpath'):table.add_advancement(PID,'subpath',second,gm=gm)
        assert CombatService(ROOT,tmp_path)._factory_owner_sheet(PID)==before


@pytest.mark.parametrize('profile,modifier',[('Constitution',4),('Cultivation',6)])
def test_native_partial_body_suppression_uses_real_source_pb_and_preserves_weapon_proficiency(tmp_path,monkeypatch,profile,modifier):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,18)
    engine=combat._load_session(mid).engine
    table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources','subject':OWNER,
        'kind':'cultivation_suppression','scope':'partial pressure','value':{'source_rule':'Body Refining R8, suppression',
        'source_cl':20,'system':'body','effective_cl':3},'expires_at':60,'readers':[OWNER]},'heron-partial-suppression')
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,choices=choices(heron_ability=[profile]))
    engine=cold(tmp_path,mid,'partial-'+profile)
    rolls=[r for r in engine.rolls if r.reason.startswith('ATTACK')]
    assert rolls and rolls[-1].modifier==modifier
    assert engine.state.actors[OWNER].proficiency_bonus==4
    assert not any(c.display_name.startswith(('Crescent Reaping Circle','Moon over the Reed Sea')) for c in engine.legal_candidates())



def test_native_unarmed_hit_does_not_borrow_wielded_polearm_or_heron_riders(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,18,foe_position={'x':6,'y':6})
    move(combat,table,mid,5,6)
    engine=combat._load_session(mid).engine
    unarmed=next(c for c in engine.legal_candidates() if FOE in c.target_ids
        and (a:=engine.action_catalog.get(c.source_definition_id)) is not None and a.owner_id==OWNER
        and a.parameters.get('typed',{}).get('source')=='unarmed_strike')
    prompts=settle(table,mid,unarmed.candidate_id,choices=choices())
    engine=cold(tmp_path,mid,'unarmed-not-polearm')
    assert engine.state.actors[OWNER].resources[STAMINA]==30
    assert not any(p['context']['reaction_source_id'] in ('choice:needle.heron_ability',
        'choice:needle.herons_passing_cut','choice:needle.white_wing_move') for p in prompts)
    assert not engine.state.actors[OWNER].turn_flags.get('_round_passing_cut')
    assert not engine.state.actors[OWNER].turn_flags.get('_round_white_wing')



def test_native_learning_does_not_infer_body_attainment_from_multipath_total_cl(tmp_path):
    from combat.tabletop_service import TabletopError
    doc=acquired(tmp_path,learn=False)
    doc['identity']['path_ids'].append('tianxia.path.qi_cultivation')
    folder=tmp_path/'portable_characters'/PID
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path);table=native_table(combat,tmp_path)
    with pytest.raises(TabletopError):table.add_advancement(PID,'subpath',SCHOOL)
    assert not any(mid.startswith(PREFIX) for mid in combat._factory_owner_sheet(PID)['path_and_subpath'].get('path_feature_record_ids',[]))



def test_native_own_turn_moon_entry_uses_turn_reach_after_real_paid_nested_reaction_moves(tmp_path,monkeypatch):
    """Existing Athletics is only a native movement caller; no sibling code changes."""
    import re
    from tests.hunt12_support import hit_dice
    from tests.worker2_support import ALLY
    from tests.test_r9i_karma_persistence import act
    hit_dice(monkeypatch)
    owner_doc=acquired(tmp_path/'owner_source',18)
    source_root=tmp_path/'motion_source';source_combat=CombatService(ROOT,source_root)
    source_table=native_table(source_combat,source_root);learned={}
    for who,pid in ((ALLY,'0badc0de-0000-4000-8000-000000000060'),(FOE,'0badc0de-0000-4000-8000-000000000061')):
        folder=source_root/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([],cl=18)))
        source_table.add_advancement(pid,'sphere','tianxia.sphere.athletics')
        source_table.add_advancement(pid,'talent','TAL_ATHLETICS_UNBROKEN_PURSUIT')
        learned[who]=source_combat._factory_owner_sheet(pid)
    def actual_bundles(bundles):
        for index,who in ((1,ALLY),(2,FOE)):
            bundles[index]=compile_character(learned[who],actor_id=who,reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path/'fight',[],cl=18,owner_bundle=compile_character(owner_doc,actor_id=OWNER,reaction_plan={'ask':True}),
        bundle_transform=actual_bundles,positions={OWNER:{'x':3,'y':6},ALLY:{'x':9,'y':6},FOE:{'x':11,'y':7}},
        named=True,seed='HERON-REAL-REACTION-ENTRY')
    settle(table,mid,candidate(combat,mid,'Moon over the Reed Sea',at=(3,6)).candidate_id,
        choices=choices(moon_over_the_reed_sea=None))
    engine=combat._load_session(mid).engine
    chosen=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(3,5,0))
    answers=[];prompts=[]
    for _ in range(45):
        result=act(table,mid,chosen.candidate_id,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];prompts.append(prompt);rid=prompt['context']['reaction_source_id']
        answer={**prompt['context'],'selection':'USE'}
        options=(prompt.get('choice') or {}).get('options',[])
        if options:
            if rid.endswith('unbroken_pursuit'):
                y=6 if prompt['context']['reactor_id']==ALLY else 7
                option=next(o for o in options if re.search(r'8\s*,\s*'+str(y)+r'\b',o.get('label','')))
                answer['option_ids']=[option['id']]
            else:answer['option_ids']=[((prompt['choice'].get('preferred') or [options[0]['id']])[0])]
        elif rid!='reaction:typed.TAL_ATHLETICS_UNBROKEN_PURSUIT':answer['selection']='DECLINE'
        answers.append(answer)
    else:raise AssertionError('Native nested movement did not settle.')
    engine=cold(tmp_path,mid,'moon-own-turn-real-reaction-entry')
    assert engine.state.current_actor_id==OWNER
    assert engine.state.actors[FOE].position.x==8 and engine.state.actors[FOE].position.y==7
    assert engine.state.actors[ALLY].resources['resource:core.martial_focus']==0
    assert engine.state.actors[FOE].resources['resource:core.martial_focus']==0
    assert engine.state.actors[OWNER].reaction_available
    assert any(p['context']['reaction_source_id']=='choice:needle.heron_polearm_attack' for p in prompts)
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==1


@pytest.mark.parametrize('bad',[False,True,-1,2,'0'])
def test_general_turn_reach_policy_rejects_malformed_flags(tmp_path,bad):
    from combat.attack_reach import opportunity_geometry
    combat,table,mid=game(tmp_path,3);engine=combat._load_session(mid).engine
    actor=engine.state.actors[OWNER]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
    action=action.model_copy(update={'parameters':{**action.parameters,'outside_turn_reach':bad}})
    with pytest.raises(ValueError):opportunity_geometry(engine,actor,action,True)


@pytest.mark.parametrize('result',['minus','push'])
def test_native_stock_attacker_declares_before_guard_and_reloads(tmp_path,monkeypatch,result):
    from combat.gate2_runtime_content import AN
    from tests.hunt12_support import hit_dice
    from combat import ext
    from combat.ext import white_heron
    from combat.attack_declaration import current_pending
    from combat.ext.attack_scope import current
    ext.effects();diagnostics=[]
    original=white_heron.guard_needs_reach
    def observe_row(engine,actor,row):
        answer=original(engine,actor,row)
        if row.get('feature_id')==PREFIX+FEATURES[1]:
            diagnostics.append({'row':row['feature_id'],'pending':dict(current_pending(engine) or {}),'answer':answer})
        return answer
    def observe_native(engine,attacker,target,source,spec):
        diagnostics.append({'native':source,'kind':engine.action_catalog[source].resolution_kind,
            'economy':engine.action_catalog[source].economy.value,'pending':dict(current_pending(engine) or {}),
            'scope':(current(engine) or {}).get('source'),'spec_reach':spec.get('reach_ft'),'spec_range':spec.get('range_ft')})
    def observe_checkpoint(engine,attacker,target,intent,context):
        diagnostics.append({'checkpoint':context['source_id'],'scope':(current(engine) or {}).get('source'),
            'has_spec':bool(context.get('attack_spec')),'pending':dict(current_pending(engine) or {})})
    monkeypatch.setitem(ext._HOOKS,'row_allowed',[observe_row if f is original else f for f in ext._HOOKS['row_allowed']])
    monkeypatch.setitem(ext._HOOKS,'native_attack_reactions',[*ext._HOOKS.get('native_attack_reactions',[]),observe_native])
    monkeypatch.setitem(ext._HOOKS,'before_attack',[*ext._HOOKS.get('before_attack',[]),observe_checkpoint])
    hit_dice(monkeypatch)
    doc=acquired(tmp_path,6)
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    combat=CombatService(ROOT,tmp_path/'fight');table=TabletopService(combat,tmp_path/'fight')
    mid=combat._finish_factory_match([bundle],[OWNER,AN],{OWNER:'team:a',AN:'team:b'},
        {OWNER:{'x':3,'y':6},AN:{'x':4,'y':6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[OWNER],[AN],
        control_modes={OWNER:'MANUAL',AN:'MANUAL'},match_seed='HERON-NATIVE-DECLARATION',
        display_name='Native committed declaration',maximum_rounds=5)['match_id']
    turn(table,mid,AN)
    engine=combat._load_session(mid).engine
    strike=next(c for c in engine.legal_candidates() if OWNER in c.target_ids
        and c.kind=='ACTION' and engine.action_catalog[c.source_definition_id].resolution_kind in ('ATTACK','MULTI_ATTACK')
        and engine.action_catalog[c.source_definition_id].range_ft is None)
    before=engine.state.actors[OWNER].resources[STAMINA]
    settle(table,mid,strike.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first',
        'choice:needle.one_legged_guard':[result]})
    engine=cold(tmp_path,mid,'native-stock-guard-'+result)
    (EVIDENCE/('native-stock-guard-diagnostic-'+result+'.json')).write_text(json.dumps(diagnostics,sort_keys=True))
    assert engine.state.actors[OWNER].resources[STAMINA]==before-1
    rolled=[e for e in engine.events if e.event_type=='ATTACK_ROLLED']
    assert rolled[0].actor_id==OWNER
    if result=='push':assert not any(e.actor_id==AN for e in rolled)
    else:
        assert any(e.actor_id==AN for e in rolled)
        assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+FEATURES[1] for e in engine.events)


def _capture_guard_bystander(root):
    """Real learning, a typed Attack against a stock NPC, commit and cold replay."""
    from pathlib import Path
    import pytest
    from combat.gate2_runtime_content import AN
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT,sheet
    from tests.worker2_support import OWNER,FOE,turn,settle
    from tests.hunt12_support import hit_dice
    from tests.test_mgr_t14_white_heron_crescent_body_floor58 import acquired,PREFIX,FEATURES,STAMINA
    root=Path(root)
    doc=acquired(root/'learning',6)
    owner=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    attacker=compile_character(sheet([],cl=6),actor_id=FOE,reaction_plan={'ask':True})
    service=CombatService(ROOT,root/'fight');table=TabletopService(service,root/'fight')
    mid=service._finish_factory_match([owner,attacker],[OWNER,FOE,AN],
        {OWNER:'team:a',AN:'team:a',FOE:'team:b'},
        {OWNER:{'x':3,'y':6},AN:{'x':3,'y':7},FOE:{'x':4,'y':7}},
        service.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[OWNER],[FOE,AN],
        control_modes={OWNER:'MANUAL',FOE:'MANUAL',AN:'MANUAL'},match_seed='HERON-STOCK-PROTECTED',
        display_name='Native stock recipient protection',maximum_rounds=5)['match_id']
    turn(table,mid,FOE)
    engine=service._load_session(mid).engine
    before=engine.state.actors[OWNER].resources[STAMINA]
    strike=next(c for c in engine.legal_candidates() if c.target_ids==(AN,)
        and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
        and a.owner_id==FOE and a.economy.value=='ACTION'
        and (a.parameters.get('typed') or {}).get('attack_action'))
    with pytest.MonkeyPatch.context() as patches:
        hit_dice(patches)
        settle(table,mid,strike.candidate_id,choices={'reaction:typed.'+PREFIX+FEATURES[1]:'first',
            'choice:needle.one_legged_guard':['minus']})
        loaded=CombatService(ROOT,root/'fight')._load_session(mid)
        replay=loaded.mechanical.replay();assert replay['status']=='PASS'
        engine=loaded.engine
        return {'paid':before-engine.state.actors[OWNER].resources[STAMINA],
            'mechanical_replay':replay,'state':engine.state.model_dump(mode='json'),
            'events':[e.model_dump(mode='json') for e in engine.events],
            'rolls':[r.model_dump(mode='json') for r in engine.rolls]}


def test_native_guard_protects_stock_recipient_fail_before_and_cold(tmp_path):
    import inspect,subprocess,sys
    # The established stock Git-tree loader isolates baseline modules/resources
    # in a child of this admitted queue job. No base worktree or live data.
    baseline='00bc34825'
    script=('import json,sys\nfrom pathlib import Path\n'
        'from tests.wall_height_stock_capture import revision_sources\n'
        'revision_sources(sys.argv[1],Path(sys.argv[2])/"resources")\n'
        +inspect.getsource(_capture_guard_bystander)
        +'\nprint(json.dumps(_capture_guard_bystander(Path(sys.argv[2])/"capture"),sort_keys=True))\n')
    proc=subprocess.run([sys.executable,'-c',script,baseline,str(tmp_path/'base')],
        cwd=ROOT,text=True,capture_output=True,timeout=600)
    assert proc.returncode==0,proc.stdout[-1000:]+proc.stderr[-3000:]
    before=json.loads(proc.stdout.splitlines()[-1]);after=_capture_guard_bystander(tmp_path/'head')
    for arm,result in (('base',before),('head',after)):
        (EVIDENCE/('guard-stock-protected-'+arm+'.json')).write_text(json.dumps({'revision':baseline if arm=='base' else 'working',**result},sort_keys=True))
    assert before['paid']==0
    assert after['paid']==1
    attacks=[e for e in after['events'] if e['event_type']=='ATTACK_ROLLED']
    assert attacks[0]['actor_id']==OWNER
    assert any(e['event_type']=='REACTION_RESOLVED' and e['source_definition_id']==PREFIX+FEATURES[1] for e in after['events'])


@pytest.mark.parametrize('stow_other',[False,True])
def test_native_reaping_committed_grip_uses_one_current_weapon_die(tmp_path,monkeypatch,stow_other):
    from tests.hunt12_support import hit_dice
    from combat.ext.hand_occupancy import versatile_die_sides
    hit_dice(monkeypatch,save_roll=1)
    doc=acquired(tmp_path/'learning',10)
    doc['equipment']=[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gang_cha'}]}}]
    from factory_authoring.owner_items import OwnerItemStore,weapon_choices
    knife='tianxia.mortal.weapon.bi_shou'
    options=weapon_choices(knife,'Spiritual',None,[])
    store=OwnerItemStore(tmp_path/'items')
    store.give(PID,{'kind':'weapon','chassis_id':knife,'grade':'Spiritual','material_id':options['material_id'],
        'enchantment_ids':[],'name':'Heron Grip Knife','runtime_profile':{
            'source_rule':'Item Book: Spiritual Bi Shou, native owner gift','authority':'native table owner',
            'source_cl':1,'kind':'weapon','weight_lb':1,'cube_ft':1,'flags':{'prerequisites_met':1},'properties':[]}})
    bundle=compile_character(doc,actor_id=OWNER,owner_items=store.items(PID),reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path/'fight',[],owner_bundle=bundle,cl=10,primary='Stamina',
        foe_position={'x':4,'y':6},ally_position={'x':3,'y':7},named=True)
    engine=combat._load_session(mid).engine
    if stow_other:
        stow=next(c for c in engine.legal_candidates() if c.display_name.startswith('Stow Heron Grip Knife'))
        settle(table,mid,stow.candidate_id)
        engine=combat._load_session(mid).engine
    sweep=next(c for c in engine.legal_candidates() if c.display_name.startswith('Crescent Reaping Circle'))
    sweep_action=engine.action_catalog[sweep.source_definition_id]
    base=engine.action_catalog[sweep_action.parameters['typed']['attack_line_of']]
    expected=versatile_die_sides(engine,engine.state.actors[OWNER],base) or base.parameters['typed']['weapon']['damage']['sides']
    settle(table,mid,sweep.candidate_id,choices=choices(reaping_circle_rider=['deny'],reaping_circle_move=None,heron_damage_type=['FORCE']))
    engine=cold(tmp_path,mid,'reaping-current-grip-'+str(stow_other))
    root=[r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.expression.startswith('1d')]
    assert root and any(r.expression.startswith('1d'+str(expected)) for r in root)
    assert any(r.expression.startswith('3d8') for r in engine.rolls)


def _capture_moon_entry_policy(root,kind):
    from pathlib import Path
    import json,pytest
    from combat.gate5_service import CombatService
    from combat.factory_compiler import compile_character
    from tests.h1_support import ROOT
    from tests.worker2_support import fixture,turn,settle,candidate,OWNER,ALLY,FOE
    from tests.hunt12_support import hit_dice
    from tests.test_mgr_t14_white_heron_crescent_body_floor58 import acquired,choices,move
    root=Path(root);forced=kind=='forced'
    guard=ALLY if forced else FOE
    owner_doc=acquired(root/'learning-owner',3 if forced else 14)
    guard_doc=acquired(root/'learning-guard',18)
    maps=CombatService(ROOT,root/'maps')
    admitted=maps.tabletop_maps.save({'display_name':'Native Moon entry policy','width_squares':14,'height_squares':14,
        'walls':[],'objects':[],'starts':{'team1':[[2,4]],'team2':[[4,6]]}})
    arena=maps.factory_arenas()['battlefield:map.'+admitted['map_id']]
    def guard_bundle(bundles):
        bundles[1 if forced else 2]=compile_character(guard_doc,actor_id=guard,reaction_plan={'ask':True})
    places=({OWNER:{'x':2,'y':4},ALLY:{'x':8,'y':6},FOE:{'x':4,'y':6}} if forced else
        {OWNER:{'x':3,'y':4},ALLY:{'x':1,'y':7},FOE:{'x':7,'y':6}})
    service,table,mid=fixture(root/'fight',[],cl=3 if forced else 14,
        owner_bundle=compile_character(owner_doc,actor_id=OWNER,reaction_plan={'ask':True}),
        bundle_transform=guard_bundle,positions=places,battlefield=arena,named=True,seed='HERON-ENTRY-'+kind)
    with pytest.MonkeyPatch.context() as patches:
        hit_dice(patches)
        turn(table,mid,guard)
        pos=places[guard]
        settle(table,mid,candidate(service,mid,'Moon over the Reed Sea',at=(pos['x'],pos['y'])).candidate_id,
            choices=choices(moon_over_the_reed_sea=None))
        turn(table,mid,OWNER)
        move(service,table,mid,2 if forced else 3,6)
        engine=service._load_session(mid).engine
        start=len(engine.events)
        attack=next(c for c in engine.legal_candidates() if FOE in c.target_ids
            and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
            and a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
        settle(table,mid,attack.candidate_id,choices=choices(herons_passing_cut=['push' if forced else 'move'],
            passing_cut_move=['cell:4,6'],heron_polearm_attack='first'))
        loaded=CombatService(ROOT,root/'fight')._load_session(mid)
        replay=loaded.mechanical.replay();assert replay['status']=='PASS'
        engine=loaded.engine
        return {'kind':kind,'guard':guard,'mechanical_replay':replay,
            'guard_attacks':sum(e.event_type=='ATTACK_ROLLED' and e.actor_id==guard for e in engine.events[start:]),
            'state':engine.state.model_dump(mode='json'),'events':[e.model_dump(mode='json') for e in engine.events],
            'rolls':[r.model_dump(mode='json') for r in engine.rolls]}


@pytest.mark.parametrize('kind',['granted_no_oa','forced'])
def test_native_moon_entry_respects_actual_movement_policy_fail_before_and_cold(tmp_path,kind):
    after=_capture_moon_entry_policy(tmp_path/'head',kind)
    (EVIDENCE/('moon-entry-'+kind+'-head.json')).write_text(json.dumps(after,sort_keys=True))
    assert after['mechanical_replay']['status']=='PASS'
    assert after['guard_attacks']==0


def _capture_large_pull(root):
    from pathlib import Path
    import pytest
    from combat.gate5_service import CombatService
    from combat.factory_compiler import compile_character
    from tests.h1_support import ROOT,sheet
    from tests.worker2_support import fixture,OWNER,FOE
    from tests.test_r9i_karma_persistence import act
    from tests.hunt12_support import hit_dice
    from tests.test_mgr_t14_white_heron_crescent_body_floor58 import acquired,move,STAMINA
    root=Path(root)
    owner_doc=acquired(root/'learning',3)
    # An explicit GM-created starting creature profile uses the native Factory
    # size producer. This grants no anatomy or size ability to White Heron.
    opponent=sheet([],cl=3,name='Recorded Large practice opponent')
    opponent['identity']['size']='Large'
    maps=CombatService(ROOT,root/'maps')
    arena=maps.tabletop_maps.save({'display_name':'Native full-space pull','width_squares':14,'height_squares':14,
        'walls':[],'objects':[],'starts':{'team1':[[10,4]],'team2':[[6,6]]}})
    battlefield=maps.factory_arenas()['battlefield:map.'+arena['map_id']]
    service,table,mid=fixture(root/'fight',[],cl=3,foe_sheet=opponent,
        owner_bundle=compile_character(owner_doc,actor_id=OWNER,reaction_plan={'ask':True}),
        positions={OWNER:{'x':10,'y':4},FOE:{'x':6,'y':6},'actor:factory.worker2-ally':{'x':1,'y':1}},
        battlefield=battlefield,named=True,seed='HERON-LARGE-PULL')
    with pytest.MonkeyPatch.context() as patches:
        hit_dice(patches)
        move(service,table,mid,10,6)
        engine=service._load_session(mid).engine
        assert engine.state.actors[FOE].size_category=='Large' and len(engine._actor_cells(engine.state.actors[FOE]))==4
        attack=next(c for c in engine.legal_candidates() if c.target_ids==(FOE,)
            and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
            and a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')
        answers=[];prompts=[]
        for _ in range(25):
            result=act(table,mid,attack.candidate_id,answers)
            if result['status']=='COMMITTED':break
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
            answer={**p['context'],'selection':'USE'}
            if p.get('choice'):
                options=[o['id'] for o in p['choice']['options']]
                if rid=='choice:needle.herons_passing_cut':answer['option_ids']=['pull']
                elif rid=='choice:needle.passing_cut_pull':answer['option_ids']=['cell:7,6' if 'cell:7,6' in options else 'cell:8,6']
                else:answer['option_ids']=[(p['choice'].get('preferred') or options)[0]]
            else:answer['selection']='DECLINE'
            answers.append(answer)
        else:raise AssertionError('Native Large-target pull did not settle.')
        loaded=CombatService(ROOT,root/'fight')._load_session(mid)
        replay=loaded.mechanical.replay();assert replay['status']=='PASS'
        engine=loaded.engine
        return {'opponent_sheet':opponent,'mechanical_replay':replay,'target_x':engine.state.actors[FOE].position.x,
            'paid':30-engine.state.actors[OWNER].resources[STAMINA],'prompts':prompts,
            'state':engine.state.model_dump(mode='json'),'events':[e.model_dump(mode='json') for e in engine.events],
            'rolls':[r.model_dump(mode='json') for r in engine.rolls]}


def test_native_passing_pull_full_target_space_and_five_foot_budget_fail_before_and_cold(tmp_path):
    after=_capture_large_pull(tmp_path/'head')
    (EVIDENCE/'passing-large-pull-head.json').write_text(json.dumps(after,sort_keys=True))
    assert after['mechanical_replay']['status']=='PASS'
    assert after['target_x']==7 and after['paid']==1
    offered=next(p['choice']['options'] for p in after['prompts'] if p['context']['reaction_source_id']=='choice:needle.passing_cut_pull')
    assert 'cell:8,6' not in {o['id'] for o in offered}


def test_native_off_turn_passing_after_actual_paid_pursuit_and_moon_entry(tmp_path,monkeypatch):
    import re
    from tests.hunt12_support import hit_dice
    from tests.worker2_support import ALLY
    from tests.test_r9i_karma_persistence import act
    hit_dice(monkeypatch)
    source=tmp_path/'learning';doc=acquired(source,18)
    source_table=native_table(CombatService(ROOT,source),source)
    source_table.add_advancement(PID,'sphere','tianxia.sphere.athletics')
    source_table.add_advancement(PID,'talent','TAL_ATHLETICS_UNBROKEN_PURSUIT')
    doc=CombatService(ROOT,source)._factory_owner_sheet(PID)
    maps=CombatService(ROOT,tmp_path/'maps')
    admitted=maps.tabletop_maps.save({'display_name':'Native off-turn Passing Cut','width_squares':14,'height_squares':14,
        'walls':[],'objects':[],'starts':{'team1':[[3,6]],'team2':[[9,6]]}})
    combat,table,mid=fixture(tmp_path/'fight',[],cl=18,
        owner_bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True}),
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':1,'y':1},FOE:{'x':9,'y':6}},
        battlefield=maps.factory_arenas()['battlefield:map.'+admitted['map_id']],seed='HERON-OFF-TURN-PASSING')
    settle(table,mid,candidate(combat,mid,'Moon over the Reed Sea',at=(3,6)).candidate_id,
        choices=choices(moon_over_the_reed_sea=None))
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine;before=engine.state.actors[OWNER].resources[STAMINA]
    chosen=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
        and (c.destination.x,c.destination.y,c.destination.z)==(7,6,0))
    answers=[];prompts=[]
    for _ in range(40):
        result=act(table,mid,chosen.candidate_id,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        answer={**p['context'],'selection':'USE'};opts=(p.get('choice') or {}).get('options',[])
        if opts:
            if rid.endswith('unbroken_pursuit'):
                option=next(o for o in opts if re.search(r'5\s*,\s*6\b',o.get('label','')))
                answer['option_ids']=[option['id']]
            elif rid.endswith('herons_passing_cut'):answer['option_ids']=['damage']
            else:answer['option_ids']=[((p['choice'].get('preferred') or [opts[0]['id']])[0])]
        elif rid!='reaction:typed.TAL_ATHLETICS_UNBROKEN_PURSUIT':answer['selection']='DECLINE'
        answers.append(answer)
    else:raise AssertionError('Native off-turn movement failed to settle')
    engine=cold(tmp_path,mid,'passing-off-turn-paid-pursuit-moon')
    owner=engine.state.actors[OWNER]
    assert engine.state.current_actor_id==FOE
    assert owner.resources['resource:core.martial_focus']==0 and not owner.reaction_available
    assert owner.resources[STAMINA]==before-1
    assert any(p['context']['reaction_source_id'].endswith('herons_passing_cut') for p in prompts)
    assert not any(p['context']['reaction_source_id'].endswith('white_wing_move') for p in prompts)
    assert any(r.expression.startswith('3d8') for r in engine.rolls)
    turn(table,mid,OWNER)
    before= combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,choices=choices())
    engine=cold(tmp_path,mid,'passing-off-turn-progress-expired')
    assert engine.state.actors[OWNER].resources[STAMINA]==before
    assert not any(p['context']['reaction_source_id'].endswith('herons_passing_cut') for p in prompts)
