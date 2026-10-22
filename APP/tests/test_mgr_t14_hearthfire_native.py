"""Hearthfire family through native table/journey transactions and cold replay."""
import pytest
from pathlib import Path
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_qi_subpaths_7 import controls
BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
FEATURES = [BASE+s for s in ('kindled_hearth','homefire_recovery','hearthward_pavilion','carry_the_hearth','flame_that_welcomes_all')]


def test_welcome_native_field_reduction_healing_and_replay(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,owner_features=FEATURES,bundle_transform=controls,seed='HEARTHFIRE-WELCOME',owner_bundle=acquired_bundle(tmp_path,18))
    prompts=settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,
        choices={'choice:needle.welcoming_allies':[OWNER,ALLY],'choice:needle.homefire_recovery':'temp_hp'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==92
    assert e.state.actors[ALLY].temporary_hp==12
    z=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('welcome'))
    assert z.trigger_profile['height_ft']==40 and z.trigger_profile['size_ft']==40
    assert z.concentration_link and e.state.actors[OWNER].concentration is not None
    assert any(p['context']['reactor_id']==ALLY for p in prompts)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,choices={'choice:needle.hearth_shield':None})
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp==478
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert any(r.reason=='HEARTH_FEED' for r in e.rolls)
    assert e.state.actors[ALLY].current_hp>478


def journey(tmp_path,monkeypatch,*,cl=18,owned=True,arena_objects=None,roofs=None,terrain=None,dc=18,guest_kind=None,owner_score=None,guest_talents=(),guest_score=14,owner_base_features=(),zero_guest=False,observer=False):
    def document(pid):
        s=acquired_document(tmp_path,cl,dc=dc,base_features=owner_base_features) if owned and pid=='hearth' else sheet(guest_talents,cl=cl,name=pid,score=guest_score)
        if zero_guest and pid=='guest':s['ability_scores_and_statistics']['hit_points']['maximum']=64
        if zero_guest and pid=='raider':s=sheet(['STARS_TAL_FALLING_STAR'],cl=18,dc=100)
        s['identity']['name']=pid
        if guest_kind and pid=='guest':s['identity']['creature_type']=guest_kind
        if owner_score is not None and pid=='hearth':
            for ability in s['ability_scores_and_statistics']['abilities']:
                ability.update(score=owner_score,modifier=(owner_score-10)//2)
        s['identity']['proficiency_bonus']=6
        s['ability_scores_and_statistics']['primary_resource']['maximum']=100
        return s
    import json,zipfile
    parties=('hearth','guest','raider') if zero_guest else (('hearth','guest','observer') if observer else ('hearth','guest'))
    for pid in parties:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document(pid)))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'scene':{'stable_id':'hearth:test','display_name':'Hearthfire camp','width_squares':25,'height_squares':15,'square_size_ft':5,'starting_positions':{},'terrain_regions':terrain or [],'map_objects':arena_objects or [],'roof_surfaces':roofs or []}})
    cold=lambda:CombatService(ROOT,tmp_path)
    a,b='actor:factory.hearth','actor:factory.guest'
    if zero_guest:
        positions={a:{'x':3,'y':6},b:{'x':9,'y':6},'actor:factory.raider':{'x':12,'y':6}}
        with monkeypatch.context() as identifiers:
            identifiers.setattr('combat.journey.secrets.token_hex',lambda count:'0123456789abcdef01234567')
            state=cold().create_journey(project_ids=['hearth','guest','raider'],arena_id='scene',positions=positions,base_paces={who:18000 for who in positions})
    elif observer:
        # A third creature standing inside the Pavilion who never listened: it
        # must receive no Private Hearth reading at all. Off the guest's eastward
        # walk (row 6) so it never blocks that committed move.
        positions={a:{'x':3,'y':6},b:{'x':4,'y':6},'actor:factory.observer':{'x':7,'y':7}}
        state=cold().create_journey(project_ids=['hearth','guest','observer'],arena_id='scene',positions=positions,base_paces={who:18000 for who in positions})
    else:
        state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
    jid=state['journey_id']
    def admit(kind,payload,actor=a):
        from combat.ext.qi_hearthfire_camp import WORLD_COMMANDS
        source,fact_kind=WORLD_COMMANDS[kind]
        value={k:v for k,v in payload.items() if k not in ('record_id','authority','expires_at')}
        if 'ordinary' in value:value['ordinary']=int(value['ordinary'])
        before=cold().journey_state(jid)
        state=cold().journey_world_fact(jid,before['revision'],{'source':source,'subject':actor,
            'kind':fact_kind,'scope':payload['record_id'],'value':value,'expires_at':payload['expires_at'],'readers':[]})
        assert cold().journey_state(jid)==state
        return {'record_id':payload['record_id']}
    def act(kind,payload=None,actor=a):
        from combat.ext.qi_hearthfire_camp import WORLD_COMMANDS
        if kind in WORLD_COMMANDS and set(payload or {})!={'record_id'}:payload=admit(kind,payload,actor)
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],actor,kind,payload)
        assert cold().journey_state(jid)==result
        return result
    act.admit=admit
    return cold,jid,act,a,b


def kindle(act,a,b):
    return act('hearth_kindle',{'position':{'x':5,'y':6},'invited':[a,b],'host':a})


