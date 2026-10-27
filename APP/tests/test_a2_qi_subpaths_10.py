"""A2GQISUB10: real service/table transactions, persisted rules and cold replay."""
import copy
import pytest
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from tests.h1_support import sheet
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

DREAM='tianxia.subpath.qi.dream_qi_cultivator.feature.'
MANTRA='tianxia.subpath.qi.mantra_cultivator.feature.'


def reseal(bundle):
    bundle.pop('bundle_sha256',None)
    bundle['bundle_sha256']=canonical_sha256(bundle)


def accuracy(bundles):
    for action in bundles[0]['action_catalog']:
        typed=action.get('parameters',{}).get('typed',{})
        typed.setdefault('numbers',{})['attack_bonus']=100
    reseal(bundles[0])


@pytest.mark.parametrize('cl,dice',[(6,3),(11,4),(17,5)])
@pytest.mark.parametrize('option,condition',[('Stolen Reaction','reaction_denied'),('Endless Corridor','speed'),
    ('False Opening','attack_mode'),('Fractured Concentration','concentration_mode'),('Shifting Horizon','lucid_horizon')])
def test_lucid_all_options_scaling_payment_and_source_expiry(tmp_path,cl,dice,option,condition):
    combat,table,mid=fixture(tmp_path,[DREAM+'lucid_strike'],cl=cl,seed='LUCID-'+option,owner_dc=100,bundle_transform=accuracy)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.qi']
    c=candidate(combat,mid,'Lucid Strike: '+option,target=FOE)
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid)
    damage=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and e.actor_id==OWNER]
    assert damage and damage[-1].payload['expression'].startswith(str(dice)+'d8')
    assert engine.state.actors[OWNER].resources['resource:core.qi']==before-2
    bars=list(engine.state.actors[FOE].conditions.values())
    if condition=='speed':
        assert any(m.target_field=='speed_ft' and int(m.value)==-10 for m in engine.state.actors[FOE].modifiers.values())
    elif condition=='attack_mode':
        assert any(m.target_field=='attack_mode' and m.value=='DISADVANTAGE' for m in engine.state.actors[FOE].modifiers.values())
    else:
        assert any(condition in b.condition_id for b in bars),[(b.condition_id,b.data) for b in bars]
    assert not any(e.event_type=='GM_RIDER' and 'lucid_strike' in e.source_definition_id for e in engine.events)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert not any('lucid_strike' in b.source_definition_id for b in engine.state.actors[FOE].conditions.values())
    assert not any('lucid_strike' in m.source_definition_id for m in engine.state.actors[FOE].modifiers.values())


def saves_fixture(bundles):
    bundle=bundles[2]
    effects=[{'type':'save','ability':'wis','applies_to':'target','on_fail':[{'type':'condition','condition':'frightened','applies_to':'target','expires_on':'END_OF_CURRENT_TURN'}],'on_success':[]}]
    row={'source_definition_id':'action:test.dream_ward_save','display_name':'Ward test save','owner_id':FOE,'economy':'NONE','resolution_kind':'TYPED',
         'target_kind':'HOSTILE_ENTITY','range_ft':60,'parameters':{'typed':{'source':'test:frightened','effects':effects,'numbers':{'save_dc':18},'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id']);reseal(bundle)


def test_dream_ward_advantage_optional_rescue_once_scene_and_reload(tmp_path):
    combat,table,mid=fixture(tmp_path,[DREAM+'dreamer_s_rest'],seed='WARD-SAVE',bundle_transform=saves_fixture)
    turn(table,mid,FOE)
    rescue_prompts=[]
    for _ in range(20):
        c=candidate(combat,mid,'Ward test save',target=OWNER)
        rescue_prompts.extend(settle(table,mid,c.candidate_id))
        engine=reload(tmp_path,mid)
        rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
        assert rolls[-1].payload['mode']=='ADVANTAGE'
        if any(c.condition_id=='condition:typed.dream_ward_used' for c in engine.state.actors[OWNER].conditions.values()):break
    else:pytest.fail('seed never reached a rescuable failed save')
    prompt=next(p for p in rescue_prompts if p['context']['reaction_source_id']=='choice:needle.dream_ward')
    assert prompt['action']=='Ward test save'
    assert 'Ward test save' in prompt['moment']
    assert prompt['trigger_actor'] and prompt['affected'] and 'actor:' not in prompt['moment']
    rescued=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and 'dreamer_s_rest' in e.source_definition_id]
    assert len(rescued)==1
    for _ in range(6):
        settle(table,mid,candidate(combat,mid,'Ward test save',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type=='D20_REWRITTEN' and 'dreamer_s_rest' in e.source_definition_id])==1


