"""An Origin tool pick naming one tool of a Background's combined fixed line projects.

Owner build: Shinobi Apprentice grants "poisoner's kit and thieves' tools" as one
fixed line. An Origin insight whose tool pick is one of those two tools is a
duplicate the Background already grants, so it must become expertise. The
validator accepted that pick, but the projector compared the pick against the
whole printed line and raised PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID.
"""
from __future__ import annotations

import hashlib
import json
from itertools import permutations
from pathlib import Path

import pytest

from app.core import FoundryError
from character_creation.starting_proficiency_authority import (
    _tool_key,
    build_starting_proficiency_choice_contract,
    granted_tool_keys,
    validate_starting_proficiency_choices,
)
from projector.v3_bridge import _project_starting_proficiency_skills

AUTHORITY = (
    Path(__file__).parents[1]
    / "non_sphere_authority"
    / "authority"
    / "Background_Core_Authority_v1.json"
)
SHINOBI_ID = "tianxia.background.shinobi_apprentice"
ORIGIN_ID = "tianxia.origin_insight.combined_tool_pick"
MODS = {name: 1 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}


def _catalog_backgrounds() -> list[dict]:
    return json.loads(AUTHORITY.read_text())["backgrounds"]


def _combined_line_picks() -> list:
    """Every (Background, pick, other) from a fixed "X and Y" tool line in the catalog."""
    picks = []
    for row in _catalog_backgrounds():
        for line in row["tools_languages_trades"]["fixed_proficiencies"]:
            if " and " not in line:
                continue
            parts = sorted(granted_tool_keys([line]))
            for pick, other in permutations(parts, 2):
                picks.append(pytest.param(
                    row["background_id"],
                    line,
                    row["skills"]["fixed_skill_names"],
                    pick,
                    other,
                    id=f"{row['background_id']}-{pick}",
                ))
    return picks


def _normalized(background_id: str, line: str, skills: list[str], origin_tool: str) -> dict:
    return {
        "path_skill_choices_by_path_id": {"tianxia.path.body_refining": []},
        "background": {
            "background_id": background_id,
            "fixed_skill_names": list(skills),
            "fixed_tool_proficiencies": [line],
            "selected_languages": [],
        },
        "origin": {
            "origin_id": ORIGIN_ID,
            "selected_skill": None,
            "selected_tool": origin_tool,
            "selected_tool_id": None,
            "result": "expertise",
        },
        "proficiencies": {
            "skills": list(skills),
            "tools": [line],
            "languages": [],
            "expertise": [],
            "tool_expertise": [origin_tool],
        },
    }


def _project(normalized: dict, background_id: str):
    return _project_starting_proficiency_skills(
        normalized,
        path_ids=["tianxia.path.body_refining"],
        background_id=background_id,
        origin_id=ORIGIN_ID,
        final_mods=MODS,
        final_pb=2,
    )


@pytest.mark.parametrize(("background_id", "line", "skills", "pick", "other"), _combined_line_picks())
def test_origin_pick_from_combined_tool_line_projects_expertise(background_id, line, skills, pick, other):
    normalized = _normalized(background_id, line, skills, pick)
    try:
        result = _project(normalized, background_id)
    except FoundryError as exc:
        pytest.fail(f"{background_id}: pick {pick!r} from {line!r} raised {exc.code}")

    assert result["origin_result"] == "expertise"
    assert result["tool_expertise"] == [pick]
    # The line's other tool is still granted as a proficiency through the combined line.
    assert _tool_key(other) in granted_tool_keys(result["tool_proficiencies"])


def test_shinobi_quick_hands_tool_validates_and_projects_expertise():
    authority = AUTHORITY.parent
    master = json.loads((authority / "Tianxia_Path_Index_Master_P2A.json").read_text())
    profiles = {}
    for row in master["paths"]:
        profile = json.loads((authority / row["index_file"]).read_text())
        profiles[profile["canonical_id"]] = profile
    backgrounds = {row["background_id"]: row for row in _catalog_backgrounds()}
    source = (authority / "Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md").read_text()
    path_id = "tianxia.path.qi_cultivation"
    origin_id = "tianxia.origin_insight.quick_hands"
    selected = {
        "path_choice": [path_id],
        "background_choice": [SHINOBI_ID],
        "origin_insight_choice": [origin_id],
    }
    contract = build_starting_proficiency_choice_contract(
        path_profiles=profiles,
        backgrounds=backgrounds,
        choices_by_slot={
            "path_choice": {path_id: {"choice_id": path_id, "name": "Qi Cultivation"}},
            "background_choice": {SHINOBI_ID: {"choice_id": SHINOBI_ID, "name": "Shinobi Apprentice"}},
            "origin_insight_choice": {origin_id: {
                "choice_id": origin_id,
                "name": "Quick Hands",
                "summary": (
                    "You gain proficiency in Sleight of Hand or thieves' tools. "
                    "If you already have proficiency in the chosen option, gain expertise in it."
                ),
                "source_evidence": [{
                    "source_path": "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md",
                    "source_hash": "b" * 64,
                    "source_anchor": "heading:quick_hands",
                }],
            }},
        },
        allowed_choice_ids_by_slot=selected,
        campaign_language_source_text=source,
        campaign_language_source={
            "path": "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
            "source_hash": hashlib.sha256(source.encode()).hexdigest(),
        },
    )
    validated = validate_starting_proficiency_choices(
        contract=contract,
        selected_by_slot=selected,
        bounded_choices={
            "path_skill_choices_by_path_id": {path_id: ["Arcana", "Medicine"]},
            "origin_skill_choices_by_origin_id": {origin_id: ["thieves' tools"]},
        },
    )
    assert validated["valid"], validated["blockers"]
    normalized = validated["normalized_mechanics"]
    line = "poisoner’s kit and thieves’ tools"
    assert normalized["origin"]["result"] == "expertise"
    assert normalized["proficiencies"]["tools"] == [line]
    assert normalized["proficiencies"]["tool_expertise"] == ["thieves' tools"]
    projected = _project_starting_proficiency_skills(
        normalized, path_ids=[path_id], background_id=SHINOBI_ID,
        origin_id=origin_id, final_mods=MODS, final_pb=2,
    )
    assert projected["origin_result"] == "expertise"
    assert projected["tool_proficiencies"] == [line, "thieves' tools"]
    assert projected["tool_expertise"] == ["thieves' tools"]


def test_origin_pick_outside_combined_tool_line_still_rejected():
    line = "poisoner’s kit and thieves’ tools"
    normalized = _normalized(SHINOBI_ID, line, ["Deception", "Sleight of Hand"], "smith's tools")
    with pytest.raises(FoundryError) as raised:
        _project(normalized, SHINOBI_ID)
    assert raised.value.code == "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID"
