"""Native Restricted Scripture acquisition -> table intent -> cold replay."""
import copy
import json
import zipfile
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_ns1r_r2c_bound_evidence import make
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.ns1r_evidence_helpers import access_evidence, commit_authority_event

BASE='tianxia.subpath.body.still_water_draw_body'
PREFIX=BASE+'.feature.'
BODY='tianxia.path.body_refining'
ME,FOE='actor:factory.water','actor:factory.guard'
STAMINA='resource:core.stamina'

@pytest.fixture(scope='module', autouse=True)
def acquisition_cache(tmp_path_factory):
    # Acquisition is immutable input to each fight. Build each source variant
    # once, then give every test a private copy of the exported documents.
    acquired.cache = {}
    acquired.root = tmp_path_factory.mktemp('still-water-acquisition')
    yield
    acquired.cache = {}


def acquired(tmp_path,cl=18,recorded='jian',project='water'):
    key = (cl, recorded, project)
    if key in acquired.cache:
        return copy.deepcopy(acquired.cache[key])
    tmp_path = acquired.root / str(len(acquired.cache))
    svc,db=make(tmp_path/'authority')
    insert_project(db,project,cl)
    svc.initialize_for_project(project,target_cl=cl,path_ids=[BODY],method_id='METHOD-002',
        path_attainment_by_id={BODY:cl},access_source_records=access_evidence(db,svc,project,'METHOD-002'))
    access=commit_authority_event(db,svc,project,'subpath_access',{'path_id':BODY,'selection_id':BASE})
    state=svc.select_subpath(project,BODY,BASE,access_source_records=[access])
    exported=svc.export_state(project);svc.validate_import_payload(project,exported)
    source=exported['state']
    from stage2.ability_changes import published_path_records
    progression = published_path_records()[BODY]['compatibility']['factory']['stage2_authority']['progression_by_cl']
    fields={'paths':source['paths'],
            'path_record_ids':[row['path_id'] for row in source['paths'] if row.get('attainment',0)>0],
            'subpath_record_ids':[BASE],
            'path_feature_record_ids':[feature for level, row in progression.items() if int(level)<=cl
                                       for feature in row.get('feature_record_ids', [])]}
    from combat.subpath_acquisition import acquired_features
    fields['source_granted_subpath_feature_record_ids']=sorted(acquired_features(
        {'path_and_subpath':fields,'identity':{'cultivation_level':cl}},ROOT))
    assert len(fields['source_granted_subpath_feature_record_ids'])==sum(level<=cl for level in (3,6,10,14,18))
    doc=sheet([],cl=cl,primary='Stamina',kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.weapon.'+i} for i in ('dao','jian','fu')]}})
    pb=2+(cl-1)//4
    doc['identity'].update(path='Body Refining',proficiency_bonus=pb,key_ability='CON')
    doc['ability_scores_and_statistics'].update(hit_points={'maximum':240},technique_attack_bonus=pb+2,technique_save_dc=10+pb)
    doc['path_and_subpath']={**fields,'still_water_draw_weapon':recorded}
    acquired.cache[key] = (doc, exported)
    return copy.deepcopy(acquired.cache[key])


def send(ui,mid,select,picks=None,at=None):
    state=ui.state(mid);menu=state['menu']
    if select=='end':cid=menu['end_turn']
    else:
        group=next(g for g in menu['actions'] if select(g))
        option=next((o for o in group['options'] if at is None or o.get('destination')=={'x':at[0],'y':at[1]}),group['options'][0])
        cid=option['candidate_id']
    answers=[];prompts=[]
    for _ in range(40):
        result=ui.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            return prompts
        p=result['reaction'];prompts.append(p);choice=p.get('choice') or {};ctx=p['context']
        requested=next((v for k,v in (picks or {}).items() if ctx['reaction_source_id'].endswith(k)),'DEFAULT')
        if callable(requested):requested=requested(p,prompts)
        if at is not None and ctx['reaction_source_id']=='choice:placement_menu.square':
            offered={o['id'] for o in choice.get('options',[])}
            requested=[next(k for k in (f'cell:{at[0]},{at[1]},0',f'cell:{at[0]},{at[1]}') if k in offered)]
        if ctx['reaction_source_id']=='choice:needle.still_water_draw_weapon' and requested not in ('DEFAULT',None):
            selected=[o['id'] for o in choice.get('options',[]) if any(o['id'].endswith('.weapon.'+value) for value in requested)]
            assert len(selected)==len(requested),choice
            requested=selected
        if ctx['reaction_source_id']=='choice:needle.held_weapon_impairment' and requested not in ('DEFAULT',None):
            wanted=requested[0]
            requested=[o['id'] for o in choice.get('options',[]) if o['label'].startswith(wanted)]
            assert len(requested)==1,choice
        if requested=='DEFAULT':
            use=not choice.get('allow_decline',True)
            selected=[o['id'] for o in (choice.get('options') or [])[:max(1,choice.get('minimum',1))]] if use else []
        else:use=requested is not None;selected=list(requested or [])
        answers.append({**ctx,'selection':'USE' if use else 'DECLINE','option_ids':selected,'spend':0})
    raise AssertionError('too many choices')


def turn(ui,mid,actor,picks=None):
    for _ in range(6):
        if ui.state(mid)['menu']['actor_id']==actor:return
        send(ui,mid,'end',picks)
    raise AssertionError('no turn')


def table(tmp_path,cl=18,recorded='jian',foe_at=(4,6),picks=None,objects=(),journey=False,foe_body=False):
    doc,exported=acquired(tmp_path,cl,recorded)
    foe=sheet([],cl=18,primary='Stamina',kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.dao'}]}})
    if foe_body:
        foe,_=acquired(tmp_path/'guard-source',recorded='dao',project='guard')
    foe['ability_scores_and_statistics'].update(hit_points={'maximum':120},armor_class={'base_value':1})
    for pid,d in [('water',doc),('guard',foe)]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(d))
    service=CombatService(ROOT,tmp_path)
    # Only x=1..12, y=6 are used by these scenarios.  A compact yard keeps
    # the real table's exhaustive destination menus from scaling with empty map.
    service.tabletop_maps.save({'display_name':'Still Water Native Yard','width_squares':13,'height_squares':8,
        'walls':[],'objects':list(objects),'starts':{'team1':[[3,6]],'team2':[list(foe_at)]}})
    if journey:
        state=service.create_journey(project_ids=['water','guard'],arena_id='battlefield:map.still-water-native-yard',
            positions={ME:{'x':3,'y':6},FOE:{'x':foe_at[0],'y':foe_at[1]}},
            base_paces={ME:3000,FOE:3000},control_modes={ME:'MANUAL',FOE:'MANUAL'})
        jid=state['journey_id']
        mid=service.journey_start_combat(jid,state['revision'],{ME:'team:water',FOE:'team:guard'},maximum_rounds=1)['match_id']
        exported={'acquisition':exported,'journey_id':jid}
    else:
        mid=service.create_factory_match(project_ids=['water'],opponent_actor_ids=[FOE],
            arena_id='battlefield:map.still-water-native-yard',control_modes={ME:'MANUAL',FOE:'MANUAL'},match_seed='WATER58')['match_id']
    ui=TabletopService(service,tmp_path)
    if service._load_session(mid).engine.state.setup_tasks:
        send(ui,mid,lambda g:g['source_definition_id']=='system:combat.fight_setup',picks)
    turn(ui,mid,ME,picks)
    # The third carried item is deliberately not another free hand. Stow the
    # initially readied axe through its real inventory action before drawing Jian.
    if any(g['label'].startswith('Stow Fu ') for g in ui.state(mid)['menu']['actions']):
        send(ui,mid,lambda g:g['label'].startswith('Stow Fu '))
    return service,ui,mid,exported


def cold(tmp_path,mid):
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


def attack(g):return g['label']=='Jian (Straight Sword) attack (Constitution)'


def test_native_recorded_weapon_source_grant_commit_reload(tmp_path):
    _,ui,mid,exported=table(tmp_path)
    labels={g['label'] for g in ui.state(mid)['menu']['actions']}
    assert 'Jian (Straight Sword) attack (Constitution)' in labels
    assert 'Dao (Saber / Broadsword) attack (Constitution)' not in labels
    assert not any('Short Axe' in l and '(Constitution)' in l for l in labels)
    assert exported['evidence_ledger']['evidence']
    prompts=send(ui,mid,attack,{'first_cut':['force'],'first_cut_move':['cell:2,6']})
    assert any(p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].position.x==2
    assert any(x.event_type=='DAMAGE_COMMITTED' and x.actor_id==ME and x.payload['damage_type'].upper()=='FORCE' for x in e.events)


def test_native_empty_scabbard_committed_reaction_reload(tmp_path):
    _,ui,mid,_=table(tmp_path);turn(ui,mid,FOE)
    prompts=send(ui,mid,lambda g:g['label']=='Dao (Saber / Broadsword) attack',{'empty_scabbard_use':['use'],'empty_scabbard_step':['cell:1,6']})
    e=cold(tmp_path,mid)
    assert any(p['context']['reaction_source_id'].endswith('empty_scabbard_use') for p in prompts)
    assert e.state.actors[ME].resources[STAMINA]==29
    assert e.state.actors[ME].position.x==1
    assert not any(x.event_type=='ATTACK_ROLLED' and x.actor_id==FOE for x in e.events)


def test_native_one_breath_source_grant_line_reload(tmp_path):
    _,ui,mid,_=table(tmp_path)
    # This is a nonattack technique: the weapon must actually be ready; the
    # attack-only draw permission cannot stand in for a native Draw command.
    send(ui,mid,lambda g:g['label'].startswith('Draw Jian '))
    ready=cold(tmp_path,mid)
    from combat.ext.hand_occupancy import weapon_allowed
    line=next(a for a in ready.action_catalog.values() if a.owner_id==ME
        and a.display_name.startswith('One Breath, Three Horizons (Jian'))
    assert weapon_allowed(ready,ready.state.actors[ME],line) is True
    assert not line.parameters['typed'].get('weapon')
    wrong=line.model_copy(update={'owner_id':FOE})
    assert weapon_allowed(ready,ready.state.actors[ME],wrong) is False
    broken=line.model_copy(update={'parameters':{**line.parameters,'weapon_grip_from_action':'missing'}})
    assert weapon_allowed(ready,ready.state.actors[ME],broken) is False
    plain=line.model_copy(update={'parameters':{k:v for k,v in line.parameters.items() if k!='weapon_grip_from_action'}})
    assert weapon_allowed(ready,ready.state.actors[ME],plain) is False
    prompts=send(ui,mid,lambda g:g['label'].startswith('One Breath, Three Horizons (Jian'),
        {'still_water_horizons_type':['force']},at=(8,6))
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].resources[STAMINA]==28
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)
    assert not any(x.event_type=='ATTACK_ROLLED' and x.actor_id==ME for x in e.events)
    assert not any(p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)
    assert any(x.event_type=='DAMAGE_COMMITTED' and x.actor_id==ME and x.payload['damage_type']=='FORCE' for x in e.events)
    assert not any(g['label'].startswith('One Breath') for g in ui.state(mid)['menu']['actions'])


