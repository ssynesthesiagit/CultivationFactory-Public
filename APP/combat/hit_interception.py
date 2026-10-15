"""Confirmed-hit recipient replacement, shared by protective interception rules.

A confirmed_hit_interception provider may set spec.confirmed_hit_recipient to a mapping with
target_id and source_id after its native movement, choice and payment. consume
validates the original attack's range and line of sight, records the replacement,
and returns the recipient. Core reuses the existing roll and applies damage and
on-hit effects to that creature. No declaration leaves the packet unchanged.
This is distinct from pre-roll redirection and from damage transfer.
"""


def consume(engine, attacker, target, spec):
    declaration = spec.pop('confirmed_hit_recipient', None)
    if declaration is None:
        return target
    from .ext.redirection import legal_target
    if not isinstance(declaration, dict) or not declaration.get('source_id'):
        raise ValueError('Hit interception requires a source and recipient')
    recipient = engine.state.actors.get(declaration.get('target_id'))
    if not legal_target(engine, attacker, recipient, spec.get('range_ft') or spec.get('reach_ft') or 5):
        raise ValueError('The same attack cannot legally target the interceptor')
    spec['resolved_target_id'] = recipient.entity_id
    spec.pop('declaration_cover', None)  # a previous recipient's granted cover cannot move onto the interceptor
    engine._append_event('PASSIVE_TRIGGERED', declaration['source_id'], actor_id=recipient.entity_id,
        target_ids=(target.entity_id,), payload={'attacker_id':attacker.entity_id,
            'recipient_id':recipient.entity_id, 'interception':1,
            'log':f'{recipient.display_name} takes the attack intended for {target.display_name}.'})
    return recipient
