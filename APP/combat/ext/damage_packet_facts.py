"""Shared packet receipt provenance for Jigoku and other damage-event consumers.

No ability is granted here. Producers seal damage_source_flags on their typed
action or pass source_flags for one packet; native receipts preserve those
primitive facts so post-resolution consumers do not guess a source's intent.
"""
from . import hook
from ..pending_damage import current


@hook('damage_receipt_facts')
def receipt_flags(engine, target, source_id, source_actor_id):
    packet = current(engine)
    if packet is None or not packet.source_flags:
        return None
    return {'source_flags': sorted(packet.source_flags)}
