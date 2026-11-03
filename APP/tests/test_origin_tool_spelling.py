"""Origin tool picks match a Background's tool regardless of printed spelling.

Owner build 2026-10-10: Forest Hermit grants "the herbalism kit"; Bitter Root
Wisdom picked "herbalism kit" (expertise). The projector rejected it as
PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID.
"""
from projector.v3_bridge import _project_starting_proficiency_skills

MODS = {name: 1 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}


def _normalized():
    return {
        "path_skill_choices_by_path_id": {"tianxia.path.body_refining": []},
        "background": {
            "background_id": "tianxia.background.forest_hermit",
            "fixed_skill_names": ["Nature", "Survival"],
            "fixed_tool_proficiencies": ["the herbalism kit"],
            "selected_languages": [],
        },
        "origin": {
            "origin_id": "tianxia.origin_insight.bitter_root_wisdom",
            "selected_skill": None,
            "selected_tool": "herbalism kit",
            "selected_tool_id": None,
            "result": "expertise",
        },
        "proficiencies": {
            "skills": ["Nature", "Survival"],
            "tools": ["the herbalism kit"],
            "languages": [],
            "expertise": [],
            "tool_expertise": ["herbalism kit"],
        },
    }


def test_origin_tool_matching_background_tool_by_spelling_projects_expertise():
    result = _project_starting_proficiency_skills(
        _normalized(),
        path_ids=["tianxia.path.body_refining"],
        background_id="tianxia.background.forest_hermit",
        origin_id="tianxia.origin_insight.bitter_root_wisdom",
        final_mods=MODS,
        final_pb=2,
    )
    assert result["tool_proficiencies"] == ["the herbalism kit"]
    assert result["tool_expertise"] == ["herbalism kit"]
    assert result["origin_result"] == "expertise"


def test_origin_tool_absent_from_tools_still_rejected():
    import pytest
    from app.core import FoundryError

    normalized = _normalized()
    normalized["proficiencies"]["tools"] = ["smith's tools"]
    normalized["background"]["fixed_tool_proficiencies"] = ["smith's tools"]
    with pytest.raises(FoundryError) as raised:
        _project_starting_proficiency_skills(
            normalized,
            path_ids=["tianxia.path.body_refining"],
            background_id="tianxia.background.forest_hermit",
            origin_id="tianxia.origin_insight.bitter_root_wisdom",
            final_mods=MODS,
            final_pb=2,
        )
    assert raised.value.code == "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID"


def test_tool_proficiencies_list_one_entry_per_tool_whatever_the_spelling():
    normalized = _normalized()
    # Exact membership already holds here, so this isolates the de-duplication.
    normalized["proficiencies"]["tools"] = ["the herbalism kit", "herbalism kit"]
    result = _project_starting_proficiency_skills(
        normalized,
        path_ids=["tianxia.path.body_refining"],
        background_id="tianxia.background.forest_hermit",
        origin_id="tianxia.origin_insight.bitter_root_wisdom",
        final_mods=MODS,
        final_pb=2,
    )
    assert result["tool_proficiencies"] == ["the herbalism kit"]
