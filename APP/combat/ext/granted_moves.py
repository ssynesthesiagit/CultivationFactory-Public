"""Shared native movement adapter for guardian_chassis and guardian_patrol.

Interpose keeps its explicit non-provoking default. Patrol callers must pass
provokes=True and their remaining budget_ft, then charge the returned actual cost
and recheck reach/eligibility before attacking (an OA may interrupt the response).
"""
from .. import granted_movement


def destinations(engine, mover, budget_ft, wanted):
    """Observed legal routes using the same Speed, terrain and fear rules as native movement."""
    found = [(mover.position, (mover.position,), 0)] if wanted(mover.position) else []
    intent = getattr(engine, '_active_intent', None)
    if budget_ft <= 0 or intent is None:
        return found
    rows = granted_movement.candidates(engine, mover, budget_ft, intent, 'system:granted_movement')
    found.extend((c.destination, granted_movement.Route(c.canonical_path, c.metadata.get('movement_mode', 'walk')), c.movement_cost_ft)
                 for c in sorted(rows.values(), key=lambda c: (c.movement_cost_ft, c.destination.y, c.destination.x))
                 if wanted(c.destination))
    return found


def commit(engine, mover, path, source, *, budget_ft=None, provokes=False, ignore_oa_from=(), intent=None, mode=None):
    """Commit through native steps, returning actual grant cost; ordinary movement stays unchanged."""
    if not path:
        return 0
    mode = granted_movement.movement_mode(engine, mover, path, mode)
    feet = granted_movement.path_cost(engine, mover, path, mode=mode) if budget_ft is None else budget_ft
    return engine.grant_movement(mover, path, source, feet=feet, intent=intent,
                                 provokes=provokes, ignore_oa_from=ignore_oa_from, mode=mode)


def choose(engine, mover, budget_ft, source, name, *, intent=None, provokes=True, ignore_oa_from=(), action_name=None):
    """Ask the moving creature for an immediate, separate-budget native route.

    Used by Sacred Body and Beast-Echo riders. All observed legal destinations
    remain available; AI ranking reads only enemies the mover can perceive.
    Returns actual feet spent; declining or interrupted movement grants nothing.
    """
    from . import needle
    from ..target_knowledge import can_see
    intent = intent or getattr(engine, '_active_intent', None)
    if intent is None:
        return 0
    moves = granted_movement.candidates(engine, mover, budget_ft, intent, source)
    if not moves:
        return 0
    enemies = [a for a in engine.state.actors.values() if a.active
               and a.team_id != mover.team_id and can_see(engine, mover, a)]
    def score(key):
        cell = moves[key].destination
        return min((engine.grid.distance_ft(cell, a.position) for a in enemies), default=0)
    ordered = sorted(moves, key=lambda key: (-score(key), key))
    exempt_names = [engine.state.actors[a].display_name for a in ignore_oa_from]
    protection = (' without provoking opportunity attacks' if not provokes else
                  ' without provoking opportunity attacks from ' + ', '.join(exempt_names) if exempt_names else '')
    action = engine.action_catalog.get(getattr(engine, '_active_action_source_id', None) or '')
    trigger = action_name or (action.display_name if action is not None else 'the triggering action')
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'GRANTED_DESTINATION', source + ':' + mover.entity_id),
        mover, 'choice:needle.granted_destination', ordered,
        labels={key: f'Move {mover.display_name} to {c.destination.x},{c.destination.y},{c.destination.z}'
                for key, c in moves.items()}, preferred=ordered[:1], allow_decline=True,
        name=name, target_id=mover.entity_id,
        prompt=f'{name}: after {trigger}, choose where {mover.display_name} moves up to {budget_ft} feet'
               f'{protection}. This uses no ordinary movement, Action, Reaction or additional resource; or stay in place.')
    if not picked or picked[0] not in moves:
        return 0
    candidate = moves[picked[0]]
    return commit(engine, mover, candidate.canonical_path, source, budget_ft=budget_ft,
                  intent=intent, provokes=provokes, ignore_oa_from=ignore_oa_from,
                  mode=candidate.metadata.get('movement_mode', 'walk'))
