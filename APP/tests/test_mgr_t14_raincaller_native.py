"""Real seeded acquisition -> installed combat/table -> cold reload/replay."""
from pathlib import Path
import shutil
import pytest
from app.api import create_app
from app.core import Settings
from product_bootstrap.service import ProductBootstrapService
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
ROOT=Path(__file__).resolve().parents[1]
P='tianxia.subpath.qi.raincaller_cultivator.feature.'
ALL=[P+n for n in ('call_rain','shape_the_rain','monsoon_wall','provincial_rain_rite','monsoon_sovereign')]

@pytest.fixture(scope='module')
def installed(tmp_path_factory):
    from ai_provider.service import AIProviderService
    from unittest.mock import patch
    root=tmp_path_factory.mktemp('rain-acquisition');settings=Settings.from_env(ROOT,root/'userdata')
    def forbidden(*a,**k):raise AssertionError('No model transport in native seeded acquisition')
    with patch.object(AIProviderService,'complete_json',forbidden):
        ProductBootstrapService(settings).run();app=create_app(settings)
        built=app.state.character_builder.create_project(working_name='Raincaller',concept='An open-school raincaller cultivator.',
            target_cl=18,power_band='standard',source_reference=None,creation_mode='detailed',ability_scores={},
            generation_route='ai_bootstrap',autogen_seed='RAINCALLER-NATIVE-18',
            selections={'path_choice':['tianxia.path.qi_cultivation'],'subpath_choice':['tianxia.subpath.qi.raincaller_cultivator']})
        pid=built['project_id']
        run=app.state.character_creation.start(pid,execution_mode='STANDARD_API',idempotency_key='rain-native-full',
            controller_route='DETERMINISTIC_CREATIVE_CONTROLLER',combat_ready=True)
        assert run['status']=='READY_FOR_REVIEW',run.get('blockers')
        final=app.state.character_creation.finalize(run['run_id']);assert final['status']=='CLEAN_AND_FINALIZED',final.get('blockers')
    return settings.data_dir,pid

@pytest.fixture
def native(tmp_path,installed):
    original,pid=installed;data=tmp_path/'userdata';shutil.copytree(original,data)
    combat=CombatService(ROOT,data);owner='actor:factory.'+pid
    match=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[AN],
        control_modes={owner:'MANUAL',AN:'MANUAL'},arena_id='battlefield:factory_pillar_arena',match_seed='RAIN-NATIVE')
    return Play(combat,TabletopService(combat,data),match['match_id'],owner,data)

class Play:
    def __init__(self,combat,table,mid,owner,data):self.combat,self.table,self.mid,self.owner,self.data=combat,table,mid,owner,data
    def load(self):
        loaded=CombatService(ROOT,self.data)._load_session(self.mid)
        assert loaded.verify()['status']=='PASS';assert loaded.mechanical.replay()['status']=='PASS'
        return loaded.engine
    def commit(self,cid,picks=None):
        answers=[];prompts=[];picks=picks or {}
        for _ in range(35):
            menu=self.table.state(self.mid)['menu'];result=self.table.act(self.mid,cid,menu['decision_id'],menu['state_version'],0,answers)
            if result['status']=='COMMITTED':self.load();return prompts
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];prompts.append(p);answer={**p['context'],'selection':'DECLINE'}
            if p.get('choice'):
                c=p['choice'];rid=p['context']['reaction_source_id'];v=picks.get(rid,c.get('preferred') or [c['options'][0]['id']])
                if v is not None:answer.update(selection='USE',option_ids=v if isinstance(v,list) else [v])
            answers.append(answer)
        raise AssertionError('Too many choices')
    def turn(self,aid=None,picks=None):
        aid=aid or self.owner
        for _ in range(10):
            if self.table.state(self.mid)['menu']['actor_id']==aid:return
            self.commit(self.table.state(self.mid)['menu']['end_turn'],picks)
        raise AssertionError('Turn unavailable')
    def next(self,picks=None):
        self.commit(self.table.state(self.mid)['menu']['end_turn'],picks);self.turn(picks=picks)
    def candidate(self,name,at=None):
        e=self.combat._load_session(self.mid).engine
        rows=[c for c in e.legal_candidates() if getattr(e.action_catalog.get(c.source_definition_id),'display_name',None)==name
              and (at is None or c.destination and c.destination.model_dump()==at)]
        assert rows,name
        return rows[0]
    def cast(self,name,picks=None):
        self.turn();e=self.combat._load_session(self.mid).engine
        at=e.state.actors[self.owner].position.model_dump() if name in ('Call Rain','Monsoon Wall','Monsoon Sovereign') else None
        c=self.candidate(name,at=at);return self.commit(c.candidate_id,picks)

def test_native_acquisition_call_rain_choices(native):
    p=native;prompts=p.cast('Call Rain',{'choice:needle.rain_form':'restorative'})
    assert any(x['context']['reaction_source_id']=='choice:needle.rain_form' for x in prompts)
    rain=[z for z in p.load().state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='call']
    assert len(rain)==1;assert rain[0].trigger_profile['height_ft']==20
    assert rain[0].trigger_profile['profile']['form']=='restorative'

@pytest.mark.parametrize('form', ['mist','heavy','restorative','driving','cleansing'])
def test_all_five_forms_have_one_persistent_area(native,form):
    p=native;p.cast('Call Rain',{'choice:needle.rain_form':form})
    z=next(z for z in p.load().state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='call')
    assert z.trigger_profile['profile']['form']==form
    assert z.trigger_profile.get('difficult')==('hostile' if form=='heavy' else None)
    assert z.trigger_profile.get('obscured')==('light' if form=='mist' else None)
    p.next({'choice:needle.rain_form':form})
    e=p.load();assert any(z.active and z.zone_id==zid for zid in [z.zone_id] for z in e.state.zones.values())
    assert len([z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='call'])==1


