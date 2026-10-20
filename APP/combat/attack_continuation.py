"""One-roll native attack continuation across creature/object recipients.

Used by hit redirections, including interchangeable physical projections.
The immutable original die is scoped to one source/attacker and consumed once;
the destination executes its ordinary hit, critical, damage and rider path.
No new attack die, catalogue patch or persistent scratch state is introduced.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_PENDING = ContextVar('continued_attack_roll', default=None)


@contextmanager
def same_roll(engine, actor, source, roll, total):
    pending = {'engine': engine, 'actor': actor.entity_id, 'source': source,
               'roll': roll, 'total': total, 'used': False}
    token = _PENDING.set(pending)
    try:
        yield
    finally:
        _PENDING.reset(token)


def take(engine, actor, source):
    pending = _PENDING.get()
    if (pending is None or pending['used'] or pending['engine'] is not engine
            or pending['actor'] != actor.entity_id or pending['source'] != source):
        return None
    pending['used'] = True
    return pending['roll'], pending['total']


def creature(ctx, target, roll, total):
    from copy import deepcopy
    from .typed_executor import Context, run_effects
    typed = deepcopy(ctx.typed.get('object_creature_delivery') or ctx.typed)
    if ctx.typed.get('object_weapon') and not ctx.typed.get('object_creature_delivery'):
        typed['weapon'] = deepcopy(ctx.typed['object_weapon'])
        typed['effects'] = [{'type': 'attack', 'attack_kind': 'unarmed' if ctx.typed.get('object_weapon_group') == 'unarmed' else 'melee',
                             'count': 1, 'on_hit': [{'type': 'damage', 'weapon_damage': True, 'applies_to': 'target'}]}]
    # A continuation is one already-declared strike, not another Extra Attack.
    attacks = [e for e in typed.get('effects', []) if e.get('type') == 'attack']
    attacks = [{**e, 'count': 1} for e in attacks[:1]]
    sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, [target], target)
    with same_roll(ctx.engine, ctx.actor, ctx.source, roll, total):
        run_effects(sub, attacks)


def object_target(engine, attacker, obj, spec, roll, total, intent):
    from copy import deepcopy
    from .typed_executor import Context
    from .ext import objects, attack_scope
    action = engine.action_catalog[spec['source_definition_id']]
    frame = attack_scope.current(engine)
    typed = deepcopy(action.parameters.get('typed') or spec.get('typed') or {})
    if frame:
        typed = deepcopy(frame['context'].typed)
    if not typed.get('effects') and spec.get('damage') is not None:
        dice = spec['damage']
        typed['weapon'] = {'damage': dice.model_dump(mode='json') if hasattr(dice,'model_dump') else deepcopy(dice),
                           'damage_type': spec.get('damage_type') or 'UNTYPED',
                           **({'fixed_damage': spec['fixed_damage']} if spec.get('fixed_damage') is not None else {})}
        typed['effects'] = [{'type':'attack','count':1,'on_hit':[{'type':'damage','weapon_damage':True}]}]
        typed['numbers'] = {'attack_bonus':int(spec.get('attack_bonus') or 0)}
    ctx = Context(engine, attacker, action, intent, typed, [], None,
                  frame['context'].damage_cache if frame else {})
    objects.continue_attack(ctx, obj, spec, roll, total)
