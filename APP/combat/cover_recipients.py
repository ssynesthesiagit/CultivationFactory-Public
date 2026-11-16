"""Default-inert cover-caused attack recipient replacement using one drawn roll.

Providers own the cover rule. The native resolver validates the new creature's
reach, sight and effect line, retains the original die and modifiers, and runs
ordinary defenses/damage against that recipient. No recursive redirection.
"""
from . import ext


def recipient(engine, attacker, target, spec, roll, intent, total, cover):
    """Validate the single recipient offered after miss correction/replacement.

    The caller checks for a cover-only miss; providers establish causation by
    removing only their own cover, retaining independent defenses.
    Typed specs may carry recipient_reach_check(actor) -> bool to preserve the
    declaration's reach semantics. Other specs use the native reach maximum.
    """
    answers = ext.run_strict('cover_miss_recipient', engine, attacker, target, spec, roll, intent, total, cover)
    if not answers:
        return None
    if any(not isinstance(answer, str) for answer in answers) or len(set(answers)) != 1:
        raise ValueError('cover_miss_recipient requires one agreed creature id or None')
    other = engine.state.actors.get(answers[0])
    from .targeting import attack_line_of_effect
    from .attack_reach import spec_maximum
    reach_check = spec.get('recipient_reach_check')
    if reach_check is not None and not callable(reach_check):
        raise ValueError('recipient_reach_check must be callable')
    if (other is None or not other.active or other is target or other is attacker
            or not engine._line_of_sight_actor_to_actor(attacker, other)
            or not attack_line_of_effect(engine, attacker, other, spec['source_definition_id'])
            or not (reach_check(other) if reach_check is not None else
                    engine._effect_distance(attacker, other) <=
                    spec_maximum(engine, attacker, spec['source_definition_id'], spec))):
        raise ValueError('A cover recipient must be a different active creature legally reached by this attack')
    return other