def test_native_moon_turn_boundary_attack_reload(tmp_path):
    _,ui,mid,_=table(tmp_path,picks={'still_water_posture':['enter']})
    prompts=send(ui,mid,attack,{'still_water_posture':['enter'],'first_cut':['force']})
    e=cold(tmp_path,mid)
    assert any(x.event_type=='CONDITION_APPLIED' and x.source_definition_id==PREFIX+'moon_reflected_before_motion' for x in e.events)
    attacks=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME]
    assert attacks and attacks[0].payload['mode']=='ADVANTAGE'
    assert not any(c.condition_id.endswith('still_water_posture') for c in e.state.actors[ME].conditions.values())
    assert e._effective_speed(e.state.actors[ME])==30


def test_native_heaven_source_grant_scene_reload(tmp_path):
    _,ui,mid,_=table(tmp_path,foe_at=(6,6))
    send(ui,mid,lambda g:g['label'].startswith('Heaven Divided Before Sound'),{'heaven_divided_targets':[FOE]},at=(10,6))
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].resources[STAMINA]==23
    assert any(x.event_type=='MOVEMENT_COMMITTED' and x.actor_id==ME for x in e.events)
    assert any(r.expression.startswith('6d8') for r in e.rolls)
    assert any(x.event_type=='ATTACK_ROLLED' and x.actor_id==ME and FOE in x.target_ids for x in e.events)
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)
    turn(ui,mid,FOE);send(ui,mid,'end');turn(ui,mid,ME)
    assert not any(g['label'].startswith('Heaven Divided') for g in ui.state(mid)['menu']['actions'])


