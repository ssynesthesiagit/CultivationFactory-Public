"""A declared next-weapon-attack penalty, consumed only by its actual d20."""
from . import effect, hook

PENALTY = 'condition:typed.next_weapon_attack_penalty'


@effect('next_weapon_attack_penalty')
def apply_penalty(ctx, row):
    from ..typed_executor import effect_expiry
    from .condition_events import drop_condition
    subject = ctx.target
    if subject is None:
        return
    for held in list(subject.conditions.values()):
        if held.condition_id == PENALTY and held.source_actor_id == ctx.actor.entity_id:
            drop_condition(ctx.engine, subject, held.instance_id, ctx.source)
    ctx.engine._apply_condition(subject, PENALTY, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, subject),
        data={'label': 'Disadvantage on your next weapon attack'})


def weapon_roll(engine, actor):
    frame = engine.d20_context()
    if not frame or frame.get('kind') != 'attack' or frame.get('actor_id') != actor.entity_id:
        return False
    return frame.get("attack_delivery") == "weapon"


@hook('before_attack')
def penalty_mode(engine, attacker, defender, intent, context):
    if any(c.condition_id == PENALTY for c in attacker.conditions.values()) and weapon_roll(engine, attacker):
        return {'mode': 'DISADVANTAGE'}
    return None


@hook('event')
def spend_penalty(engine, event_type, kwargs):
    if event_type != 'ATTACK_ROLLED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None or not any(c.condition_id == PENALTY for c in actor.conditions.values()) or not weapon_roll(engine, actor):
        return
    from .condition_events import drop_condition
    for held in list(actor.conditions.values()):
        if held.condition_id == PENALTY:
            drop_condition(engine, actor, held.instance_id, held.source_definition_id)
