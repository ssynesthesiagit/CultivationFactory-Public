"""Source-owned, temporary Obscure Passage on represented map surfaces.

Diameter and depth are retained in feet. The native grid projects horizontal
geometry to cells; vertical bounds remain exact. Depth is measured along the
chosen direction, including horizontal floor/roof planes, and explicit exceptional-hardness metadata vetoes it
after the ordinary cultivation point payment. Ending the source restores the
original map spans without editing the map document.
"""
from . import effect, hook
from .needle import ask, checkpoint_id, cell_id, numbers_of

PASSAGE = 'TAL_DARK_OBSCURE_PASSAGE'
DIRECTIONS = {'east': (1, 0, 0), 'west': (-1, 0, 0), 'north': (0, -1, 0), 'south': (0, 1, 0),
              'up': (0, 0, 1), 'down': (0, 0, -1)}


def failed_surface(ctx, message):
    from . import note
    note(ctx.engine, ctx.source, ctx.actor, message)
    if ctx.actor.concentration is not None and ctx.actor.concentration.source_definition_id == ctx.source:
        ctx.engine._end_concentration(ctx.actor, 'FAILED_PASSAGE')


@hook('compile_action')
def passage_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != PASSAGE:
        return None
    typed = {**typed, 'effects': [{'type': 'obscure_passage'}]}
    typed.pop('zone_spec', None)
    typed.pop('area', None)
    return action.model_copy(update={'target_kind': 'CELL', 'range_ft': 30,
        'parameters': {**action.parameters, 'typed': typed, 'any_cell': True, 'targets_surface': True,
                       'ai_empty_area_filter': False, 'inert': False}})


@hook('candidate_allowed')
def visible_surface(engine, actor, candidate, action):
    if action is not None and (action.parameters.get('typed') or {}).get('source') == PASSAGE:
        from ..targeting import cell_line_of_effect
        if not candidate.destination:
            return False
        roof = any(r.solid_at(candidate.destination.x, candidate.destination.y)
                   and r.walk_ft == candidate.destination.z * 5 for r in engine.grid.roof_surfaces)
        return bool((roof or engine._line_of_sight_actor_to_cell(actor, candidate.destination))
                    and cell_line_of_effect(engine, actor, action, candidate.destination))


def exceptional(engine, cell):
    return any((region.get('exceptional_hardness') or str(region.get('material') or '').lower() == 'adamantine')
        and any((c['x'], c['y']) == (cell.x, cell.y) for c in region.get('cells', []))
        for region in engine.grid._occluder_regions)


