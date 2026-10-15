"""Opt-in native scene action transport and controller-owned pending choices."""
from copy import deepcopy
import json
from . import hook,run_strict
from ..native_scene import KEY,PENDING,canonical,enabled_actions,engine_for,bind_turn,save_engine,run_operation,provider
from ..journey import require


@hook('journey_options')
def actions(session,aid):
    if session.state['phase']!='travel':return None
    pending=session.state.get(PENDING)
    if pending:
        request=pending['request']
        if request['reactor_id']!=aid:return []
        spec=request.get('extension_choice') or {}
        trigger=request.get('choice_trigger') or {}
        return [{'id':'native_scene_answer','kind':'native_scene_answer','auto_select':0,
            'label':trigger.get('prompt','Choose your own response.'),'payload':{'selection':'USE','option_ids':[]},
            'options':[{'id':k,'label':trigger.get('labels',{}).get(k,k)} for k in spec.get('option_ids',[])],
            'minimum':spec.get('minimum_selections',0),'maximum':spec.get('maximum_selections',0),
            'allow_decline':int(spec.get('allow_decline',True))}]
    allowed=enabled_actions(session,aid)
    if not allowed or session.state['actors'][aid]['incapacitated']:return None
    turn=session.state['actors'][aid].get('source_turn')
    if turn and not turn['active']:return None
    engine=engine_for(session);bind_turn(engine,session,aid)
    return [{'id':'native_scene:'+c.candidate_id,'kind':'native_scene_action','auto_select':0,
        'label':c.display_name,
        'payload':{'action_id':c.source_definition_id,'subject_id':c.target_ids[0],'choices':{},'option_ids':list(c.option_ids)}}
        for c in engine.legal_candidates() if c.source_definition_id in allowed and len(c.target_ids)==1]


@hook('journey_command_gate')
def pending_gate(session,aid,kind,payload):
    if session.state.get(PENDING):return kind=='native_scene_answer'


