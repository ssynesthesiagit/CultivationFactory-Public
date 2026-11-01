"""Candidate safety for immobilization and interrupted moves, independent of ability names.

Ordinary movement is unchanged. A zero-step interruption suppresses that route
only while its mechanical surroundings are unchanged. Turn start clears flags.
"""
from typing import Any

from ..canonical import canonical_sha256
from . import hook

FLAG = "movement_safety_blocked"


def edge_key(path):
    """Full 3D first-step identity, independent of a route's final destination."""
    if len(path) < 2:
        return None
    return FLAG + ':edge:' + '>'.join(f'{p.x},{p.y},{p.z}' for p in path[:2])


def _movement_state(engine: Any) -> str:
    """Fingerprint mechanical inputs, excluding counters and our own vetoes.

    Include all actors' conditions, resources and flags: reactions and movement
    plug-ins can depend on them, not just Speed. Grid terrain and persisted
    zones/objects cover occupancy and path changes. A changed input permits a
    fresh attempt; a new decision/event number alone must not permit a retry.
    This is computed only for interrupted routes and stores a string, not state.
    """
    actors = {key: actor.model_dump(mode="json") for key, actor in engine.state.actors.items()}
    for actor in actors.values():
        actor["turn_flags"] = {key: value for key, value in actor["turn_flags"].items()
                               if not key.startswith(FLAG + ":")}
    grid = engine.grid
    # motion.terrain_for temporarily strips difficult costs during execution.
    # Its retained full view also tracks zone resyncs; use the same terrain as
    # menus and reloads without hiding genuine terrain changes.
    costs = getattr(grid, "unimpeded_full_costs", grid.base_movement_cost)
    return canonical_sha256({
        "actors": actors,
        "zones": {key: zone.model_dump(mode="json") for key, zone in engine.state.zones.items()},
        "objects": {key: obj.model_dump(mode="json") for key, obj in engine.state.objects.items()},
        "grid": {"width": grid.width, "height": grid.height, "square_size_ft": grid.square_size_ft,
                 "blocked": sorted(grid.blocked), "opaque": sorted(grid.opaque),
                 "cover": sorted(grid.cover), "qi_hazard": sorted(grid.qi_hazard),
                 "costs": sorted((x, y, cost) for (x, y), cost in costs.items())},
    })


@hook("candidate_allowed")
def movement_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if candidate.kind.value != "MOVE":
        return None
    # Speed has no destination/path dependency. Keep projected actors/origins
    # separate and reuse only inside the unchanged, pure candidate pass.
    from ..read_queries import invariant_memo
    from ..hook_queries import actor_action
    actor_key = actor_action(engine, actor, None, None)
    if invariant_memo(engine, ('movement_safety_speed', actor_key),
                      lambda: engine._effective_speed(actor)) <= 0:
        return False
    # Suppress only unchanged failures. Legacy integer flags lack the blocking
    # state and cannot safely forbid a recovered route in an old saved fight.
    destination = candidate.destination
    key = f"{FLAG}:{actor.position.x},{actor.position.y}>{destination.x},{destination.y}"
    blocked_state = actor.turn_flags.get(key)
    failures = {value for name, value in actor.turn_flags.items()
                if name.startswith(FLAG + ':') and isinstance(value, str)}
    if not failures:
        return None
    state = invariant_memo(engine, ('movement_safety_state', actor_key),
                           lambda: _movement_state(engine))
    if isinstance(blocked_state, str) and blocked_state == state:
        return False
    edge = edge_key(candidate.canonical_path)
    if edge is not None and actor.turn_flags.get(edge) == state:
        return False
    return None


@hook("event")
def interrupted_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if not payload.get("interrupted") or payload.get("cost_ft") != 0 or len(payload.get("path") or []) > 1:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    intent = getattr(engine, "_active_intent", None)
    destination = getattr(intent, "destination", None)
    if actor is not None and destination is not None:
        # A recorded interruption sequence stops this move, not future moves.
        # Do not turn a paid, one-shot response into a persistent route veto.
        # Older receipts from another action retain the normal safety policy.
        accepted = next((event for event in reversed(engine.events)
                         if event.event_type == 'INTENT_ACCEPTED'
                         and event.trigger_or_intent_id == getattr(intent, 'intent_id', None)
                         and event.actor_id == actor.entity_id), None)
        interrupted_at = int(actor.turn_flags.get('movement_interrupted_sequence') or 0)
        if accepted is not None and accepted.sequence < interrupted_at <= engine.state.event_sequence:
            return
        key = f"{FLAG}:{actor.position.x},{actor.position.y}>{destination.x},{destination.y}"
        state = _movement_state(engine)
        actor.turn_flags[key] = state
        candidate = getattr(engine, '_active_candidate', None)
        edge = edge_key(candidate.canonical_path) if candidate is not None else None
        if edge is not None:
            actor.turn_flags[edge] = state
