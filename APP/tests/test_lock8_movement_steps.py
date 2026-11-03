"""Per-step pauses, native granted steps and two real interruption consumers."""
import pytest
from combat import ext
from combat.gate2_runtime_models import Position, ActionIntent
from combat.movement_steps import context
from tests import lock8_support as S
from tests.test_lock_choices import install

PRISON='tianxia.talent.gravity.event_horizon_prison'
STEAL='TAL_SCOUNDREL_STEAL_MOMENTUM'


def candidate(e,x,y=6):
    return next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination==Position(x=x,y=y))


def use(e,c):
    return e.execute_intent(ActionIntent(intent_id='steps-'+str(e.state.event_sequence),decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,
        target_ids=c.target_ids,destination=c.destination,
        movement_path=c.canonical_path if c.metadata.get('explicit_movement_path') else None,
        movement_mode=c.metadata.get('movement_mode') if c.metadata.get('explicit_movement_path') else None))


@pytest.mark.parametrize('point,position,cost',[('movement_attempt',3,0),('movement_step',4,5)])
def test_checkpoint_timing_and_interrupted_receipt(monkeypatch,point,position,cost):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(10,6))
    install(monkeypatch,point,lambda *args:{'stop':True,'source_id':'test:stop','label':'Movement stopped here.'})
    use(e,candidate(e,6))
    ev=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert e.state.actors[S.ME].position==Position(x=position,y=6)
    assert ev.payload['interrupted'] and ev.payload['cost_ft']==cost and len(ev.payload['interruptions'])==1
    assert getattr(e,'_movement_step_context',None) is None


def test_invalid_reply_after_payment_rolls_back_whole_move(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(10,6));c=candidate(e,6)
    before=e.state.model_dump(mode='json')
    def bad(engine,mover,*args):
        engine._spend_resource(mover,'resource:core.qi',1,'test:bad')
        return {'stop':0}
    install(monkeypatch,'movement_step',bad)
    with pytest.raises(ValueError):use(e,c)
    assert e.state.model_dump(mode='json')==before
    assert getattr(e,'_movement_step_context',None) is None


def test_completed_step_finalizers_run_after_a_stop_with_distance_context(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(10,6))
    seen=[]
    install(monkeypatch,'movement_step',lambda *args:{'stop':True,'source_id':'test:stop','label':'Stop here.'})
    def settle(engine,mover,previous,nxt,intent):
        seen.append((previous,nxt,dict(context(engine,mover))))
    install(monkeypatch,'movement_step_settled',settle)
    use(e,candidate(e,6))
    assert len(seen)==1 and seen[0][2]['travelled_ft']==5
    assert seen[0][1]==e.state.actors[S.ME].position
    assert getattr(e,'_movement_step_context',None) is None


def test_invalid_completed_step_finalizer_rolls_back(monkeypatch):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(10,6));c=candidate(e,6)
    before=e.state.model_dump(mode='json')
    install(monkeypatch,'movement_step_settled',lambda *args:{'stop':False})
    with pytest.raises(ValueError):use(e,c)
    assert e.state.model_dump(mode='json')==before


@pytest.mark.parametrize('dc,stopped',[(50,True),(-20,False)])
def test_real_prison_stops_at_boundary_before_crossing(monkeypatch,dc,stopped):
    e=S.fight(S.bundle(PRISON,dc=dc),foe_at=(8,6))
    e.grid.blocked.clear();e.grid.opaque.clear();e._wall_base=(frozenset(),frozenset(),frozenset(),{})
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    S.use(e,'Event Horizon Prison',at=(5,6))
    S.turn(e,S.FOE)
    # Pin the path whose second step leaves the prison. The new default route
    # avoids the map's hazardous square and can cross the boundary earlier.
    from combat.movement_routes import explicit_candidate
    use(e, explicit_candidate(e, S.FOE, tuple(Position(x=x, y=6) for x in (8, 9, 10))))
    actor=e.state.actors[S.FOE]
    assert actor.position==Position(x=9 if stopped else 10,y=6)
    ev=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED')
    assert ev.payload['cost_ft']==(5 if stopped else 10)
    assert ev.payload['interrupted'] is stopped


