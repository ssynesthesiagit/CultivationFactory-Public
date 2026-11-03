"""Jester: actual table transactions and cold reload/mechanical replay."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload, sealed_native_attack
from tests.cw2_service_support import add_action, seal
T='tianxia.talent.jester.'

def corridor(arena):
    arena['terrain_regions']=[{'region_id':'corridor','terrain_type':'BLOCKED','movement_cost':0,
        'description':'Narrow corridor','cells':[{'x':x,'y':y} for x in range(20) for y in range(14) if y!=6]}]

def configure(bs):
    for b,bonus in zip(bs,[100,0,-100]):
        b['actor_template']['initiative_bonus']=bonus;seal(b)

POSITIONS={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},ALLY:{'x':8,'y':6}}

@pytest.mark.parametrize('prone',[False,True])
def test_painted_exit_crosses_enemy_at_double_cost_before_prone(tmp_path,prone):
    combat,table,mid=fixture(tmp_path,[T+'painted_exit'],bundle_transform=configure,
        positions=POSITIONS,battlefield_transform=corridor)
    before=reload(tmp_path,mid).state.actors[OWNER].movement_remaining_ft
    prompts=settle(table,mid,candidate(combat,mid,'Painted Exit: '+('Fall Prone' if prone else 'Remain Standing')).candidate_id,
        {'choice:needle.rider_step':'cell:5,6'})
    p=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.rider_step')
    assert 'cell:4,6' not in [o['id'] for o in p['choice']['options']]
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    assert a.position.x==5 and a.movement_remaining_ft==before
    assert any(c.condition_id.endswith('.prone') for c in a.conditions.values())==prone
    ev=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==OWNER][-1]
    assert ev.payload.get('actual_cost_ft',ev.payload.get('planned_cost_ft'))==15
    assert not a.turn_flags.get('oa_free_ft')

@pytest.mark.parametrize('size,allowed',[('Large',True),('Huge',False)])
def test_painted_exit_size_limit(tmp_path,size,allowed):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['size_category']=size;seal(bs[2])
    combat,table,mid=fixture(tmp_path,[T+'painted_exit'],bundle_transform=setup,
        positions=POSITIONS,battlefield_transform=corridor)
    prompts=settle(table,mid,candidate(combat,mid,'Painted Exit: Remain Standing').candidate_id,
        {'choice:needle.rider_step':'cell:5,6'} if allowed else {})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==(5 if allowed else 3)
    options=[o['id'] for p in prompts if p.get('choice') for o in p['choice']['options']]
    assert ('cell:5,6' in options)==allowed

def test_dancing_fool_free_ally_space_enemy_crossing_once(tmp_path):
    combat,table,mid=fixture(tmp_path,[T+'dancing_fool'],bundle_transform=configure,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':6,'y':6}},battlefield_transform=corridor)
    settle(table,mid,candidate(combat,mid,'Disengage').candidate_id)
    e=reload(tmp_path,mid)
    move=next(c for c in e.legal_candidates() if c.destination and c.destination.x==7 and c.destination.y==6)
    assert move.movement_cost_ft==25
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.x==7
    assert e.state.actors[OWNER].turn_flags['jester_dancing_crossed']==FOE
    assert not any(c.destination and c.destination.x<6 for c in e.legal_candidates())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not reload(tmp_path,mid).state.actors[OWNER].turn_flags.get('disengaged')
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Disengage').candidate_id)
    assert any(c.destination and c.destination.x==5 for c in reload(tmp_path,mid).legal_candidates())

def test_court_hermit_crosses_enemy_after_missed_attack(tmp_path):
    def setup(bs):
        configure(bs);sealed_native_attack(bs[2],'Miss the fool',attack_bonus=-100,range_ft=120)
    combat,table,mid=fixture(tmp_path,[T+'dongfang_shuo_s_court_hermit_step'],bundle_transform=setup,
        positions=POSITIONS,battlefield_transform=corridor)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Miss the fool',target=OWNER).candidate_id,
        {'reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step':'first','choice:needle.rider_step':'cell:5,6'})
    a=reload(tmp_path,mid).state.actors[OWNER]
    assert a.position.x==5 and not a.reaction_available and a.resources['resource:core.martial_focus']==0
    assert any(p['context']['reactor_id']==OWNER for p in prompts)

@pytest.mark.parametrize('success',[False,True])
def test_whole_court_next_check_and_duration(tmp_path,success):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['saving_throws']['CHA']=100 if success else -100;seal(bs[2])
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[0],'Contest the foil',[{'type':'brutal_shove','no_damage':True,'no_manhandle':True,'mode':'prone_only'}])
        add_action(bs[2],'Actual check',[{'type':'skill_check','ability':'DEX','skill':'Acrobatics'}])
        sealed_native_attack(bs[2],'Miss badly',attack_bonus=-100,range_ft=120)
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Miss badly',target=OWNER).candidate_id,
        {'reaction:typed.'+T+'the_whole_court_laughs':'first'})
    e=reload(tmp_path,mid)
    c=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.flustered')
    assert c.data['disadvantage'] and c.data['auto65']==1
    assert not e.state.actors[OWNER].reaction_available
    assert e._effective_speed(e.state.actors[FOE])==(30 if success else 0)
    assert any(c.condition_id=='condition:typed.no_bonus_actions' for c in e.state.actors[FOE].conditions.values()) != success
    if success:
        settle(table,mid,candidate(combat,mid,'Actual check',target=FOE).candidate_id)
        turn(table,mid,OWNER)
    else:
        turn(table,mid,OWNER)
        settle(table,mid,candidate(combat,mid,'Contest the foil',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert [r for r in e.rolls if r.actor_id==FOE and r.reason.startswith('CHECK:')][-1].mode=='DISADVANTAGE'
    assert any(c.condition_id=='condition:typed.flustered' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values()) != success
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id=='condition:typed.flustered' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())

MASK_OPTIONS=['Become Flustered','Reduce Speed by 10 feet','Disadvantage on its next saving throw','Cannot take Bonus Actions']

@pytest.mark.parametrize('choice',MASK_OPTIONS)
def test_masks_enemy_start_choice_allied_benefits_and_once_round_step(tmp_path,choice):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['saving_throws']['WIS']=-100;seal(bs[2])
        add_action(bs[0],'Fluster the enemy',[{'type':'flustered','check_penalty':True}])
        add_action(bs[0],'Test the next saves',[
            {'type':'save','ability':'DEX','applies_to':'target','on_fail':[],'on_success':[]},
            {'type':'save','ability':'DEX','applies_to':'target','on_fail':[],'on_success':[]}])
        add_action(bs[2],'Use Flustered penalty',[{'type':'skill_check','ability':'DEX','skill':'Acrobatics'}])
    combat,table,mid=fixture(tmp_path,[T+'ten_thousand_masks_procession'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Ten-Thousand Masks Procession: Become Flustered').candidate_id)
    e=reload(tmp_path,mid)
    assert not [v for v in e.events if v.event_type=='SAVE_ROLLED']
    assert any(v.event_type=='GM_RIDER' and 'Help action as a Bonus Action' in (v.payload.get('rider') or '') for v in e.events)
    assert e._effective_speed(e.state.actors[ALLY])==40
    assert e._effective_speed(e.state.actors[OWNER])==30
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id']==ALLY
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],
        {'choice:needle.effect_choices':choice,'choice:needle.rider_step':'cell:4,7'})
    e=reload(tmp_path,mid);a=e.state.actors[FOE]
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED']
    assert len(saves)==1 and saves[0].actor_id==FOE
    assert not any(c.condition_id=='condition:typed.flustered' for c in e.state.actors[ALLY].conditions.values())
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.effect_choices' for p in prompts)
    assert any(c.condition_id=='condition:typed.flustered' for c in a.conditions.values())==(choice==MASK_OPTIONS[0])
    def holder_start(value): return value.startswith('START_OF_TURN_AT:'+FOE+':')
    if choice==MASK_OPTIONS[0]:
        flustered=next(c for c in a.conditions.values() if c.condition_id=='condition:typed.flustered')
        assert holder_start(flustered.expires_on)
    elif choice==MASK_OPTIONS[1]:
        assert any(holder_start(m.expires_on or '') or m.expires_on=='START_OF_SOURCE_NEXT_TURN'
                   for m in a.modifiers.values())
    elif choice==MASK_OPTIONS[2]:
        assert any(holder_start(c.expires_on or '') for c in a.conditions.values())
    elif choice==MASK_OPTIONS[3]:
        no_bonus=next(c for c in a.conditions.values() if c.condition_id=='condition:typed.no_bonus_actions')
        assert holder_start(no_bonus.expires_on or '')
    assert e._effective_speed(a)==(20 if choice==MASK_OPTIONS[1] else 30)
    assert any(c.condition_id=='condition:typed.no_bonus_actions' for c in a.conditions.values())==(choice==MASK_OPTIONS[3])
    if choice==MASK_OPTIONS[0]:
        assert e.state.actors[ALLY].position.y==7
        assert any(p['context']['reactor_id']==ALLY for p in prompts)
        moved=e.state.actors[ALLY].position
        settle(table,mid,candidate(combat,mid,'Use Flustered penalty',target=FOE).candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.actors[ALLY].position==moved
        flustered=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.flustered')
        assert flustered.data.get('disadvantage') is False
    tracked_condition=None
    tracked_modifier=None
    if choice==MASK_OPTIONS[0]:
        tracked_condition=next(c.instance_id for c in a.conditions.values() if c.condition_id=='condition:typed.flustered')
    elif choice==MASK_OPTIONS[1]:
        tracked_modifier=next(m.modifier_id for m in a.modifiers.values() if m.target_field=='speed_ft' and m.value<0)
    elif choice==MASK_OPTIONS[2]:
        tracked_condition=next(c.instance_id for c in a.conditions.values() if holder_start(c.expires_on or ''))
    elif choice==MASK_OPTIONS[3]:
        tracked_condition=next(c.instance_id for c in a.conditions.values() if c.condition_id=='condition:typed.no_bonus_actions')
    turn(table,mid,OWNER)
    e=reload(tmp_path,mid);a=e.state.actors[FOE]
    if tracked_condition is not None: assert tracked_condition in a.conditions
    if tracked_modifier is not None: assert tracked_modifier in a.modifiers
    if choice==MASK_OPTIONS[1]: assert e._effective_speed(a)==20
    if choice==MASK_OPTIONS[2]:
        settle(table,mid,candidate(combat,mid,'Test the next saves',target=FOE).candidate_id)
        e=reload(tmp_path,mid)
        modes=[r.mode for r in e.rolls if r.reason.startswith('SAVE:') and r.actor_id==FOE][-2:]
        assert modes==['DISADVANTAGE','NORMAL']
    # A second application in this round cannot make the same ally step again.
    settle(table,mid,candidate(combat,mid,'Fluster the enemy',target=FOE).candidate_id,
        {'choice:needle.rider_step':'cell:4,8' if choice==MASK_OPTIONS[0] else 'cell:4,7'})
    e=reload(tmp_path,mid)
    before=e.state.actors[ALLY].position
    prompts=settle(table,mid,candidate(combat,mid,'Fluster the enemy',target=FOE).candidate_id,
        {'choice:needle.rider_step':'cell:4,9'})
    assert reload(tmp_path,mid).state.actors[ALLY].position==before
    assert not any(p['context']['reaction_source_id']=='choice:needle.rider_step' for p in prompts)


def test_masks_ai_enemy_save_never_hinders_allies_and_keeps_benefits_scoped(tmp_path,monkeypatch):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['saving_throws']['WIS']=-100;seal(bs[2])
        bs[0]['action_catalog']=[a for a in bs[0]['action_catalog'] if a['display_name']=='Ten-Thousand Masks Procession: Become Flustered']
        bs[0]['actor_template']['action_ids']=[a['source_definition_id'] for a in bs[0]['action_catalog']];seal(bs[0])
    combat,table,mid=fixture(tmp_path,[T+'ten_thousand_masks_procession'],bundle_transform=setup,ask=False,
        modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    action=candidate(combat,mid,'Ten-Thousand Masks Procession: Become Flustered').source_definition_id
    preferred=combat.policies.fallback().model_copy(update={'action_priorities':{action:2000}})
    monkeypatch.setattr(combat.policies,'for_actor',lambda aid:(preferred,True))
    settle(table,mid,None,auto=True)
    e=reload(tmp_path,mid)
    assert any(z.active and (z.trigger_profile.get('profile') or {}).get('jester_masks') for z in e.state.zones.values())
    # Let the real AI finish its turn; its menu deliberately has no manual End Turn.
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']!=OWNER:break
        settle(table,mid,None,auto=True)
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.flustered' for c in e.state.actors[FOE].conditions.values())
    for aid in [OWNER,ALLY]:
        assert not any(c.condition_id=='condition:typed.flustered' for c in e.state.actors[aid].conditions.values())
    assert [v.actor_id for v in e.events if v.event_type=='SAVE_ROLLED']==[FOE]
    assert e._effective_speed(e.state.actors[ALLY])==40


@pytest.mark.parametrize('harmful',[False,True])
def test_court_hermit_actual_successful_save_requires_harm(tmp_path,harmful):
    def setup(bs):
        configure(bs);bs[0]['actor_template']['saving_throws']['DEX']=100;seal(bs[0])
        add_action(bs[2],'Test the fool',[{'type':'save','ability':'DEX',
            'on_fail':[{'type':'condition','condition':'prone'}] if harmful else [],'on_success':[]}])
    combat,table,mid=fixture(tmp_path,[T+'dongfang_shuo_s_court_hermit_step'],bundle_transform=setup,
        positions=POSITIONS,battlefield_transform=corridor)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Test the fool',target=OWNER).candidate_id,
        {'reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step':'first','choice:needle.rider_step':'cell:5,6'})
    e=reload(tmp_path,mid)
    assert [v for v in e.events if v.event_type=='SAVE_ROLLED'][-1].payload['success']
    assert e.state.actors[OWNER].position.x==(5 if harmful else 3)
    assert any(p['context']['reaction_source_id']=='reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step' for p in prompts)==harmful


def test_whole_court_natural_one_check_receipt(tmp_path):
    def setup(bs):
        configure(bs)
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[2],'Actual check',[{'type':'skill_check','ability':'DEX','skill':'Acrobatics'}])
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    for _ in range(80):
        settle(table,mid,candidate(combat,mid,'Actual check',target=FOE).candidate_id,
            {'reaction:typed.'+T+'the_whole_court_laughs':'first'})
        e=reload(tmp_path,mid)
        if not e.state.actors[OWNER].reaction_available:break
    else:pytest.fail('deterministic check stream never produced a natural 1')
    assert any(r.reason.startswith('CHECK:') and r.actor_id==FOE and r.natural_result==1 for r in e.rolls)
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'the_whole_court_laughs' for v in e.events)


def test_whole_court_jester_save_failure_margin(tmp_path):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['saving_throws']['WIS']=-100;seal(bs[2])
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[0],'Jester test',[{'type':'save','ability':'WIS','on_fail':[{'type':'condition','condition':'prone'}]}],
            typed={'source':T+'test_save'})
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    prompts=settle(table,mid,candidate(combat,mid,'Jester test',target=FOE).candidate_id,
        {'reaction:typed.'+T+'the_whole_court_laughs':'first'})
    asked=next(p for p in prompts if p['context']['reaction_source_id']=='reaction:typed.'+T+'the_whole_court_laughs')
    words=str(asked.get('trigger') or '')
    assert 'Jester test' in words and reload(tmp_path,mid).state.actors[FOE].display_name in words, (
        f"checkpoint={asked['context'].get('checkpoint')!r}; action={asked.get('action')!r}; "
        f"affected={asked.get('affected')!r}; trigger={words!r}")
    assert 'Whole Court' not in words
    e=reload(tmp_path,mid)
    assert not e.state.actors[OWNER].reaction_available
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'the_whole_court_laughs' for v in e.events)


def test_whole_court_uses_corrected_total_for_five_point_miss(tmp_path,monkeypatch):
    from combat import ext
    def setup(bs):
        configure(bs)
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        sealed_native_attack(bs[2],'Corrected miss',attack_bonus=-100,range_ft=120)
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup,
                            seed='JESTER-SETTLED-MARGIN')
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    original=ext.callbacks
    def callbacks(point):
        found=original(point)
        if point!='attack_miss_correction':return found
        def correction(engine,attacker,target,spec,roll,intent,total,ac):
            return {'bonus':max(1,ac-total-4),'source_id':'system:test.corrected_miss',
                    'label':'Test correction'}
        return (*found,correction)
    monkeypatch.setattr(ext,'callbacks',callbacks)
    prompts=settle(table,mid,candidate(combat,mid,'Corrected miss',target=OWNER).candidate_id)
    e=reload(tmp_path,mid)
    roll=next(r for r in e.rolls if r.reason.startswith('ATTACK:') and r.actor_id==FOE)
    assert roll.natural_result!=1  # the natural-1 exception is separately tested below
    event=next(v for v in e.events if v.event_type=='PASSIVE_TRIGGERED' and
               (v.payload or {}).get('attack_correction') and (v.payload or {}).get('roll_id')==roll.roll_id)
    assert event.payload['target_ac']-event.payload['modified_total']==4
    assert not any(p['context']['reaction_source_id']=='reaction:typed.'+T+'the_whole_court_laughs' for p in prompts)
    assert e.state.actors[OWNER].reaction_available



def test_court_hermit_offered_after_real_free_punchline(tmp_path):
    from tests.test_r9i_karma_persistence import act
    def setup(bs):
        configure(bs)
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[0],'Recover Focus',[{'type':'gain_resource','resource_id':'resource:core.martial_focus','flat':1}],target='SELF')
        sealed_native_attack(bs[2],'Miss the fool',attack_bonus=-100,range_ft=120)
    combat,table,mid=fixture(tmp_path,[T+'a_fine_display',T+'court_of_words_without_offense',T+'dongfang_shuo_s_court_hermit_step'],bundle_transform=setup)
    settle(table,mid,candidate(combat,mid,'Court of Words Without Offense').candidate_id)
    settle(table,mid,candidate(combat,mid,'Recover Focus',target=OWNER).candidate_id)
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    cid=candidate(combat,mid,'Miss the fool',target=OWNER).candidate_id
    answers=[];step_offers=0
    for _ in range(12):
        result=act(table,mid,cid,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED';break
        p=result['reaction'];rid=p['context']['reaction_source_id']
        use=rid=='choice:needle.strike_the_fool'
        if rid=='reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step':
            step_offers+=1;use=step_offers>1
        answer={**p['context'],'selection':'USE' if use else 'DECLINE'}
        if use and p.get('choice'):answer['option_ids']=[p['choice']['options'][0]['id']]
        answers.append(answer)
    else:pytest.fail('too many reaction prompts')
    e=reload(tmp_path,mid)
    assert step_offers==2  # miss first, then the completed free Punchline
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'fine_display' for v in e.events)
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'dongfang_shuo_s_court_hermit_step' for v in e.events)
    assert not e.state.actors[OWNER].reaction_available



def test_whole_court_ai_does_not_react_to_unperceived_foil_check(tmp_path):
    def setup(bs):
        configure(bs)
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[2],'Disappear',[{'type':'condition','condition':'invisible','applies_to':'self'}],target='SELF')
        add_action(bs[2],'Actual check',[{'type':'skill_check','ability':'DEX','skill':'Acrobatics'}])
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup,ask=False)
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,candidate(combat,mid,'Disappear',target=FOE).candidate_id)
    from combat.target_knowledge import located
    e=reload(tmp_path,mid)
    assert not located(e,e.state.actors[OWNER],e.state.actors[FOE])
    for _ in range(80):
        settle(table,mid,candidate(combat,mid,'Actual check',target=FOE).candidate_id)
        e=reload(tmp_path,mid)
        if any(r.reason.startswith('CHECK:') and r.actor_id==FOE and r.natural_result==1 for r in e.rolls):break
    else:pytest.fail('no natural 1 in deterministic check stream')
    assert e.state.actors[OWNER].reaction_available
    assert not any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'the_whole_court_laughs' for v in e.events)



def test_whole_court_natural_one_death_save_is_a_d20_test(tmp_path):
    def setup(bs):
        configure(bs);bs[2]['actor_template']['maximum_hp']=10;seal(bs[2])
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[0],'Knock down',[{'type':'damage','flat':10,'damage_types':['force']}])
    combat,table,mid=fixture(tmp_path,[T+'the_whole_court_laughs'],bundle_transform=setup,seed='A2JESTER-DEATH-10')
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    settle(table,mid,candidate(combat,mid,'Knock down',target=FOE).candidate_id)
    assert reload(tmp_path,mid).state.actors[FOE].life_state=='DYING'
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    settle(table,mid,table.state(mid)['menu']['end_turn'],
        {'reaction:typed.'+T+'the_whole_court_laughs':'first'})
    e=reload(tmp_path,mid)
    assert any(r.reason=='SAVE:death' and r.natural_result==1 for r in e.rolls)
    assert e.state.actors[OWNER].resources['resource:uses.reaction:typed.'+T+'the_whole_court_laughs']==0
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==T+'the_whole_court_laughs' for v in e.events)



def test_court_hermit_automatic_successful_harmful_save(tmp_path):
    def setup(bs):
        configure(bs)
        add_action(bs[2],'Protected save',[{'type':'save','ability':'DEX',
            'on_fail':[{'type':'condition','condition':'prone'}],'on_success':[]}],
            typed={'chosen_save_protection':True})
    combat,table,mid=fixture(tmp_path,[T+'dongfang_shuo_s_court_hermit_step'],bundle_transform=setup,
        positions=POSITIONS,battlefield_transform=corridor)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Protected save',target=OWNER).candidate_id,
        {'choice:needle.gentle_modulation':OWNER,
         'reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step':'first','choice:needle.rider_step':'cell:5,6'})
    e=reload(tmp_path,mid)
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)
    assert any('automatically succeeds' in (v.payload.get('log') or '') for v in e.events)
    assert e.state.actors[OWNER].position.x==5
    assert not e.state.actors[OWNER].reaction_available


def test_concealment_miss_offers_court_step_but_not_whole_court(tmp_path,monkeypatch):
    from combat import targeting
    monkeypatch.setattr(targeting,'rules',lambda:dict(targeting.LEGACY_POLICY))
    def setup(bs):
        configure(bs)
        add_action(bs[0],'Mark Foil',[{'type':'jester_foil','proposition':'Strike the Fool'}])
        add_action(bs[2],'Blind self',[{'type':'condition','condition':'blinded','applies_to':'self'}],target='SELF')
        sealed_native_attack(bs[2],'Concealed attack',attack_bonus=100,range_ft=120)
    combat,table,mid=fixture(tmp_path,[T+'dongfang_shuo_s_court_hermit_step',T+'the_whole_court_laughs'],bundle_transform=setup,
        positions=POSITIONS,battlefield_transform=corridor,seed='A2JESTER-CONCEAL-1')
    settle(table,mid,candidate(combat,mid,'Mark Foil',target=FOE).candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Blind self',target=FOE).candidate_id)
    prompts=settle(table,mid,candidate(combat,mid,'Concealed attack',target=OWNER).candidate_id,
        {'reaction:typed.'+T+'dongfang_shuo_s_court_hermit_step':'first','choice:needle.rider_step':'cell:5,6'})
    e=reload(tmp_path,mid)
    assert any(v.payload.get('missed') and v.payload.get('miss_chance_percent')==50 for v in e.events)
    assert not any(v.event_type=='ATTACK_ROLLED' for v in e.events)
    assert e.state.actors[OWNER].position.x==5
    assert not any(p['context']['reaction_source_id']=='reaction:typed.'+T+'the_whole_court_laughs' for p in prompts)
