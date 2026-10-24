"""Sealed second-pass Axes descent and a general next-opportunity penalty."""
from . import effect, hook
from .condition_ownership import remove_instance, refresh_owned

PENALTY = 'condition:typed.next_opportunity_penalty'


@effect('general_next_opportunity_penalty')
def penalty(ctx, row):
    from ..typed_executor import effect_expiry
    target = ctx.target
    if target is None or not target.active:
        return
    refresh_owned(ctx.engine, target, PENALTY, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(target, PENALTY, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, target, condition=True),
        data={'label': f'Disadvantage on your next Opportunity Attack before the start of {ctx.actor.display_name}’s next turn.'})


def held(actor):
    return [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == PENALTY]


@hook('attack_mode')
def opportunity_mode(ctx, target):
    if ctx.typed.get('opportunity_of') and held(ctx.actor):
        return 'DISADVANTAGE'
    return None


@hook('native_reaction_roll_mode')
def native_mode(engine, context):
    actor = engine.state.actors.get(context.get('actor_id'))
    if context.get('source_id') == 'system:combat.opportunity_attack' and actor is not None and held(actor):
        return {'mode': 'DISADVANTAGE', 'effect': 'Bearded Hook Method',
                'why': 'your next Opportunity Attack before this attacker’s next turn has Disadvantage'}
    return None


@hook('event', nested=True)
def consume(engine, event_type, kwargs):
    if event_type != 'ATTACK_ROLLED':
        return
    source = kwargs.get('source_definition_id')
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get('typed') or {}) if action else {}
    if source != 'system:combat.opportunity_attack' and not typed.get('opportunity_of'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is not None:
        for iid, condition in held(actor):
            remove_instance(engine, actor, iid, source)


@effect('axes_knee_descent')
def descent(ctx, row):
    """Resolve the printed safe descent to a supported surface beneath a flyer."""
    from ..flight import profile
    from ..falling import supported
    from .rider_movement import volume_route
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or target.position.z <= 0:
        return
    capability = profile(ctx.engine, target)
    if capability.hover or capability.speed_ft <= 0:
        return
    surface = next((target.position.model_copy(update={'z': z})
                    for z in range(target.position.z - 1, max(-1, target.position.z - 7), -1)
                    if supported(ctx.engine, target, target.position.model_copy(update={'z': z}))), None)
    path = ([target.position] + [target.position.model_copy(update={'z': z})
            for z in range(target.position.z - 1, surface.z - 1, -1)]) if surface is not None else []
    if not path or not volume_route(ctx.engine, target, path, ctx.source):
        ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
            target_ids=(target.entity_id,), payload={'log':
                f'{target.display_name} needs a manual safe descent ruling: the complete route and landing could not be completed. Choose a legal landing within 30 feet; do not apply falling damage.'})
        return
    if target.position == surface:
        run_effects(ctx, [{'type': 'condition', 'condition': 'prone', 'duration': 'instant'}])
