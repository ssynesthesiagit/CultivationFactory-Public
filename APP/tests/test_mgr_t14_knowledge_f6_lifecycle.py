"""F6 review: real native lifecycle, controller decisions and private rendering.

All services use isolated storage; Node executes the actual renderer without a
browser. No live service/model calls or fabricated ownership/state receipts.
"""
import base64
import json
import subprocess

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.knowledge_inputs_support import (
    OWNER, ALLY, FOE, QI, VENOM, SKY, make, source, journey_settle, candidates, answers,
)
from tests.worker2_support import settle, reload, turn

PID=OWNER.removeprefix('actor:factory.')
SHROUD='WEATHER_BASE_CLOUD_SHROUD'
RENDERER_SOURCE='APP/static/tabletop/observer-information.js'


def scene(combat,values=None,subject=ALLY,automatic=()):
    return combat.create_journey(project_ids=[PID,ALLY.removeprefix('actor:factory.')],
        arena_id='battlefield:map.builtin-sect-trial-platform',
        positions={OWNER:{'x':4,'y':5},ALLY:{'x':4,'y':6}},base_paces={OWNER:5,ALLY:5},
        control_modes={aid:'LOCAL_AUTO' if aid in automatic else 'MANUAL' for aid in (OWNER,ALLY)},
        source_inputs=[source(subject,values)] if values else None)


def shroud(combat,state,sign='cold'):
    jid=state['journey_id']
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options']
        if r['kind']=='native_scene_action' and r['payload']['subject_id']==ALLY and 'Shroud' in r['label'])
    return journey_settle(combat,jid,state,OWNER,'native_scene_action',{**action,
        'choices':{'choice:needle.weather_shroud_sign':[sign],'choice:needle.weather_battle_reading':[]}})


def native(combat,jid):
    return json.loads(combat.journeys.load(jid).state['native_scene']['state'])


