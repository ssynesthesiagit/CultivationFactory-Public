"""Yang second-pass effects through service/table execution, cold reload and replay."""
import pytest
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,turn,reload
from tests.test_auto35_yang import _seal,_add_action
TRAIL='TAL_YANG_OVERBRIGHT_TRAIL'
WARMTH='TAL_YANG_SEAL_BREAKING_WARMTH'
TRAIL_CONDITION='condition:typed.yang_overbright_trail'
from combat.typed_executor import bears_mark


@pytest.mark.parametrize('kind',['FIRE','RADIANT','FORCE'])
@pytest.mark.parametrize('hit',[True,False])
def test_thread_selects_printed_type_before_roll_and_mark_on_hit(tmp_path,kind,hit):
    def prepare(bundles):
        bundles[2]['actor_template']['armor_class']=0 if hit else 1000
        _seal(bundles[2])
    combat,table,mid=fixture(tmp_path,[TRAIL],bundle_transform=prepare)
    cid=candidate(combat,mid,'Rising Thread',target=FOE).candidate_id
    from tests.test_r9i_karma_persistence import act
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    preview=act(table,mid,cid)
    assert preview['status']=='REACTION_REQUIRED'
    assert preview['reaction']['context']['reaction_source_id']=='choice:needle.rising_thread_type'
    assert reload(tmp_path,mid).state.model_dump(mode='json')==before
    settle(table,mid,cid,{'choice:needle.rising_thread_type':kind})
    engine=reload(tmp_path,mid)
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER]
    assert bool(damage)==hit
    if hit:assert damage[-1].payload['damage_type']==kind
    assert bears_mark(engine.state.actors[FOE],OWNER,'Overkindled Mark')==hit


