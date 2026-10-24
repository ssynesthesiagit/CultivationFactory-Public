"""Printed Sound second-pass behavior through genuine service transactions."""
import pytest
from combat.gate2_runtime_models import ActionIntent
from combat.typed_executor import condition_rules
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

NAME='TAL_SOUND_NAME_STRIKING_TONE'
SWALLOW='TAL_SOUND_SILENCE_THAT_SWALLOWS_THUNDER'
FIRST='tianxia.talent.sound.the_first_sound_before_heaven'


def execute(combat, mid, c):
    session=combat._load_session(mid)
    session.mechanical.execute_intent(ActionIntent(intent_id='sound-second-pass',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,
        destination=c.destination,option_ids=c.option_ids))


def high_hp(bundles):
    from combat.canonical import canonical_sha256
    for b in bundles:
        b['actor_template']['maximum_hp']=1000
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


@pytest.mark.parametrize('rider',['frightened','distance','save','resonance'])
@pytest.mark.parametrize('dc',[50,-50])
def test_name_damage_and_failed_save_choice_on_source_clock(tmp_path,rider,dc):
    combat,table,mid=fixture(tmp_path,[NAME],owner_dc=dc,bundle_transform=high_hp)
    c=candidate(combat,mid,'Name-Striking Tone',target=FOE)
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.sound_name_known':'known',
        'choice:needle.sound_name_damage':'thunder','choice:needle.sound_name_failure':rider})
    e=reload(tmp_path,mid);foe=e.state.actors[FOE]
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and NAME in str(v.source_definition_id)]
    assert len(saves)==1
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and NAME in str(v.source_definition_id)]
    assert len(damage)==1 and damage[0].payload['damage_type']=='THUNDER'
    penalties=[c for c in foe.conditions.values() if NAME in str(c.source_definition_id)]
    assert bool(penalties)==(dc==50)
    assert any('sound_name_failure' in str(p) for p in prompts)==(dc==50)
    if penalties:
        assert all((c.expires_on=='END_OF_MARKER_NEXT_TURN' or c.expires_on.startswith('END_OF_SOURCE_TURN_AT:')) for c in penalties)
        turn(table,mid,FOE);assert any(NAME in str(c.source_definition_id) for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        turn(table,mid,OWNER);assert any(NAME in str(c.source_definition_id) for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        assert not any(NAME in str(c.source_definition_id) for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_name_ai_cannot_use_roster_name_as_knowledge(tmp_path):
    combat,table,mid=fixture(tmp_path,[NAME],ask=False)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid)
    assert not any(NAME in str(c.source_definition_id) for c in e.legal_candidates())


def test_name_next_sound_save_is_consumed_after_real_save(tmp_path):
    combat,table,mid=fixture(tmp_path,[NAME,'TAL_SOUND_THUNDERING_VOICE'],owner_dc=50,bundle_transform=high_hp)
    c=candidate(combat,mid,'Name-Striking Tone',target=FOE)
    settle(table,mid,c.candidate_id,picks={'choice:needle.sound_name_known':'known',
        'choice:needle.sound_name_failure':'save'})
    assert any(c.condition_id=='condition:typed.sound_name_save' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    turn(table,mid,ALLY)
    turn(table,mid,OWNER)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
        and e.action_catalog[c.source_definition_id].display_name=='Thundering Voice' and c.destination==e.state.actors[FOE].position)
    execute(combat,mid,c)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.sound_name_save' for c in e.state.actors[FOE].conditions.values())
    rolls=[r for r in e.rolls if r.actor_id==FOE and 'SAVE' in r.reason]
    assert any(len(r.dice)==2 for r in rolls),[(r.reason,r.dice) for r in rolls]


def packet_setup(source_side,kind='THUNDER'):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        for b in bundles:
            source='action:test.sound_packet.'+b['actor_id'].rsplit('-',1)[-1]
            b['action_catalog'].append({'source_definition_id':source,'display_name':'Test packet','owner_id':b['actor_id'],
                'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY' if source_side=='foe' else 'ALLY_OR_SELF',
                'range_ft':100,'costs':[],'parameters':{'typed':{'source':source,'numbers':{'key_mod':0,'pb':5},
                    'effects':[{'type':'damage','applies_to':'target','flat':20,'damage_types':[kind]}]}}})
            b['actor_template']['action_ids'].append(source)
            b['actor_template']['maximum_hp']=1000
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    return setup


@pytest.mark.parametrize('feature,name',[(SWALLOW,'Silence That Swallows Thunder'),(FIRST,'The First Sound Before Heaven: Silence-Before-Sound Mode')])
@pytest.mark.parametrize('source_side,dc,blocked',[('foe',50,True),('foe',-50,False),('ally',50,False)])
def test_silence_suppresses_hostile_sources_only_inside_area(tmp_path,feature,name,source_side,dc,blocked):
    combat,table,mid=fixture(tmp_path,[feature],owner_dc=dc,bundle_transform=packet_setup(source_side),ask=False)
    e=combat._load_session(mid).engine
    c=candidate(combat,mid,name,at=(3,6))
    execute(combat,mid,c);e=reload(tmp_path,mid)
    assert e.state.zones
    caster=FOE if source_side=='foe' else ALLY
    turn(table,mid,caster)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Test packet',target=OWNER)
    execute(combat,mid,c);e=reload(tmp_path,mid)
    if feature==FIRST and source_side=='foe': blocked=True
    assert e.state.actors[OWNER].current_hp==before-(0 if blocked else 20)
    checks=[v for v in e.events if v.event_type=='CHECK_ROLLED']
    assert bool(checks)==(feature==SWALLOW and source_side=='foe')
    assert not any(m.target_field=='damage_immunity' for a in e.state.actors.values() for m in a.modifiers.values())


@pytest.mark.parametrize('resistant',[False,True])
def test_bell_bone_reduces_one_thunder_packet_per_round_on_cold_reload(tmp_path,resistant):
    def setup(bundles):
        packet_setup('foe')(bundles)
        for b in bundles:
            for action in b['action_catalog']:
                if action['display_name']=='Test packet': action['economy']='NONE'
        from combat.canonical import canonical_sha256
        if resistant:
            bundles[0]['typed_passives'].append({'feature_id':'test:resistance','block':'defense','kind':'resistance','damage_types':['THUNDER']})
        for b in bundles:
            b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc=sheet([],cl=15)
    doc['identity']['proficiency_bonus']=5
    doc['spheres_and_talents']={'cultivation_insight_record_ids':['insight.bell-bone-adept']}
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':False})
    assert any(r.get('feature_id')=='insight.bell-bone-adept' for r in bundle['typed_passives']),bundle['diagnostics']
    combat,table,mid=fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=setup,ask=False)
    turn(table,mid,FOE);e=reload(tmp_path,mid);before=e.state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Test packet',target=OWNER);execute(combat,mid,c);e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==before-(10 if resistant else 20)+5
    assert e.state.actors[OWNER].turn_flags['defense_round_used:insight.bell-bone-adept']==e.state.round_number
    first_round=e.state.round_number
    before=e.state.actors[OWNER].current_hp
    execute(combat,mid,candidate(combat,mid,'Test packet',target=OWNER));e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==before-(10 if resistant else 20)
    turn(table,mid,OWNER);turn(table,mid,FOE)
    e=reload(tmp_path,mid);assert e.state.round_number>first_round
    before=e.state.actors[OWNER].current_hp
    execute(combat,mid,candidate(combat,mid,'Test packet',target=OWNER));e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==before-(10 if resistant else 20)+5


def test_name_direct_session_requires_actual_observed_voice_with_mixed_sides(tmp_path):
    from tests.h1_support import sheet
    combat,table,mid=fixture(tmp_path,[NAME],owner_dc=50,ask=False,bundle_transform=high_hp,
                            foe_sheet=sheet(['WARLEADER_BASE_FIERCE_SHOUT'],cl=15))
    turn(table,mid,FOE)
    e=combat._load_session(mid).engine
    voice=next(c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
        and (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')=='WARLEADER_BASE_FIERCE_SHOUT')
    execute(combat,mid,voice)
    e=reload(tmp_path,mid)
    assert any(v.event_type=='PASSIVE_TRIGGERED' and v.payload.get('sound_voice_observed') for v in e.events)
    turn(table,mid,OWNER)
    before=reload(tmp_path,mid).state.actors[ALLY].current_hp
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    c=candidate(combat,mid,'Name-Striking Tone',target=FOE)
    execute(combat,mid,c);e=reload(tmp_path,mid)
    assert e.state.actors[ALLY].current_hp==before
    assert any(c.condition_id=='condition:typed.frightened' for c in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('trigger',['dodge','disengage','focus'])
@pytest.mark.parametrize('dampen',[False,True])
def test_silent_step_native_grant_trigger_distance_and_reload(tmp_path,trigger,dampen):
    feature='TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'
    def setup(bundles):
        from combat.canonical import canonical_sha256
        from combat.factory_compiler import RESOURCE_IDS
        owner=bundles[0]
        source='action:test.focus_step'
        owner['action_catalog'].append({'source_definition_id':source,'display_name':'Spend focus','owner_id':OWNER,
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'typed':{'effects':[{'type':'spend_resource','applies_to':'self','resource_id':RESOURCE_IDS['martial_focus'],'flat':1}]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    talents=[feature]+(['TAL_SOUND_DAMPEN_SOUND'] if dampen else [])
    combat,table,mid=fixture(tmp_path,talents,bundle_transform=setup)
    if dampen:
        c=candidate(combat,mid,'Dampen Sound',at=(3,6))
        settle(table,mid,c.candidate_id)
        turn(table,mid,ALLY)
        turn(table,mid,OWNER)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.source_definition_id==('action:test.focus_step' if trigger=='focus' else 'system:combat.'+trigger))
    before=e.state.actors[OWNER].movement_remaining_ft
    # Square 2,6 is five feet away; square 1,6 is ten feet away.
    destination='step:1,6' if dampen else 'step:2,6'
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.silent_step_hearing':FOE,
                                               'choice:needle.silent_step_destination':destination})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==(1 if dampen else 2)
    assert e.state.actors[OWNER].movement_remaining_ft==before
    assert e.state.actors[OWNER].turn_flags['sound_silent_step_round_']==[e.state.round_number,e.state.current_actor_id,e.state.actors[e.state.current_actor_id].turns_started]
    assert any(f'up to {10 if dampen else 5} feet' in str(p) for p in prompts)
    if trigger!='focus':
        c=next(c for c in e.legal_candidates() if c.source_definition_id=='action:test.focus_step')
        prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.silent_step_hearing':FOE})
        assert not prompts


def test_first_silence_ai_cast_has_both_sides_in_range_but_no_friendly_immunity(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat,table,mid=fixture(tmp_path,[FIRST],ask=False,bundle_transform=packet_setup('ally'))
    c=candidate(combat,mid,'The First Sound Before Heaven: Silence-Before-Sound Mode',at=(3,6))
    original=combat.controller
    class ChooseField:
        def choose_primary_action(self,context):
            return ManualControllerAdapter(lambda _:(c.candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(original,name)
    combat.controller=ChooseField()
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    combat.controller=original
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    e=reload(tmp_path,mid)
    from combat import zones
    z=next(iter(zones.typed_zones(e)))
    assert zones._inside(e,e.state.actors[ALLY],z) and zones._inside(e,e.state.actors[FOE],z)
    turn(table,mid,ALLY);before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    execute(combat,mid,candidate(combat,mid,'Test packet',target=OWNER))
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==before-20


def test_unknown_name_confirmation_decline_spends_nothing(tmp_path):
    combat,table,mid=fixture(tmp_path,[NAME])
    e=reload(tmp_path,mid);before=e.state.actors[OWNER].resources['resource:core.qi']
    prompts=settle(table,mid,candidate(combat,mid,'Name-Striking Tone',target=FOE).candidate_id,
                   picks={'choice:needle.sound_name_known':None})
    e=reload(tmp_path,mid)
    assert any('sound_name_known' in str(p) for p in prompts)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before
    assert e.state.actors[OWNER].action_available
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)


def test_silent_step_exempts_only_named_hearing_tracker_and_no_ally_option(tmp_path):
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'],foe_position={'x':3,'y':5})
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dodge')
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.silent_step_hearing':FOE,
                                               'choice:needle.silent_step_destination':'step:2,7',
        'reaction:typed.opportunity_attack':'first'})
    e=reload(tmp_path,mid)
    prompt=next(p for p in prompts if 'silent_step_hearing' in p['context']['reaction_source_id'])
    options=[o['id'] for o in prompt['choice']['options']]
    assert options==[FOE] and ALLY not in options
    assert e.state.actors[OWNER].position.y==7
    assert not any(v.event_type=='REACTION_RESOLVED' and 'opportunity' in str(v.source_definition_id) for v in e.events)


def sealed_sound_action(bundles, name, effects):
    from combat.canonical import canonical_sha256
    b=bundles[0];source='action:test.sound.'+name
    b['action_catalog'].append({'source_definition_id':source,'display_name':name,'owner_id':OWNER,
        'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,'costs':[],
        'parameters':{'typed':{'source':source,'sphere':'tianxia.sphere.sound',
            'numbers':{'save_dc':50,'pb':5,'key_mod':5},'effects':effects}}})
    b['actor_template']['action_ids'].append(source)
    b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


def test_name_penalty_consumes_native_repeat_save_once(tmp_path):
    def setup(bundles):
        high_hp(bundles)
        sealed_sound_action(bundles,'Repeat', [{'type':'condition','condition':'test_sound_repeat',
            'applies_to':'target','duration':{'kind':'rounds','amount':10},
            'repeat_save':{'ability':'wis','when':'end'}}])
    combat,table,mid=fixture(tmp_path,[NAME],owner_dc=50,bundle_transform=setup)
    execute(combat,mid,candidate(combat,mid,'Repeat',target=FOE));reload(tmp_path,mid)
    settle(table,mid,candidate(combat,mid,'Name-Striking Tone',target=FOE).candidate_id,
           picks={'choice:needle.sound_name_known':'known','choice:needle.sound_name_failure':'save'})
    turn(table,mid,FOE)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('SAVE:action:test.sound.Repeat:')]
    assert len(rolls)==1 and len(rolls[0].dice)==2
    assert not any(c.condition_id=='condition:typed.sound_name_save' for c in e.state.actors[FOE].conditions.values())
    turn(table,mid,FOE);settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('SAVE:action:test.sound.Repeat:')]
    assert len(rolls)==2 and len(rolls[1].dice)==1


def test_silent_step_after_focus_spent_inside_event_callback(tmp_path,monkeypatch):
    from combat import ext
    def setup(bundles):
        sealed_sound_action(bundles,'Nested', [{'type':'damage','applies_to':'target','flat':1,'damage_types':['FORCE']}])
    def nested(engine,event_type,kwargs):
        if event_type=='DAMAGE_COMMITTED' and kwargs.get('source_definition_id')=='action:test.sound.Nested':
            engine._spend_resource(engine.state.actors[OWNER],'resource:core.martial_focus',1,'action:test.sound.Nested')
    monkeypatch.setitem(ext._HOOKS,'event',list(ext._HOOKS['event'])+[nested])
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Nested',target=FOE).candidate_id,picks={
        'choice:needle.silent_step_hearing':FOE,'choice:needle.silent_step_destination':'step:2,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.martial_focus']==0
    assert e.state.actors[OWNER].position.x==2


@pytest.mark.parametrize('feature,name',[(SWALLOW,'Silence That Swallows Thunder'),
    (FIRST,'The First Sound Before Heaven: Silence-Before-Sound Mode')])
def test_silence_does_not_suppress_thunder_outside_its_footprint(tmp_path,feature,name):
    combat,table,mid=fixture(tmp_path,[feature],owner_dc=50,bundle_transform=packet_setup('foe'),ask=False,
        positions={OWNER:{'x':0,'y':0},ALLY:{'x':1,'y':0},FOE:{'x':3,'y':0}})
    execute(combat,mid,candidate(combat,mid,name,at=(0,13)))
    e=reload(tmp_path,mid)
    from combat import zones
    from combat.spatial_areas import zone_contains
    zone=next(iter(zones.typed_zones(e)))
    assert not zone_contains(e,e.state.actors[OWNER],zone)
    assert not any(row.get('cant_hear') for row in condition_rules(e.state.actors[OWNER]))
    turn(table,mid,FOE);before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    execute(combat,mid,candidate(combat,mid,'Test packet',target=OWNER));e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].current_hp==before-20
    assert not any(v.event_type=='CHECK_ROLLED' for v in e.events)


