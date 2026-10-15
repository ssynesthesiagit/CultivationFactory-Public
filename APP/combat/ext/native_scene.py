"""Opt-in native scene action transport and controller-owned pending choices."""
from copy import deepcopy
import json
from . import hook,run_strict
from ..native_scene import KEY,PENDING,canonical,enabled_actions,engine_for,bind_turn,save_engine,run_operation,provider,apply_turn,procedures,procedure_candidates
from ..journey import require


@hook('journey_options')
def actions(session,aid):
    if session.state['phase']!='travel':return None
    pending=session.state.get(PENDING)
    if pending:
        request=pending['request']
        if request.get('controller_id',request['reactor_id'])!=aid:return []
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
    engine=engine_for(session);bind_turn(engine,session,aid)
    from ..resource_labels import resource_name
    def label(c):
        action=engine.action_catalog[c.source_definition_id]
        cost=', '.join(str(amount)+' '+resource_name(pool) for pool,amount in action.costs) or 'no CP'
        target=engine.state.actors.get(c.target_ids[0]) or engine.state.objects.get(c.target_ids[0])
        from ..object_rules import label as object_label
        name=getattr(target,'display_name',None) or object_label(target)
        name=action.parameters.get('deferred_target_label') or 'on '+name
        return c.display_name+'; '+name+'; '+action.economy.value.replace('_',' ').title()+', '+cost
    result=[{'id':'native_scene:'+c.candidate_id,'kind':'native_scene_action','auto_select':0,
        'label':label(c),
        'payload':{'action_id':c.source_definition_id,'subject_id':c.target_ids[0],'choices':{},'option_ids':list(c.option_ids)}}
        for c in engine.legal_candidates() if (not turn or turn['active']) and c.source_definition_id in allowed and len(c.target_ids)==1]
    for source,seconds in procedures(session,aid).items():
        action=engine.action_catalog.get(source)
        if action is None or action.owner_id!=aid or source not in engine.state.actors[aid].action_ids:continue
        for c in procedure_candidates(engine,engine.state.actors[aid],action):
            if len(c.target_ids)!=1:continue
            result.append({'id':'native_scene_procedure:'+c.candidate_id,'kind':'native_scene_procedure','auto_select':0,
                'label':action.display_name+'; '+str(seconds)+' seconds of examination, no CP',
                'payload':{'action_id':source,'subject_id':c.target_ids[0],'choices':{},'option_ids':list(c.option_ids)}})
    return result


@hook('journey_command_gate')
def pending_gate(session,aid,kind,payload):
    if session.state.get(PENDING):return kind=='native_scene_answer'


@hook('journey_execute')
def native_commands(session,aid,kind,payload):
    if kind in {'native_scene_action','native_scene_procedure'}:
        require(session.state['phase']=='travel' and not session.state.get(PENDING),'Finish the current scene decision before acting.')
        run_operation(session,aid,'procedure' if kind=='native_scene_procedure' else 'action',payload)
        return True
    if kind=='native_scene_answer':
        pending=session.state.get(PENDING)
        require(pending is not None and pending['request'].get('controller_id',pending['request']['reactor_id'])==aid,'Only this choice’s creature may answer it.')
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
    engine.set_reaction_provider(provider(session,getattr(session,'native_scene_chooser',aid),{},getattr(session,'native_scene_answers',{}),engine))
    turn=session.state['actors'][aid]['source_turn']
    if edge=='end' and engine.state.actors[aid].turns_started<turn['started']:
        apply_turn(engine,session,aid,'start',turn['started'])
    apply_turn(engine,session,aid,edge,turn['started'])
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
        out[PENDING]={'request':pending['request']} if pending['request'].get('controller_id',pending['request']['reactor_id'])==viewer else {'awaiting_actor_id':pending['request']['reactor_id']}
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
    old=carrier['state'];require(set(actors)<=set(old['actors'])<=set(engine.actor_templates),'The scene continuation roster changed.')
    fields=('active','life_state','maximum_hp','current_hp','temporary_hp','conditions','modifiers','concentration',
        'turns_started','turn_flags','resources','maximum_hp_base','maximum_hp_adjustments','transformed_size_category')
    for aid,row in old['actors'].items():
        if aid not in actors:continue
        saved=ActorState.model_validate(row)
        for field in fields:setattr(actors[aid],field,deepcopy(getattr(saved,field)))
    engine.events=[CombatEvent.model_validate(r) for r in carrier['events']]
    engine.rolls=[RollRecord.model_validate(r) for r in carrier['rolls']]
    engine.roller.counter=old['roll_counter']
    engine._transaction_result_version=old['state_version']
    engine.native_scene_primary_imported=set(actors)
    engine.native_scene_continuation=carrier


