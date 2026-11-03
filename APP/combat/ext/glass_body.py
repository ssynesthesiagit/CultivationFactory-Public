"""Glass-Bone Guard and Walking Pane Body on the documented compile/effect hooks.

The user explicitly tempers their body when choosing these benefits. The sealed
row records armor eligibility; benefits live on one condition with the same
deadline as Temper Glass Surface, and retempering replaces that selection.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .glass_refraction import give_mark, tempered
from .rider_choices import pick

GUARD = 'TAL_GLASS_GLASS_BONE_GUARD'
WALK = 'TAL_GLASS_WALKING_PANE_BODY'
TEMPER = 'GLASS_BASE_TEMPER_GLASS_SURFACE'
CONDITION = 'condition:typed.glass_body_guard'


@hook('compile_action')
def body_guard_action(action: Any, info: dict) -> Any:
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != TEMPER or GUARD not in info['owned_ids']:
        return None
    from ..armour import catalog

    armor = catalog()
    params = copy.deepcopy(action.parameters)
    params['typed']['effects'].append({
        'type': 'glass_body_guard', 'count': 2 if WALK in info['owned_ids'] else 1,
        'heavy': any(item.get('worn') and (armor.get(item.get('item_id')) or {}).get('armor_category') == 'heavy'
                     for item in (info.get('carrying') or {}).get('items') or []),
        'evidence': 'When you use Temper Glass Surface on your own body, choose one benefit; Walking Pane Body allows two.'})
    return action.model_copy(update={'parameters': params})


def benefits(actor: Any) -> set[str]:
    return {b for c in actor.conditions.values() if c.condition_id == CONDITION
            for b in (c.data or {}).get('benefits') or []}


@effect('glass_body_guard')
def body_guard(ctx: Any, row: dict) -> None:
    options = ['reduce', 'mark'] + ([] if row.get('heavy') else ['ac'])
    count = min(int(row.get('count') or 1), len(options))
    labels = {'ac': '+1 Armor Class while your body stays tempered',
              'reduce': 'Reduce the first physical damage each round by your Proficiency Bonus',
              'mark': 'Mark a hostile creature when it hits you with a melee attack'}
    chosen = pick(ctx.engine, ctx.actor, 'glass_body_guard', 'Glass-Bone Guard', options,
                  subject=ctx.actor, maximum=count, minimum=1, optional=True,
                  preferred=options[:count], labels=labels,
                  choose=f'Temper your body and choose up to {count} different benefits, or decline.',
                  automatic_options=options[:count])
    ctx.engine._remove_condition(ctx.actor, CONDITION, ctx.source)
    if chosen:
        ctx.engine._apply_condition(ctx.actor, CONDITION, ctx.source, ctx.actor.entity_id,
                                    expires_on=ctx.expires_on() or 'UNTIL_REMOVED',
                                    data={'benefits': chosen, 'pb': int(ctx.numbers.get('pb') or 2),
                                          'label': 'Glass-Bone Guard: ' + '; '.join(labels[b] for b in chosen)})


@hook('ac')
def body_guard_ac(engine: Any, actor: Any) -> int | None:
    return 1 if tempered(engine, actor) and 'ac' in benefits(actor) else None


@hook('final_damage')
def body_guard_reduction(engine: Any, target: Any, amount: int, damage_type: str,
                         source_id: str, source_actor_id: str, intent: Any) -> dict | None:
    if amount <= 0 or str(damage_type).upper() not in {'BLUDGEONING', 'PIERCING', 'SLASHING'} \
            or not tempered(engine, target) or 'reduce' not in benefits(target) \
            or target.turn_flags.get('glass_body_reduced_round') == engine.state.round_number:
        return None
    pb = next(int(c.data['pb']) for c in target.conditions.values() if c.condition_id == CONDITION)

    def used(applied: int) -> None:
        if applied > 0:
            target.turn_flags['glass_body_reduced_round'] = engine.state.round_number

    return {'reduction': min(amount, pb), 'settle': used}


@hook('after_hit')
def body_guard_mark(ctx: Any, target: Any, kind: str) -> None:
    notice = getattr(ctx, 'attack_notice', None)
    attack = getattr(ctx, 'attack_effect', None) or {}
    melee = bool(notice.melee) if notice is not None else (
        attack.get('attack_kind') in {'weapon_melee', 'cultivation_melee', 'unarmed', 'melee'}
        or (ctx.typed.get('range_ft') is None and attack.get('attack_kind') != 'ranged'))
    if target is not None and target.active and tempered(ctx.engine, target) \
            and 'mark' in benefits(target) and melee:
        give_mark(ctx.engine, target, ctx.actor, GUARD)