@pytest.mark.parametrize('ordinary',[True,False])
@pytest.mark.parametrize('owns',[True,False])
def test_trail_follows_actual_overcommit_and_only_ignores_ordinary_concealment(tmp_path,ordinary,owns):
    def prepare(bundles):
        _add_action(bundles[1],'Cloud',[{'type':'zone','applies_to':'self'}],target='SELF',
            zone_spec={'name':'Test fog','shape':'sphere','size_ft':10,'centered_on_self':False,
                  'duration':{'kind':'minutes','amount':1},'obscured':'heavy',
                  'visual':{'magical':not ordinary}})
        # A real aimed zone action; no direct mutation of a running fight.
        row=bundles[1]['action_catalog'][-1]
        row['target_kind']='CELL';row['parameters']['any_cell']=True
        bundles[2]['actor_template']['armor_class']=0
        for i,b in enumerate(bundles):
            b['actor_template']['initiative_bonus']={0:100,1:-200,2:-100}[i]
            _seal(b)
    combat,table,mid=fixture(tmp_path,[TRAIL] if owns else ['TAL_YANG_FURNACE_BACKLASH'],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Rising Thread',target=FOE).candidate_id,
           {'choice:needle.rising_thread_type':'FORCE'})
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y)==(8,6) and c.destination.z==0
              and c.metadata.get('movement_mode','walk')=='walk')
    settle(table,mid,move.candidate_id,{'reaction:typed.TAL_YANG_OVERKINDLED_RESPONSES#overcommit_step':'first'})
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Cloud',at=(8,6)).candidate_id)
    engine=reload(tmp_path,mid)
    foe=engine.state.actors[FOE];owner=engine.state.actors[OWNER];ally=engine.state.actors[ALLY]
    assert any(c.condition_id==TRAIL_CONDITION for c in foe.conditions.values())==owns
    assert not bears_mark(foe,OWNER,'Overkindled Mark')
    from combat import zones,senses
    assert zones.hidden_from(engine,owner,foe)==(not (ordinary and owns))
    assert zones.hidden_from(engine,ally,foe), 'only the originating Yang owner ignores the fog'
    assert senses.perceives(engine,owner,foe)==(ordinary and owns)
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id==TRAIL_CONDITION for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('success',[True,False])
@pytest.mark.parametrize('accept',[True,False])
@pytest.mark.parametrize('provenance',['ordinary','unknown','artifact'])
def test_warmth_repeats_one_existing_save_at_owners_cost(tmp_path,monkeypatch,success,accept,provenance):
    def prepare(bundles):
        # Sealed preparation: establish a save-imposed movement restriction with
        # original provenance. Both branches deliberately impose the fixture restriction.
        hold={'type':'condition','condition':'restrained','applies_to':'self','expires_on':'UNTIL_REMOVED'}
        _add_action(bundles[0],'Prepare restriction',[{'type':'save','ability':'con','dc':16,'applies_to':'self',
            'on_fail':[hold],'on_success':[hold]}],target='SELF')
        prepared=bundles[0]['action_catalog'][-1]['parameters']['typed']
        if provenance != 'unknown': prepared['source']='TAL_YANG_APPLYING_A_RISING_MARK'
        if provenance in ('artifact','curse','formation','narrative_seal'):
            prepared['source_category']=provenance
        _add_action(bundles[1],'Control save',[{'type':'save','ability':'wis','dc':16,
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}],
            'on_success':[]}],target='ANY_CREATURE')
        bundles[0]['actor_template']['saving_throws']={'CON':1000 if success else -1000,'WIS':1000}
        for b in bundles:_seal(b)
    combat,table,mid=fixture(tmp_path,[WARMTH],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare restriction',target=OWNER).candidate_id)
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    assert bears_mark(reload(tmp_path,mid).state.actors[OWNER],OWNER,'Kindled Mark')
    turn(table,mid,ALLY)
    from combat.ext import needle
    ask=needle.ask; routed=[]
    def capture(engine,intent,checkpoint,chooser,choice_id,options,**kwargs):
        if choice_id in ('choice:needle.seal_warmth','choice:needle.seal_warmth_repeat'):
            routed.append((choice_id,chooser.entity_id,kwargs.get('target_id'),kwargs.get('prompt','')))
        return ask(engine,intent,checkpoint,chooser,choice_id,options,**kwargs)
    monkeypatch.setattr(needle,'ask',capture)
    prompts=settle(table,mid,candidate(combat,mid,'Control save',target=OWNER).candidate_id,
        {'reaction:typed.TAL_YANG_KINDLED_RESPONSES#complete_resolve':'first',
         'choice:needle.seal_warmth':'use' if accept else None,
         'choice:needle.seal_warmth_repeat':'first'})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.seal_warmth' for p in prompts)==(provenance=='ordinary')
    warmth_prompt=next((p for p in prompts if p['context']['reaction_source_id']=='choice:needle.seal_warmth'),None)
    if warmth_prompt:
        assert routed
        assert all(row[2]==OWNER for row in routed)
        assert all('Complete Resolve' in row[3] for row in routed)
    accept=accept and provenance=='ordinary'
    assert engine.state.actors[OWNER].resources['resource:core.qi']==(98 if accept else 100)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id==WARMTH]
    assert len(saves)==int(accept)
    assert any(c.condition_id=='condition:typed.restrained'
               for c in engine.state.actors[OWNER].conditions.values())==(not (accept and success))
    assert engine.state.actors[OWNER].temporary_hp==(6 if accept and not success else 0)
    assert not bears_mark(engine.state.actors[OWNER],OWNER,'Kindled Mark')


