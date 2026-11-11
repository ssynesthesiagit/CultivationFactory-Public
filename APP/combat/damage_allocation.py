"""Pure Temporary HP availability for a damage packet and its early drop checks."""

def available_temporary_hp(engine, target, amount, source_actor_id, *, source_id=None, damage_type=''):
    from . import ext
    if source_id is None:
        from .ext.damage_delivery import identity
        source_id = identity(engine)
    bypass = False
    for reply in ext.run_strict('damage_bypasses_temporary_hp', engine, target, amount, damage_type, source_id, source_actor_id):
        if type(reply) is not bool:
            raise ValueError('damage_bypasses_temporary_hp requires a boolean')
        bypass = bypass or reply
    return 0 if bypass else target.temporary_hp


def lethal_threshold(engine, target, amount, source_actor_id, *, source_id=None, damage_type=''):
    """Return HP damage after this packet's actual Temporary HP eligibility."""
    temporary = available_temporary_hp(engine, target, amount, source_actor_id,
                                       source_id=source_id, damage_type=damage_type)
    return max(0, amount - min(temporary, max(0, amount)))


def maximum_packet_before_hp_floor(engine, target, amount, floor, source_actor_id, *, source_id=None, damage_type=''):
    """Maximum packet size that leaves the target at ``floor`` HP."""
    temporary = available_temporary_hp(engine, target, amount,
                                       source_actor_id, source_id=source_id, damage_type=damage_type)
    return min(max(0, amount), temporary) + max(0, target.current_hp - floor)