def test_monsoon_wall_is_persistent_and_does_not_save_on_activation(native):
    p=native;p.cast('Monsoon Wall')
    e=p.load();z=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='wall')
    assert z.duration_rounds==10 and z.concentration_link
    assert z.trigger_profile['height_ft']==10
    assert z.trigger_profile['wall']['thick_ft']==5
    assert z.trigger_profile['obscured']=='heavy'
    assert z.trigger_profile['difficult']=='hostile'
    assert len(z.affected_cells)<=6
    assert not any(r.reason.startswith('SAVE:') and r.actor_id==AN for r in e.rolls)


@pytest.mark.parametrize('decree',['gentle','flood','purification','lightning','veiling','channel'])
def test_sovereign_is_one_paid_field_with_six_free_start_turn_decrees(native,decree):
    p=native;p.cast('Monsoon Sovereign')
    e=p.load();before=e.state.actors[p.owner].resources['resource:core.qi']
    field=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='sovereign')
    assert field.trigger_profile['height_ft']==50
    p.next({'choice:needle.rain_decree':decree})
    e=p.load();assert e.state.actors[p.owner].resources['resource:core.qi']==before
    assert not any(getattr(e.action_catalog.get(c.source_definition_id),'display_name','')=='Monsoon Sovereign' for c in e.legal_candidates())


@pytest.fixture
def civil(tmp_path,installed):
    original,pid=installed;data=tmp_path/'civil';shutil.copytree(original,data)
    combat=CombatService(ROOT,data);aid='actor:factory.'+pid
    state=combat.create_journey(project_ids=[pid],arena_id='battlefield:factory_pillar_arena',positions={aid:{'x':3,'y':6}},base_paces={aid:3000})
    return combat,aid,state['journey_id']


def site_profile():
    def f(id,kind,**kw):
        return dict(**({'fire_kind':'wildfire','source_duration':'persistent'} if kind in ('ordinary_fire','supernatural_fire') else {}),id=id,name=id.replace('-',' ').title(),kind=kind,position={'x':3,'y':6},source_cl=0,save_dc=0,ordinary=1,attended=0,amount=10,alive=1,viable=1,permanent=0,useful=1,save_bonus=0,**kw)
    return {'plane':'Material','center':{'x':3,'y':6},'open_space':1,'sealed':0,'clear_zones':[],
        'containers':[{'id':'stone-cistern','name':'Stone cistern','kind':'cistern','open':1,'position':{'x':3,'y':6},'capacity':20,'water':0}],
        'features':[f('brush-fire','ordinary_fire'),f('smoke','smoke'),f('dust','dust'),f('ash','ash'),f('pollen','pollen'),
                    f('pollution','pollution'),f('soil','soil'),f('living-crop','plant'),f('pond','pond'),f('heat','heat'),f('lava','lava'),f('irritant','irritant')]}


def scene(civil,site=None):
    combat,aid,jid=civil
    state=combat.journey_state(jid)
    state=combat.journey_world_fact(jid,state['revision'],{'source':ALL[0],'subject':aid,'kind':'rain_site','scope':'site',
        'value':{**(site or site_profile()),'allies':(site or {}).get('allies',[aid])},'expires_at':604800,'readers':[aid]})
    return combat.journey_act(jid,state['revision'],aid,'rain_site',{'scope':'site'})


def command(civil,kind,payload):
    combat,aid,jid=civil;s=combat.journey_state(jid)
    result=combat.journey_act(jid,s['revision'],aid,kind,payload)
    if kind=='rain_rite':
        assert result['actors'][aid]['source_states']['journey:activity']['worked_seconds']==0
        result=combat.journey_act(jid,result['revision'],aid,'activity_work',{'seconds':600})
    cold=CombatService(ROOT,combat.userdata_root)
    assert cold.journey_state(jid)==result
    assert cold.journey_verify(jid)['status']=='PASS'
    return result


def rainstate(state,aid):
    return state['actors'][aid]['source_states'][P]


def test_call_rain_native_world_collection_and_water_cadence(civil):
    combat,aid,jid=civil;scene(civil)
    s=command(civil,'rain_call',{'form':'cleansing','allies':[aid]})
    r=rainstate(s,aid);assert r['rains']['call']['expires_at']-s['seconds']==60
    features={f['id']:f for f in r['site']['features']}
    assert features['brush-fire']['amount']==0 and features['irritant']['amount']==0
    assert features['smoke']['suppressed_until']>s['seconds']
    assert 'suppressed_until' not in features['pollution']
    s=command(civil,'rain_collect',{'container':'stone-cistern'})
    assert rainstate(s,aid)['site']['containers'][0]['water']==1
    assert rainstate(s,aid)['site']['containers'][0]['clean_rainwater']==1
    with pytest.raises(ValueError,match='one waterskin'):command(civil,'rain_collect',{'container':'stone-cistern'})
    fire_event(civil,{'kind':'ordinary_ignition','feature':'brush-fire','cause':'Actual external ordinary ignition attempt'})
    assert next(f for f in rainstate(combat.journey_state(jid),aid)['site']['features'] if f['id']=='brush-fire')['amount']==0
    command(civil,'wait',{'seconds':6})
    s=command(civil,'rain_collect',{'container':'stone-cistern'})
    assert rainstate(s,aid)['site']['containers'][0]['water']==2
    s=command(civil,'wait',{'seconds':54})
    assert not rainstate(s,aid)['rains']
    with pytest.raises(ValueError,match='active'):command(civil,'rain_collect',{'container':'stone-cistern'})