@pytest.mark.parametrize('controller,take', [('MANUAL', True), ('MANUAL', False), ('LOCAL_AUTO', True)])
def test_dream_ward_negative_save_rescue_choice_outcome_once_scene_and_reload(tmp_path, controller, take):
    def negative_save(bundles):
        saves_fixture(bundles)
        # Legal signed save modifier; the sealed seed draws (2, 4), then (4, 4).
        # Both advantaged saves total -1 against DC 5. PB 6 rescues either one.
        bundles[0]['actor_template']['saving_throws']['WIS'] = -5
        reseal(bundles[0])
        probe = next(row for row in bundles[2]['action_catalog'] if row['display_name'] == 'Ward test save')
        probe['parameters']['typed']['numbers']['save_dc'] = 5
        reseal(bundles[2])
    combat, table, mid = fixture(tmp_path, [DREAM+'dreamer_s_rest'], seed='WARD-NEGATIVE-2698',
        owner_pb=6, bundle_transform=negative_save)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=controller)
    prompts = settle(table, mid, candidate(combat, mid, 'Ward test save', target=OWNER).candidate_id,
        choices={'choice:needle.dream_ward': ['rescue'] if take else None})
    ward_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dream_ward']
    if controller == 'MANUAL':
        assert len(ward_prompts) == 1, 'Negative failed saves must offer the player Dream Ward'
        prompt = ward_prompts[0]
        assert prompt['action'] == 'Ward test save'
        assert 'Ward test save' in prompt['moment'] and 'Dream Ward' in prompt['moment']
        assert prompt['trigger_actor'] and prompt['affected'] and 'actor:' not in prompt['moment']
    else:
        assert not ward_prompts, 'The automatic recipient resolves its own rescue'
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and 'dreamer_s_rest' in e.source_definition_id]
    assert len(saves) == 1 and saves[0].payload['mode'] == 'ADVANTAGE'
    assert saves[0].payload['natural_result'] == 4 and saves[0].payload['dc'] == 5
    assert saves[0].payload['total'] == (5 if take else -1)
    assert saves[0].payload['success'] is take
    assert len(rewrites) == int(take)
    if take:
        assert rewrites[0].payload['original']['total'] == -1
        assert rewrites[0].payload['bonus'] == 6 and rewrites[0].payload['result']['total'] == 5
    owner = engine.state.actors[OWNER]
    assert sum(c.condition_id == 'condition:typed.dream_ward_used' for c in owner.conditions.values()) == int(take)
    assert any(c.condition_id == 'condition:typed.frightened' for c in owner.conditions.values()) is (not take)
    # A second equally rescuable save after cold reload cannot use a spent Ward.
    # Declining instead preserves the player's choice and leaves Ward available.
    prompts = settle(table, mid, candidate(combat, mid, 'Ward test save', target=OWNER).candidate_id,
        choices={'choice:needle.dream_ward': None})
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.dream_ward' for p in prompts) == int(not take)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(saves) == 2 and saves[-1].payload['total'] == -1 and saves[-1].payload['success'] is False
    assert any(c.condition_id == 'condition:typed.frightened' for c in engine.state.actors[OWNER].conditions.values())
    assert sum(c.condition_id == 'condition:typed.dream_ward_used' for c in engine.state.actors[OWNER].conditions.values()) == int(take)
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN' and 'dreamer_s_rest' in e.source_definition_id]) == int(take)


def test_dream_ward_manual_recipient_can_answer_on_automatic_foe_turn(tmp_path):
    def sole_ai_save(bundles):
        saves_fixture(bundles)
        bundle=bundles[2]
        probe=next(row for row in bundle['action_catalog'] if row['display_name']=='Ward test save')
        bundle['action_catalog']=[probe]
        bundle['actor_template']['action_ids']=[probe['source_definition_id']]
        reseal(bundle)
    combat,table,mid=fixture(tmp_path,[DREAM+'dreamer_s_rest'],seed='WARD-MIXED-AI-MANUAL',
        bundle_transform=sole_ai_save)
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    turn(table,mid,FOE)
    prompts=[]
    # Let the foe take its real automatic table step. The manual Dreamer must
    # still receive the optional rescue choice and answer it through that step.
    for _ in range(20):
        from tests.r1i_service_support import force_ai_candidate
        probe=candidate(combat,mid,'Ward test save',target=OWNER)
        force_ai_candidate(combat,mid,FOE,probe.candidate_id)
        result=table.auto_step(mid,0,[])
        while result['status']=='REACTION_REQUIRED':
            prompt=result['reaction'];prompts.append(prompt)
            if prompt['context']['reaction_source_id']=='choice:needle.dream_ward':
                answer={**prompt['context'],'selection':'USE','option_ids':['rescue']}
            else:
                # The automatic fighter can provoke an ordinary opportunity
                # reaction while moving to a legal attack position. Decline it
                # so the test observes the separate optional Dream Ward choice.
                answer={**prompt['context'],'selection':'DECLINE'}
            result=table.auto_step(mid,0,[answer])
        assert result['status']=='COMMITTED',result
        engine=reload(tmp_path,mid)
        if any(c.condition_id=='condition:typed.dream_ward_used' for c in engine.state.actors[OWNER].conditions.values()):
            break
    else:
        pytest.fail('the automatic foe turn never presented a rescuable Dream Ward prompt')
    ward_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.dream_ward')
    assert ward_prompt['action']=='Ward test save'
    assert 'Ward test save' in ward_prompt['moment'] and 'actor:' not in ward_prompt['moment']
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==OWNER]
    rescued=[e for e in engine.events if e.event_type=='D20_REWRITTEN' and 'dreamer_s_rest' in e.source_definition_id]
    assert rolls and rolls[-1].payload['mode']=='ADVANTAGE' and rescued
    assert len([c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id=='condition:typed.dream_ward_used'])==1


