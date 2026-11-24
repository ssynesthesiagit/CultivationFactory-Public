"""Redacted background prose must not prevent acquisition route projection."""
import pytest

from non_sphere_authority.background_route_links import BACKGROUND_ROUTE_IDS, ROUTE_TARGETS
from test_background_route_links import route_context


@pytest.mark.parametrize("bullet", ["", "[text redacted]", "Lantern Ward"])
def test_background_route_without_source_prose_requires_an_exact_unique_identity(route_context, bullet):
    for background in route_context.backgrounds.values():
        background["background_sphere_talent_routes"]["route_bullets"] = [bullet]
    for route in route_context.cat2_background_routes:
        route["source_text"] = "[text redacted]"
    result = route_context._build_background_route_authority()
    for background_id, route_ids in BACKGROUND_ROUTE_IDS.items():
        options = result[background_id]["route_options"]
        assert [option["background_route_record_id"] for option in options] == list(route_ids)
        for option in options:
            route_id = option["background_route_record_id"]
            assert option["background_talent_choice_id"] == route_id
            assert option["canonical_sphere_id"] == ROUTE_TARGETS[route_id][0]
            assert option["record_commitment_sha256"]