@pytest.mark.parametrize('effects',[['steady','drought'],['firebreak','clearing'],['cooling','agriculture'],['mist']])
def test_provincial_rite_native_ten_minute_setup_and_eight_hour_clock(civil,effects):
    combat,aid,jid=civil;scene(civil)
    s=command(civil,'rain_rite',{'effects':effects,'clear_zones':[]})
    state=rainstate(s,aid);rite=state['rains']['rite']
    assert s['seconds']==600 and rite['expires_at']==29400
    assert rite['effects']==effects and rite['radius_ft']==5280
    s=command(civil,'wait',{'seconds':600});state=rainstate(s,aid)
    features={f['id']:f for f in state['site']['features']}
    if 'clearing' in effects:assert features['pollution']['suppressed_until']==29400
    if 'firebreak' in effects:assert features['brush-fire']['amount']==0
    if 'drought' in effects:assert features['soil']['normal_moisture_days']==1
    if 'cooling' in effects:
        assert features['heat']['tolerable_until']==29400
        assert 'tolerable_until' not in features['lava']
    if 'agriculture' in effects:assert state['blessings'][0]['expires_at']==605400
    s=command(civil,'wait',{'seconds':28200});state=rainstate(s,aid)
    assert not state['rains']
    if 'steady' in effects:assert next(f for f in state['site']['features'] if f['id']=='pond')['rain_inches_num']==28800
    if 'agriculture' in effects:assert state['blessings']


@pytest.mark.parametrize('flag',['sealed','open_space'])
def test_native_rain_rejects_sealed_or_insufficient_space_without_payment(civil,flag):
    combat,aid,jid=civil;site=site_profile();site[flag]=1 if flag=='sealed' else 0
    s=scene(civil,site);before=s['actors'][aid]['resources']
    with pytest.raises(ValueError,match='open space'):command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert combat.journey_state(jid)['actors'][aid]['resources']==before


def test_world_input_cannot_be_supplied_by_subject_controller(civil):
    combat,aid,jid=civil;s=combat.journey_state(jid)
    with pytest.raises(ValueError,match='table-owner'):
        command(civil,'declare_fact',{'source':ALL[0],'subject':aid,'kind':'rain_site','scope':'site','value':site_profile(),'expires_at':100,'readers':[aid]})
    assert combat.journey_state(jid)==s


def test_native_crop_advantage_and_blessing_survives_rite_expiry(civil):
    combat,aid,jid=civil;site=site_profile()
    heat=next(f for f in site['features'] if f['kind']=='heat');heat['save_dc']=12
    scene(civil,site);command(civil,'rain_rite',{'effects':['agriculture'],'clear_zones':[]})
    s=command(civil,'rain_crop_save',{'plant':'living-crop','hazard':'heat'})
    assert s['events'][-1]['roll']['mode']=='ADVANTAGE'
    command(civil,'wait',{'seconds':28800})
    s=command(civil,'rain_crop_save',{'plant':'living-crop','hazard':'heat'})
    assert s['events'][-1]['roll']['mode']=='ADVANTAGE'
    command(civil,'wait',{'seconds':604800-28800})
    s=command(civil,'rain_crop_save',{'plant':'living-crop','hazard':'heat'})
    assert s['events'][-1]['roll']['mode']=='NORMAL'


def test_source_cl_contests_happen_once_on_rite_start_and_ordinary_fire_is_distinct(civil):
    combat,aid,jid=civil;site=site_profile()
    for i,cl in enumerate((17,18,19)):
        f=dict(site['features'][0]);f.update(id='cultivated-fire-'+str(cl),kind='supernatural_fire',ordinary=0,authority_grade='ordinary',source_cl=cl,save_dc=100 if cl==19 else 1)
        site['features'].append(f)
    scene(civil,site)
    s=command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert all('suppressed_until' not in f for f in rainstate(s,aid)['site']['features'] if f['kind']=='supernatural_fire')
    command(civil,'wait',{'seconds':60})
    s=command(civil,'rain_rite',{'effects':['firebreak'],'clear_zones':[]})
    features={f['id']:f for f in rainstate(s,aid)['site']['features']}
    assert features['cultivated-fire-17']['suppressed_until']>s['seconds']
    assert features['cultivated-fire-18']['suppressed_until']>s['seconds']
    assert 'suppressed_until' not in features['cultivated-fire-19']
    checks=[e for e in s['events'] if e['kind']=='RAIN_CULTIVATION_CHECK']
    assert len(checks)==2
    s=command(civil,'wait',{'seconds':120})
    assert len([e for e in s['events'] if e['kind']=='RAIN_CULTIVATION_CHECK'])==2


def test_native_rite_rejects_three_effects_and_preserves_dead_crop_and_permanent_damage(civil):
    combat,aid,jid=civil;site=site_profile()
    plant=next(f for f in site['features'] if f['kind']=='plant');plant.update(alive=0,viable=0,permanent=1)
    scene(civil,site);before=combat.journey_state(jid)
    with pytest.raises(ValueError,match='one or two'):command(civil,'rain_rite',{'effects':['steady','cooling','agriculture']})
    assert combat.journey_state(jid)==before
    s=command(civil,'rain_rite',{'effects':['drought','agriculture']})
    plant=next(f for f in rainstate(s,aid)['site']['features'] if f['kind']=='plant')
    assert plant['alive']==0 and plant['permanent']==1 and not rainstate(s,aid)['blessings']


