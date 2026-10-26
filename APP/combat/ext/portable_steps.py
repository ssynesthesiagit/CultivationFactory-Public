"""Sealed portable Combustive Step: one route query for menus and execution.

The legacy portable adapter delegates its movement primitive here. Factory typed
steps keep their existing implementation. This plug-in only filters actions the
actor owns with the sealed C3AR movement resolver; other actions are untouched.
"""
from . import hook


def route(engine, actor, destination, feet=15):
    """Observed ground route, priced as movement rather than a radius or teleport.

Shared by the portable candidate hook and CharacterCombatRuntimeEngine. Hidden
occupants are handled at native contact, without disclosing them in the menu.
"""
    if destination is None or not actor.active:
        return None
    if destination == actor.position:
        return (actor.position,), 0  # "up to" permits staying for the attack rider
    if destination.z != actor.position.z or actor.position.z or engine._effective_speed(actor) <= 0:
        return None
    from ..creature_passage import geometry
    from ..voluntary_movement import edge_predicate
    from ..posture import walking_extra
    occupied, end_blocked, difficult, _ = geometry(engine, actor, observed=True)
    return engine.grid.shortest_path(
        actor.position, destination,
        occupied_cells=occupied, end_blocked_cells=end_blocked,
        difficult_cells=engine._hostile_difficult_cells(actor) | difficult,
        max_cost_ft=feet // engine._drag_multiplier(actor),
        footprint=engine._footprint(actor),
        extra_step_multiplier=walking_extra(engine, actor),
        edge_allowed=edge_predicate(engine, actor),
    )


@hook('candidate_allowed')
def candidate_allowed(engine, actor, candidate, action):
    if (action is None or action.resolution_kind != 'C3AR_COMBUSTIVE_STEP'
            or action.source_definition_id not in actor.action_ids):
        return None
    return route(engine, actor, candidate.destination) is not None


def commit(engine, actor, destination, source, intent):
    """Spend the separate 15-foot grant through native steps and recorded hazards."""
    found = route(engine, actor, destination)
    if found is None:
        raise ValueError('Combustive Step destination is not reachable within 15 feet')
    path, _ = found
    engine.grant_movement(actor, path, source, feet=15, intent=intent, provokes=False, mode='walk')
