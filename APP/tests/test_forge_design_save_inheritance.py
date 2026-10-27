"""An omitted save difficulty or scope inherits from the enclosing save.

The typed composer writes a printed rider such as Lava Spit's "The target makes
a Dexterity saving throw" without a DC and with the default target scope. The
engine rolls every typed save against the action's Save DC, and the default
target under an area delivery is the creature the enclosing area save already
resolved. The single-resolution forging policy must compare those two saves as
the one printed roll they are, not as a second gate.

Public CI: synthetic fixtures only; no private data or history reads.
"""
from character_creation.constructed_arts.forge_design import (
    collapse_repeated_saves, design_issues, restructure)


DAMAGE = {"type": "damage", "applies_to": "target", "dice": {"count": 3, "sides": 8}}
SLOW = {"type": "condition", "condition": "slowed", "applies_to": "target",
        "duration": "until_start_of_next_turn"}
HALF = [{"type": "half_damage", "applies_to": "target"}]


def test_a_nested_save_inherits_the_enclosing_difficulty_and_recipients():
    """A DC-less rider under an area save is the same roll, metadata and all.

    Composer rows carry inert defaults and provenance (flat 0, formula none,
    evidence, origin); those change nothing and must not block the fold.
    """
    rider = {"type": "save", "ability": "dex", "applies_to": "target",
             "flat": 0, "formula": "none", "damage_types": [], "condition": "none",
             "distance_ft": 0, "on": "", "duration": "instant",
             "evidence": "The target makes a Dexterity saving throw.", "origin": "model_v2",
             "on_fail": [SLOW], "on_success": []}
    parent = {"type": "save", "ability": "dex", "dc": "technique_save_dc",
              "applies_to": "enemies_in_area", "on_fail": [DAMAGE, rider],
              "on_success": list(HALF)}
    mechanic = {"effects": [parent], "cost": [[{"amount": 2}]]}
    # Without inherited difficulty/recipients the rider stays a stacked gate.
    assert design_issues(mechanic) == []
    [save] = collapse_repeated_saves(mechanic["effects"])
    assert [row["type"] for row in save["on_fail"]] == ["damage", "condition"]
    structured = restructure(mechanic)
    assert [row["type"] for row in structured["effects"]] == ["save"]
    assert [row["type"] for row in structured["effects"][0]["on_fail"]] == ["damage", "condition"]
