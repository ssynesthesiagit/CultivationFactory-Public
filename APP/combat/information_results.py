"""Pure observer-only information transport used by perception and decision contexts.

Providers project only facts their observer is entitled to learn. Results never
enter team observations, targeting, public events or the underlying actor roster.
"""
from . import ext


def for_observer(engine, observer):
    results = []
    for rows in ext.run_strict('observer_information', engine, observer):
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError('observer_information must return a list of fact dictionaries')
        results.extend(rows)
    return results


def describe(engine, observer, facts):
    """Plain own-observer findings for the table and model-seat consumers.

    Resolve references only through this observer's sight. Never expose source
    keys, unknown fact fields or a hidden creature's identity/position. The
    categorical vocabulary is shared; ability predicates remain in providers.
    Unknown kinds have no presentation until they define a safe description.
    """
    from .senses import ordinary_sight_perceives, perceives_object

    def reference(value, fallback):
        actor = engine.state.actors.get(value)
        if actor is not None:
            return actor.display_name if ordinary_sight_perceives(engine, observer, actor) else fallback
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
        # Retained observer envelopes have their own renderer and nested fact
        # vocabulary. A private supernatural direction is not the top-level
        # sensory "direction" finding about a Bloodied creature.
        if 'viewer_id' in fact and isinstance(fact.get('details'), dict):
            continue
        kind = fact.get('kind')
        direction = fact.get('direction')
        where = ('here' if direction == 'here' else 'to the ' + direction
                 if direction in {'north', 'south', 'east', 'west', 'northeast',
                                  'northwest', 'southeast', 'southwest'} else 'nearby')
        line = None
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
