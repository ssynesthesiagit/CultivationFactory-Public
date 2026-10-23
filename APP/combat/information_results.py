"""Pure observer-only information transport used by perception and decision contexts.

Providers project only facts their observer is entitled to learn. Results never
enter team observations, targeting, public events or the underlying actor roster.
"""
from . import ext


def record_private(engine, observer, source, feature, kind, key, public, *, identity=None):
    """Journal an owner-only learned record, optionally with private identity.

    Used by Appraise findings/profiles; other information providers can retain
    learned observations through the same native commit/replay transport. This
    is a producer API, never an intent input or a grant of revelation authority.
    The owning provider supplies an allowlisted public projection. Internal
    identity stays in the authoritative journal and is never returned by the
    observer projection or recent-events context. None retires an exact key.
    """
    from .canonical import canonical_sha256
    if observer.entity_id not in engine.state.actors or not all(
            isinstance(v, str) and v for v in (feature, kind, key)):
        raise ValueError('A private observation requires its owner and stable source identity')
    record = {'owner': observer.entity_id, 'feature': feature, 'kind': kind,
              'key': key, 'public': public, 'identity': identity or {}}
    canonical_sha256(record)
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=observer.entity_id,
                         payload={'history_hidden': 1, 'private_information': record})


def private_records(engine, observer, feature, kind):
    """Latest live value per owner/source/key; pure, cold-reload-safe query."""
    records = {}
    for event in engine.events:
        row = event.payload.get('private_information') or {}
        if (row.get('owner'), row.get('feature'), row.get('kind')) != (observer.entity_id, feature, kind):
            continue
        if row.get('public') is None:
            records.pop(row['key'], None)
        else:
            records[row['key']] = row
    return records


def for_observer(engine, observer):
    results = []
    for rows in ext.run_strict('observer_information', engine, observer):
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError('observer_information must return a list of fact dictionaries')
        results.extend(rows)
    return results


def creature_name(engine, observer, creature_id, fallback='The selected creature'):
    """Viewer-safe reference shared by information findings and Duel status cards.

    Pinpointing supplies a location, not a visible identity. Missing actors and
    unobserved identities use plain fallback prose, never raw persistent IDs.
    """
    from .senses import ordinary_sight_perceives
    actor = engine.state.actors.get(creature_id)
    if actor is not None and observer is not None and ordinary_sight_perceives(engine, observer, actor):
        return actor.display_name
    return fallback


def describe(engine, observer, facts):
    """Plain own-observer findings for the table and model-seat consumers.

    Resolve references only through this observer's sight. Never expose source
    keys, unknown fact fields or a hidden creature's identity/position. The
    categorical vocabulary is shared; ability predicates remain in providers.
    Unknown kinds have no presentation until they define a safe description.
    """
    from .senses import perceives_object

    def reference(value, fallback):
        actor = engine.state.actors.get(value)
        if actor is not None:
            return creature_name(engine, observer, value, fallback)
        obj = engine.state.objects.get(value)
        if obj is not None:
            from .object_rules import label
            return label(obj) if perceives_object(engine, observer, obj) else fallback
        # Providers may author public labels for unanchored visible sources.
        if str(value).startswith(('actor:', 'object:')):
            return fallback
        return str(value or fallback)

    lines = []
    for fact in facts:
        kind = fact.get('kind')
        direction = fact.get('direction')
        compass, _, vertical = str(direction).partition(' and ')
        where = ('here' if direction == 'here' else 'to the ' + compass
                 if compass in {'north', 'south', 'east', 'west', 'northeast',
                                'northwest', 'southeast', 'southwest'}
                 and vertical in {'', 'above', 'below'} else 'nearby')
        if direction in {'above', 'below'}:
            where = direction + ' you'
        elif where.startswith('to the ') and vertical:
            where += ', ' + vertical + ' you'
        line = None
        if isinstance(fact.get('text'), str):
            # Existing observer_information providers own permission and plain
            # wording. Their explicit text is never inferred from source IDs,
            # private identity or an arbitrary action/choice payload.
            lines.append(f"{fact.get('ability') or 'Observation'}: {fact['text']}")
            continue
        if kind == 'direction':
            line = f'A creature at half its maximum HP or less is {where}.'
        elif kind == 'injury':
            name = reference(fact.get('creature_id'), 'The visible creature')
            line = f'{name} is injured.' if fact.get('injured') else f'{name} is uninjured.'
        elif kind == 'recent_spill':
            line = f'Blood was spilled {where} within the last hour.'
        elif kind == 'corpse_cause':
            name = reference(fact.get('source'), 'The corpse')
            line = (f'{name} likely died from blood loss.' if fact.get('likely_blood_loss')
                    else f'{name} likely did not die from blood loss.')
        elif kind == 'sample_match':
            name = reference(fact.get('sample'), 'This blood sample')
            studied = reference(fact.get('studied_sample'), 'the previously studied sample')
            relation = 'the same creature as' if fact.get('same_creature') else 'a different creature from'
            line = f'{name} comes from {relation} {studied}, which you already studied.'
        if line:
            lines.append(f"{fact.get('ability') or 'Observation'}: {line}")
    return lines
