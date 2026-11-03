"""Native fact transport and private projections; no source schema means no behavior."""
from copy import deepcopy

from . import hook, query


@hook('presentation_hidden_conditions')
def private_declarations(engine, actor):
    from ..fact_consent_admission import CONDITION
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == CONDITION]


@hook('journey_command')
def admission_command(session, actor_id, kind, payload):
    if kind != 'declare_fact':
        return None
    from ..fact_consent_admission import declare
    declare(session, actor_id, payload)
    return True


# Resolve source authority on the complete scene before other providers redact it.
@hook('journey_view', priority=-100)
def project_facts(state, viewer_id):
    if 'fact_consent_admission' not in state:
        return None
    from ..fact_consent_admission import KEY, read
    from ..journey import JourneySession

    out = deepcopy(state)
    history = out.pop(KEY)
    if viewer_id is None:
        return out
    session = JourneySession(state)
    identities = dict.fromkeys((r['source'], r['subject'], r['kind'], r['scope']) for r in history)
    visible = []
    for identity in identities:
        latest = max((r for r in history if (r['source'], r['subject'], r['kind'], r['scope']) == identity),
                     key=lambda r: int(r['sequence']))
        if latest['expires_at'] <= session.clock():
            continue
        # A source may cease to admit facts as its scene or ability expires.
        if not query('fact_admission_schema', session, *identity[:3]):
            continue
        record = read(session, *identity, viewer_id)
        if record is not None:
            visible.append(record)
    if visible:
        out[KEY] = visible
    return out
