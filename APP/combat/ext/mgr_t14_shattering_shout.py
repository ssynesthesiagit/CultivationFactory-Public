"""Shattering Shout uses native area/save/damage and destructible-object delivery.

The printed shout is audible, not hearing-dependent. No remote origin or
unprinted resonance medium is granted. All hooks are inert for other sources.
"""
from . import effect, hook

SOURCE = 'tianxia.subpath.qi.kiai_master.feature.shattering_shout'
CHOICE = 'choice:needle.shattering_shout_damage'


@hook('compile_action')
def shout_action(action, info):
    if (action.parameters.get('typed') or {}).get('source') != SOURCE:
        return None
    # Empty cones (including object-only cones) remain legal for every seat.
    return action.model_copy(update={'parameters': {**action.parameters, 'any_cell': True,
        'description': 'Shattering Shout: spend an Action and 2 Qi. Choose Thunder or Force damage '
        'in a 15-foot cone from you: 4d6 damage (6d6 at Cultivation Level 11, 8d6 at level 17). '
        'Constitution save: full damage, pushed 10 feet and Prone '
        'on failure; half damage and pushed 5 feet on success. Unattended fragile objects '
        'automatically fail; temporary barriers and Formation Anchors take double damage.'}})


@hook('damage_type_choice')
def shout_type(ctx, kinds, targets):
    if ctx.typed.get('source') != SOURCE:
        return None
    if 'shattering_shout_type' in ctx.damage_cache:
        return ctx.damage_cache['shattering_shout_type']
    from .needle import ask
    from .. import senses
    known = [target for target in targets if senses.perceives(ctx.engine, ctx.actor, target)]
    # Seeing a creature is not knowledge of its resistances. Use the printed
    # first type as the automatic default; never inspect undisclosed defenses.
    preferred = kinds[0]
    affected = ', '.join(target.display_name for target in known) or 'the cone’s eligible recipients'
    chosen = ask(ctx.engine, ctx.intent, 'TECHNIQUE_USE', ctx.actor, CHOICE, kinds,
        labels={kind: kind.title() + ' damage' for kind in kinds}, preferred=[preferred],
        name='Shattering Shout damage', feature_id=SOURCE,
        prompt=f'Shattering Shout affecting {affected}: choose Thunder or Force damage for every creature and eligible '
        'object in your 15-foot cone, before Constitution saves. This audible shout costs '
        'your Action and 2 Qi. Deafness alone does not protect a creature.')
    kind = chosen[0] if chosen else preferred
    ctx.damage_cache['shattering_shout_type'] = kind
    return kind


@effect('shattering_shout_declaration', harmful=False)
def declare_shout(ctx, row):
    if ctx.typed.get('source') != SOURCE:
        return
    from ..typed_executor import choose_damage_type
    choose_damage_type(ctx, ['THUNDER', 'FORCE'], list(ctx.targets))


@hook('technique_used')
def shout_objects(ctx):
    if ctx.typed.get('source') != SOURCE:
        return
    from .. import object_rules, typed_executor
    from .objects import area_reaches, deal, technique_damage_row
    area = ctx.typed.get('area') or {}
    aim = ctx.damage_cache.get('_checkpoint_aim') or ctx.actor.position
    # Snapshot recipients before breaking any obstruction. Classification is
    # supplied by the map/asset producer, never guessed from a display name.
    struck = [obj for obj in ctx.engine.state.objects.values()
        if not obj.destroyed and obj.current_hp is not None and (
            (object_rules.has_tag(obj, 'unattended') and object_rules.has_tag(obj, 'fragile'))
            or object_rules.has_tag(obj, 'temporary_barrier')
            or object_rules.has_tag(obj, 'formation_anchor'))
        and area_reaches(ctx.engine, ctx.actor.position, aim, obj, area)]
    if not struck:
        return
    damage = technique_damage_row(ctx.typed.get('effects'))
    if damage is None:
        return
    amount, kind = typed_executor._damage_roll(ctx, damage)
    for obj in struck:
        double = any(object_rules.has_tag(obj, tag) for tag in ('temporary_barrier', 'formation_anchor'))
        deal(ctx.engine, ctx.actor, obj, [(amount, kind)], ctx.source, multiplier=2 if double else 1)
