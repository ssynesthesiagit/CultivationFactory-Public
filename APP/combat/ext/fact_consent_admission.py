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
    from ..fact_consent_admission import CONDITION,GM_CONTEXT
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in {CONDITION,GM_CONTEXT}]


@hook('technique_accepted')
def context_declaration_producer(engine,actor,action):
    from ..fact_consent_admission import commit_context_facts
    commit_context_facts(engine,actor,action)


@hook('history_event_metadata')
def private_fact_history(event,events):
    from ..fact_consent_admission import CONDITION,GM_CONTEXT
    if event.get('event_type') in {'CONDITION_APPLIED','CONDITION_REMOVED'} and (event.get('payload') or {}).get('condition_id') in {CONDITION,GM_CONTEXT}:
        return {'history_hidden':True}
    return None