def test_warmth_recognizes_save_imposed_flat_speed_delta(tmp_path):
    """A save-imposed -10 Speed condition is eligible without a named condition/rule key."""
    def prepare(bundles):
        slow={'type':'condition','condition':'frightened','applies_to':'self','expires_on':'UNTIL_REMOVED',
              'condition_data':{'speed_delta':-10}}
        _add_action(bundles[0],'Prepare leg slow',[{'type':'save','ability':'con','dc':16,'applies_to':'self',
            'on_fail':[slow],'on_success':[slow]}],target='SELF')
        bundles[0]['action_catalog'][-1]['parameters']['typed']['source']='TAL_YANG_APPLYING_A_RISING_MARK'
        bundles[0]['actor_template']['saving_throws']={'CON':1000,'WIS':1000}
        _add_action(bundles[1],'Control save',[{'type':'save','ability':'wis','dc':16,
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}],
            'on_success':[]}],target='ANY_CREATURE')
        for b in bundles:_seal(b)
    combat,table,mid=fixture(tmp_path,[WARMTH],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare leg slow',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    slow=next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.frightened')
    assert slow.data['speed_delta']==-10 and slow.data['origin_save']=={'ability':'CON','dc':16}
    from combat.ext.yang_recovery import warmth_conditions
    assert warmth_conditions(engine,engine.state.actors[OWNER],engine.state.actors[OWNER])
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    assert bears_mark(reload(tmp_path,mid).state.actors[OWNER],OWNER,'Kindled Mark')
    turn(table,mid,ALLY)
    prompts=settle(table,mid,candidate(combat,mid,'Control save',target=OWNER).candidate_id,
        {'reaction:typed.TAL_YANG_KINDLED_RESPONSES#complete_resolve':'first',
         'choice:needle.seal_warmth':'use','choice:needle.seal_warmth_repeat':'first'})
    after=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.seal_warmth' for p in prompts), (
        [p['context'].get('reaction_source_id') for p in prompts],
        ';'.join(f'{e.event_type}:{e.source_definition_id}' for e in after.events[-30:]))
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==98
    assert any(e.event_type=='SAVE_ROLLED' and e.source_definition_id==WARMTH for e in engine.events)
    assert not any(c.condition_id=='condition:typed.frightened' for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('overlap',[False,True])
def test_warmth_releases_only_reaction_suppression_it_ends_through_cold_reload(tmp_path,overlap):
    """A successful recovery restores an unspent Reaction only after all denials end."""
    def prepare(bundles):
        effects=[{'type':'condition','condition':'paralyzed','applies_to':'target','expires_on':'UNTIL_REMOVED'}]
        if overlap:
            effects.append({'type':'condition','condition':'stunned','applies_to':'target','expires_on':'UNTIL_REMOVED'})
        _add_action(bundles[0],'Prepare reaction denial',[{'type':'save','ability':'con','dc':16,
            'applies_to':'target','on_fail':effects,'on_success':effects}],target='ANY_CREATURE')
        bundles[0]['action_catalog'][-1]['parameters']['typed']['source']='TAL_YANG_APPLYING_A_RISING_MARK'
        # Warmth repeats the bearer's original CON save, not the mark owner's.
        bundles[1]['actor_template']['saving_throws']={'CON':1000,'WIS':1000}
        _add_action(bundles[2],'Control save',[{'type':'save','ability':'wis','dc':16,
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}],
            'on_success':[]}],target='ANY_CREATURE')
        for bundle in bundles:_seal(bundle)
    combat,table,mid=fixture(tmp_path,[WARMTH],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Prepare reaction denial',target=ALLY).candidate_id)
    before=reload(tmp_path,mid)
    denied=before.state.actors[ALLY]
    assert not denied.reaction_available
    assert any(c.condition_id=='condition:typed.paralyzed' for c in denied.conditions.values())
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=ALLY).candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Control save',target=ALLY).candidate_id,
        {'reaction:typed.TAL_YANG_KINDLED_RESPONSES#complete_resolve':'first',
         'choice:needle.seal_warmth':'use','choice:needle.seal_warmth_repeat':'first'})
    after=reload(tmp_path,mid).state.actors[ALLY]
    recovery_saves=[e for e in reload(tmp_path,mid).events
                    if e.event_type=='SAVE_ROLLED' and e.source_definition_id==WARMTH]
    assert len(recovery_saves)==1, 'Warmth must actually repeat the bearer\'s save'
    assert recovery_saves[0].payload.get('success') is True, recovery_saves[0].payload
    assert not any(c.condition_id=='condition:typed.paralyzed' for c in after.conditions.values())
    if overlap:
        assert any(c.condition_id=='condition:typed.stunned' for c in after.conditions.values())
        assert not after.reaction_available
    else:
        assert after.reaction_available


