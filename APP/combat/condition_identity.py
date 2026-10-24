"""Opt-in identities for actual condition-backed manifestations.

Taiji's optional Domain Armament Anchor uses this contract. Other features may
bind an actual condition without creating an object, inventing HP or treating a
display name as identity. Bookkeeping-preserving mode changes retain the sealed
identity in condition data; removal and a fresh activation do not inherit it.
The native condition update event preserves provenance and cold replay.
"""
KEY = 'native_manifestation_identity'


def seal(engine, target, condition, source):
    from .canonical import canonical_sha256
    if target.conditions.get(condition.instance_id) is not condition:
        raise ValueError('Manifestation identity requires the actual live condition')
    identity = condition.data.get(KEY)
    if identity is None:
        identity = 'manifestation:' + canonical_sha256({'context': engine.state.match_id,
            'target': target.entity_id, 'instance': condition.instance_id})
        engine._update_condition_data(target, condition, {**condition.data, KEY: identity}, source)
    if type(identity) is not str or not identity:
        raise ValueError('A native manifestation identity must be nonempty text')
    return {'actor_id': target.entity_id, 'condition_id': condition.condition_id, 'identity': identity}


def live(engine, reference):
    if not isinstance(reference, dict) or set(reference) != {'actor_id', 'condition_id', 'identity'}:
        raise ValueError('A condition Anchor requires its exact sealed reference')
    actor = engine.state.actors.get(reference['actor_id'])
    return actor is not None and any(condition.condition_id == reference['condition_id']
        and condition.data.get(KEY) == reference['identity'] for condition in actor.conditions.values())
