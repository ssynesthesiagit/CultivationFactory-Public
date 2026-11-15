"""A "Choose one" reaction runs one option (owner 2026-09-26, step 14).

The reaction hook fires with no moment to pick, so the whole printed menu used to run at once (157 reactions).
tools/build_typed_mechanics_authority.split_reaction_menu splits a reaction's menu the way actions' menus are
split, keeping an earlier-typed effect the options leave out; combat/factory_compiler.py _generic_reaction runs
the option the character's reaction plan picks (a default by trigger until the player picks one); the sheet's
Reactions panel saves the pick (combat/tabletop.py ButtonStore.save_reactions).
"""

import pytest

from combat.factory_compiler import compile_character
from tools.typed_mechanics_helpers import split_reaction_menu

_AC = {"type": "ac_bonus", "amount": 2, "applies_to": "self", "evidence": "Gain +2 AC against the triggering attack"}
_TEMP = {"type": "temp_hp", "flat": 5, "applies_to": "self", "evidence": "gain 5 temporary Hit Points"}
_MOVE = {"type": "movement", "distance_ft": 10, "applies_to": "self", "evidence": "move 10 feet"}
_TEXT = "Gain +2 AC against the triggering attack. Choose one: Brace: gain 5 temporary Hit Points. Slip: move 10 feet."


