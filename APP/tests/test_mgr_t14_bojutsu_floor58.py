"""Bojutsu native learning -> table commit -> cold mechanical replay."""
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
SCHOOL='tianxia.subpath.body.bojutsu'
PREFIX=SCHOOL+'.feature.'
FEATURES=['staff_form','flowing_spin','sweeping_strike','staff_of_one','heavenly_staff_barrier']
PID='0badc0de-0000-4000-8000-000000000058'
STAFF='tianxia.mortal.weapon.gun'
KIT={'starting_kit':{'items':[{'item_id':STAFF}]}}


@lru_cache(maxsize=1)
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def native_table(combat,tmp_path):
    table=TabletopService(combat,tmp_path)
    table.canonical_catalog=catalog()
    return table


def acquired(tmp_path,cl=18,path='Body Refining'):
    doc=sheet([],cl=cl,primary='Stamina',kit=KIT,dc=50)
    doc['identity']['path']=path
    doc['identity']['name']='Staff practitioner'
    doc['identity']['path_ids']=['tianxia.path.body_refining'] if path=='Body Refining' else ['tianxia.path.qi_cultivation']
    doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
    folder=tmp_path/'portable_characters'/PID;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    table.add_advancement(PID,'subpath',SCHOOL)
    return CombatService(ROOT,tmp_path)._factory_owner_sheet(PID)


def game(tmp_path,cl=18,**kwargs):
    doc=acquired(tmp_path/'learning',cl)
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    return fixture(tmp_path/'fight',[],owner_bundle=bundle,owner_path='Body Refining',primary='Stamina',
        owner_kit=KIT,cl=cl,seed='BOJUTSU58',foe_position=kwargs.pop('foe_position',{'x':4,'y':6}),
        ally_position={'x':3,'y':7},named=True,**kwargs)


@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_progression_cold(tmp_path,cl,count):
    doc=acquired(tmp_path,cl)
    ids=doc.get('path_and_subpath',{}).get('path_feature_record_ids',[])
    assert [mid for mid in ids if mid.startswith(PREFIX)]==[PREFIX+f for f in FEATURES[:count]]
    assert not doc.get('spheres_and_talents',{}).get('sphere_record_ids')


def test_native_acquisition_rejects_wrong_path(tmp_path):
    from combat.tabletop_service import TabletopError
    with pytest.raises((ValueError,TabletopError)):
        acquired(tmp_path,path='Qi Cultivation')