@hook('match_initialize')
def native_import_after(engine):
    carrier=getattr(engine,'native_scene_continuation',None)
    if not carrier:return None
    from ..gate2_runtime_models import RuntimeObjectState,ZoneState
    old=carrier['state']
    from ..gate2_runtime_models import ActorState
    for aid,row in old['actors'].items():
        if aid not in engine.native_scene_primary_imported:
            require(aid in engine.state.actors,'An owned scene actor is absent from the combat roster.')
            prior=ActorState.model_validate(row)
            engine.state.actors[aid]=prior
    engine.state.event_sequence=max(engine.state.event_sequence,old['event_sequence'])
    engine.state.objects={k:RuntimeObjectState.model_validate(v) for k,v in old.get('objects',{}).items()}
    engine.state.zones={k:ZoneState.model_validate(v) for k,v in old.get('zones',{}).items()}
    return True


@hook('journey_auto_blocked')
def pending_manual_scene(session,aid):
    return True if session.state.get(PENDING) else None


@hook('journey_properties')
def native_status(session,aid):
    if KEY not in session.state:return None
    engine=engine_for(session);actor=engine.state.actors[aid]
    hidden={iid for rows in run_strict('presentation_hidden_conditions',engine,actor) for iid in rows}
    from ..condition_names import condition_label
    return {'current_hp':actor.current_hp,'maximum_hp':actor.maximum_hp,'temporary_hp':actor.temporary_hp,
        'native_effects':[str(c.data.get('label') or condition_label(c.condition_id))
            for iid,c in actor.conditions.items() if iid not in hidden]}


@hook('journey_options')
def concentration_options(session,aid):
    if KEY not in session.state or session.state.get(PENDING) or session.state['phase']!='travel':return None
    engine=engine_for(session);actor=engine.state.actors[aid]
    from ..concentration import copies
    sources={one.source_definition_id for one in [actor.concentration] if one is not None}
    from ..concentration import held
    sources.update(one.source_definition_id for _,one in held(actor))
    return [{'id':'end_concentration:'+str(sequence),'kind':'native_scene_end_concentration','auto_select':0,
        'label':'End Concentration on '+(engine.action_catalog[source].display_name if source in engine.action_catalog else 'this effect')+' (no action or CP)',
        'payload':{'started_sequence':sequence}}
        for source in sorted(sources) for sequence in copies(actor,source)]


@hook('journey_command')
def end_concentration(session,aid,kind,payload):
    if kind!='native_scene_end_concentration':return None
    require(KEY in session.state and set(payload)=={'started_sequence'} and type(payload['started_sequence']) is int,'Choose your own active Concentration.')
    engine=engine_for(session);actor=engine.state.actors[aid]
    from ..concentration import held,end_copy
    live=[actor.concentration,*[one for _,one in held(actor)]]
    require(any(one is not None and one.started_sequence==payload['started_sequence'] for one in live),'That Concentration does not belong to this creature.')
    end_copy(engine,actor,payload['started_sequence'],'OWNER_ENDED')
    save_engine(session,engine)
    session.emit('NATIVE_SCENE_CONCENTRATION_ENDED',aid,started_sequence=payload['started_sequence'])
    return True
