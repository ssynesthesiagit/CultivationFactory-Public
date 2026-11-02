"""Source-sealed Force automation using the shared origin, object and wall hooks.

New rows opt in; markerless saved actions/Incarnations retain their old behavior.
No live authority lookup, actor relocation for geometry, or core ability branch.
"""
from __future__ import annotations

import copy
from . import effect, hook, note
from . import force as F

ORIGIN = 'force_geometry'
BRACED = 'condition:typed.force_bracing_barriers'
SUNDER = 'force_sundering'
LINES = {'TAL_FORCE_GROUND_ANSWERING_PALM': 60, 'TAL_FORCE_MERIDIAN_OF_IMPACT': 120}
WALL = 'TAL_FORCE_FORCE_WALL'
SHOCK = 'TAL_FORCE_SHOCKWAVE'


def geometry(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return next((row for row in typed.get('effects', []) if row.get('type') == ORIGIN), None)


@effect(ORIGIN)
def bind_origin(ctx, row):
    from ..action_geometry import point
    origin = point(ctx.engine, ctx.actor)
    ctx.typed['_area_centre'] = (origin.x, origin.y)


@hook('compile_action')
def compile_geometry(action, info):
    row = geometry(action)
    if row is None:
        return None
    # Native origin variants measure range, cover and area vertices from their
    # bound point. The original actor still supplies perception and reactions.
    feature = row['feature']
    span = 30 if feature == F.IMPACT else 5 if feature == WALL else 0 if feature == SHOCK else int((action.parameters['typed'].get('area') or {}).get('size_ft') or 30)
    parameters = action.parameters
    if feature == WALL:
        typed = copy.deepcopy(parameters['typed'])
        spec = typed['zone_spec']
        spec['wall'] = {**spec['wall'], 'height_ft': 10}
        parameters = {**parameters, 'typed': typed}
    return action.model_copy(update={'range_ft': span, 'parameters': parameters})


@hook('effect_origins')
def pressure_origins(engine, actor, action):
    row = geometry(action)
    if row is None:
        return None
    from ..senses import perceives_cell
    from ..action_geometry import activate
    from ..falling import supported
    feature, reach = row['feature'], int(row['reach_ft'])
    with activate(engine, actor, action.source_definition_id, None):
        cells = F.origins(engine, actor, reach)[1:]
        return [{'id': f'force:{cell.x},{cell.y},{cell.z}', 'label': f'Pressure Anchor at ({cell.x}, {cell.y}, {cell.z * 5} feet high)',
                 'position': cell.model_dump(mode='json')}
                for cell in cells if perceives_cell(engine, actor, cell)
                and (feature not in LINES or supported(engine, actor, cell))]


@hook('candidate_allowed')
def geometry_candidates(engine, actor, candidate, action):
    row = geometry(action)
    if row is None:
        return None
    from ..target_knowledge import can_see
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell
    from ..action_geometry import activate
    feature = row['feature']
    # A relay does not supply a creature's senses. Unseen anchors and targets
    # cannot be used by a player or by an AI.
    record = (candidate.metadata or {}).get('effect_origin')
    with activate(engine, actor, action.source_definition_id, None):
        if record and not perceives_cell(engine, actor, Position(**record['position'])):
            return False
        for tid in candidate.target_ids:
            target = engine.state.actors.get(tid)
            if target is not None and not can_see(engine, actor, target):
                return False
            obj = engine.state.objects.get(tid)
            if obj is not None:
                from ..object_geometry import target_cells
                if not any(perceives_cell(engine, actor, cell) for cell in target_cells(engine, obj)):
                    return False
        if action.parameters.get('force_impact_wall') and not perceives_cell(engine, actor, candidate.destination):
            return False
    if feature == SHOCK:
        origin = Position(**record['position']) if record else actor.position
        return candidate.destination == origin
    if feature == WALL:
        from ..gate2_runtime_models import Position
        origin = Position(**record['position']) if record else actor.position
        aim = candidate.destination
        if aim is None or engine.grid.distance_ft(origin, aim) != 5:
            return False
        return not engine._occupied_cells_except(actor.entity_id).intersection({(aim.x, aim.y)}) and (aim.x, aim.y) not in engine.grid.blocked
    return None


@hook('effect_subject_allowed')
def standing_on_route(ctx, row, subject):
    if geometry(ctx.action) is None or geometry(ctx.action)['feature'] not in LINES:
        return None
    if row.get('type') not in {'save', 'damage', 'half_damage', 'condition'}:
        return None
    from ..falling import supported
    return None if supported(ctx.engine, subject) else False


@effect(SUNDER)
def sundering_marker(ctx, row):
    """The paid Impact variant seals its additional die, read at the actual roll."""
    return None


def sundering(typed):
    from ..effect_harm import rows
    return any(row.get('type') == SUNDER for row in rows(typed.get('effects') or []))


@hook('confirmed_hit_damage_dice')
def sundering_construct(engine, attacker, target, spec, intent, source, critical):
    from .attack_scope import current
    from ..creature_types import has_type
    from ..gate2_runtime_models import DiceSpec
    frame = current(engine)
    if not frame or frame['actor_id'] != attacker.entity_id or frame['source'] != source:
        return None
    ctx = frame['context']
    dice = spec.get('damage')
    if (not sundering(ctx.typed) or F.IMPACT not in source or not has_type(target, 'construct')
            or not isinstance(dice, DiceSpec)):
        return None
    return DiceSpec(count=dice.count + 1, sides=dice.sides, modifier=dice.modifier)


@hook('object_targets')
def impact_objects(engine, actor, action):
    row = geometry(action)
    if row is None or row['feature'] != F.IMPACT:
        return None
    return [obj.object_id for obj in engine.state.objects.values()
            if not obj.destroyed and obj.ac is not None and obj.current_hp is not None]


def impact_dice(ctx, damage, *, critical=False):
    from ..typed_executor import _effect_dice, _roll, damage_choices
    from ..gate2_runtime_models import DiceSpec
    from .objects import prepare_damage_dice
    dice = ctx.dice(_effect_dice(ctx, damage), flat=int(damage.get('flat') or 0), formula=damage.get('formula'))
    dice = F.force_attack_damage(ctx, dice) or dice
    if sundering(ctx.typed):
        dice = DiceSpec(count=dice.count + 1, sides=dice.sides, modifier=dice.modifier)
    # Force's own shaping (Mantle, the Bracing die) is already applied above, and
    # ``force_attack_damage`` spends the Mantle clock first, so the shared fold below pays it
    # exactly once. Every other plug-in's printed damage-roll bonus reaches this packet.
    dice = prepare_damage_dice(ctx, dice, damage, damage_choices(damage))
    return _roll(ctx, dice, 'DAMAGE', critical=critical)


def impact_kind(ctx, damage, name):
    from ..typed_executor import damage_choices
    from .rider_choices import pick
    kinds = damage_choices(damage)
    if len(kinds) <= 1:
        return kinds[0] if kinds else 'UNTYPED'
    chosen = pick(ctx.engine, ctx.actor, 'force_object_damage_type', ctx.action.display_name, kinds,
        subject=ctx.actor, optional=False, intent=ctx.intent,
        labels={kind: kind.title() + ' damage' for kind in kinds}, preferred=[kinds[0]],
        prompt=f'{ctx.action.display_name}: choose the damage type against {name}.')
    return chosen[0]


@hook('object_action')
def impact_at_object(engine, actor, action, obj, candidate, intent):
    row = geometry(action)
    if row is None or row['feature'] != F.IMPACT:
        return None
    from ..typed_executor import Context
    from .objects import roll_technique_attack, technique_damage_row, deal
    typed = copy.deepcopy(action.parameters['typed'])
    ctx = Context(engine, actor, action, intent, typed, [], None, {})
    damage = technique_damage_row(typed['effects'])
    hit, natural = roll_technique_attack(ctx, obj, 0)
    if hit:
        kind = impact_kind(ctx, damage, str(obj.component.get('name') or 'the object'))
        amount = impact_dice(ctx, damage, critical=natural == 20)
        deal(engine, actor, obj, [(amount, kind)], ctx.source)
    return True


@effect('force_bracing_barriers')
def bracing_barriers(ctx, row):
    from ..typed_executor import effect_expiry
    ctx.engine._apply_condition(ctx.actor, BRACED, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.actor, condition=True),
        data={'bonus': 5 * F.pb_of(ctx.engine, ctx.actor), 'label': 'World-Bracing Incarnation: new Barriers have more hit points'})


