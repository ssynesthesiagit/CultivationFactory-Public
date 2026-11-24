"""Public non-HP value settlement for typed resource loss and numeric healing penalties.

Consumers supply an actual integer outcome and its declared cause. This never
converts damage, boolean prohibitions, percentages or private facts into points.
Packets are ephemeral; only primitive settlement/cost receipts are evented.
"""
from dataclasses import dataclass
from . import ext
from .pending_damage import resources
from .resource_labels import resource_name

# Pressure kinds that reach this seam. Shared with the Devouring Return receiver
# (ext/foundation_combat.py) so both agree on what a reducible value is.
PRESSURE_KINDS = frozenset({'drain', 'origin_theft', 'healing_denied', 'source_corruption'})


def pressure_label(pressure_kind, value_id):
    """Player-facing name for a settled value, naming the drained resource.

    ``value_id`` is the resource id for drain/origin-theft/source-corruption
    pressure, and a non-resource id for numeric healing penalties.
    """
    if pressure_kind == 'healing_denied':
        return 'healing penalty'
    resource = resource_name(value_id)
    return {'drain': f'{resource} loss', 'origin_theft': f'origin theft of {resource}',
            'source_corruption': f'{resource} lost to source corruption'}[pressure_kind]


@dataclass(frozen=True)
class ScalarPressure:
    amount: int
    pressure_kind: str
    source_id: str
    source_actor_id: str
    target_id: str
    value_id: str
    cause: str
    hostile: bool
    source_wounded: bool
    event_sequence: int
    intent_id: str
    instance_id: str
    source_flags: frozenset[str]
    resources_before: tuple

    def resource_before(self, actor_id, resource_id):
        return dict(dict(self.resources_before).get(actor_id, ())).get(resource_id, 0)


def settle(engine, target, amount, *, pressure_kind, source_id, source_actor_id,
           value_id, cause, intent, source_flags=()):
    """Return the actual remaining value after strict, actor-signed reducers.

    Only positive represented values with public source/recipient/cause enter
    the seam. Nested calls carry independent frozen packets. A missing provider
    returns the original value with no event or cost. Pauses propagate to the
    enclosing accepted transaction for rollback/replay.
    """
    if type(amount) is not int or amount < 0:
        raise ValueError('Scalar pressure requires a nonnegative integer value')
    source = engine.state.actors.get(source_actor_id)
    flags = frozenset(source_flags)
    if any(not isinstance(flag, str) or not flag for flag in flags):
        raise ValueError('Scalar source flags must be public names')
    if (not amount or source is None or not source_id or not value_id or not cause
            or flags & {'private', 'self_cost', 'voluntary_overdraw', 'hidden_injury', 'breakthrough_backlash'}
            or intent is None or pressure_kind not in PRESSURE_KINDS):
        return amount
    intent_id = str(getattr(intent, 'intent_id', '') or '')
    instance_id = ':'.join((intent_id, str(engine.state.event_sequence), source_actor_id,
                            target.entity_id, value_id))
    packet = ScalarPressure(amount, pressure_kind, source_id, source_actor_id,
        target.entity_id, value_id, cause, source.team_id != target.team_id,
        source.current_hp < source.maximum_hp, engine.state.event_sequence,
        intent_id, instance_id, flags, resources(engine))
    remaining = amount
    seen = set()
    for receipt in ext.run_checkpoint('scalar_pressure_pending', engine, packet, intent):
        if (not isinstance(receipt, dict) or set(receipt) !=
                {'actor_id', 'source_id', 'reduction', 'resource_id', 'resource_spent', 'reaction_spent'}
                or receipt['actor_id'] not in engine.state.actors
                or receipt['actor_id'] in seen or not isinstance(receipt['source_id'], str)
                or type(receipt['reduction']) is not int or receipt['reduction'] < 0
                or not isinstance(receipt['resource_id'], str)
                or type(receipt['resource_spent']) is not int or receipt['resource_spent'] < 0
                or type(receipt['reaction_spent']) is not bool):
            raise ext.CheckpointError('Scalar reducer requires one primitive actor-signed cost receipt')
        seen.add(receipt['actor_id'])
        reduction = min(remaining, receipt['reduction'])
        remaining -= reduction
        # The existing non-mutating history envelope is supported by cold
        # persistence. Actual resource/modifier consumers event their own state.
        label = pressure_label(pressure_kind, value_id)
        ext.note(engine, receipt['source_id'], receipt['actor_id'],
            f'{target.display_name}: hostile {label} reduced from {remaining + reduction} to {remaining}.',
            targets=(target,), **{
                **receipt, 'receipt_kind': 'scalar_pressure_reduced',
                'reduction': reduction, 'pressure_kind': pressure_kind,
                'hostile_source_id': source_id, 'hostile_source_actor_id': source_actor_id,
                'value_id': value_id, 'cause': cause, 'value_before': remaining + reduction,
                'value_after': remaining, 'trigger_sequence': packet.event_sequence,
                'intent_id': packet.intent_id, 'instance_id': instance_id,
                'source_flags': sorted(flags)})
    return remaining