def test_body_attainment_boundary_and_default_inert(tmp_path):
    doc,_=acquired(tmp_path,6);doc['identity']['cultivation_level']=20
    doc['path_and_subpath']['source_granted_subpath_feature_record_ids'] += [PREFIX+'moon_reflected_before_motion',PREFIX+'heaven_divided_before_sound']
    b=compile_character(doc,actor_id=ME)
    profile=next(a['parameters']['still_water_profile'] for a in b['action_catalog'] if a['parameters'].get('still_water_profile'))
    assert profile['body_cl']==6
    unrelated=compile_character(sheet([],cl=20),actor_id=FOE)
    assert not any(a.get('parameters',{}).get('still_water_profile') for a in unrelated['action_catalog'])


def test_native_unrecorded_binding_is_player_owned_and_cold_persisted(tmp_path):
    _,ui,mid,_=table(tmp_path,recorded='',picks={'still_water_draw_weapon':['jian']})
    e=cold(tmp_path,mid)
    bindings=[c for c in e.state.actors[ME].conditions.values()
              if c.condition_id=='condition:typed.still_water_draw_weapon']
    assert len(bindings)==1
    assert bindings[0].source_definition_id==PREFIX+'drawn_from_stillness'
    assert bindings[0].source_actor_id==ME and bindings[0].data['item']=='jian'
    labels={g['label'] for g in ui.state(mid)['menu']['actions']}
    assert 'Jian (Straight Sword) attack (Constitution)' in labels
    assert not any(l.startswith('Draw Weapon: choose') for l in labels)
    assert 'Dao (Saber / Broadsword) attack (Constitution)' not in labels
    # The persisted bind survives a real direct-fight attack and another cold load.
    send(ui,mid,attack,{'first_cut':['force']})
    fought=cold(tmp_path,mid)
    assert any(x.event_type=='ATTACK_ROLLED' and x.actor_id==ME for x in fought.events)
    assert any(c.condition_id=='condition:typed.still_water_draw_weapon'
        and c.data['item']=='jian' for c in fought.state.actors[ME].conditions.values())


