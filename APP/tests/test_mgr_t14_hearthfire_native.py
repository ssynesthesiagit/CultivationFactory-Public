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


def journey(tmp_path,monkeypatch,*,cl=18,owned=True):
    def document(pid):
        s=acquired_document(tmp_path,cl) if owned and pid=='hearth' else sheet([],cl=cl,name=pid)
        s['identity']['name']=pid
        s['identity']['proficiency_bonus']=6
        s['ability_scores_and_statistics']['primary_resource']['maximum']=100
        return s
    import json,zipfile
    for pid in ('hearth','guest'):
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document(pid)))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'scene':{'stable_id':'hearth:test','width_squares':25,'height_squares':15,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}})
    cold=lambda:CombatService(ROOT,tmp_path)
    a,b='actor:factory.hearth','actor:factory.guest'
    state=cold().create_journey(project_ids=['hearth','guest'],arena_id='scene',positions={a:{'x':3,'y':6},b:{'x':4,'y':6}},base_paces={a:18000,b:18000})
    jid=state['journey_id']
    def act(kind,payload=None,actor=a):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],actor,kind,payload)
        assert cold().journey_state(jid)==result
        return result
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
    result=cold().journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})
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
        before=cold().journey_state(jid)
        with pytest.raises(ValueError):act('hearth_shelter',{'people':people,'capacity':capacity,'authority':'GM','record_id':'space','expires_at':30000})
        assert cold().journey_state(jid)==before
    state=act('hearth_shelter',{'people':180,'capacity':200,'authority':'GM','record_id':'space','expires_at':30000})
    assert state['events'][-1]['people']==180
    # A native route actually carries the listener outside the ward.
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    spoken=act('hearth_speak',{'text':'The tea is ready.','expires_at':30000})
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
    kindle(act,a,b)
    act('travel_exhaustion',{'levels':2,'ordinary':True},b)
    act('hearth_short_rest',{},b)
    state=act('hearth_recovery',{'benefit':benefit},b)
    assert state['actors'][b]['travel_uses'][FEATURES[1]]==0
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
        assert held[0].expires_on=='START_OF_TARGET_NEXT_TURN'
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


def test_welcome_no_guest_stable_once_and_outright_guard(tmp_path):
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
        combat,table,mid=fixture(path,[],cl=18,owner_pb=6,owner_features=FEATURES,bundle_transform=setup,seed='WELCOME-RESCUE',owner_bundle=acquired_bundle(path,18))
        settle(table,mid,candidate(combat,mid,'Flame That Welcomes All').candidate_id,
            choices={'choice:needle.welcoming_allies':[OWNER,ALLY],'choice:needle.homefire_recovery':'temp_hp'})
        turn(table,mid,FOE)
        settle(table,mid,candidate(combat,mid,name,target=ALLY).candidate_id,
            choices={'choice:needle.hearth_shield':None,'choice:needle.hearth_rescue_move':None})
        e=reload(path,mid)
        actor=e.state.actors[ALLY]
        assert (actor.life_state=='STABLE')==stable
        if stable:
            assert actor.current_hp==0 and actor.temporary_hp==12
            assert any(z.per_turn_triggered.get('welcome_saved:'+ALLY)==1 for z in e.state.zones.values())


def test_real_empowered_item_native_pickup_consent_and_no_duplicate(tmp_path):
    from tests.test_a2_qi_subpaths_7 import fight
    combat,table,mid=fight(tmp_path,carry=True,empowered=True,owner_bundle=acquired_bundle(tmp_path,18))
    e=reload(tmp_path,mid)
    assert e.state.objects['object:map.91'].component['hearth_original']['object_id']=='object:map.91'
    assert any(c.condition_id=='condition:typed.hearth_item_custody' for c in e.state.actors[ALLY].conditions.values())
    prompts=settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':ALLY,'choice:needle.carry_hearth_consent':'carry'})
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


def acquired_document(tmp_path,cl,*,dc=18):
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
    assert cold.get_state(pid)==selected
    path=next(r for r in selected['paths'] if r['path_id']==qi)
    assert path['subpath_or_tradition_id']==parent
    projection=cold.project_locked_subpath_catalog_record(path['subpath_or_tradition_id'])
    progression=projection['compatibility']['factory']['stage2_authority']['feature_progression']
    ids=[r['canonical_id'] for r in progression if r['granted_at_cl']<=path['attainment']]
    assert ids==[f for f,l in zip(FEATURES,(3,6,10,14,18)) if l<=cl]
    doc=sheet([],cl=path['attainment'],dc=dc);doc['identity']['proficiency_bonus']=6
    doc['path_and_subpath']={'path_feature_record_ids':ids}
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
    result=cold().journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=2)
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
    result=cold().journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    engine=loaded.engine
    rows=perception(engine,engine.state.actors[b])['information']
    assert len(rows)==1 and rows[0]['viewer_id']==b and 'words' not in rows[0]['details']
    assert not perception(engine,engine.state.actors[a]).get('information')