@effect('obscure_passage')
def open_passage(ctx, row):
    from ..gate2_runtime_models import Position
    from .. import zones
    from . import note
    target = ctx.intent.destination
    if target is None:
        return
    direction = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'passage_direction', ctx.source), ctx.actor,
        'choice:needle.passage_direction', list(DIRECTIONS), name='Obscure Passage',
        labels={key: ('Open upward through the ceiling or roof' if key == 'up'
                     else 'Open downward through the floor' if key == 'down'
                     else f'Open through the surface toward the {key}') for key in DIRECTIONS},
        prompt='Obscure Passage: choose the direction through the visible surface. The passage’s diameter is your Proficiency Bonus in feet; an overly thick or exceptionally hard surface consumes the cultivation point without opening.')
    if not direction:
        return
    dx, dy, dz = DIRECTIONS[direction[0]]
    cl = int(ctx.numbers.get('cl') or 1)
    maximum = 20 if cl >= 15 else 15 if cl >= 10 else 10 if cl >= 5 else 5
    diameter = int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus)
    cells = []
    point = target
    while ctx.engine.grid.in_bounds((point.x, point.y)) and point.z >= 0:
        if exceptional(ctx.engine, point):
            failed_surface(ctx, 'Obscure Passage fails: this surface is exceptionally hard. The cultivation point is spent.')
            return
        cells.append(point)
        if not ctx.engine.grid.terrain_at((point.x, point.y, point.z), 'BLOCKED'):
            break
        if len(cells) * 5 > maximum:
            failed_surface(ctx, 'Obscure Passage fails: this surface is too thick. The cultivation point is spent.')
            return
        point = Position(x=point.x + dx, y=point.y + dy, z=point.z + dz)
    low, high = target.z * 5, target.z * 5 + diameter
    ground = False
    if dz:
        # A horizontal surface is a sealed roof/floor plane, or the top of
        # finite solid terrain. Start downward excavation below its upper face.
        roofs = [r for r in ctx.engine.grid.roof_surfaces
                 if r.solid_at(target.x, target.y) and
                 (target.z * 5 <= r.height_ft <= (target.z + 1) * 5 if dz > 0
                  else r.walk_ft == target.z * 5)]
        roof = next(iter(roofs), None)
        ground = target.z == 0 and dz < 0
        if roof or ground:
            cells = [target.model_copy(update={'z': roof.walk_ft // 5}) if roof else target]
            plane = roof.height_ft if roof else 0
            low, high = (plane, plane + 1) if dz > 0 or ground else (max(0, plane - 1), plane)
        else:
            point = target if dz > 0 else target.model_copy(update={'z': max(0, target.z - 1)})
            cells = []
            while point.z >= 0 and ctx.engine.grid.terrain_at((point.x, point.y, point.z), 'BLOCKED'):
                if exceptional(ctx.engine, point) or (len(cells) + 1) * 5 > maximum:
                    failed_surface(ctx, 'Obscure Passage fails: this surface is too thick or exceptionally hard. The cultivation point is spent.')
                    return
                cells.append(point)
                if point.z == 0 and dz < 0:
                    break
                point = point.model_copy(update={'z': point.z + dz})
            if not cells:
                failed_surface(ctx, 'Obscure Passage fails: there is no represented solid surface here. The cultivation point is spent.')
                return
            low, high = min(p.z for p in cells) * 5, (max(p.z for p in cells) + 1) * 5
            cells = [target]
    # The far-side open square is an exit, not a part removed from the surface.
    if len(cells) > 1 and not ctx.engine.grid.terrain_at((cells[-1].x, cells[-1].y, cells[-1].z), 'BLOCKED'):
        cells.pop()
    spec = {'name': 'Obscure Passage', 'shape': 'wall', 'size_ft': diameter, 'cells': tuple(cells),
            'wall': {'blocks_movement': False, 'blocks_sight': False, 'obscures': 'all',
                     'material': 'darkness', 'height_ft': diameter, 'base_altitude_ft': target.z * 5},
            'visual': {'material': 'darkness', 'darkness': True},
            'obscured': 'heavy', 'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True}}
    zone = zones.create(ctx, spec)
    if zone is None:
        return
    zone.trigger_profile['aperture'] = {'cells': [[p.x, p.y] for p in cells],
        'bottom_ft': low, 'top_ft': high, 'horizontal': int(bool(dz)), 'ground': int(ground),
        'diameter_ft': diameter, 'maximum_depth_ft': maximum, 'transmits_light': 0}
    ctx.engine._append_event('ZONE_CREATED', ctx.source, actor_id=ctx.actor.entity_id, payload={'zone': zone.model_dump(mode='json')})
    zones.sync_walls(ctx.engine)
    from ..typed_executor import Context, run_effects
    for actor in list(ctx.engine.state.actors.values()):
        if not actor.active or actor.position not in cells:
            continue
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'passage_save', zone.zone_id, actor.entity_id),
            actor, 'choice:needle.passage_save', ['save', 'stay'], name='Obscure Passage',
            labels={'save': 'Make a Dexterity save to move to the nearest safe space', 'stay': 'Stay over the opening'},
            prompt=f'Obscure Passage opens under {actor.display_name}. Make a Dexterity save to move to a nearest safe space, or remain over the opening?')
        if selected and selected[0] == 'save':
            sub = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {})
            run_effects(sub, [{'type': 'save', 'ability': 'dex', 'applies_to': 'target',
                'on_success': [{'type': 'passage_safe_relocation', 'zone_id': zone.zone_id}], 'on_fail': []}])


@effect('passage_safe_relocation')
def safe_space(ctx, row):
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve
    from collections import deque
    actor = ctx.target
    opening = ctx.engine.state.zones[row['zone_id']]
    occupied = ctx.engine._occupied_volumes_except(actor.entity_id)
    paths = {(actor.position.x, actor.position.y): (actor.position,)}
    pending = deque([actor.position])
    while pending:
        point = pending.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
            x, y = point.x + dx, point.y + dy
            if min(x, y) < 0 or (x, y) in paths:
                continue
            nxt = Position(x=x, y=y, z=point.z)
            if ctx.engine.grid.volume_step_legal(point, nxt, footprint=ctx.engine._footprint(actor), occupied_cells=occupied):
                paths[(x, y)] = (*paths[(point.x, point.y)], nxt)
                pending.append(nxt)
    from ..falling import supported
    from ..flight import profile
    from ..typed_executor import condition_rules
    can_steer = actor.active and actor.current_hp > 0 and not ctx.engine._has_condition(actor, 'condition:core.prone') \
        and not any(rule.get('no_actions') or rule.get('speed_zero') or rule.get('ends_on_stand_up')
                    for rule in condition_rules(actor))
    def safe_landing(point):
        if supported(ctx.engine, actor, point):
            return True
        # Conditional flight (e.g. Created Air inside a vacuum) must still be
        # available at the landing, rather than only over the opening.
        capability = profile(ctx.engine, actor.model_copy(update={'position': point}))
        return capability.hover or capability.suspended or (capability.speed_ft > 0 and can_steer)
    points = [path[-1] for path in paths.values() if path[-1] not in opening.affected_cells
              and safe_landing(path[-1])]
    if not points:
        return
    distance = min(ctx.engine.grid.distance_ft(actor.position, p) for p in points)
    points = [p for p in points if ctx.engine.grid.distance_ft(actor.position, p) == distance]
    options = {cell_id(p, include_altitude=True): p for p in points}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'passage_safe', ctx.source, actor.entity_id), actor,
        'choice:needle.passage_safe', list(options), name='Obscure Passage',
        labels={key: f'Nearest safe space at {point.x},{point.y}' for key, point in options.items()},
        prompt=f'Obscure Passage: {actor.display_name} succeeded on its Dexterity save. Choose a nearest safe space.')
    if selected:
        destination = options[selected[0]]
        path = paths[(destination.x, destination.y)]
        resolve(ctx.engine, actor, path, ctx.source, kind='forced', feet=(len(path) - 1) * 5,
                intent=ctx.intent, source_actor_id=ctx.actor.entity_id, ctx=ctx)


