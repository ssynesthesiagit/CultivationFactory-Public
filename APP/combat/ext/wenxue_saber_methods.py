"""Native once-only Saber Method learning choice and persistent continuation.

Sphere Compendium, Core Sabers Rules / Saber Methods: choose one when learning
the sphere. This records actual practice, not a hit-derived guess. Qualifying
weapon proficiency remains with the existing Saber-Line Method implementation.
Saber-Line Pressure consumes the public practices() query for Cruel Edge.
"""
from . import hook

SOURCE = 'tianxia.sphere.sabers'
METHOD = 'SABERS_BASE_SABER_LINE_METHOD'
KEY = SOURCE + ':method'
BLOCK = 'sabers_method_choice'
CONDITION = 'condition:typed.sabers.practiced_method'
METHODS = {
    'battlefield_dao': 'Battlefield Dao Method',
    'duan_dao_close_cut': 'Duan Dao Close-Cut Method',
    'execution_saber': 'Execution Saber Method',
    'cavalry_crescent': 'Cavalry Crescent Method',
    'cruel_edge': 'Cruel Edge Method',
}


@hook('compile_bundle')
def method_acquisition(bundle, info):
    """Actual sphere/base acquisition supplies only this source-choice marker."""
    spheres = (info['owner_sheet'].get('spheres_and_talents') or {}).get('sphere_record_ids') or []
    rows = bundle.get('typed_passives') or []
    if (SOURCE not in spheres and METHOD not in (info.get('owned_ids') or ())) or any(
            row.get('block') == BLOCK for row in rows):
        return bundle
    return {**bundle, 'typed_passives': [*rows, {'block': BLOCK, 'feature_id': METHOD}]}


def owns_bundle(bundle):
    return any(row.get('block') == BLOCK and row.get('feature_id') == METHOD
        for row in bundle.get('typed_passives', ()))


def selection(actor):
    return (actor.get('source_selections') or {}).get(KEY)


def valid_selection(value, actor_id):
    return (isinstance(value, dict) and set(value) == {'source', 'actor_id', 'method'}
        and value['source'] == SOURCE and value['actor_id'] == actor_id
        and type(value['method']) is str and value['method'] in METHODS)


@hook('journey_options')
def method_options(session, actor_id):
    actor = session.state['actors'][actor_id]
    if session.state['phase'] != 'travel' or not owns_bundle(actor['bundle']) or selection(actor) is not None:
        return []
    return [{'id': KEY + ':' + method, 'kind': 'source_selection',
        'payload': {'source': SOURCE, 'method': method},
        'label': f'Record {name} as the Saber Method you learned with the sphere. '
            'Choose one permanently; no Action, travel time or Qi cost.'}
        for method, name in METHODS.items()]


@hook('journey_command')
def learn_method(session, actor_id, kind, payload):
    if kind != 'source_selection' or not isinstance(payload, dict) or payload.get('source') != SOURCE:
        return None
    from ..journey import require
    actor = session.state['actors'][actor_id]
    require(session.state['phase'] == 'travel' and owns_bundle(actor['bundle']),
        'Only a creature that learned Sabers can choose its Saber Method outside combat.')
    require(selection(actor) is None, 'This creature already chose its Saber Method when learning Sabers.')
    require(set(payload) == {'source', 'method'} and type(payload['method']) is str
        and payload['method'] in METHODS, 'Choose one of the five printed Saber Methods.')
    value = {**payload, 'actor_id': actor_id}
    actor.setdefault('source_selections', {})[KEY] = value
    session.emit('SOURCE_SELECTION_COMMITTED', actor_id, source=SOURCE,
        method=payload['method'], label=f"{actor['name']} practices {METHODS[payload['method']]}.")
    return True


@hook('journey_combat_setup')
def method_continuation(session, actor_id):
    actor = session.state['actors'][actor_id]
    if not owns_bundle(actor['bundle']):
        return None
    from ..journey import require
    value = selection(actor)
    require(valid_selection(value, actor_id),
        'Choose the Saber Method learned with this sphere from the journey menu before entering combat.')
    return {'sabers_method': dict(value)}


@hook('match_initialize')
def method_in_combat(engine):
    for bundle in engine.typed_bundle_documents:
        value = (bundle.get('journey_setup') or {}).get('sabers_method')
        if value is None:
            continue
        actor = engine.state.actors.get(bundle['actor_id'])
        if not actor or not owns_bundle(bundle) or not valid_selection(value, actor.entity_id):
            raise ValueError('A Saber Method continuation requires its actual acquired owner and selection.')
        if not any(c.condition_id == CONDITION for c in actor.conditions.values()):
            engine._apply_condition(actor, CONDITION, METHOD, actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'method': value['method'],
                    'label': 'Practiced Saber Method: ' + METHODS[value['method']]})


def practices(engine, actor, method):
    """Read an actual owned, committed practice selection; unknown means false."""
    return (any(row.get('block') == BLOCK and row.get('feature_id') == METHOD
                for row in engine.typed_passive_rows.get(actor.entity_id, ()))
        and any(c.condition_id == CONDITION and c.source_actor_id == actor.entity_id
            and c.data.get('method') == method for c in actor.conditions.values()))