def test_warmth_keeps_a_reaction_spent_before_the_denial_unavailable_through_reload(tmp_path):
    """A real spent Reaction stays spent when Warmth lifts the save-imposed denial that came later."""
    def prepare(bundles):
        # Enemy -> Yang owner -> bearer: the owner can mark an already-denied
        # bearer without advancing through the bearer's Reaction refresh.
        bundles[0]['actor_template']['initiative_bonus']=50
        bundles[2]['actor_template']['initiative_bonus']=100
        bundles[1]['actor_template']['initiative_bonus']=-100
        effects=[{'type':'condition','condition':'paralyzed','applies_to':'target','expires_on':'UNTIL_REMOVED'}]
        _add_action(bundles[2],'Prepare reaction denial',[{'type':'save','ability':'con','dc':16,
            'applies_to':'target','on_fail':effects,'on_success':effects}],target='ANY_CREATURE')
        bundles[2]['action_catalog'][-1]['parameters']['typed']['source']='TAL_YANG_APPLYING_A_RISING_MARK'
        bundles[1]['actor_template']['saving_throws']={'CON':1000,'WIS':1000}
        _add_action(bundles[0],'Control save',[{'type':'save','ability':'wis','dc':16,
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}],
            'on_success':[]}],target='ANY_CREATURE')
        for bundle in bundles:_seal(bundle)
    combat,table,mid=fixture(tmp_path,[WARMTH],bundle_transform=prepare,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':5,'y':6}})
    turn(table,mid,FOE)
    bearer_turns=reload(tmp_path,mid).state.actors[ALLY].turns_started
    move=next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(6,6,0)
              and c.metadata.get('movement_mode','walk')=='walk')
    prompts=settle(table,mid,move.candidate_id,{'reaction:typed.opportunity_attack':'use'})
    assert any(p['context']['reaction_source_id']=='reaction:typed.opportunity_attack'
               and p['context']['reactor_id']==ALLY for p in prompts)
    assert not reload(tmp_path,mid).state.actors[ALLY].reaction_available
    settle(table,mid,candidate(combat,mid,'Prepare reaction denial',target=ALLY).candidate_id)
    denied=reload(tmp_path,mid).state.actors[ALLY]
    assert any(c.condition_id=='condition:typed.paralyzed' for c in denied.conditions.values())
    assert not denied.reaction_available
    assert denied.turns_started==bearer_turns
    # Mark only after the denial exists: otherwise the automatic Complete
    # Resolve response spends it before that save imposes the restriction.
    turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=ALLY).candidate_id)
    assert bears_mark(reload(tmp_path,mid).state.actors[ALLY],OWNER,'Kindled Mark')
    prompts=settle(table,mid,candidate(combat,mid,'Control save',target=ALLY).candidate_id,
        {'choice:needle.seal_warmth':'use','choice:needle.seal_warmth_repeat':'first'})
    assert any(p['context']['reaction_source_id']=='choice:needle.seal_warmth' for p in prompts)
    engine=reload(tmp_path,mid);after=engine.state.actors[ALLY]
    recovery_saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id==WARMTH]
    assert len(recovery_saves)==1 and recovery_saves[0].actor_id==ALLY
    assert recovery_saves[0].payload.get('success') is True
    assert not any(c.condition_id=='condition:typed.paralyzed' for c in after.conditions.values())
    assert not bears_mark(after,OWNER,'Kindled Mark')
    assert engine.state.actors[OWNER].resources['resource:core.qi']==98
    assert after.turns_started==bearer_turns
    assert not after.reaction_available
    turn(table,mid,ALLY)
    refreshed=reload(tmp_path,mid).state.actors[ALLY]
    assert refreshed.turns_started==bearer_turns+1
    assert refreshed.reaction_available


