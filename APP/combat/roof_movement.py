"""Native roof climbing, grip, and deliberate drops.

Routes use the ordinary MOVE transaction and observed occupancy. A climb costs
one extra foot per foot unless the creature uses a Climb Speed. Slippery walls
and walls with few handholds may require the map's DC 15 Athletics check;
ordinary walls never draw a check. Grid routes include the step onto the roof.
"""
from dataclasses import dataclass
import heapq

from .gate2_runtime_models import Position
from .space import point


@dataclass(frozen=True)
class Climbing:
    speed_ft: int = 0
    without_check: bool = False
    disabled: bool = False
    check_abilities: tuple[str, ...] = ('STR',)
    check_modes: tuple[str, ...] = ()
    check_choice_name: str = ''
    check_choice_source: str = ''
    ceiling: bool = False
    virtual_wall: bool = False
    virtual_hold: bool = False
    physical_disabled: bool = False


def profile(engine, actor):
    """Recorded capabilities, with an optional pure ``climbing`` provider.

    Providers return climb_speed_ft, climb_without_check, climbing_disabled,
    climb_physical_disabled (physical grips only, preserving virtual walls),
    climb_check_abilities (STR/DEX), climb_check_modes (Advantage/Disadvantage)
    and, for an owned ability that opens a Strength/Dexterity choice,
    climb_check_choice_name (a readable ability name) and
    climb_check_choice_source (its source id). No ability name is interpreted by
    the movement engine; the readable name is only shown to the player.
    """
    from . import ext
    speed = actor.climb_speed_ft
    without_check = disabled = ceiling = virtual_wall = virtual_hold = physical_disabled = False
    abilities, modes = {'STR'}, set()
    choice_name, choice_source = '', ''
    rows = [condition.data for condition in actor.conditions.values()]
    if ext.has('climbing'):
        rows += ext.run_strict('climbing', engine, actor)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Climbing providers must return a capability dictionary')
        value = row.get('climb_speed_ft', 0)
        if type(value) is not int or value < 0:
            raise ValueError('Climb Speed must be nonnegative integer feet')
        speed = max(speed, value)
        without_check |= bool(row.get('climb_without_check'))
        disabled |= bool(row.get('climbing_disabled'))
        physical_disabled |= bool(row.get('climb_physical_disabled'))
        ceiling |= bool(row.get('climb_ceiling'))
        virtual_wall |= bool(row.get('climb_virtual_wall'))
        virtual_hold |= bool(row.get('climb_hold_virtual'))
        offered = row.get('climb_check_abilities', ())
        check_modes = row.get('climb_check_modes', ())
        if (not isinstance(offered, (tuple, list)) or any(value not in {'STR', 'DEX'} for value in offered)
                or not isinstance(check_modes, (tuple, list))
                or any(value not in {'ADVANTAGE', 'DISADVANTAGE'} for value in check_modes)):
            raise ValueError('Climbing checks require STR/DEX choices and valid Advantage/Disadvantage modes')
        for key in ('climb_check_choice_name', 'climb_check_choice_source'):
            text = row.get(key, '')
            if text and not isinstance(text, str):
                raise ValueError('Climbing choice provenance must be strings')
        abilities.update(offered)
        modes.update(check_modes)
        choice_name = choice_name or str(row.get('climb_check_choice_name') or '')
        choice_source = choice_source or str(row.get('climb_check_choice_source') or '')
    from .motion import all_mode_speed_penalties
    speed=max(0,speed-sum(all_mode_speed_penalties(engine,actor).values()))
    return Climbing(speed, without_check, disabled,
                    tuple(value for value in ('STR', 'DEX') if value in abilities), tuple(sorted(modes)),
                    choice_name, choice_source, ceiling, virtual_wall, virtual_hold, physical_disabled)


