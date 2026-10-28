from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.starting_proficiency_authority import origin_starting_proficiency_unresolved


def _origin(choice_id: str, summary: str) -> dict:
    return {
        "record_id": choice_id, "display_name": choice_id, "summary": summary,
        "source": {"path": "rules.md", "anchor": "line:1:column:1", "source_hash": "a" * 64},
    }


def test_grammar_types_skills_tools_trades_and_languages_but_refuses_unprinted_options() -> None:
    skills = _origin("tianxia.origin_insight.body_is_a_shrine",
                     "You gain proficiency in Athletics, Medicine, or Religion. If you already have proficiency in the chosen skill, gain expertise in it.")
    trade = _origin("tianxia.origin_insight.listen_while_serving",
                    "You gain proficiency in Insight, Perception, or one service trade proficiency. If you already have proficiency in the chosen option, gain expertise in it.")
    language = _origin("tianxia.origin_insight.courtly_caution",
                       "You gain proficiency in Insight, Persuasion, or one court or formal campaign language. If you already have proficiency in the chosen option, gain expertise in it.")
    kit = _origin("tianxia.origin_insight.hide_the_stain",
                  "You gain proficiency in Deception or disguise kit. If you already have proficiency in the chosen option, gain expertise in it.")
    unprinted = _origin("tianxia.origin_insight.made_up",
                        "You gain proficiency in Deception or glassblower's tools. If you already have proficiency in the chosen option, gain expertise in it.")
    assert origin_starting_proficiency_unresolved(skills["record_id"], skills) is False
    # A printed trade phrase and a campaign-language category are typed by
    # the registry, as is a kit printed in the campaign books.
    assert origin_starting_proficiency_unresolved(trade["record_id"], trade) is False
    assert origin_starting_proficiency_unresolved(language["record_id"], language) is False
    assert origin_starting_proficiency_unresolved(kit["record_id"], kit) is False
    # A tool the books never print stays untyped instead of being guessed.
    assert origin_starting_proficiency_unresolved(unprinted["record_id"], unprinted) is True


def test_builder_marks_untyped_origins_unavailable_and_refuses_to_lock_them(catalog_environment) -> None:
    from character_builder.service import CharacterBuilderService, ORIGIN_PROFICIENCY_UNTYPED_REASON

    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    categories = options.get("categories") if isinstance(options, dict) else options
    category = next((row for row in categories if row.get("slot_id") == "origin_insight_choice"), None)
    if not category or not category.get("choices"):
        pytest.skip("the test catalog installs no Background-Origin Insights")
    by_id = {row["choice_id"]: row for row in category["choices"]}
    untyped = [row for row in category["choices"] if row.get("planning_priority_available") is False]
    typed = [row for row in category["choices"] if row.get("planning_priority_available") is not False]
    assert typed, "every Origin cannot be untyped"
    for row in untyped:
        assert row["unavailable_reason"] == ORIGIN_PROFICIENCY_UNTYPED_REASON
    assert untyped or typed
    backgrounds = next((row for row in categories if row.get("slot_id") == "background_choice"), {}).get("choices") or []
    pair = next(
        ((background["choice_id"], origin["choice_id"]) for origin in untyped for background in backgrounds
         if origin["choice_id"] in (background.get("related_choice_ids") or [])),
        None,
    )
    if pair is not None:
        with pytest.raises(FoundryError) as error:
            service.create_project(
                working_name="Untyped origin lock",
                concept="An owner locks an Origin the grammar cannot type.",
                target_cl=3,
                power_band="standard",
                source_reference=None,
                creation_mode="detailed",
                ability_scores={},
                selections={"background_choice": [pair[0]], "origin_insight_choice": [pair[1]]},
            )
        assert error.value.code == "CHARACTER_SHEET_CHOICE_SOURCE_CONFLICT"
        assert error.value.message == ORIGIN_PROFICIENCY_UNTYPED_REASON