def test_warmth_routes_owner_offer_and_bearer_question_to_distinct_creatures(tmp_path,monkeypatch):
    def prepare(bundles):
        hold={'type':'condition','condition':'restrained','applies_to':'target','expires_on':'UNTIL_REMOVED'}
        _add_action(bundles[0],'Prepare ally restriction',[{'type':'save','ability':'con','dc':16,
            'on_fail':[hold],'on_success':[hold]}],target='ANY_CREATURE')
        bundles[0]['action_catalog'][-1]['parameters']['typed']['source']='TAL_YANG_APPLYING_A_RISING_MARK'
        bundles[1]['actor_template']['saving_throws']={'CON':1000,'WIS':1000}
        _add_action(bundles[2],'Control save',[{'type':'save','ability':'wis','dc':16,
            'on_fail':[{'type':'condition','condition':'frightened','applies_to':'target'}],
            'on_success':[]}],target='ANY_CREATURE')
        for b in bundles:_seal(b)
    combat,table,mid=fixture(tmp_path,[WARMTH],bundle_transform=prepare)
    bearer_name=combat._load_session(mid).engine.state.actors[ALLY].display_name
    settle(table,mid,candidate(combat,mid,'Prepare ally restriction',target=ALLY).candidate_id)
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=ALLY).candidate_id)
    assert bears_mark(reload(tmp_path,mid).state.actors[ALLY],OWNER,'Kindled Mark')
    turn(table,mid,FOE)
    from combat.ext import needle
    ask=needle.ask; routed=[]
    def capture(engine,intent,checkpoint,chooser,choice_id,options,**kwargs):
        if choice_id in ('choice:needle.seal_warmth','choice:needle.seal_warmth_repeat'):
            routed.append((choice_id,chooser.entity_id,kwargs.get('target_id'),kwargs.get('prompt','')))
        return ask(engine,intent,checkpoint,chooser,choice_id,options,**kwargs)
    monkeypatch.setattr(needle,'ask',capture)
    prompts=settle(table,mid,candidate(combat,mid,'Control save',target=ALLY).candidate_id,
        {'reaction:typed.TAL_YANG_KINDLED_RESPONSES#complete_resolve':'first',
         'choice:needle.seal_warmth':'use','choice:needle.seal_warmth_repeat':'first'})
    assert any(p['context']['reaction_source_id']=='choice:needle.seal_warmth_repeat' for p in prompts)
    assert routed and all(row[2]==ALLY for row in routed)
    assert all('Complete Resolve' in row[3] and bearer_name in row[3] for row in routed)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==98
    assert not any(c.condition_id=='condition:typed.restrained' for c in engine.state.actors[ALLY].conditions.values())


def test_twofold_automatic_multi_recipient_choice_only_marks_allies(tmp_path):
    """Allies and enemies are in range; an AI must restrict beneficial recipients by side."""
    from tests.test_r9i_karma_persistence import act
    combat,table,mid=fixture(tmp_path,['TAL_YANG_TWOFOLD_RISING'])
    engine=combat._load_session(mid).engine
    choice=next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
                and 'Kindle Two Creatures' in engine.action_catalog[c.source_definition_id].display_name)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    from combat.gate4_adapters import ManualControllerAdapter
    controller=combat.controller
    combat.controller=ManualControllerAdapter(lambda context:(choice.candidate_id,()),
        reaction_chooser=lambda context:controller.choose_reaction(context).decision)
    assert not settle(table,mid,choice.candidate_id,auto=True)
    engine=reload(tmp_path,mid)
    assert bears_mark(engine.state.actors[OWNER],OWNER,'Kindled Mark')
    assert bears_mark(engine.state.actors[ALLY],OWNER,'Kindled Mark')
    assert not bears_mark(engine.state.actors[FOE],OWNER,'Kindled Mark')


@pytest.mark.parametrize('cl,boost',[(5,10),(11,20)])
@pytest.mark.parametrize('accept',[True,False])
def test_complete_step_and_surplus_actual_movement(tmp_path,cl,boost,accept):
    STEP_CONDITION='condition:typed.yang_complete_step'
    SURPLUS_CONDITION='condition:typed.yang_surplus_step'
    combat,table,mid=fixture(tmp_path,['TAL_YANG_SURPLUS_STEP'],cl=cl,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':11,'y':6}})
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    before=reload(tmp_path,mid)
    movement_before=before.state.actors[OWNER].movement_remaining_ft
    engine=combat._load_session(mid).engine
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(3,4,0)
              and c.metadata.get('movement_mode','walk')=='walk')
    prompts=settle(table,mid,move.candidate_id,{'choice:needle.complete_step':'walk' if accept else None})
    assert any(p['context']['reaction_source_id']=='choice:needle.complete_step' for p in prompts)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert engine._effective_speed(actor)==30+(boost if accept else 0)
    assert any(c.condition_id==SURPLUS_CONDITION for c in actor.conditions.values())==accept
    assert actor.movement_remaining_ft==movement_before-10+(boost if accept else 0)
    assert actor.temporary_hp==0,'ten feet is below the twenty-foot threshold'
    assert bears_mark(actor,OWNER,'Kindled Mark')!=accept
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(3,2,0)
              and c.metadata.get('movement_mode','walk')=='walk')
    settle(table,mid,move.candidate_id,{'choice:needle.complete_step':None})
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.temporary_hp==(4 if accept else 0)
    if accept:
        assert len([e for e in engine.events if e.event_type=='TEMP_HP_GRANTED'
                    and e.source_definition_id=='TAL_YANG_SURPLUS_STEP'])==1
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert not any(c.condition_id in (STEP_CONDITION,SURPLUS_CONDITION) for c in actor.conditions.values())
    assert engine._effective_speed(actor)==30


