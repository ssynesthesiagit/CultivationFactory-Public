"""Explicit bodily-effect provenance, shared by cleansing and injury defenses.

Reviewed condition rows opt in with ``bodily_effect``. The applied condition
stores the source's CL and a validated primitive profile, never guesses anatomy
from a condition name or damage type. Bone Monarch consumes the retained profile;
ordinary_physical holds keep their existing public classifier. Unclassified
effects remain unclassified. This module grants no Injury from ordinary damage.
"""
from . import hook

CAUSES = frozenset({'broken_bone', 'crushed_limb', 'physical_binding', 'bodily_deformation',
                    'physical_injury', 'physical_paralysis', 'forced_bodily_transformation',
                    'body_breaking', 'body_liquefaction', 'psychic', 'spiritual', 'spatial',
                    'oath', 'conceptual'})
PHYSICAL = CAUSES - {'psychic', 'spiritual', 'spatial', 'oath', 'conceptual'}


def validate(profile):
    """Validate source-declared anatomy semantics; unknown fields fail closed."""
    if (not isinstance(profile, dict) or set(profile) - {'cause', 'temporary', 'speed_reduction_ft',
            'permanent_broken_bone', 'hidden', 'foundation', 'soul', 'identity'}
            or profile.get('cause') not in CAUSES):
        raise ValueError('A bodily effect needs a printed cause and supported bodily-harm fields.')
    for key, value in profile.items():
        if key != 'cause' and (type(value) is not int or value < 0
                or key != 'speed_reduction_ft' and value not in (0, 1)):
            raise ValueError('Bodily effect flags and Speed reductions use nonnegative integers.')
    return dict(profile)


def profile(condition, *, engine=None, actor=None):
    value = (condition.data or {}).get('bodily_effect')
    if value is not None:
        return validate(value)
    if engine is None or actor is None or not hasattr(engine, 'events'):
        return {}
    # The table owner records the exact instance, not a name-based inference.
    # Audience, correction and expiry are supplied by the public fact journal.
    from ..table_facts import records
    source_cl = (condition.data or {}).get('source_cl')
    action = engine.action_catalog.get(condition.source_definition_id)
    if source_cl is None and action is not None:
        source_cl = (action.parameters.get('typed') or {}).get('numbers', {}).get('cl')
    causes = set()
    for fact in records(engine, viewer=actor).values():
        answer = fact.answers.get('bodily_effect.cause')
        if (fact.subject_kind != 'creature' or fact.subject_id != actor.entity_id
                or fact.source_reference != condition.source_definition_id or answer is None
                or answer.condition != condition.instance_id or answer.category not in CAUSES
                or source_cl is None or answer.source_cl != source_cl):
            continue
        causes.add(answer.category)
    # Conflicting declarations need an owner correction, never import-order
    # precedence. An explicit printed profile above cannot be overridden.
    return {'cause': next(iter(causes))} if len(causes) == 1 else {}


def physical_temporary(condition):
    value = profile(condition)
    return (value.get('cause') in PHYSICAL and value.get('temporary') == 1
            and not any(value.get(key) for key in ('hidden', 'foundation', 'soul', 'identity')))


def speed_reduced(engine, actor, condition):
    """An actual native Speed penalty, never an amount supplied by narration."""
    from ..motion import grouped_speed_penalty
    from ..typed_executor import condition_rule_instances
    if grouped_speed_penalty(engine, actor, condition) > 0:
        return True
    return any(c.instance_id == condition.instance_id and type(rule.get('speed_ft')) is int
               and rule['speed_ft'] < 0 for c, rule in condition_rule_instances(actor, engine=engine))


@hook('condition_state')
def retain_source(ctx, subject, effect):
    if 'bodily_effect' not in effect:
        return None
    value = validate(effect['bodily_effect'])
    return {'data': {'bodily_effect': value, 'source_cl': int(ctx.numbers['cl'])}}


def save_causes(effects):
    """Only the actual pending source branches establish bodily save categories."""
    from ..effect_harm import rows
    return {validate(row['bodily_effect'])['cause'] for row in rows(effects) if 'bodily_effect' in row}


