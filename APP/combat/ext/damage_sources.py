"""Explicit packet provenance for source-qualified guards and pressure consumers.

Typed damage/attack producers may declare ``source_flags`` on the actual effect
row. The existing effect scope carries them into native PendingDamage, just as
native producers pass source_flags to _commit_damage. Never infer categories
from an action name, sphere, damage type, or another effect in the action.
Last Cinder Guard consumes these flags; future guards can use the same public
PendingDamage contract. Flags are transient and restored on nesting or pause.
"""
from contextlib import contextmanager

from . import hook


@contextmanager
def source_scope(ctx, flags):
    previous = ctx.damage_source_flags
    ctx.damage_source_flags = tuple(dict.fromkeys((*previous, *flags)))
    try:
        yield
    finally:
        ctx.damage_source_flags = previous


@hook('effect_resolution_scope')
def typed_source_flags(ctx, effect):
    if effect.get('type') not in {'attack', 'damage', 'extra_damage', 'half_damage'}:
        return None
    flags = effect.get('source_flags')
    if flags is None:
        return None
    if not isinstance(flags, (list, tuple)) or any(type(f) is not str or not f for f in flags):
        raise ValueError('Damage source_flags must be a list of nonempty names')
    return source_scope(ctx, flags)
