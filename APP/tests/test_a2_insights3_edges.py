"""Boundary coverage for the seven Insight defense/healing implementations."""
import pytest
from tests.test_a2_insights3 import FALL,FROZEN,FURNACE,HEART,STOMACH,DEMON,FLESH,fight,damage,save,typed_prepare,commits
from tests.auto_worker1_support import LEFT,RIGHT,ALLY,act,reload,resolve,settle,turn,action_sender


@pytest.mark.parametrize('overlap',[False,True])
def test_stomach_poisoned_advantage_requires_another_resistance(tmp_path,overlap):
    resistance={'type':'resistance','damage_types':['poison'],'applies_to':'self','duration':{'kind':'until_removed'}}
    c,t,m=fight(tmp_path,[STOMACH],prepare=[resistance] if overlap else [],cause=[save([{'type':'condition','condition':'poisoned','applies_to':'target'}])])
    if overlap:resolve(lambda a:act(t,m,'Prepare',a))
    turn(t,m,RIGHT);resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m)
    assert next(r for r in e.rolls if r.reason.startswith('SAVE:')).mode==('ADVANTAGE' if overlap else 'NORMAL')


@pytest.mark.parametrize('kind',['fire','cold'])
def test_furnace_heart_concentration_uses_triggering_packet_type(tmp_path,kind):
    def seal(bundle):
        for a in bundle['action_catalog']:
            if a['display_name']=='Prepare':
                a['concentration']=True;a['parameters']['typed']['duration']={'kind':'one_minute','concentration':True}
    c,t,m=fight(tmp_path,[HEART],prepare=[{'type':'temp_hp','flat':1,'applies_to':'self'}],prepare_target='SELF',cause=[damage(20,kind)],bundle_edit=seal)
    resolve(lambda a:act(t,m,'Prepare',a));turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m)
    assert next(r for r in e.rolls if r.reason.startswith('SAVE:system:combat.concentration')).mode=='ADVANTAGE'


def test_furnace_does_not_reward_the_same_first_self_fire_packet(tmp_path):
    c,t,m=fight(tmp_path,[FURNACE],prepare=[damage(12,'fire','self')],prepare_target='SELF')
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].temporary_hp==0
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].temporary_hp==8


def test_furnace_overlap_allowance_resets_only_when_the_round_changes(tmp_path):
    res={'type':'resistance','damage_types':['fire'],'applies_to':'self','duration':{'kind':'until_removed'}}
    c,t,m=fight(tmp_path,[FURNACE],prepare=[res],cause=[damage(20,'fire')])
    resolve(lambda a:act(t,m,'Prepare',a));turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m);round_number=e.state.round_number
    first=e.state.actors[LEFT].current_hp
    # Repeated current-round packets do not consume the allowance again.
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp==first-10
    turn(t,m,LEFT);turn(t,m,RIGHT)
    e=commits(c,m);assert e.state.round_number>round_number
    before=e.state.actors[LEFT].current_hp
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp==before-6


@pytest.mark.parametrize('feature,category',[(DEMON,'emotional_manipulation'),(HEART,'heat')])
def test_declining_failed_save_rewrite_spends_nothing(tmp_path,feature,category):
    c,t,m=fight(tmp_path,[feature],left_score=1,cause=[save([damage(1,'force')],save_categories=[category])])
    turn(t,m,RIGHT)
    def decline(prompt):return [] if prompt['context']['reaction_source_id']=='reaction:typed.'+feature else [o['id'] for o in prompt.get('choice',{}).get('options',[])][:1]
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline)
    e=commits(c,m)
    assert any(feature in str(p) for p in prompts)
    assert e.state.actors[LEFT].resources['resource:core.qi']==100
    assert e.state.actors[LEFT].reaction_available
    assert not any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==feature for v in e.events)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==feature for v in commits(c,m).events)


