"""Fatal Strike, sealed at compilation and delivered from a settled hit receipt."""
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from . import hook
from .needle import ask, checkpoint_id
from .sword_core import sword_attack

FATAL = 'TAL_SWORD_FATAL_STRIKE'
BLOCK = 'sword_second_pass'
USED = 'condition:typed.sword_fatal_strike_used'


@hook('compile_block')
def compile_fatal(block: str, spec: dict, row: dict, numbers: dict) -> list | None:
    if block != BLOCK or row['feature_id'] != FATAL:
        return None
    record = numbers.get('record') or {}
    effect = next((e for e in record.get('effects') or [] if e.get('type') == 'sword_fatal_strike'), None)
    if effect is None or numbers['cl'] < int(record.get('min_cl') or 15):
        return None
    return [{**row, 'choice_owner': True, 'effects': deepcopy(effect['effects']),
             'cost': deepcopy(record['cost']), 'numbers': {k: numbers[k] for k in ('pb', 'key_mod', 'cl')}}]


def owned(engine: Any, actor: Any) -> dict | None:
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get('block') == BLOCK and r.get('feature_id') == FATAL), None)


@hook('compile_actions')
def fatal_delivery(info: dict) -> list | None:
    """Seal a private delivery identity so defenses read the talent's sphere."""
    row = next((r for r in info['passives']
                if r.get('block') == BLOCK and r.get('feature_id') == FATAL), None)
    if row is None:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.sword_fatal_strike.damage",
        display_name='Fatal Strike damage', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=0,
        parameters={'sword_fatal_strike_delivery': True,
                    'typed': {'sphere': 'tianxia.sphere.sword', 'numbers': deepcopy(row['numbers']),
                              'effects': deepcopy(row['effects']), 'riders': [],
                              'duration': {'kind': 'instant'}}})]


@hook('candidate_allowed')
def private_delivery(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.parameters.get('sword_fatal_strike_delivery'):
        return False
    return None


@hook('hit_snapshot')
def fatal_snapshot(engine: Any, attacker: Any, target: Any, attack: Any, intent: Any) -> dict | None:
    """Sample Bloodied and the attacker's mark before this hit changes either."""
    if not owned(engine, attacker):
        return None
    action = engine.action_catalog.get(attack.source_id)
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    from ..typed_executor import bears_mark
    from ..target_knowledge import located
    from .needle import ai_controlled
    if ai_controlled(engine, attacker) and not located(engine, attacker, target):
        return None
    qualifies = (sword_attack(SimpleNamespace(engine=engine, actor=attacker, typed=typed, action=action))
                 and target.current_hp <= target.maximum_hp // 2
                 and bears_mark(target, attacker.entity_id, 'Sword Intent'))
    return {'sword_fatal_strike': {'eligible': bool(qualifies)}}


@hook('hit_final')
def fatal_hit(ctx: Any, target: Any, kind: str) -> None:
    """Optional payment on a qualifying hit, without using Action or Reaction."""
    row = owned(ctx.engine, ctx.actor)
    action = next((a for a in ctx.engine.action_catalog.values()
                   if a.owner_id == ctx.actor.entity_id and a.parameters.get('sword_fatal_strike_delivery')), None)
    if (row is None or action is None or not target.active
            or not (ctx.hit_snapshots.get('sword_fatal_strike') or {}).get('eligible')
            or any(c.condition_id == USED for c in ctx.actor.conditions.values())):
        return
    from ..typed_executor import CP_POOLS, run_effects
    from .needle import numbers_of

    from .choice_costs import Payment
    payments = {}
    for option in row['cost']:
        if len(option) != 1:
            continue
        part = option[0]
        pools = CP_POOLS if part['resource'] == 'cp' else ('resource:core.' + part['resource'],)
        for pool in pools:
            amount = int(part['amount'])
            if ctx.actor.resources.get(pool, 0) >= amount:
                payments[pool] = Payment(pool, amount)
    if not payments:
        return
    labels = {pool: 'Pay ' + payment.quote() for pool, payment in payments.items()}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'sword_fatal_strike', target.entity_id),
                 ctx.actor, 'choice:needle.sword_fatal_strike', list(payments), labels=labels,
                 allow_decline=True, target_id=target.entity_id, feature_id=FATAL, name='Fatal Strike',
                 prompt_context={'cost': ' or '.join(payment.quote() for payment in payments.values())},
                 prompt=f"Fatal Strike: your Sword attack hit {target.display_name}, already Bloodied (at half HP or less) "
                        "and bearing your Sword Intent. Pay 8 Cultivation Points, 8 Stamina or expend Martial Focus, "
                        "or decline. Add 6d10 Slashing or Force damage. Failed Constitution save: no healing or "
                        "ordinary regeneration until the end of your next turn. Successful save: healing is halved "
                        "until that end. Either result prevents Reactions until the start of your next turn. "
                        "This needs no Action or Reaction and can be used once per long rest (once in this fight).")
    if not chosen:
        return
    pool = chosen[0]
    payments[pool].pay(ctx.engine, ctx.actor, FATAL)
    ctx.engine._apply_condition(ctx.actor, USED, FATAL, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                               data={'label': 'Fatal Strike used: available again after a long rest'})
    # Preserve the actual confirmed attack's critical and damage provenance, but
    # read the talent owner's sealed DC even on an Opportunity Attack.
    typed = {**action.parameters['typed'],
             'numbers': numbers_of(ctx.engine, ctx.actor)}
    hit_cache = {key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)}
    child = ctx.on_hit_context(target, action=action, typed=typed, effect_source=FATAL, damage_cache=hit_cache)
    run_effects(child, deepcopy(row['effects']))
    ctx.damage_cache.update({key: value for key, value in hit_cache.items() if isinstance(key, str)})
