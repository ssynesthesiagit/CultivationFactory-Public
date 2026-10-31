"""Public-safe copy of Meridian Snare's compiled-text pin.

This file originally pinned the record's exact printed roll-target prose and the
Repeat Use sentence, which routed it to the private checkout (the public export
scrambles every 8+ word prose string in the compiled authority).

It now asserts the typed ids, fields and structure of the compiled lines rather
than printed wording. The exact-printed-prose pins moved to
test_auto_support_compiled_text_private.py (## Stays private).
"""
from pathlib import Path

from combat.factory_compiler import compile_character

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.support"

SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10,
                 "path": "Qi Cultivation", "key_ability": "CON"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2}
                      for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 30},
        "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 30,
        "technique_attack_bonus": 8,
    },
    "equipment": [],
    "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.thread"],
        "learned_talent_record_ids": ["TAL_THREAD_MERIDIAN_SNARE"],
    },
}


def _bundle():
    return compile_character(SHEET, actor_id=ME)


def _line_row(bundle, name):
    return next(row for row in bundle["action_catalog"]
                if row["display_name"] == f"Meridian Snare: {name}")


def test_compiled_meridian_snare_lines_have_typed_on_fail_disadvantage_and_repeat_mark():
    # The Arm and Focus lines both apply disadvantage on a failed Constitution
    # save and attach the Repeat-Use mark. Assert the typed identity/structure
    # (type, ability, applies_to, mark id, duration) rather than the exact
    # printed wording, which the public export scrambles.
    for name in ("Arm Line", "Focus Line"):
        save = _line_row(_bundle(), name)["parameters"]["typed"]["effects"][0]["on_hit"][0]
        assert save["type"] == "save", name
        assert save["ability"] == "con", name
        assert save["applies_to"] == "target", name
        snare, repeat = save["on_fail"]
        assert snare["type"] == "disadvantage", name
        assert snare["applies_to"] == "target", name
        assert repeat["type"] == "mark", name
        assert repeat["mark"] == "Meridian Snare", name
        assert repeat["duration"] == {"kind": "until_end_of_your_next_turn"}, name


def test_compiled_meridian_snare_lines_keep_their_distinct_typed_on_fail():
    # The Leg (speed) and Breath (condition) lines are structurally distinct from
    # the disadvantage pair, so a regression that cross-wires lines still fails
    # without any prose assertion.
    bundle = _bundle()
    leg_eff, leg_mark = (
        _line_row(bundle, "Leg Line")["parameters"]["typed"]["effects"][0]["on_hit"][0]["on_fail"])
    assert leg_eff["type"] == "speed" and leg_eff["flat"] == -15
    assert leg_eff["provenance"] == "meridian_constriction"
    breath_eff, breath_mark = (
        _line_row(bundle, "Breath Line")["parameters"]["typed"]["effects"][0]["on_hit"][0]["on_fail"])
    assert breath_eff["type"] == "condition"
    assert breath_eff["condition"] == "cannot_advantage_con_saves"
    for mark in (leg_mark, breath_mark):
        assert mark["type"] == "mark" and mark["mark"] == "Meridian Snare"