def test_native_unrelated_attacker_has_no_draw_riders(tmp_path):
    _,ui,mid,_=table(tmp_path)
    turn(ui,mid,FOE)
    prompts=send(ui,mid,lambda g:g['label']=='Dao (Saber / Broadsword) attack')
    e=cold(tmp_path,mid)
    assert not any(p['context']['reactor_id']==FOE and p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)
    assert not any(c.condition_id=='condition:typed.still_water_draw_weapon' for c in e.state.actors[FOE].conditions.values())
    assert not any(r.get('block')=='still_water_profile' for r in e.typed_passive_rows.get(FOE,[]))
    assert not any(a.owner_id==FOE and a.display_name.startswith('Draw Weapon: choose')
        for a in e.action_catalog.values())



@pytest.mark.parametrize("hp", [5, 999])
def test_native_heaven_barrier_before_unseen_destination_commit_reload(tmp_path, hp):
    _,ui,mid,_=table(tmp_path,foe_at=(12,6),objects=[
        {"id":1,"kind":"crate","x":5,"y":6,"hp":hp,"ac":1,"blocks":True}])
    send(ui,mid,lambda g:g['label'].startswith('Heaven Divided Before Sound'),at=(10,6))
    e=cold(tmp_path,mid)
    obj=e.state.objects['object:map.1']
    assert any(x.event_type=='ATTACK_ROLLED' and x.target_ids==(obj.object_id,) for x in e.events)
    assert bool(obj.destroyed)==(hp==5)
    assert e.state.actors[ME].position.x==(10 if hp==5 else 4)
    assert e.state.actors[ME].resources[STAMINA]==23