@hook('created_durability_bonus')
def bracing_durability(ctx, kind):
    if kind != 'barrier':
        return None
    return max((int(c.data['bonus']) for c in ctx.actor.conditions.values()
                if c.condition_id == BRACED and c.source_actor_id == ctx.actor.entity_id), default=0) or None


@effect('force_shockwave_objects')
def shockwave_objects(ctx, row):
    """Move only explicitly weighed unattended objects, through clear physical cells."""
    from ..action_geometry import point
    from ..gate2_runtime_models import Position
    from ..object_geometry import diagonal_swept_cells, target_cells
    from ..typed_executor import in_area
    from .. import zones
    engine = ctx.engine
    origin = ctx.intent.destination or point(engine, ctx.actor)
    area = ctx.typed.get('area') or {}
    for old in list(engine.state.objects.values()):
        weight = (old.component or {}).get('weight_lb')
        if old.destroyed or not old.unattended or type(weight) is not int or not 0 <= weight <= 20 * int(ctx.numbers['cl']):
            continue
        if not any(in_area(engine, point(engine, ctx.actor), origin, cell, area) for cell in target_cells(engine, old)):
            continue
        if old.component.get('structure') or old.component.get('mount_axis'):
            continue  # a fixed structure has no route along which it can be pushed
        dx, dy = (old.position.x > origin.x) - (old.position.x < origin.x), (old.position.y > origin.y) - (old.position.y < origin.y)
        if not (dx or dy):
            continue
        obj = old
        own = {(c.x, c.y) for c in target_cells(engine, old)}
        blocked = set(engine.grid.blocked) - own
        occupied = {cell for creature in engine.state.actors.values() if creature.active
                    and creature.position.z == old.position.z for cell in engine._actor_cells(creature)}
        occupied.update((cell.x, cell.y) for other in engine.state.objects.values()
                        if other.object_id != old.object_id and not other.destroyed
                        for cell in target_cells(engine, other) if cell.z == old.position.z)
        for _ in range(2):
            nxt = obj.model_copy(update={'position': Position(x=obj.position.x + dx, y=obj.position.y + dy, z=obj.position.z)})
            if not engine.grid.in_bounds((nxt.position.x, nxt.position.y)):
                break
            try:
                cells = {(c.x, c.y) for c in target_cells(engine, nxt)}
            except ValueError:
                break
            if cells & (blocked | occupied):
                break
            # Both full intermediate footprints of a diagonal must be clear, just like native
            # movement: a wide object sweeps cells that neither its destination nor the two
            # squares beside its anchor contain, so a blocker there stops the push.
            if dx and dy:
                swept = diagonal_swept_cells(engine, obj, dx, dy)
                if swept is None or (swept - own) & (blocked | occupied):
                    break
            obj = nxt
        if obj.position != old.position:
            engine._update_object(obj, ctx.source, ctx.actor.entity_id)
            note(engine, ctx.source, ctx.actor, f'Shockwave pushes {obj.component.get("name") or "the object"} away from the origin.')
            zones.sync_walls(engine)


