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
        self.request=choice_document(request)


def choice_document(value):
    """Persist native questions as integer/string documents, never live objects.

    Native optional fields may be None and native flags may be booleans; omit
    absent fields and encode flags as 0/1 before crossing the journey boundary.
    Keep every offered choice; no list or selection domain is truncated.
    """
    if isinstance(value,str):return str(value)
    if isinstance(value,int):return int(value)
    if isinstance(value,(list,tuple)):return [choice_document(v) for v in value]
    if isinstance(value,dict):return {str(k):choice_document(v) for k,v in value.items() if v is not None}
    raise ValueError('A native scene question must contain only integer/string documents.')


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
            require(len(set(decision.option_ids))==len(decision.option_ids)
                    and set(decision.option_ids)<=set(request.get('legal_option_ids',[]))
                    and (decision.spend in request.get('spend_options',[]) or decision.spend==0),
                    'Choose an offered reaction spend.')
            require(decision.selection!='DECLINE' or (decision.spend==0 and not decision.option_ids),
                    'Passing a response spends nothing and selects no options.')
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
            from .typed_reactions import source_reaction_rows
            response=next((r.get('name','optional response') for r in source_reaction_rows(native,affected)
                if (r.get('consent_source_id') or 'reaction:typed.'+r['feature_id'])==request['reaction_source_id']), 'optional response')
            trigger['prompt']=(trigger.get('prompt') or f'Choose whether to use {response}.')+f' During {acting.display_name}’s {action.display_name}; decision for {affected.display_name}.'
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
        return ReactionDecision(checkpoint=key[0],reactor_id=key[1],reaction_source_id=key[2],
            selection='USE',spend=min(request.get('spend_options') or [0]),
            option_ids=tuple(request.get('legal_option_ids',[])[:1])),None
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
        roster_setup={'defer_first_turn':True,'defer_initiative':True,'nonterminal_resolution':True,'primary_actor_ids':list(actors),'team_by_actor':{aid:'scene' for aid in actors},
            'starting_positions':{aid:row['position'] for aid,row in actors.items()}})
    # Ordinary persisted health and physical conditions are inputs, not heals.
    from .journey_equipment import context
    physical=context(session)
    for aid,actor in native.state.actors.items():
        saved=ext.transform('journey_snapshot_actor',physical.state.actors[aid],session,aid,native)
        actor.current_hp=saved.current_hp;actor.active=saved.active;actor.life_state=saved.life_state
        actor.temporary_hp=saved.temporary_hp
        actor.turn_flags=deepcopy(saved.turn_flags)
        actor.reaction_available=bool(actors[aid].get('scene_reaction_available',1))
        for iid,c in saved.conditions.items():
            if iid not in actor.conditions:actor.conditions[iid]=c.model_copy(deep=True)
        turn=actors[aid].get('source_turn')
        actor.action_available=bool(not turn or (turn['active'] and turn['action']))
        actor.bonus_action_available=bool(not turn or (turn['active'] and turn['bonus_action']))
        # Journey conditions are ordinary combat conditions and must affect the
        # transient resolver exactly as they do at encounter entry.
        if actors[aid].get('incapacitated'):
            native._apply_condition(actor,'incapacitated','journey:condition_snapshot',aid,
                                    expires_on='UNTIL_REMOVED',data={'label':'Incapacitated'})
        exhaustion=int(actors[aid].get('exhaustion',0))
        if exhaustion:
            from .ext.forged_exhaustion import add,level
            delta=exhaustion-level(actor)
            if delta>0:add(native,actor,delta,'journey:condition_snapshot')
    native.typed_control_modes={aid:row['control_mode'] for aid,row in actors.items()}
    native.typed_ask_reactors={aid for aid,mode in native.typed_control_modes.items() if mode=='MANUAL'}
    native.set_reaction_provider(choice_provider(session,native))
    # A scene has no combat team assignment. An explicitly admitted offensive
    # command can target another creature even before an encounter is declared;
    # this does not invent enemy relations or share the actor's knowledge.
    for key,action in list(native.action_catalog.items()):
        if action.target_kind=='HOSTILE_ENTITY':
            native.action_catalog[key]=action.model_copy(update={'target_kind':'ANY_CREATURE',
                'parameters':{**action.parameters,'scene_other_creature':1}})
    return native


def candidates(native,aid,action):
    """All native candidates, including source gates and exact physical routes."""
    actor=native.state.actors[aid]
    return [c for c in native._action_candidates(actor,action)
        if not (action.parameters.get('scene_other_creature') and aid in c.target_ids)
        if False not in ext.run_strict('candidate_allowed',native,actor,c,action)]


def commit(session,native,aid,action,candidate,choices):
    """Resolve and validate settlement privately before publishing any payment.

    Generic health/permanent damage consequences use encounter_snapshot; timed
    effects require an owning continuation provider. Unsupported results reject
    atomically, with no scene payment, receipt or state change.
    """
    from .ext.needle import declared_choices
    from .ext.journey_turns import pay
    from .journey import JourneySession
    original=session
    session=JourneySession(deepcopy(original.state))
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
            native.resolve_accepted_action(native.state.actors[aid],action,candidate,intent)
    finally:
        for name,value in previous.items():setattr(native,name,value)
    from .journey_assets import JourneyAssetContext
    from .ext.journey_setup import encounter_snapshot,encounter_incapacitated
    for subject,actor in native.state.actors.items():
        row=session.state['actors'][subject]
        row['position']=actor.position.model_dump(mode='json');row['resources']=dict(actor.resources)
        physical=ext.transform('journey_snapshot_actor',actor,session,subject,native)
        row['encounter_snapshot']=encounter_snapshot(physical)
        # Ordinary damage settlement cannot clear a separately declared travel
        # incapacitation. Recovery still requires its existing explicit command.
        row['incapacitated']=int(row['incapacitated'] or encounter_incapacitated(row['encounter_snapshot']))
        ext.run_strict('journey_resolution_settled',session,subject,native,actor)
    objects=JourneyAssetContext(session)
    for obj in native.state.objects.values():
        objects._update_object(obj,'system:scene.native_resolution',aid)
    for event in native.events[start:]:
        # The authoritative receipt is retained privately; source view providers
        # never project this internal native journal to another controller.
        session.emit('SOURCE_NATIVE_RESOLVED',aid,native=event.model_dump_json(exclude_none=True))
    original.state=session.state
    return True