def test_native_cistern_fills_only_over_full_steady_rain_and_no_collection_after_call(civil):
    combat,aid,jid=civil;scene(civil)
    s=command(civil,'rain_rite',{'effects':['steady']})
    assert rainstate(s,aid)['site']['containers'][0]['water']==0
    s=command(civil,'wait',{'seconds':14400})
    assert rainstate(s,aid)['site']['containers'][0]['water']==1
    assert rainstate(s,aid)['site']['containers'][0]['clean_rainwater']==10
    s=command(civil,'wait',{'seconds':14400})
    assert rainstate(s,aid)['site']['containers'][0]['water']==20
    with pytest.raises(ValueError,match='Call Rain'):command(civil,'rain_collect',{'container':'stone-cistern'})


def test_native_rite_work_can_be_interrupted_without_awarding_rain(civil):
    combat,aid,jid=civil;scene(civil)
    s=combat.journey_state(jid);before=s['actors'][aid]['resources']['resource:core.qi']
    s=combat.journey_act(jid,s['revision'],aid,'rain_rite',{'effects':['steady','cooling']})
    assert s['actors'][aid]['resources']['resource:core.qi']==before-5
    assert not rainstate(s,aid)['rains']
    s=command(civil,'activity_work',{'seconds':599})
    assert not rainstate(s,aid)['rains']
    s=command(civil,'wait',{'seconds':1})
    assert 'journey:activity' not in s['actors'][aid]['source_states']
    assert not rainstate(s,aid)['rains']
    with pytest.raises(ValueError,match='remaining'):command(civil,'activity_work',{'seconds':1})


def test_wrong_owner_has_no_rain_actions_or_ambient_state(native):
    p=native;e=p.load();other=e.state.actors[AN]
    assert not any((e.action_catalog[s].parameters.get('typed') or {}).get('source') in ALL for s in other.action_ids)
    assert not any(c.condition_id in ('condition:typed.raincaller_site','condition:typed.raincaller_scene_use') for c in other.conditions.values())
    assert not any(z.trigger_profile.get('profile',{}).get('rain_family') for z in e.state.zones.values())


def test_native_restorative_rain_turn_clock_grants_real_temporary_hp(civil):
    combat,aid,jid=civil;scene(civil)
    s=command(civil,'rain_call',{'form':'restorative','allies':[aid]})
    assert 'encounter_snapshot' not in s['actors'][aid]
    s=command(civil,'wait',{'seconds':6})
    pb=rainstate(s,aid)['rains']['call']['numbers']['pb']
    assert s['actors'][aid]['encounter_snapshot']['temporary_hp']==pb
    count=len([e for e in s['events'] if e['kind']=='RAIN_TEMP_HP_GRANTED'])
    s=command(civil,'wait',{'seconds':0})
    assert len([e for e in s['events'] if e['kind']=='RAIN_TEMP_HP_GRANTED'])==count
    s=command(civil,'wait',{'seconds':54})
    assert not rainstate(s,aid)['rains']
    assert s['actors'][aid]['encounter_snapshot']['temporary_hp']==pb


def affliction(play,identity,category,*,cl=1,ordinary=0,tags=None,symptoms=None,dc=10,success=None,authority='ordinary',counter=None,basis=None):
    """Actual table-owner input through the replayed native world transaction."""
    row={'id':identity,'label':identity.replace('-',' ').title(),'category':category,
         'source':'external:world.'+identity,'save_ability':'CON','save_dc':dc,
         'source_cl':cl,'ordinary':ordinary,'cause_tags':tags if tags is not None else ['poison'],'authority_grade':authority,
         'save_success':success or {'kind':'end_episode' if 'disease' in category else 'end_condition'}}
    if symptoms is not None:row['imposed_conditions']=symptoms
    if counter is not None:row.update(counterprocedures=counter,authority_basis=basis)
    e=play.load()
    result=play.table.world_fact(play.mid,e.state.state_version,
        {'source':'journey:external_effect','subject':play.owner,'kind':'effect','scope':identity,
         'value':row,'expires_at':3600,'readers':[]},'actual-affliction-'+identity)
    assert result['status']=='COMMITTED';play.load()
    return row


def episodes(play):
    return {c.data['journey_effect_id'] for c in play.load().state.actors[play.owner].conditions.values() if c.data.get('journey_effect_id')}


@pytest.mark.parametrize('procedure,category,tags',[
    ('poison','poisoned',['poison']),('airborne','airborne_blinded',['dust'])])
def test_purification_ends_all_lower_equal_instances_and_keeps_other_causes(native,procedure,category,tags):
    p=native;p.turn()
    affliction(p,'low',category,cl=17,tags=tags)
    affliction(p,'equal',category,cl=18,tags=tags)
    affliction(p,'high',category,cl=19,tags=tags,dc=35)
    affliction(p,'eye-injury','injury_blinded',cl=1,ordinary=1,tags=['injury'])
    p.cast('Monsoon Sovereign')
    p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':procedure})
    assert episodes(p)=={'high','eye-injury'}


def test_purification_ends_one_disease_episode_with_all_its_symptoms(native):
    p=native;p.turn()
    affliction(p,'fever','ordinary_disease',cl=0,ordinary=1,tags=['disease'],symptoms=['poisoned','sickened'])
    affliction(p,'cough','ordinary_disease',cl=0,ordinary=1,tags=['disease'])
    p.cast('Monsoon Sovereign')
    p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'disease','choice:needle.rain_purify_episode':'fever'})
    assert episodes(p)=={'cough'}