def ordinary_smoke_wall_fixture(bundles, *, magical=False):
    """Attach an ordinary smoke wall as a real table action for the opposing fighter."""
    from combat.factory_compiler import compile_character
    smoke=compile_character(sheet(['SMOKE_BASE_SMOKE_VEIL','TAL_SMOKE_WALL_OF_SMOKE']),actor_id=OWNER)
    row=next(row for row in smoke['action_catalog'] if row['display_name']=='Smoke Veil + Wall of Smoke')
    row=copy.deepcopy(row)
    row['source_definition_id']='action:test.ordinary_smoke_wall'
    row['display_name']='Raise ordinary smoke wall'
    row['owner_id']=OWNER;row['economy']='NONE';row['costs']=[]
    row['parameters']['typed']['zone_spec']['visual']['magical']=magical
    bundles[0]['action_catalog'].append(row)
    bundles[0]['actor_template']['action_ids'].append(row['source_definition_id'])
    probe={'source_definition_id':'action:test.horizon_followup','display_name':'Horizon follow-up attack',
        'owner_id':OWNER,'economy':'NONE','resolution_kind':'ATTACK','target_kind':'HOSTILE_ENTITY','range_ft':60,
        'attack_bonus':100,'damage':{'count':1,'sides':4,'modifier':0},'damage_type':'FORCE',
        'parameters':{},'costs':[]}
    bundles[0]['action_catalog'].append(probe)
    bundles[0]['actor_template']['action_ids'].append(probe['source_definition_id'])
    reseal(bundles[0])


@pytest.mark.parametrize('magical',[False,True])
def test_horizon_native_hide_across_smoke_wall_through_table_and_reload(tmp_path,magical):
    from combat import stealth,zones
    def prepare(bundles):
        accuracy(bundles)
        ordinary_smoke_wall_fixture(bundles,magical=magical)
    foe=sheet([])
    foe['ability_scores_and_statistics']['skills']=[{'skill':'Stealth','bonus':100}]
    combat,table,mid=fixture(tmp_path,[DREAM+'lucid_strike'],seed='HORIZON-HIDE-SMOKE-2',
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':8,'y':6}},foe_sheet=foe,owner_dc=100,bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Raise ordinary smoke wall',at=(5,6)).candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Hide').candidate_id)
    engine=reload(tmp_path,mid)
    wall=next(z for z in zones.typed_zones(engine) if z.source_definition_id=='action:test.ordinary_smoke_wall')
    owner,foe_actor=engine.state.actors[OWNER],engine.state.actors[FOE]
    assert not zones._inside(engine,owner,wall) and not zones._inside(engine,foe_actor,wall)
    assert zones.ordinary_visual_wall_between(engine,owner,foe_actor) is not magical
    assert engine.grid.line_of_sight(owner.position,foe_actor.position)
    assert stealth.hidden(engine.state.actors[FOE])
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Lucid Strike: Shifting Horizon',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.lucid_horizon' for c in engine.state.actors[FOE].conditions.values())
    attack=candidate(combat,mid,'Horizon follow-up attack',target=FOE)
    settle(table,mid,attack.candidate_id)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER and FOE in e.target_ids]
    assert rolls and rolls[-1].payload['mode']==('DISADVANTAGE' if magical else 'NORMAL')
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER and FOE in e.target_ids]
    # Horizon masks only the ordinary visual Hide rider for this attacker; it
    # does not remove the target's native Hidden condition. Magical smoke keeps
    # the disadvantage, while ordinary smoke permits the normal roll above.
    assert damage and stealth.hidden(engine.state.actors[FOE])


@pytest.mark.parametrize('kind',['Fortitude','Precision','Motion',*['Endurance: '+t for t in ['Acid','Cold','Fire','Lightning','Necrotic','Poison','Radiant','Thunder']]])
def test_great_mantra_aura_chosen_allies_payment_and_cold_reload(tmp_path,kind):
    from combat.ext import mantra_fields,placed
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra'],seed='MANTRA-'+kind)
    c=candidate(combat,mid,'Great Mantra: Great Mantra of '+kind)
    settle(table,mid,c.candidate_id,choices={'choice:needle.great_mantra_allies':[OWNER,ALLY]})
    engine=reload(tmp_path,mid)
    zone=placed.of(engine,'great_mantra')[0]
    assert placed.data(zone)['chosen']==[OWNER,ALLY]
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95
    assert not mantra_fields._zones(engine,engine.state.actors[FOE])
    if kind=='Motion':
        assert mantra_fields.motion(engine,engine.state.actors[ALLY])==10
        assert mantra_fields.motion_stand(engine,engine.state.actors[ALLY],15)==5
    if kind.startswith('Endurance'):
        assert mantra_fields.endurance(engine,engine.state.actors[ALLY],'FIRE',{},FOE)[0]['damage_types']==[kind.split(': ')[1].upper()]
    # A subsequent concentration action replaces this aura, with no lingering buffs.
    turn(table,mid,OWNER)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    replacement=candidate(combat,mid,'Great Mantra: Great Mantra of Motion')
    settle(table,mid,replacement.candidate_id,choices={'choice:needle.great_mantra_allies':[OWNER]})
    engine=reload(tmp_path,mid)
    assert len(placed.of(engine,'great_mantra'))==1
    assert not mantra_fields._zones(engine,engine.state.actors[ALLY])


def test_great_mantra_automatic_recipients_are_allies(tmp_path):
    from combat.ext import placed
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra'],seed='MANTRA-AUTO',ask=False,
                            modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    # The existing explicit-choice bridge applies the automatic owner policy.
    c=candidate(combat,mid,'Great Mantra: Great Mantra of Precision')
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(intent_id='automatic-aura',decision_id=c.decision_id,candidate_id=c.candidate_id,state_version=c.state_version,actor_id=OWNER,target_ids=c.target_ids,destination=c.destination))
    engine=reload(tmp_path,mid)
    chosen=placed.data(placed.of(engine,'great_mantra')[0])['chosen']
    assert OWNER in chosen and ALLY in chosen and FOE not in chosen


