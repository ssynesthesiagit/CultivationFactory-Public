"""Native action resolution inside a persisted elapsed scene.

Source plug-ins opt in actual owned action IDs. This adapter uses the real native
candidate, intent, save, damage, condition and object resolver; it contains no
ability IDs or duplicated effect implementation. Explicit journey source turns
own turn boundaries. Native state/events/rolls are canonical JSON strings and
cold command replay re-executes the same accepted intents and actor answers.
"""
from copy import deepcopy
import json
from pathlib import Path
from . import ext
from .journey import require
from .gate2_runtime_models import MatchState,CombatEvent,RollRecord,ReactionDecision,ActionIntent,Position
from .choice_checkpoints import ChoicePause

KEY='native_scene'
PENDING='native_scene_pending'


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


class SceneChoice(ChoicePause):
    def __init__(self,request):self.request=deepcopy(request)


def enabled_actions(session,aid):
    return {item for rows in ext.run_strict('journey_native_actions',session,aid) for item in rows}


def engine_for(session):
    from .gate4_engine import Gate4ControllerEngine
    ids=list(session.state['actors'])
    bundles=[]
    for a in session.state['actors'].values():
        bundle=deepcopy(a['bundle'])
        bundle['journey_setup']={'incapacitated':a['incapacitated'],'exhaustion':a['exhaustion']}
        if 'encounter_snapshot' in a:bundle['journey_setup']['encounter_snapshot']=a['encounter_snapshot']
        bundles.append(bundle)
    engine=Gate4ControllerEngine(Path(__file__).resolve().parents[1],match_seed=session.state['journey_id']+':native',
        maximum_rounds=1000000,scene_mode=True,
        typed_bundles=tuple(bundles),battlefield=session.state['battlefield'],
        roster_setup={'primary_actor_ids':ids,'team_by_actor':{aid:a.get('team_id',a['bundle']['actor_template']['team_id']) for aid,a in session.state['actors'].items()},
            'starting_positions':{aid:a['position'] for aid,a in session.state['actors'].items()},
            'participant_control_modes':{aid:a['control_mode'] for aid,a in session.state['actors'].items()},
            'rules':{'zero_hp':'dying_2024','finalized_turns':'skip_finalized_v1'}})
    saved=session.state.get(KEY)
    if saved:
        engine.state=MatchState.model_validate_json(saved['state'])
        engine.events=[CombatEvent.model_validate_json(row) for row in saved['events']]
        engine.rolls=[RollRecord.model_validate_json(row) for row in saved['rolls']]
        engine.roller.counter=engine.state.roll_counter
        engine._transaction_result_version=engine.state.state_version
    from .gate2_runtime_models import RuntimeObjectState
    for oid,row in session.state.get('runtime_objects',{}).items():
        engine.state.objects[oid]=RuntimeObjectState.model_validate(row)
    engine.scene_source_session=session
    engine.typed_control_modes={aid:a['control_mode'] for aid,a in session.state['actors'].items()}
    for aid,actor in engine.state.actors.items():
        if aid not in session.state['actors']:continue
        outside=session.state['actors'][aid]
        actor.position=Position.model_validate(outside['position'])
        actor.resources.update(outside['resources'])
    from . import zones
    zones.sync_walls(engine)
    return engine


def bind_turn(engine,session,aid):
    actor=engine.state.actors[aid]
    turn=session.state['actors'][aid].get('source_turn')
    marker=turn['started'] if turn else 1
    if getattr(session,'native_scene_executing',False):
        apply_turn(engine,session,aid,'start',marker)
    else:engine.scene_turn(aid,'start',marker)
    if turn:
        actor.action_available=bool(turn['active'] and turn['action'])
        actor.bonus_action_available=bool(turn['active'] and turn['bonus_action'])
        actor.movement_remaining_ft=min(actor.movement_remaining_ft,turn['movement_remaining_ft'])
    return actor


def apply_turn(engine,session,aid,edge,marker):
    """Bind actual source-turn intent and ordinary transaction rollback."""
    if edge=='start' and engine.state.actors[aid].turns_started>=marker:
        engine.state.current_actor_id=aid
        engine.state.current_slot_index=engine.state.initiative_order.index(aid)
        return
    previous=getattr(engine,'_active_intent',None)
    frame=ActionIntent(intent_id='journey-turn:'+str(getattr(session,'native_scene_identity_revision',session.state['revision']))+':'+aid+':'+edge,
        decision_id='scene-turn',candidate_id='scene-turn',state_version=engine.state.state_version,actor_id=aid)
    engine._active_intent=frame
    try:
        with engine._transaction('system:scene.turn',frame.intent_id,aid):engine.scene_turn(aid,edge,marker)
    finally:engine._active_intent=previous