def eligible(engine, actor):
    """One posture/capability gate for climbing menus, quotes and execution."""
    from .motion import independent_speed_blocked
    if ((not engine.grid.roof_surfaces and not profile(engine, actor).virtual_wall) or not actor.active or actor.current_hp <= 0
            or (independent_speed_blocked(engine,actor) if profile(engine,actor).speed_ft else engine._effective_speed(actor)<=0) or profile(engine, actor).disabled):
        return False
    from .typed_executor import condition_rules
    return (not engine._has_condition(actor, 'condition:core.prone')
            and not engine._has_condition(actor, 'condition:typed.prone')
            and not any(row.get('no_actions') or row.get('speed_zero') or row.get('ends_on_stand_up')
                        for row in condition_rules(actor, engine=engine)))


def step_mode(engine, actor, previous, destination):
    """A level supported approach uses walking Speed and walking surcharges.

    Leaving or regaining a grip uses the climbing allowance, including the
    level lip step onto a roof. A Climb Speed cannot pay for a long ground walk.
    """
    from .falling import supported
    return ('walk' if previous.z == destination.z
            and supported(engine, actor, previous) and supported(engine, actor, destination) else 'climb')


def max_remaining(engine, actor):
    """Maximum shared allowance for a route that mixes walking and climbing."""
    from .flight import remaining
    walking = remaining(engine, actor, 'walk')
    return max(walking, remaining(engine, actor, 'climb')) if eligible(engine, actor) else walking


def step_remaining(engine, actor, previous, destination):
    """Remaining allowance for this actual edge, after already executed steps."""
    from .flight import remaining
    return remaining(engine, actor, step_mode(engine, actor, previous, destination))


