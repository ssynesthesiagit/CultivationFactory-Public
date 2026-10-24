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
    from ..fact_consent_admission import CONDITION
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==CONDITION]


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


@hook('presentation_hidden_conditions')
def private_world_records(engine, actor):
    from ..combat_world_facts import HISTORY
    return [iid for iid, condition in actor.conditions.items() if condition.condition_id == HISTORY] or None


@hook('presentation_hidden_history_conditions')
def private_world_history(events):
    from ..combat_world_facts import HISTORY
    return [event.payload['instance_id'] for event in events if not isinstance(event, dict)
            and event.payload.get('condition_id') == HISTORY and event.payload.get('instance_id')] or None