def test_native_heaven_traverse_is_bounded_when_a_step_never_finishes(monkeypatch):
    """A re-entrant step that keeps extending its route must fail, not spin forever."""
    from types import SimpleNamespace
    from combat.ext import rider_movement, still_water
    from combat.gate2_runtime_models import Position

    calls=[]
    class Grid:
        square_size_ft=5
        def volume_step_legal(self,*args,**kwargs):
            return True
    engine=SimpleNamespace(
        state=SimpleNamespace(terminal_result=None,actors={}),
        grid=Grid(),_effective_speed=lambda actor:30,_footprint=lambda actor:None,
        _actor_volume=lambda actor:((0,0,0),))
    actor=SimpleNamespace(entity_id=ME,active=True,position=Position(x=0,y=0,z=0))
    def runaway(engine,actor,path,source,record_willing=True):
        calls.append(tuple(path))
        assert len(calls)<=20,'heaven traversal did not bound its re-entrant route'
        frame=still_water._HEAVEN_ROUTE.get()
        frame['cursor']+=1
        actor.position=path[-1]
        frame['line'].append(Position(x=len(frame['line']),y=0,z=0))
    monkeypatch.setattr(rider_movement,'step',runaway)
    line=[Position(x=index,y=0,z=0) for index in range(3)]
    walked=still_water._native_heaven_traverse(
        SimpleNamespace(engine=engine,actor=actor),line,[],{},None,0)
    assert walked==[Position(x=0,y=0,z=0)]
    assert 0<len(calls)<10


def test_native_draw_object_profiles_are_available_to_ai_only_when_owned(tmp_path):
    from combat.gate4_context import build_decision_context
    from combat.gate4_models import LocalControllerPolicy
    _,ui,mid,_=table(tmp_path,objects=[
        {"id":1,"kind":"crate","x":4,"y":5,"hp":30,"ac":10,"blocks":False}])
    engine=cold(tmp_path,mid)
    ai=build_decision_context(engine,LocalControllerPolicy(
        policy_id="test-local",policy_version="1",role=("frontline",),
        preferred_range_bands_ft=((0,5),),target_priorities={},action_priorities={},
        resource_reserves={},reaction_rules={},ally_companion_priorities={},
        low_hp_behavior={},prohibited_choices=(),weights={}),for_ai=True)
    candidates=[c for c in ai.legal_candidates if "still_water_object" in c.source_definition_id]
    assert candidates
    unrelated=compile_character(sheet([],cl=18),actor_id="actor:factory.unrelated")
    assert not any(a.get("parameters",{}).get("still_water_object") for a in unrelated["action_catalog"])


@pytest.mark.parametrize('recorded', ['fu', 'zhan_ma_dao'])
def test_native_invalid_or_unavailable_recorded_item_cannot_rebind(tmp_path, recorded):
    _,ui,mid,_=table(tmp_path,recorded=recorded)
    labels={g['label'] for g in ui.state(mid)['menu']['actions']}
    assert not any(l.startswith('Draw Weapon: choose') for l in labels)
    assert not any(l.startswith(('One Breath, Three Horizons', 'Heaven Divided Before Sound')) for l in labels)
    assert 'Jian (Straight Sword) attack (Constitution)' not in labels
    assert 'Dao (Saber / Broadsword) attack (Constitution)' not in labels
    send(ui,mid,'end');turn(ui,mid,FOE);send(ui,mid,'end');turn(ui,mid,ME)
    send(ui,mid,lambda g:g['label'].startswith('Draw Jian '))
    send(ui,mid,lambda g:g['label']=='Jian (Straight Sword) attack')
    e=cold(tmp_path,mid)
    assert not any(x.source_definition_id==PREFIX+'drawn_from_stillness' and x.event_type=='DAMAGE_COMMITTED' for x in e.events)
    assert not any(c.condition_id=='condition:typed.still_water_draw_weapon' for c in e.state.actors[ME].conditions.values())


def test_native_draw_and_sheath_same_item_commit_reload(tmp_path):
    _,ui,mid,_=table(tmp_path)
    prompts=send(ui,mid,attack,{'draw_weapon_sheath':['sheath']})
    assert any(p['context']['reaction_source_id'].endswith('draw_weapon_sheath') for p in prompts)
    e=cold(tmp_path,mid)
    from combat.ext.hand_occupancy import weapon_grips
    from combat.weapon_delivery import weapon_identity
    base=next(a for a in e.action_catalog.values() if a.owner_id==ME and a.display_name=='Jian (Straight Sword) attack')
    identity=weapon_identity(e,base.source_definition_id,base.parameters['typed'],base.parameters)
    assert identity not in weapon_grips(e,e.state.actors[ME])
    # The source has not created or substituted another carried item.
    from combat.carry import carrying_of
    assert {i['item_id'] for i in carrying_of(e,ME)['items']}=={
        'tianxia.mortal.weapon.dao','tianxia.mortal.weapon.jian','tianxia.mortal.weapon.fu'}


