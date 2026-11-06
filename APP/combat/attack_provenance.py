"""Pure delivery descriptors shared by attack defense, tactical cover and wall cover.

Only the resolving packet (or an explicitly supplied catalogue action for a
preview) is authoritative. Range is never evidence of weapon delivery. These
immutable query values are transient and never enter a fight's saved state.
"""
from collections.abc import Mapping
from types import MappingProxyType
from .weapon_delivery import delivery_kind, weapon_identity


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def describe(engine, actor, spec, source_id=None):
    """Describe the actual spec without d20_context, a scope, or any mutation."""
    source = source_id or spec.get('source_definition_id')
    delivering_source = spec.get('source_definition_id') or source
    action = engine.action_catalog.get(delivering_source)
    parameters = spec.get('parameters')
    if parameters is None:
        parameters = action.parameters if action else {}
    typed = spec.get('typed')
    if typed is None:
        typed = parameters.get('typed') or {}
    effect = (spec.get('checkpoint_context') or {}).get('effect')
    # Native actions may retain typed equipment metadata, but not a particular
    # effect: never substitute the first effect for the actual resolving one.
    delivery = delivery_kind(typed, effect, parameters)
    opportunity = typed.get('opportunity_of') or parameters.get('opportunity_of')
    explicit = any(typed.get(key) or parameters.get(key) for key in ('weapon_source_id', 'delivered_by', 'opportunity_of'))
    identity = weapon_identity(engine, delivering_source, typed, parameters) if delivery == 'weapon' or explicit else None
    return _freeze({'source_id': source, 'delivering_source_id': delivering_source, 'actor_id': actor.entity_id,
                    'parameters': parameters, 'typed': typed, 'effect': effect,
                    'ranged': spec.get('range_ft') is not None,
                    'range_ft': spec.get('range_ft'), 'reach_ft': spec.get('reach_ft'),
                    'delivery': delivery,
                    'weapon_source_id': str(identity).split('#', 1)[0] if identity else None,
                    'opportunity_of': opportunity})


def ranged_attacks(engine, actor):
    """Known possessed ranged attacks, independent of current turn economy.

    Disabled/dropped weapons are excluded. Mixed typed actions supply one
    descriptor per attack effect; no candidate generation or defense recursion.
    """
    disabled = {c.data.get('disables_action') for c in actor.conditions.values()}
    held = {c.data.get('disables_action') for a in engine.state.actors.values()
            for c in a.conditions.values() if c.data.get('held_by') == actor.entity_id}
    for source in actor.action_ids:
        action = engine.action_catalog.get(source)
        if action is None or action.range_ft is None or source.split('#', 1)[0] in disabled:
            continue
        required = action.parameters.get('requires_held_weapon')
        if required and required not in held:
            continue
        typed = action.parameters.get('typed') or {}
        # Catalogue range is also used for melee reach. Delivery follows the
        # actual typed packet; retain catalogue long range for threat distance.
        if action.resolution_kind == 'TYPED' and typed.get('range_ft') is None:
            continue
        effects = [e for e in typed.get('effects') or () if e.get('type') == 'attack']
        if action.resolution_kind != 'TYPED':
            effects = [None] if action.resolution_kind == 'ATTACK' else []
        for effect in effects:
            yield describe(engine, actor, {'parameters': action.parameters,
                'range_ft': action.range_ft, 'reach_ft': action.reach_ft,
                'checkpoint_context': {'effect': effect}}, source)