@hook('terrain_apertures')
def apertures(engine):
    return [z.trigger_profile['aperture'] for z in engine.state.zones.values() if z.active and z.trigger_profile.get('aperture')]


@hook('zone_created')
def passage_concentration(ctx, zone):
    """Bind before the creation receipt snapshots current concentration.

    Native create's later assignment cannot survive a cold event replay. This
    existing pre-publication hook keeps the owned opening tied to its caster.
    """
    if ctx.typed.get('source') != PASSAGE or not zone.concentration_link:
        return
    from .zone_concentration import bind
    bind(ctx, zone)


@hook('wall_sense_allowed')
def passage_vision(engine, zone, viewer, sense, seen):
    if zone.trigger_profile.get('aperture') and sense in ('darkvision', 'low_light_vision'):
        return False


@hook('light_path_allowed')
def black_passage(engine, start, end):
    from ..space import ray
    path = ray(start, end)
    for row in apertures(engine):
        cells = {tuple(p) for p in row['cells']}
        if any((x, y) in cells and
               (z * 5 <= row['top_ft'] and (z + 1) * 5 >= row['bottom_ft'] if row.get('horizontal')
                else row['bottom_ft'] <= z * 5 < row['top_ft']) for x, y, z in path):
            return False


@hook('choice_reactors')
def occupants(engine):
    # A player's save/relocation may be triggered by an AI opening the passage.
    from .fight_ownership import owns_feature
    return tuple(engine.state.actors) if any(owns_feature(engine, actor, PASSAGE) for actor in engine.state.actors.values()) else ()


@hook('event')
def restored_surface(engine, event_type, kwargs):
    if event_type != 'ZONE_REMOVED':
        return
    zone = engine.state.zones.get((kwargs.get('payload') or {}).get('zone_id'))
    if zone is not None and zone.trigger_profile.get('aperture'):
        from .. import zones
        zones.sync_walls(engine)