def test_native_human_scabbard_choice_on_local_ai_turn_commits_and_replays(tmp_path):
    service,ui,mid,_=table(tmp_path)
    turn(ui,mid,FOE)
    service.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    offered=[]
    # Local Auto may first improve its position. Continue its real committed
    # turn until it actually declares its melee attack; do not fabricate one.
    for _step in range(8):
        state=ui.state(mid);menu=state['menu'];answers=[]
        assert menu['actor_id']==FOE
        for _ in range(40):
            result=ui.auto_step(mid,state['last_sequence'],answers,menu['decision_id'],menu['state_version'])
            if result['status']!='REACTION_REQUIRED':
                assert result['status']=='COMMITTED',result
                break
            p=result['reaction'];ctx=p['context'];choice=p.get('choice') or {}
            offered.append(ctx['reaction_source_id'])
            if ctx['reaction_source_id'].endswith('empty_scabbard_use'):
                selected=['use']
            elif ctx['reaction_source_id'].endswith('empty_scabbard_step'):
                selected=['cell:1,6']
            else:
                selected=[] if choice.get('allow_decline',True) else [choice['options'][0]['id']]
            answers.append({**ctx,'selection':'USE' if selected else 'DECLINE','option_ids':selected,'spend':0})
        else:raise AssertionError('local AI did not finish its source choices')
        if any(key.endswith('empty_scabbard_step') for key in offered):break
    else:raise AssertionError('local AI never committed a melee attack this turn')
    assert any(s.endswith('empty_scabbard_use') for s in offered)
    assert any(s.endswith('empty_scabbard_step') for s in offered)
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].position.x==1
    assert e.state.actors[ME].resources[STAMINA]==29


def test_owned_body_dc_and_cam_ignore_foreign_global_key_numbers(tmp_path):
    doc,_=acquired(tmp_path)
    doc['identity']['key_ability']='INT'
    doc['ability_scores_and_statistics'].update(technique_attack_bonus=77,technique_save_dc=85)
    bundle=compile_character(doc,actor_id=ME)
    guarded=[a for a in bundle['action_catalog'] if a.get('parameters',{}).get('integrated_selection_source')==PREFIX+'drawn_from_stillness']
    assert guarded and all(a['parameters']['typed']['numbers']['attack_bonus']==8 for a in guarded)
    line=next(a for a in bundle['action_catalog'] if a['display_name'].startswith('One Breath, Three Horizons (Jian'))
    assert line['parameters']['typed']['numbers']['save_dc']==16


def test_native_scene_use_survives_encounters_rest_and_only_owner_scene_end_restores(tmp_path):
    service,ui,mid,proof=table(tmp_path,journey=True,foe_at=(12,6))
    jid=proof['journey_id']
    send(ui,mid,lambda g:g['label'].startswith('Heaven Divided Before Sound'),at=(10,6))
    cold(tmp_path,mid)
    for _ in range(8):
        if service._load_session(mid).engine.state.terminal_result is not None:break
        send(ui,mid,'end')
    else:raise AssertionError('first bounded encounter did not finish')
    state=service.journey_state(jid)
    state=service.journey_resume(jid,state['revision'])
    spent=state['actors'][ME]['resources'][STAMINA]
    assert spent==23
    second=service.journey_start_combat(jid,state['revision'],{ME:'team:water',FOE:'team:guard'},maximum_rounds=1)['match_id']
    ui=TabletopService(service,tmp_path)
    if service._load_session(second).engine.state.setup_tasks:
        send(ui,second,lambda g:g['source_definition_id']=='system:combat.fight_setup')
    turn(ui,second,ME)
    assert not any(g['label'].startswith('Heaven Divided Before Sound') for g in ui.state(second)['menu']['actions'])
    for _ in range(8):
        if service._load_session(second).engine.state.terminal_result is not None:break
        send(ui,second,'end')
    else:raise AssertionError('second bounded encounter did not finish')
    cold(tmp_path,second)
    state=service.journey_state(jid);state=service.journey_resume(jid,state['revision'])
    state=service.journey_act(jid,state['revision'],ME,'long_rest')
    use_pools={pool for a in state['actors'][ME]['bundle']['action_catalog']
        if a.get('parameters',{}).get('typed',{}).get('source')==PREFIX+'heaven_divided_before_sound'
        for pool,cost in a.get('costs',[]) if pool.startswith('resource:uses.')}
    assert len(use_pools)==1
    pool=next(iter(use_pools));assert state['actors'][ME]['resources'][pool]==0
    after=service.journey_end_scene(jid,state['revision'],'The pursuit ends; the table begins a new scene.')
    assert after['actors'][ME]['resources'][pool]==1
    assert after['actors'][ME]['resources'][STAMINA]==spent
    assert CombatService(ROOT,tmp_path).journey_state(jid)==after
    assert any(e['kind']=='SCENE_ENDED' for e in after['events'])
    assert any(e['kind']=='SOURCE_SCENE_USE_RESTORED' for e in after['events'])