def test_complete_step_not_offered_after_prepared_response_stops_movement(tmp_path,monkeypatch):
    """An INTENT_ACCEPTED prepared response receipt suppresses start-of-move benefits."""
    combat,table,mid=fixture(tmp_path,['TAL_YANG_SURPLUS_STEP'])
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    from combat import ext
    from tests.worker2_support import FOE
    option={'option_id':'stop_first_step','source_id':'test:prepared_stop_first_step',
            'label':'Stop the first step','trigger':'INTENT_ACCEPTED'}
    monkeypatch.setitem(ext._HOOKS,'prepare_options',[
        lambda engine,actor:[option] if actor.entity_id==FOE else []])
    monkeypatch.setitem(ext._HOOKS,'prepared_trigger',[
        lambda engine,actor,row,event: event.event_type=='INTENT_ACCEPTED' and event.actor_id==OWNER
            and event.payload.get('kind')=='MOVE'])
    def stop_first_step(engine,actor,row,event,intent):
        engine.state.actors[OWNER].turn_flags['movement_interrupted_sequence']=event.sequence
        return True
    monkeypatch.setitem(ext._HOOKS,'prepared_action',[stop_first_step])
    turn(table,mid,FOE)
    ready=next(c for c in combat._load_session(mid).engine.legal_candidates()
               if c.source_definition_id=='system:combat.ready:stop_first_step')
    settle(table,mid,ready.candidate_id)
    turn(table,mid,OWNER)
    engine=combat._load_session(mid).engine
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y)==(3,4) and c.destination.z==0)
    prompts=settle(table,mid,move.candidate_id,{'test:prepared_stop_first_step':'first',
                                                'choice:needle.complete_step':'walk'})
    assert not any(p['context']['reaction_source_id']=='choice:needle.complete_step' for p in prompts)
    assert any(p['context']['reaction_source_id']=='test:prepared_stop_first_step' for p in prompts)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert bears_mark(actor,OWNER,'Kindled Mark')
    assert engine.state.actors[OWNER].resources['resource:core.qi']==100
    receipt=next(e for e in reversed(engine.events) if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER)
    assert receipt.payload['interrupted'] and receipt.payload['cost_ft']==0
    assert not any(c.condition_id=='condition:typed.yang_complete_step' for c in actor.conditions.values())


def test_twofold_thread_has_the_same_pre_roll_damage_choice(tmp_path):
    def prepare(bundles):
        bundles[2]['actor_template']['armor_class']=0
        _seal(bundles[2])
    combat,table,mid=fixture(tmp_path,['TAL_YANG_TWOFOLD_RISING'],bundle_transform=prepare)
    engine=combat._load_session(mid).engine
    cid=next(c for c in engine.legal_candidates() if c.target_ids==(FOE,) and c.source_definition_id in engine.action_catalog
             and 'Rising Thread and Self Mark' in engine.action_catalog[c.source_definition_id].display_name).candidate_id
    prompts=settle(table,mid,cid,{'choice:needle.rising_thread_type':'RADIANT','choice:needle.twofold_self':'use'})
    assert any(p['context']['reaction_source_id']=='choice:needle.rising_thread_type' for p in prompts)
    engine=reload(tmp_path,mid)
    assert any(e.event_type=='DAMAGE_COMMITTED' and e.payload['damage_type']=='RADIANT' for e in engine.events)
    assert bears_mark(engine.state.actors[OWNER],OWNER,'Kindled Mark')
    assert bears_mark(engine.state.actors[FOE],OWNER,'Overkindled Mark')


