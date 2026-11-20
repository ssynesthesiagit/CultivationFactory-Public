"""Final damage decisions shared by native commitment and typed responses.

Reduction and allocation stay in their native owners. This module only answers
whether the remaining packet permits a zero-HP substitution; it never pays,
prompts, heals, or changes a damage value. Typed reactions, Preserving Yin and
Standard Cannot Fall share the packet gate and the reviewed per-row requirement.
"""
from .damage_allocation import lethal_threshold
from .pending_damage import current


def replacement_requirement(row):
    """Require the reviewed trigger fact, including an explicit False."""
    value = row.get('requires_not_killed_outright')
    if type(value) is not bool:
        raise ValueError(f"Zero-HP substitution {row.get('feature_id') or row.get('name') or ''} "
                         "requires boolean requires_not_killed_outright")
    return value


def replacement_allowed(engine, target, amount, source_actor_id, *, source_id=None, damage_type=''):
    """Packet-wide bans, before choosing any substitution row."""
    from .typed_reactions import _death_prevention_denied
    packet = current(engine)
    if (target.current_hp <= 0 or target.maximum_hp <= 0
            or _death_prevention_denied(target)
            or packet is not None and packet.source_flags.intersection({
                'no_zero_hp_substitution', 'total_bodily_destruction', 'instant_death'})):
        return False
    source_id = source_id if source_id is not None else packet.source_id if packet else None
    damage_type = damage_type or (packet.damage_type if packet else '')
    hp_loss = lethal_threshold(engine, target, amount, source_actor_id,
                              source_id=source_id, damage_type=damage_type)
    return target.current_hp <= hp_loss


def row_replacement_allowed(engine, target, amount, source_actor_id, row, *, source_id=None, damage_type=''):
    """Apply one substitution's printed outright-death requirement to this packet.

    Native would_drop providers and typed final/standalone checkpoints use the
    same engine massive threshold, after actual Temporary HP allocation.
    """
    requires_survival = replacement_requirement(row)
    if not replacement_allowed(engine, target, amount, source_actor_id,
                               source_id=source_id, damage_type=damage_type):
        return False
    if not requires_survival:
        return True
    packet = current(engine)
    source_id = source_id if source_id is not None else packet.source_id if packet else None
    damage_type = damage_type or (packet.damage_type if packet else '')
    hp_loss = lethal_threshold(engine, target, amount, source_actor_id,
                              source_id=source_id, damage_type=damage_type)
    from .ext.life_state import massive
    return hp_loss < target.current_hp + massive(engine, target)
