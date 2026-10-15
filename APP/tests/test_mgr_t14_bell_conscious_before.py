from pathlib import Path
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
P='tianxia.subpath.qi.bell_tower_cultivator.feature.'
def test_native_bell_progression_has_all_paid_callers():
    ids=[P+s for s in ('watch_bell','alarm_resonance','purifying_peal','bell_tower_formation','ninefold_heavenly_bell')]
    b=compile_character(sheet(ids,cl=18),actor_id='actor:bell')
    names={a['display_name'] for a in b['action_catalog']}
    assert {'Watch Bell','Purifying Peal','Begin Bell-Tower Formation','Ninefold Heavenly Bell'} <= names

import pytest
from combat import observer_information as information
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from tests.worker2_support import fixture,candidate,settle,reload,turn,OWNER,ALLY,FOE

ALL=[P+s for s in ('watch_bell','alarm_resonance','purifying_peal','bell_tower_formation','ninefold_heavenly_bell')]

def play(tmp_path,cl=18,features=None,**kw):
    return fixture(tmp_path,[],owner_features=ALL if features is None else features,cl=cl,named=True,**kw)

def cast(combat,table,mid,name,choices):
    c=candidate(combat,mid,name)
    return settle(table,mid,c.candidate_id,picks=choices)

@pytest.mark.parametrize('tone',['guarding','clarity','revealing'])
def test_watch_paid_table_commit_reload(tmp_path,tone):
    combat,table,mid=play(tmp_path,features=[bell.WATCH])
    prompts=cast(combat,table,mid,'Watch Bell',{
        'choice:needle.bell_warning_tone':tone,
        'choice:needle.bell_'+tone:[ALLY],
        'choice:needle.bell_reveal_target':FOE})
    engine=reload(tmp_path,mid)
    owner=engine.state.actors[OWNER]
    assert owner.resources[bell.QI]==99
    target=engine.state.actors[FOE if tone=='revealing' else ALLY]
    assert bell.held(target,'marked' if tone=='revealing' else tone)
    assert prompts
    assert not owner.bonus_action_available

@pytest.mark.parametrize('name,cost',[('Purifying Peal',4),('Ninefold Heavenly Bell',8),('Begin Bell-Tower Formation',5)])
def test_paid_family_native_callers_reload(tmp_path,name,cost):
    combat,table,mid=play(tmp_path)
    cast(combat,table,mid,name,{'choice:needle.bell_protected_allies':[OWNER,ALLY],
        'choice:needle.bell_allies_to_purify':[ALLY]})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[bell.QI]==100-cost
    assert not engine.state.actors[OWNER].action_available
    if name=='Ninefold Heavenly Bell':
        assert bell.held(engine.state.actors[OWNER],'nine_used')
        assert engine.state.actors[OWNER].concentration
        assert bell.fields(engine,engine.state.actors[ALLY],bell.NINE_TAG)
    if name=='Begin Bell-Tower Formation':
        assert bell.held(engine.state.actors[OWNER],'ritual')
        assert not list(bell.placed.of(engine,bell.FORM_TAG))

@pytest.mark.parametrize('cl,expected',[(2,0),(3,1),(5,1),(6,2),(9,2),(10,3),(13,3),(14,4),(17,4),(18,5)])
def test_progression_threshold_guards(cl,expected):
    b=compile_character(sheet(ALL,cl=cl),actor_id='actor:bell')
    assert len([r for r in b['typed_passives'] if r.get('block')=='bell_tower'])==expected

def test_observer_contract_default_inert(tmp_path):
    combat,table,mid=play(tmp_path,features=[])
    engine=reload(tmp_path,mid)
    assert information.readings(engine,engine.state.actors[OWNER])==[]
    assert not bell.owned(engine,engine.state.actors[ALLY],bell.ALARM)
    rolls=[r for r in engine.rolls if r.reason=='INITIATIVE']
    assert rolls and all(r.mode=='NORMAL' for r in rolls)

def test_alarm_initiative_owned_only(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.ALARM])
    engine=reload(tmp_path,mid)
    rolls={r.actor_id:r for r in engine.rolls if r.reason=='INITIATIVE'}
    assert rolls[OWNER].mode=='ADVANTAGE'
    assert rolls[ALLY].mode==rolls[FOE].mode=='NORMAL'