def test_furnace_heart_scene_limit_survives_owner_turn(tmp_path):
    c,t,m=fight(tmp_path,[HEART],left_score=1,cause=[save([damage(1,'fire')])])
    turn(t,m,RIGHT);resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert sum(v.event_type=='D20_REWRITTEN' and v.source_definition_id==HEART for v in commits(c,m).events)==1
    turn(t,m,LEFT);turn(t,m,RIGHT)
    _,prompts=resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert not any(HEART in str(p) for p in prompts)
    assert sum(v.event_type=='D20_REWRITTEN' and v.source_definition_id==HEART for v in commits(c,m).events)==1


def test_flesh_separate_healing_rolls_share_one_selected_activation(tmp_path):
    heal={'type':'healing','flat':10,'applies_to':'self'}
    c,t,m=fight(tmp_path,[FLESH],prepare=[damage(80,'force','self'),heal,heal],prepare_target='SELF',bundle_edit=typed_prepare('flesh'))
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].current_hp==948
    resolve(lambda a:act(t,m,'Prepare',a))
    assert commits(c,m).state.actors[LEFT].current_hp==888


@pytest.mark.parametrize('automatic',[False,True])
def test_flesh_shared_healing_offer_keeps_automatic_recipients_on_allied_side(tmp_path,automatic):
    heal={'type':'healing','flat':10,'applies_to':'ally','evidence':'Allies within 30 feet regain Hit Points.'}
    c,t,m=fight(tmp_path,[FLESH],prepare=[heal],prepare_target='SELF',cause=[damage(30,'force')],bundle_edit=typed_prepare('flesh'),ally=(),extra_witness=True,witness_team='team:factory',positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':3,'y':7}})
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=ALLY))
    resolve(lambda a:act(t,m,'Cause',a,target_id='actor:factory.auto111-witness'))
    turn(t,m,LEFT)
    resolve(action_sender(c,t,m,'Prepare',ai=automatic))
    e=commits(c,m)
    offers=[v for v in e.events if v.event_type=='HEALING_APPLIED']
    assert len(offers)==2
    assert all(e.state.actors[v.target_ids[0]].team_id==e.state.actors[LEFT].team_id for v in offers)
    assert all(v.payload['offered']==14 for v in offers)
    assert not any(RIGHT in v.target_ids for v in offers)


def test_flesh_zero_healing_cannot_create_a_bonus_and_does_not_spend_the_use(tmp_path):
    c,t,m=fight(tmp_path,[FLESH],prepare=[damage(30,'force','self'),{'type':'healing','flat':0,'applies_to':'self'},{'type':'healing','flat':10,'applies_to':'self'}],prepare_target='SELF',bundle_edit=typed_prepare('flesh'))
    resolve(lambda a:act(t,m,'Prepare',a))
    e=commits(c,m)
    assert e.state.actors[LEFT].current_hp==984
    assert [v.payload['offered'] for v in e.events if v.event_type=='HEALING_APPLIED']==[0,14]


def test_flesh_full_hp_offer_does_not_spend_the_next_real_healing_bonus(tmp_path):
    heal={'type':'healing','flat':10,'applies_to':'self'}
    def seal(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] in {'Prepare','Wound and Mend'}:
                a['parameters']['typed'].update(sphere='tianxia.sphere.flesh',source='test:printed.flesh')
    c,t,m=fight(tmp_path,[FLESH],prepare=[heal],prepare_target='SELF',bundle_edit=seal,extra_actions=[('Wound and Mend',{'effects':[damage(30,'force','self'),heal]})])
    resolve(lambda a:act(t,m,'Prepare',a))
    assert 'insights3_flesh_turn' not in commits(c,m).state.actors[LEFT].turn_flags
    resolve(lambda a:act(t,m,'Wound and Mend',a))
    assert commits(c,m).state.actors[LEFT].current_hp==984