def test_native_scabbard_stay_after_dodge_miss_grants_exactly_one_draw_attack(tmp_path):
    _,ui,mid,_=table(tmp_path)
    send(ui,mid,lambda g:g['source_definition_id']=='system:combat.dodge')
    turn(ui,mid,FOE)
    prompts=send(ui,mid,lambda g:g['label']=='Dao (Saber / Broadsword) attack',
        {'empty_scabbard_use':['use'],'empty_scabbard_step':None,'first_cut':['force']})
    e=cold(tmp_path,mid)
    incoming=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==FOE]
    counters=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME]
    assert incoming and incoming[-1].payload['provisional_hit'] is False
    assert len(counters)==1
    assert e.state.actors[ME].resources[STAMINA]==29
    assert e.events.index(counters[0])>e.events.index(incoming[-1])
    assert any(p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)


def test_body_dormant_attainment_does_not_activate_but_explicit_effective_cl_is_authoritative(tmp_path):
    doc,_=acquired(tmp_path)
    row=next(r for r in doc['path_and_subpath']['paths'] if r['path_id']==BODY)
    row['status']='DORMANT'
    b=compile_character(doc,actor_id=ME)
    profile=next(r for r in b['typed_passives'] if r.get('block')=='still_water_profile')
    assert profile['body_cl']==0
    row['effective_cl']=6
    b=compile_character(doc,actor_id=ME)
    profile=next(r for r in b['typed_passives'] if r.get('block')=='still_water_profile')
    assert profile['body_cl']==6


def test_native_preroll_geometry_miss_settles_exact_posture_and_scabbard_watch(tmp_path):
    _,ui,mid,_=table(tmp_path,foe_body=True,picks={'still_water_posture':['enter']})
    send(ui,mid,attack,{'empty_scabbard_use':['use'],'empty_scabbard_step':['cell:6,6']})
    e=cold(tmp_path,mid)
    assert not any(x.event_type=='ATTACK_ROLLED' for x in e.events)
    assert e.state.actors[FOE].resources[STAMINA]==29
    assert e.state.actors[FOE].position.x==6
    assert '_scabbard_watch' not in e.state.actors[FOE].turn_flags
    assert not any(c.condition_id.endswith('still_water_posture') for c in e.state.actors[ME].conditions.values())
    assert e._effective_speed(e.state.actors[ME])==30


def test_native_draw_weapon_object_attack_packets_and_posture_reload(tmp_path):
    _,ui,mid,_=table(tmp_path,foe_at=(8,6),objects=[{'id':1,'kind':'crate','x':4,'y':6,'hp':200,'ac':1}],
        picks={'still_water_posture':['enter']})
    prompts=send(ui,mid,lambda g:g['label']=='Draw Weapon object attack: Jian (Straight Sword) (Constitution)',
        {'first_cut':['force'],'still_water_posture_type':['force'],
         'still_water_weapon_damage_type':['FORCE'],'draw_weapon_sheath':['sheath']})
    e=cold(tmp_path,mid)
    attacks=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME]
    assert attacks and attacks[0].payload['mode']=='ADVANTAGE'
    assert e.state.objects['object:map.1'].current_hp<200
    assert any(p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)
    assert any(p['context']['reaction_source_id'].endswith('still_water_posture_type') for p in prompts)
    assert not any(c.condition_id.endswith('still_water_posture') for c in e.state.actors[ME].conditions.values())
    assert e._effective_speed(e.state.actors[ME])==30
    assert not any(x.event_type=='SAVE_ROLLED' and x.actor_id=='object:map.1' for x in e.events)