def test_native_flow_commit_cold_reload(tmp_path):
    combat,table,mid=game(tmp_path,6)
    engine=combat._load_session(mid).engine
    assert not any('Flowing Spin' in engine.action_catalog[c.source_definition_id].display_name
        for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    settle(table,mid,candidate(combat,mid,'Gun (Staff) attack').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert any(c.condition_id=='condition:typed.bojutsu_staff_attack_action' for c in engine.state.actors[OWNER].conditions.values())
    before=engine.state.actors[OWNER].resources['resource:core.stamina'];start=len(engine.events)
    settle(table,mid,candidate(combat,mid,'Flowing Spin: Gun (Staff) attack').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert engine.state.actors[OWNER].resources['resource:core.stamina']==before-1
    assert len([e for e in engine.events[start:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==1


def test_native_staff_stow_dormancy_commit_reload(tmp_path):
    combat,table,mid=game(tmp_path,14)
    engine=combat._load_session(mid).engine
    ac=engine._ac_modifier(engine.state.actors[OWNER])
    settle(table,mid,candidate(combat,mid,'Stow Gun (Staff) (frees 1 hand; no Action)').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert engine._ac_modifier(engine.state.actors[OWNER])==ac-1
    settle(table,mid,candidate(combat,mid,'Draw Gun (Staff) (uses 1 hand; no Action)').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert engine._ac_modifier(engine.state.actors[OWNER])==ac


@pytest.mark.parametrize('rider',['Push 10 feet','No Reactions','Move 10 feet','Gain +1 AC'])
def test_native_barrier_rider_commit_reload(tmp_path,rider):
    combat,table,mid=game(tmp_path)
    settle(table,mid,candidate(combat,mid,'Heavenly Staff Barrier').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert any(c.condition_id=='condition:typed.bojutsu_barrier' for c in engine.state.actors[OWNER].conditions.values())
    # Decline the independent, paid Sweeping Strike to isolate Barrier's result.
    prompts=settle(table,mid,candidate(combat,mid,'Gun (Staff) attack').candidate_id,
        choices={'choice:needle.bojutsu_sweep':None,'choice:needle.bojutsu_barrier_hit':[rider],
            'choice:needle.bojutsu_barrier_step':'first'})
    engine=reload(tmp_path/'fight',mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.bojutsu_ability' for p in prompts)
    assert any(c.condition_id=='condition:typed.bojutsu_barrier_hit_used' for c in engine.state.actors[OWNER].conditions.values())
    actor,target=engine.state.actors[OWNER],engine.state.actors[FOE]
    if rider=='Push 10 feet':
        assert target.position.x>=6
    elif rider=='Move 10 feet':
        assert (actor.position.x,actor.position.y)!=(3,6)
    elif rider=='No Reactions':
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(target))
    else:
        assert any(c.condition_id=='condition:typed.bojutsu_barrier_ac' for c in actor.conditions.values())


def test_public_opportunity_profiles_reject_wrong_owner(tmp_path,monkeypatch):
    from combat import opportunity_choices
    from combat import ext
    combat,table,mid=game(tmp_path)
    engine=combat._load_session(mid).engine
    action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
    monkeypatch.setattr(ext,'run_strict',lambda *args:[[action]])
    with pytest.raises(ValueError,match='reactor'):
        opportunity_choices.profiles(engine,engine.state.actors[OWNER],action)


from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    from tests.test_a2_glass_stock import test_six_stock_captures_equal_main
    monkeypatch.setenv('CF_REPLAY_BASE','224183aa0820a83cee6069328add3c2ad954adfa')
    monkeypatch.setenv('CF_STOCK_EVIDENCE','/var/tmp/auto-audit/fix/MGR-T14-ling-seam-bojutsu-4-evidence/stock')
    test_six_stock_captures_equal_main(tmp_path,seed)


@pytest.mark.parametrize('result',['Prone','Push 10 feet','Reposition within reach','No Reactions'])
def test_native_sweep_paid_save_and_one_result_reload(tmp_path,result):
    combat,table,mid=game(tmp_path,10)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.stamina']
    prompts=settle(table,mid,candidate(combat,mid,'Gun (Staff) attack').candidate_id,
        choices={'choice:needle.bojutsu_sweep':['Use Sweeping Strike'],'choice:needle.bojutsu_result':[result],
            'choice:needle.bojutsu_reposition':'first'})
    engine=reload(tmp_path/'fight',mid)
    assert engine.state.actors[OWNER].resources['resource:core.stamina']==before-1
    assert any(p['context']['reaction_source_id']=='choice:needle.bojutsu_result' for p in prompts)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==FOE]
    assert saves
    spent=next(e.sequence for e in engine.events if e.event_type=='RESOURCE_SPENT'
        and e.source_definition_id==PREFIX+'sweeping_strike')
    assert spent<max(e.sequence for e in saves)
    target=engine.state.actors[FOE]
    if result=='Prone':
        assert any(c.condition_id.endswith('.prone') for c in target.conditions.values())
    elif result=='Push 10 feet':
        assert target.position.x>=6
    elif result=='Reposition within reach':
        assert (target.position.x,target.position.y)!=(4,6)
        assert engine._distance_actor_to_actor(engine.state.actors[OWNER],target)<=15
        assert not any(e.event_type=='TELEPORTED' and e.actor_id==FOE for e in engine.events)
    else:
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(target))


def test_native_acquisition_http_model_and_menu(tmp_path):
    from app.models import TabletopAdvanceRequest
    request=TabletopAdvanceRequest(kind='subpath',record_id=SCHOOL)
    assert request.kind=='subpath'
    acquired(tmp_path)
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    menu=table.advancement(PID)
    assert any(r['id']==SCHOOL and r['legal'] for r in menu['subpaths'])
    assert menu['added']['subpaths'][0]['id']==SCHOOL




@pytest.mark.parametrize('result',['Catch projectile','Deflect projectile'])
def test_native_fired_unit_is_settled_once_and_reloads(tmp_path,result):
    bow='tianxia.mortal.weapon.gong_jian'
    ammo='tianxia.mortal.gear.arrows_20'
    enemy_kit={'starting_kit':{'items':[{'item_id':bow},{'item_id':ammo,'quantity':1}]}}
    combat,table,mid=game(tmp_path,14,foe_position={'x':8,'y':6},foe_kit=enemy_kit)
    for _ in range(8):
        turn(table,mid,FOE)
        engine=combat._load_session(mid).engine
        shot=next(c for c in engine.legal_candidates() if c.target_ids==(OWNER,)
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==bow)
        settle(table,mid,shot.candidate_id,choices={'choice:needle.bojutsu_deflect':['Use Deflecting Staff'],
            'choice:needle.bojutsu_deflect_result':[result],
            'choice:needle.bojutsu_catch_hand':'first','choice:needle.bojutsu_projectile_space':'first'})
        engine=reload(tmp_path/'fight',mid)
        records=[c for a in engine.state.actors.values() for c in a.conditions.values()
            if c.condition_id=='condition:typed.fired_projectile_item']
        if records:
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert len(records)==1
    receipt=records[0].data
    assert receipt['quantity']==1 and receipt['item_id']==ammo and receipt['shooter']==FOE
    from combat.ext.hand_occupancy import free_hands
    if result=='Catch projectile':
        assert receipt['holder']==OWNER and receipt['hand'] not in free_hands(engine,engine.state.actors[OWNER])
    else:
        assert not receipt['holder'] and 'x' in receipt and 'y' in receipt
    assert any(k.startswith('_round_ammunition_spent:') and v>=1
        for k,v in engine.state.actors[FOE].turn_flags.items())


@pytest.mark.parametrize('body,expected',[
    ({'attainment':3},1),({'attainment':14},4),({'attainment':20},5),
    ({'attainment':3,'effective_cl':6},2),({'attainment':18,'effective_cl':0},0)])
def test_native_path_profile_projection_caps_attainment(tmp_path,body,expected):
    from combat.subpath_acquisition import project
    # This consumes the same native saved school journal, with an explicit
    # existing Path profile; it does not grant a feature or fabricated receipt.
    doc=acquired(tmp_path)
    doc['path_and_subpath']['path_feature_record_ids']=[]
    doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.body_refining',**body}]
    projected=project(doc,[{'id':SCHOOL,'gm':False}])
    assert len(projected['path_and_subpath']['path_feature_record_ids'])==expected


def test_exact_base_native_frontdoor_regressions(tmp_path):
    """Run the exact-base arm inside this already admitted Pueue job."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-bojutsu-4-evidence')
    base=Path('/var/tmp/auto-audit/scratch/MGR-T14-ling-seam-bojutsu-4/base')
    result=subprocess.run([sys.executable,'/var/tmp/auto-audit/sweeprun/r25chunk.py',
        str(evidence/'baseline-selectors.txt'),str(tmp_path/'base-pt')],cwd=base/'APP',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},text=True,capture_output=True,timeout=600)
    (evidence/'exact-base-native.log').write_text(result.stdout+'\n'+result.stderr)
    assert result.returncode==1,result.stdout[-2000:]+result.stderr[-2000:]
    assert '16 failed' in result.stdout,result.stdout[-4000:]
    assert 'TABLETOP_ADVANCE_KIND' in result.stdout or 'Choose a Sphere or a talent' in result.stdout


def test_native_barrier_extra_reaction_after_actual_deflection(tmp_path):
    from combat import typed_reactions as tr
    bow='tianxia.mortal.weapon.gong_jian'
    enemy_kit={'starting_kit':{'items':[{'item_id':bow},
        {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    combat,table,mid=game(tmp_path,foe_position={'x':8,'y':6},foe_kit=enemy_kit)
    settle(table,mid,candidate(combat,mid,'Heavenly Staff Barrier').candidate_id,choices={})
    for _ in range(8):
        turn(table,mid,FOE)
        engine=combat._load_session(mid).engine
        shot=next(c for c in engine.legal_candidates() if c.target_ids==(OWNER,)
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==bow)
        start=len(engine.events)
        settle(table,mid,shot.candidate_id,choices={'choice:needle.bojutsu_deflect':['Use Deflecting Staff'],
            'choice:needle.bojutsu_deflect_result':['Deflect projectile'],
            'choice:needle.bojutsu_projectile_space':'first'})
        engine=reload(tmp_path/'fight',mid)
        if any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+'staff_of_one'
               for e in engine.events[start:]):
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    actor=engine.state.actors[OWNER]
    assert not actor.reaction_available
    assert not tr.can_react(engine,actor,{'feature_id':'unrelated','block':'generic'})
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.x==4 and c.destination.y==6)
    prompts=settle(table,mid,move.candidate_id,choices={'reaction:typed.opportunity_attack':[],
        'choice:needle.opportunity_profile':'first',
        'choice:needle.bojutsu_sweep':None,'choice:needle.bojutsu_barrier_hit':['Gain +1 AC']})
    engine=reload(tmp_path/'fight',mid);actor=engine.state.actors[OWNER]
    assert actor.turn_flags['_round_bojutsu_barrier_reaction']==engine.state.round_number
    assert not actor.reaction_available and not tr.can_react(engine,actor,tr.opportunity_reaction_row(engine,actor))
    assert any(p['context']['reaction_source_id']=='reaction:typed.opportunity_attack' for p in prompts)
    assert any(p['context']['reaction_source_id']=='choice:needle.opportunity_profile' for p in prompts)
    assert not actor.turn_flags.get('bojutsu_extra_transaction')
    # A hit stops at the actual entry square; a miss can finish its route.
    if engine._effective_speed(engine.state.actors[FOE])==0:
        assert engine.state.actors[FOE].position.x==6


def test_native_barrier_exact_clock_and_scene_use_survive_reload(tmp_path):
    combat,table,mid=game(tmp_path)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.stamina']
    settle(table,mid,candidate(combat,mid,'Heavenly Staff Barrier').candidate_id,choices={})
    for round_offset in range(1,11):
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        turn(table,mid,OWNER)
        engine=reload(tmp_path/'fight',mid)
        active=any(c.condition_id=='condition:typed.bojutsu_barrier' for c in engine.state.actors[OWNER].conditions.values())
        assert active==(round_offset<10)
        assert not any((engine.action_catalog.get(c.source_definition_id).parameters.get('typed') or {}).get('source')
            ==PREFIX+'heavenly_staff_barrier' for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog)
    assert engine.state.actors[OWNER].resources['resource:core.stamina']==before-6


def test_native_school_journal_is_bound_to_exact_printed_progression(tmp_path):
    import copy
    from combat.subpath_acquisition import project
    acquired(tmp_path)
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    record=table.buttons.get(PID)['advancement']['subpaths'][0]
    assert [f['id'] for f in record['source_features']]==[PREFIX+f for f in FEATURES]
    assert [f['minimum_cl'] for f in record['source_features']]==[3,6,10,14,18]
    assert all(len(f['text_sha256'])==64 for f in record['source_features'])
    damaged=copy.deepcopy(record);damaged['source_features'][0]['minimum_cl']=1
    with pytest.raises(ValueError,match='source changed'):
        project(CombatService(ROOT,tmp_path)._factory_owner_sheet(PID),[damaged])


def test_native_delivery_scope_is_inert_outside_its_exact_packet(tmp_path):
    from combat.attack_delivery import current,resolving
    combat,table,mid=game(tmp_path,6)
    engine=combat._load_session(mid).engine
    actor,target=engine.state.actors[FOE],engine.state.actors[OWNER]
    action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
    spec={'source_definition_id':action.source_definition_id,'parameters':action.parameters,'range_ft':30}
    assert current(engine,FOE,OWNER) is None
    with resolving(engine,actor,target,spec):
        assert current(engine,OWNER,FOE) is None
        assert current(engine,FOE,OWNER,'wrong-source') is None
        assert current(engine,FOE,OWNER,action.source_definition_id,pending=True) is None
    assert current(engine,FOE,OWNER) is None


def test_opportunity_selection_without_provider_preserves_default(tmp_path):
    from combat import typed_reactions as tr,opportunity_choices
    combat,table,mid=game(tmp_path,6)
    engine=combat._load_session(mid).engine
    actor=engine.state.actors[FOE]
    _,action,_=tr.opportunity_profile(engine,actor)
    assert opportunity_choices.profiles(engine,actor,action) is None
    assert opportunity_choices.choose(engine,actor,engine.state.actors[OWNER],None,action) is action


def test_native_non_typed_weapon_transport_consumes_the_same_deflection(tmp_path):
    """Fake transport only: retain the acquired catalog weapon and its real profile."""
    import copy
    from combat.canonical import canonical_sha256
    bow='tianxia.mortal.weapon.gong_jian'
    kit={'starting_kit':{'items':[{'item_id':bow},
        {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    def native_transport(bundles):
        bundle=bundles[2]
        row=next(a for a in bundle['action_catalog'] if (a.get('parameters',{}).get('typed') or {}).get('source')==bow
            and '#' not in a['source_definition_id'] and a['economy']=='ACTION')
        typed=row['parameters']['typed']
        attack=next(e for e in typed['effects'] if e['type']=='attack')
        row.update(resolution_kind='ATTACK',attack_bonus=typed['numbers']['attack_bonus'],
            damage=copy.deepcopy(typed['weapon']['damage']),damage_type=typed['weapon']['damage_type'])
        row['parameters']['attack_kind']=attack['attack_kind']
        bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=game(tmp_path,14,foe_position={'x':8,'y':6},foe_kit=kit,bundle_transform=native_transport)
    for _ in range(8):
        turn(table,mid,FOE);engine=combat._load_session(mid).engine
        shot=next(c for c in engine.legal_candidates() if c.target_ids==(OWNER,)
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==bow)
        stamina=engine.state.actors[OWNER].resources['resource:core.stamina'];start=len(engine.events)
        prompts=settle(table,mid,shot.candidate_id,choices={'choice:needle.bojutsu_deflect':['Use Deflecting Staff'],
            'choice:needle.bojutsu_deflect_result':['Move 5 feet'],'choice:needle.bojutsu_deflect_step':'first'})
        engine=reload(tmp_path/'fight',mid)
        receipts=[e for e in engine.events[start:] if e.event_type=='REACTION_RESOLVED'
            and e.source_definition_id==PREFIX+'staff_of_one']
        if receipts:
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert receipts
    assert engine.state.actors[OWNER].resources['resource:core.stamina']==stamina-1
    assert any(p['context']['reaction_source_id']=='choice:needle.bojutsu_deflect' for p in prompts)
    assert receipts[0].payload['pending_after']<receipts[0].payload['pending_before']


def test_native_world_suppression_dormancy_commit_reload(tmp_path):
    combat,table,mid=game(tmp_path,14)
    engine=combat._load_session(mid).engine
    actor=engine.state.actors[OWNER]
    ac=engine._ac_modifier(actor)
    payload={'source':'system:body_modes_scene_resources','subject':OWNER,
             'kind':'cultivation_suppression','scope':'realm-pressure',
             'value':{'source_rule':'Body Refining R8 Realm Suppression','source_cl':20,
                      'system':'body','effective_cl':2},'expires_at':60,'readers':[OWNER]}
    result=table.world_fact(mid,engine.state.state_version,payload,'bojutsu-suppression')
    assert result['status']=='COMMITTED'
    engine=reload(tmp_path/'fight',mid)
    assert engine._ac_modifier(engine.state.actors[OWNER])==ac-1
    assert not any(engine.action_catalog[c.source_definition_id].display_name.startswith('Flowing Spin')
        for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    # A world declaration is not an action or a payment, and cannot reset limits.
    assert engine.state.actors[OWNER].resources==actor.resources
    assert any(e.event_type=='WORLD_FACT_DECLARED' for e in engine.events)


def journey_game(tmp_path,monkeypatch,cl=18):
    doc=acquired(tmp_path/'source',cl)
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:doc)
    arena={'stable_id':'battlefield:bojutsu-road','display_name':'Staff road',
           'width_squares':8,'height_squares':8,'square_size_ft':5,
           'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'road':arena})
    service=CombatService(ROOT,tmp_path/'journey')
    aid='actor:factory.'+PID
    state=service.create_journey(project_ids=[PID],arena_id='road',
        positions={aid:{'x':2,'y':2}},base_paces={aid:5})
    return service,state,aid


def test_native_journey_barrier_cost_expiry_scene_and_reload(tmp_path,monkeypatch):
    service,state,aid=journey_game(tmp_path,monkeypatch)
    jid=state['journey_id'];before=state['actors'][aid]['resources']['resource:core.stamina']
    state=service.journey_act(jid,state['revision'],aid,'bojutsu_barrier',{})
    service=CombatService(ROOT,tmp_path/'journey')
    assert service.journey_state(jid)==state
    actor=state['actors'][aid]
    assert actor['resources']['resource:core.stamina']==before-6
    managed=actor['source_states']['system:body_modes_scene_resources']
    assert managed['effects'][0]['remaining_num']==60
    assert any(e['kind']=='ACTIVATION_RESOLVED' and e.get('source')==PREFIX+'heavenly_staff_barrier'
        for e in state['events'])
    with pytest.raises(ValueError):service.journey_act(jid,state['revision'],aid,'bojutsu_barrier',{})
    state=service.journey_act(jid,state['revision'],aid,'wait',{'seconds':59})
    assert state['actors'][aid]['source_states']['system:body_modes_scene_resources']['effects'][0]['remaining_num']==1
    state=service.journey_act(jid,state['revision'],aid,'wait',{'seconds':1})
    assert not state['actors'][aid]['source_states']['system:body_modes_scene_resources']['effects']
    with pytest.raises(ValueError):service.journey_act(jid,state['revision'],aid,'bojutsu_barrier',{})
    state=service.journey_end_scene(jid,state['revision'],'The staff practice ends and the caravan departs.')
    state=service.journey_act(jid,state['revision'],aid,'bojutsu_barrier',{})
    assert state['actors'][aid]['resources']['resource:core.stamina']==before-12


@pytest.mark.parametrize('guard',['missing_owner','wrong_schema','malformed','authority'])
def test_native_world_body_guards_atomic(tmp_path,guard):
    combat,table,mid=game(tmp_path,2 if guard=='missing_owner' else 14)
    engine=combat._load_session(mid).engine
    before=engine.state.model_dump(mode='json')
    payload={'source':'system:body_modes_scene_resources','subject':OWNER,
             'kind':'cultivation_suppression','scope':'pressure',
             'value':{'source_rule':'Body Refining R8','source_cl':20,'system':'body','effective_cl':2},
             'expires_at':60,'readers':[OWNER]}
    if guard=='wrong_schema':payload['source']='unowned-source'
    if guard=='malformed':payload['value']={'effective_cl':2}
    if guard=='authority':payload['authority']='actor'
    with pytest.raises(ValueError):table.world_fact(mid,engine.state.state_version,payload,'bad-'+guard)
    assert reload(tmp_path/'fight',mid).state.model_dump(mode='json')==before


def test_builder_created_body_bojutsu_native_all_features(catalog_environment,monkeypatch,tmp_path):
    """Fresh printed Path/Subpath progression, real granted implement, table commit and replay."""
    from pathlib import Path
    from app.api import create_app
    from app.core import sha256_json
    from factory_authoring.owner_items import OwnerItemStore, weapon_choices
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(catalog_environment['settings'])
    builder=app.state.character_builder
    project=builder.create_project(working_name='Bojutsu source practitioner',concept='Body Refiner of the Open School of Bojutsu',
        source_reference=None,target_cl=18,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='BOJUTSU-SOURCE-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],'subpath_choice':[SCHOOL]},method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='bojutsu-native-source-18',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'),run
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==SCHOOL]
    assert {r['feature_id'] for r in earned}=={PREFIX+name for name in FEATURES}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    for name in ('refined_iron_fist','heavenly_fist'):
        assert any(r['feature_id']=='tianxia.path.body_refining.feature.'+name and r['source_backed']
                   for r in doc['path_and_subpath']['earned_feature_occurrences'])
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-bojutsu-4-evidence')
    (evidence/'native-body-bojutsu-acquisition.json').write_text(json.dumps({'document':doc,'document_sha256':sha256_json(doc),
        'project_id':project['project_id'],'run_id':run['run_id'],'status':run['status'],'blockers':run.get('blockers',[])},sort_keys=True))
    # The native Items store grants one real Staff with its printed chassis and properties.
    choices=weapon_choices(STAFF,'Spiritual',None,[])
    profile={'source_rule':'Item Book: Gun (Staff), Spiritual Treasure; owner assigned Source CL 3',
             'authority':'native table owner','source_cl':3,'kind':'weapon','weight_lb':4,'cube_ft':6,
             'flags':{'magical':1,'cultivated':1,'prerequisites_met':1},'properties':[]}
    root=tmp_path/'native';pid=PID
    entry=OwnerItemStore(root/'owner_items').give(pid,{'kind':'weapon','chassis_id':STAFF,'grade':'Spiritual',
        'material_id':choices['material_id'],'enchantment_ids':[],'name':'Recorded Road Staff','runtime_profile':profile})
    aid='actor:factory.'+pid;foe='actor:factory.native-bow-opponent'
    for actor_id,document in ((aid,doc),(foe,sheet([],cl=18,kit={'starting_kit':{'items':[
            {'item_id':'tianxia.mortal.weapon.gong_jian'},{'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}))):
        folder=root/'portable_characters'/actor_id.removeprefix('actor:factory.');folder.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document))
    combat=CombatService(ROOT,root);table=TabletopService(combat,root)
    arena=combat.tabletop_maps.save({'display_name':'Bojutsu sourced practice','width_squares':14,'height_squares':14,
        'walls':[],'objects':[{'id':1,'x':4,'y':5,'kind':'custom','name':'Sourced practice pillar','hp':999,'ac':1,
            'blocks':False,'threshold':100,'resist':['BLUDGEONING','FORCE'],'source_cl':3,'source_rule':'Owner: ordinary unattended practice pillar, Source CL 3'}],
        'starts':{'team1':[[3,6]],'team2':[[5,6]]}})
    mid=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[foe],
        control_modes={aid:'MANUAL',foe:'MANUAL'},arena_id='battlefield:map.'+arena['map_id'],
        match_seed='BOJUTSU-SOURCE-NATIVE',maximum_rounds=20)['match_id']
    turn(table,mid,aid)
    engine=combat._load_session(mid).engine
    from combat.acquisition_inventory import read
    assert read(engine.state.actors[aid])[entry['item_uid']]['acquisition']['route']=='owner_gift'
    native_features={r['feature_id'] for r in engine.typed_passive_rows[aid] if r.get('block')=='bojutsu'}
    assert native_features=={PREFIX+name for name in FEATURES}
    ac=engine._ac_modifier(engine.state.actors[aid]);assert ac>=1
    # The object target is a real map record; its known authority permits Heavenly Fist.
    object_attack=next(c for c in engine.legal_candidates() if c.target_ids==('object:map.1',)
        and engine.action_catalog[c.source_definition_id].parameters.get('object_source_weapon')
        and 'Recorded Road Staff' in engine.action_catalog[c.source_definition_id].display_name)
    settle(table,mid,object_attack.candidate_id,choices={'choice:needle.bojutsu_object_type':['FORCE']})
    engine=reload(root,mid)
    assert engine.state.objects['object:map.1'].current_hp<999
    assert any(c.condition_id=='condition:typed.bojutsu_staff_attack_action' for c in engine.state.actors[aid].conditions.values())
    flow=next(c for c in engine.legal_candidates() if engine.action_catalog[c.source_definition_id].parameters.get('bojutsu_flow') and c.target_ids==(foe,))
    before=engine.state.actors[aid].resources['resource:core.stamina']
    settle(table,mid,flow.candidate_id,choices={'choice:needle.bojutsu_sweep':['Use Sweeping Strike'],
        'choice:needle.bojutsu_result':['Prone'],'choice:needle.bojutsu_heavenly_type':['FORCE']})
    engine=reload(root,mid)
    assert engine.state.actors[aid].resources['resource:core.stamina']<=before-1
    assert combat.replay(mid)['status']=='PASS'


def test_native_explicit_relations_control_staff_defense_not_roster_team(tmp_path):
    from tests.worker2_support import ALLY
    combat,table,mid=game(tmp_path,14,foe_position={'x':8,'y':6},
        foe_kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gong_jian'}]}})
    engine=combat._load_session(mid).engine
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':ALLY,'relation':'ENEMY'},
        expected_state_version=engine.state.state_version)
    engine=reload(tmp_path/'fight',mid)
    assert engine.state.actors[OWNER].team_id==engine.state.actors[ALLY].team_id
    for _ in range(6):
        turn(table,mid,FOE)
        engine=combat._load_session(mid).engine
        shot=next(c for c in engine.legal_candidates() if c.target_ids==(ALLY,)
            and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')=='tianxia.mortal.weapon.gong_jian')
        prompts=settle(table,mid,shot.candidate_id,choices={})
        assert not any(p['context']['reaction_source_id']=='choice:needle.bojutsu_deflect' for p in prompts)
        engine=reload(tmp_path/'fight',mid)
        if any(e.event_type=='DAMAGE_APPLIED' and ALLY in e.target_ids for e in engine.events):
            break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert combat.replay(mid)['status']=='PASS'


def test_native_three_section_flail_is_not_a_printed_staff(tmp_path):
    from factory_authoring.owner_items import OwnerItemStore,weapon_choices
    item='tianxia.mortal.weapon.san_jie_gun'
    doc=acquired(tmp_path/'source',14)
    choices=weapon_choices(item,'Spiritual',None,[])
    store=OwnerItemStore(tmp_path/'items')
    store.give(PID,{'kind':'weapon','chassis_id':item,'grade':'Spiritual',
                   'material_id':choices['material_id'],'enchantment_ids':[]})
    bundle=compile_character(doc,actor_id=OWNER,owner_items=store.items(PID),reaction_plan={'ask':True})
    rows=[a for a in bundle['action_catalog'] if (a.get('parameters',{}).get('typed') or {}).get('source')==item]
    assert rows
    # Wielding the quarterstaff grants +1 AC; retaining a sectional flail after
    # stowing that actual Staff does not keep the Staff-only bonus alive.
    combat,table,mid=fixture(tmp_path/'fight',[],cl=14,owner_bundle=bundle,seed='BOJUTSU-NOT-FLAIL')
    engine=combat._load_session(mid).engine
    before=engine._ac_modifier(engine.state.actors[OWNER])
    settle(table,mid,candidate(combat,mid,'Stow Gun (Staff) (frees 1 hand; no Action)').candidate_id,choices={})
    engine=reload(tmp_path/'fight',mid)
    assert engine._ac_modifier(engine.state.actors[OWNER])==before-1
    assert not any('#bojutsu_' in a['source_definition_id'] for a in rows)
    assert not any('Flowing Spin' in engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
        if c.source_definition_id in engine.action_catalog)


def test_native_journey_item_profile_requires_owner_input_and_reloads(tmp_path,monkeypatch):
    service,state,aid=journey_game(tmp_path,monkeypatch)
    jid=state['journey_id']
    actual=next(i for i in state['actors'][aid]['bundle']['carrying']['items'] if i.get('item_id')==STAFF)
    profile={'source_rule':'Item Book Gun (Staff); native owner records this acquired implement',
             'authority':'native table owner','source_cl':1,'kind':'weapon','weight_lb':4,'cube_ft':6,
             'flags':{'prerequisites_met':1},'properties':[]}
    payload={'key':actual['key'],'profile':profile}
    with pytest.raises(ValueError):service.journey_act(jid,state['revision'],aid,'inventory_record',payload)
    assert service.journey_state(jid)==state
    after=service.journey_owner_act(jid,state['revision'],aid,'inventory_record',payload)
    cold=CombatService(ROOT,tmp_path/'journey')
    assert cold.journey_state(jid)==after
    record=next(iter(after['actors'][aid]['recorded_inventory'].values()))
    assert record['acquisition']['route']=='compiled_equipment' and record['inventory_key']==actual['key']
    assert len(after['actors'][aid]['bundle']['carrying']['items'])==len(state['actors'][aid]['bundle']['carrying']['items'])
    with pytest.raises(ValueError):cold.journey_owner_act(jid,after['revision'],aid,'inventory_record',payload)


def test_native_mixed_projectile_rolls_all_damage_before_deflection_and_zero_result(tmp_path):
    from factory_authoring.owner_items import OwnerItemStore,weapon_choices
    bow='tianxia.mortal.weapon.gong_jian'
    choices=weapon_choices(bow,'Spiritual',None,[])
    frost=next(r['enchantment_id'] for r in choices['enchantments'] if r['enchantment_id'].endswith('frost_meridian_inscription'))
    store=OwnerItemStore(tmp_path/'enemy-items')
    store.give('foe',{'kind':'weapon','chassis_id':bow,'grade':'Spiritual','material_id':choices['material_id'],
                     'enchantment_ids':[frost]})
    foe=compile_character(sheet([],cl=14),actor_id=FOE,owner_items=store.items('foe'))
    def transport(bundles):
        bundles[:]=[foe if b['actor_id']==FOE else b for b in bundles]
    combat,table,mid=game(tmp_path,14,foe_position={'x':8,'y':6},bundle_transform=transport)
    for _ in range(8):
        turn(table,mid,FOE)
        engine=combat._load_session(mid).engine
        shot=next(c for c in engine.legal_candidates() if c.target_ids==(OWNER,)
                  and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==bow)
        before_hp=engine.state.actors[OWNER].current_hp;before_stamina=engine.state.actors[OWNER].resources['resource:core.stamina'];start=len(engine.events);roll_start=len(engine.rolls)
        prompts=settle(table,mid,shot.candidate_id,choices={'choice:needle.bojutsu_deflect':['Use Deflecting Staff'],
            'choice:needle.bojutsu_deflect_result':['Move 5 feet'],'choice:needle.bojutsu_deflect_step':'first'})
        engine=reload(tmp_path/'fight',mid);events=engine.events[start:]
        new_rolls=engine.rolls[roll_start:]
        reduction=[i for i,r in enumerate(new_rolls) if r.reason.startswith('DAMAGE_REDUCTION:')]
        if reduction:
            rolls=[i for i,r in enumerate(new_rolls) if r.actor_id==FOE and r.reason.startswith('DAMAGE:')]
            assert len(rolls)>=2 and max(rolls)<reduction[0]
            assert engine.state.actors[OWNER].resources['resource:core.stamina']==before_stamina-1
            zero_choices=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.bojutsu_deflect_result']
            if engine.state.actors[OWNER].current_hp==before_hp:
                assert len(zero_choices)==1
                assert not any(c.condition_id=='condition:typed.bojutsu_deflect_packet_pending' for c in engine.state.actors[OWNER].conditions.values())
                break
            assert not zero_choices
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    else:
        raise AssertionError('The actual mixed projectile never reached a fully reduced packet')
    assert combat.replay(mid)['status']=='PASS'