def fail_weather_saves(monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    original=DeterministicRollAuthority.d20
    def roll(self,**kwargs):
        result=original(self,**kwargs)
        if kwargs['reason'].startswith('SAVE:'):
            return result.model_copy(update={'natural_result':1,'total':1+kwargs.get('modifier',0)})
        return result
    monkeypatch.setattr(DeterministicRollAuthority,'d20',roll)


@pytest.mark.parametrize('resolve',[False,True])
def test_f1_verified_terminal_fight_replaces_retained_scene_and_survives_next_export(tmp_path,monkeypatch,resolve):
    fail_weather_saves(monkeypatch)
    # Cold Sign changes Speed; it does not deal Shroud damage. Heat's printed
    # damage makes the HP-transfer assertion below test an actual consequence.
    combat,table,_=make(tmp_path,SKY,starting_sign='heat')
    state=scene(combat);jid=state['journey_id']
    state=shroud(combat,state,sign='heat')
    before=native(combat,jid)
    match=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'},maximum_rounds=1)
    mid=match['match_id']
    for _ in range(6):
        engine=reload(tmp_path,mid)
        if engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    terminal=reload(tmp_path,mid)
    assert terminal.state.terminal_result is not None
    assert [e.sequence for e in terminal.events]==list(range(1,terminal.state.event_sequence+1))
    assert sum(e.event_type=='MATCH_CREATED' for e in terminal.events)==1
    assert terminal.state.actors[ALLY].current_hp<before['actors'][ALLY]['current_hp']
    state=combat.journey_resume(jid,combat.journeys.load(jid).state['revision'],
        effect_resolutions={OWNER:'The caster ends the weather.'} if resolve else None)
    cold=CombatService(ROOT,tmp_path)
    restored=native(cold,jid)
    for field in ('match_id','match_seed','maximum_rounds'):
        assert restored[field]==before[field]
    for aid in (OWNER,ALLY):
        for field in ('current_hp','conditions','modifiers','concentration','turns_started'):
            if resolve and field in ('conditions','modifiers','concentration'):continue
            assert restored['actors'][aid][field]==terminal.state.actors[aid].model_dump(mode='json')[field]
    if resolve:
        assert restored['actors'][OWNER]['concentration'] is None
        assert 'resolutions' in cold.journeys.load(jid).state['native_scene']
        assert all('previous_state' not in e for e in state['events'])
    assert restored['round_number']==terminal.state.round_number
    # A creature Shroud creates no map object. Native serialization omits an
    # empty object registry; compare actual state, including that native default.
    assert restored.get('objects',{})=={oid:obj.model_dump(mode='json')
        for oid,obj in terminal.state.objects.items()}
    properties=cold.journey_menu(jid,ALLY)['properties']
    assert properties['current_hp']==terminal.state.actors[ALLY].current_hp
    next_match=cold.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'})
    again=reload(tmp_path,next_match['match_id'])
    assert again.state.actors[ALLY].current_hp==terminal.state.actors[ALLY].current_hp
    assert again.state.actors[OWNER].resources==terminal.state.actors[OWNER].resources
    assert (again.state.actors[OWNER].concentration is None)==resolve


def test_f2_native_damage_conditions_and_remaining_seconds_survive_new_journey(tmp_path,monkeypatch):
    fail_weather_saves(monkeypatch)
    combat,_,_=make(tmp_path,SKY,starting_sign='cold')
    state=scene(combat);jid=state['journey_id'];state=shroud(combat,state)
    state=combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':30})
    before=native(combat,jid)
    state=combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    assert combat.journey_replay(jid)['status']=='PASS'
    cold=CombatService(ROOT,tmp_path);state=scene(cold);new=state['journey_id']
    restored=native(cold,new)
    assert state['seconds']==0
    assert restored['actors'][ALLY]['current_hp']==before['actors'][ALLY]['current_hp']
    assert restored['actors'][ALLY]['conditions']==before['actors'][ALLY]['conditions']
    state=cold.journey_act(new,state['revision'],OWNER,'wait',{'seconds':29})
    assert native(cold,new)['actors'][OWNER]['concentration'] is not None
    state=cold.journey_act(new,state['revision'],OWNER,'wait',{'seconds':1})
    ended=native(cold,new)
    assert ended['actors'][OWNER]['concentration'] is None
    assert ended['actors'][ALLY]['current_hp']==before['actors'][ALLY]['current_hp']
    from combat.ext.weather_shroud import SHROUD as CONDITION
    assert not any(c['condition_id']==CONDITION for c in ended['actors'][ALLY]['conditions'].values())
    assert CombatService(ROOT,tmp_path).journey_replay(new)['status']=='PASS'


@pytest.mark.parametrize('ending',['dismiss','long_rest'])
def test_f2_antidote_profile_survives_finish_until_its_printed_endpoint(tmp_path,ending):
    combat,_,_=make(tmp_path,VENOM)
    state=scene(combat,{'poison.present':True,'poison.kind':'Spiritual'});jid=state['journey_id']
    state=combat.journey_act(jid,state['revision'],OWNER,'information_reading',
        {'source':VENOM,'subject_id':ALLY,'questions':['poison.kind'],'profile':True})
    state=combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    assert combat.journey_replay(jid)['status']=='PASS'
    cold=CombatService(ROOT,tmp_path);state=scene(cold);jid=state['journey_id']
    from combat.antidote_profiles import profiles_journey
    profiles=profiles_journey(cold.journeys.load(jid),OWNER)
    assert len(profiles)==1 and 'Spiritual' in json.dumps(profiles)
    assert not profiles_journey(cold.journeys.load(jid),ALLY)
    other=cold.journey_state(jid,viewer_id=ALLY)
    assert not other['actors'][OWNER].get('observer_information')
    assert not cold.journey_menu(jid,ALLY)['properties'].get('information')
    assert all(json.loads(c).get('condition_id')!='condition:information.reading'
        for c in other['actors'][OWNER].get('encounter_snapshot',{}).get('conditions',{}).values())
    state=cold.journey_act(jid,state['revision'],OWNER,
        'dismiss_antidote_profile' if ending=='dismiss' else 'long_rest',
        {'slot':profiles[0]['slot']} if ending=='dismiss' else {})
    assert not profiles_journey(CombatService(ROOT,tmp_path).journeys.load(jid),OWNER)
    assert cold.journey_replay(jid)['status']=='PASS'


def test_f2_owned_concentration_expires_when_only_the_caster_continues_travel(tmp_path):
    combat,_,_=make(tmp_path,SKY,starting_sign='cold')
    state=scene(combat);jid=state['journey_id'];state=shroud(combat,state)
    state=combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    cold=CombatService(ROOT,tmp_path)
    state=cold.create_journey(project_ids=[PID],arena_id='battlefield:map.builtin-sect-trial-platform',
        positions={OWNER:{'x':4,'y':5}},base_paces={OWNER:5},control_modes={OWNER:'MANUAL'})
    jid=state['journey_id']
    assert native(cold,jid)['actors'][OWNER]['concentration'] is not None
    state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':60})
    assert native(cold,jid)['actors'][OWNER]['concentration'] is None
    assert cold.journey_replay(jid)['status']=='PASS'


def test_f3_human_reader_ai_target_declares_its_own_nature_automatically(tmp_path):
    combat,_,_=make(tmp_path,QI)
    state=scene(combat,{'qi.expression':'A cold spiritual pressure'},automatic=(ALLY,));jid=state['journey_id']
    state=combat.journey_act(jid,state['revision'],OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.expression']})
    assert 'native_scene_pending' not in state
    raw=native(combat,jid)
    declarations=[c for c in raw['actors'][ALLY]['conditions'].values()
        if c['condition_id']=='condition:typed.fact_consent_admission']
    assert len(declarations)==1
    assert json.loads(declarations[0]['data']['record'])['authority']==ALLY
    rows=combat.journey_menu(jid,OWNER)['properties']['information']
    assert 'A cold spiritual pressure' in json.dumps(rows)
    assert 'A cold spiritual pressure' not in json.dumps(combat.journey_menu(jid,ALLY)['properties'].get('information',[]))
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'


def test_f2_elapsed_observer_memory_survives_finish_without_native_carrier(tmp_path):
    categories=dict.fromkeys(('wind','precipitation','cold','heat','aridity','storm'),0)
    combat,_,_=make(tmp_path,SKY)
    state=scene(combat,{'weather.air':True,'weather.categories':categories,
        'weather.categories_radius_ft':5280,'weather.origin':['natural'],'weather.origin_radius_ft':300},'scene')
    jid=state['journey_id']
    state=combat.journey_act(jid,state['revision'],OWNER,'information_weather',{'mode':'immediate'})
    assert 'native_scene' not in combat.journeys.load(jid).state
    state=combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    assert combat.journey_replay(jid)['status']=='PASS'
    cold=CombatService(ROOT,tmp_path);state=scene(cold);jid=state['journey_id']
    rows=cold.journey_menu(jid,OWNER)['properties']['information']
    assert len(rows)==1 and rows[0]['details']['ability']=='Read the Sky'
    assert not cold.journey_menu(jid,ALLY)['properties'].get('information')
    assert cold.journey_replay(jid)['status']=='PASS'


def test_f3_table_ai_defender_answers_human_reader_without_a_human_prompt(tmp_path):
    combat,table,mid=make(tmp_path,QI,{'qi.expression':'A cold spiritual pressure'})
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    prompts=settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,
        picks={'choice:needle.reading_questions':'qi.expression'})
    assert not any(p['context']['reaction_source_id']=='choice:needle.fact_admission.qi_nature' for p in prompts)
    engine=reload(tmp_path,mid)
    records=[json.loads(c.data['record']) for c in engine.state.actors[FOE].conditions.values()
        if c.condition_id=='condition:typed.fact_consent_admission']
    assert len(records)==1 and records[0]['authority']==FOE
    assert 'A cold spiritual pressure' in json.dumps(answers(tmp_path,mid))


def test_f4_ai_battle_reading_discovers_new_ambient_sign_only_after_weather_cast(tmp_path):
    categories=dict.fromkeys(('wind','precipitation','cold','heat','aridity','storm'),0);categories['cold']=1
    combat,_,_=make(tmp_path,SKY,starting_sign='heat')
    state=scene(combat,{'weather.categories':categories},'scene',automatic=(OWNER,ALLY));jid=state['journey_id']
    assert not combat.journey_menu(jid,OWNER)['properties'].get('information')
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options']
        if r['kind']=='native_scene_action' and r['payload']['subject_id']==ALLY and 'Shroud' in r['label'])
    state=combat.journey_act(jid,state['revision'],OWNER,'native_scene_action',action)
    assert 'native_scene_pending' not in state
    rows=combat.journey_menu(jid,OWNER)['properties']['information']
    assert any(r.get('details',{}).get('sign')=='cold' for r in rows)
    assert not combat.journey_menu(jid,ALLY)['properties'].get('information')
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'


