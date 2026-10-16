"""Native action adapter for source-owned journey commands.

No second attack/save/geometry implementation: consumers select an acquired
action and a native candidate before payment, then use the normal resolver.
Only registered continuation providers export effects back to the journey.
The transient engine never creates a fight, writes a database or advances a
scene turn. Inputs and native receipts are journaled by the journey caller.
"""
from copy import deepcopy
from pathlib import Path
from . import ext
from .gate4_engine import Gate4ControllerEngine
from .gate2_runtime_models import ActionIntent
from .choice_checkpoints import ChoicePause


class SceneChoicePause(ChoicePause):
    def __init__(self, request):
        self.request=deepcopy(request)


def dispatch(session, aid, kind, payload, command):
    """Atomic scene-choice transport, shared by all native source commands.

    Pausing rolls back the entire attempted command. Only the question and
    exact accepted answers persist; resumption replays the same sealed inputs.
    A different creature cannot answer, move, or spend while priority is held.
    """
    from .journey import require
    from .gate2_runtime_models import ReactionDecision
    pending=session.state.get('scene_pending')
    answers=[]
    origin={'actor_id':aid,'kind':kind,'payload':deepcopy(payload)}
    if pending:
        request=pending['request']
        require(kind=='scene_choice' and aid==request['reactor_id'],
                'The named creature must answer its pending scene choice first.')
        require(set(payload)=={'selection','option_ids','spend'},'Choose Use or Pass and the offered options.')
        decision=ReactionDecision(checkpoint=request['checkpoint'],reactor_id=aid,
            reaction_source_id=request['reaction_source_id'],**payload)
        from .choice_checkpoints import validate
        from .gate4_models import ExtensionChoice
        if request.get('extension_choice'):
            validate(decision,ExtensionChoice.model_validate(request['extension_choice']))
        else:
            require(not decision.option_ids and (decision.spend in request.get('spend_options',[]) or decision.spend==0),
                    'Choose an offered reaction spend.')
        origin=deepcopy(pending['origin'])
        answers=[*pending['answers'],decision.model_dump(mode='json')]
    else:require(kind!='scene_choice','There is no pending scene choice.')
    before=deepcopy(session.state)
    session.state.pop('scene_pending',None)
    session._scene_answers=answers
    try:
        return command(origin['actor_id'],origin['kind'],origin['payload'])
    except SceneChoicePause as pause:
        session.state=before
        session.state['scene_pending']={'origin':origin,'answers':answers,'request':pause.request}
    finally:
        session.__dict__.pop('_scene_answers',None)


def choice_provider(session, native):
    """Route each question by its chooser, even during another actor's action."""
    from .gate2_runtime_models import ReactionDecision
    def provider(request):
        key=tuple(request[k] for k in ('checkpoint','reactor_id','reaction_source_id'))
        for row in getattr(session,'_scene_answers',()):
            if tuple(row[k] for k in ('checkpoint','reactor_id','reaction_source_id'))==key:
                return ReactionDecision.model_validate(row),None
        if native.typed_control_modes[request['reactor_id']]=='MANUAL':
            request=deepcopy(request)
            trigger=request.setdefault('choice_trigger',{})
            acting=native.state.actors[native._active_intent.actor_id]
            affected=native.state.actors[request['reactor_id']]
            action=native.action_catalog[native._active_action_source_id]
            trigger['prompt']=(trigger.get('prompt') or 'Choose whether to use this optional response.')+f' During {acting.display_name}’s {action.display_name}; decision for {affected.display_name}.'
            raise SceneChoicePause(request)
        spec=request.get('extension_choice')
        if spec:
            options=spec['option_ids'];preferred=spec.get('preferred_option_ids',[])
            ordered=[*preferred,*[o for o in options if o not in preferred]]
            use=spec.get('automatic_use',False)
            chosen=ordered[:max(1,spec['minimum_selections'])] if use else []
            if use and spec['maximum_selections']==0:chosen=[]
            return ReactionDecision(checkpoint=key[0],reactor_id=key[1],reaction_source_id=key[2],
                selection='USE' if use else 'DECLINE',option_ids=tuple(chosen)),None
        return None,None
    return provider