def test_journey_kindling_rest_pavilion_and_combat_genesis(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    state=kindle(act,a,b)
    assert state['actors'][a]['resources']['resource:core.qi']==99
    state=act('hearth_short_rest',{},b)
    assert state['seconds']==3600
    options=cold().journey_menu(jid,b)['options']
    assert {o['payload']['benefit'] for o in options if o['kind']=='hearth_recovery'}>={'heal','temp_hp','fear'}
    state=act('hearth_recovery',{'benefit':'temp_hp'},b)
    assert state['actors'][b]['hearthfire']['temporary_hp']==12
    with pytest.raises(ValueError):act('hearth_recovery',{'benefit':'temp_hp'},b)
    assert cold().journey_state(jid)==state
    state=act('hearth_pavilion',{})
    assert state['seconds']==4200
    assert state['actors'][a]['resources']['resource:core.qi']==95
    props=cold().journey_menu(jid,b)['properties']
    assert props['hearth_ac_bonus']==1 and props['hearth_weather_discomfort_immune']==1
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[b].temporary_hp==12
    assert any(z.active and z.trigger_profile.get('profile',{}).get('pavilion') for z in loaded.engine.state.zones.values())


def test_journey_default_inert_wrong_owner_and_expiry(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,owned=False)
    before=cold().journey_state(jid)
    assert not any(o['kind'].startswith('hearth_') for o in cold().journey_menu(jid,a)['options'])
    with pytest.raises(ValueError):kindle(act,a,b)
    assert cold().journey_state(jid)==before


def weather(owner,**changes):
    return {'owner':owner,'phenomenon':'rain','ordinary':True,'source_cl':0,'delivery':'environment',
            'authority':'GM','record_id':'weather:rain','expires_at':10000,**changes}


@pytest.mark.parametrize('changes,blocked',[
    ({},1),({'source_cl':18},0),({'source_cl':19},0),({'ordinary':False},0),
    ({'delivery':'attack'},0),({'delivery':'creature'},0),({'delivery':'technique'},0),({'phenomenon':'poison_gas'},0)])
def test_weatherward_native_delivery_boundaries(tmp_path,monkeypatch,changes,blocked):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    state=act('hearth_weather',weather(a,**changes),b)
    event=state['events'][-1]
    assert event['kind']=='WEATHERWARD_DELIVERY' and event['blocked']==blocked and event['extinguished']==0
    assert cold().journey_state(jid)==state
    if not changes:
        act('hearth_permit_weather',{'permitted':['rain']})
        state=act('hearth_weather',weather(a,record_id='weather:permitted'),b)
        assert state['events'][-1]['blocked']==0


def test_pavilion_civic_space_and_private_hearth_native_results(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    for people,capacity in ((181,181),(5,4)):
        admitted=act.admit('hearth_shelter',{'people':people,'capacity':capacity,'authority':'GM','record_id':'space','expires_at':10000})
        before=cold().journey_state(jid)
        with pytest.raises(ValueError):act('hearth_shelter',admitted)
        assert cold().journey_state(jid)==before
    state=act('hearth_shelter',{'people':180,'capacity':200,'authority':'GM','record_id':'space','expires_at':10000})
    assert state['events'][-1]['people']==180
    # A native route actually carries the listener outside the ward.
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    spoken=act('hearth_speak',{'text':'The tea is ready.','expires_at':10000})
    speech=spoken['events'][-1]['record_id']
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'auditory','effect_source_cl':0,'speech_record_id':speech},b)
    assert state['events'][-1]['understood']==0
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'check','effect_source_cl':0,'speech_record_id':speech},b)
    assert 'roll' in state['events'][-1]
    before=state
    with pytest.raises(ValueError):act('hearth_listen',{'owner':a,'speaker':a,'method':'telepathy','effect_source_cl':99,'speech_record_id':speech},b)
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('benefit',['heal','temp_hp','fear','exhaustion:travel'])
def test_every_recovery_choice_native_interval_and_long_rest_cadence(tmp_path,monkeypatch,benefit):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    if benefit=='heal':wounded=native_wound_guest(cold,jid,a,b,tmp_path)
    kindle(act,a,b)
    act('travel_exhaustion',{'levels':2,'ordinary':True},b)
    act('hearth_short_rest',{},b)
    state=act('hearth_recovery',{'benefit':benefit},b)
    assert state['actors'][b]['travel_uses'][FEATURES[1]]==0
    if benefit=='heal':
        expected=wounded+12
        assert state['actors'][b]['encounter_snapshot']['current_hp']==expected
        assert cold().journey_state(jid)['actors'][b]['encounter_snapshot']['current_hp']==expected
    if benefit=='exhaustion:travel':assert state['actors'][b]['exhaustion']==1
    if benefit=='fear':assert state['actors'][b]['hearthfire']['fear_scene']==2
    act('hearth_short_rest',{},b)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('hearth_recovery',{'benefit':benefit},b)
    assert cold().journey_state(jid)==before
    act('long_rest',{},b)
    state=kindle(act,a,b)
    act('hearth_short_rest',{},b)
    state=act('hearth_recovery',{'benefit':'temp_hp'},b)
    assert state['actors'][b]['travel_uses'][FEATURES[1]]==1
    if benefit=='heal':
        result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
        loaded=cold()._load_session(result['match_id'])
        assert loaded.mechanical.replay()['status']=='PASS'
        assert loaded.engine.state.actors[b].current_hp==expected


def test_expired_camp_and_low_cl_cannot_grant_later_rows(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,cl=3)
    kindle(act,a,b)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('hearth_pavilion')
    assert cold().journey_state(jid)==before
    act('wait',{'seconds':28800})
    assert not cold().journey_menu(jid,b)['properties']
    with pytest.raises(ValueError):act('hearth_short_rest',{},b)


def native_welcome(tmp_path,*,dc=18,kind=None):
    def setup(bundles):
        controls(bundles)
        if kind:
            from combat.canonical import canonical_sha256
            bundles[2]['actor_template']['creature_types']=[kind]
            bundles[2].pop('bundle_sha256',None);bundles[2]['bundle_sha256']=canonical_sha256(bundles[2])
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,owner_dc=dc,owner_features=FEATURES,bundle_transform=setup,seed='WELCOME-BOUNDARY',owner_bundle=acquired_bundle(tmp_path,18,dc=dc))
    settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,
        choices={'choice:needle.welcoming_allies':[OWNER,ALLY],'choice:needle.homefire_recovery':'temp_hp'})
    return combat,table,mid


@pytest.mark.parametrize('kind,dc,failed',[('Undead',100,True),('Undead',1,False),('Humanoid',100,None)])
def test_threshold_native_kind_save_and_reaction_state(tmp_path,kind,dc,failed):
    combat,table,mid=native_welcome(tmp_path,kind=kind,dc=dc)
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    held=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.hospitality_threshold']
    if failed is None:
        assert not held
    else:
        assert len(held)==1 and held[0].data['failed']==int(failed)
        assert held[0].expires_on=='START_OF_TURN_AT:'+FOE+':'+str(e.state.actors[FOE].turns_started+1)
        if failed:
            pos=e.state.actors[FOE].position;center=next(z.center for z in e.state.zones.values() if z.trigger_profile.get('profile',{}).get('welcome'))
            assert all(e.grid.distance_ft(c.destination,center)>=e.grid.distance_ft(pos,center)
                       for c in e.legal_candidates() if c.kind.value=='MOVE')


def test_welcome_ac_resistance_nonstacking_and_scene_limit(tmp_path):
    combat,table,mid=native_welcome(tmp_path)
    e=reload(tmp_path,mid)
    from combat import ext
    assert sum(ext.run('ac',e,e.state.actors[ALLY]))==1
    assert sum(ext.run('ac',e,e.state.actors[FOE]))==0
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert not any(e.action_catalog[c.source_definition_id].display_name=='Flame That Welcomes All'
                   for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)


def test_welcome_no_guest_stable_once_and_outright_guard(tmp_path,accept_move=False):
    # A committed native packet takes a protected ally to exactly zero. The
    # temporary HP packet and per-activation receipt must survive cold replay.
    def setup(bundles):
        controls(bundles)
        from combat.gate2_runtime_models import ActionDefinition
        from combat.canonical import canonical_sha256
        for b in bundles:
            for name,flat in [('Drop guest',518),('Kill guest outright',1018)]:
                sid='action:test.'+b['actor_id']+'.'+name.replace(' ','_')
                row=ActionDefinition(source_definition_id=sid,owner_id=b['actor_id'],display_name=name,economy='BONUS_ACTION',
                    resolution_kind='TYPED',target_kind='HOSTILE_ENTITY',range_ft=60,parameters={'typed':{'source':sid,
                    'effects':[{'type':'damage','applies_to':'target','flat':flat,'damage_types':['force']}],
                    'numbers':{'cl':18,'pb':6,'key_mod':4,'save_dc':18},'duration':{'kind':'instant'},'riders':[]}})
                b['action_catalog'].append(row.model_dump(mode='json'));b['actor_template']['action_ids'].append(sid)
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    for name,stable in [('Drop guest',True),('Kill guest outright',False)]:
        path=tmp_path/name
        combat,table,mid=fixture(path,[],cl=18,owner_pb=6,owner_features=FEATURES,bundle_transform=setup,seed='WELCOME-RESCUE',owner_bundle=acquired_bundle(path,18),foe_position={'x':5,'y':6})
        settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,
            choices={'choice:needle.welcoming_allies':[OWNER,ALLY],'choice:needle.homefire_recovery':'temp_hp'})
        turn(table,mid,FOE)
        before=reload(path,mid);origin=before.state.actors[ALLY].position;event_count=len(before.events)
        settle(table,mid,candidate(combat,mid,name,target=ALLY).candidate_id,
            choices={'choice:needle.hearth_shield':None,'choice:needle.hearth_rescue_move':'first' if accept_move else None})
        e=reload(path,mid)
        actor=e.state.actors[ALLY]
        assert (actor.life_state=='STABLE')==stable
        if stable:
            assert actor.current_hp==0 and actor.temporary_hp==12
            moves=[event for event in e.events[event_count:] if event.event_type=='MOVEMENT_COMMITTED' and event.actor_id==ALLY]
            if accept_move:
                assert actor.position!=origin and e.grid.distance_ft(origin,actor.position)==5
                assert len(moves)==1 and moves[0].payload['granted_cost_ft']==5
                assert not any(event.event_type=='REACTION_SPENT' for event in e.events[event_count:])
            else:
                assert actor.position==origin and not moves
            assert any(z.per_turn_triggered.get('welcome_saved:'+ALLY)==1 for z in e.state.zones.values())
            assert e._effective_speed(actor)==0
            assert not any(c.condition_id=='condition:typed.welcome_rescue' for c in actor.conditions.values())
        else:
            assert actor.position==origin
            assert not any(event.event_type=='MOVEMENT_COMMITTED' and event.actor_id==ALLY for event in e.events[event_count:])


