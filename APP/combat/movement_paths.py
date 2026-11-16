"""Chosen physical paths shared by plug-ins, native grants and typed pushes.

resolve returns budget feet spent: terrain/drag cost for willing/granted paths,
physical distance for forced paths. Call in an accepted transaction; callers own
their ability's consent, activation cost and passage entitlement. Willing paths
spend ordinary movement; granted paths use an explicit pool without spending it.
Forced paths require a source actor and apply the usual forced-movement reactions
once, then ignore Speed, difficult terrain, Frightened and Opportunity Attacks.
All modes validate full footprints at every step and record their actual path.
A forced path given the caller's resolution Context also runs the moved
creature's forced_movement_reduction hooks on it, in the same order and scope a
typed push or pull uses (typed_executor._push).
"""
from .gate2_runtime_models import Position


def resolve(engine, actor, path, source, *, kind='willing', feet=None, intent=None,
            provokes=True, ignore_oa_from=(), source_actor_id=None, ctx=None):
    from .ext import CheckpointError
    try:
        return _resolve(engine, actor, path, source, kind=kind, feet=feet, intent=intent,
            provokes=provokes, ignore_oa_from=ignore_oa_from, source_actor_id=source_actor_id, ctx=ctx)
    except CheckpointError:
        raise
    except Exception as exc:
        raise CheckpointError(f'Movement path failed: {exc}') from exc