def encounter_conditions(session, aid):
    """Actual native encounter conditions retained by journey continuation."""
    import json
    from ..gate2_runtime_models import ConditionInstance
    snapshot = session.state['actors'][aid].get('encounter_snapshot') or {}
    return {iid: ConditionInstance.model_validate(json.loads(row))
            for iid, row in snapshot.get('conditions', {}).items()}


@hook('fact_admission_schema')
def injury_declaration(session, source, subject, kind):
    if kind != 'bodily_effect' or subject not in session.state['actors']:
        return None
    if not any(c.source_definition_id == source for c in encounter_conditions(session, subject).values()):
        return None
    return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
            'validate': validate_admission,
            'description': 'Classify one already recorded bodily condition by its actual Source Rule. This cannot create an Injury or alter a printed effect.'}


def validate_admission(session, payload):
    admitted_profile(session, payload['source'], payload['subject'], payload['scope'], payload['value'])
    return True


def admitted_profile(session, source, aid, scope, value):
    """Validate a classification against the actual immutable source instance."""
    if set(value) != {'instance_id', 'source_cl', 'profile'} or value['instance_id'] != scope:
        raise ValueError('A bodily classification must bind its exact condition instance, Source CL and profile.')
    condition = encounter_conditions(session, aid).get(scope)
    if condition is None or condition.source_definition_id != source:
        raise ValueError('A bodily classification cannot invent a condition or change its source.')
    if type(value['source_cl']) is not int or value['source_cl'] < 1:
        raise ValueError('The bodily Source CL must be a positive integer.')
    known = (condition.data or {}).get('source_cl')
    if known is None:
        source_action = next((a for person in session.state['actors'].values()
                              for a in person['bundle']['action_catalog'] if a['source_definition_id'] == source), None)
        if source_action:
            known = (source_action.get('parameters', {}).get('typed') or {}).get('numbers', {}).get('cl')
    if known is not None and known != value['source_cl']:
        raise ValueError('A declaration cannot replace the condition’s recorded Source CL.')
    return {'instance_id': scope, 'source': source, 'source_cl': value['source_cl'],
            'profile': validate(value['profile'])}


@hook('journey_combat_bundle')
def declared_condition_profiles(bundle, session, aid):
    """Carry only valid, current, subject-visible GM classifications to combat."""
    from ..fact_consent_admission import KEY, read
    conditions = encounter_conditions(session, aid)
    profiles = []
    keys = {(r['source'], r['scope']) for r in session.state.get(KEY, [])
            if r['subject'] == aid and r['kind'] == 'bodily_effect'}
    for source, scope in sorted(keys):
        condition = conditions.get(scope)
        if condition is None or condition.source_definition_id != source:
            continue  # A cured or expired effect no longer needs classification.
        record = read(session, source, aid, 'bodily_effect', scope, aid)
        if record is None:
            continue
        profiles.append({**admitted_profile(session, source, aid, scope, record['value']), 'receipt_id': record['receipt_id']})
    return {**bundle, 'bodily_effect_declarations': profiles} if profiles else None


@hook('match_initialize', priority=100)
def import_declarations(engine):
    """Replayable metadata replacement of an existing condition, never a new harm."""
    from .effect_durations import apply_condition_preserving_clock
    for bundle in getattr(engine, 'typed_bundle_documents', []):
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for declared in bundle.get('bodily_effect_declarations', []):
            held = actor.conditions.get(declared['instance_id'])
            if held is None or held.source_definition_id != declared['source']:
                raise ValueError('The declared bodily effect no longer matches the native condition.')
            data = {**held.data, 'bodily_effect': validate(declared['profile']),
                    'source_cl': declared['source_cl'], 'bodily_declaration': declared['receipt_id']}
            engine._remove_condition_instance(actor, held.instance_id, held.source_definition_id)
            apply_condition_preserving_clock(engine, actor, held, held.condition_id, held.source_definition_id,
                held.source_actor_id, expires_on=held.expires_on, data=data)