@hook('journey_execute')
def native_commands(session,aid,kind,payload):
    if kind=='native_scene_action':
        require(session.state['phase']=='travel' and not session.state.get(PENDING),'Finish the current scene decision before acting.')
        run_operation(session,aid,'action',payload)
        return True
    if kind=='native_scene_answer':
        pending=session.state.get(PENDING)
        require(pending is not None and pending['request']['reactor_id']==aid,'Only this choice’s creature may answer it.')
        require(set(payload)<={'selection','option_ids','spend'} and payload.get('selection') in ('USE','DECLINE'),'Choose your own offered response.')
        request=pending['request'];answers=deepcopy(pending['answers'])
        key=canonical({k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')})
        answers[key]=deepcopy(payload)
        run_operation(session,pending['actor_id'],pending['operation'],pending['payload'],answers,identity_revision=pending['identity_revision'])
        return True
    if kind=='scene_turn' and KEY in session.state and not session.state.get(PENDING):
        run_operation(session,aid,'turn',payload)
        return True


@hook('journey_turn_boundary')
def native_turn(session,aid,edge):
    if KEY not in session.state:return
    engine=engine_for(session)
    engine.set_reaction_provider(provider(session,getattr(session,'native_scene_chooser',aid),{},getattr(session,'native_scene_answers',{})))
    turn=session.state['actors'][aid]['source_turn']
    if edge=='end' and engine.state.actors[aid].turns_started<turn['started']:
        engine.scene_turn(aid,'start',turn['started'])
    from ..gate2_runtime_models import ActionIntent
    engine._active_intent=ActionIntent(intent_id='journey-turn:'+str(session.state['revision'])+':'+aid+':'+edge,
        decision_id='scene-turn',candidate_id='scene-turn',state_version=engine.state.state_version,actor_id=aid)
    try:engine.scene_turn(aid,edge,turn['started'])
    finally:engine._active_intent=None
    save_engine(session,engine)


@hook('journey_elapsed')
def native_elapsed(session,aid,before,seconds,moving):
    if KEY not in session.state or aid!=next(iter(session.state['actors'])):return
    engine=engine_for(session)
    run_strict('journey_native_elapsed',session,engine,before,before+seconds)
    save_engine(session,engine)


@hook('journey_pace_ratio')
def native_pace(session,aid):
    if KEY not in session.state:return
    engine=engine_for(session);actor=engine.state.actors[aid]
    base=int(session.state['actors'][aid]['bundle']['actor_template']['speed_ft'])
    return (engine._effective_speed(actor),base) if base else (0,1)


@hook('journey_view')
def native_private(state,viewer):
    if KEY not in state and PENDING not in state:return None
    out=deepcopy(state);out.pop(KEY,None);out.pop('replay_base',None);out.pop('command_journal',None)
    if PENDING in out:
        pending=out[PENDING]
        out[PENDING]={'request':pending['request']} if pending['request']['reactor_id']==viewer else {'awaiting_actor_id':pending['request']['reactor_id']}
    return out


@hook('journey_combat_setup')
def native_export(bundle,session,aid):
    if KEY not in session.state:return None
    setup={k:v for k,v in bundle.get('journey_setup',{}).items() if k not in {'incapacitated','exhaustion','encounter_snapshot'}}
    bundle={**bundle,'journey_setup':setup}
    if aid!=next(iter(session.state['actors'])):return bundle
    engine=engine_for(session)
    run_strict('journey_native_export',session,engine)
    state=engine.state.model_dump(mode='json')
    # The carrier is built only from this actual persisted native scene. The
    # pre-initiative consumer preserves source receipts and their integer IDs.
    carrier={'state':state,'events':[r.model_dump(mode='json') for r in engine.events],
        'rolls':[r.model_dump(mode='json') for r in engine.rolls]}
    from ..canonical import canonical_sha256
    return {**bundle,'native_scene_continuation':{**carrier,'sha256':canonical_sha256(carrier)}}


@hook('match_before_initiative')
def native_import_before(engine,actors):
    if engine.scene_mode:return
    carriers=[b['native_scene_continuation'] for b in engine.typed_bundle_documents if 'native_scene_continuation' in b]
    if not carriers:return
    require(len(carriers)==1,'A native scene continuation needs one actual scene carrier.')
    carrier=carriers[0]
    from ..canonical import canonical_sha256
    from ..gate2_runtime_models import ActorState,CombatEvent,RollRecord
    require(carrier['sha256']==canonical_sha256({k:v for k,v in carrier.items() if k!='sha256'}),'The native scene carrier failed its commitment check.')
    old=carrier['state'];require(set(old['actors'])==set(actors),'The scene continuation roster changed.')
    fields=('active','life_state','maximum_hp','current_hp','temporary_hp','conditions','modifiers','concentration',
        'turns_started','turn_flags','resources','maximum_hp_base','maximum_hp_adjustments','transformed_size_category')
    for aid,row in old['actors'].items():
        saved=ActorState.model_validate(row)
        for field in fields:setattr(actors[aid],field,deepcopy(getattr(saved,field)))
    engine.events=[CombatEvent.model_validate(r) for r in carrier['events']]
    engine.rolls=[RollRecord.model_validate(r) for r in carrier['rolls']]
    engine.roller.counter=old['roll_counter']
    engine.native_scene_continuation=carrier


@hook('match_initialize')
def native_import_after(engine):
    carrier=getattr(engine,'native_scene_continuation',None)
    if not carrier:return None
    from ..gate2_runtime_models import RuntimeObjectState,ZoneState
    old=carrier['state']
    engine.state.event_sequence=max(engine.state.event_sequence,old['event_sequence'])
    engine.state.objects={k:RuntimeObjectState.model_validate(v) for k,v in old.get('objects',{}).items()}
    engine.state.zones={k:ZoneState.model_validate(v) for k,v in old.get('zones',{}).items()}
    return True
