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
