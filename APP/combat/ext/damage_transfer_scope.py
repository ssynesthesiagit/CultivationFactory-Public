"""Nonrecursive recipient-damage scope shared by damage_sharing and protection.

Wrap both recipient defense evaluation and its damage commit. A transferred
packet has already had its source adjusted, and cannot be redirected again.
Only transient engine state is used; nested calls and choice pauses restore it.
Defense evaluation is bound to its recipient and parent packet. Commitment
uses the existing pending-damage source flag; unrelated fresh packets remain
eligible, including counter-damage to the same recipient during the scope.
The already-defended bypass is likewise bound to the committed share by a
depth-specific source flag, so nested fresh damage receives its own defenses.
"""
from contextlib import contextmanager


NONRECURSIVE_TRANSFER = "nonrecursive_transfer"


def transfers_allowed(engine, recipient):
    """Whether the current packet may receive source adjustments and transfers."""
    from ..pending_damage import current

    packet = current(engine)
    if packet is not None and packet.target_id == recipient.entity_id and NONRECURSIVE_TRANSFER in packet.source_flags:
        return False
    defense = getattr(engine, "_nonrecursive_transfer_defense", None)
    return not (defense is not None and defense[0] == recipient.entity_id and defense[1] is packet)


@contextmanager
def nonrecursive_transfer(engine, recipient):
    """Suppress further transfers; yield source flags for this defended share."""
    from ..pending_damage import current

    previous = getattr(engine, "_nonrecursive_transfer_defense", None)
    depth = previous[2] + 1 if previous is not None else 1
    defended_flag = f"already_defended_packet:{depth}"
    engine._nonrecursive_transfer_defense = (recipient.entity_id, current(engine), depth, defended_flag)
    try:
        yield (NONRECURSIVE_TRANSFER, defended_flag)
    finally:
        engine._nonrecursive_transfer_defense = previous


def already_defended_packet(engine, recipient):
    """Bind a scoped defense bypass to its share; preserve unscoped legacy callers."""
    from ..pending_damage import current

    scope = getattr(engine, "_nonrecursive_transfer_defense", None)
    packet = current(engine)
    if scope is None or scope[0] != recipient.entity_id or packet is None:
        return True
    return packet.target_id == recipient.entity_id and scope[3] in packet.source_flags
