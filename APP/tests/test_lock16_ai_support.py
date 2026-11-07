"""Support decisions and zone movement estimates across Table commits/reloads."""
import pytest
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate4_context import build_decision_context
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD, ROOT
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from combat.gate5_service import CombatService


def context(combat, mid):
    engine=combat._load_session(mid).engine
    policy,_=combat.policies.for_actor(engine.state.current_actor_id)
    return build_decision_context(engine,policy,for_ai=True)


def checked(combat,tmp_path,mid):
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state==combat._load_session(mid).engine.state
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


@pytest.mark.parametrize('kind',['healing','temp_hp'])
def test_ai_prefers_useful_recovery_and_table_commit_replays(monkeypatch,tmp_path,kind):
    def actions(info):
        return [ActionDefinition(source_definition_id='test:recovery:'+info['actor_id'],display_name='Restore an ally',
            owner_id=info['actor_id'],economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',
            target_kind='ALLY_OR_SELF',range_ft=60,parameters={'typed':{'numbers':info['numbers'],
                'effects':[{'type':kind,'flat':30,'applies_to':'target'}]}})]
    install(monkeypatch,'compile_actions',actions)
    def injury(engine):
        engine._commit_damage(engine.state.actors[LEFT],25,'FORCE','test:injury',RIGHT,None,reaction_depth=0)
    on_hold(monkeypatch,injury)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    checked(combat,tmp_path,mid)
    engine=combat._load_session(mid).engine
    before=(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))
    ctx=context(combat,mid)
    heals=[c for c in ctx.legal_candidates if c.source_definition_id=='test:recovery:'+LEFT]
    mine=next(c for c in heals if c.target_ids==(LEFT,))
    full=next(c for c in heals if c.target_ids==(ALLY,))
    score=lambda c: combat.controller._score_candidate(ctx,c,())
    mine_score,full_score=score(mine),score(full)
    assert mine_score.total>full_score.total
    assert next(c.value for c in full_score.components if c.component=='immediate_effect')==0
    assert next(c.value for c in full_score.components if c.component=='target')==0
    assert before==(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))
    combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    fresh=checked(combat,tmp_path,mid)
    me=fresh.state.actors[LEFT]
    assert me.current_hp==me.maximum_hp if kind=='healing' else me.temporary_hp==30


@pytest.mark.parametrize('who,exposed',[('hostile',True),('ally',False)])
def test_zone_hazard_metadata_uses_recipient_and_committed_zone(monkeypatch,tmp_path,who,exposed):
    from tests.test_ai_restraint import _lay
    def zone(engine):
        row=_lay(engine,[(2,4)],owner=RIGHT,on=('enter','start'),who=who)
        engine._append_event('ZONE_CREATED',row.source_definition_id,actor_id=RIGHT,
                             payload={'zone':row.model_dump(mode='json')})
    on_hold(monkeypatch,zone)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    engine=checked(combat,tmp_path,mid)
    before=(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))
    moves=[c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=2,y=4)]
    assert len(moves)==1 and moves[0].metadata['hazard_exposure'] is exposed
    if exposed: assert moves[0].metadata['zone_hazard_exposure']
    policy,_=combat.policies.for_actor(LEFT)
    ctx=build_decision_context(engine,policy,for_ai=True)
    move=next(c for c in ctx.legal_candidates if c.candidate_id==moves[0].candidate_id)
    score=combat.controller._score_candidate(ctx,move,())
    risk=next(c.value for c in score.components if c.component=='avoidable_risk')
    assert risk<0 if exposed else risk<=0
    assert before==(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))


def test_recovery_query_does_not_consume_one_use_penalty():
    from tests.h1_support import duel,ME
    from combat.support_estimates import recovery
    engine=duel([]); actor=engine.state.actors[ME]; actor.current_hp-=20
    engine._add_modifier(actor,'test:penalty','healing_reduction','SET','next:half','SELF',expires_on='UNTIL_REMOVED')
    action=ActionDefinition(source_definition_id='test:heal',display_name='Heal',owner_id=ME,
        economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',
        parameters={'typed':{'effects':[{'type':'healing','flat':10}]}})
    candidate=next(c for c in engine.legal_candidates() if c.kind=='END_TURN')
    before=(engine.state.model_dump(mode='json'),len(engine.events))
    assert recovery(engine,actor,candidate,action)==[{'target_id':ME,'healing_hp':5,'temporary_hp':0}]
    assert before==(engine.state.model_dump(mode='json'),len(engine.events))