def save_engine(session,engine):
    engine.state.roll_counter=engine.roller.counter
    session.state[KEY]={'state':canonical(engine.state.model_dump(mode='json')),
        'events':[canonical(row.model_dump(mode='json')) for row in engine.events],
        'rolls':[canonical(row.model_dump(mode='json')) for row in engine.rolls]}
    for aid,outside in session.state['actors'].items():
        actor=engine.state.actors[aid]
        outside['position']=actor.position.model_dump(mode='json')
        outside['resources']=dict(actor.resources)
        from .ext.needle import incapacitated
        outside['incapacitated']=int(not actor.active or incapacitated(actor) or actor.life_state in ('DYING','STABLE','DEAD'))
        turn=outside.get('source_turn')
        if turn:
            turn['movement_remaining_ft']=min(turn['movement_remaining_ft'],actor.movement_remaining_ft)
            turn['movement_position']=dict(outside['position'])
    if engine.state.objects:
        session.state['runtime_objects']={key:row.model_dump(mode='json') for key,row in engine.state.objects.items()}


def provider(session,owner,choices,answers,engine=None):
    def resolve(request):
        key=canonical({k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')})
        identity={k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')}
        if key in answers:
            return ReactionDecision.model_validate({**identity,**answers[key]}),None
        rid=request['reaction_source_id']
        reactor=engine.state.actors.get(request['reactor_id']) if engine else None
        controller=(reactor.owner_id if reactor and reactor.owner_id in session.state['actors'] else request['reactor_id'])
        if controller==owner and rid in choices:
            selected=choices[rid]
            require(isinstance(selected,list) and all(type(v) is str for v in selected),'Choose actual offered options.')
            return ReactionDecision(**identity,selection='USE' if selected else 'DECLINE',option_ids=tuple(selected)),None
        spec=request.get('extension_choice') or {}
        if session.state['actors'][controller]['control_mode']=='LOCAL_AUTO' and spec.get('automatic_use'):
            options=list(spec.get('preferred_option_ids') or spec.get('option_ids') or [])
            selected=options[:spec.get('minimum_selections',1)]
            return ReactionDecision(**identity,selection='USE' if selected or not spec.get('allow_decline') else 'DECLINE',option_ids=tuple(selected)),None
        raise SceneChoice({**request,'controller_id':controller})
    return resolve


def execute_action(session,aid,payload,answers,*,identity_revision):
    require(set(payload)<={'action_id','subject_id','choices','option_ids'},'Choose a native action, target and owned decisions.')
    source=payload.get('action_id');subject=payload.get('subject_id',aid)
    require(source in enabled_actions(session,aid),'That source has not enabled this native scene action.')
    choices=payload.get('choices',{})
    require(isinstance(choices,dict) and all(type(k) is str for k in choices),'Source choices must be a document.')
    from .ext.journey_turns import begin,pay
    turn=session.state['actors'][aid].get('source_turn')
    if turn is None:begin(session,aid)
    else:require(turn['active'],'Begin this creature’s next scene turn before acting.')
    session.native_scene_executing=True
    engine=engine_for(session)
    engine.set_reaction_provider(provider(session,aid,choices,answers,engine))
    actor=bind_turn(engine,session,aid)
    candidates=[c for c in engine.legal_candidates() if c.source_definition_id==source and c.target_ids==(subject,)]
    require(len(candidates)==1,'Choose a currently reachable, legal native target.')
    candidate=candidates[0]
    intent=ActionIntent(intent_id='journey-native:'+str(identity_revision)+':'+aid,
        decision_id=candidate.decision_id,candidate_id=candidate.candidate_id,state_version=candidate.state_version,
        actor_id=aid,target_ids=candidate.target_ids,destination=candidate.destination,
        option_ids=tuple(payload.get('option_ids',candidate.option_ids)))
    before=engine.state.event_sequence
    engine.execute_intent(intent)
    for economy,available in [('action',actor.action_available),('bonus_action',actor.bonus_action_available)]:
        if not available and session.state['actors'][aid]['source_turn'][economy]:pay(session,aid,economy)
    ext.run_strict('journey_native_committed',session,engine,aid,engine.action_catalog[source],before)
    save_engine(session,engine)
    session.emit('NATIVE_SCENE_ACTION_COMMITTED',aid,source=source,subject=subject,intent_id=intent.intent_id)


def procedures(session,aid):
    """Registered native action IDs and their printed elapsed procedure times."""
    result={}
    for rows in ext.run_strict('journey_native_procedures',session,aid):
        for source,seconds in rows.items():
            require(type(source) is str and type(seconds) is int and seconds>0,'A procedure needs a source and positive elapsed duration.')
            require(source not in result or result[source]==seconds,'Conflicting procedure durations.')
            result[source]=seconds
    return result


def procedure_action(action):
    # This local descriptor is never published as a free combat action. The
    # registered elapsed procedure owns timing; ordinary geometry/costs remain.
    from .gate2_runtime_models import EconomyKind
    return action.model_copy(update={'economy':EconomyKind.NONE,
        'parameters':{**action.parameters,'free_primary':True}})


def procedure_candidates(engine,actor,action):
    return [c for c in engine._action_candidates(actor,procedure_action(action))
        if not ext.any_false('candidate_allowed',engine,actor,c,action)]


def execute_procedure(session,aid,payload,answers,*,identity_revision):
    require(set(payload)<={'action_id','subject_id','choices','option_ids'},'Choose a native procedure, target and owned decisions.')
    source=payload.get('action_id');subject=payload.get('subject_id',aid)
    seconds=procedures(session,aid).get(source)
    require(seconds is not None,'That source has not enabled an elapsed examination.')
    choices=payload.get('choices',{})
    require(isinstance(choices,dict) and all(type(k) is str for k in choices),'Source choices must be a document.')
    # Validate admission before advancing time, then recheck after elapsed scene
    # effects. No Action, Bonus Action, initiative or source turn is fabricated.
    engine=engine_for(session);actor=engine.state.actors[aid]
    engine.state.current_actor_id=aid
    engine.state.current_slot_index=engine.state.initiative_order.index(aid)
    action=engine.action_catalog.get(source)
    require(action is not None and action.owner_id==aid and source in actor.action_ids,'Choose your own acquired procedure.')
    require(any(c.target_ids==(subject,) for c in procedure_candidates(engine,actor,action)),'Choose a currently reachable native procedure target.')
    session.tick(seconds)
    engine=engine_for(session);actor=engine.state.actors[aid]
    require(not session.state['actors'][aid]['incapacitated'],'The examination was interrupted.')
    engine.state.current_actor_id=aid
    engine.state.current_slot_index=engine.state.initiative_order.index(aid)
    action=procedure_action(engine.action_catalog[source])
    candidates=[c for c in procedure_candidates(engine,actor,action) if c.target_ids==(subject,)]
    require(len(candidates)==1,'The target is no longer available after the examination.')
    candidate=candidates[0]
    intent=ActionIntent(intent_id='journey-procedure:'+str(identity_revision)+':'+aid,
        decision_id=candidate.decision_id,candidate_id=candidate.candidate_id,state_version=candidate.state_version,
        actor_id=aid,target_ids=candidate.target_ids,destination=candidate.destination,
        option_ids=tuple(payload.get('option_ids',candidate.option_ids)))
    engine.set_reaction_provider(provider(session,aid,choices,answers,engine))
    engine._active_intent=intent;engine._active_candidate=candidate;engine._active_action_source_id=source
    before=engine.state.event_sequence
    try:
        with engine._transaction(source,intent.intent_id,aid):
            engine._append_event('INTENT_ACCEPTED',source,actor_id=aid,target_ids=candidate.target_ids,
                payload={'candidate_id':candidate.candidate_id,'kind':'PROCEDURE','elapsed_seconds':seconds,'option_ids':list(intent.option_ids)})
            from .technique_interception import activation
            try:
                with activation(engine,actor,action,candidate,intent) as (resolved,bound,canceled):
                    if not canceled and engine._resolve_action(actor,resolved,bound,intent) is not False:
                        engine._run_final_riders('resolution_final',engine,actor,resolved,bound,intent)
            finally:ext.run('activation_end',engine,actor,action,candidate,intent)
    finally:
        engine._active_intent=None;engine._active_candidate=None;engine._active_action_source_id=None
    ext.run_strict('journey_native_committed',session,engine,aid,action,before)
    save_engine(session,engine)
    session.emit('NATIVE_SCENE_PROCEDURE_COMMITTED',aid,source=source,subject=subject,intent_id=intent.intent_id,elapsed_seconds=seconds)


def run_operation(session,aid,operation,payload,answers=None,identity_revision=None):
    before=deepcopy(session.state)
    revision=session.state['revision'] if identity_revision is None else identity_revision
    session.native_scene_identity_revision=revision
    try:
        if operation=='action':execute_action(session,aid,payload,answers or {},identity_revision=revision)
        elif operation=='procedure':execute_procedure(session,aid,payload,answers or {},identity_revision=revision)
        elif operation=='turn':
            session.native_scene_answers=answers or {}
            session.native_scene_chooser=aid
            from .ext.journey_turns import boundary
            boundary(session,aid,'scene_turn',payload)
        else:raise ValueError('Unknown native scene operation.')
    except SceneChoice as pause:
        session.state=before
        session.state[PENDING]={'actor_id':aid,'operation':operation,'payload':deepcopy(payload),
            'answers':deepcopy(answers or {}),'identity_revision':revision,'request':pause.request}
        session.emit('NATIVE_SCENE_CHOICE_REQUIRED',pause.request['reactor_id'],
            prompt=(pause.request.get('choice_trigger') or {}).get('prompt','Choose your own response.'))
        return
    session.state.pop(PENDING,None)