@hook('compile_actions')
def impact_wall_actions(info):
    out = []
    for action in info.get('actions') or []:
        row = geometry(action)
        if row is None or row['feature'] != F.IMPACT:
            continue
        typed = copy.deepcopy(action.parameters['typed'])
        for effect_row in typed['effects']:
            if effect_row.get('type') == 'attack':
                effect_row['type'] = 'force_impact_wall'
        out.append(action.model_copy(update={
            'source_definition_id': action.source_definition_id + '.wall',
            'display_name': action.display_name + ' (wall section)', 'target_kind': 'CELL',
            'parameters': {**action.parameters, 'typed': typed, 'any_cell': True, 'player_only': True,
                           'force_impact_wall': True}}))
    return out or None


@hook('candidate_allowed')
def impact_wall_candidate(engine, actor, candidate, action):
    if not (action and action.parameters.get('force_impact_wall')):
        return None
    from .docket_walls import section_at
    return candidate.destination is not None and section_at(engine, candidate.destination) is not None


@effect('force_impact_wall')
def impact_wall(ctx, row):
    from .docket_walls import section_at, defense_stats, damage_section
    from .objects import technique_damage_row, attack_roll_bonus
    found = section_at(ctx.engine, ctx.intent.destination)
    if found is None:
        return
    zone, section = found
    stats = defense_stats(ctx, zone)
    # The shared modifier fold, so a rider whose printed text changes this attack roll (Jinxed
    # Name, Turning Wheel, Exhaustion) reaches the wall route exactly as it does the object and
    # creature routes, and a consumable penalty is spent by the roll that reads it.
    roll = ctx.engine.roller.d20(modifier=attack_roll_bonus(ctx), actor_id=ctx.actor.entity_id,
        reason=f'ATTACK:{ctx.source}:wall', mode='NORMAL')
    ctx.engine._record_roll(roll)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or roll.total >= stats['ac'])
    ctx.engine._append_event('CHECK_ROLLED', ctx.source, actor_id=ctx.actor.entity_id,
        payload={'actor': roll.model_dump(mode='json'), 'dc': stats['ac'], 'success': hit,
                 'check': 'Impact against a wall section', 'zone_id': zone.zone_id, 'cell': [section.x, section.y]})
    if hit:
        damage = technique_damage_row(row.get('on_hit'))
        kind = impact_kind(ctx, damage, str(zone.trigger_profile.get('name') or 'the wall section'))
        amount = impact_dice(ctx, damage, critical=natural == 20)
        if kind in stats['immune']:
            amount = 0
        elif kind in stats.get('resist', ()):
            amount //= 2
        if kind in stats['vulnerable']:
            amount *= 2
        damage_section(ctx.engine, zone, section, amount, ctx.source, kind)


@hook('forced_movement_distance')
def impact_optional_push(ctx, subject, row, maximum_ft):
    marker = geometry(ctx.action)
    if marker is None or marker['feature'] != F.IMPACT or row.get('direction') != 'away_center':
        return None
    from .rider_choices import pick
    key = ('force_impact_push', subject.entity_id)
    if key not in ctx.damage_cache:
        chosen = pick(ctx.engine, ctx.actor, 'force_impact_push', 'Impact', ['push', 'stay'],
            subject=subject, intent=ctx.intent, optional=False, preferred=['push'],
            labels={'push': 'Push away from the origin', 'stay': 'Deal damage without pushing'},
            prompt=f'Impact hits {subject.display_name}. Do you also push them directly away from the origin?')
        ctx.damage_cache[key] = chosen == ['push']
    return maximum_ft if ctx.damage_cache[key] else 0


def allows_impact_push(ctx, subject):
    """Shared with force.incarnation_push: an optional base push owns its bonus too."""
    return ctx.damage_cache.get(('force_impact_push', getattr(subject, 'entity_id', ''))) is not False
