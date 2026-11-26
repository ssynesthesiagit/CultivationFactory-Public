"""Shared helper: opt-in standing burdens and controller-chosen straight displacement.

Only explicitly sealed effect rows participate. Native posture and forced
movement retain payment, defenses, terrain, reactions and event ownership.
Rows may opt into a caster-relative ``relative_directions`` set containing
``away`` and/or ``toward``. The chooser keeps that heading for the full move;
without the field, every legal compass direction remains available.
"""
from contextvars import ContextVar
from dataclasses import replace

from . import effect, hook

_DIRECTION = ContextVar("directed_forced_movement", default=None)
BURDEN = "condition:typed.standing_burden"
DIRECTIONS = {"north": (0, -1), "northeast": (1, -1), "east": (1, 0),
              "southeast": (1, 1), "south": (0, 1), "southwest": (-1, 1),
              "west": (-1, 0), "northwest": (-1, -1)}


@effect("speed_based_step")
def speed_based_step(ctx, row):
    from .rider_step import step

    basis = row.get("distance_ft")
    if basis not in {"speed", "half_speed"}:
        raise ValueError("speed_based_step requires speed or half_speed")
    feet = ctx.engine._effective_speed(ctx.actor)
    step(ctx, {**row, "distance_ft": feet // 2 if basis == "half_speed" else feet})


@effect("standing_burden")
def standing_burden(ctx, row):
    from ..typed_executor import effect_expiry
    from .condition_ownership import remove_instance

    feet = row.get("extra_ft")
    if type(feet) is not int or feet < 0:
        raise ValueError("standing_burden.extra_ft must be nonnegative integer feet")
    for subject in [ctx.target] if ctx.target is not None else ctx.targets:
        for held in list(subject.conditions.values()):
            if (held.condition_id == BURDEN and held.source_actor_id == ctx.actor.entity_id
                    and held.source_definition_id == ctx.source):
                remove_instance(ctx.engine, subject, held.instance_id, ctx.source)
        ctx.engine._apply_condition(subject, BURDEN, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True),
            data={"extra_ft": feet, **({"elevation_extra_ft": feet} if row.get("elevation") else {}),
                  "label": f"{ctx.action.display_name}: standing costs {feet} extra feet"})


@hook("stand_extra_cost")
def standing_extra(engine, actor):
    # Repeated instances of the same named burden do not stack.
    return max((int(c.data["extra_ft"]) for c in actor.conditions.values()
                if c.condition_id == BURDEN), default=0) or None


@hook("movement_elevation_surcharge")
def elevation_extra(engine, actor, previous, destination, mode):
    return max((int(c.data.get("elevation_extra_ft", 0)) for c in actor.conditions.values()
                if c.condition_id == BURDEN), default=0) or None


@effect("directed_forced_movement")
def directed_forced_movement(ctx, row):
    from ..typed_executor import block_forced_movement

    for subject in [ctx.target] if ctx.target is not None else ctx.targets:
        token = _DIRECTION.set((id(ctx.engine), ctx.source, subject.entity_id,
                                tuple(row.get("relative_directions") or ()), None, row.get("direction_axis")))
        try:
            block_forced_movement(replace(ctx, targets=[subject], target=subject),
                                  {**row, "type": "forced_movement", "direction": "away"})
        finally:
            _DIRECTION.reset(token)


@hook("forced_movement_direction")
def choose_direction(ctx, subject, distance_ft):
    request = _DIRECTION.get()
    if not request or request[:3] != (id(ctx.engine), ctx.source, subject.entity_id):
        return None
    if request[4] is not None:
        return request[4]
    relative_directions = request[3]
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    here = subject.position
    # The caster chooses with their own knowledge. Real hidden occupancy is
    # checked only by native execution, which may stop the selected route.
    occupied = engine._occupied_volumes_except(actor.entity_id, observed=True,
                                               ignore_actor_ids=(subject.entity_id,))
    occupied.update(engine._actor_volume(actor))
    directions = DIRECTIONS
    if request[5] == 'area_path':
        from ..action_geometry import point
        origin = point(engine, actor)
        aim = ctx.damage_cache.get('_checkpoint_aim')
        if aim is None or (aim.x, aim.y) == (origin.x, origin.y):
            raise ValueError('area_path displacement requires a directed area aim')
        ax, ay = aim.x - origin.x, aim.y - origin.y
        # The two lateral headings move away from the travel axis; a creature
        # on the axis may choose either defended side. Off-axis it moves farther
        # onto its existing side, never across the path toward another creature.
        lateral = ((-((ay > 0) - (ay < 0)), (ax > 0) - (ax < 0)),
                   (((ay > 0) - (ay < 0)), -((ax > 0) - (ax < 0))))
        side = ax * (here.y - origin.y) - ay * (here.x - origin.x)
        directions = {name: vector for name, vector in DIRECTIONS.items()
                      if vector in lateral and (side == 0 or side * (ax * vector[1] - ay * vector[0]) > 0)}
    options = []
    for name, (dx, dy) in directions.items():
        x, y = here.x + dx, here.y + dy
        if x < 0 or y < 0:
            continue
        end = Position(x=x, y=y, z=here.z)
        if engine.grid.volume_step_legal(here, end,
                occupied_cells=occupied,
                footprint=engine._footprint(subject)):
            options.append(name)
    if not options:
        # A constrained heading policy cannot degrade into ordinary away-from-caster movement.
        # The shared forced-movement contract treats (0, 0) as an explicit stop.
        return (0, 0) if request[5] == 'area_path' else None
    away = ((here.x > actor.position.x) - (here.x < actor.position.x),
            (here.y > actor.position.y) - (here.y < actor.position.y))
    if relative_directions:
        if not set(relative_directions) <= {"away", "toward"}:
            raise ValueError("relative_directions must contain away and/or toward")
        toward = (-away[0], -away[1])
        legal_vectors = {DIRECTIONS[name] for name in options}
        relative_vectors = {name: vector for name, vector in (("away", away), ("toward", toward))
                            if name in relative_directions and vector in legal_vectors}
        if not relative_vectors:
            return None
        options = list(relative_vectors)
        preferred = ["away"] if "away" in options else []
    else:
        relative_vectors = {}
        preferred = [name for name in options if DIRECTIONS[name] == away][:1]
    labels = ({"away": f"Push {subject.display_name} away from you (up to {distance_ft} feet)",
               "toward": f"Pull {subject.display_name} toward you (up to {distance_ft} feet)"}
              if relative_directions else
              {name: f"Move {subject.display_name} {name} (up to {distance_ft} feet, stopping at obstructions)"
               for name in options})
    prompt = (f"{ctx.action.display_name}: choose to push {subject.display_name} away from you or pull them toward you, "
              f"up to {distance_ft} feet. A blocked route stops early; no extra cost."
              if relative_directions else
              f"{ctx.action.display_name}: choose one direction to move {subject.display_name} "
              f"{distance_ft} feet without provoking Opportunity Attacks. A blocked route stops early; no extra cost.")
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "directed_movement", subject.entity_id), actor,
        "choice:needle.directed_movement", options, preferred=preferred,
        labels=labels, target_id=subject.entity_id,
        name=ctx.action.display_name, feature_id=ctx.source,
        prompt=prompt)
    vector = relative_vectors[chosen[0]] if chosen and relative_directions else DIRECTIONS[chosen[0]] if chosen else None
    if vector is not None:
        _DIRECTION.set((*request[:4], vector, request[5]))
    return vector


@hook('forced_movement_distance')
def optional_displacement_distance(ctx, subject, row, maximum_ft):
    """An opted-in push chooses its distance in map-square increments."""
    if not row.get('optional_distance_ft'):
        return None
    from .needle import ask, checkpoint_id
    feet = list(range(maximum_ft // 5 * 5, -1, -5))
    picked = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'optional_displacement', ctx.source, subject.entity_id),
        ctx.actor, 'choice:needle.displacement_distance', [str(ft) for ft in feet],
        labels={str(ft):f'Move {subject.display_name} {ft} feet' for ft in feet},
        minimum=1, maximum=1, preferred=[str(feet[0])],
        prompt=f'{ctx.action.display_name}: choose how far to push {subject.display_name}, up to {maximum_ft} feet.')
    return int(picked[0]) if picked else 0
