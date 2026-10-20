"""Packet provenance that is never ordinary hostile harm.

Who uses this: phoenix_rebirth (Ember gain) and black_thorn_demon_body (Demon Spine gain).
Damage that the recipient chose, trained for, inflicted on itself, farmed as a
resource, or paid as a feature's cost does not count as hostile harm, whatever
team its source is on. The packet's source_flags carry this provenance.
"""

NON_HOSTILE_PROVENANCE = frozenset({"voluntary", "training", "self_inflicted", "resource_farming", "feature_cost"})


def excluded_by_provenance(packet) -> bool:
    """True when the in-flight damage packet carries a non-hostile provenance flag. No packet means no exclusion."""
    return bool(packet is not None and packet.source_flags & NON_HOSTILE_PROVENANCE)
