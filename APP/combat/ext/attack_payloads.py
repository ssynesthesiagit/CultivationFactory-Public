"""Opted-in physical attack packet preparation using the existing native effects.

Ordinary top-level extra damage on a confirmed hit is part of that attack.
Nested saves, areas, conditions, named separate sources and explicit
separate_packet rows retain their own delivery. The native packet scope calls
this after the primary dice roll and before HP; every damage roll still belongs
to the ordinary executor. Prepared rows are consumed once, never rerolled by the
later on-hit pass. No native buffer subscriber means this path is entirely inert.
"""
from dataclasses import replace
from . import hook, effect_permitted

KEY = '_native_prepared_payload_rows'


@hook('attack_payload_prepare')
def prepare(ctx):
    from ..typed_executor import run_effects
    for row in (ctx.attack_effect or {}).get('on_hit', []):
        if (row.get('type') != 'damage' or row.get('weapon_damage') or row.get('separate_packet')
                or row.get('applies_to', 'target') not in ('target', 'targets')):
            continue
        local = replace(ctx, defer_damage_notifications=True, continue_after_defeat=True)
        if not effect_permitted(local, row, [ctx.target]):
            continue
        run_effects(local, [row])
        ctx.damage_cache.setdefault(KEY, set()).add(id(row))


@hook('effect_allowed')
def consume_prepared(ctx, row):
    if id(row) in ctx.damage_cache.get(KEY, ()) and not ctx.defer_damage_notifications:
        return False
    return None
