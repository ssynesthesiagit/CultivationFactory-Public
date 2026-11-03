"""Glass-Cutting Palm: explicit owned Insight, settled melee hit and modeled terrain contact.

No owner means no hook reply. Pure hit_snapshot receipts preserve actual-target
contact and Buried eligibility through damage; hit_final offers the earned bonus.
Native and portable hits use AttackNotice; typed hits retain delivery metadata.
The compiled row seals the
character's CL/PB/key modifier, including construction eligibility. The finalized
sheet already carries the level-selection Ability Increase.
"""
from dataclasses import replace
from . import hook
from .fight_ownership import block_rows
from .sand_terrain import standing_in, touching_created_glass

INSIGHT = 'insight.glass-cutting-palm'
BLOCK = 'sand_glass_palm'
USED = 'typed_once_turn:sand_glass_palm'


@hook('compile_block')
def compile_palm(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'pb': int(numbers.get('pb') or 0),
             'key_mod': int(numbers.get('key_mod') or 0), 'cl': int(numbers.get('cl') or 1)}]


@hook('hit_snapshot')
def palm_hit_snapshot(engine, actor, target, attack_context, intent):
    """Pure eligibility receipt from the actual confirmed hit, before its damage."""
    row = next((r for r in block_rows(engine, actor, BLOCK)
                if not r.get('held_back') and int(r.get('cl') or 1) >= 8), None)
    if row is None or actor.turn_flags.get(USED):
        return
    if not all(standing_in(engine, actor.entity_id, creature)
               or touching_created_glass(engine, actor.entity_id, creature)
               for creature in (actor, target)):
        return
    amount = int(row['pb'])
    if int(row['cl']) >= 15 and any(c.condition_id == 'condition:typed.buried' for c in target.conditions.values()):
        amount += int(row['key_mod'])
    return {BLOCK: {'attacker_id': actor.entity_id, 'target_id': target.entity_id, 'amount': amount}}


@hook('hit_final')
def glass_cutting_palm(ctx, target, kind):
    from ..attack_notifications import is_melee_hit
    from ..typed_executor import run_effects
    from ..weapon_delivery import delivery_kind
    from .needle import CHOICE, ask, checkpoint_id

    receipt = ctx.hit_snapshots.get(BLOCK) or {}
    delivery = delivery_kind(ctx.typed, getattr(ctx, 'attack_effect', None), ctx.action.parameters)
    if (receipt.get('attacker_id') != ctx.actor.entity_id or receipt.get('target_id') != target.entity_id
            or delivery not in ('weapon', 'unarmed') or not is_melee_hit(ctx) or ctx.actor.turn_flags.get(USED)):
        return
    amount = int(receipt['amount'])
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, BLOCK, ctx.source, target.entity_id), ctx.actor,
                 CHOICE + BLOCK, ['use'], allow_decline=True, preferred=['use'], target_id=target.entity_id,
                 name='Glass-Cutting Palm', feature_id=INSIGHT,
                 labels={'use': f'Add {amount} Piercing damage'},
                 prompt=f'Glass-Cutting Palm: your melee hit struck {target.display_name} while both of you were touching '
                        f'Sand Terrain or glass you created. Add {amount} Piercing damage? No extra Action, Reaction '
                        'or CP is needed. You may use this once per turn, including another creature’s turn.')
    if not chosen:
        return
    ctx.actor.turn_flags[USED] = True
    own = replace(ctx, targets=[target], target=target, effect_source=INSIGHT,
                  damage_cache={}, critical_hit=False)
    run_effects(own, [{'type': 'damage', 'applies_to': 'target', 'flat': amount, 'damage_types': ['piercing'],
                       'evidence': 'Glass-Cutting Palm: additional Piercing damage on a melee hit in your sand'}])