@pytest.mark.parametrize('dc,stopped',[(1,True),(50,False)])
def test_real_steal_momentum_five_feet_and_once_per_round(monkeypatch,dc,stopped):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND',dc=dc),foe=S.bundle(STEAL,actor_id=S.FOE),foe_at=(10,6))
    reactor=e.state.actors[S.FOE]
    e._gain_resource(reactor,'resource:core.martial_focus',1,'test:ready')
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    use(e,candidate(e,6))
    actor=e.state.actors[S.ME]
    assert actor.position==Position(x=4 if stopped else 6,y=6)
    assert not reactor.reaction_available and reactor.resources['resource:core.martial_focus']==0
    assert reactor.turn_flags['once_per_round:steal_momentum']==e.state.round_number
    assert getattr(e,'_movement_step_context',None) is None
    # Restore both costs and trigger another eligible five-foot move this round.
    # The once-per-round marker, rather than exhausted economy, must deny it.
    reactor.reaction_available=True
    e._gain_resource(reactor,'resource:core.martial_focus',1,'test:restore')
    count=sum(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==STEAL for ev in e.events)
    use(e,candidate(e,3))
    assert e.state.actors[S.ME].position==Position(x=3,y=6)
    assert reactor.reaction_available and reactor.resources['resource:core.martial_focus']==1
    assert sum(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==STEAL for ev in e.events)==count


def test_nested_granted_step_context_restored(monkeypatch):
    from combat import granted_movement
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(10,6))
    seen=[]
    def nested(engine,mover,previous,nxt,intent):
        saved=dict(context(engine,mover));seen.append((mover.entity_id,saved['travelled_ft']))
        if mover.entity_id==S.ME:
            reactor=engine.state.actors[S.FOE]
            c=next(iter(granted_movement.candidates(engine,reactor,5,intent,'test:grant').values()))
            ordinary=reactor.movement_remaining_ft
            engine._resolve_movement(reactor,c,intent,granted_ft=5,ignore_oa_from=tuple(engine.state.actors))
            assert reactor.movement_remaining_ft==ordinary
            assert dict(context(engine,mover))==saved
            return {'stop':True,'source_id':'test:nested','label':'Stop after the response.'}
    install(monkeypatch,'movement_step',nested)
    use(e,candidate(e,6))
    assert seen==[(S.ME,5),(S.FOE,5)] and getattr(e,'_movement_step_context',None) is None


def portable(tmp_path,left_feature,right_feature,*,left_at=(3,6),right_at=(10,6),dc=1,provider=None,blocker=False,map_fields=None):
    import json,zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from tests.h1_support import ROOT,sheet
    from tests.test_hidden_targeting import turn
    left,right='actor:factory.aaaaaaaa','actor:factory.ffffffff'
    fighters=[('aaaaaaaa',left_feature),('ffffffff',right_feature)]
    if blocker: fighters.append(('bbbbbbbb','SAND_BASE_SCOURING_HAND'))
    for pid,feature in fighters:
        document=sheet([feature],cl=20,dc=dc if pid=='aaaaaaaa' else 16)
        document['ability_scores_and_statistics']['hit_points']['maximum']=600
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document))
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(pid,{'mode':'ask'},{feature})
    service=CombatService(ROOT,tmp_path,ai_provider=provider)
    service.tabletop_maps.save({'display_name':'Step yard','width_squares':20,'height_squares':14,
        'walls':[],'starts':{'team1':[list(left_at),[11,10]],'team2':[list(right_at)]},**(map_fields or {})})
    projects=['aaaaaaaa']+(['bbbbbbbb'] if blocker else [])
    actors=[left,right]+(['actor:factory.bbbbbbbb'] if blocker else [])
    mid=service.create_factory_match(project_ids=projects,opponent_actor_ids=[right],
        control_modes={a:'MANUAL' for a in actors},arena_id='battlefield:map.step-yard',match_seed='L8-STEPS')['match_id']
    table=TabletopService(service,tmp_path);turn(table,mid,left)
    return service,table,mid,left,right