def test_call_rain_washes_only_ordinary_airborne_blindness(native):
    p=native;p.turn()
    affliction(p,'dust','airborne_blinded',ordinary=1,tags=['dust'])
    affliction(p,'supernatural-ash','airborne_blinded',cl=3,tags=['ash'])
    affliction(p,'eye-injury','injury_blinded',ordinary=1,tags=['injury'])
    affliction(p,'venom','poisoned')
    p.cast('Call Rain')
    assert episodes(p)=={'supernatural-ash','eye-injury','venom'}


def test_world_affliction_rejects_invented_cause_and_replayed_episode_atomically(native):
    p=native;p.turn();before=p.load().state.state_version
    with pytest.raises(Exception,match='actual poison'):
        affliction(p,'bad','poisoned',tags=['injury'])
    assert p.load().state.state_version==before
    affliction(p,'real','poisoned')
    before=p.load().state.state_version
    with pytest.raises(Exception,match='episode identity'):
        affliction(p,'real','poisoned')
    assert p.load().state.state_version==before


def test_finish_reopen_preserves_remaining_rain_duration_and_water(civil):
    combat,aid,jid=civil;scene(civil)
    command(civil,'rain_call',{'form':'restorative','allies':[aid]})
    command(civil,'rain_collect',{'container':'stone-cistern'})
    s=command(civil,'wait',{'seconds':30});remaining=rainstate(s,aid)['rains']['call']['expires_at']-s['seconds']
    command(civil,'finish',{})
    pid=aid.removeprefix('actor:factory.')
    reopened=combat.create_journey(project_ids=[pid],arena_id='battlefield:factory_pillar_arena',positions={aid:{'x':3,'y':6}},base_paces={aid:3000})
    assert rainstate(reopened,aid)['rains']['call']['expires_at']==remaining
    assert rainstate(reopened,aid)['site']['containers'][0]['water']==1
    assert combat.journey_verify(reopened['journey_id'])['status']=='PASS'
    later=command((combat,aid,reopened['journey_id']),'wait',{'seconds':remaining})
    assert not rainstate(later,aid)['rains']


def test_rain_washes_new_native_world_irritant_while_active(native):
    p=native;p.cast('Call Rain');affliction(p,'fresh-dust','airborne_blinded',ordinary=1,tags=['dust'])
    assert 'fresh-dust' not in episodes(p)


def test_native_qi_zero_has_one_real_exhaustion_consequence(civil):
    combat,aid,jid=civil;scene(civil)
    before=combat.journey_state(jid)['actors'][aid]['exhaustion']
    amount=combat.journey_state(jid)['actors'][aid]['resources']['resource:core.qi']
    for _ in range(amount):s=command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert s['actors'][aid]['resources']['resource:core.qi']==0
    assert s['actors'][aid]['exhaustion']==before+1
    assert sum(e['kind']=='QI_ZERO_EXHAUSTION' for e in s['events'])==1
    with pytest.raises(ValueError):command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert combat.journey_state(jid)==s


@pytest.mark.parametrize('category,tags',[('poisoned',['poison']),('supernatural_disease',['disease']),('airborne_blinded',['ash'])])
def test_higher_cl_purification_repeats_actual_original_save_with_advantage(native,category,tags):
    p=native;p.turn();affliction(p,'higher-effect',category,cl=19,tags=tags,dc=1)
    p.cast('Monsoon Sovereign')
    p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'repeat','choice:needle.rain_purify_episode':'higher-effect'})
    e=p.load();assert 'higher-effect' not in episodes(p)
    original=[r for r in e.rolls if r.actor_id==p.owner and r.reason.endswith(':CON')]
    assert original and original[-1].mode=='ADVANTAGE'


def test_sovereign_free_origin_is_reachable_without_a_water_container(native):
    p=native;p.cast('Monsoon Sovereign')
    e=p.load();qi=e.state.actors[p.owner].resources['resource:core.qi']
    prompts=p.cast('Monsoon Sovereign: choose rain origin')
    assert any(r['context']['reaction_source_id']=='choice:needle.rain_origin' for r in prompts)
    e=p.load();assert e.state.actors[p.owner].resources['resource:core.qi']==qi
    chosen=[c for c in e.state.actors[p.owner].conditions.values() if c.condition_id=='condition:typed.raincaller_origin']
    assert len(chosen)==1


def test_monsoon_wall_uses_actual_native_free_wall_point_plan(native):
    p=native;p.turn();e=p.load();pos=e.state.actors[p.owner].position
    # The generic native wall-plan commands, not synthetic zone cells.
    points=[]
    for candidate in e.legal_candidates():
        action=e.action_catalog.get(candidate.source_definition_id)
        if action and action.display_name=='Wall point' and candidate.destination and candidate.destination!=pos:
            points.append(candidate)
    assert points
    first=min(points,key=lambda c:e.grid.distance_ft(pos,c.destination))
    p.commit(first.candidate_id)
    p.cast('Monsoon Wall')
    e=p.load();z=next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='wall')
    assert (first.destination.x,first.destination.y) in {(c.x,c.y) for c in z.affected_cells}
    assert not any(c.condition_id=='condition:typed.wall_plan' for c in e.state.actors[p.owner].conditions.values())


