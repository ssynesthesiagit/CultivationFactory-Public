"""Native journey transport and viewer projection for source-scoped facts.

Uses combat.fact_consent_admission for validation, persistence and replay.
No source schema means declarations are rejected and unrelated journeys are inert.
"""
from copy import deepcopy

from . import hook


@hook('journey_command')
def declare_fact(session, actor_id, kind, payload):
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
    from . import query

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
