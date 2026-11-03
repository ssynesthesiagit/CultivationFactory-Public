"""Pure effect gates shared by typed execution and AI recovery estimates.

The caller owns activation-local damage_cache. Eligibility queries never mark a use,
open a menu, roll, emit events or invoke an effect. Typed execution also uses the
occurrence scope below to distinguish strikes without storing fight state.
"""
from contextlib import contextmanager


@contextmanager
def attack_damage_occurrence(ctx):
    """Scope one strike's child packets, including all recipients of a nested area save.

    Only activation-local cache entries are used. Nested strikes receive distinct integers;
    restoring the caller's occurrence keeps its remaining packets on the original roll.
    """
    previous = ctx.damage_cache.get('_damage_bonus_occurrence', 0)
    occurrence = int(ctx.damage_cache.get('_damage_bonus_counter', 0)) + 1
    ctx.damage_cache['_damage_bonus_counter'] = occurrence
    ctx.damage_cache['_damage_bonus_occurrence'] = occurrence
    try:
        yield
    finally:
        ctx.damage_cache['_damage_bonus_occurrence'] = previous


def damage_bonus_slot(ctx, effect):
    """Stage plus strike occurrence; area recipients within that occurrence share a roll."""
    return (effect.get('damage_bonus_stage'), ctx.damage_cache.get('_damage_bonus_occurrence', 0))


def modifier_key(effect):
    """Use clock shared by typed execution and recovery/term eligibility.

    Historical untyped gates keep their owner-turn reset; explicit per-turn
    gates use the native all-creature turn reset admitted in lock round 15.
    """
    gate = effect.get('modifier_once')
    return (f'typed_once_turn:modifier:{gate}' if effect.get('modifier_once_period') == 'turn'
            else f'typed_modifier_once:{gate}')


def damage_bonus_available(ctx, effect):
    """Optional compiler roll slot: stage and strike compete; area recipients share it.

    Used by typed effect dispatch and save-for-half's direct damage path. Absent metadata is
    inert. The string key survives the executor's between-hit cache copies, only for this use.
    """
    group = effect.get('damage_bonus_group')
    selected = ctx.damage_cache.get(f'damage_bonus_stage:{group}') if group else None
    return selected is None or selected == damage_bonus_slot(ctx, effect)


def eligible(ctx, effect, *, include_deferred=False):
    if not damage_bonus_available(ctx, effect):
        return False
    cl = int(ctx.numbers.get('cl') or 1)
    if effect.get('min_cl') and cl < int(effect['min_cl']):
        return False
    if effect.get('max_cl') is not None and cl > int(effect['max_cl']):
        return False
    if effect.get('menu') and effect.get('option') and effect.get('type') not in ('menu', 'menu_pick'):
        from .ext.menus import picked
        if not picked(ctx, effect):
            return False
    if effect.get('deferred'):
        return include_deferred  # execution registers watches before once gates
    gate = effect.get('modifier_once')
    if gate and effect.get('modifier_once_period') == 'owner_turn' and ctx.engine.state.current_actor_id != ctx.actor.entity_id:
        return False
    return not (gate and ctx.actor.turn_flags.get(modifier_key(effect))
                and not ctx.damage_cache.get(('modifier_once', gate)))