def test_great_mantra_fortitude_changes_an_actual_service_save(tmp_path):
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra'],seed='MANTRA-FORTITUDE',bundle_transform=saves_fixture)
    c=candidate(combat,mid,'Great Mantra: Great Mantra of Fortitude')
    settle(table,mid,c.candidate_id,choices={'choice:needle.great_mantra_allies':[ALLY]})
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Ward test save',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY]
    assert rolls and rolls[-1].payload['mode']=='ADVANTAGE'


def damage_probe_fixture(bundles):
    """A deterministic hostile damage action that exercises the real defense pipeline."""
    bundle=bundles[2]
    row={'source_definition_id':'action:test.mantra.fire_damage','display_name':'Mantra fire probe','owner_id':FOE,
         'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
         'parameters':{'typed':{'source':'test:fire_probe','effects':[{'type':'damage','flat':20,
             'damage_types':['fire'],'applies_to':'target'}],'numbers':{},
             'duration':{'kind':'instant'},'riders':[]},'expected_damage':20}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id']);reseal(bundle)


def test_great_mantra_endurance_resists_committed_damage_only_for_selected_ally(tmp_path):
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra'],seed='MANTRA-ENDURANCE-DAMAGE',bundle_transform=damage_probe_fixture)
    settle(table,mid,candidate(combat,mid,'Great Mantra: Great Mantra of Endurance: Fire').candidate_id,
           choices={'choice:needle.great_mantra_allies':[ALLY]})
    turn(table,mid,FOE)
    for target in (ALLY,OWNER):
        before=reload(tmp_path,mid).state.actors[target].current_hp
        settle(table,mid,candidate(combat,mid,'Mantra fire probe',target=target).candidate_id)
        engine=reload(tmp_path,mid)
        after=engine.state.actors[target].current_hp
        assert before-after==(10 if target==ALLY else 20)
        committed=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and target in e.target_ids]
        assert committed


