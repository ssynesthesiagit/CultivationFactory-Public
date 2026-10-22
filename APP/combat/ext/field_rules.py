"""Opt-in continuous field rules and sealed summon appearance traits.

Native zone.inside reconciliation owns recipients and lifetime. No ability ID
or today's authority grants a benefit to an old sealed packet.
"""
from . import hook


def _conditions(actor):
    from ..typed_executor import is_active_typed_condition
    return [r for r in actor.conditions.values() if is_active_typed_condition(r)]


def _terrain_exempt(engine, actor, zone):
    from .. import zones

    names = {str(n).lower() for n in zone.trigger_profile.get('terrain') or []}
    # Zone-derived conditions can still describe the previous square during a
    # landed step. Resolve those grants with the same pure policy as sync_inside.
    grants = [(c.source_actor_id, ((c.data or {}).get('rule') or {}))
              for c in _conditions(actor) if c.condition_id != zones.ZONE_EFFECT]
    grants.extend((field.owner_id, row.get('rule') or {})
                  for field, row in zones.current_inside_grants(engine, actor).values())
    for owner_id, rule in grants:
        spec = rule.get('terrain_immunity') or {}
        if names & {str(n).lower() for n in spec.get('names') or []}:
            if spec.get('owner') == 'any' or owner_id == zone.owner_id:
                return True
    return False


@hook('difficult_zone_exempt')
def terrain_difficulty(engine, actor, zone):
    return _terrain_exempt(engine, actor, zone) or None


@hook('zone_recipient_allowed')
def terrain_triggers(engine, zone, actor, spec):
    if spec.get('exclude_owner') and actor.entity_id == zone.owner_id:
        return False
    # Excuse the named terrain's traversal, never ability damage on that ground.
    if spec == zone.trigger_profile.get('move_through') and _terrain_exempt(engine, actor, zone):
        return False
    return None


@hook('healing_received')
def field_healing(engine, subject, amount):
    owners = {c.source_actor_id for c in _conditions(subject)
              if ((c.data or {}).get('rule') or {}).get('healing_minus_source_pb')}
    if owners:
        return max(0, amount - sum(int(engine.state.actors[aid].proficiency_bonus or 2)
                                  for aid in owners if aid in engine.state.actors))
    return None


@hook('save_mode')
def conditional_concentration(engine, target, ability, dc, source_id, roll_context):
    if source_id == 'system:combat.concentration':
        for c in _conditions(target):
            required = ((c.data or {}).get('rule') or {}).get('concentration_disadvantage_if')
            if required and any(r.condition_id == 'condition:typed.' + required for r in _conditions(target)):
                return 'DISADVANTAGE'
    return None


@hook('hide_concealment_allowed')
def lesser_concealment(engine, actor):
    from ..typed_executor import condition_rules
    from .. import zones
    if any(r.get('hide_in_light_obscurement') for r in condition_rules(actor)):
        return any(z.trigger_profile.get('obscured') in ('light', 'heavy') and zones._inside(engine, actor, z)
                   for z in zones.typed_zones(engine))
    return None


@hook('masked_conditions')
def visible_residue(engine, attacker, target):
    from ..typed_executor import condition_rules
    out = {}
    for actor in (attacker, target):
        if actor is not None and any(r.get('suppress_hide_invisibility') for r in condition_rules(actor)):
            ids = {iid for iid, c in actor.conditions.items() if c.condition_id == 'condition:typed.hidden'}
            if ids:
                out[actor.entity_id] = ids
    return out or None


@hook('condition_choice_owner')
def step_choice_owner(engine, actor, condition):
    """The active grant belongs to its bearer, including off-turn choices."""
    from ..typed_executor import is_active_typed_condition
    if (is_active_typed_condition(condition) and
            int(((condition.data or {}).get('rule') or {}).get('step_after_enemy_miss_ft') or 0) > 0):
        return True
    return None


