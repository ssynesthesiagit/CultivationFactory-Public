"""Native declaration intent transport; schemas/consumers own their Source Rules.

Private native admission records: no source schema means no behavior.
"""
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
    """Source-owner 7073de53 scene authority; declaration alone ends no scene."""
    if source!='system:journey.scene' or kind!='scene_end' or subject not in session.state['actors']:return None
    return {'value_type':'text','maximum_seconds':1,'authority':'table_owner',
        'description':'The native table owner records why this meaningful scene ended.'}