@pytest.mark.parametrize('missing,existing,expected',[(0,0,0),(7,0,7),(20,8,7),(20,20,0)])
def test_temporary_hp_estimate_caps_combined_grants(missing,existing,expected):
    from tests.h1_support import duel,ME
    from combat.support_estimates import recovery
    engine=duel([]); actor=engine.state.actors[ME]
    actor.current_hp=actor.maximum_hp-missing; actor.temporary_hp=existing
    action=ActionDefinition(source_definition_id='test:temp',display_name='Protect',owner_id=ME,
        economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',
        parameters={'typed':{'effects':[{'type':'temp_hp','flat':10},{'type':'temp_hp','flat':15}]}})
    candidate=next(c for c in engine.legal_candidates() if c.kind=='END_TURN')
    assert recovery(engine,actor,candidate,action)==[{'target_id':ME,'healing_hp':0,'temporary_hp':expected}]


@pytest.mark.parametrize('gate',['min_cl','max_cl','menu','modifier_once','modifier_turn','temp_hp_denied'])
def test_ai_skips_ineligible_recovery_and_commits_effective_alternative(monkeypatch,tmp_path,gate):
    def actions(info):
        bad={'type':'temp_hp' if gate=='temp_hp_denied' else 'healing','flat':40,'applies_to':'self'}
        extras=[]
        if gate=='min_cl': bad['min_cl']=16
        if gate=='max_cl': bad['max_cl']=14
        if gate=='modifier_once': bad['modifier_once']='test:once'
        if gate=='modifier_turn':
            bad.update(modifier_once='test:once',modifier_once_period='turn')
        if gate=='menu':
            bad.update(menu='test:menu',option='Unchosen')
            extras=[{'type':'menu','id':'test:menu','count':1,'options':['Chosen','Unchosen'],
                     'default':['Chosen'],'cast_only':True}]
        return [ActionDefinition(source_definition_id=f'test:{key}:'+info['actor_id'],
            display_name='Recover now' if key=='good' else 'Conditional recovery',owner_id=info['actor_id'],
            economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',target_kind='SELF',
            parameters={'typed':{'numbers':info['numbers'],'effects':effects}})
            for key,effects in [('bad',[*extras,bad]),('good',[{'type':'healing','flat':10,'applies_to':'self'}])]]
    install(monkeypatch,'compile_actions',actions)
    def setup(engine):
        me=engine.state.actors[LEFT]
        engine._commit_damage(me,30,'FORCE','test:injury',RIGHT,None,reaction_depth=0)
        if gate=='temp_hp_denied':
            engine._apply_condition(me,'condition:typed.test_no_protection','test:denial',RIGHT,
                expires_on='UNTIL_REMOVED',data={'rule':{'temp_hp_denied':True}})
        if gate in ('modifier_once','modifier_turn'):
            from combat.typed_executor import Context,run_effects
            action=engine.action_catalog['test:bad:'+LEFT]
            ctx=Context(engine,me,action,engine._active_intent,action.parameters['typed'],[],None)
            once={'type':'temp_hp','flat':1,'modifier_once':'test:once'}
            if gate=='modifier_turn': once['modifier_once_period']='turn'
            run_effects(ctx,[once])
    on_hold(monkeypatch,setup)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    engine=checked(combat,tmp_path,mid)
    before=(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))
    ctx=context(combat,mid)
    bad=next(c for c in ctx.legal_candidates if c.source_definition_id=='test:bad:'+LEFT)
    assert sum(r['healing_hp']+r['temporary_hp'] for r in bad.metadata['useful_recovery'])==0
    assert before==(engine.state.model_dump(mode='json'),len(engine.events),len(engine.rolls))
    combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid,0,[])['status']=='COMMITTED'
    fresh=checked(combat,tmp_path,mid)
    assert fresh.state.actors[LEFT].current_hp==fresh.state.actors[LEFT].maximum_hp-20
    assert any(e.event_type=='HEALING_APPLIED' and e.source_definition_id=='test:good:'+LEFT for e in fresh.events)


