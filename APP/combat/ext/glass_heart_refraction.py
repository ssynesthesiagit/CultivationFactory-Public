"""Private scene admission for the existing Glass Heart Refraction provider.

The owner/GM records scene facts and the bearer's actual declaration. Neither
damage, teams, names nor a model's guess establish scene importance or intent.
This module adds no Reflection grant or positive numerical combat benefit.
"""
from . import hook
from ..table_facts import records

SOURCE = 'foundation.glass_heart_meridian_v0_2A.perfected_glass_heart_refraction'
SCENES = {'Major combat', 'Emotionally decisive scene', 'Neither'}


def owned_action(engine, actor_id):
    return next((a for a in engine.action_catalog.values() if a.owner_id == actor_id
                 and (a.parameters.get('typed') or {}).get('source') == SOURCE), None)


@hook('table_source_inputs')
def scene_forms(engine):
    return [{'source_id': SOURCE, 'actor_id': a.entity_id,
             'label': f'{a.display_name}: Glass Heart Refraction',
             'description': 'Owner/GM: record the scene being entered and the character’s actual choice. '
                'This private declaration costs nothing. Activation then costs a Bonus Action and 2 CP '
                '(your Path resource), once per long rest, for 1 minute. Reflection maximum stays 1; '
                'Reflection cannot pay for the event that created it.',
             'fields': [
                 {'name': 'scene', 'label': 'Scene being entered', 'options': sorted(SCENES)},
                 {'name': 'clarity', 'label': 'The character chooses transparent clarity instead of hiding '
                    'behind beauty, denial, or reflection', 'options': ['Yes', 'No']},
                 {'name': 'reason', 'label': 'Private scene and declaration details', 'options': []}]} 
            for a in engine.state.actors.values() if owned_action(engine, a.entity_id)] or None


@hook('table_source_document')
def scene_document(engine, source_id, actor_id, values):
    if source_id != SOURCE:
        return None
    actor = engine.state.actors.get(actor_id)
    if actor is None or owned_action(engine, actor_id) is None:
        raise ValueError('Only a character with Perfected Glass Heart Refraction can declare it.')
    if (set(values) != {'scene', 'clarity', 'reason'}
            or not all(isinstance(v, str) for v in values.values()) or values['scene'] not in SCENES
            or values['clarity'] not in {'Yes', 'No'} or not isinstance(values['reason'], str)
            or not 1 <= len(values['reason'].strip()) <= 2000):
        raise ValueError('Choose the actual scene, the character’s clarity decision, and private details.')
    return {'record_id': SOURCE + ':' + actor_id, 'subject_id': actor_id,
            'subject_name': actor.display_name, 'subject_kind': 'creature',
            'position': actor.position.model_dump(mode='json'),
            'source_reference': values['reason'].strip(), 'witness_ids': [actor_id],
            'valid_through_round': engine.state.round_number,
            'answers': {'glass_refraction': {'fact': values['scene'], 'category': values['clarity'],
                'visible_sign': 'Private owner declaration', 'source_cl': 0}}}


@hook('table_fact_validate')
def validate_scene(engine, fact):
    answer = fact.answers.get('glass_refraction')
    if answer is None:
        return
    if (owned_action(engine, fact.subject_id) is None
            or fact.record_id != SOURCE + ':' + fact.subject_id
            or fact.valid_through_round != engine.state.round_number
            or fact.witness_ids != (fact.subject_id,)
            or answer.fact not in SCENES or answer.category not in {'Yes', 'No'}):
        raise ValueError('Refraction needs this bearer’s current, private entry declaration.')


@hook('candidate_allowed')
def admitted(engine, actor, candidate, action):
    if action is None or (action.parameters.get('typed') or {}).get('source') != SOURCE:
        return None
    fact = records(engine, actor).get(SOURCE + ':' + actor.entity_id)
    answer = fact.answers.get('glass_refraction') if fact else None
    return bool(answer and answer.fact in SCENES - {'Neither'} and answer.category == 'Yes')


@hook('journey_rest')
def long_rest(session, actor_id):
    """Native eight-hour recipient rest restores only this owned use counter."""
    actor = session.state['actors'][actor_id]
    bundle = actor['bundle']
    maxima = {r['resource_id']: int(r['maximum']) for r in bundle['actor_template']['resources']}
    for action in bundle.get('action_catalog') or []:
        if ((action.get('parameters') or {}).get('typed') or {}).get('source') != SOURCE:
            continue
        rid = 'resource:uses.' + action['source_definition_id']
        if rid in actor['resources'] and rid in maxima:
            actor['resources'][rid] = maxima[rid]
