"""Empirical Tracker targets a real, perceived physical sign, not its creature.

The explicit empirical_tracker source profile seals creature_id and age_seconds.
Old evidence needs the admitted
unusually_clear=1 ruling. A source's current position, roster name, plans and
unrelated traits are never a result. The native object targeting route owns
range/LoS/LoE; native Analyze owns economy, Focus and attempt limits.
"""
from . import hook, effect
from .. import source_objects

FEATURE = 'TAL_THE_HIDDEN_EYE_EMPIRICAL_TRACKER'
PROFILE = 'empirical_tracker'
FLAG = 'empirical_evidence'


def evidence(engine, obj):
    data = source_objects.profile(obj, PROFILE)
    age = source_objects.age_seconds(engine, obj, data)
    if obj.destroyed or age is None or (age > 86400 and data.get('unusually_clear') != 1):
        return None
    target = engine.state.actors.get(data.get('creature_id'))
    if target is None:
        return None  # an unresolved identity never becomes a guessed roster match
    return {'target': target, 'source': data}


@hook('compile_basic_actions')
def evidence_action(info):
    """Adapt the finished native Analyze catalog, including owned economy variants."""
    if FEATURE not in info['owned_ids']:
        return None
    out=[]
    for action in info['actions']:
        effects = (action.parameters.get('typed') or {}).get('effects') or []
        if action.target_kind != 'HOSTILE_ENTITY' or not any(e.get('type') == 'analyze_check' for e in effects):
            continue
        typed={**action.parameters['typed'],'effects':[{'type':FLAG}]}
        out.append(action.model_copy(update={
            'source_definition_id': action.source_definition_id+'.evidence',
            'display_name': action.display_name+' physical evidence (Empirical Tracker)',
            'target_kind': 'OBJECT', 'parameters':{**action.parameters,'typed':typed,FLAG:1,
                                                  'analyze_source_id':action.source_definition_id,
                                                  # This adapter runs the complete native choice pipeline for AI too.
                                                  'player_only':False}}))
    return out or None


@hook('object_targets')
def evidence_targets(engine, actor, action):
    if not (getattr(action,'parameters',None) or {}).get(FLAG):
        return None
    from .eye_common import has
    if not has(engine,actor.entity_id,PROFILE):
        return []
    return [obj.object_id for obj in engine.state.objects.values() if evidence(engine,obj)]


@hook('candidate_allowed')
def evidence_allowed(engine,actor,candidate,action):
    if not (getattr(action,'parameters',None) or {}).get(FLAG):
        return None
    obj=engine.state.objects.get(next(iter(candidate.target_ids),None))
    data=evidence(engine,obj) if obj is not None else None
    if data is None:
        return False
    from .riders14_eye import attempts_left
    return attempts_left(engine,actor,data['target'])


@effect(FLAG)
def object_only(ctx,row):
    """The native object action owns this effect; never apply it to a creature."""
    raise ValueError('Empirical Tracker requires its qualified physical-evidence object route')


@hook('object_action')
def analyze_evidence(engine, actor, action, obj, candidate, intent):
    if not (action.parameters or {}).get(FLAG):
        return None
    data=evidence(engine,obj)
    if data is None:
        raise ValueError('This object has no fresh, qualified physical evidence')
    from .mind_hidden_eye import analyze_result
    from .riders14_eye import attempts_left, chosen_analyze_roll
    from ..typed_executor import Context
    target=data['target']
    if not attempts_left(engine,actor,target):
        return True
    # The check's subject is described by its sign. No source location/name
    # is imported into the approach prompt or resulting information.
    label='the creature that left this physical evidence'
    roll=chosen_analyze_roll(engine,actor,target,subject_label=label,subject_record_id=obj.object_id)
    ctx=Context(engine,actor,action,intent,(action.parameters or {}).get('typed') or {},[target],target,{})
    analyze_result(ctx,roll,target,subject_label=label,subject_record_id=obj.object_id)
    return True