@pytest.mark.parametrize('marked',[False,True])
def test_frozen_denies_reactions_only_if_conditional_zero_speed_was_applied(tmp_path,marked):
    gate={'type':'if_marked','mark':'Chilled','effects':[{'type':'speed','becomes':0,'applies_to':'target','duration':{'kind':'until_start_of_next_turn'}}]}
    prep=[*([{'type':'mark','mark':'Chilled','applies_to':'target','duration':{'kind':'until_removed'}}] if marked else []),save([damage(1,'cold'),gate])]
    c,t,m=fight(tmp_path,[FROZEN],prepare=prep,bundle_edit=typed_prepare('ice'))
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m);subject=e.state.actors[RIGHT]
    assert e._effective_speed(subject)==(0 if marked else 20)
    assert any(c.condition_id=='condition:typed.reaction_denied' for c in subject.conditions.values())==marked


def test_frozen_two_owners_under_one_shared_intent_stay_separate_applications(tmp_path,monkeypatch):
    """Two owners whose Cold saves both resolve inside one table intent are two applications.

    combat/zones.py dispatches each arriving area under the active movement intent, so a
    creature that walks into two overlapping Cold areas fails both saves inside a single
    intent. Both owners genuinely qualify, but the same-source nonstacking contract means
    the creature takes one owner's penalty -- not the sum of both owners' -- and each
    owner's row still expires on its own schedule.

    The deliveries are built the way combat/zones.py builds them (a Context per owner that
    reuses the active intent), so the application identity is the one production assigns.
    """
    from combat import ext
    from combat.typed_executor import Context,run_effects
    ext.effects()
    def two_owner_shared_intent(ctx,row):
        """One enclosing intent, two independently owned Cold saves against the same creature."""
        victim=ctx.engine.state.actors[RIGHT]
        for owner_id,label in ((LEFT,'Cold Field'),(RIGHT,'Cause')):
            owner=ctx.engine.state.actors[owner_id]
            action=next(a for a in ctx.engine.action_catalog.values()
                        if a.owner_id==owner_id and a.display_name==label)
            inner=Context(ctx.engine,owner,action,ctx.intent,action.parameters['typed'],[victim],victim)
            run_effects(inner,inner.typed['effects'])
    monkeypatch.setitem(ext._EFFECTS,'test_insights3_two_owner_shared_intent',two_owner_shared_intent)
    def ice(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] in {'Prepare','Cold Field','Cause'}:
                a['parameters']['typed'].update(sphere='tianxia.sphere.ice',source='test:printed.ice')
    c,t,m=fight(tmp_path,[FROZEN],right_talents=[FROZEN],
        prepare=[{'type':'test_insights3_two_owner_shared_intent'}],
        cause=[save([damage(1,'cold')])],
        extra_actions=[('Cold Field',{'target_kind':'HOSTILE_ENTITY','effects':[save([damage(1,'cold')])]})],
        bundle_edit=ice)
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m);victim=e.state.actors[RIGHT]
    rows=[m for m in victim.modifiers.values() if m.source_definition_id==FROZEN]
    # Both owners really applied their own rider under the one shared intent.
    assert len(rows)==2
    assert {m.source_actor_id for m in rows}=={LEFT,RIGHT}
    assert len({m.application_id for m in rows})==2
    # Same-source nonstacking takes one owner's penalty, not the sum of both.
    assert e._effective_speed(victim)==20
    # Each owner's row expires on its own schedule, and the survivor still counts once.
    turn(t,m,RIGHT)
    e=commits(c,m);victim=e.state.actors[RIGHT]
    remaining=[m for m in victim.modifiers.values() if m.source_definition_id==FROZEN]
    assert len(remaining)==1 and remaining[0].source_actor_id==LEFT
    assert e._effective_speed(victim)==20
    turn(t,m,LEFT)
    e=commits(c,m)
    assert not [m for m in e.state.actors[RIGHT].modifiers.values() if m.source_definition_id==FROZEN]
    assert e._effective_speed(e.state.actors[RIGHT])==30