def test_real_empowered_item_native_pickup_consent_and_no_duplicate(tmp_path):
    from tests.test_a2_qi_subpaths_7 import fight
    combat,table,mid=fight(tmp_path,carry=True,empowered=True,owner_bundle=acquired_bundle(tmp_path,18))
    e=reload(tmp_path,mid)
    assert e.state.objects['object:map.91'].component['hearth_original']['object_id']=='object:map.91'
    assert any(c.condition_id=='condition:typed.hearth_item_custody' for c in e.state.actors[ALLY].conditions.values())
    prompts=settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':ALLY,'choice:needle.fact_admission.carry_hearth_consent':'carry'})
    e=reload(tmp_path,mid)
    assert len(e.state.objects)==1
    assert e.state.objects['object:map.91'].position==e.state.actors[ALLY].position
    assert any(p['context']['reactor_id']==ALLY for p in prompts)


def test_created_flame_does_not_invent_real_item_custody(tmp_path):
    from tests.test_a2_qi_subpaths_7 import fight
    combat,table,mid=fight(tmp_path,carry=True,owner_bundle=acquired_bundle(tmp_path,18))
    prompts=settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':OWNER})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.carry_hearth')
    assert ALLY not in [o['id'] for o in p['choice']['options']]


def acquired_document(tmp_path,cl,*,dc=18,base_features=()):
    from app.core import Database,Settings
    from project_store.service import ProjectStore
    from non_sphere_authority.service import NonSphereAuthorityService
    from vendor_adapter.service import FactoryAdapter
    from catalog.service import CatalogService
    from content_packs.service import ContentPackManager
    settings=Settings.from_env(ROOT,tmp_path.parent/'hearthfire-authenticated-catalog');settings.ensure_dirs()
    db=Database(settings);db.migrate()
    if not getattr(acquired_document,'catalogs',set()).__contains__(str(settings.data_dir)):
        config=FactoryAdapter(db).configure(ROOT/'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip')
        CatalogService(db).rebuild_core(Path(config['factory_root']))
        acquired_document.catalogs=getattr(acquired_document,'catalogs',set())|{str(settings.data_dir)}
    locks=[{'pack_id':p['pack_id'],'version':p['version'],'pack_hash':p['pack_hash']}
           for p in ContentPackManager(db).list() if p.get('authority')=='canonical' and p.get('lifecycle_state')=='published']
    assert locks
    project=ProjectStore(db).create_project(working_name='Hearthfire source acquisition',pack_locks=locks,
        user_locks=[{'field':'target_cl','value':cl}])
    pid=project['project_id'];qi='tianxia.path.qi_cultivation';parent=BASE.removesuffix('.feature.')
    authority=NonSphereAuthorityService(db)
    authority.initialize_for_project(pid,target_cl=cl,path_ids=[qi],method_id='METHOD-001',path_attainment_by_id={qi:cl})
    selected=authority.select_subpath(pid,qi,parent)
    cold=NonSphereAuthorityService(Database(settings))
    reopened=cold.get_state(pid)
    assert {k:v for k,v in reopened.items() if k not in ('semantic_validation','readiness')}=={k:v for k,v in selected.items() if k not in ('semantic_validation','readiness')}
    assert reopened['semantic_validation']['blocker_count']==0
    path=next(r for r in selected['paths'] if r['path_id']==qi)
    assert path['subpath_or_tradition_id']==parent
    projection=cold.project_locked_subpath_catalog_record(path['subpath_or_tradition_id'])
    progression=projection['compatibility']['factory']['stage2_authority']['feature_progression']
    ids=[r['canonical_id'] for r in progression if r['granted_at_cl']<=path['attainment']]
    assert ids==[f for f,l in zip(FEATURES,(3,6,10,14,18)) if l<=cl]
    doc=sheet([],cl=path['attainment'],dc=dc);doc['identity']['proficiency_bonus']=6
    path_projection=cold.project_locked_path_catalog_record(qi)['compatibility']['factory']['stage2_authority']
    legal={fid for level,grants in path_projection['automatic_feature_record_ids_by_cl'].items() if int(level)<=cl for fid in grants}
    assert set(base_features)<=legal
    doc['path_and_subpath']={'path_feature_record_ids':[*ids,*base_features]}
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    return doc


def acquired_bundle(tmp_path,cl,*,dc=18):
    from combat.factory_compiler import compile_character
    return compile_character(acquired_document(tmp_path,cl,dc=dc),actor_id=OWNER,reaction_plan={'ask':True})


def test_native_open_school_acquisition_is_source_derived_before_play(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    state=kindle(act,a,b)
    assert state['actors'][a]['resources']['resource:core.qi']==99
    assert {r['feature_id'] for r in state['actors'][a]['bundle']['typed_passives'] if r.get('block')=='qi_hearthfire'}==set(FEATURES)


def test_source_clock_reopen_does_not_refill_eight_hours(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('wait',{'seconds':100});act('finish')
    state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',
        positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
    new=state['journey_id']
    before=cold().journey_state(new)
    assert cold().journey_menu(new,b)['properties']['hearth_frightened_advantage']==1
    assert cold().journey_state(new)==before,'a menu read may not mutate or extend the source clock'
    cold().journey_act(new,before['revision'],a,'wait',{'seconds':28700})
    assert not cold().journey_menu(new,b)['properties']


def test_source_clock_native_combat_rounds_resume_without_refill(tmp_path,monkeypatch):
    from combat.tabletop_service import TabletopService
    from combat.ext.qi_hearthfire_persistence import CLOCK
    import json
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    state=kindle(act,a,b)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(6):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    final=cold()._load_session(mid)
    assert final.engine.state.terminal_result is not None
    record=next(c.data for c in final.engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert record['remaining']==28800-12
    travel=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,travel['revision'])
    assert resumed['phase']=='travel'
    assert cold().journey_menu(jid,b)['properties']['hearth_frightened_advantage']==1
    after=cold().journey_act(jid,resumed['revision'],a,'wait',{'seconds':record['remaining']})
    assert not cold().journey_menu(jid,b)['properties']


def test_private_speech_native_source_and_observer_scope(tmp_path,monkeypatch):
    from combat.senses import perception
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('hearth_listen',{'owner':a,'speaker':a,'method':'auditory',
        'effect_source_cl':0,'speech_record_id':'invented'},b)
    assert cold().journey_state(jid)==before
    spoken=act('hearth_speak',{'text':'Keep this sentence private.','expires_at':10000})
    record=spoken['events'][-1]['record_id']
    assert 'Keep this sentence private.' not in str(spoken['events'][-1])
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'auditory','effect_source_cl':0,'speech_record_id':record},b)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    engine=loaded.engine
    rows=perception(engine,engine.state.actors[b])['information']
    assert len(rows)==1 and rows[0]['viewer_id']==b and 'words' not in rows[0]['details']
    assert not perception(engine,engine.state.actors[a]).get('information')


