from __future__ import annotations

from typing import Any, Callable


PUBLIC_ORIGIN_INSIGHT_PREFIX = "tianxia.origin_insight."
NATIVE_ORIGIN_INSIGHT_SEGMENT = ".origin_insight."


def bind_background_scoped_origin_insight(
    resolver: Callable[..., dict[str, Any]],
    locked_choices: dict[str, list[str]],
    supplied: dict[str, Any],
    *,
    authority: Any,
) -> dict[str, Any]:
    """Translate the creator's stable origin-Insight ID to native authority.

    CAT2 exposes owner-facing origin Insights under the public
    ``tianxia.origin_insight.<slug>`` namespace. The native non-Sphere state
    authority scopes the same exact authored choice to its Background as
    ``<background_id>.origin_insight.<slug>``. The Character Builder already
    validates the selected Background, route Sphere, route Talent, and exact
    published route. This adapter performs only the deterministic namespace
    binding after that validation; it never accepts a name, fuzzy match, or
    unknown authority record.
    """

    routes = resolver(locked_choices, supplied, authority=authority)
    selected = routes.get("origin_insight_choice_id")
    background_ids = locked_choices.get("background_choice") or []
    if not selected or len(background_ids) != 1:
        return routes

    background_id = background_ids[0]
    exact = authority.background_route_authority.get(background_id) or {}
    exact_ids = {
        row.get("origin_insight_choice_id")
        for row in exact.get("origin_insight_options") or []
        if isinstance(row, dict) and row.get("origin_insight_choice_id")
    }
    if selected in exact_ids or not selected.startswith(PUBLIC_ORIGIN_INSIGHT_PREFIX):
        return routes

    suffix = selected.removeprefix(PUBLIC_ORIGIN_INSIGHT_PREFIX)
    candidate = f"{background_id}{NATIVE_ORIGIN_INSIGHT_SEGMENT}{suffix}"
    if candidate in exact_ids:
        routes["origin_insight_choice_id"] = candidate
    return routes
