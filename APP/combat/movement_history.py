"""Read-only movement endpoint history for Gate4 contexts and controllers.

The event journal already owns this history. Nothing is added to fight state;
reloads derive the same integer positions and manual movement remains legal.
"""
from .gate2_runtime_models import Position


def endpoints(engine, actor_id):
    """Decision endpoints in the current uninterrupted willing-movement segment.

    A turn boundary, non-move intent, reaction or changed creature position/HP/
    condition permits reconsidering a retreat. Intermediate path squares are
    not forbidden: a route may cross old ground to reach a new endpoint.
    """
    positions = set()
    pending_start = None
    for event in reversed(engine.events):
        kind = event.event_type
        if kind in {'TURN_STARTED', 'TURN_ENDED', 'REACTION_RESOLVED',
                    'DAMAGE_COMMITTED', 'HEALING_APPLIED', 'CONDITION_APPLIED', 'CONDITION_REMOVED'}:
            break
        if kind == 'INTENT_ACCEPTED':
            if event.payload.get('kind') != 'MOVE':
                break
            if pending_start is not None:
                positions.add(pending_start)
                pending_start = None
        if kind != 'MOVEMENT_COMMITTED':
            continue
        if event.actor_id != actor_id and event.payload.get('carried_by') == actor_id:
            # The companion follows this same decision; it is not a new
            # tactical opportunity that makes revisiting an endpoint useful.
            continue
        if event.actor_id != actor_id or event.source_definition_id != 'system:combat.movement':
            break
        if pending_start is not None:
            positions.add(pending_start)
        path = event.payload.get('path') or ()
        start = path[0] if path else None
        # Damage during a move is logged before its final receipt. Defer that
        # receipt's start until its accepted MOVE: a boundary in between drops
        # the pre-boundary start but retains the post-boundary destination.
        pending_start = ((int(start['x']), int(start['y']), int(start.get('z', 0)))
                         if start is not None else None)
        cell = event.payload.get('destination')
        if cell is not None:
            positions.add((int(cell['x']), int(cell['y']), int(cell.get('z', 0))))
    else:
        # Older retained journals can begin with a receipt, without its intent.
        if pending_start is not None:
            positions.add(pending_start)
    return tuple(Position(x=x, y=y, z=z) for x, y, z in sorted(positions))