def test_native_world_input_history_and_private_diagnosis_are_not_public_pills(native):
    p=native;p.turn();affliction(p,'secret-venom','poisoned')
    from combat.history_feed import concealed_condition_instances
    e=p.load();hidden=concealed_condition_instances(e.state.model_dump(mode='json'))
    histories=[c for c in e.state.actors[p.owner].conditions.values() if c.condition_id=='condition:world.fact_history']
    assert histories and all(c.instance_id in hidden for c in histories)
    condition=next(c for c in e.state.actors[p.owner].conditions.values() if c.data.get('journey_effect_id')=='secret-venom')
    assert condition.data['label']=='Poisoned'
    assert condition.data['private_label']=='Secret Venom'


def test_gentle_rain_heals_actual_native_attack_damage(native):
    p=native;p.turn(AN);e=p.load()
    attacks=[c for c in e.legal_candidates() if p.owner in c.target_ids and e.action_catalog.get(c.source_definition_id)
             and e.action_catalog[c.source_definition_id].damage is not None]
    assert attacks,'The native opposing fighter needs a legal damaging action.'
    selected=min(attacks,key=lambda c:e.action_catalog[c.source_definition_id].save is None)
    p.commit(selected.candidate_id);p.turn()
    e=p.load();patient=e.state.actors[p.owner];assert 0<patient.current_hp<patient.maximum_hp
    p.cast('Monsoon Sovereign');before=p.load().state.actors[p.owner].current_hp
    p.next({'choice:needle.rain_decree':'gentle'})
    patient=p.load().state.actors[p.owner]
    assert before<patient.current_hp<=patient.maximum_hp


def test_lightning_decree_resolves_actual_hostile_save_damage_and_ally_exclusion(native):
    p=native;p.cast('Monsoon Sovereign');e=p.load();enemy=e.state.actors[AN]
    point=f'{enemy.position.x},{enemy.position.y},{enemy.position.z}'
    before=enemy.current_hp;own=e.state.actors[p.owner].current_hp
    start=len(e.rolls)
    p.next({'choice:needle.rain_decree':'lightning','choice:needle.rain_point':point})
    e=p.load();assert e.state.actors[AN].current_hp<before
    assert e.state.actors[p.owner].current_hp==own
    saves=[r for r in e.rolls[start:] if r.actor_id==AN and r.reason.endswith(':DEX')]
    assert len(saves)==1
    failed=saves[0].total<next(z for z in e.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='sovereign').trigger_profile['numbers']['save_dc']
    denied=any(c.condition_id=='condition:typed.reaction_denied' for c in e.state.actors[AN].conditions.values())
    assert denied==failed


@pytest.mark.parametrize('ability',['Call Rain','Monsoon Wall','Monsoon Sovereign'])
def test_native_combat_rain_consumes_actual_world_environment_profile(native,ability):
    p=native;p.turn();e=p.load();site=site_profile();site['allies']=[p.owner]
    location=e.state.actors[p.owner].position.model_dump(mode='json');site['center']=location
    for feature in site['features']:feature['position']=location
    for container in site['containers']:container['position']=location
    result=p.table.world_fact(p.mid,e.state.state_version,
        {'source':ALL[0],'subject':p.owner,'kind':'rain_site','scope':'encounter-site',
         'value':site,'expires_at':3600,'readers':[]},'actual-environment')
    assert result['status']=='COMMITTED';p.load();p.cast(ability)
    e=p.load();held=next(c for c in e.state.actors[p.owner].conditions.values() if c.condition_id=='condition:typed.raincaller_site')
    features={f['id']:f for f in held.data['state']['site']['features']}
    assert features['brush-fire']['amount']==0
    if ability=='Call Rain':
        assert features['irritant']['amount']==0
        assert features['smoke']['suppressed_until']>0
        assert 'suppressed_until' not in features['pollution']
    assert features['lava']['amount']==10