def test_prison_table_crossing_stops_and_replays(tmp_path,monkeypatch):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_hidden_targeting import turn
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    service,table,mid,left,right=portable(tmp_path,PRISON,'SAND_BASE_SCOURING_HAND',right_at=(8,6),dc=50)
    def send(c):
        return table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])
    e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Event Horizon Prison') and c.destination==Position(x=5,y=6))
    assert send(c)['status']=='COMMITTED'
    turn(table,mid,right)
    e=service._load_session(mid).engine
    assert send(candidate(e,10))['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[right].position==Position(x=9,y=6)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('dc,expected',[ (1,4),(50,6)])
def test_api_move_pauses_for_real_reaction_and_followup_step_after_reload(tmp_path,monkeypatch,dc,expected):
    import json
    from combat.gate5_service import CombatService,AI_RESPONSE_SCHEMA
    from combat.gate3_reducer import canonical_state_sha256
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    class Provider:
        calls=0
        def status(self):return {'ready':True}
        def complete_json(self,*,prompt_text,**kw):
            self.calls+=1
            frame=json.loads(prompt_text.split('\n\n',1)[1])
            c=next(c for c in frame['legal_candidates'] if c['kind']=='MOVE' and c['destination']=={'x':6,'y':6})
            payload={k:c[k] for k in ('candidate_id','actor_id','target_ids','destination','option_ids')}
            payload.update(decision_id=frame['decision_id'],state_version=frame['state_version'])
            return {'value':{'schema':AI_RESPONSE_SCHEMA,'action_intent':payload,'rationale':'Walk three squares.'},
                'provider_id':'test:offline','model':'fake','request_sha256':'test-request'}
    p=Provider()
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    service,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND',STEAL,dc=dc,provider=p)
    def focus(engine,kind,kwargs):
        if kind=='HOLD_POSITION_COMMITTED' and kwargs.get('actor_id')==left:
            engine._gain_resource(engine.state.actors[right],'resource:core.martial_focus',1,'test:ready')
    ext.effects();monkeypatch.setitem(ext._HOOKS,'event',[*ext._HOOKS.get('event',[]),focus])
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    service.set_controller_mode(mid,actor_id=left,controller_mode='API_AUTO')
    before=canonical_state_sha256(service._load_session(mid).engine.state)
    first=service.provider_step(mid)
    assert first['status']=='AWAITING_REACTION' and p.calls==1
    assert canonical_state_sha256(service._load_session(mid).engine.state)==before
    def answer(ctx,option):
        return {k:ctx[k] for k in ('checkpoint','reactor_id','reaction_source_id')} | {'selection':'USE','option_ids':[option]}
    restarted=CombatService(ROOT,tmp_path)
    second=restarted.provider_step(mid,[answer(first['reaction_context'],'use')])
    assert second['status']=='AWAITING_REACTION'
    assert canonical_state_sha256(restarted._load_session(mid).engine.state)==before
    restarted=CombatService(ROOT,tmp_path)
    result=restarted.provider_step(mid,[answer(second['reaction_context'],'cell:10,7')])
    assert result['status']=='COMMITTED' and p.calls==1
    loaded=restarted._load_session(mid);e=loaded.engine
    assert e.state.actors[left].position==Position(x=expected,y=6)
    assert e.state.actors[right].position==Position(x=10,y=7)
    assert not e.state.actors[right].reaction_available and e.state.actors[right].resources['resource:core.martial_focus']==0
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