@pytest.mark.parametrize('mode',['fly','fly_half','stand'])
def test_complete_step_other_represented_movement_choices(tmp_path,mode):
    from combat import flight,posture,motion
    def prepare(bundles):
        if mode.startswith('fly'):
            bundles[0]['actor_template']['fly_speed_ft']=40
            if mode=='fly_half':
                _add_action(bundles[0],'Prepare Fly restriction',[{'type':'gravity_half_flight',
                    'duration':'one_minute'}],target='ANY_CREATURE')
        else:
            _add_action(bundles[0],'Prepare Prone',[{'type':'condition','condition':'prone',
                'applies_to':'self','expires_on':'UNTIL_REMOVED'}],target='SELF')
        _seal(bundles[0])
    combat,table,mid=fixture(tmp_path,['TAL_YANG_SURPLUS_STEP'],cl=5,bundle_transform=prepare,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':11,'y':6}})
    if mode=='stand':settle(table,mid,candidate(combat,mid,'Prepare Prone',target=OWNER).candidate_id)
    if mode=='fly_half':
        settle(table,mid,candidate(combat,mid,'Prepare Fly restriction',target=OWNER).candidate_id)
        assert flight.profile(reload(tmp_path,mid),reload(tmp_path,mid).state.actors[OWNER]).speed_ft==20
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid);before=engine.state.actors[OWNER].movement_remaining_ft
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(3,5,0)
              and c.metadata.get('movement_mode','walk')=='walk')
    settle(table,mid,move.candidate_id,{'choice:needle.complete_step':'fly' if mode.startswith('fly') else mode})
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert not bears_mark(actor,OWNER,'Kindled Mark')
    assert actor.movement_remaining_ft==before-5
    assert engine._effective_speed(actor)==30
    assert motion.ignores_difficult(engine,actor)
    assert not motion.ignores_area_difficult(engine,actor)
    if mode.startswith('fly'):assert flight.profile(engine,actor).speed_ft==(25 if mode=='fly_half' else 50)
    else:assert not posture.prone_conditions(actor)
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert not motion.ignores_difficult(engine,actor)
    if mode.startswith('fly'):assert flight.profile(engine,actor).speed_ft==(20 if mode=='fly_half' else 40)


@pytest.mark.parametrize('mode',['walk','fly'])
def test_two_yang_owners_complete_step_does_not_add_to_itself(tmp_path,mode):
    from combat import flight
    from combat.ext.yang_recovery import STEP_CONDITION,ROUND
    def prepare(bundles):
        bundles[0]['actor_template']['fly_speed_ft']=40
        _seal(bundles[0])
    combat,table,mid=fixture(tmp_path,['TAL_YANG_SURPLUS_STEP'],cl=5,
        ally_talents=['TAL_YANG_SURPLUS_STEP'],bundle_transform=prepare,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':11,'y':6}})
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    turn(table,mid,ALLY)
    settle(table,mid,candidate(combat,mid,'Kindle the Rising',target=OWNER).candidate_id)
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert all(bears_mark(engine.state.actors[OWNER],a,'Kindled Mark') for a in (OWNER,ALLY))
    move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y,c.destination.z)==(3,4,0)
              and c.metadata.get('movement_mode','walk')=='walk')
    prompts=settle(table,mid,move.candidate_id,{'choice:needle.complete_step':mode})
    assert {p['context']['reactor_id'] for p in prompts
            if p['context']['reaction_source_id']=='choice:needle.complete_step'}=={OWNER,ALLY}
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert engine._effective_speed(actor)==(40 if mode=='walk' else 30)
    assert flight.profile(engine,actor).speed_ft==(50 if mode=='fly' else 40)
    assert actor.movement_remaining_ft==(30 if mode=='walk' else 20)
    assert len([c for c in actor.conditions.values() if c.condition_id==STEP_CONDITION])==1
    assert all(not bears_mark(actor,a,'Kindled Mark') for a in (OWNER,ALLY))
    assert all(engine.state.actors[a].turn_flags[ROUND]==engine.state.round_number for a in (OWNER,ALLY))
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert engine._effective_speed(actor)==30 and flight.profile(engine,actor).speed_ft==40


@pytest.mark.parametrize('category',['curse','formation','narrative_seal'])
def test_warmth_rejects_its_own_protected_categories(tmp_path,monkeypatch,category):
    test_warmth_repeats_one_existing_save_at_owners_cost(
        tmp_path,monkeypatch,True,True,category)