def test_private_hearth_projection_reaches_only_the_listener_in_combat(tmp_path,monkeypatch):
    # Finding F10-2: exercise the Private Hearth observer_information provider at
    # the combat level, through information_results.for_observer and
    # senses.perception, with a second creature present who never listened.
    from combat.information_results import for_observer
    from combat.senses import perception
    from combat.ext.qi_hearthfire_sanctuary import PAVILION
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,observer=True)
    c='actor:factory.observer'
    kindle(act,a,b);act('hearth_pavilion')
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    spoken=act('hearth_speak',{'text':'Keep this inside.','expires_at':10000})
    record=spoken['events'][-1]['record_id']
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'auditory','effect_source_cl':0,'speech_record_id':record},b)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b',c:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    engine=loaded.engine
    facts=[row for row in for_observer(engine,engine.state.actors[b]) if row.get('source_id')==PAVILION]
    assert len(facts)==1 and facts[0]['viewer_id']==b and 'words' not in facts[0]['details']
    # The listener's own perception carries that exact Private Hearth fact ...
    assert [row for row in perception(engine,engine.state.actors[b])['information'] if row.get('source_id')==PAVILION]==facts
    # ... and the third creature and the speaker receive nothing from it.
    assert not [row for row in for_observer(engine,engine.state.actors[c]) if row.get('source_id')==PAVILION]
    assert not perception(engine,engine.state.actors[c]).get('information')
    assert not [row for row in for_observer(engine,engine.state.actors[a]) if row.get('source_id')==PAVILION]


def test_environmental_penalty_is_native_and_recovery_removes_exact_condition(tmp_path,monkeypatch):
    import json
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b)
    # Smoke is not the base Hearth's ordinary cold/rain/damp immunity.
    state=act('hearth_hardship',{'cause':'smoke','ordinary':True,'source_cl':0,'levels':0,
        'penalty':{'speed_penalty_ft':10},'record_id':'smoke:stinging-air','authority':'controller',
        'expires_at':10000,'visibility':'subject'},b)
    row=state['actors'][b]['hearthfire']['hardships'][0]
    iid=row['condition_instance_id']
    condition=json.loads(state['actors'][b]['encounter_snapshot']['conditions'][iid])
    assert condition['data']['speed_delta']==-10
    assert row['authority']==b and row['receipt_id']
    act('hearth_short_rest',{},b)
    assert any(o['payload'].get('benefit')=='penalty:0' for o in cold().journey_menu(jid,b)['options'])
    state=act('hearth_recovery',{'benefit':'penalty:0'},b)
    assert iid not in state['actors'][b]['encounter_snapshot']['conditions']
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert iid not in loaded.engine.state.actors[b].conditions


def test_carry_outside_combat_same_asset_minute_and_native_transfer(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    state=kindle(act,a,b)
    oid=state['actors'][a]['hearthfire']['camp']['native_object']['object_id']
    act('hearth_pavilion')
    state=act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    assert state['actors'][a]['resources']['resource:core.qi']==91
    state=act('move',{'path':[{'x':2,'y':6},{'x':1,'y':6}]})
    camp=state['actors'][a]['hearthfire']['camp']
    assert camp['position']==state['actors'][a]['position']
    assert camp['native_object']['object_id']==oid
    assert camp['pavilion']['position']=={'x':5,'y':6}
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    hearth=next(z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object')==oid)
    assert hearth.trigger_profile['size_ft']==20
    assert hearth.trigger_profile['profile']['hearth_carrier']==a
    assert len([o for o in loaded.engine.state.objects.values() if o.object_id==oid])==1



def test_private_hearth_actual_nonauditory_delivery_is_reachable(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    spoken=act('hearth_speak',{'text':'Come home.','expires_at':10000,'delivery':'visible_gesture','recipients':[b]})
    record=spoken['events'][-1]['record_id']
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'nonauditory','effect_source_cl':0,'speech_record_id':record},b)
    info=cold().journey_menu(jid,b)['properties']['hearth_private_information']
    assert info['understood']==1 and info['words']=='Come home.'
    assert cold().journey_state(jid)==state


def test_welcome_native_travel_activation_cost_recovery_and_concentration_transfer(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    state=act('hearth_welcome',{'center':'self','invited':[a,b]})
    assert state['actors'][a]['resources']['resource:core.qi']==92
    assert cold().journey_menu(jid,b)['properties']['hearth_ac_bonus']==1
    state=act('hearth_recovery',{'benefit':'temp_hp'},b)
    before=state
    with pytest.raises(ValueError):act('hearth_welcome',{'center':'self','invited':[a,b]})
    assert cold().journey_state(jid)==before
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[a].concentration is not None
    assert loaded.engine.state.actors[b].temporary_hp==12
    field=next(z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('welcome'))
    assert field.concentration_link and field.duration_rounds==10
    assert field.owner_id==a



def test_uninvited_rest_recipient_and_pavilion_ally_are_legal(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    act('hearth_kindle',{'position':{'x':5,'y':6},'invited':[a],'host':a})
    assert not cold().journey_menu(jid,b)['properties']
    act('hearth_short_rest',{},b)
    state=act('hearth_recovery',{'benefit':'temp_hp'},b)
    assert state['actors'][b]['hearthfire']['temporary_hp']==12
    act('hearth_pavilion')
    assert cold().journey_menu(jid,b)['properties']['hearth_ac_bonus']==1


def test_existing_native_flame_expiry_preserves_real_item_in_next_encounter(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10}])
    options=cold().journey_menu(jid,a)['options']
    option=next(o for o in options if o['kind']=='hearth_kindle' and o['payload'].get('existing')=='object:map.91')
    state=act('hearth_kindle',option['payload'])
    camp=state['actors'][a]['hearthfire']['camp']
    original=camp['native_object']['component']['hearth_original']
    assert camp['native_object']['object_id']=='object:map.91'
    from combat.asset_anchor_runtime import source_profile,is_asset
    from combat.journey_assets import JourneyAssetContext
    context=JourneyAssetContext(cold().journeys.load(jid))
    assert is_asset(context.state.objects['object:map.91'])
    assert source_profile(context,context.state.objects['object:map.91'])['owner']==a
    assert context.state.objects['object:map.91'].owner_id==original.get('owner_id')
    state=act('wait',{'seconds':28800})
    mundane=state['runtime_objects']['object:map.91']
    assert mundane['maximum_hp']==original['maximum_hp'] and not mundane['destroyed']
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    obj=loaded.engine.state.objects['object:map.91']
    assert obj.maximum_hp==original['maximum_hp']
    assert not any(z.active and z.trigger_profile.get('profile',{}).get('hearth_object') for z in loaded.engine.state.zones.values())


def test_welcome_first_damage_round_is_not_rearmed_by_another_cultivator(tmp_path):
    from combat.factory_compiler import compile_character
    from combat.canonical import canonical_sha256
    other_foe='actor:factory.worker2-foe1'
    def setup(bundles):
        bundles[1]=compile_character(acquired_document(tmp_path,18),actor_id=ALLY,reaction_plan={'ask':True})
        controls(bundles)
        order={OWNER:1000,FOE:900,ALLY:800,other_foe:700}
        for bundle in bundles:
            bundle['actor_template']['initiative_bonus']=order[bundle['actor_id']]
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,extra_foes=1,bundle_transform=setup,
        owner_bundle=acquired_bundle(tmp_path,18),seed='HEARTHFIRE-OVERLAP')
    choices={'choice:needle.welcoming_allies':[OWNER,ALLY],'choice:needle.homefire_recovery':'temp_hp',
             'choice:needle.hearth_shield':None}
    settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,choices=choices)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,choices=choices)
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp==478
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,choices=choices)
    turn(table,mid,other_foe)
    settle(table,mid,candidate(combat,mid,'Force damage',target=ALLY).candidate_id,choices=choices)
    assert reload(tmp_path,mid).state.actors[ALLY].current_hp==438



