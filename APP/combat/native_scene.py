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
        roster_setup={'primary_actor_ids':ids,'team_by_actor':{aid:a.get('team_id',aid) for aid,a in session.state['actors'].items()},
            'starting_positions':{aid:a['position'] for aid,a in session.state['actors'].items()},
            'participant_control_modes':{aid:a['control_mode'] for aid,a in session.state['actors'].items()},
            'rules':{'zero_hp':'dying_2024','finalized_turns':'skip_finalized_v1'}})
    saved=session.state.get(KEY)
    if saved:
        engine.state=MatchState.model_validate_json(saved['state'])
        engine.events=[CombatEvent.model_validate_json(row) for row in saved['events']]
        engine.rolls=[RollRecord.model_validate_json(row) for row in saved['rolls']]
        engine.roller.counter=engine.state.roll_counter
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
    previous=getattr(engine,'_active_intent',None)
    if getattr(session,'native_scene_executing',False):
        engine._active_intent=ActionIntent(intent_id='journey-turn:'+str(session.state['revision'])+':'+aid,
            decision_id='scene-turn',candidate_id='scene-turn',state_version=engine.state.state_version,actor_id=aid)
    try:engine.scene_turn(aid,'start',marker)
    finally:engine._active_intent=previous
    if turn:
        actor.action_available=bool(turn['active'] and turn['action'])
        actor.bonus_action_available=bool(turn['active'] and turn['bonus_action'])
        actor.movement_remaining_ft=min(actor.movement_remaining_ft,turn['movement_remaining_ft'])
    return actor


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


def provider(session,owner,choices,answers):
    def resolve(request):
        key=canonical({k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')})
        identity={k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')}
        if key in answers:
            return ReactionDecision.model_validate({**identity,**answers[key]}),None
        rid=request['reaction_source_id']
        if request['reactor_id']==owner and rid in choices:
            selected=choices[rid]
            require(isinstance(selected,list) and all(type(v) is str for v in selected),'Choose actual offered options.')
            return ReactionDecision(**identity,selection='USE' if selected else 'DECLINE',option_ids=tuple(selected)),None
        spec=request.get('extension_choice') or {}
        if session.state['actors'][request['reactor_id']]['control_mode']=='LOCAL_AUTO' and spec.get('automatic_use'):
            options=list(spec.get('preferred_option_ids') or spec.get('option_ids') or [])
            selected=options[:spec.get('minimum_selections',1)]
            return ReactionDecision(**identity,selection='USE' if selected or not spec.get('allow_decline') else 'DECLINE',option_ids=tuple(selected)),None
        raise SceneChoice(request)
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
    engine.set_reaction_provider(provider(session,aid,choices,answers))
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


def run_operation(session,aid,operation,payload,answers=None,identity_revision=None):
    before=deepcopy(session.state)
    revision=session.state['revision'] if identity_revision is None else identity_revision
    try:
        if operation=='action':execute_action(session,aid,payload,answers or {},identity_revision=revision)
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
