"""Source-specific external projection/contact facts for Earth and Puppetry.

The native GM admission path records an actual breakthrough or a required
connected-surface ruling, with source provenance. It grants no acquisition,
learned feature, item, or general projection. Combat receives a sealed snapshot;
subsequent source edits cannot change a saved fight or its replay.
"""
from copy import deepcopy
from . import hook
from ..journey import require
EARTH = ('EARTH_BASE_SET_FOUNDATION', 'EARTH_BASE_WEIGHT_SEEKING_CLOD')
PUPPET = 'PUPPETRY_BASE_THREAD_THE_OBJECT'


@hook('journey_admission')
def admit(session, aid, kind, payload, reason):
    if kind not in ('projection_permission', 'earth_connection_policy'):
        return None
    actor = session.state['actors'][aid]
    if kind == 'projection_permission':
        require(set(payload) == {'feature', 'objects', 'breakthrough'} and payload['feature'] in (*EARTH, PUPPET)
                and isinstance(payload['objects'], list) and payload['objects']
                and all(isinstance(o, str) and o for o in payload['objects'])
                and isinstance(payload['breakthrough'], str) and payload['breakthrough'].strip(),
                'Record the exact feature, permitted objects (or *), and the actual projection breakthrough.')
        actor.setdefault('physical_source_facts', {}).setdefault('projection', {})[payload['feature']] = {
            'objects': list(dict.fromkeys(payload['objects'])), 'breakthrough': payload['breakthrough'], 'provenance': reason}
    else:
        require(set(payload) == {'required'} and type(payload['required']) is int and payload['required'] in (0, 1),
                'Record whether this scene requires a connected surface for body-originating Earth attacks.')
        actor.setdefault('physical_source_facts', {})['earth_connection_required'] = payload['required']
    session.emit('PHYSICAL_SOURCE_FACT_ADMITTED', aid, kind_of_fact=kind, reason=reason)
    return True


@hook('journey_combat_setup')
def snapshot(bundle, session, aid):
    facts = session.state['actors'][aid].get('physical_source_facts')
    if not facts:
        return None
    return {**bundle, 'physical_source_facts': deepcopy(facts)}


def facts(engine, aid):
    return next((b.get('physical_source_facts', {}) for b in engine.typed_bundle_documents if b.get('actor_id') == aid), {})


def projected(engine, aid, feature, object_id='*'):
    """Public, sealed permission query. A known talent name is never permission."""
    row = facts(engine, aid).get('projection', {}).get(feature)
    return bool(row and ('*' in row['objects'] or object_id in row['objects']))


@hook('journey_view')
def private(state, viewer_id):
    if not any('physical_source_facts' in a for a in state['actors'].values()):
        return None
    out = deepcopy(state)
    out.pop('replay_base', None); out.pop('command_journal', None)
    for aid, actor in out['actors'].items():
        if aid != viewer_id:
            actor.pop('physical_source_facts', None)
    return out