def test_defensive_flame_type_is_owners_off_turn_native_choice(tmp_path):
    from combat.canonical import canonical_sha256
    def setup(bundles):
        controls(bundles)
        order={OWNER:1000,ALLY:900,FOE:800}
        for bundle in bundles:
            bundle['actor_template']['initiative_bonus']=order[bundle['actor_id']]
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,bundle_transform=setup,
        owner_bundle=acquired_bundle(tmp_path,18),seed='HEARTHFIRE-RADIANT')
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id)
    settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':OWNER})
    turn(table,mid,ALLY)
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],
        choices={'choice:needle.hearth_defensive_damage':'RADIANT'})
    e=reload(tmp_path,mid)
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.hearth_defensive_damage' for p in prompts)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids and ev.payload.get('damage_type')=='RADIANT' for ev in e.events)
    assert e.state.actors[OWNER].resources['resource:core.qi']==95



def test_native_world_authority_cannot_be_supplied_by_creature_payload(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    before=cold().journey_state(jid)
    raw=weather(a)
    with pytest.raises(ValueError,match='table-owner'):
        cold().journey_act(jid,before['revision'],b,'hearth_weather',raw)
    assert cold().journey_state(jid)==before
    from combat.ext.qi_hearthfire_camp import WORLD_COMMANDS
    source,kind=WORLD_COMMANDS['hearth_weather']
    spoof={'source':source,'subject':b,'kind':kind,'scope':'spoof','value':{'ordinary':1},'expires_at':10000,'readers':[]}
    with pytest.raises(ValueError,match='table-owner'):
        cold().journey_act(jid,before['revision'],b,'declare_fact',spoof)
    assert cold().journey_state(jid)==before
    state=act('hearth_weather',raw,b)
    assert state['events'][-1]['blocked']==1
    world=[r for r in state['fact_consent_admission'] if r['authority']=='table_owner']
    assert world and state['actors'][b]['hearthfire']['weather_result']['world_receipt_id']==world[-1]['receipt_id']


def test_only_native_scene_boundary_recharges_welcome_and_expires_next_scene_fear(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    act('hearth_welcome',{'center':'self','invited':[a,b]})
    state=act('hearth_recovery',{'benefit':'fear'},b)
    before=state
    with pytest.raises(ValueError,match='table-owner'):
        act('hearth_scene_end',{'authority':'GM','reason':'I say so.'})
    assert cold().journey_state(jid)==before
    first=cold().journey_end_scene(jid,before['revision'],'The camp meeting ends; the party begins its next meaningful situation.')
    assert first['scene_number']==1 and first['actors'][b]['hearthfire']['fear_scene']==2
    assert any(o['kind']=='hearth_welcome' for o in cold().journey_menu(jid,a)['options'])
    second=cold().journey_end_scene(jid,first['revision'],'That next meaningful situation has now ended.')
    assert 'fear_scene' not in second['actors'][b]['hearthfire']
    assert second['actors'][a]['resources']['resource:core.qi']==92



def test_empowering_real_furnace_retains_physical_geometry_and_property_owner(tmp_path,monkeypatch):
    # Property title is a real native map-owner declaration, distinct from the
    # cultivator's later source/creator binding. No owner is inferred from kind.
    saved=CombatService(ROOT,tmp_path).tabletop_maps.save({'map_id':'hearth-property','display_name':'Guest-owned furnace',
        'width_squares':25,'height_squares':15,'objects':[{
            'id':91,'kind':'alchemy_furnace','x':5,'y':6,'height_ft':5,'weight_lb':200,
            'property_owner_id':'actor:factory.guest','asset_declaration':{
                'actor':'table-owner','authority':'GM','source_rule':'GM declares the guest owns this real furnace.',
                'visibility':'public','expiry':'source_rule'}}]})
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,
        arena_objects=saved['objects'])
    option=next(o for o in cold().journey_menu(jid,a)['options'] if o['payload'].get('existing')=='object:map.91')
    state=act('hearth_kindle',option['payload'])
    obj=state['runtime_objects']['object:map.91']
    assert obj['component']['blocks'] and obj['component']['structure']==obj['component']['hearth_original']['component']['structure']
    assert obj['owner_id']==obj['component']['hearth_original']['owner_id']==b
    assert obj['component']['asset_anchor_runtime']['owner']==a
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('move',{'path':[{'x':5,'y':6}]},b)
    assert cold().journey_state(jid)==before
    # Renewing the actual contained flame is legal even though its real object
    # blocks movement; it is not an empty-cell placement.
    state=act('hearth_kindle',option['payload'])
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    obj=loaded.engine.state.objects['object:map.91']
    assert obj.component['blocks'] and obj.object_kind=='alchemy_furnace'
    assert obj.owner_id==b and obj.component['asset_anchor_runtime']['owner']==a



def test_pavilion_native_cylinder_does_not_protect_creatures_below_its_base(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,
        arena_objects=[{'id':91,'kind':'stone_lantern','x':5,'y':6,'z':2,'height_ft':5,'weight_lb':10}])
    option=next(o for o in cold().journey_menu(jid,a)['options'] if o['payload'].get('existing')=='object:map.91')
    payload={**option['payload'],'invited':[a,b]}
    act('hearth_kindle',payload);state=act('hearth_pavilion')
    assert cold().journey_menu(jid,b)['properties']['hearth_ac_bonus']==0
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    from combat import ext
    assert sum(ext.run('ac',loaded.engine,loaded.engine.state.actors[b]))==0



def test_body_cl_and_unacquired_effect_names_cannot_supply_qi_progression(tmp_path):
    # Deliberately invalid imported IDs are a negative admission guard, not an
    # ownership fixture or a positive native-play receipt.
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Body',owner_features=FEATURES,bundle_transform=controls,seed='HEARTHFIRE-WRONG-PATH')
    e=reload(tmp_path,mid)
    names={e.action_catalog[c.source_definition_id].display_name for c in e.legal_candidates() if c.source_definition_id in e.action_catalog}
    assert not names & {'Kindled Hearth','Carry the Hearth','Flame That Welcomes All'}
    assert not any(z.trigger_profile.get('profile',{}).get('hearth_object') for z in e.state.zones.values())


@pytest.mark.parametrize('center',['self','hearth'])
@pytest.mark.parametrize('origin',['travel','combat','cancelled','gm_cancelled'])
def test_welcome_combat_travel_fresh_encounter_clock(tmp_path,monkeypatch,origin,center):
    from combat.tabletop_service import TabletopService
    from combat.ext.qi_hearthfire_persistence import CLOCK
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    if center=='hearth':kindle(act,a,b)
    if origin in ('travel','cancelled'):
        act('hearth_welcome',{'center':center,'invited':[a,b]})
        if origin=='cancelled':act('hearth_end_welcome')
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    if origin in ('combat','gm_cancelled'):
        for _ in range(2):
            if table.state(mid)['menu']['actor_id']==a:break
            settle(table,mid,table.state(mid)['menu']['end_turn'])
        settle(table,mid,candidate(cold(),mid,'Flame That Welcomes All').candidate_id,
            choices={'choice:needle.welcoming_center':center,'choice:needle.welcoming_allies':[a],'choice:needle.homefire_recovery':'temp_hp'})
    for _ in range(8):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold()._load_session(mid).engine.state.terminal_result is not None
    before=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,before['revision'],effect_resolutions={a:'The GM ends this sanctuary and its Concentration.'} if origin=='gm_cancelled' else None)
    props=cold().journey_menu(jid,a)['properties']
    if origin in ('cancelled','gm_cancelled'):
        assert not props.get('hearth_ac_bonus')
        result=begin_combat(cold,jid,resumed['revision'],{a:'team:a',b:'team:b'})
        fresh=cold()._load_session(result['match_id'])
        assert fresh.mechanical.replay()['status']=='PASS'
        assert fresh.engine.state.actors[a].concentration is None
        assert not any(z.active and (z.trigger_profile.get('profile') or {}).get('welcome') for z in fresh.engine.state.zones.values())
        return
    assert props['hearth_ac_bonus']==1
    assert not any(o['kind']=='hearth_welcome' for o in cold().journey_menu(jid,a)['options'])
    record=next(c.data for c in cold()._load_session(mid).engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert 0<record['welcome_remaining']<60
    act('wait',{'seconds':6})
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    fresh=cold()._load_session(result['match_id'])
    assert fresh.mechanical.replay()['status']=='PASS'
    field=next(z for z in fresh.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('welcome'))
    assert field.duration_rounds==(record['welcome_remaining']-6+5)//6
    assert field.trigger_profile['profile']['chosen_recipients']==([a] if origin=='combat' else [a,b])
    assert fresh.engine.state.actors[a].concentration.zone_id==field.zone_id

    assert (field.center.x,field.center.y,field.center.z)==((5,6,0) if center=='hearth' else (3,6,0))

@pytest.mark.parametrize('support',['roof','terrain'])
def test_elevated_kindled_hearth_menu_command_and_reload(tmp_path,monkeypatch,support):
    roof={'id':'native-roof','height_ft':10,'cells':[{'x':5,'y':6}]}
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,roofs=[roof] if support=='roof' else [],
        terrain=[{'terrain_type':'BLOCKED','cells':[{'x':5,'y':6}],'height_ft':10,'movement_cost':1}] if support=='terrain' else [])
    options=cold().journey_menu(jid,a)['options']
    elevated=next(o for o in options if o['kind']=='hearth_kindle' and o['payload']['position']=={'x':5,'y':6,'z':2})
    state=act(elevated['kind'],elevated['payload'])
    assert state['actors'][a]['hearthfire']['camp']['position']=={'x':5,'y':6,'z':2}
    before=state
    with pytest.raises(ValueError):act('hearth_kindle',{**elevated['payload'],'position':{'x':5,'y':6,'z':3}})
    assert cold().journey_state(jid)==before
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert next(o for o in loaded.engine.state.objects.values() if (o.component or {}).get('name')=='Kindled Hearth').position.z==2