def motion_ground_fixture(bundles):
    """Add a normal service action that creates nonmagical difficult ground."""
    bundle=bundles[0]
    row={'source_definition_id':'action:test.mantra.difficult_ground','display_name':'Create difficult ground',
         'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','range_ft':0,
         'parameters':{'typed':{'source':'test:difficult_ground','effects':[],
             'zone_spec':{'name':'Loose rubble','difficult':'all','shape':'sphere','size_ft':20,
                          'centered_on_self':True,'duration':{},
                          'source_profile':{'schema':'TianxiaFoundry.ZoneSource.v1','mundane':1}},'numbers':{},
             'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id']);reseal(bundle)
    prone={'source_definition_id':'action:test.mantra.prone_self','display_name':'Fall Prone',
       'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF',
       'parameters':{'typed':{'source':'test:prone_self','effects':[{'type':'condition','condition':'prone','applies_to':'self'}],
       'numbers':{},'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}}
    bundle['action_catalog'].append(prone);bundle['actor_template']['action_ids'].append(prone['source_definition_id']);reseal(bundle)


def test_great_mantra_motion_committed_traversal_and_standing_cost(tmp_path):
    from combat import zones
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra'],seed='MANTRA-MOTION-CONSUMERS',
                             bundle_transform=motion_ground_fixture)
    settle(table,mid,candidate(combat,mid,'Great Mantra: Great Mantra of Motion').candidate_id,
           choices={'choice:needle.great_mantra_allies':[OWNER]})
    settle(table,mid,candidate(combat,mid,'Create difficult ground').candidate_id)
    engine=reload(tmp_path,mid)
    ground=next(z for z in zones.typed_zones(engine) if z.source_definition_id=='action:test.mantra.difficult_ground')
    cells={(p.x,p.y) for p in ground.affected_cells}
    options=[c for c in engine.legal_candidates() if c.actor_id==OWNER and c.destination and c.canonical_path
             and any((p.x,p.y) in cells for p in c.canonical_path[1:])]
    from math import ceil
    def natural_cost(path):
        return ceil(sum(engine.grid.distance_ft(a,b) for a,b in zip(path,path[1:])))
    options=[c for c in options if all(p.z==0 for p in c.canonical_path)]
    move=next(c for c in options if c.movement_cost_ft==natural_cost(c.canonical_path))
    path=[{'x':p.x,'y':p.y,'z':p.z} for p in move.canonical_path]
    quote=table.preview_move_path(mid,move.decision_id,move.state_version,OWNER,path)
    result=table.commit_move_path(mid,quote['candidate']['candidate_id'],move.decision_id,
                                  move.state_version,OWNER,path)
    assert result['status']=='COMMITTED',result
    engine=reload(tmp_path,mid)
    movement=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER]
    expected_cost=natural_cost(move.canonical_path)
    assert movement and movement[-1].payload['cost_ft']==expected_cost
    destination=path[-1]
    assert (engine.state.actors[OWNER].position.x,engine.state.actors[OWNER].position.y)==(destination['x'],destination['y'])

    # Prone is applied through an ordinary committed action; the holder's next
    # native start-turn checkpoint performs the reduced-cost stand and persists it.
    settle(table,mid,candidate(combat,mid,'Fall Prone').candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    stood=[e for e in engine.events if e.event_type=='STOOD_UP' and e.actor_id==OWNER]
    assert stood and stood[-1].payload['cost_ft']==5
    assert not any(c.condition_id.endswith('.prone') for c in engine.state.actors[OWNER].conditions.values())


def test_mantra_silence_exemptions_voice_and_boundary(tmp_path):
    from combat import speech,typed_executor
    from combat.ext import placed
    combat,table,mid=fixture(tmp_path,[MANTRA+'mantra_of_silence','tianxia.subpath.qi.kiai_master.feature.kiai'],seed='SILENCE')
    c=candidate(combat,mid,'Mantra of Silence',at=(3,6))
    settle(table,mid,c.candidate_id,choices={'choice:needle.mantra_silence_exempt':[OWNER]})
    engine=reload(tmp_path,mid)
    assert not typed_executor.cant_hear(engine.state.actors[OWNER])
    assert typed_executor.cant_hear(engine.state.actors[ALLY])
    assert typed_executor.cant_hear(engine.state.actors[FOE])
    assert speech.silenced(engine.state.actors[FOE])
    assert not speech.silenced(engine.state.actors[OWNER])
    assert not speech.can_hear_from(engine,engine.state.actors[FOE],engine.state.actors[OWNER])
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95
    assert len(placed.of(engine,'mantra_silence'))==1
    # Standalone area damage retains its damage type and does not become immune to Thunder.
    assert not any(m.target_field=='damage_immunity' for m in engine.state.actors[FOE].modifiers.values())


def test_mantra_silence_automatic_exempts_allies_not_foes(tmp_path):
    from combat.ext import placed
    combat,table,mid=fixture(tmp_path,[MANTRA+'mantra_of_silence'],seed='SILENCE-AUTO',ask=False,
                            modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    c=candidate(combat,mid,'Mantra of Silence',at=(3,6))
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(intent_id='automatic-aura',decision_id=c.decision_id,candidate_id=c.candidate_id,state_version=c.state_version,actor_id=OWNER,target_ids=c.target_ids,destination=c.destination))
    engine=reload(tmp_path,mid)
    exempt=placed.data(placed.of(engine,'mantra_silence')[0])['exempt']
    assert OWNER in exempt and ALLY in exempt and FOE not in exempt


def test_flowing_passage_route_recipients_payment_and_reload(tmp_path):
    from combat.ext import placed,riverway_passage
    prefix='tianxia.subpath.qi.riverway_cultivator.feature.'
    combat,table,mid=fixture(tmp_path,[prefix+'flowing_passage'],seed='PASSAGE',ally_position={'x':3,'y':7},foe_position={'x':6,'y':5})
    c=candidate(combat,mid,'Flowing Passage',at=(3,6))
    choices={'choice:needle.flowing_passage_allies':[OWNER,ALLY]}
    for n in range(1,6):choices['choice:needle.flowing_passage_cell.'+str(n)]=[f'cell:{3+n},6']
    settle(table,mid,c.candidate_id,choices=choices)
    engine=reload(tmp_path,mid)
    zone=placed.of(engine,'riverway_passage')[0]
    assert [(p.x,p.y) for p in zone.affected_cells]==[(x,6) for x in range(3,9)]
    assert placed.data(zone)['chosen']==[OWNER,ALLY]
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert riverway_passage.current_speed(engine,engine.state.actors[OWNER])==5
    assert riverway_passage.current_speed(engine,engine.state.actors[FOE]) is None
    moves=[c for c in engine.legal_candidates() if c.destination and (c.destination.x,c.destination.y)==(8,6) and c.canonical_path]
    assert moves
    move=moves[0]
    path=[{'x':x,'y':6,'z':0} for x in range(3,9)]
    quote=table.preview_move_path(mid,move.decision_id,move.state_version,OWNER,path)
    result=table.commit_move_path(mid,quote['candidate']['candidate_id'],move.decision_id,move.state_version,OWNER,path)
    assert result['status']=='COMMITTED',result
    engine=reload(tmp_path,mid)
    assert (engine.state.actors[OWNER].position.x,engine.state.actors[OWNER].position.y)==(8,6)
    assert engine.state.actors[OWNER].turn_flags[riverway_passage.USED]['reactor']==FOE
    assert not any(e.event_type=='REACTION_USED' and e.actor_id==FOE for e in engine.events)


def passage_difficult_ground_fixture(bundles, *, magical_overlap=False):
    """Create character-owned mundane ground, optionally covered by magical ground."""
    bundle=bundles[0]
    for name, mundane in [('Create mundane rubble',1), *([('Create magical stone',0)] if magical_overlap else [])]:
        row={'source_definition_id':'action:test.passage.'+str(mundane),'display_name':name,
             'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','range_ft':0,
             'parameters':{'typed':{'source':'test:passage_difficult_ground','effects':[],
                 'zone_spec':{'name':name,'difficult':'all','shape':'sphere','size_ft':20,
                     'centered_on_self':True,'duration':{},
                     'source_profile':{'schema':'TianxiaFoundry.ZoneSource.v1','mundane':mundane}},
                 'numbers':{},'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}}
        bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id'])
    reseal(bundle)


@pytest.mark.parametrize('magical_overlap',[False,True])
def test_flowing_passage_exempts_character_created_mundane_terrain_only(tmp_path,magical_overlap):
    from math import ceil
    from combat import zones
    from combat.ext import placed
    prefix='tianxia.subpath.qi.riverway_cultivator.feature.'
    combat,table,mid=fixture(tmp_path,[prefix+'flowing_passage'],seed='PASSAGE-MUNDANE-'+str(magical_overlap),
        ally_position={'x':2,'y':2},foe_position={'x':8,'y':8},
        bundle_transform=lambda bundles: passage_difficult_ground_fixture(bundles,magical_overlap=magical_overlap))
    settle(table,mid,candidate(combat,mid,'Create mundane rubble').candidate_id)
    if magical_overlap:
        settle(table,mid,candidate(combat,mid,'Create magical stone').candidate_id)
    choices={'choice:needle.flowing_passage_allies':[OWNER]}
    for n in range(1,6):choices['choice:needle.flowing_passage_cell.'+str(n)]=[f'cell:{3+n},6']
    settle(table,mid,candidate(combat,mid,'Flowing Passage',at=(3,6)).candidate_id,choices=choices)
    engine=reload(tmp_path,mid)
    passage=placed.of(engine,'riverway_passage')[0]
    assert len([z for z in zones.typed_zones(engine) if z.source_definition_id.startswith('action:test.passage.')])==(2 if magical_overlap else 1)
    assert OWNER in placed.data(passage)['chosen']
    natural=lambda path:ceil(sum(engine.grid.distance_ft(a,b) for a,b in zip(path,path[1:])))
    moves=[c for c in engine.legal_candidates() if c.actor_id==OWNER and c.destination
           and (c.destination.x,c.destination.y)==(6,6) and c.canonical_path
           and all(p.y==6 and p.z==0 for p in c.canonical_path)]
    move=next(c for c in moves if c.movement_cost_ft==(natural(c.canonical_path)*(2 if magical_overlap else 1)))
    expected=natural(move.canonical_path)
    assert move.movement_cost_ft==(expected*2 if magical_overlap else expected)
    path=[{'x':p.x,'y':p.y,'z':p.z} for p in move.canonical_path]
    quote=table.preview_move_path(mid,move.decision_id,move.state_version,OWNER,path)
    result=table.commit_move_path(mid,quote['candidate']['candidate_id'],move.decision_id,
        move.state_version,OWNER,path)
    assert result['status']=='COMMITTED',result
    engine=reload(tmp_path,mid)
    committed=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER]
    assert committed and committed[-1].payload['cost_ft']==(expected*2 if magical_overlap else expected)

BANNER='tianxia.subpath.qi.banner_cultivator.feature.'


def test_banner_projected_stats_and_rally_immediate_recipient_step(tmp_path):
    from combat.ext import placed,banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'rally_the_line'],seed='BANNER-RALLY',foe_position={'x':5,'y':5})
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    engine=reload(tmp_path,mid)
    zone=placed.of(engine,'standard')[0]
    obj=engine.state.objects['object:banner:'+zone.zone_id]
    assert obj.ac==14 and obj.current_hp==45 and obj.maximum_hp==45
    assert obj.damage_immunities==('POISON','PSYCHIC') and not obj.component['blocks']
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    prompts=settle(table,mid,candidate(combat,mid,'Rally the Line (2 Qi)').candidate_id,
           choices={'choice:needle.rally_allies':[ALLY],'choice:needle.rider_step':['cell:4,7']})
    step_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.rider_step')
    assert 'Rally the Line' in step_prompt['moment'] and 'Action:Typed.' not in step_prompt['moment']
    engine=reload(tmp_path,mid)
    ally=engine.state.actors[ALLY]
    assert (ally.position.x,ally.position.y)==(4,7)
    assert ally.temporary_hp>0 and engine.state.actors[OWNER].temporary_hp==0 and engine.state.actors[FOE].temporary_hp==0
    assert not any(c.condition_id==banner.STEP for c in ally.conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.qi']==97
    movement=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY]
    assert movement and movement[-1].payload['cost_ft']==0
    assert not any(e.event_type=='REACTION_RESOLVED' and e.actor_id==FOE for e in engine.events)


def test_advancing_standard_start_turn_immediate_step(tmp_path):
    from combat.ext import placed,banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'advancing_standard'],seed='BANNER-ADVANCE')
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Advancing Standard (4 Qi)').candidate_id)
    # The new turn choice is raised while advancing initiative, within the persisted end-turn intent.
    for _ in range(4):
        if table.state(mid)['menu']['actor_id']==ALLY:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={'choice:needle.rider_step':['cell:4,7']})
    engine=reload(tmp_path,mid)
    assert engine.state.current_actor_id==ALLY
    assert (engine.state.actors[ALLY].position.x,engine.state.actors[ALLY].position.y)==(4,7)
    assert not any(c.condition_id==banner.STEP for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95
    assert banner._aura(engine,placed.of(engine,'standard')[0])==20


def test_imperial_standard_recipient_selection_native_steps_and_replacement(tmp_path):
    from combat.ext import placed,banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'advancing_standard',BANNER+'imperial_standard_of_heaven'],cl=18,seed='BANNER-IMPERIAL')
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    for _ in range(4):
        if table.state(mid)['menu']['actor_id']==OWNER:break
        settle_imperial_steps(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    assert engine.state.current_actor_id==OWNER
    assert (engine.state.actors[ALLY].position.x,engine.state.actors[ALLY].position.y)==(4,7)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==91
    assert banner._aura(engine,placed.of(engine,'standard')[0])==40
    assert banner.guarded_ac(engine,engine.state.actors[ALLY])==1
    assert not any(c.condition_id==banner.STEP for c in engine.state.actors[ALLY].conditions.values())


def victor_attacks_fixture(bundles):
    from tests.worker2_support import sealed_native_attack
    for bundle in bundles[:2]:
        sealed_native_attack(bundle,'Victor test hit',damage_type='FORCE',modifier=50,attack_bonus=100)


def test_follow_the_victor_decline_keeps_round_use_for_later_hit(tmp_path):
    from combat.ext import banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'imperial_standard_of_heaven'],
                             seed='BANNER-VICTOR-DECLINE',bundle_transform=victor_attacks_fixture)
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id)
    settle(table,mid,candidate(combat,mid,'Victor test hit',target=FOE).candidate_id,
           choices={'choice:needle.follow_the_victor':[]})
    engine=reload(tmp_path,mid)
    use=f"banner_victor_round_{engine.state.round_number}"
    assert not engine.state.actors[OWNER].turn_flags.get(use)
    turn(table,mid,ALLY)
    prompts=settle(table,mid,candidate(combat,mid,'Victor test hit',target=FOE).candidate_id,
                   choices={'choice:needle.follow_the_victor':[OWNER],'choice:needle.rider_step':[]})
    assert any(p['context']['reaction_source_id']=='choice:needle.follow_the_victor' for p in prompts)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].turn_flags.get(f"banner_victor_round_{engine.state.round_number}")


