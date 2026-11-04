from .service import CharacterBuilderService
from .origin_insight_route_binding import bind_background_scoped_origin_insight


_original_background_route_resolver = CharacterBuilderService._resolved_background_routes


def _resolved_background_routes_with_native_insight_binding(
    locked_choices,
    supplied,
    *,
    authority,
):
    return bind_background_scoped_origin_insight(
        _original_background_route_resolver,
        locked_choices,
        supplied,
        authority=authority,
    )


CharacterBuilderService._resolved_background_routes = staticmethod(
    _resolved_background_routes_with_native_insight_binding
)

__all__ = ["CharacterBuilderService"]