def test_real_coagulate_combined_terms_match_committed_grant(monkeypatch,tmp_path):
    # compile_bundle is not required: the existing compile_action hook changes
    # typed numeric input before canonical bundle hashing.
    def action_numbers(action,info):
        if 'BLOOD_BASE_COAGULATE' in action.source_definition_id:
            typed=dict(action.parameters['typed'])
            typed['numbers']={**typed['numbers'],'pb':4,'key_mod':4,'cl':1}
            return action.model_copy(update={'parameters':{**action.parameters,'typed':typed}})
    install(monkeypatch,'compile_action',action_numbers)
    def setup(engine):
        me=engine.state.actors[LEFT]
        engine._commit_damage(me,20,'FORCE','test:injury',RIGHT,None,reaction_depth=0)
        engine._grant_temp_hp(me,5,'test:old-protection',LEFT)
        # Printed target: a willing creature bearing the caster's Blood Thread.
        engine._apply_condition(me, 'condition:typed.mark.blood_thread.' + LEFT,
                                'test:thread', LEFT, expires_on='UNTIL_REMOVED')
    on_hold(monkeypatch,setup)
    combat,table,mid=table_fight(tmp_path,['BLOOD_BASE_COAGULATE'],cl=1,ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    ctx=context(combat,mid)
    choice=next(c for c in ctx.legal_candidates if 'BLOOD_BASE_COAGULATE' in c.source_definition_id
                and 'Temporary HP' in c.display_name
                and c.target_ids==(LEFT,))
    assert choice.metadata['useful_recovery']==[{'target_id':LEFT,'healing_hp':0,'temporary_hp':3}]
    assert table.act(mid,choice.candidate_id,choice.decision_id,choice.state_version,0,[])['status']=='COMMITTED'
    fresh=checked(combat,tmp_path,mid)
    assert fresh.state.actors[LEFT].temporary_hp==8


def test_table_ai_avoids_zone_crossed_between_safe_endpoints(monkeypatch,tmp_path):
    from combat.granted_movement import resolve_path
    from tests.test_ai_restraint import _lay
    def setup(engine):
        foe=engine.state.actors[RIGHT]
        resolve_path(engine,foe,tuple(Position(x=x,y=4) for x in range(4,10)),feet=25,
                source='test:retreat',provokes=False,intent=engine._active_intent)
        zone=_lay(engine,[(5,y) for y in range(8)],owner=RIGHT,on=('enter','start'))
        engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=RIGHT,
                             payload={'zone':zone.model_dump(mode='json')})
    on_hold(monkeypatch,setup)
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    engine=checked(combat,tmp_path,mid)
    from combat.zones import hazard_test
    danger=hazard_test(engine,engine.state.actors[LEFT])
    crossing=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=7,y=4))
    assert not danger(crossing.destination) and any(danger(p) for p in crossing.canonical_path[1:])
    assert crossing.metadata['zone_hazard_exposure']
    combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    state=combat._load_session(mid).engine.state
    hp=state.actors[LEFT].current_hp
    sequence=len(combat._load_session(mid).engine.events)
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    fresh=checked(combat,tmp_path,mid)
    moves=[e for e in fresh.events[sequence:] if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==LEFT]
    assert moves and all(p['x']<5 for p in moves[-1].payload['path'])
    assert fresh.state.actors[LEFT].current_hp==hp


@pytest.mark.parametrize('gate',['max_cl','menu'])
def test_combined_grant_excludes_terms_execution_cannot_use(monkeypatch,tmp_path,gate):
    def actions(info):
        term={'type':'temp_hp','formula':'key_ability_modifier','applies_to':'self'}
        extras=[]
        if gate=='max_cl': term['max_cl']=14
        else:
            term.update(menu='test:parts',option='Unchosen')
            extras=[{'type':'menu','id':'test:parts','count':1,'options':['Chosen','Unchosen'],
                     'default':['Chosen'],'cast_only':True}]
        return [ActionDefinition(source_definition_id='test:parts:'+info['actor_id'],display_name='Limited protection',
            owner_id=info['actor_id'],economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',target_kind='SELF',
            parameters={'typed':{'numbers':{**info['numbers'],'pb':4,'key_mod':4},
                'effects':[*extras,{'type':'temp_hp','formula':'pb','applies_to':'self'},term]}})]
    install(monkeypatch,'compile_actions',actions)
    on_hold(monkeypatch,lambda engine: engine._commit_damage(engine.state.actors[LEFT],20,'FORCE',
        'test:injury',RIGHT,None,reaction_depth=0))
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    assert act(table,mid,HOLD)['status']=='COMMITTED'
    candidate=next(c for c in context(combat,mid).legal_candidates if c.source_definition_id=='test:parts:'+LEFT)
    assert candidate.metadata['useful_recovery']==[{'target_id':LEFT,'healing_hp':0,'temporary_hp':4}]
    assert table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,0,[])['status']=='COMMITTED'
    assert checked(combat,tmp_path,mid).state.actors[LEFT].temporary_hp==4


def test_movement_preview_refreshes_after_a_table_reaction(tmp_path):
    combat,table,mid=table_fight(tmp_path,[],ally_talents=[])
    combat.set_controller_mode(mid,actor_id=RIGHT,controller_mode='LOCAL_AUTO')
    engine=combat._load_session(mid).engine
    choice=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=1,y=4))
    assert RIGHT in choice.metadata['reaction_exposure']
    assert table.act(mid,choice.candidate_id,choice.decision_id,choice.state_version,0,[])['status']=='COMMITTED'
    fresh=checked(combat,tmp_path,mid)
    assert not fresh.state.actors[RIGHT].reaction_available
    moves=[c for c in fresh.legal_candidates() if c.kind=='MOVE']
    assert moves and all(RIGHT not in c.metadata['reaction_exposure'] for c in moves)