def _resolve(engine, actor, path, source, *, kind, feet, intent, provokes, ignore_oa_from, source_actor_id, ctx=None):
    if kind not in {'willing', 'granted', 'forced'} or not isinstance(source, str) or not source:
        raise ValueError('A movement path needs its source and a supported movement kind')
    from .granted_movement import Route
    selected_mode = path.mode if isinstance(path, Route) else None
    path = tuple(path)
    if (not path or any(not isinstance(p, Position) for p in path) or path[0] != actor.position
            or any(max(abs(a.x-b.x), abs(a.y-b.y), abs(a.z-b.z)) != 1 for a, b in zip(path, path[1:]))):
        raise ValueError('A movement path must start here and use adjacent spaces')
    intent = intent or getattr(engine, '_active_intent', None)
    if intent is None:
        raise ValueError('A movement path requires an active action')
    if kind != 'forced':
        from .granted_movement import resolve_path, movement_mode
        if kind == 'willing':
            if feet is not None:
                raise ValueError('Willing movement uses the creature\'s ordinary movement allowance')
            from .flight import remaining
            feet = remaining(engine, actor, movement_mode(engine, actor, path, selected_mode))
        return resolve_path(engine, actor, path, source, feet=feet, intent=intent,
            provokes=provokes, ignore_oa_from=ignore_oa_from, use_movement=kind == 'willing', mode=selected_mode)
    if source_actor_id not in engine.state.actors:
        raise ValueError('Forced movement requires the creature causing it')
    maximum = (len(path)-1) * engine.grid.square_size_ft
    feet = maximum if feet is None else feet
    if type(feet) is not int or feet < 0:
        raise ValueError('Forced movement requires nonnegative integer feet')
    if not actor.active or min(feet, maximum) < engine.grid.square_size_ft:
        return 0
    from . import typed_reactions
    from .technique_interception import forced_distance, movement_committed
    feet = forced_distance(engine, source_actor_id, source, feet, actor.entity_id)
    from .reaction_trigger import trigger_scope
    with trigger_scope(engine, 'FORCED_MOVEMENT', actor_id=source_actor_id,
                       target_id=actor.entity_id, source_id=source, roll_kind=''):
        remaining = typed_reactions.on_forced_movement(engine, actor, engine.state.actors[source_actor_id], min(feet, maximum))
    remaining = _reduced_by_hook(actor, ctx, remaining)
    if actor.position != path[0] or not actor.active:
        return 0
    count = max(0, remaining // engine.grid.square_size_ft)
    if not count:
        return 0
    actual, blocked = forced_steps(engine, actor, path[1:count+1], source, intent, count, report_contact=True)
    movement_committed(engine, source_actor_id, source, actor.entity_id, (len(actual)-1) * engine.grid.square_size_ft)
    return (len(actual)-1) * engine.grid.square_size_ft


def _reduced_by_hook(actor, ctx, remaining):
    """The moved creature's own reductions, exactly as typed_executor._push applies them: the hooks run on
    the caller's resolution Context while ``ctx.forced_movement_distance_ft`` holds the distance left after
    the ordinary forced-movement reactions, and the Context's field is restored whatever happens. Without a
    caller Context (engine.move_path) no reduction hook can run and the distance is unchanged.
    """
    if ctx is None:
        return remaining
    from . import ext
    try:
        ctx.forced_movement_distance_ft = remaining
        after = max(0, remaining - sum(int(n or 0) for n in ext.run('forced_movement_reduction', ctx, actor)))
    finally:
        ctx.forced_movement_distance_ft = None
    if ext.run_strict('forced_movement_reduced', ctx, actor, remaining, after):
        raise ValueError('forced_movement_reduced providers must return None')
    return after


def landed_forced_step(engine, actor, previous, destination, *, interrupt_drag=True):
    """Shared drag/push landing: typed areas, map hazards and legacy zones.

    Preexisting Grappled/Speed 0 does not prevent displacement. Newly inflicted
    damage (including Temporary HP), incapacity or Prone stops a dragging path.
    Pushes/pulls keep their prescribed distance through those effects; explicit
    zone stops, displacement, death and the end of combat still interrupt them.
    """
    from . import zones
    from .typed_executor import condition_rules
    from .movement_steps import landed
    landed(engine, actor, previous, destination, getattr(engine, '_active_intent', None), forced=True)
    before = len(engine.events)
    speed = engine._effective_speed(actor)
    rules = condition_rules(actor)
    stopped = zones.on_step(engine, actor, previous, destination, forced=True,
                            interrupt_harm=interrupt_drag)
    if actor.active and actor.position == destination:
        engine._resolve_qi_hazard(actor)
        engine._resolve_zone_entry_triggers(actor)
        engine._remove_zone_leave_conditions(actor)
    new_rules = condition_rules(actor)
    return (stopped or not actor.active or actor.position != destination
        or (engine.state.terminal_result is not None and not getattr(engine, '_final_rider_active', False))
        or (interrupt_drag and ((speed > 0 and engine._effective_speed(actor) <= 0)
        or any(not any(row.get(key) for row in rules) and any(row.get(key) for row in new_rules)
               for key in ('no_actions', 'ends_on_stand_up'))
        or any(ev.event_type == 'DAMAGE_COMMITTED' and actor.entity_id in ev.target_ids
               and int(ev.payload.get('reduced_to', 0)) > 0 for ev in engine.events[before:]))))


def forced_steps(engine, actor, steps, source, intent, maximum_steps, *, report_contact=False):
    """Internal shared executor after forced-movement reactions reduced distance.

    Typed push/pull feeds its directional route here; plug-ins use resolve above.
    Returns (actual path, collision square). Separate forced checkpoints prevent
    willing-only riders from answering a push. Existing zone effects resolve first
    at each landed step, so later callbacks cannot spend against a stale mover.
    """
    from .movement_steps import checkpoint
    from . import zones
    path, blocked, interruptions = [actor.position], None, []
    for nxt in steps:
        previous = path[-1]
        def valid():
            return actor.active and actor.position == previous and (
                engine.state.terminal_result is None or getattr(engine, '_final_rider_active', False))
        if not valid():
            break
        if not engine.grid.volume_step_legal(previous, nxt, occupied_cells=engine._occupied_volumes_except(actor.entity_id),
                                      footprint=engine._footprint(actor)):
            blocked = nxt
            break
        interruptions = checkpoint(engine, actor, previous, nxt, intent, point='forced_movement_attempt',
            travelled_ft=(len(path)-1)*engine.grid.square_size_ft,
            remaining_ft=(maximum_steps-len(path)+1)*engine.grid.square_size_ft, source_id=source)
        if interruptions or not valid():
            break
        if not engine.grid.volume_step_legal(previous, nxt, occupied_cells=engine._occupied_volumes_except(actor.entity_id),
                                      footprint=engine._footprint(actor)):
            blocked = nxt
            break
        actor.position = nxt
        path.append(nxt)
        if landed_forced_step(engine, actor, previous, nxt, interrupt_drag=False):
            break
        interruptions = checkpoint(engine, actor, previous, nxt, intent, point='forced_movement_step',
            travelled_ft=(len(path)-1)*engine.grid.square_size_ft,
            remaining_ft=(maximum_steps-len(path)+1)*engine.grid.square_size_ft, source_id=source)
        if interruptions:
            break
    if blocked is not None and report_contact:
        engine._record_movement_collision(actor, blocked)
    engine._append_event('MOVEMENT_COMMITTED', source, actor_id=actor.entity_id, payload={
        'destination': actor.position.model_dump(mode='json'),
        'path': [p.model_dump(mode='json') for p in path], 'cost_ft': 0, 'forced': True,
        **({'interruptions': interruptions} if interruptions else {})})
    if len(path) > 1 and actor.active:
        zones.on_moved(engine, actor, path[0], actor.position, forced=True, triggers=False)
    return path, blocked
