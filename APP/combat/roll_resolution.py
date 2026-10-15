"""Public roll phases shared by native and typed committed attacks.

No subscriber means no state, event, extra draw or targeting change. The
existing native resolver owns the roll and outcome. Subscribers may resolve
ordinary transactional choices, and return a strike-local AC contribution and
request same-target geometry revalidation. No reply can retarget an attack.
"""
from . import ext


def visible_attack(engine, attacker, target, spec, roll, intent):
    bonus, revalidate = 0, False
    for reply in ext.run_strict('attack_roll_visible', engine, attacker, target, spec, roll, intent):
        if (not isinstance(reply, dict) or set(reply) - {'ac_bonus', 'revalidate_target'}
                or type(reply.get('ac_bonus', 0)) is not int
                or type(reply.get('revalidate_target', False)) is not bool):
            raise ValueError('attack_roll_visible requires integer ac_bonus and boolean revalidate_target')
        bonus += reply.get('ac_bonus', 0)
        revalidate |= reply.get('revalidate_target', False)
    return bonus, revalidate
