"""Labelled walking features from personally known frames (core, pure).

Shared by the knowledge plug-in (combat/ext/ai_movement.py) and the core walking
decision (combat/ground_decision.py). Core must not import plug-in modules, so
the feature definitions live here. Integer differences only: no engine access,
unseen bounds or future rolls.
"""
from .ai_observation import point


def occupied_harm(frame):
    # Memory is advisory, not a damage forecast. Once an actor has moved away
    # from the hurt square we do not repeatedly reward moving farther away.
    return max((h.damage for h in frame.harms if h.position == frame.position), default=0)


def movement_features(frame, candidate):
    """Labelled integer differences; no engine, unseen bounds or future rolls."""
    if candidate.destination is None:
        return {}
    destination = point(candidate.destination)
    squares = {s.position: s for s in frame.squares}
    square = squares.get(destination)
    current = squares.get(frame.position)
    damage = occupied_harm(frame)
    distance = max(abs(destination[i] - frame.position[i]) for i in (0, 1))
    # Require actual horizontal displacement, not unsafe guessed vertical escape.
    escape, stay = 0, 0
    if damage and distance:
        covering = [h for h in frame.harms if h.position == frame.position]
        occupied = set(frame.occupied_at(destination))
        inside = any(occupied.intersection(h.cells) for h in covering)
        complete = all(h.complete_boundary for h in covering)
        if not inside:
            escape = min(100, damage * (8 if complete else 4)) - min(15, candidate.movement_cost_ft // 5)
        else:
            stay = -min(100, damage * 6)
    creatures = [c for c in frame.creatures if c.mode == 'DIRECT' and c.relation == 'ENEMY']
    approach = 0
    if creatures:
        # Approach only personally located enemies; last sightings are beliefs.
        before = min(max(abs(frame.position[i] - c.position[i]) for i in range(3)) for c in creatures)
        after = min(max(abs(destination[i] - c.position[i]) for i in range(3)) for c in creatures)
        approach = max(-5, min(5, before - after))
    from ..gate4_controller import native_flight_position_value
    return {'escape': max(0, escape), 'stay': stay, 'approach': approach,
        'cover': 8 * (int(bool(square and square.cover)) - int(bool(current and current.cover))),
        'flight': native_flight_position_value(candidate),
        'objective': 12 * int(bool(square and square.objective))}
