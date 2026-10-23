"""Owner route preference for Factory fighters; fixtures keep their old routes."""
from . import hook


@hook('native_route_selection')
def select(engine, actor):
    if actor.entity_id not in getattr(engine, 'typed_actor_ids', set()):
        return None
    from ..movement_routes import safe_selector
    return safe_selector(engine, actor)