def test_silent_step_movement_survives_declining_tracker_and_cold_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'])
    c=next(c for c in combat._load_session(mid).engine.legal_candidates()
           if c.source_definition_id=='system:combat.dodge')
    prompts=settle(table,mid,c.candidate_id,picks={
        'choice:needle.silent_step_hearing':None,
        'choice:needle.silent_step_destination':'step:2,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==2
    from combat.ext.sound_second_pass import source_name
    assert source_name(e,'system:combat.dodge')=='Dodge'
    hearing=next(p for p in prompts if 'silent_step_hearing' in p['context']['reaction_source_id'])
    assert 'after Dodge' in hearing['moment'] and 'system:combat.' not in hearing['moment'],hearing
    assert 'Declining this choice does not cancel the step' in hearing['moment']


def test_silent_step_without_perceived_tracker_still_offers_movement(tmp_path,monkeypatch):
    from combat import senses
    monkeypatch.setattr(senses,'perceives',lambda engine,viewer,seen,**kwargs:False)
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'])
    c=next(c for c in combat._load_session(mid).engine.legal_candidates()
           if c.source_definition_id=='system:combat.dodge')
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.silent_step_destination':'step:2,6'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==2
    assert not any('silent_step_hearing' in p['context']['reaction_source_id'] for p in prompts)
    assert any('silent_step_destination' in p['context']['reaction_source_id'] for p in prompts)


def test_nonowner_focus_spend_does_not_write_sound_state_on_reload(tmp_path):
    def setup(bundles):
        from combat.canonical import canonical_sha256
        from combat.factory_compiler import RESOURCE_IDS
        owner=bundles[0];source='action:test.nonowner_focus'
        owner['action_catalog'].append({'source_definition_id':source,'display_name':'Spend focus','owner_id':OWNER,
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'typed':{'effects':[{'type':'spend_resource','applies_to':'self',
                'resource_id':RESOURCE_IDS['martial_focus'],'flat':1}]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256',None);owner['bundle_sha256']=canonical_sha256(owner)
    combat,table,mid=fixture(tmp_path,[],bundle_transform=setup)
    c=candidate(combat,mid,'Spend focus')
    prompts=settle(table,mid,c.candidate_id)
    e=reload(tmp_path,mid)
    assert 'sound_focus_seen_round_' not in e.state.actors[OWNER].turn_flags
    assert not any('silent_step' in str(p) for p in prompts)


def test_name_resonance_choice_explains_sound_mark(tmp_path):
    combat,table,mid=fixture(tmp_path,[NAME],owner_dc=50)
    prompts=settle(table,mid,candidate(combat,mid,'Name-Striking Tone',target=FOE).candidate_id,picks={
        'choice:needle.sound_name_known':'known',
        'choice:needle.sound_name_damage':'psychic',
        'choice:needle.sound_name_failure':'resonance'})
    failure=next(p for p in prompts if 'sound_name_failure' in p['context']['reaction_source_id'])
    resonance=next(o['label'] for o in failure['choice']['options'] if o['id']=='resonance')
    assert 'Sound mark' in resonance and 'extra Sound effects' in resonance
    reload(tmp_path,mid)


def test_silent_step_manual_focus_choice_during_another_actors_ai_turn(tmp_path,monkeypatch):
    from combat import ext
    from combat.gate4_adapters import ManualControllerAdapter
    def setup(bundles):
        from combat.canonical import canonical_sha256
        b=next(b for b in bundles if b['actor_id']==ALLY)
        source='action:test.ally_focus_window'
        b['action_catalog'].append({'source_definition_id':source,'display_name':'Ally focus-window strike',
            'owner_id':ALLY,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY',
            'range_ft':60,'costs':[],'parameters':{'typed':{'effects':[
                {'type':'damage','applies_to':'target','flat':1,'damage_types':['FORCE']}]}}})
        b['actor_template']['action_ids'].append(source)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    def spend_owner(engine,event_type,kwargs):
        if event_type=='DAMAGE_COMMITTED' and kwargs.get('source_definition_id')=='action:test.ally_focus_window':
            engine._spend_resource(engine.state.actors[OWNER],'resource:core.martial_focus',1,'action:test.ally_focus_window')
    monkeypatch.setitem(ext._HOOKS,'event',list(ext._HOOKS['event'])+[spend_owner])
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'],ally_talents=(),bundle_transform=setup)
    turn(table,mid,ALLY)
    e=combat._load_session(mid).engine
    strike=next(c for c in e.legal_candidates() if c.source_definition_id=='action:test.ally_focus_window')
    original=combat.controller
    class ChooseStrike:
        def choose_primary_action(self,context):
            return ManualControllerAdapter(lambda _:(strike.candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(original,name)
    combat.controller=ChooseStrike()
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='LOCAL_AUTO')
    prompts=settle(table,mid,None,auto=True,picks={
        'choice:needle.silent_step_hearing':FOE,
        'choice:needle.silent_step_destination':'step:2,6'})
    combat.controller=original
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==2
    assert any('silent_step_hearing' in p['context']['reaction_source_id'] for p in prompts)
    assert e.state.current_actor_id==ALLY
    hearing=next(p for p in prompts if 'silent_step_hearing' in p['context']['reaction_source_id'])
    assert FOE in [o['id'] for o in hearing['choice']['options']]


def test_silent_step_exempts_only_selected_tracker_when_two_enemies_can_react(tmp_path):
    second='actor:factory.worker2-ally3'
    positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':5},second:{'x':4,'y':7}}
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'],extra_allies=1,
                             positions=positions,team_overrides={second:'team:opponents'})
    e=combat._load_session(mid).engine
    from combat import typed_reactions
    assert typed_reactions.opportunity_reach(e,e.state.actors[FOE])==5
    assert typed_reactions.opportunity_reach(e,e.state.actors[second])==5
    c=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dodge')
    prompts=settle(table,mid,c.candidate_id,picks={
        'choice:needle.silent_step_hearing':FOE,
        'choice:needle.silent_step_destination':'step:2,7',
        'reaction:typed.opportunity_attack':'first'})
    result=reload(tmp_path,mid)
    resolved=[event.actor_id for event in result.events
              if event.event_type=='REACTION_RESOLVED' and event.source_definition_id=='system:combat.opportunity_attack']
    assert FOE not in resolved
    assert second in resolved, (resolved,prompts)



def test_silent_step_ai_moves_without_inventing_a_tracker(tmp_path,monkeypatch):
    from combat import senses
    from combat.gate4_adapters import ManualControllerAdapter
    monkeypatch.setattr(senses,'perceives',lambda engine,viewer,seen,**kwargs:False)
    combat,table,mid=fixture(tmp_path,['TAL_SOUND_SILENT_STEP_BETWEEN_NOTES'],ask=False)
    e=combat._load_session(mid).engine
    dodge=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.dodge')
    original=combat.controller
    class ChooseDodge:
        def choose_primary_action(self,context):
            return ManualControllerAdapter(lambda _:(dodge.candidate_id,())).choose_primary_action(context)
        def __getattr__(self,name):return getattr(original,name)
    combat.controller=ChooseDodge()
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    result=table.auto_step(mid,0,[])
    combat.controller=original
    assert result['status']=='COMMITTED',result
    e=reload(tmp_path,mid)
    assert (e.state.actors[OWNER].position.x,e.state.actors[OWNER].position.y)!=(3,6)
