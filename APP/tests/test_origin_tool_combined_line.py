"""An Origin tool pick naming one tool of a Background's combined fixed line projects.

Owner build: Shinobi Apprentice grants "poisoner's kit and thieves' tools" as one
fixed line. An Origin insight whose tool pick is one of those two tools is a
duplicate the Background already grants, so it must become expertise. The
validator accepted that pick, but the projector compared the pick against the
whole printed line and raised PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core import FoundryError
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
            if " and " not in line or re.search(r"\bor\b", line):
                continue
            parts = [part.strip() for part in line.split(" and ")]
            if len(parts) != 2:
                continue
            for pick, other in ((parts[0], parts[1]), (parts[1], parts[0])):
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
    assert any(other in tool for tool in result["tool_proficiencies"])


def test_origin_pick_outside_combined_tool_line_still_rejected():
    line = "poisoner’s kit and thieves’ tools"
    normalized = _normalized(SHINOBI_ID, line, ["Deception", "Sleight of Hand"], "smith's tools")
    with pytest.raises(FoundryError) as raised:
        _project(normalized, SHINOBI_ID)
    assert raised.value.code == "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID"