def test_creature_without_raincaller_can_collect_real_rainwater_but_not_cast(native):
    p=native;p.turn();e=p.load();other=e.state.actors[AN]
    site=site_profile();site['allies']=[p.owner]
    site['containers'][0]['position']=other.position.model_dump(mode='json')
    p.table.world_fact(p.mid,e.state.state_version,
        {'source':ALL[0],'subject':p.owner,'kind':'rain_site','scope':'water-site','value':site,'expires_at':3600,'readers':[]},'actual-shared-water')
    e=p.load()
    calls=[c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
           and e.action_catalog[c.source_definition_id].display_name=='Call Rain' and c.destination
           and e.grid.distance_ft(c.destination,other.position)<=15]
    assert calls
    selected=min(calls,key=lambda c:e.grid.distance_ft(c.destination,other.position))
    p.commit(selected.candidate_id);p.turn(AN)
    e=p.load();before=e.state.actors[AN].resources.copy()
    assert not any(e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Call Rain' for c in e.legal_candidates())
    p.commit(p.candidate('Call Rain: collect clean water').candidate_id)
    e=p.load();held=next(c for c in e.state.actors[p.owner].conditions.values() if c.condition_id=='condition:typed.raincaller_site')
    assert held.data['state']['site']['containers'][0]['water']==1
    assert held.data['state']['site']['containers'][0]['clean_rainwater']==1
    assert e.state.actors[AN].resources==before
    assert not any(e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Call Rain: collect clean water' for c in e.legal_candidates())


def test_native_nonliving_soil_gets_moisture_without_reviving_dead_crop(civil):
    combat,aid,jid=civil;site=site_profile()
    for f in site['features']:
        if f['kind'] in ('soil','plant'):f['alive']=0
    scene(civil,site);s=command(civil,'rain_rite',{'effects':['drought']})
    features={f['id']:f for f in rainstate(s,aid)['site']['features']}
    assert features['soil']['normal_moisture_days']==1
    assert features['living-crop']['alive']==0
    assert 'normal_moisture_days' not in features['living-crop']


def test_replacing_civil_call_releases_only_its_prior_area_suppression(civil):
    combat,aid,jid=civil;scene(civil)
    s=command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert next(f for f in rainstate(s,aid)['site']['features'] if f['id']=='smoke')['suppressed_until']>0
    # Activate the replacement at another actual legal point in range, leaving
    # the old smoke location outside the new twenty-foot cylinder.
    s=command(civil,'rain_call',{'center':{'x':10,'y':6},'form':'mist','allies':[aid]})
    smoke=next(f for f in rainstate(s,aid)['site']['features'] if f['id']=='smoke')
    assert 'suppressed_until' not in smoke
    assert smoke['amount']==10


def test_native_free_ending_releases_suppression_and_keeps_sovereign_scene_use(native):
    p=native;p.turn();e=p.load();site=site_profile();site['allies']=[p.owner]
    site['features'][1]['position']=e.state.actors[p.owner].position.model_dump(mode='json')
    p.table.world_fact(p.mid,e.state.state_version,{'source':ALL[0],'subject':p.owner,'kind':'rain_site','scope':'release-site',
        'value':site,'expires_at':3600,'readers':[]},'actual-release-site')
    p.cast('Call Rain');e=p.load();before=e.state.actors[p.owner].resources['resource:core.qi']
    p.cast('Raincaller: end your rain');e=p.load()
    assert e.state.actors[p.owner].resources['resource:core.qi']==before
    assert not any(z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='call' for z in e.state.zones.values())
    held=next(c for c in e.state.actors[p.owner].conditions.values() if c.condition_id=='condition:typed.raincaller_site')
    assert 'suppressed_until' not in next(f for f in held.data['state']['site']['features'] if f['id']=='smoke')
    p.next();p.cast('Monsoon Sovereign');p.cast('Raincaller: end your rain')
    e=p.load();assert any(c.condition_id=='condition:typed.raincaller_scene_use' for c in e.state.actors[p.owner].conditions.values())
    assert not any(e.action_catalog.get(c.source_definition_id) and e.action_catalog[c.source_definition_id].display_name=='Monsoon Sovereign' for c in e.legal_candidates())


def test_native_journey_ending_call_restores_ordinary_air_without_reigniting_fire(civil):
    combat,aid,jid=civil;scene(civil)
    command(civil,'rain_call',{'form':'mist','allies':[aid]})
    s=command(civil,'rain_end',{'kind':'call'});features={f['id']:f for f in rainstate(s,aid)['site']['features']}
    assert not rainstate(s,aid)['rains']
    assert 'suppressed_until' not in features['smoke'] and features['smoke']['amount']==10
    assert features['brush-fire']['amount']==0


def test_purification_preserves_original_progressive_recovery(native):
    p=native;p.turn();affliction(p,'progressive-fever','supernatural_disease',cl=19,tags=['disease'],dc=1,
        symptoms=['poisoned'],success={'kind':'progress','required':2,'progress':0})
    p.cast('Monsoon Sovereign')
    picks={'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'repeat','choice:needle.rain_purify_episode':'progressive-fever'}
    p.next(picks);e=p.load();held=[c for c in e.state.actors[p.owner].conditions.values() if c.data.get('journey_effect_id')=='progressive-fever']
    assert len(held)==2 and all(c.data['save_success']['progress']==1 for c in held)
    p.next(picks);assert 'progressive-fever' not in episodes(p)


def test_purification_does_not_invent_a_cure_from_an_original_save(native):
    p=native;p.turn();affliction(p,'persistent-poison','poisoned',cl=19,dc=1,success={'kind':'none'})
    p.cast('Monsoon Sovereign');start=len(p.load().rolls)
    p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'repeat','choice:needle.rain_purify_episode':'persistent-poison'})
    assert 'persistent-poison' in episodes(p)
    assert any(r.actor_id==p.owner and r.reason.endswith(':CON') and r.mode=='ADVANTAGE' for r in p.load().rolls[start:])


def condition_profile(play,condition,*,cl,tags):
    e=play.load()
    value={'instance_id':condition.instance_id,'source':condition.source_definition_id,'source_actor_id':condition.source_actor_id,
        'source_cl':cl,'ordinary':1,'cause_tags':tags,'authority_grade':'ordinary'}
    result=play.table.world_fact(play.mid,e.state.state_version,
        {'source':'journey:external_effect','subject':play.owner,'kind':'condition_profile','scope':condition.instance_id,
         'value':value,'expires_at':3600,'readers':[]},'actual-profile-'+str(e.state.state_version))
    assert result['status']=='COMMITTED';play.load()


def test_unknown_blindness_requires_actual_owner_cause_input_before_washing(native):
    p=native;p.turn();affliction(p,'unknown-blindness','unknown_blinded',cl=12,ordinary=1,tags=[])
    p.cast('Call Rain');assert 'unknown-blindness' in episodes(p)
    c=next(c for c in p.load().state.actors[p.owner].conditions.values() if c.data.get('journey_effect_id')=='unknown-blindness')
    before=p.load().state.state_version
    with pytest.raises(Exception,match='cannot contradict'):condition_profile(p,c,cl=13,tags=['dust'])
    assert p.load().state.state_version==before
    condition_profile(p,c,cl=12,tags=['dust'])
    assert 'unknown-blindness' not in episodes(p)


def test_native_owner_profile_cannot_turn_an_eye_injury_into_airborne_blindness(native):
    p=native;p.turn();affliction(p,'actual-eye-injury','injury_blinded',cl=12,ordinary=1,tags=['injury'])
    c=next(c for c in p.load().state.actors[p.owner].conditions.values() if c.data.get('journey_effect_id')=='actual-eye-injury')
    before=p.load().state.state_version
    with pytest.raises(Exception,match='cannot contradict'):condition_profile(p,c,cl=12,tags=['dust'])
    assert p.load().state.state_version==before


def fire_event(civil,value):
    combat,aid,jid=civil;state=combat.journey_state(jid)
    result=combat.journey_world_fact(jid,state['revision'],{'source':ALL[0],'subject':aid,'kind':'rain_environment_event',
        'scope':'fire-attempt-'+str(state['revision']),'value':value,'expires_at':state['seconds']+60,'readers':[]})
    assert CombatService(ROOT,combat.userdata_root).journey_verify(jid)['status']=='PASS'
    return result


def test_provincial_firebreak_prevents_actual_adjacent_wildfire_spread(civil):
    combat,aid,jid=civil;site=site_profile()
    source=dict(site['features'][0]);source.update(id='wildfire-edge',position={'x':4,'y':6},amount=0)
    site['features'].append(source);scene(civil,site)
    command(civil,'rain_rite',{'effects':['firebreak']})
    s=fire_event(civil,{'kind':'ordinary_spread','feature':'wildfire-edge','source_feature':'brush-fire','sections':1,
        'cause':'Actual adjacent ordinary wildfire front'})
    features={f['id']:f for f in rainstate(s,aid)['site']['features']}
    assert features['wildfire-edge']['amount']==0
    assert any(e['kind']=='RAIN_FIRE_PREVENTED' and e.get('input_receipt_id') for e in s['events'])
    s=command(civil,'wait',{'seconds':60})
    assert next(f for f in rainstate(s,aid)['site']['features'] if f['id']=='brush-fire')['amount']==9


def test_firebreak_does_not_treat_every_flame_as_wildfire(civil):
    combat,aid,jid=civil;site=site_profile();site['features'][0]['fire_kind']='flame';scene(civil,site)
    command(civil,'rain_rite',{'effects':['firebreak']});s=command(civil,'wait',{'seconds':60})
    assert next(f for f in rainstate(s,aid)['site']['features'] if f['id']=='brush-fire')['amount']==10


def test_numerical_cl_does_not_erase_explicit_protected_poison_authority(native):
    p=native;p.turn();affliction(p,'artifact-poison','poisoned',cl=1,authority='artifact')
    p.cast('Monsoon Sovereign');p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'poison'})
    assert 'artifact-poison' in episodes(p)


