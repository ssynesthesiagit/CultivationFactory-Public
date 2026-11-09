"""Settled legacy attack notifications, using the existing typed hook contract."""
from copy import deepcopy
from dataclasses import dataclass
import json

from .gate2_runtime_models import ActionDefinition, EconomyKind


@dataclass(frozen=True)
class AttackNotice:
    source_id: str
    attacker_id: str
    target_id: str
    attack_index: int
    hit: bool
    melee: bool
    kind: str
    roll_id: str = ""
    opportunity: bool = False
    opportunity_trigger: str = ""


def is_melee_hit(ctx):
    """Read settled delivery metadata; distance never turns a ranged hit into melee.

    Native/portable notices state delivery explicitly. Typed profiles use no
    range_ft for melee (including reach weapons); ranged profiles retain range
    even when their selected target is adjacent. Unknown profiles return False.
    """
    notice = getattr(ctx, "attack_notice", None)
    if notice is not None:
        return bool(notice.hit and notice.melee)
    if not getattr(ctx, "attack_result", None):
        return False
    effect = getattr(ctx, "attack_effect", None) or {}
    if effect.get("attack_kind") == "ranged":
        return False
    return "range_ft" in ctx.typed and ctx.typed["range_ft"] is None


def capture(engine, actor, target, attack_context, intent):
    """Copy pure, namespaced hit-time receipts before any damage can remove their source.

    Used by native, typed and portable attacks. Receipts are transient JSON values,
    never callbacks or engine flags; nested attacks each own a separate copy.
    """
    from . import ext

    receipts = {}
    for reply in ext.run_strict('hit_snapshot', engine, actor, target, attack_context, intent):
        if not isinstance(reply, dict) or any(not isinstance(k, str) or not k for k in reply):
            raise ValueError('hit_snapshot must return a namespaced mapping or None')
        if receipts.keys() & reply.keys():
            raise ValueError('duplicate hit_snapshot namespace')
        json.dumps(reply, allow_nan=False)
        receipts.update(deepcopy(reply))
    return receipts


def finish(ctx, target, kind, spec, *, point="hit_final"):
    """Deliver a hit phase with copied receipts, restoring context even on pause.

    Native notify and typed_executor use hit_final for existing hit riders and
    hit_settled after all attached packets. Resource generators use the latter;
    future post-packet effects can reuse the same pure hit-time snapshots.
    """
    previous_receipts, previous_damage = ctx.hit_snapshots, ctx.attack_damage_context
    try:
        ctx.hit_snapshots = deepcopy(spec.get('hit_snapshots') or {})
        ctx.attack_damage_context = spec.get('resolved_attack_context')
        ctx.engine._run_final_riders(point, ctx, target, kind)
    finally:
        ctx.hit_snapshots, ctx.attack_damage_context = previous_receipts, previous_damage


def can_strike(actor):
    """Recheck eligibility between native/typed strikes after reaction effects."""
    from .typed_executor import condition_rules
    return actor.active and actor.life_state in {None, 'CONSCIOUS'} and not any(row.get('no_actions') for row in condition_rules(actor))


def notify(engine, actor, target, spec, intent, source_id, hit, attack_index=1):
    """Returns cannot alter a settled attack. Owning riders may emit their own effects.

    The notice is immutable; action/typed metadata are copies, not catalog edits.
    Unknown legacy weapon kinds remain 'other' rather than being guessed from damage.
    """
    from . import ext
    from .typed_executor import Context

    if spec.get("portable_declaration"):
        from .ext.attack_defenses import finish_portable_declaration

        finish_portable_declaration(engine, actor, source_id, attack_index)
    point = 'after_hit' if hit else 'after_miss'
    choice_point = 'after_hit_choice' if hit else 'after_miss_choice'
    if not ext.has(point) and not ext.has(choice_point) and not (hit and (ext.has('hit_final') or ext.has('hit_settled'))):
        if hit and spec.get('resolved_attack_context') is not None:
            engine._run_final_riders('attack_damage_final', engine, actor, target, spec['resolved_attack_context'], intent)
        return
    action = engine.action_catalog.get(source_id) or engine.action_catalog.get(spec.get('source_definition_id'))
    if action is None:
        action = ActionDefinition(source_definition_id=source_id, display_name='Attack', owner_id=actor.entity_id,
            economy=EconomyKind.REACTION, resolution_kind='ATTACK', target_kind='HOSTILE_ENTITY',
            range_ft=spec.get('range_ft'), reach_ft=spec.get('reach_ft'), attack_bonus=spec.get('attack_bonus'),
            damage=spec.get('damage'), damage_type=spec.get('damage_type'))
    else:
        action = action.model_copy(deep=True, update={'source_definition_id': source_id})
    typed = deepcopy(action.parameters.get('typed') or {})
    kind = str((spec.get('parameters') or action.parameters).get('attack_kind')
               or ('weapon' if typed.get('weapon') else 'other'))
    if kind not in ('unarmed', 'weapon'):
        kind = 'other'
    melee = spec.get('reach_ft') is not None or spec.get('range_ft') is None
    typed.setdefault('source', source_id)
    typed.setdefault('range_ft', None if melee else spec.get('range_ft'))
    typed.setdefault('numbers', {'pb': actor.proficiency_bonus, 'attack_bonus': int(spec.get('attack_bonus') or 0)})
    typed.setdefault('effects', [{'type': 'attack', 'attack_kind': kind}])
    ctx = Context(engine, actor, action, intent, typed, [target], target)
    provenance = spec.get('resolved_attack_context')
    roll_id = provenance.roll_id if provenance is not None else str(spec.get('attack_roll_id') or '')
    ctx.attack_notice = AttackNotice(source_id, actor.entity_id, target.entity_id, attack_index, hit, melee, kind, roll_id)
    ctx.attack_damage_context = spec.get('resolved_attack_context') if hit else None
    ctx.critical_hit = bool(ctx.attack_damage_context and ctx.attack_damage_context.critical)
    if hit:
        ext.run_strict('after_hit_choice', ctx, target, kind)
        ext.run(point, ctx, target, kind)
        finish(ctx, target, kind, spec)
    else:
        ext.run_strict('after_miss_choice', ctx, target, spec)
        ext.run(point, ctx, target)
    if hit and spec.get('resolved_attack_context') is not None:
        engine._run_final_riders('attack_damage_final', engine, actor, target, spec['resolved_attack_context'], intent)
        finish(ctx, target, kind, spec, point='hit_settled')
