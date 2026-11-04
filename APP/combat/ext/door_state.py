"""Shared attached-door state changes for ordinary interaction and Thread the Object."""
from ..object_rules import simple_door_state


def closing_blocked(engine, obj):
    """A closing door must not occupy a creature or another standing object."""
    from ..object_geometry import target_cells
    cells = {(p.x, p.y) for p in target_cells(engine, obj)}
    return (any(cells.intersection(engine.grid.footprint_cells(a.position, engine._footprint(a)))
                for a in engine.state.actors.values() if a.active)
            or any(cells.intersection((p.x, p.y) for p in target_cells(engine, other))
                   and (obj.position.z == other.position.z
                        or (obj.position.z * 5 < other.position.z * 5 + (other.height_ft or 5)
                            and other.position.z * 5 < obj.position.z * 5 + (obj.height_ft or 5)))
                   for other in engine.state.objects.values()
                   if other.object_id != obj.object_id and not other.destroyed))


def change_door(engine, actor, obj, opening, source):
    """Event the integer door state and immediately rebuild movement/sight/effect blockers."""
    from .. import zones
    state = simple_door_state(obj.component or {})
    if state is None or obj.destroyed:
        raise ValueError("This is not a simple door.")
    if state['door_locked']:
        raise ValueError("Locked: this door cannot be opened or closed by simple interaction.")
    if state['door_jammed']:
        raise ValueError("Stuck: this door cannot be opened or closed by simple interaction.")
    if not opening and closing_blocked(engine, obj):
        raise ValueError("There is no space to close this door: a creature or object is in the opening.")
    component = {**obj.component, 'door_open': int(opening), 'blocks': not opening}
    engine._update_object(obj.model_copy(update={'component': component}), source, actor.entity_id)
    zones.sync_walls(engine)
