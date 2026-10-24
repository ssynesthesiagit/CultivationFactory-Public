"""Transactional packet context shared by reaction ranking and numeric responses.

Devouring Return and other source-sensitive reductions consume this contract.
Contexts and query caches are ephemeral; only consumers' ordinary events/state
are persisted. Nested packets restore the enclosing context, including on pause.
``packet_scratch`` is that same nesting for per-packet bookkeeping: it holds only
what one packet's own resolution may read, never fight state.
``attack_packet_start`` is the strict pre-defense component seam used by
Thousand-Hunger Adaptation and available to other attached attack damage types.
It runs before the primary packet snapshots, so nested bonus HP/resource changes
are reflected in that packet's context without altering attack provenance.
``damage_origin`` is the producer's generic provenance name (for example
``ongoing`` for a recurring typed effect). It travels on the in-flight packet and
is copied into that packet's DAMAGE_COMMITTED payload, so every event subscriber
sees it at delivery time rather than after the commit returns. A producer names it once, where the packet is
created. Only a split or shared portion of that same delivery copies it, through ``portion_origin``; a reaction
that deals a new blow while the packet happens to be in flight does not, and nothing else sets it.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace

from . import ext


@dataclass(frozen=True)
class PendingDamage:
    amount: int
    damage_type: str
    pressure_kind: str
    source_id: str
    source_actor_id: str | None
    target_id: str
    hostile: bool
    source_wounded: bool
    source_flags: frozenset[str]
    event_sequence: int
    transaction_id: str | None
    resources_before: tuple
    hp_before: int
    # Generic provenance for a packet produced by a recurring typed effect ("ongoing"), so a
    # damage subscriber can tell it apart from a fresh blow while the packet is still in flight.
    damage_origin: str | None = None

    def resource_before(self, actor_id, resource_id):
        return dict(dict(self.resources_before).get(actor_id, ())).get(resource_id, 0)


def resources(engine):
    return tuple((a.entity_id, tuple(sorted(a.resources.items()))) for a in engine.state.actors.values())


def current(engine):
    """Current immutable damage/drain context, or None outside its transaction."""
    return getattr(engine, '_pending_damage_context', None)


def portion_origin(engine):
    """The origin a split or shared portion of the in-flight packet keeps.

    Only the sites that move part of the very delivery in flight call this: Take the Blow, Community, Guardian Knot,
    Shelter Beneath the Tusks and Subvert Harm. A reaction that deals a new blow while a packet is being delivered
    does not, so it is classified by its own producer (normally as a fresh blow).
    """
    parent = current(engine)
    return parent.damage_origin if parent is not None else None


def packet_scratch(engine):
    """Transient scratch shared by everyone reading the damage packet in flight.

    ``scope`` installs an empty one for every packet and restores the enclosing
    packet's on the way out, so a nested packet starts empty and a return to the
    enclosing packet finds its own entries exactly as it left them. Keys belong to
    the caller. Scratch lives and dies with its packet and is never saved, so it
    holds in-flight values only, never fight state.
    """
    return getattr(engine, '_pending_damage_scratch', None)


@contextmanager
def scope(engine, target, amount, damage_type, source_id, source_actor_id, *, pressure_kind='damage', source_flags=(),
          damage_origin: str | None = None):
    if type(amount) is not int or not isinstance(pressure_kind, str) or not pressure_kind:
        raise ValueError('Pending damage requires an integer amount and a named pressure kind')
    if any(not isinstance(flag, str) or not flag for flag in source_flags):
        raise ValueError('Pending damage source flags must be names')
    if damage_origin is not None and (not isinstance(damage_origin, str) or not damage_origin):
        raise ValueError('Pending damage origin must be a non-empty name')
    attack = engine.damage_context()
    if attack is not None and (attack.source_id, attack.attacker_id, attack.target_id) == (
            source_id, source_actor_id, target.entity_id):
        # Strict, pre-defense component delivery. Capture the pending packet only
        # afterwards: an attached component may have changed HP or resources.
        ext.run_strict('attack_packet_start', engine, target, amount, attack)
    source = engine.state.actors.get(source_actor_id)
    packet = PendingDamage(max(0, amount), str(damage_type), pressure_kind, source_id, source_actor_id,
        target.entity_id, bool(source and source.team_id != target.team_id),
        bool(source and source.current_hp < source.maximum_hp), frozenset(source_flags),
        engine.state.event_sequence, getattr(engine, '_transaction_id', None), resources(engine), target.current_hp,
        damage_origin)
    previous = (current(engine), getattr(engine, '_pending_damage_answers', None), packet_scratch(engine))
    engine._pending_damage_context, engine._pending_damage_answers, engine._pending_damage_scratch = packet, {}, {}
    try:
        yield packet
    finally:
        engine._pending_damage_context, engine._pending_damage_answers, engine._pending_damage_scratch = previous


def prepare(engine, pending, intent):
    """Run strict opt-in queries once, before ranking, consent or numeric use.

    A provider may ask/record a classification, but cannot mutate the packet.
    False eligibility wins; flat nonnegative reduction bonuses add. An absent
    provider introduces no event, reaction, cost, or damage change.
    """
    packet = current(engine)
    if packet is None:
        return
    packet = replace(packet, amount=pending)
    engine._pending_damage_context = packet
    if not ext.has('damage_context_pending_reaction_rank'):
        return
    for actor_id, rows in sorted(getattr(engine, 'typed_reaction_rows', {}).items()):
        reactor = engine.state.actors.get(actor_id)
        if reactor is None:
            continue
        for row in rows:
            if row.get('block') != 'generic' or row.get('kind') not in {'damaged', 'ally_damaged', 'bloodied', 'drop_to_zero', 'ally_drop_to_zero'}:
                continue
            allowed, bonus = True, 0
            for answer in ext.run_checkpoint('damage_context_pending_reaction_rank', engine, reactor, row, packet, intent):
                if not isinstance(answer, dict) or set(answer) - {'allowed', 'reduction_bonus'}:
                    raise ext.CheckpointError('Damage reaction query must return eligibility and/or a reduction bonus')
                yes, extra = answer.get('allowed', True), answer.get('reduction_bonus', 0)
                if type(yes) is not bool or type(extra) is not int or extra < 0:
                    raise ext.CheckpointError('Damage reaction query requires boolean eligibility and a nonnegative integer bonus')
                allowed, bonus = allowed and yes, bonus + extra
            engine._pending_damage_answers[id(row)] = (allowed, bonus)


def answer(engine, row):
    return (getattr(engine, '_pending_damage_answers', None) or {}).get(id(row), (True, 0))
