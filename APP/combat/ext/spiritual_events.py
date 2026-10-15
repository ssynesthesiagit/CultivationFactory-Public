"""Causal committed-event groups for Equal Measure and lineage observers.

Uses paid_relocation's public activation accounting, including independent
reactions and continuation riders. The transient sequence index contains no
game facts or decisions; those come only from the actual committed events.
The general transaction_settled phase includes linked falls and aftermath.
"""
from . import hook
from ..paid_relocation import current_activation, capture, preserve_pending

TRACK = '_spiritual_event_groups'
TYPES = {'DAMAGE_COMMITTED', 'MOVEMENT_COMMITTED', 'CONDITION_APPLIED', 'SAVE_ROLLED', 'CHECK_ROLLED', 'INTENT_ACCEPTED'}


@hook('activation_accounting')
def accounting(engine):
    return True if any(str(r.get('feature_id', '')).startswith((
        'tianxia.tradition.spirit.equal_measure_scripture.feature.',
        'tianxia.tradition.spirit.ancestral_channeler.feature.'))
        for rows in getattr(engine, 'typed_passive_rows', {}).values() for r in rows) else None


@hook('event', nested=True)
def observe(engine, event_type, kwargs):
    from ..movement_steps import is_denial_event
    event = kwargs.get('originating_event')
    if (event_type not in TYPES and (event is None or not is_denial_event(event))) or not accounting(engine):
        return
    owner = current_activation(engine)
    if owner is None or owner.actor_id is None or event is None:
        return
    preserve_pending(engine, TRACK)
    records = dict(getattr(engine, TRACK, {}))
    # The public opaque receipt distinguishes two independent activations of
    # the same source by the same actor. Do not merge their qualifying harm.
    # It stays transient, like the native retained aftermath ownership itself.
    key = (capture(engine), owner.actor_id, owner.source_id)
    records[key] = [*records.get(key, []), event.sequence]
    setattr(engine, TRACK, records)


def completed(engine):
    """Actual source-owned activations, in first-event order, for this transaction."""
    by_sequence = {e.sequence: e for e in engine.events}
    groups = []
    for (_receipt, actor_id, source), sequences in getattr(engine, TRACK, {}).items():
        events = [by_sequence[s] for s in sequences if s in by_sequence]
        if events:
            groups.append((actor_id, source, events))
    return sorted(groups, key=lambda g: g[2][0].sequence)


@hook('transaction_settled', priority=100)
def clear(engine, actor_id, source):
    if hasattr(engine, TRACK):
        preserve_pending(engine, TRACK)
        setattr(engine, TRACK, {})
