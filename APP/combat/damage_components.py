"""Same-packet damage accounting for native attacks and typed paid hit riders.

Consumers: Gate2 damage delivery and attack_reduction's flat-reduction budgets.
Only opted-in mixed packets install balances; ordinary packets are unchanged.
Balances are transient integer/type data in the existing pending packet scope.
"""
from .pending_damage import packet_scratch


def grouped(amount, damage_type, components):
    """Validate all pre-rolled additions before defenses mutate any state."""
    result = {str(damage_type).upper(): max(0, amount)}
    for row in components:
        if (not isinstance(row, dict) or type(row.get('amount')) is not int or row['amount'] < 0
                or not isinstance(row.get('damage_type'), str) or not row['damage_type'].strip()):
            raise ValueError('damage components require nonnegative integer amounts and named types')
        kind = row['damage_type'].upper()
        result[kind] = result.get(kind, 0) + row['amount']
    return result


def begin(engine, values):
    scratch = packet_scratch(engine)
    if scratch is not None:
        scratch['damage_components'] = dict(values)


def remaining(engine):
    return (packet_scratch(engine) or {}).get('damage_components')


def reduce(engine, actor, amount, allowed=()):
    """Spend a reduction on eligible live types, asking the damaged owner for order.

    Returns the amount actually reduced, or None for the ordinary packet path.
    AI uses the same complete options with the ordinary deterministic preference.
    """
    balances = remaining(engine)
    if balances is None:
        return None
    kinds = [kind for kind, value in balances.items() if value > 0 and (not allowed or kind in allowed)]
    if len(kinds) > 1 and 0 < amount < sum(balances[kind] for kind in kinds):
        from .pending_damage import current
        from .ext.needle import ask, checkpoint_id
        packet = current(engine)
        action = engine.action_catalog.get(packet.source_id)
        action_name = action.display_name if action is not None else 'the incoming hit'
        kinds = ask(engine, getattr(engine, '_active_intent', None),
            checkpoint_id(engine, 'damage_components', str(packet.event_sequence), str(sum(balances.values()))),
            actor, 'choice:damage_components.reduction_order', kinds,
            minimum=len(kinds), maximum=len(kinds), labels={kind: kind.title() for kind in kinds},
            prompt=f'Damage reduction against {action_name}: {actor.display_name}, choose the damage types to reduce first.')
    left = max(0, amount)
    for kind in kinds:
        taken = min(left, balances[kind])
        balances[kind] -= taken
        left -= taken
    return max(0, amount) - left


def settle(engine, actor, pending):
    """Allocate any final flat reductions, returning positive applied type receipts."""
    balances = remaining(engine)
    if balances is None:
        return []
    reduce(engine, actor, max(0, sum(balances.values()) - pending))
    return [{'damage_type': kind, 'applied': value} for kind, value in balances.items()]


def applied_types(payload):
    """Positive committed types; a canceled component never becomes a trigger."""
    if 'components' in payload:
        return {row['damage_type'] for row in payload['components'] if row.get('applied', 0) > 0}
    return {str(payload.get('damage_type') or '').upper()}


def declared_types(payload):
    """Types actually committed in one packet, including fully prevented types."""
    if 'components' in payload:
        return {row['damage_type'] for row in payload['components']}
    return {str(payload.get('damage_type') or 'UNTYPED').upper()}