def test_alarm_does_not_infer_unconsciousness_from_native_journey_incapacitation(tmp_path):
    combat,table,unused=play(tmp_path,features=[bell.ALARM])
    positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}}
    state=combat.create_journey(project_ids=['worker2-owner','worker2-ally','worker2-foe'],
        arena_id=next(iter(combat.factory_arenas())),positions=positions,
        base_paces={a:1000 for a in positions},control_modes={a:'MANUAL' for a in positions})
    jid=state['journey_id']
    state=combat.journey_act(jid,state['revision'],OWNER,'incapacitated',{'value':True})
    mid=combat.journey_start_combat(jid,state['revision'],
        {OWNER:'team:bell',ALLY:'team:bell',FOE:'team:other'},positions=positions)['match_id']
    engine=reload(tmp_path,mid)
    roll=next(r for r in engine.rolls if r.reason=='INITIATIVE' and r.actor_id==OWNER)
    assert roll.mode=='ADVANTAGE'
    assert any(c.condition_id=='incapacitated' for c in engine.state.actors[OWNER].conditions.values())
    from combat.typed_reactions import can_react
    assert not can_react(engine,engine.state.actors[OWNER])

def test_alarm_enters_space_before_followup_native_action(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.ALARM])
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine
    moves=[c for c in engine.legal_candidates() if c.kind=='MOVE' and c.movement_cost_ft==5]
    assert moves
    settle(table,mid,moves[0].candidate_id,picks={
        'choice:needle.bell_ring_alarm':'ring',
        'choice:needle.bell_alarm_recipient':[ALLY],
        'choice:needle.bell_alarm_benefit':'temp_hp'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[bell.QI]==98
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[ALLY].temporary_hp==4
    assert bell.held(engine.state.actors[OWNER],'alarm_used')


def test_alarm_keeps_human_choices_on_a_native_local_ai_turn(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.ALARM],
        modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO'})
    turn(table,mid,FOE)
    prompts=settle(table,mid,None,auto=True,picks={
        'choice:needle.bell_ring_alarm':'ring',
        'choice:needle.bell_alarm_recipient':[ALLY],
        'choice:needle.bell_alarm_benefit':'temp_hp'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[bell.QI]==98
    assert engine.state.actors[ALLY].temporary_hp==4
    assert any(p['context']['reaction_source_id']=='choice:needle.bell_alarm_benefit'
        and p['context']['reactor_id']==ALLY for p in prompts)


def test_ninefold_two_tones_on_next_turn_and_same_tone_guard(tmp_path):
    combat,table,mid=play(tmp_path)
    cast(combat,table,mid,'Ninefold Heavenly Bell',{'choice:needle.bell_protected_allies':[OWNER,ALLY]})
    # Resolve all turns to the next owner start, including the owned two-tone choice.
    for _ in range(3):
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
            'choice:needle.bell_two_different_heavenly_tones':['iron_vigil','great_alarm'],
            'choice:needle.bell_iron_vigil':[ALLY],
            'choice:needle.bell_great_alarm':[ALLY]})
    engine=reload(tmp_path,mid)
    target=engine.state.actors[ALLY]
    assert target.temporary_hp==8
    assert bell.held(target,'great_alarm')
    assert any(m.target_field=='armor_class' and m.value==2 for m in target.modifiers.values())
    assert not any(c.display_name=='Ninefold Heavenly Bell' for c in engine.legal_candidates())


def test_formation_one_minute_actual_turns_then_native_anchor(tmp_path):
    combat,table,mid=play(tmp_path)
    cast(combat,table,mid,'Begin Bell-Tower Formation',{'choice:needle.bell_protected_allies':[OWNER,ALLY]})
    for _ in range(30):settle(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    formations=list(bell.placed.of(engine,bell.FORM_TAG))
    assert len(formations)==1
    anchor=engine.state.objects[bell.placed.data(formations[0])['anchor_id']]
    assert anchor.ac==15 and anchor.current_hp==anchor.maximum_hp==72
    assert set(anchor.damage_immunities)=={'POISON','PSYCHIC'}
    assert not bell.held(engine.state.actors[OWNER],'ritual')


def test_watch_guarding_is_consumed_by_one_real_attack(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.WATCH],foe_position={'x':5,'y':6})
    cast(combat,table,mid,'Watch Bell',{'choice:needle.bell_warning_tone':'guarding','choice:needle.bell_guarding':[ALLY]})
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine
    attacks=[c for c in engine.legal_candidates() if c.target_ids==(ALLY,) and
        any(e.get('type')=='attack' for e in (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',[]))]
    assert attacks
    settle(table,mid,attacks[0].candidate_id)
    engine=reload(tmp_path,mid)
    assert not bell.held(engine.state.actors[ALLY],'guarding')
    assert not any(m.source_definition_id.endswith(bell.WATCH) and m.target_field=='armor_class'
                   for m in engine.state.actors[ALLY].modifiers.values())
    rolled=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and ALLY in e.target_ids]
    assert rolled and rolled[-1].payload['target_ac']==16


def test_mark_direction_is_private_even_to_another_bell_owner(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.WATCH],ally_talents=[bell.WATCH])
    cast(combat,table,mid,'Watch Bell',{'choice:needle.bell_warning_tone':'revealing','choice:needle.bell_reveal_target':FOE})
    engine=reload(tmp_path,mid)
    own=information.readings(engine,engine.state.actors[OWNER])
    assert any(row['kind']=='direction' and row['details']=={'direction':'east'} for row in own)
    assert information.readings(engine,engine.state.actors[ALLY])==[]
    assert all('position' not in row['details'] and 'target_id' not in row['details'] for row in own)


def test_mark_survives_native_darkness_for_only_its_actual_observer(tmp_path):
    from combat.senses import perceives
    successful_marks=0
    for index in range(4):
        root=tmp_path/str(index)
        combat,table,mid=play(root,features=[bell.WATCH],owner_pb=6,
            foe_sheet=sheet(['DARK_BASE_DARKNESS'],cl=18,name='Mara'),seed='BELL-DARK-'+str(index))
        cast(combat,table,mid,'Watch Bell',{'choice:needle.bell_warning_tone':'revealing',
            'choice:needle.bell_reveal_target':FOE})
        engine=reload(root,mid)
        mark=bell.held(engine.state.actors[FOE],'marked')[0]
        if mark.expires_on!=bell.UNTIL:continue
        successful_marks+=1
        turn(table,mid,FOE)
        c=candidate(combat,mid,'Darkness',at=(6,6))
        settle(table,mid,c.candidate_id)
        engine=reload(root,mid)
        assert perceives(engine,engine.state.actors[OWNER],engine.state.actors[FOE])
        assert not perceives(engine,engine.state.actors[ALLY],engine.state.actors[FOE])
        assert any(e.event_type=='ZONE_CREATED' for e in engine.events)
    assert successful_marks, 'Fixed native seeds must cover a failed Charisma save and its full Mark duration'


def test_information_rejects_unowned_authority_without_changing_native_state(tmp_path):
    combat,table,mid=play(tmp_path,features=[])
    engine=reload(tmp_path,mid)
    actor=engine.state.actors[OWNER]
    before=engine.state.model_dump(mode='json'),len(engine.events)
    with pytest.raises(ValueError,match='actual source owner'):
        information.publish(engine,actor,'invented:source',actor,'direction',{'direction':'east'},'END_OF_CURRENT_TURN')
    assert before==(engine.state.model_dump(mode='json'),len(engine.events))


def test_native_factory_request_collects_surprise_and_alarm_ignores_only_its_source(tmp_path):
    from app.models import CombatFactoryMatchRequest
    combat,table,unused=play(tmp_path,features=[bell.ALARM])
    request=CombatFactoryMatchRequest(project_ids=['worker2-owner','worker2-ally'],opponent_actor_ids=[FOE],
        control_modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'MANUAL'},match_seed='BELL-NATIVE-SURPRISE',
        arena_id=next(iter(combat.factory_arenas())),prefight={OWNER:[],ALLY:[],FOE:[]},
        surprised_actor_ids=[OWNER,ALLY])
    mid=combat.create_factory_match(**request.model_dump())['match_id']
    engine=reload(tmp_path,mid)
    rolls={r.actor_id:r for r in engine.rolls if r.reason=='INITIATIVE'}
    assert rolls[OWNER].mode=='ADVANTAGE'
    assert rolls[ALLY].mode=='DISADVANTAGE'
    assert rolls[FOE].mode=='NORMAL'
    created=next(e for e in engine.events if e.event_type=='MATCH_CREATED')
    assert created.payload['initiative_surprise']=={'actor_ids':sorted([OWNER,ALLY]),'authority':'table_owner'}


def test_revealing_active_effect_does_not_strip_its_holders_invisibility(tmp_path):
    invis='tianxia.talent.illusion.greater_invisibility'
    successes=0
    for index in range(3):
        root=tmp_path/str(index)
        combat,table,mid=fixture(root,[invis],owner_features=[bell.WATCH],cl=18,
            named=True,seed='BELL-RESONANCE-'+str(index))
        c=candidate(combat,mid,'Greater Invisibility',target=ALLY)
        settle(table,mid,c.candidate_id)
        engine=reload(root,mid)
        condition=next(c for c in engine.state.actors[ALLY].conditions.values()
            if c.condition_id=='condition:typed.invisible')
        cast(combat,table,mid,'Watch Bell',{'choice:needle.bell_warning_tone':'revealing',
            'choice:needle.bell_reveal_target':condition.instance_id})
        engine=reload(root,mid)
        ally=engine.state.actors[ALLY]
        assert condition.instance_id in ally.conditions
        if bell.held(ally,'resonance'):
            successes+=1
            assert bell.marked_visibility(engine,engine.state.actors[OWNER],ally) is None
            from combat.ext.information_sources import private_information
            owner=engine.state.actors[OWNER]
            readings=[c for c in owner.conditions.values() if c.condition_id==information.READING]
            assert readings and all(c.instance_id in private_information(engine,owner) for c in readings)
            assert any(e.event_type=='CHECK_ROLLED' and e.payload.get('check')=='Revealing Tone Cultivation Check'
                for e in engine.events)
    assert successes, 'The fixed native seeds must exercise a successful effect revelation'


def test_ninefold_scene_limit_survives_reopen_then_renews_after_native_journey_scene(tmp_path):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    combat,table,unused=play(tmp_path,features=[bell.NINE])
    positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}}
    journey=combat.create_journey(project_ids=['worker2-owner','worker2-ally','worker2-foe'],
        arena_id=next(iter(combat.factory_arenas())),positions=positions,
        base_paces={a:1000 for a in positions},control_modes={a:'MANUAL' for a in positions})
    jid=journey['journey_id'];teams={OWNER:'team:bell',ALLY:'team:bell',FOE:'team:other'}
    mid=combat.journey_start_combat(jid,journey['revision'],teams,maximum_rounds=1,positions=positions)['match_id']
    turn(table,mid,OWNER)
    cast(combat,table,mid,'Ninefold Heavenly Bell',{'choice:needle.bell_protected_allies':[OWNER,ALLY]})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[bell.QI]==92
    for _ in range(3):
        if combat._load_session(mid).engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    cold=CombatService(ROOT,tmp_path)
    journey=cold.journey_state(jid)
    journey=cold.journey_resume(jid,journey['revision'],effect_resolutions={OWNER:
        'GM ends the completed encounter Concentration before starting a separate scene; resources do not recover.'})
    journey=cold.journey_act(jid,journey['revision'],OWNER,'wait',{'seconds':60})
    second=cold.journey_start_combat(jid,journey['revision'],teams,maximum_rounds=1,positions=positions)['match_id']
    turn(table,second,OWNER)
    engine=reload(tmp_path,second)
    assert engine.state.actors[OWNER].action_available
    assert not any(c.display_name=='Ninefold Heavenly Bell' for c in engine.legal_candidates())
    assert engine.state.actors[OWNER].resources[bell.QI]==92
    for _ in range(3):
        if cold._load_session(second).engine.state.terminal_result is not None:break
        settle(table,second,table.state(second)['menu']['end_turn'])
    assert reload(tmp_path,second).state.terminal_result is not None
    journey=cold.journey_state(jid)
    journey=cold.journey_resume(jid,journey['revision'])
    journey=cold.journey_end_scene(jid,journey['revision'],'The intrusion is resolved; the party begins a new watch.')
    assert journey['events'][-1]['kind']=='SCENE_ENDED'
    third=cold.journey_start_combat(jid,journey['revision'],teams,maximum_rounds=1,positions=positions)['match_id']
    turn(table,third,OWNER)
    cast(cold,table,third,'Ninefold Heavenly Bell',{'choice:needle.bell_protected_allies':[OWNER,ALLY]})
    engine=reload(tmp_path,third)
    assert engine.state.actors[OWNER].resources[bell.QI]==84