def test_silken_whip_player_damage_choice_cost_and_cold_reload(tmp_path):
    feature='tianxia.subpath.qi.iron_cloth_cultivator.feature.silken_whip'
    combat,table,mid=fixture(tmp_path,[feature],seed='SILKEN',bundle_transform=accuracy)
    settle(table,mid,candidate(combat,mid,'Silken Whip').candidate_id)
    settle(table,mid,candidate(combat,mid,'Silken Whip Attack',target=FOE).candidate_id,
           choices={'choice:needle.silken_whip_type':['FORCE']})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert all(c.expires_on!='UNTIL_REMOVED' for c in engine.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.silken_whip')
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER and FOE in e.target_ids]
    assert damage and damage[-1].payload['damage_type']=='FORCE'


def object_attack_fixture(bundles):
    bundle=bundles[2]
    row={'source_definition_id':'action:test.banner.object_damage','display_name':'Banner destruction test','owner_id':FOE,'economy':'NONE','resolution_kind':'TYPED',
         'target_kind':'OBJECT','range_ft':60,'parameters':{'typed':{'source':'test:object_damage','effects':[{'type':'object_damage','flat':200,'damage_types':['force']}],
         'numbers':{},'duration':{'kind':'instant'},'riders':[]},'expected_damage':200}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id']);reseal(bundle)


@pytest.mark.parametrize('imperial',[False,True])
def test_banner_object_destruction_and_lower_cl_protection_through_service(tmp_path,imperial):
    from combat.ext import placed
    features=[BANNER+'raise_the_standard']+([BANNER+'imperial_standard_of_heaven'] if imperial else [])
    combat,table,mid=fixture(tmp_path,features,cl=18,seed='BANNER-DESTRUCTION',bundle_transform=object_attack_fixture,foe_sheet=sheet([],cl=3))
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    if imperial:
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
        settle(table,mid,candidate(combat,mid,'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id)
    engine=reload(tmp_path,mid)
    zone=placed.of(engine,'standard')[0];oid='object:banner:'+zone.zone_id
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Banner destruction test',target=oid).candidate_id)
    engine=reload(tmp_path,mid)
    obj=engine.state.objects[oid]
    if imperial:
        assert obj.current_hp==1 and not obj.destroyed and placed.of(engine,'standard')
    else:
        assert obj.current_hp==0 and obj.destroyed and not placed.of(engine,'standard')


def test_silence_start_turn_relief_and_native_three_dimensional_boundary(tmp_path):
    from combat import speech,typed_executor,zones
    from combat.ext import placed
    from combat.gate2_runtime_models import Position
    combat,table,mid=fixture(tmp_path,[MANTRA+'mantra_of_silence'],seed='SILENCE-RELIEF',owner_dc=1)
    settle(table,mid,candidate(combat,mid,'Mantra of Silence',at=(3,6)).candidate_id,
           choices={'choice:needle.mantra_silence_exempt':[OWNER]})
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE];owner=engine.state.actors[OWNER]
    assert not typed_executor.cant_hear(foe) and not speech.silenced(foe)
    relief=next(c for c in foe.conditions.values() if c.condition_id=='condition:typed.mantra_silence_relief')
    assert relief.expires_on.startswith(f'START_OF_TURN_AT:{FOE}:')
    assert speech.can_hear_from(engine,foe,owner)
    zone=placed.of(engine,'mantra_silence')[0]
    assert zone.center==Position(x=3,y=6)
    high=foe.model_copy(deep=True,update={'position':Position(x=3,y=6,z=5)})
    assert zones._inside(engine,high,zone)
    beyond=foe.model_copy(deep=True,update={'position':Position(x=3,y=6,z=8)})
    assert not zones._inside(engine,beyond,zone)
    assert not speech.can_hear_from(engine,owner,beyond)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.mantra_silence_relief' for c in engine.state.actors[FOE].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'],decline_after=0)
    settle(table,mid,table.state(mid)['menu']['end_turn'],decline_after=0)
    engine=reload(tmp_path,mid)
    # A successful start-turn save may immediately grant a fresh instance; the
    # prior instance must still have expired at the holder's start checkpoint.
    removed=[e for e in engine.events if e.event_type=='CONDITION_REMOVED'
             and e.payload.get('condition_id')=='condition:typed.mantra_silence_relief']
    assert any(e.payload.get('checkpoint')=='START_OF_TURN' for e in removed)