def test_frozen_off_turn_speed_rider_keeps_its_real_source_owner_and_expiry(tmp_path,monkeypatch):
    from combat import ext
    from combat.typed_executor import Context,run_effects
    ext.effects()
    def pulse(ctx,row):
        actor=ctx.engine.state.actors[LEFT]
        action=next(a for a in ctx.engine.action_catalog.values() if a.owner_id==LEFT and a.display_name=='Prepare')
        inner=Context(ctx.engine,actor,action,ctx.intent,action.parameters['typed'],[ctx.actor],ctx.actor)
        run_effects(inner,inner.typed['effects'])
    monkeypatch.setitem(ext._EFFECTS,'test_insights3_offturn_pulse',pulse)
    c,t,m=fight(tmp_path,[FROZEN],prepare=[save([damage(1,'cold')])],cause=[{'type':'test_insights3_offturn_pulse'}],cause_target='SELF',bundle_edit=typed_prepare('ice'))
    turn(t,m,RIGHT);resolve(lambda a:act(t,m,'Cause',a))
    e=commits(c,m)
    modifier=next(v for v in e.state.actors[RIGHT].modifiers.values() if v.source_definition_id==FROZEN)
    assert modifier.source_actor_id==LEFT
    assert e._effective_speed(e.state.actors[RIGHT])==20
    turn(t,m,LEFT)
    assert not any(v.source_definition_id==FROZEN for v in commits(c,m).state.actors[RIGHT].modifiers.values())


def test_frozen_same_slow_from_two_owners_keeps_independent_expiries_after_reload(tmp_path,monkeypatch):
    from combat import ext
    ext.effects()
    def apply_two_source_slows(ctx,row):
        victim=ctx.engine.state.actors[RIGHT]
        for owner in (LEFT,RIGHT):
            ctx.engine._add_modifier(victim,FROZEN,'speed_ft','ADD',-10,'ALL_MOVEMENT',
                expires_on='START_OF_SOURCE_NEXT_TURN',source_actor_id=owner)
    monkeypatch.setitem(ext._EFFECTS,'test_insights3_two_owner_slow',apply_two_source_slows)
    c,t,m=fight(tmp_path,prepare=[{'type':'test_insights3_two_owner_slow'}])
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m);victim=e.state.actors[RIGHT]
    rows=[m for m in victim.modifiers.values() if m.source_definition_id==FROZEN]
    assert len(rows)==2
    assert e._effective_speed(victim)==20
    # The right owner's row expires at its next start.
    turn(t,m,RIGHT)
    e=commits(c,m);victim=e.state.actors[RIGHT]
    remaining=[m for m in victim.modifiers.values() if m.source_definition_id==FROZEN]
    assert len(remaining)==1 and remaining[0].source_actor_id==LEFT
    assert e._effective_speed(victim)==20
    # The left owner's row expires at its independently timed next start.
    turn(t,m,LEFT)
    e=commits(c,m);victim=e.state.actors[RIGHT]
    assert not any(m.source_definition_id==FROZEN for m in victim.modifiers.values())
    assert e._effective_speed(victim)==30


def test_frozen_additional_slow_stacks_with_cold_feature_slow_after_reload(tmp_path):
    slow={'type':'speed','amount':-10,'applies_to':'target',
          'duration':{'kind':'until_start_of_next_turn'}}
    c,t,m=fight(tmp_path,[FROZEN],prepare=[slow,save([damage(1,'cold')])],
                bundle_edit=typed_prepare('ice'))
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m)
    victim=e.state.actors[RIGHT]
    assert len([x for x in victim.modifiers.values() if x.target_field=='speed_ft'])==2
    assert e._effective_speed(victim)==10


def test_independent_table_slow_sources_add_after_service_reload(tmp_path):
    """Different printed actions remain separate Speed penalties on a creature without Insights."""
    slow={'type':'speed','amount':-10,'applies_to':'target',
          'duration':{'kind':'until_start_of_next_turn'}}
    c,t,m=fight(tmp_path,prepare=[slow],prepare_target='HOSTILE_ENTITY',
                extra_actions=[('Second Slow',{'target_kind':'HOSTILE_ENTITY','effects':[slow]})])
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    resolve(lambda a:act(t,m,'Second Slow',a,target_id=RIGHT))
    e=commits(c,m)
    victim=e.state.actors[RIGHT]
    assert e._effective_speed(victim)==10
    assert len([x for x in victim.modifiers.values() if x.target_field=='speed_ft'])==2