def engine_for(session):
    actors=session.state['actors'];bundles=[]
    for aid,row in actors.items():
        bundle=ext.transform('journey_combat_setup',deepcopy(row['bundle']),session,aid)
        # A source-resolution adapter restores its own continuations below,
        # without beginning an encounter or reapplying a terminal health delta.
        bundle.pop('journey_setup',None)
        bundle['native_scene_resolution']=1
        for pool in bundle['actor_template']['resources']:
            pool['initial']=row['resources'].get(pool['resource_id'],pool['initial'])
        bundles.append(bundle)
    native=Gate4ControllerEngine(Path(__file__).resolve().parents[1],
        match_seed=session.state['journey_id']+':source:'+str(len(session.state['events'])),
        typed_bundles=tuple(bundles),battlefield=session.state['battlefield'],
        roster_setup={'defer_first_turn':True,'defer_initiative':True,'primary_actor_ids':list(actors),'team_by_actor':{aid:'scene' for aid in actors},
            'starting_positions':{aid:row['position'] for aid,row in actors.items()}})
    # Ordinary persisted health and physical conditions are inputs, not heals.
    from .journey_equipment import context
    physical=context(session)
    for aid,actor in native.state.actors.items():
        saved=ext.transform('journey_snapshot_actor',physical.state.actors[aid],session,aid,native)
        actor.current_hp=saved.current_hp;actor.active=saved.active;actor.life_state=saved.life_state
        for iid,c in saved.conditions.items():
            if iid not in actor.conditions:actor.conditions[iid]=c.model_copy(deep=True)
        actor.action_available=True;actor.bonus_action_available=True
    native.typed_control_modes={aid:row['control_mode'] for aid,row in actors.items()}
    native.typed_ask_reactors={aid for aid,mode in native.typed_control_modes.items() if mode=='MANUAL'}
    native.set_reaction_provider(choice_provider(session,native))
    return native


def candidates(native,aid,action):
    """All native candidates, including source gates and exact physical routes."""
    actor=native.state.actors[aid]
    return [c for c in native._action_candidates(actor,action)
        if False not in ext.run_strict('candidate_allowed',native,actor,c,action)]


def commit(session,native,aid,action,candidate,choices):
    """Resolve one already admitted action and export only opted-in state."""
    from .ext.needle import declared_choices
    from .ext.journey_turns import pay
    if action.economy.value in ('ACTION','BONUS_ACTION'):
        pay(session,aid,'bonus_action' if action.economy.value=='BONUS_ACTION' else 'action')
    start=len(native.events)
    intent=ActionIntent(intent_id='scene:'+str(len(session.state['events'])),
        decision_id=candidate.decision_id,candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,actor_id=aid,target_ids=candidate.target_ids,
        destination=candidate.destination)
    # Native targeting and defender/source hooks read the accepted intent and
    # candidate, including a frozen remembered-square aim. These are ordinary
    # per-intent fields, exactly as in Gate2Engine.apply_intent; no method or
    # class is replaced, and the transient engine cannot leak this frame.
    names=('_active_intent','_active_candidate','_active_action_source_id','_active_intent_id')
    previous={name:getattr(native,name,None) for name in names}
    native._active_intent=intent
    native._active_candidate=candidate
    native._active_action_source_id=action.source_definition_id
    native._active_intent_id=intent.intent_id
    try:
        with declared_choices(native,choices):
            native._resolve_action(native.state.actors[aid],action,candidate,intent)
    finally:
        for name,value in previous.items():setattr(native,name,value)
    from .journey_assets import JourneyAssetContext
    for subject,actor in native.state.actors.items():
        row=session.state['actors'][subject]
        row['position']=actor.position.model_dump(mode='json');row['resources']=dict(actor.resources)
        ext.run_strict('journey_resolution_settled',session,subject,native,actor)
    objects=JourneyAssetContext(session)
    for obj in native.state.objects.values():
        objects._update_object(obj,'system:scene.native_resolution',aid)
    for event in native.events[start:]:
        # The authoritative receipt is retained privately; source view providers
        # never project this internal native journal to another controller.
        session.emit('SOURCE_NATIVE_RESOLVED',aid,native=event.model_dump_json(exclude_none=True))
    return True