def test_f5_recovery_profile_and_lifecycle_contracts_are_documented():
    contract=(ROOT/'combat/ext/__init__.py').read_text()
    for text in ('recorded_input_no_reactions(binding)','observer_source_profile(engine,source,data)',
                 'journey_combat_resume(session,terminal_engine,effect_resolutions)',
                 'journey_native_checkpoint(session,scene_engine,actor_id)',
                 'multiple providers raise','no recovery authority','inert without subscribers'):
        assert text in contract


def test_observer_transport_does_not_describe_private_directions_as_injured_creatures(tmp_path):
    from combat.information_results import describe
    combat,_,mid=make(tmp_path,QI)
    engine=reload(tmp_path,mid)
    envelope={'kind':'direction','viewer_id':OWNER,'details':{'direction':'north'}}
    assert describe(engine,engine.state.actors[OWNER],[envelope])==[]
    assert 'supernatural presence is north' in render([envelope])[0]


def render(rows):
    module='data:text/javascript;base64,'+base64.b64encode((ROOT.parent/RENDERER_SOURCE).read_bytes()).decode()
    script='''const {observerInformationLines}=await import(process.argv[1]);
let input='';for await(const chunk of process.stdin)input+=chunk;
const p=JSON.parse(input);console.log(JSON.stringify(observerInformationLines({entity_id:p.owner},{[p.owner]:{information:p.rows}})));'''
    result=subprocess.run(['node','--input-type=module','-e',script,module],cwd=ROOT,
        input=json.dumps({'owner':OWNER,'rows':rows}),capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_f6_real_immediate_and_careful_weather_answers_render_plainly(tmp_path):
    categories=dict.fromkeys(('wind','precipitation','cold','heat','aridity','storm'),0);categories['aridity']=2
    combat,_,_=make(tmp_path,SKY)
    state=scene(combat,{'weather.air':True,'weather.categories':categories,'weather.categories_radius_ft':5280,
        'weather.origin':['natural','concentration'],'weather.origin_radius_ft':300,
        'weather.forecast':[{'hour':0,'categories':categories},{'hour':24,'categories':categories},{'hour':48,'categories':categories}],
        'weather.forecast_radius_ft':26400,'weather.interference':False},'scene')
    jid=state['journey_id']
    for mode in ('immediate','careful'):
        state=combat.journey_act(jid,state['revision'],OWNER,'information_weather',{'mode':mode})
    rows=combat.journey_menu(jid,OWNER)['properties']['information']
    lines=render(rows);text=' '.join(lines)
    assert 'Dryness: active, strength 2 of 4' in text and 'Wind: not active' in text
    assert 'natural weather' in text and 'caster must keep focusing' in text
    assert 'Now:' in text and 'In 24 hours:' in text and 'In 48 hours:' in text
    assert not any('{' in line or '"aridity"' in line for line in lines)
    battle=render([{'viewer_id':OWNER,'kind':'answer','details':{'ability':'Read the Sky — Battle Reading','sign':'dry'}}])
    assert 'Dry Sign (aridity) is active' in battle[0]
    assert combat.journey_replay(jid)['status']=='PASS'
    from combat.ext.knowledge_readings import LABELS
    assert 'supernatural command or rule' in LABELS['vessel.mandate']
    assert 'buildup of poison' in LABELS['poison.burden']
    assert 'remains in the body' in LABELS['poison.ingrained']


@pytest.mark.parametrize('aid',[OWNER,ALLY])
def test_f7_travel_exhaustion_after_native_initialization_reaches_cold_combat(tmp_path,aid):
    from combat.ext.forged_exhaustion import level
    combat,_,_=make(tmp_path,QI)
    state=scene(combat);jid=state['journey_id']
    state=journey_settle(combat,jid,state,OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.bloodied']})
    assert 'native_scene' in combat.journeys.load(jid).state
    state=combat.journey_act(jid,state['revision'],aid,'travel_exhaustion',{'levels':2,'ordinary':True})
    # A subsequent native save must reconcile the exposure before replacing
    # the durable actor checkpoint, including for the non-reader companion.
    state=combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':1})
    assert combat.journeys.load(jid).state['actors'][aid]['exhaustion']==2
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
    cold=CombatService(ROOT,tmp_path)
    mid=cold.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'})['match_id']
    engine=reload(tmp_path,mid)
    assert level(engine.state.actors[aid])==2
    assert level(engine.state.actors[ALLY if aid==OWNER else OWNER])==0


@pytest.mark.parametrize('phase',['combat','finished'])
@pytest.mark.parametrize('edge',['start','end'])
def test_f7_native_turn_and_answers_reject_closed_journey_without_mutation(tmp_path,phase,edge):
    combat,_,_=make(tmp_path,SKY,starting_sign='cold')
    state=scene(combat);jid=state['journey_id'];state=shroud(combat,state)
    if phase=='combat':
        combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'})
    else:
        combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    cold=CombatService(ROOT,tmp_path)
    before=cold.journeys.load(jid).state
    for kind,payload in [('scene_turn',{'edge':edge}),
                         ('native_scene_answer',{'selection':'DECLINE','option_ids':[]})]:
        with pytest.raises(ValueError,match='active travel scene'):
            cold.journey_act(jid,before['revision'],ALLY,kind,payload)
        assert cold.journeys.load(jid).state==before


@pytest.mark.parametrize('variant',['creature','object','inventory'])
def test_f7_combat_qi_answers_get_elapsed_deadlines_on_return(tmp_path,variant):
    from copy import deepcopy
    from combat.factory_compiler import compile_character
    from combat.encounter_sources import prepare
    from tests.test_carry import KIT
    combat,table,_=make(tmp_path,QI,kit={'starting_kit':KIT})
    bundles=[compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')),actor_id=a)
             for a in (OWNER,ALLY)]
    arena=deepcopy(combat.factory_arenas()['battlefield:map.builtin-sect-trial-platform'])
    arena['map_objects']=[{'id':601,'kind':'custom','material':'wood','x':5,'y':5,'blocks':False}]
    item=next(r for r in bundles[1]['carrying']['items'] if 'pack' in r['item_id'])
    inputs=[source('object:map.601',{'subject.kind':'container','qi.expression':'Cold pressure'}),
        {**source(ALLY,{'subject.kind':'container','item.visible':True,'item.touchable':True,
                       'qi.expression':'Cold pressure'}),'scope':'item:'+item['key']}]
    arena=prepare(arena,inputs,[OWNER,ALLY])
    state=combat.journeys.create(bundles,arena,{OWNER:{'x':4,'y':5},ALLY:{'x':4,'y':6}},
        {OWNER:5,ALLY:5});jid=state['journey_id']
    state=journey_settle(combat,jid,state,OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.bloodied']})
    mid=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'},maximum_rounds=1)['match_id']
    turn(table,mid,OWNER)
    subject='object:map.601' if variant=='object' else OWNER if variant=='inventory' else ALLY
    offered=candidates(combat,mid,QI,subject,suffix='carried or dropped item' if variant=='inventory' else None)
    if variant=='creature':
        offered=[c for c in offered if not reload(tmp_path,mid).action_catalog[c.source_definition_id].parameters['typed'].get('reading_inventory')]
    assert offered
    settle(table,mid,offered[0].candidate_id,picks={'choice:needle.reading_questions':
        'qi.bloodied' if variant=='creature' else 'qi.expression'})
    current=reload(tmp_path,mid)
    created=[c.instance_id for c in current.state.actors[OWNER].conditions.values()
        if c.condition_id=='condition:information.reading' and c.data.get('kind')=='answer'
        and str(c.expires_on).startswith('END_OF_TURN_AT:')]
    assert created
    for _ in range(4):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    state=combat.journey_resume(jid,combat.journeys.load(jid).state['revision'])
    cold=CombatService(ROOT,tmp_path)
    retained=native(cold,jid)['actors'][OWNER]['conditions']
    assert all(key in retained for key in created)
    deadlines=cold.journeys.load(jid).state['knowledge_reading_deadlines']
    assert all(0<deadlines[key]['expires_at']-state['seconds']<=60 for key in created)
    state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':60})
    assert not set(created).intersection(native(CombatService(ROOT,tmp_path),jid)['actors'][OWNER]['conditions'])
    assert cold.journey_replay(jid)['status']=='PASS'


def test_f7_native_dose_mark_without_poisoned_offers_and_persists_profile(tmp_path,monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext.stacking_marks import count
    from combat.antidote_profiles import profiles
    original=DeterministicRollAuthority.d20
    def roll(self,**kwargs):
        result=original(self,**kwargs)
        if kwargs['reason'].startswith(('SAVE:','ATTACK:')):
            natural=1 if kwargs['reason'].startswith('SAVE:') else 20
            return result.model_copy(update={'natural_result':natural,'total':natural+kwargs.get('modifier',0)})
        return result
    monkeypatch.setattr(DeterministicRollAuthority,'d20',roll)
    combat,table,mid=make(tmp_path,VENOM)
    delivery=candidates(combat,mid,'POISON_BASE_DELIVER_THE_DOSE',FOE)
    assert delivery
    settle(table,mid,delivery[0].candidate_id)
    engine=reload(tmp_path,mid)
    assert count(engine,engine.state.actors[OWNER],engine.state.actors[FOE],'Dose Mark')==1
    assert not any(c.condition_id in ('poisoned','condition:typed.poisoned') for c in engine.state.actors[FOE].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    prompts=settle(table,mid,candidates(combat,mid,VENOM,FOE)[0].candidate_id,
        picks={'choice:needle.reading_questions':'poison.dose','choice:needle.reading_profile':'create'})
    assert any(p['context']['reaction_source_id']=='choice:needle.reading_profile' for p in prompts)
    engine=reload(tmp_path,mid)
    stored=profiles(engine,engine.state.actors[OWNER])
    assert len(stored)==1 and stored[0]['subject_id']==FOE
    assert stored[0]['answers']['Is poison present?']=='Yes'
    assert not profiles(engine,engine.state.actors[FOE])


def test_f7_antidote_profile_creation_has_one_authoritative_api():
    from combat import antidote_profiles
    assert callable(antidote_profiles.create)
    assert not hasattr(antidote_profiles,'create_journey')
