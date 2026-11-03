from __future__ import annotations

from character_builder import CharacterBuilderService


BACKGROUND_ID = "tianxia.background.abandoned_orphan"
BACKGROUND_SPHERE_ID = "tianxia.background_sphere.scoundrel"
BACKGROUND_TALENT_ID = "tianxia.background_talent.scoundrel.hidden_tool_cache"
PUBLIC_INSIGHT_ID = "tianxia.origin_insight.street_hardened"
NATIVE_INSIGHT_ID = f"{BACKGROUND_ID}.origin_insight.street_hardened"
ROUTE_ID = "tianxia.background_route.abandoned_orphan.scoundrel.hidden_tool_cache"


class _ExactAuthority:
    background_route_authority = {
        BACKGROUND_ID: {
            "route_options": [
                {
                    "background_route_record_id": ROUTE_ID,
                    "background_sphere_choice_id": BACKGROUND_SPHERE_ID,
                    "background_talent_choice_id": BACKGROUND_TALENT_ID,
                }
            ],
            "origin_insight_options": [
                {
                    "origin_insight_choice_id": NATIVE_INSIGHT_ID,
                    "display_name": "Street-Hardened",
                }
            ],
            "equipment_authority_id": f"{BACKGROUND_ID}.starting_equipment",
            "skills_authority_id": f"{BACKGROUND_ID}.skills",
            "tools_languages_trades_authority_id": f"{BACKGROUND_ID}.tools_languages_trades",
        }
    }


def test_creator_origin_insight_is_bound_to_exact_background_scoped_native_id() -> None:
    resolved = CharacterBuilderService._resolved_background_routes(
        {
            "background_choice": [BACKGROUND_ID],
            "background_sphere_choice": [BACKGROUND_SPHERE_ID],
            "background_talent_choice": [BACKGROUND_TALENT_ID],
            "origin_insight_choice": [PUBLIC_INSIGHT_ID],
        },
        {},
        authority=_ExactAuthority(),
    )

    assert resolved["background_route_record_id"] == ROUTE_ID
    assert resolved["background_sphere_choice_id"] == BACKGROUND_SPHERE_ID
    assert resolved["background_talent_choice_id"] == BACKGROUND_TALENT_ID
    assert resolved["origin_insight_choice_id"] == NATIVE_INSIGHT_ID


def test_unknown_public_origin_insight_is_not_silently_rewritten() -> None:
    unknown = "tianxia.origin_insight.not_in_authority"
    resolved = CharacterBuilderService._resolved_background_routes(
        {
            "background_choice": [BACKGROUND_ID],
            "background_sphere_choice": [BACKGROUND_SPHERE_ID],
            "background_talent_choice": [BACKGROUND_TALENT_ID],
            "origin_insight_choice": [unknown],
        },
        {},
        authority=_ExactAuthority(),
    )

    assert resolved["origin_insight_choice_id"] == unknown
