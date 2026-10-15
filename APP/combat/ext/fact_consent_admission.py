"""Native declaration intent transport; schemas/consumers own their Source Rules."""
from . import hook
from ..fact_consent_admission import declare


@hook('journey_command')
def admission_command(session, actor_id, kind, payload):
    if kind != 'declare_fact':
        return None
    declare(session,actor_id,payload)
    return True


@hook('presentation_hidden_conditions')
def private_declarations(engine,actor):
    from ..fact_consent_admission import CONDITION, HEAD
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in (CONDITION, HEAD)]


@hook('journey_snapshot_actor')
def snapshot_admissions(actor, session, actor_id, engine):
    """Only metadata clocks are exported here; source mechanics remain intact."""
    from ..fact_consent_admission import CONDITION, HEAD
    if not any(c.condition_id in (CONDITION, HEAD) for c in actor.conditions.values()):
        return None
    result = actor.model_copy(deep=True)
    result.conditions = {k:c for k,c in result.conditions.items() if c.condition_id not in (CONDITION, HEAD)}
    return result


@hook('journey_encounter_settled')
def export_admissions(session, actor_id, engine, creature):
    """Rebase remaining time without rewriting the original signed receipt.

    Expired latest versions are retained as history, so an old journey consent
    cannot reappear after a refusal. Restoration never invokes source effects.
    """
    import json
    from ..fact_consent_admission import KEY, CONDITION, latest_conditions
    from .effect_durations import remaining_seconds
    from ..journey import require
    for condition in latest_conditions(creature):
        record = json.loads(condition.data['record'])
        live = next((c for c in creature.conditions.values() if c.condition_id == CONDITION
                     and json.loads(c.data['record'])['receipt_id'] == record['receipt_id']), None)
        remaining = 0
        if live is not None:
            remaining = remaining_seconds(engine, live.expires_on, source_actor_id=live.source_actor_id,
                                          holder_actor_id=creature.entity_id)
            require(remaining is not None,
                    'This source declaration uses a turn clock; its source must resolve or transport it before travel.')
        history = session.state.setdefault(KEY, [])
        history.append(record)
        expiry = session.clock() + remaining
        session.state.setdefault('fact_consent_deadlines', {})[record['receipt_id']] = [expiry.numerator, expiry.denominator]


@hook('journey_encounter_prepare')
def prepare_admissions(session, actor_id):
    from ..fact_consent_admission import KEY, identity, deadline
    latest = {}
    for record in session.state.get(KEY, []):
        if record['subject'] == actor_id:
            latest[identity(record)] = record
    rows = []
    for record in latest.values():
        remaining = max(0, deadline(session, record) - session.clock())
        from fractions import Fraction
        remaining = Fraction(remaining)
        rows.append({'record':record, 'remaining':[remaining.numerator, remaining.denominator]})
    bundle = session.state['actors'][actor_id]['bundle']
    if rows:
        bundle['fact_consent_transport'] = rows
    else:
        bundle.pop('fact_consent_transport', None)


@hook('match_initialize')
@hook('activity_initialize')
def restore_admissions(engine):
    from ..fact_consent_admission import commit_record
    from .effect_durations import expiry_after_seconds
    from fractions import Fraction
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for item in bundle.get('fact_consent_transport', []):
            remaining = Fraction(*item['remaining'])
            commit_record(engine, actor, item['record'], expiry_after_seconds(engine, remaining) if remaining > 0 else None)


@hook('fact_admission_schema')
def native_scene_owner_schema(session,source,subject,kind):
    """Second production consumer: the native table-owner scene boundary.

    This is system authority over this persisted scene, never a creature's
    ability grant or private consent. Merely declaring this fact cannot end the
    scene; JourneyStore.end_scene owns that mechanical operation.
    """
    if source!='system:journey.scene' or kind!='scene_end' or subject not in session.state['actors']:return None
    return {'value_type':'text','maximum_seconds':1,'authority':'table_owner',
        'description':'The native table owner records why this meaningful scene ended.'}