@hook('after_miss')
def field_step(ctx, target):
    from ..typed_executor import condition_rules
    if target is None or not target.active or target.team_id == ctx.actor.team_id:
        return
    feet = max([int(r.get('step_after_enemy_miss_ft') or 0) for r in condition_rules(target)] or [0])
    if not feet:
        return
    from .needle import ask, checkpoint_id, cell_id, CHOICE
    from .granted_movement import choices, move
    from .choice_prompt import action_context
    from .. import motion
    from ..senses import perceives

    grant = next((c for c in _conditions(target)
                  if int(((c.data or {}).get('rule') or {}).get('step_after_enemy_miss_ft') or 0) == feet), None)
    source = grant.source_definition_id if grant else ''
    action = ctx.engine.action_catalog.get(source)
    name = action.display_name if action else 'Granted movement'
    with motion.terrain_for(ctx.engine, target):
        paths = choices(ctx.engine, target, feet)
        if not paths:
            return
        destinations = {cell_id(c.destination): c for c in paths}
        stay = cell_id(target.position)
        options = [stay, *[key for key in destinations if key != stay]]
        labels = {key: f'Move to {c.destination.x},{c.destination.y} ({c.movement_cost_ft} feet)'
                  for key, c in destinations.items()}
        labels[stay] = 'Stay where you are'
        away = (max(paths, key=lambda c: ctx.engine.grid.distance_ft(ctx.actor.position, c.destination)).destination
                if perceives(ctx.engine, target, ctx.actor) else target.position)
        presentation = action_context(ctx.engine, ctx.actor, ctx.source, target)
        presentation['cost'] = 'No Action, Reaction or resource cost'
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'FIELD_STEP', target.entity_id), target,
                     CHOICE+'field_miss_step', options, labels=labels, preferred=[cell_id(away)], allow_decline=True,
                     name=name, feature_id=source, prompt_context=presentation,
                     prompt=f'{ctx.actor.display_name} uses {ctx.action.display_name} and misses {target.display_name}. '
                            f'{name}: move up to {feet} feet without provoking opportunity attacks; '
                            'no Action, Reaction or resource cost. Your ordinary movement is unchanged.',
                     target_id=target.entity_id)
        if chosen and chosen[0] != stay:
            ignored = [a.entity_id for a in ctx.engine.state.actors.values()
                       if a.active and a.team_id != target.team_id]
            move(ctx.engine, target, destinations[chosen[0]], ctx.intent, feet, ignored, name=name)


@hook('summon_appeared')
def appearance(engine, owner, creature, source_id):
    traits = (creature.summon or {}).get('appearance_traits')
    if traits:
        engine._apply_condition(creature, 'condition:typed.summon_appearance', source_id, owner.entity_id,
                                expires_on='UNTIL_REMOVED', data={**traits, 'numbers':dict(((engine.action_catalog[source_id].parameters or {}).get('typed') or {}).get('numbers') or {})})


@hook('event', nested=True)
def destroyed_patch(engine, event_type, kwargs):
    if event_type != 'ENTITY_DEFEATED':
        return
    creature = engine.state.actors.get(kwargs.get('actor_id'))
    if creature is None or not creature.summon or creature.current_hp > 0:
        return
    from . import placed
    from .. import zones
    for iid, c in list(creature.conditions.items()):
        spec = (c.data or {}).get('destroyed_terrain')
        owner = engine.state.actors.get(c.source_actor_id)
        if not spec or owner is None:
            continue
        terrain = zones.terrain_rules()['terrains'][spec['terrain']]
        # Cast-time arithmetic is sealed on the summon condition at appearance.
        placed.place(engine, owner, source=c.source_definition_id, tag='destroyed_summon_terrain',
                     cells=[creature.position, *[cell for cell in placed.area(engine, creature.position, 'sphere', int(spec['radius_ft'])) if cell != creature.position]],
                     shape='sphere', size_ft=int(spec['radius_ft']), name=spec['name'], material=terrain.get('material') or 'ash',
                     terrain=[spec['terrain']], difficult=terrain.get('difficult'), obscured=terrain.get('obscured'),
                     numbers=(c.data or {}).get('numbers') or {},
                     extra={'move_through':terrain.get('move_through'),
                            'until_owner_next_start':bool(spec.get('until_owner_next_start'))})
        from .condition_ownership import remove_instance
        remove_instance(engine, creature, iid, c.source_definition_id)


@hook('turn_start')
def patch_ends(engine, actor):
    from . import placed
    for zone in placed.of(engine, 'destroyed_summon_terrain', owner_id=actor.entity_id):
        if zone.trigger_profile.get('until_owner_next_start'):
            placed.drop(engine, zone, 'OWNER_NEXT_TURN')


@hook('nominal_slot_boundary')
def patch_nominal_end(engine, actor, checkpoint):
    """Expiry only when the owner's next slot is omitted; no turn effects."""
    if checkpoint == 'START_OF_TURN':
        patch_ends(engine, actor)


@hook('damage_defenses')
def field_defenses(engine, target, damage_type, typed, source_actor_id):
    from ..typed_executor import condition_rules
    rows = []
    for rule in condition_rules(target):
        for defense in rule.get('damage_resistance_rules') or []:
            if str(damage_type).upper() in defense.get('except_damage_types', []):
                continue
            kinds = defense.get('damage_types')
            if kinds is not None and str(damage_type).upper() not in kinds:
                continue
            rows.append({'kind':'resistance','damage_types':[str(damage_type).upper()],
                         'mundane_only':bool(defense.get('mundane_only'))})
    return rows or None
