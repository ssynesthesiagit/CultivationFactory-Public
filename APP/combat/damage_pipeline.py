"""Final damage decisions shared by native commitment and typed responses.

Reduction and allocation stay in their native owners. This module only answers
whether the remaining packet permits a zero-HP substitution; it never pays,
prompts, heals, or changes a damage value.
"""
from .damage_allocation import lethal_threshold
from .pending_damage import current


def replacement_allowed(engine, target, amount, source_actor_id, *, source_id=None, damage_type=''):
    """Read the final packet, including Temporary HP bypass and explicit bans.

    Native commitment and typed zero-HP responses use the same result. An
    instant-death packet is not an ordinary drop to zero. Non-damage death and
    a maximum HP of zero cannot enter this substitution window.
    """
    from .typed_reactions import _death_prevention_denied
    packet = current(engine)
    if (target.current_hp <= 0 or target.maximum_hp <= 0
            or _death_prevention_denied(target)
            or packet is not None and (packet.pressure_kind != 'damage'
                or packet.source_flags.intersection({
                    'no_zero_hp_substitution', 'total_bodily_destruction', 'instant_death'}))):
        return False
    hp_loss = lethal_threshold(engine, target, amount, source_actor_id,
                              source_id=source_id, damage_type=damage_type)
    return target.current_hp <= hp_loss < target.current_hp + target.maximum_hp