def faces(engine, actor, at, *, include_virtual=True):
    """Live solid building faces within a cardinal handhold of the footprint.

    The sealed roof stays after a wall is destroyed; the destroyed wall no
    longer supplies handholds. An opening is not an invisible climbing ladder.
    At the eave, a solid roof lip can bridge the final five-foot grid step
    above a real wall. It cannot bridge a taller gap or replace a missing wall.
    """
    virtual = include_virtual and profile(engine, actor).virtual_wall
    if not engine.grid.roof_surfaces or profile(engine, actor).physical_disabled:
        if virtual:
            from types import SimpleNamespace
            return (SimpleNamespace(id='virtual-wall', climb_check='none'),)
        return ()
    found = {}
    if profile(engine, actor).ceiling:
        # A ceiling grip touches the slab from below, never its top. The same
        # footprint volume is used by slab collision and route admission.
        top = (max(p[2] for p in engine._actor_volume(actor, at)) + 1) * 5
        for x, y in engine._actor_cells(actor, at):
            roof = engine.grid.roof_at(x, y)
            if roof is not None and roof.solid_at(x, y) and top == roof.walk_ft:
                found[roof.id] = roof
    for x, y in engine._actor_cells(actor, at):
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            nx, ny = x + dx, y + dy
            roof = engine.grid.roof_at(nx, ny)
            if roof is None or at.z * 5 > roof.walk_ft:
                continue
            z = min(at.z, roof.walk_ft // 5 - 1)
            wall = engine.grid.terrain_at((nx, ny, z), 'BLOCKED')
            lip = (z == roof.walk_ft // 5 - 1 and z > 0 and roof.solid_at(nx, ny)
                   and engine.grid.terrain_at((nx, ny, z - 1), 'BLOCKED'))
            if wall or lip:
                found[roof.id] = roof
    physical = tuple(found[key] for key in sorted(found))
    if physical or not virtual:
        return physical
    # Optional air does not replace a real wall's checks or Climb Speed pricing.
    from types import SimpleNamespace
    return (SimpleNamespace(id='virtual-wall', climb_check='none'),)


def can_hold(engine, actor, at=None):
    """A recorded grip survives turns while the face and the creature allow it."""
    at = at or actor.position
    if not actor.climbing or not eligible(engine, actor):
        return False
    return bool(faces(engine, actor, at, include_virtual=profile(engine, actor).virtual_hold))


def step_allowed(engine, actor, previous, destination, *, observed=False):
    from .falling import supported
    from .flight import profile as flight_profile
    from .creature_passage import volume_geometry
    if not eligible(engine, actor):
        return False
    if destination.z > previous.z and not flight_profile(engine, actor).can_ascend:
        return False
    delta = (destination.x - previous.x, destination.y - previous.y, destination.z - previous.z)
    if delta[2] and (delta[0] or delta[1]) and not profile(engine, actor).virtual_wall:
        return False  # climb the face, then step onto the top; no diagonal wall clipping
    if not engine.grid.volume_step_legal(previous, destination, footprint=engine._footprint(actor),
            occupied_cells=volume_geometry(engine, actor, observed=observed)[0]):
        return False
    before, after = supported(engine, actor, previous), supported(engine, actor, destination)
    if delta[2]:
        return bool(faces(engine, actor, previous) and faces(engine, actor, destination))
    return (before or bool(faces(engine, actor, previous))) and (after or bool(faces(engine, actor, destination)))


def extra_multiplier(engine, actor, previous, destination):
    from .falling import supported
    if (profile(engine, actor).virtual_wall
            and not (faces(engine, actor, previous, include_virtual=False)
                     and faces(engine, actor, destination, include_virtual=False))):
        from .motion import ignores_difficult
        return 0 if ignores_difficult(engine, actor) else 1
    if profile(engine, actor).speed_ft:
        return 0
    climbing = (previous.z != destination.z
                or (not supported(engine, actor, previous) and not supported(engine, actor, destination)))
    return int(climbing)


def valid_climb(engine, actor, path):
    from .falling import supported
    if (not eligible(engine, actor) or not path
            or (not supported(engine, actor, path[0]) and not can_hold(engine, actor))):
        return False
    return any(step_mode(engine, actor, a, b) == 'climb' for a, b in zip(path, path[1:])) or actor.climbing


def routes(engine, actor, path_selector=None):
    """Bounded native climb routes, retaining only routes that actually climb.

    Equal-cost alternatives are retained in a predecessor DAG and offered to the
    same native route selector the other movement searches use, so the safer of
    two equally short climb approaches wins here too.
    """
    from . import flight
    from .falling import supported
    from .voluntary_movement import fear_sources, blocking_source
    if (not eligible(engine, actor)
            or (not supported(engine, actor) and not can_hold(engine, actor))):
        return {}
    allowances = {mode: flight.remaining(engine, actor, mode) for mode in ('walk', 'climb')}
    allowance = max(allowances.values())
    if allowance < engine.grid.square_size_ft:
        return {}
    start = (*point(actor.position), bool(actor.climbing))
    costs, parents, predecessors, positions = {start: 0}, {}, {}, {start[:3]: actor.position}
    queue = [(0, start)]
    virtual = profile(engine, actor).virtual_wall
    ceiling = max((roof.walk_ft // 5 for roof in engine.grid.roof_surfaces), default=0)
    if virtual:
        ceiling = max(ceiling, actor.position.z + allowance // engine.grid.square_size_ft)
    fears = fear_sources(engine, actor)
    offsets = tuple((x, y, 0) for x in (-1, 0, 1) for y in (-1, 0, 1) if x or y) + ((0, 0, -1), (0, 0, 1))
    if virtual:
        offsets = tuple((x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if x or y or z)
    edge_cache = {}
    def position(cell):
        key = cell[:3]
        if key not in positions:
            positions[key] = Position(x=key[0], y=key[1], z=key[2])
        return positions[key]
    while queue:
        spent, cell = heapq.heappop(queue)
        if spent != costs[cell] or spent >= allowance:
            continue
        a = position(cell)
        for dx, dy, dz in offsets:
            xyz = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
            if not (0 <= xyz[0] < engine.grid.width and 0 <= xyz[1] < engine.grid.height and 0 <= xyz[2] <= ceiling):
                continue
            b = position(xyz)
            mode = step_mode(engine, actor, a, b)
            nxt = (*xyz, cell[3] or mode == 'climb')
            key = (cell[:3], xyz)
            if key not in edge_cache:
                edge_cache[key] = step_allowed(engine, actor, a, b, observed=True)
            if not edge_cache[key] or (fears and blocking_source(engine, actor, a, b, sources=fears)):
                continue
            cost = spent + flight.step_cost(engine, actor, a, b, 'climb')
            if cost > allowances[mode]:
                continue
            if cost < costs.get(nxt, allowance + 1):
                costs[nxt], parents[nxt], predecessors[nxt] = cost, cell, {cell}
                heapq.heappush(queue, (cost, nxt))
            elif cost == costs.get(nxt):
                predecessors[nxt].add(cell)
    from types import MappingProxyType
    selected = path_selector(start, MappingProxyType({cell: frozenset(rows) for cell, rows in predecessors.items()}),
                             MappingProxyType(costs), MappingProxyType(parents)) if path_selector else {}
    from .creature_passage import endpoint_volumes
    occupied = endpoint_volumes(engine, actor, observed=True)
    result = {}
    for cell in sorted(parents):
        at = position(cell)
        if not cell[3] or at == actor.position or not engine.grid.volume_legal(at, footprint=engine._footprint(actor), occupied_cells=occupied):
            continue
        chain = [cell]
        while chain[-1] != start:
            chain.append(parents[chain[-1]])
        if cell in selected:
            chosen = selected[cell]
            if chosen[0] != start or chosen[-1] != cell or any(a not in predecessors.get(b, ()) for a, b in zip(chosen, chosen[1:])):
                raise ValueError('Route selection must use an equal-cost native path')
            chain = list(reversed(chosen))
        path = tuple(position(c) for c in reversed(chain))
        result[at] = (path, costs[cell], 'climb')
    return result


def valid_drop(engine, actor, path):
    """A deliberate jump down walks to an edge; falling owns the descent."""
    from .falling import supported
    return (len(path) >= 2 and all(p.z == path[0].z for p in path)
            and all(supported(engine, actor, p) for p in path[:-1])
            and not supported(engine, actor, path[-1]) and path[-1].z > 0)


def needs_check(engine, actor, previous, destination):
    """Only an actual marked climbing edge uses the route's one check."""
    if profile(engine, actor).without_check or step_mode(engine, actor, previous, destination) == 'walk':
        return False
    rows = faces(engine, actor, destination) or faces(engine, actor, previous)
    return any(row.climb_check != 'none' for row in rows)


def _check_ability(engine, actor, capability, intent, bonuses):
    if len(capability.check_abilities) == 1:
        return capability.check_abilities[0]
    from .ext.needle import ask, answered, answerable, checkpoint_id
    intent = intent or getattr(engine, '_active_intent', None)
    if intent is None:
        raise ValueError('A climbing ability choice requires a recorded movement intent')
    checkpoint = checkpoint_id(engine, 'CLIMB_ABILITY', actor.entity_id)
    choice = 'choice:needle.climbing.ability'
    automatic = not answerable(engine, actor)
    # The owning ability (when a provider named one) is shown to the player, and the
    # climber is carried as the affected creature, so the table's question can say
    # whose ability opens the choice and who it applies to.
    ability_name = capability.check_choice_name or 'Climbing ability'
    selected = ask(engine, intent, checkpoint, actor, choice, list(capability.check_abilities),
        labels={ability: f'{"Strength" if ability == "STR" else "Dexterity"} (Athletics) {bonuses[ability]:+d}'
                for ability in capability.check_abilities},
        preferred=sorted(capability.check_abilities, key=lambda ability: (-bonuses[ability], ability)),
        automatic=automatic, allow_decline=False, target_id=actor.entity_id,
        name=ability_name, feature_id=capability.check_choice_source,
        prompt=(f'{ability_name} lets {actor.display_name} choose Strength or Dexterity for this climbing '
                'Athletics check.' if capability.check_choice_name
                else f'{actor.display_name} chooses Strength or Dexterity for this climbing Athletics check.'),
        prompt_context={'source_definition_id': 'system:combat.climbing', 'action_name': 'Climbing check',
                        'action_actor_id': actor.entity_id})
    if (not automatic and not answered(engine, checkpoint, actor, choice)) or len(selected) != 1:
        raise ValueError('Choose the ability for this climbing check before continuing')
    return selected[0]


def climb_check(engine, actor, previous, destination, intent):
    """Check once per chosen climbing route, after normal movement reactions.

    A failed attempt spends this step's movement and keeps the previous grip.
    This failure-cost convention prevents free repeated attempts in one turn.
    """
    if not needs_check(engine, actor, previous, destination):
        return True
    from .ability_checks import skill_bonus
    from .typed_executor import Context, check_modes
    from .gate2_runtime_models import ActionDefinition, EconomyKind
    from . import ext
    from .roll_checkpoints import rewrite_d20
    source = 'system:combat.climbing'
    capability = profile(engine, actor)
    strength_modifier = (actor.strength_score - 10) // 2
    base = skill_bonus(engine, actor, 'Athletics', strength_modifier)
    bonuses = {'STR': base, 'DEX': base + (actor.dexterity_score - 10) // 2 - strength_modifier}
    ability = _check_ability(engine, actor, capability, intent, bonuses)
    bonus = bonuses[ability]
    # An ordinary check has its own provenance. Do not borrow a weapon/spell
    # action merely to obtain a Context: scoped bonuses must see this check.
    typed = {'source': source, 'numbers': {'pb': actor.proficiency_bonus,
             'ability_mods': {'STR': strength_modifier, 'DEX': (actor.dexterity_score - 10) // 2}},
             'effects': [{'type': 'ability_check', 'ability': ability, 'skill': 'Athletics',
                          'hazards': ['climbing']}]}
    action = ActionDefinition(source_definition_id=source, display_name='Climbing check',
                              owner_id=actor.entity_id, economy=EconomyKind.NONE,
                              resolution_kind='CHECK', target_kind='SELF', parameters={'typed': typed})
    context = Context(engine, actor, action, intent, typed, [actor], actor)
    for value in ext.run_strict('check_bonus', context, actor):
        if type(value) is not int:
            raise ValueError('Check bonuses must be integer modifiers')
        bonus += value
    modes = check_modes(actor, ability, 'Athletics', engine=engine, hazards=('climbing',))
    modes.update(capability.check_modes)
    modes.update(value for value in ext.run('skill_check_mode', context, actor, ability, 'Athletics')
                 if value in {'ADVANTAGE', 'DISADVANTAGE'})
    mode = next(iter(modes)) if len(modes) == 1 else 'NORMAL'
    with engine.d20_scope({'kind': 'check', 'actor_id': actor.entity_id, 'source_id': source,
                          'source_actor_id': actor.entity_id, 'ability': ability, 'skill': 'Athletics', 'dc': 15}):
        roll = engine.roller.raw_d20(modifier=bonus, actor_id=actor.entity_id, reason=f'CHECK:{source}:Athletics', mode=mode)
        roll = rewrite_d20(engine, roll)
        roll = ext.floored(engine, actor, roll, 15)
    engine._record_roll(roll)
    success = roll.total >= 15
    engine._append_event('CHECK_ROLLED', source, actor_id=actor.entity_id,
        payload={'actor': roll.model_dump(mode='json'), 'dc': 15, 'success': success, 'check': 'Athletics', 'ability': ability,
                 'log': f'{actor.display_name} attempts the difficult climb (Athletics DC 15): ' + ('success.' if success else 'no progress; movement for the attempt is spent.')})
    return success
