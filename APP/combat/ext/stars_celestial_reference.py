"""Explicit GM celestial-reference adjudication for Stars' Open Sky rule.

The rule names references the GM must accept. This is a typed description of
that external fact, never a declaration of an attack, hit, mark or ownership.
The native position and match bind it to where the reference is available.
Unknown, expired, rejected or differently located references grant nothing.
"""
from . import hook

SOURCE = 'tianxia.sphere.stars'
KIND = 'open_sky_reference'
SCOPE = 'open-sky'
REFERENCES = frozenset(('direct_sky', 'clear_window', 'courtyard', 'cave_mouth',
    'skylight', 'mirror_pool', 'astral_projection', 'observatory_lens'))


def owns_stars(engine, subject):
    """Actual compiled Stars ownership; declarations cannot grant the sphere."""
    from .stars import row
    actor = engine.state.actors.get(subject)
    return actor is not None and row(engine, actor, 'starbolt') is not None


@hook('fact_admission_schema')
def celestial_schema(context, source, subject, kind):
    if source != SOURCE or kind != KIND:
        return None
    if not getattr(context, 'is_combat_fact_context', False) or not owns_stars(context.engine, subject):
        return None
    return {'value_type': 'document', 'authority': 'table_owner', 'combat': True,
        'validate_value': True, 'maximum_seconds': 86400,
        'description': 'Open Sky: name the celestial reference available at this creature’s current location, '
            'and whether the GM accepts it. Clouds, smoke and daylight do not automatically remove Open Sky.'}


@hook('fact_admission_value')
def celestial_value(context, payload):
    if payload.get('source') != SOURCE or payload.get('kind') != KIND:
        return None
    if not getattr(context, 'is_combat_fact_context', False):
        return False
    actor = context.engine.state.actors.get(payload.get('subject'))
    value = payload.get('value')
    return (actor is not None and owns_stars(context.engine, actor.entity_id)
        and payload.get('scope') == SCOPE and isinstance(value, dict)
        and set(value) == {'reference_kind', 'reference_name', 'accepted', 'position'}
        and type(value['reference_kind']) is str and value['reference_kind'] in REFERENCES
        and type(value['reference_name']) is str and bool(value['reference_name'].strip())
        and len(value['reference_name']) <= 500
        and type(value['accepted']) is int and value['accepted'] in (0, 1)
        and value['position'] == actor.position.model_dump(mode='json'))


def open_sky(engine, actor):
    """Only the subject's latest live, location-bound accepted GM reference."""
    if not owns_stars(engine, actor.entity_id):
        return False
    from ..fact_consent_admission import combat_records
    return any(record['subject'] == actor.entity_id and record.get('authority') == 'table_owner'
        and record['value']['accepted'] == 1
        and record['value']['position'] == actor.position.model_dump(mode='json')
        for record in combat_records(engine, actor, source=SOURCE, kind=KIND, scope=SCOPE))