def test_native_same_type_first_cut_is_in_primary_packet(tmp_path):
    _,ui,mid,_=table(tmp_path)
    send(ui,mid,attack,{'first_cut':['force'],'still_water_weapon_damage_type':['FORCE']})
    e=cold(tmp_path,mid)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==ME and FOE in x.target_ids]
    assert len(packets)==1 and packets[0].payload['damage_type']=='FORCE'
    assert not any(x.source_definition_id==PREFIX+'drawn_from_stillness' for x in packets)
    rolled=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.actor_id==ME and FOE in x.target_ids]
    # Constitution (+2) plus First Cut's Proficiency Bonus (+6), exactly once.
    assert len(rolled)==1 and rolled[0].payload['modifier']==8


def test_native_heaven_first_cut_along_original_line_continues_to_destination(tmp_path):
    _,ui,mid,_=table(tmp_path,foe_at=(6,6))
    send(ui,mid,lambda g:g['label'].startswith('Heaven Divided Before Sound'),
        {'heaven_divided_targets':[FOE],'first_cut':['force'],'first_cut_move':['cell:7,6']},at=(10,6))
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].position.x==10
    assert len([x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME])==1
    assert len([r for r in e.rolls if r.expression.startswith('6d8')])==1
    assert len([x for x in e.events if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE])==1


def test_native_one_breath_can_replace_two_slots_after_an_earlier_attack(tmp_path):
    _,ui,mid,_=table(tmp_path)
    send(ui,mid,lambda g:g['label'].startswith('Draw Jian '))
    def after_first(_prompt,history):
        visits=sum(p['context']['reaction_source_id']=='choice:needle.still_water_horizons_replace' for p in history)
        return ['replace'] if visits==2 else None
    prompts=send(ui,mid,attack,{'still_water_horizons_replace':after_first,
        'still_water_horizons_aim':['cell:8,6'],'still_water_horizons_type':['force'],'first_cut':['force']})
    e=cold(tmp_path,mid)
    attacks=[x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME]
    saves=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE]
    assert len(attacks)==2 and len(saves)==1
    assert e.events.index(attacks[0])<e.events.index(saves[0])<e.events.index(attacks[1])
    assert e.state.actors[ME].resources[STAMINA]==28
    assert e.state.actors[ME].turn_flags.get('special_attack_rest',0)==0
    assert not any('rest of the Attack action' in g['label'] for g in ui.state(mid)['menu']['actions'])
    assert sum(p['context']['reaction_source_id'].endswith('first_cut') for p in prompts)==1


def test_native_one_breath_exact_remaining_slots_keep_other_weapon_distinct(tmp_path):
    _,ui,mid,_=table(tmp_path)
    send(ui,mid,lambda g:g['label'].startswith('Draw Jian '))
    send(ui,mid,lambda g:g['label'].startswith('One Breath, Three Horizons (Jian'),
        {'still_water_horizons_type':['force']},at=(8,6))
    before=cold(tmp_path,mid)
    assert before.state.actors[ME].turn_flags['special_attack_rest']==2
    p1=send(ui,mid,lambda g:g['label']=='Dao (Saber / Broadsword) attack (rest of the Attack action)',{'first_cut':['force']})
    p2=send(ui,mid,lambda g:g['label']=='Jian (Straight Sword) attack (Constitution) (rest of the Attack action)',{'first_cut':['force']})
    e=cold(tmp_path,mid)
    assert len([x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==ME])==2
    assert e.state.actors[ME].turn_flags['special_attack_rest']==0
    assert e.state.actors[ME].resources[STAMINA]==28
    assert not any(p['context']['reaction_source_id'].endswith('first_cut') for p in p1+p2)
    assert not any('rest of the Attack action' in g['label'] for g in ui.state(mid)['menu']['actions'])


def test_heaven_uses_actual_draw_profile_after_journey_acquisition(tmp_path):
    _,ui,mid,_=table(tmp_path,recorded='dao',foe_at=(6,6),journey=True)
    send(ui,mid,lambda g:g['label'].startswith('Heaven Divided Before Sound'),
        {'heaven_divided_targets':[FOE],'first_cut_move':None},at=(10,6))
    e=cold(tmp_path,mid)
    assert any(x.event_type=='ATTACK_ROLLED' and x.actor_id==ME and FOE in x.target_ids for x in e.events)
    assert any(r.expression.startswith('6d8') for r in e.rolls)
    assert e.state.actors[ME].resources[STAMINA]==23