def test_actual_owner_supplied_counterprocedure_exception_remains_reachable(native):
    p=native;p.turn();affliction(p,'rain-soluble-artifact-poison','poisoned',cl=1,authority='artifact',counter=[ALL[4]],
        basis='This external source explicitly permits Raincaller Monsoon Sovereign purification.')
    p.cast('Monsoon Sovereign');p.next({'choice:needle.rain_decree':'purification','choice:needle.rain_purify':'poison'})
    assert 'rain-soluble-artifact-poison' not in episodes(p)


def test_native_journey_menu_exposes_all_forms_and_provincial_effect_combinations(civil):
    combat,aid,jid=civil;scene(civil);menu=combat.journey_menu(jid,aid)
    calls=[o for o in menu['options'] if o['kind']=='rain_call']
    assert {o['payload']['form'] for o in calls}=={'mist','heavy','restorative','driving','cleansing'}
    rites=[o for o in menu['options'] if o['kind']=='rain_rite']
    assert len(rites)==29
    assert {tuple(o['payload']['effects']) for o in rites}>={(),('steady',),('mist',),('steady','drought')}
    command(civil,'rain_call',{'form':'mist','allies':[aid]})
    assert len([o for o in combat.journey_menu(jid,aid)['options'] if o['kind']=='rain_form'])==5
    command(civil,'rain_form',{'form':'heavy'})
    assert not [o for o in combat.journey_menu(jid,aid)['options'] if o['kind']=='rain_form']
    with pytest.raises(ValueError,match='once'):command(civil,'rain_form',{'form':'mist'})
    command(civil,'wait',{'seconds':6})
    assert len([o for o in combat.journey_menu(jid,aid)['options'] if o['kind']=='rain_form'])==5


def test_empty_provincial_selection_pays_its_actual_ritual_and_resource_cost(civil):
    combat,aid,jid=civil;s=scene(civil);before=s['actors'][aid]['resources']['resource:core.qi']
    s=command(civil,'rain_rite',{'effects':[]});assert s['seconds']==600
    assert s['actors'][aid]['resources']['resource:core.qi']==before-5
    assert rainstate(s,aid)['rains']['rite']['effects']==[]
    assert next(f for f in rainstate(s,aid)['site']['features'] if f['id']=='brush-fire')['amount']==10


@pytest.mark.parametrize('effects',[['steady','steady'],['steady','drought','mist'],[{}]])
def test_illegal_provincial_choices_reject_without_payment_or_time(civil,effects):
    combat,aid,jid=civil;before=scene(civil)
    with pytest.raises(ValueError,match='up to two'):command(civil,'rain_rite',{'effects':effects})
    assert combat.journey_state(jid)==before
