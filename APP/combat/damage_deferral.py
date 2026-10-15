"""Post-reduction packet deferral; shared by delayed-damage pool providers.

The engine calls this once after combining every final reduction and HP floor,
before Temporary HP or HP is spent. Providers record their own deferred pool
and its expiry through ordinary events. This module never creates a pool.
"""
from dataclasses import dataclass, replace

from . import ext
from .damage_context import AttackDamage


@dataclass(frozen=True)
class DamageToCommit:
    amount: int
    damage_type: str
    source_id: str
    source_actor_id: str
    target_id: str
    attack: AttackDamage | None


def apply(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    """Subtract each strict provider's bounded deferred amount sequentially.

    Later providers see only damage not already held. Attack provenance is the
    confirmed, immutable native context; an intentless/non-attack packet has no
    invented attack. Errors and player-choice pauses unwind the transaction.
    """
    packet = DamageToCommit(amount, damage_type, source_id, source_actor_id,
                            target.entity_id, engine.damage_context())
    for provider in ext.subscribers("damage_deferral"):
        if not packet.amount:
            break
        held = provider(engine, target, packet, intent)
        if held is None:
            continue
        if type(held) is not int or not 0 <= held <= packet.amount:
            raise ValueError("damage_deferral must return a bounded integer deferred amount")
        packet = replace(packet, amount=packet.amount - held)
    return packet.amount