def test_elevated_kindled_hearth_combat_menu_offers_authored_roof_level(tmp_path):
    """The combat CELL menu keeps an authored walking surface reachable."""
    cells=[{'x':x,'y':y} for x in range(6,10) for y in range(3,8)]
    def add_roof(arena):arena['roof_surfaces']=[{'id':'native-roof','height_ft':10,'cells':cells}]
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_pb=6,owner_features=FEATURES,
        bundle_transform=controls,seed='HEARTHFIRE-ROOF',battlefield_transform=add_roof)
    engine=combat._load_session(mid).engine
    kindled={(c.destination.x,c.destination.y,c.destination.z) for c in engine.legal_candidates()
             if getattr(engine.action_catalog.get(c.source_definition_id),'display_name',None)=='Kindled Hearth'}
    assert (6,6,0) in kindled,'the ground option must stay reachable'
    assert (6,6,2) in kindled,'an authored roof level must stay reachable for the combat menu'


def native_wound_guest(cold,jid,a,b,tmp_path):
    """Derive the injury from committed ordinary attacks, never a source receipt."""
    from combat.tabletop_service import TabletopService
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=20)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(42):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        e=loaded.engine
        if e.state.terminal_result is not None:break
        target=e.state.actors[b]
        if e.state.current_actor_id==a and target.current_hp>target.maximum_hp-12:
            attacks=[c for c in e.legal_candidates() if c.target_ids==(b,)
                and (e.action_catalog[c.source_definition_id].resolution_kind in ('ATTACK','MULTI_ATTACK') or any(r.get('type')=='attack' for r in (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',())))]
            assert attacks,'The native ordinary attack must be available.'
            settle(table,mid,attacks[0].candidate_id)
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    final=cold()._load_session(mid)
    assert final.mechanical.replay()['status']=='PASS'
    target=final.engine.state.actors[b]
    assert 0<target.current_hp<=target.maximum_hp-12
    before=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,before['revision'])
    assert resumed['actors'][b]['encounter_snapshot']['current_hp']==target.current_hp
    return target.current_hp


@pytest.mark.parametrize('owner',[None,'',42,{'actor':'pretend'}])
def test_property_title_requires_native_map_owner_declaration(tmp_path,owner):
    from combat.tabletop import TabletopError
    store=CombatService(ROOT,tmp_path).tabletop_maps
    row={'id':91,'kind':'stone_lantern','x':5,'y':6,'property_owner_id':owner,
        'asset_declaration':{'actor':'table-owner','authority':'GM','source_rule':'Property title',
                             'visibility':'public','expiry':'source_rule'}}
    with pytest.raises(TabletopError):store.save({'map_id':'bad-title','display_name':'Rejected title','objects':[row]})
    assert not (tmp_path/'combat_maps/bad-title.json').exists()


def test_ordinary_map_object_does_not_invent_property_title(tmp_path):
    store=CombatService(ROOT,tmp_path).tabletop_maps
    saved=store.save({'map_id':'ordinary-title','display_name':'Ordinary lantern',
        'objects':[{'id':91,'kind':'stone_lantern','x':5,'y':6}]})
    assert 'property_owner_id' not in saved['objects'][0]


def test_native_hearth_permits_only_chosen_touching_fuel_without_spread(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_features=FEATURES,owner_pb=6,
        owner_bundle=acquired_bundle(tmp_path,18),bundle_transform=controls,seed='HEARTHFIRE-FUEL',
        battlefield_transform=lambda doc:doc.update(map_objects=[
            {'id':91,'kind':'crate','x':5,'y':7},{'id':92,'kind':'crate','x':5,'y':8}]))
    settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id)
    before=reload(tmp_path,mid).state.actors[OWNER]
    balance=before.resources['resource:core.qi'];economy=(before.action_available,before.bonus_action_available)
    settle(table,mid,candidate(combat,mid,'Kindled Hearth: ignite ordinary fuel',target='object:map.91').candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.objects['object:map.91'].ignited
    assert not e.state.objects['object:map.92'].ignited
    assert e.state.actors[OWNER].resources['resource:core.qi']==balance
    assert (e.state.actors[OWNER].action_available,e.state.actors[OWNER].bonus_action_available)==economy
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert not any(e.action_catalog[c.source_definition_id].parameters.get('hearth_ignite_fuel')
        for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)


def test_real_body_path_is_default_inert_for_qi_imports(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Cultivation',
        owner_features=FEATURES,bundle_transform=controls,seed='HEARTHFIRE-BODY-PATH')
    e=reload(tmp_path,mid)
    assert not any((e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') in FEATURES
        for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)
    assert not any(r.get('block')=='qi_hearthfire' for r in e.typed_passive_rows[OWNER])


@pytest.mark.parametrize('fund_qi',[False,True])
def test_acquired_qi_row_cannot_spend_an_imported_body_budget(tmp_path,fund_qi):
    from combat.factory_compiler import compile_character
    doc=acquired_document(tmp_path,3)
    # Adversarial imported primary budget/high total CL. The actual acquired
    # Qi row remains CL3; no Qi balance or Body acquisition is fabricated.
    doc['identity']['cultivation_level']=18
    doc['identity']['path']='Body Cultivation'
    doc['ability_scores_and_statistics']['primary_resource']['name']='Stamina'
    if fund_qi:doc['ability_scores_and_statistics']['primary_resource']['definitions']=[{'name':'Qi','maximum':2}]
    doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.qi_cultivation',
        'effective_cl':3,'effective_pb':2,'key_ability':'CON'}]
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    combat,table,mid=fixture(tmp_path,[],cl=18,primary='Stamina',owner_path='Body Cultivation',
        owner_bundle=bundle,bundle_transform=controls,seed='HEARTHFIRE-NO-QI-BUDGET')
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.stamina']==100
    assert e.state.actors[OWNER].resources.get('resource:core.qi',0)==(2 if fund_qi else 0)
    assert any(r.get('feature_id')==FEATURES[0] and r['numbers']['cl']==3 for r in e.typed_passive_rows[OWNER])
    if fund_qi:
        settle(table,mid,candidate(combat,mid,'Kindled Hearth',at=(5,6)).candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.actors[OWNER].resources['resource:core.qi']==1
        assert e.state.actors[OWNER].resources['resource:core.stamina']==100
        assert next(o for o in e.state.objects.values() if (o.component or {}).get('asset_anchor_runtime')).maximum_hp==9
    else:
        assert not any((e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==FEATURES[0]
            for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)


@pytest.mark.parametrize('continuation',['wait','fresh_encounter'])
def test_threshold_survives_source_cancellation_until_its_own_next_turn(tmp_path,monkeypatch,continuation):
    from combat.tabletop_service import TabletopService
    from combat.ext.qi_hearthfire_sanctuary import THRESHOLD
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,dc=100,guest_kind='Undead')
    act('move',{'path':[{'x':5,'y':6},{'x':6,'y':6}]},b)
    act('hearth_welcome',{'center':'self','invited':[a]})
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(8):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    target=loaded.engine.state.actors[b]
    assert any(c.condition_id==THRESHOLD and c.data['failed'] for c in target.conditions.values())
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'],effect_resolutions={a:'The GM ends the source sanctuary and Concentration.'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='Threshold of Hospitality'):
        act('move',{'path':[{'x':5,'y':6}]},b)
    assert cold().journey_state(jid)==before
    if continuation=='wait':
        act('wait',{'seconds':6},b)
        act('move',{'path':[{'x':5,'y':6}]},b)
        assert cold().journey_state(jid)['actors'][b]['position']=={'x':5,'y':6}
    else:
        result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
        mid=result['match_id'];table=TabletopService(cold(),tmp_path)
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        assert any(e.event_type=='CONDITION_APPLIED' and e.payload.get('condition_id')==THRESHOLD for e in loaded.engine.events)
        turn(table,mid,b)
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        assert not any(c.condition_id==THRESHOLD for c in loaded.engine.state.actors[b].conditions.values())
        assert not any(z.active and z.trigger_profile.get('profile',{}).get('welcome') for z in loaded.engine.state.zones.values())


def test_civic_shelter_consumes_real_space_at_fixed_site_while_hearth_moves(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    state=act('hearth_shelter',{'people':180,'capacity':200,'authority':'GM','record_id':'fixed-space','expires_at':10000})
    center=dict(state['actors'][a]['hearthfire']['camp']['pavilion']['position'])
    act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    act('move',{'path':[{'x':3,'y':7},{'x':4,'y':7},{'x':5,'y':7},{'x':6,'y':7},{'x':7,'y':7},{'x':8,'y':7},{'x':9,'y':7},{'x':10,'y':7}]},a)
    for changes,protected in (({},180),({'source_cl':18},0),({'phenomenon':'poison_gas'},0),
            ({'ordinary':False},0),({'delivery':'technique'},0)):
        state=act('hearth_weather',weather(a,recipient='civic_shelter',record_id='civic-weather:'+str(changes),**changes),b)
        event=state['events'][-1]
        assert event['people_protected']==protected and event['civic_center']==center
        assert event['space_receipt_id']
    act('wait',{'seconds':10000-int(cold().journey_state(jid)['seconds'])},b)
    payload=act.admit('hearth_weather',weather(a,recipient='civic_shelter',record_id='expired-space',expires_at=11000),b)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='physical-space'):
        act('hearth_weather',payload,b)
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('field',['hearth','pavilion','welcome'])
@pytest.mark.parametrize('continuation',['elapsed','encounter'])
def test_actual_suppression_continues_its_own_clock_across_journey(tmp_path,monkeypatch,field,continuation):
    from combat.tabletop_service import TabletopService
    from combat.ext.area_suppression import suppressed,records
    # Both real imported sources have CL18. PB6/key-2 gives the Hearth DC12;
    # the real Unmaking user's PB6/key+5 guarantees its printed check succeeds.
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,dc=12,owner_score=6,
        guest_talents=['TAL_UNMAKING_LATTICE_UNRAVELING'],guest_score=20)
    if field!='welcome':kindle(act,a,b)
    if field=='pavilion':act('hearth_pavilion')
    if field=='welcome':act('hearth_welcome',{'center':'self','invited':[a]})
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    def matches(z):
        p=z.trigger_profile.get('profile',{})
        return z.active and (bool(p.get('welcome')) if field=='welcome' else bool(p.get('pavilion')) if field=='pavilion'
            else bool(p.get('hearth_object')) and not p.get('pavilion'))
    z=next(z for z in loaded.engine.state.zones.values() if matches(z))
    turn(table,mid,b)
    settle(table,mid,candidate(cold(),mid,'Lattice Unraveling',at=(z.center.x,z.center.y)).candidate_id,
        choices={'choice:needle.area_suppression':z.zone_id})
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS' and suppressed(loaded.engine.state.zones[z.zone_id])
    for _ in range(4):
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.terminal_result is not None and suppressed(loaded.engine.state.zones[z.zone_id])
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    property_name='hearth_frightened_advantage' if field=='hearth' else 'hearth_ac_bonus'
    assert not cold().journey_menu(jid,a)['properties'].get(property_name)
    if continuation=='elapsed':
        act('wait',{'seconds':5})
        assert not cold().journey_menu(jid,a)['properties'].get(property_name)
        state=act('wait',{'seconds':1})
        assert cold().journey_menu(jid,a)['properties'][property_name]==1
    else:
        result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
        mid=result['match_id'];table=TabletopService(cold(),tmp_path)
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        assert any(e.event_type=='ZONE_CREATED' and e.payload.get('zone',{}).get('trigger_profile',{}).get('suppressed') for e in loaded.engine.events)
        for _ in range(6):
            z=next(z for z in loaded.engine.state.zones.values() if matches(z))
            if not records(z):break
            settle(table,mid,table.state(mid)['menu']['end_turn'])
            loaded=cold()._load_session(mid)
            assert loaded.mechanical.replay()['status']=='PASS'
        assert not records(z)


def test_civic_space_and_people_survive_native_encounter_without_refilling_expiry(tmp_path,monkeypatch):
    from combat.tabletop_service import TabletopService
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    state=act('hearth_shelter',{'people':180,'capacity':200,'authority':'GM','record_id':'native-space','expires_at':10000})
    receipt=state['actors'][a]['hearthfire']['camp']['pavilion']['space_record']['receipt_id']
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(4):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    p=state['actors'][a]['hearthfire']['camp']['pavilion']
    assert p['people']==180 and p['space_record']['receipt_id']==receipt
    assert p['space_record']['expires_at']==9994
    state=act('hearth_weather',weather(a,recipient='civic_shelter',record_id='after-encounter'),b)
    assert state['events'][-1]['people_protected']==180


def test_independent_paid_pavilions_keep_both_fixed_sites_and_native_replay(tmp_path,monkeypatch):
    def pavilions(camp):return camp.get('pavilions',[camp['pavilion']] if camp.get('pavilion') else [])
    from combat.tabletop_service import TabletopService
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_pavilion')
    first=cold().journey_state(jid)['actors'][a]['hearthfire']['camp']['pavilion']
    old_id=first.get('id')
    act('hearth_shelter',{'people':180,'capacity':200,'authority':'GM','record_id':'first-space','expires_at':10000})
    act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    act('move',{'path':[{'x':x,'y':7} for x in range(3,14)]+[{'x':13,'y':6}]})
    act('wait',{'seconds':60})
    act('hearth_pavilion')
    state=cold().journey_state(jid);camp=state['actors'][a]['hearthfire']['camp']
    assert len(pavilions(camp))==2
    assert {p['position']['x'] for p in pavilions(camp)}=={5,13}
    assert next(p for p in pavilions(camp) if p['id']==old_id)['people']==180
    assert state['actors'][a]['resources']['resource:core.qi']==87
    for person in (a,b):assert cold().journey_menu(jid,person)['properties']['hearth_ac_bonus']==1
    choices=[o for o in cold().journey_menu(jid,a)['options'] if o['kind']=='hearth_permit_weather']
    assert len(choices)==2
    act('hearth_permit_weather',{'pavilion_id':old_id,'permitted':['rain']})
    assert act('hearth_weather',weather(a,record_id='old-site-rain'),b)['events'][-1]['blocked']==0
    assert act('hearth_weather',weather(a,record_id='new-site-rain'),a)['events'][-1]['blocked']==1
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(5):
        loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    wards=[z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('pavilion')]
    assert len(wards)==2
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    restored=pavilions(state['actors'][a]['hearthfire']['camp'])
    assert len(restored)==2
    assert next(p for p in restored if p['id']==old_id)['people']==180
    assert {p['position']['x'] for p in restored}=={5,13}


def test_two_actual_scene_welcomes_keep_independent_concentration_copies(tmp_path,monkeypatch):
    def welcomes(family):return family.get('welcomes',[family['welcome']] if family.get('welcome') else [])
    from combat.concentration import held
    from combat.tabletop_service import TabletopService
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b)
    act('hearth_welcome',{'center':'hearth','invited':[a]})
    state=cold().journey_state(jid)
    cold().journey_end_scene(jid,state['revision'],'The resolved camp discussion ends; a distinct urgent situation begins.')
    act('hearth_welcome',{'center':'self','invited':[a]})
    state=cold().journey_state(jid);fields=welcomes(state['actors'][a]['hearthfire'])
    assert len(fields)==2
    refs={w['activation_ref'] for w in fields};assert len(refs)==2
    assert {w['position']['x'] for w in fields}=={3,5}
    assert state['actors'][a]['resources']['resource:core.qi']==83
    assert len([o for o in cold().journey_menu(jid,a)['options'] if o['kind']=='hearth_end_welcome'])==2
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
    actor=loaded.engine.state.actors[a]
    assert len(list(held(actor)))+int(actor.concentration is not None)==2
    for _ in range(5):
        loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    assert {w['activation_ref'] for w in welcomes(state['actors'][a]['hearthfire'])}==refs
    chosen=next(iter(refs));state=act('hearth_end_welcome',{'activation_ref':chosen})
    assert {w['activation_ref'] for w in welcomes(state['actors'][a]['hearthfire'])}==refs-{chosen}
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    loaded=cold()._load_session(result['match_id']);assert loaded.mechanical.replay()['status']=='PASS'
    zones=[z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('welcome')]
    assert len(zones)==1 and zones[0].trigger_profile['profile']['activation_ref'] in refs-{chosen}


def begin_combat(cold,jid,revision,teams,**kwargs):
    """Explicit recipient fixture decisions through the real native menu."""
    state=cold().journey_state(jid)
    for who in state['actors']:
        options=cold().journey_menu(jid,who)['options']
        choice=next((o for o in options if o['kind']=='hearth_recovery' and o['payload']['benefit']=='fear'),None)
        if choice:
            state=cold().journey_act(jid,state['revision'],who,choice['kind'],choice['payload'])
    return cold().journey_start_combat(jid,state['revision'],teams,**kwargs)


def test_earned_recovery_choice_is_settled_by_recipient_before_native_entry(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b);act('hearth_welcome',{'center':'self','invited':[b]})
    before=cold().journey_state(jid)
    service=cold()
    with pytest.raises(ValueError,match='Homefire Recovery'):
        service.journey_start_combat(jid,before['revision'],{a:'team:a',b:'team:b'})
    assert cold().journey_state(jid)==before
    assert any(o['kind']=='hearth_recovery' for o in cold().journey_menu(jid,b)['options'])
    state=act('hearth_recovery',{'benefit':'temp_hp'},b)
    result=service.journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[b].temporary_hp==12