def _reaction(effects: list) -> dict:
    return {"mechanic_id": "MENU", "name": "Menu Guard", "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "reaction", "trigger": "A creature hits you with a melee attack"},
            "effects": effects, "riders": [], "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


def _types(effects: list) -> list:
    return sorted(effect["type"] for effect in effects)


def test_the_split_keeps_an_effect_the_options_leave_out_in_every_option():
    mechanic = _reaction([dict(_AC), dict(_TEMP), dict(_MOVE)])
    split_reaction_menu(mechanic, {"common_effects": [], "options": [{"label": "Brace", "effects": [dict(_TEMP)]},
                                                                      {"label": "Slip", "effects": [dict(_MOVE)]}]}, _TEXT)
    assert _types(mechanic["effects"]) == ["ac_bonus"]
    assert [(option["label"], _types(option["effects"])) for option in mechanic["options"]] == [
        ("Brace", ["ac_bonus", "temp_hp"]), ("Slip", ["ac_bonus", "movement"])]


def test_a_menu_whose_left_out_effect_shares_a_row_with_an_option_stays_whole():
    save = {"type": "save", "ability": "dex", "on_fail": [{"type": "condition", "condition": "prone", "evidence": "falls prone"}, dict(_TEMP)],
            "on_success": []}
    mechanic = _reaction([save])
    before = [dict(row) for row in mechanic["effects"]]
    split_reaction_menu(mechanic, {"common_effects": [], "options": [{"label": "Brace", "effects": [dict(_TEMP)]},
                                                                      {"label": "Slip", "effects": [dict(_MOVE)]}]}, _TEXT)
    assert "options" not in mechanic and mechanic["effects"] == before


SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["MENU"]},
}
_STRIKE = {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"], "applies_to": "target", "evidence": "deal 1d6 force damage"}
_SOAK = {"type": "damage_modifier", "flat": -5, "applies_to": "self", "evidence": "reduce the damage by 5"}
AUTHORITY = {"mechanics": {"MENU": {**_reaction([]), "options": [{"label": "Strike Back", "effects": [dict(_STRIKE)]},
                                                                  {"label": "Brace", "effects": [dict(_SOAK)]}]}}}


def _row(plan=None) -> tuple[dict, dict]:
    bundle = compile_character(SHEET, actor_id="actor:factory.menu", typed_authority=AUTHORITY, reaction_plan=plan)
    row = next(row for row in bundle["typed_reactions"] if row.get("feature_id") == "MENU")
    choice = next(choice for choice in bundle["reaction_plan"]["choices"] if choice["id"] == "MENU")
    return row, choice


def test_a_reaction_runs_one_option_the_default_answering_its_trigger():
    row, choice = _row()
    assert _types(row["effects"]) == ["damage_modifier"]  # a hit: the damage reduction answers it, not both options
    assert row["option_labels"] == ["Strike Back", "Brace"] and row["option"] == 1
    assert choice["options"] == ["Strike Back", "Brace"] and choice["option"] == 1


def test_manual_modes_keep_the_full_authority_menu_even_when_a_mode_has_no_effect_rows():
    authority = {"mechanics": {"MENU": {**_reaction([]), "options": [
        {"label": "Brace", "effects": [dict(_SOAK)]}, {"label": "Hold position", "effects": []}]}}}
    bundle = compile_character(SHEET, actor_id="actor:factory.menu", typed_authority=authority,
                               reaction_plan={"ask": True})
    row = next(r for r in bundle["typed_reactions"] if r.get("feature_id") == "MENU")
    assert [(m["index"], m["label"]) for m in row["reaction_modes"]] == [(0, "Brace"), (1, "Hold position")]


def test_the_reaction_plan_picks_the_option_in_either_mode():
    row, choice = _row({"options": {"MENU": 0}})
    assert _types(row["effects"]) == ["damage"] and choice["option"] == 0
    row, _ = _row({"order": ["MENU"], "off": [], "options": {"MENU": 0}})
    assert _types(row["effects"]) == ["damage"] and row.get("priority") == 0
    row, _ = _row({"options": {"MENU": 7}})  # a stale pick (the menu changed) falls back to the default
    assert row["option"] == 1


def test_the_sheet_saves_a_pick_only_for_a_real_option(tmp_path):
    from combat.tabletop import ButtonStore

    pid = "2f0e6c55-8a53-4f6f-9d67-1a1f0ce4c1b2"
    store = ButtonStore(tmp_path)
    store.save_reactions(pid, {"mode": "auto", "options": {"MENU": 0}}, {"MENU"}, {"MENU": 2})
    assert store.get(pid)["reactions"] == {"options": {"MENU": 0}}
    for bad in ({"MENU": 2}, {"OTHER": 0}, {"MENU": True}):
        with pytest.raises(Exception):
            store.save_reactions(pid, {"mode": "auto", "options": bad}, {"MENU"}, {"MENU": 2})


def test_the_default_pick_does_not_count_help_for_a_servant_the_character_may_not_have():
    from combat.factory_compiler import _default_reaction_option

    regain = {"label": "Regain CP", "effects": [{"type": "gain_resource", "applies_to": "self", "evidence": "regain CP equal to your PB"}]}
    servant = {"label": "Servant Recovers HP", "effects": [{"type": "healing", "applies_to": "ally",
                                                           "evidence": "one Death servant you control regains HP equal to 2 x your CL"}]}
    assert _default_reaction_option([servant, regain], "any_drop_to_zero") == 1


@pytest.mark.parametrize("tree,when,branch", [("plain", "success", None), ("attack", "hit", "on_hit"),
                                             ("save", "failed_save", "on_fail")])
def test_named_modifiers_follow_each_manual_mode_and_its_own_tree(tree, when, branch):
    from copy import deepcopy
    from types import SimpleNamespace
    from combat.ext.reaction_menus import manual_modes

    def effects(flat):
        damage = {**_STRIKE, "dice": None, "flat": flat}
        if tree == "plain":
            return [damage]
        return [{"type": tree, "ability": "dex", "attack_kind": "melee", branch: [damage],
                 **({"on_success": []} if tree == "save" else {"on_miss": []})}]
    modifier = {**_reaction([]), "mechanic_id": "BOOST", "name": "Guard Training", "kind": "passive",
                "activation": {"economy": "passive"},
                "modifier": {"scope": "named", "targets": ["Menu Guard"], "when": when,
                             "effects": [{"type": "gain_resource", "resource": "qi", "flat": 2,
                                          "applies_to": "self", "evidence": "regain 2 Qi"}]}}
    authority = {"mechanics": {"MENU": {**_reaction([]), "options": [
        {"label": "First", "effects": effects(1)}, {"label": "Second", "effects": effects(3)}]}, "BOOST": modifier}}
    document = deepcopy(SHEET)
    document["spheres_and_talents"]["learned_talent_record_ids"] = ["MENU", "BOOST"]
    bundle = compile_character(document, actor_id="actor:factory.menu", typed_authority=authority,
                               reaction_plan={"ask": True, "options": {"MENU": 1}})
    row = next(r for r in bundle["typed_reactions"] if r["feature_id"] == "MENU")
    expanded = manual_modes(SimpleNamespace(typed_ask_reactors={"actor:factory.menu"}), "actor:factory.menu", "generic", [row])
    for index, choice in enumerate(expanded):
        nodes = choice["effects"][0][branch] if branch else choice["effects"]
        assert [node["type"] for node in nodes] == ["damage", "gain_resource"]
        assert nodes[0]["flat"] == (1 if index == 0 else 3)
        assert nodes[1]["flat"] == 2
    assert expanded[1]["effects"] == row["effects"]