def test_rally_automatic_recipients_pick_perceived_allies(tmp_path):
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'rally_the_line'],seed='BANNER-AUTO',ask=False)
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='LOCAL_AUTO')
    c=candidate(combat,mid,'Rally the Line (2 Qi)')
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(intent_id='automatic-rally',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=OWNER,target_ids=c.target_ids,destination=c.destination))
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].temporary_hp>0 and engine.state.actors[ALLY].temporary_hp>0
    assert engine.state.actors[FOE].temporary_hp==0


def survival_damage_fixture(bundles):
    bundle=bundles[2]
    row={'source_definition_id':'action:test.banner.survival_damage','display_name':'Standard survival test','owner_id':FOE,'economy':'NONE','resolution_kind':'TYPED',
         'target_kind':'HOSTILE_ENTITY','range_ft':60,'parameters':{'typed':{'source':'test:survival_damage','effects':[{'type':'damage','flat':70,'damage_types':['force'],'applies_to':'target'}],
         'numbers':{},'duration':{'kind':'instant'},'riders':[]},'expected_damage':70}}
    bundle['action_catalog'].append(row);bundle['actor_template']['action_ids'].append(row['source_definition_id']);reseal(bundle)


def test_standard_cannot_fall_steps_after_hp_commit_once_per_activation(tmp_path):
    from combat.ext import placed,banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard',BANNER+'imperial_standard_of_heaven'],cl=18,seed='BANNER-SURVIVAL',bundle_transform=survival_damage_fixture)
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(3,7)).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id,
           choices={'choice:needle.imperial_allies':[OWNER]})
    engine=reload(tmp_path,mid)
    assert placed.data(placed.of(engine,'standard')[0])['imperial_chosen']==[OWNER]
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Standard survival test',target=ALLY).candidate_id,
           choices={'choice:needle.rider_step':['cell:4,7']})
    engine=reload(tmp_path,mid);ally=engine.state.actors[ALLY]
    assert ally.current_hp==1 and ally.active and (ally.position.x,ally.position.y)==(4,7)
    assert ALLY in placed.data(placed.of(engine,'standard')[0])['held']
    assert not any(c.condition_id==banner.STEP for c in ally.conditions.values())
    events=[e for e in engine.events if e.event_type in {'DAMAGE_COMMITTED','MOVEMENT_COMMITTED'} and (ALLY in e.target_ids or e.actor_id==ALLY)]
    damage=next(i for i,e in enumerate(events) if e.event_type=='DAMAGE_COMMITTED')
    movement=next(i for i,e in enumerate(events) if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY)
    assert damage<movement
    settle(table,mid,candidate(combat,mid,'Standard survival test',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==0


def settle_imperial_steps(table,mid,cid):
    from tests.test_r9i_karma_persistence import act
    answers=[]
    for _ in range(20):
        result=act(table,mid,cid,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            return
        prompt=result['reaction'];context=prompt['context'];rid=context['reaction_source_id']
        options=None
        if rid=='choice:needle.imperial_advance':options=[ALLY]
        elif rid=='choice:needle.rider_step' and context['reactor_id']==ALLY:options=['cell:4,7']
        elif (prompt.get('choice') or {}).get('allow_decline') is False:
            options=(prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1]
        answers.append({**context,'selection':'USE' if options else 'DECLINE',**({'option_ids':options} if options else {})})
    raise AssertionError('Too many Imperial prompts')


@pytest.mark.parametrize('native',[False,True])
def test_precision_adds_exactly_one_to_actual_typed_and_native_rolls(tmp_path,native):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        accuracy(bundles)
        if native:sealed_native_attack(bundles[0],'Mantra native probe',attack_bonus=100,modifier=0)
    combat,table,mid=fixture(tmp_path,[MANTRA+'great_mantra',DREAM+'lucid_strike'],seed='MANTRA-ROLL',bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Great Mantra: Great Mantra of Precision').candidate_id,
           choices={'choice:needle.great_mantra_allies':[OWNER]})
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    name='Mantra native probe' if native else 'Lucid Strike: Stolen Reaction'
    settle(table,mid,candidate(combat,mid,name,target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER]
    assert rolls and rolls[-1].payload['modifier']==101,rolls[-1].payload if rolls else None


def test_banner_aura_uses_native_line_of_effect_across_pillars(tmp_path):
    from combat.ext import banner
    combat,table,mid=fixture(tmp_path,[BANNER+'raise_the_standard'],seed='BANNER-LOE',
        positions={OWNER:{'x':3,'y':3},ALLY:{'x':8,'y':3},FOE:{'x':3,'y':6}})
    settle(table,mid,candidate(combat,mid,'Manifest Command Banner (1 Qi)',at=(5,3)).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.grid.distance_ft(engine.state.actors[ALLY].position,banner._banner(engine,engine.state.actors[OWNER]).center)==15
    assert banner._banners_over(engine,engine.state.actors[OWNER])
    assert not banner._banners_over(engine,engine.state.actors[ALLY])
    assert engine._effective_speed(engine.state.actors[OWNER])==35
    assert engine._effective_speed(engine.state.actors[ALLY])==30