def test_speed_rows_from_one_typed_activation_combine(tmp_path):
    slows=[{'type':'speed','amount':-10,'applies_to':'target',
            'duration':{'kind':'until_start_of_next_turn'}},
           {'type':'speed','amount':-15,'applies_to':'target',
            'duration':{'kind':'until_start_of_next_turn'}}]
    c,t,m=fight(tmp_path,prepare=slows,prepare_target='HOSTILE_ENTITY')
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m)
    assert e._effective_speed(e.state.actors[RIGHT])==5


def test_set_speed_zero_uses_nonstacking_rows_through_service_reload(tmp_path,monkeypatch):
    """A set-Speed effect must see the same two-owner aggregate as movement."""
    from combat import ext
    ext.effects()
    def apply_two_owned_slows(ctx,row):
        victim=ctx.engine.state.actors[RIGHT]
        for owner,application in ((LEFT,'owner-left'),(RIGHT,'owner-right')):
            ctx.engine._add_modifier(victim,'test:owned_slow','speed_ft','ADD',-10,'ALL_MOVEMENT',
                expires_on='START_OF_SOURCE_NEXT_TURN',source_actor_id=owner,application_id=application)
    monkeypatch.setitem(ext._EFFECTS,'test_insights3_owned_slows',apply_two_owned_slows)
    c,t,m=fight(tmp_path,prepare=[{'type':'test_insights3_owned_slows'}],
        extra_actions=[('Set Speed Zero',{'target_kind':'HOSTILE_ENTITY','effects':[
            {'type':'speed','becomes':0,'applies_to':'target','duration':{'kind':'until_start_of_next_turn'}}]})])
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m)
    assert e._effective_speed(e.state.actors[RIGHT])==20
    resolve(lambda a:act(t,m,'Set Speed Zero',a,target_id=RIGHT))
    e=commits(c,m)
    assert len([x for x in e.state.actors[RIGHT].modifiers.values()
                if x.source_definition_id=='test:owned_slow'])==2
    assert e._effective_speed(e.state.actors[RIGHT])==0


def test_strongest_same_source_speed_application_survives_cold_reload(tmp_path,monkeypatch):
    """Unequal application penalties choose the greatest reduction, not the smallest."""
    from combat import ext
    ext.effects()
    def apply_unequal_slows(ctx,row):
        victim=ctx.engine.state.actors[RIGHT]
        for owner,application,amount in ((LEFT,'lesser',-10),(RIGHT,'stronger',-20)):
            ctx.engine._add_modifier(victim,'test:shared_slow','speed_ft','ADD',amount,'ALL_MOVEMENT',
                expires_on='START_OF_SOURCE_NEXT_TURN',source_actor_id=owner,application_id=application)
    monkeypatch.setitem(ext._EFFECTS,'test_insights3_unequal_slows',apply_unequal_slows)
    c,t,m=fight(tmp_path,prepare=[{'type':'test_insights3_unequal_slows'}])
    resolve(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    e=commits(c,m);victim=e.state.actors[RIGHT]
    assert len([x for x in victim.modifiers.values() if x.source_definition_id=='test:shared_slow'])==2
    assert e._effective_speed(victim)==10


def test_one_point_next_instance_resistance_consumes_through_service_reload(tmp_path):
    next_resistance={'type':'resistance_next','damage_types':['fire'],'applies_to':'self',
                     'duration':{'kind':'until_removed'}}
    c,t,m=fight(tmp_path,prepare=[next_resistance],prepare_target='SELF',
                cause=[damage(1,'fire')],bundle_edit=typed_prepare('fire'))
    resolve(lambda a:act(t,m,'Prepare',a))
    assert any(x.target_field=='damage_resistance_next' for x in commits(c,m).state.actors[LEFT].modifiers.values())
    turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=commits(c,m)
    assert not any(x.target_field=='damage_resistance_next' for x in e.state.actors[LEFT].modifiers.values())
    assert e.state.actors[LEFT].current_hp==1000
    turn(t,m,LEFT);turn(t,m,RIGHT)
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert commits(c,m).state.actors[LEFT].current_hp==999
