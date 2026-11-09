""""Choose one" abilities no longer apply every option at once (owner 2026-09-26).

Tonight's tournament found 751 usable abilities whose printed text says "Choose one:", "choose one of
the following" or "one of the following", but whose typed effects listed every option -- combat applied
all of them together (e.g. Coagulate: stabilize, end bleeding and temporary HP all at once). The fix:
tools/type_options.py grounds the ability's common part and each option separately;
factory_authoring/typed_structure.py's ``build_options`` structures them; combat/factory_compiler.py
compiles one action per option instead of the one action that ran every option; combat/tabletop.py
shows them grouped under the ability with the option named in the hover text. Built like
tests/test_typed_structure.py and tests/test_marks.py.
"""

from pathlib import Path

from combat.factory_compiler import MAX_OPTIONS_PER_ABILITY, compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.tabletop import auto_buttons, sheet_library, sheet_summary
from factory_authoring.typed_structure import build_options

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ builder: build_options
def test_builder_splits_a_choose_one_menu_into_common_and_per_option_trees():
    text = ("Make a ranged Cultivation Attack. On a hit, choose one of the following: push the target 5 feet "
            "directly away from you; or the target is knocked Prone.")
    rows = [
        {"label": "Push", "effects": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5,
                                       "evidence": "push the target 5 feet directly away from you"}]},
        {"label": "Prone", "effects": [{"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "knocked Prone"}]},
    ]
    common, options = build_options([], rows, text)
    # Neither option's own effect states "make an attack": the shared delivery is learned from the whole
    # menu and wraps common_effects even though common_effects alone had nothing to wrap.
    assert common[0]["type"] == "attack" and common[0]["attack_kind"] == "cultivation_ranged" and common[0]["on_hit"] == []
    assert len(options) == 2
    push = next(row for row in options if row["label"] == "Push")
    prone = next(row for row in options if row["label"] == "Prone")
    assert push["effects"][0]["type"] == "attack"
    assert [row["type"] for row in push["effects"][0]["on_hit"]] == ["forced_movement"]
    assert [row["type"] for row in prone["effects"][0]["on_hit"]] == ["condition"]
    # Each option only ever carries its own effect, never the other's (the bug this pass fixes).
    assert not any(row["type"] == "condition" for row in push["effects"][0]["on_hit"])
    assert not any(row["type"] == "forced_movement" for row in prone["effects"][0]["on_hit"])


def test_builder_drops_an_option_with_no_grounded_effect_and_leaves_a_single_option_unsplit():
    text = "Make a ranged Cultivation Attack. On a hit, choose one of the following: knock the target Prone."
    _common, options = build_options(
        [], [{"label": "Prone", "effects": [{"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "knock the target Prone"}]}], text)
    assert options == []  # fewer than two grounded options: the authority builder leaves this ability as before


# ------------------------------------------------------------------ compiler: one action per option
def _mechanic(key: str, name: str, options: list, *, cost=None) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "action"}, "effects": [], "riders": [], "range": {"kind": "self"},
            "area": None, "duration": {"kind": "instant"}, "cost": cost or [], "options": options}


TWIN_CHOICE = _mechanic("TWIN_CHOICE", "Twin Choice", [
    {"label": "Shell", "effects": [{"type": "temp_hp", "applies_to": "self", "flat": 10, "formula": "none", "evidence": "gain 10 temporary hit points"}]},
    {"label": "Guard", "effects": [{"type": "ac_bonus", "applies_to": "self", "flat": 3, "formula": "none", "evidence": "+3 to AC"}]},
], cost=[[{"resource": "qi", "amount": 1}]])
STEADY_FOCUS = {
    "mechanic_id": "BOOST", "name": "Steady Focus", "sphere_id": "tianxia.sphere.test", "kind": "talent",
    "activation": {"economy": "passive"}, "effects": [], "riders": [], "range": None, "area": None,
    "duration": {"kind": "instant"}, "cost": [],
    "modifier": {"targets": ["Twin Choice"], "scope": "named", "when": "use", "optional": False, "limit": "none",
                "effects": [{"type": "advantage", "applies_to": "self", "on": "the next save", "evidence": "advantage on your next save"}]},
}
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["TWIN_CHOICE"]},
}


def test_compiler_makes_one_action_per_option_sharing_cost_and_range():
    bundle = compile_character(SHEET, actor_id="actor:factory.compile_choice", typed_authority={"mechanics": {"TWIN_CHOICE": TWIN_CHOICE}})
    by_name = {row["display_name"]: row for row in bundle["action_catalog"]}
    assert "Twin Choice" not in by_name  # the all-options action is never compiled
    shell, guard = by_name["Twin Choice: Shell"], by_name["Twin Choice: Guard"]
    for row in (shell, guard):
        assert row["target_kind"] == "SELF" and [tuple(cost) for cost in row["costs"]] == [("resource:core.qi", 1)]
    assert [row["type"] for row in shell["parameters"]["typed"]["effects"]] == ["temp_hp"]
    assert [row["type"] for row in guard["parameters"]["typed"]["effects"]] == ["ac_bonus"]
    assert not bundle["diagnostics"]["skipped"]["not_typed"]


def test_options_are_capped_per_ability_with_a_diagnostics_note():
    many = _mechanic("MANY_CHOICE", "Many Choice",
                     [{"label": f"Pick {i}", "effects": [{"type": "temp_hp", "applies_to": "self", "flat": i, "formula": "none"}]} for i in range(1, 10)])
    sheet = {**SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["MANY_CHOICE"]}}
    bundle = compile_character(sheet, actor_id="actor:factory.capped_choice", typed_authority={"mechanics": {"MANY_CHOICE": many}})
    compiled = [row for row in bundle["action_catalog"] if row["display_name"].startswith("Many Choice:")]
    assert len(compiled) == MAX_OPTIONS_PER_ABILITY == 6
    assert any("9 options capped at 6" in note for note in bundle["diagnostics"]["notes"])


# ------------------------------------------------------------------ engine: only the chosen option applies
def _intent(candidate):
    return ActionIntent(intent_id="test:choice", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        destination=candidate.destination)


def _engine_with(typed: dict, seed: str) -> tuple[Gate2Engine, str]:
    engine = Gate2Engine(ROOT, match_seed=seed)
    actor = engine.state.actors[engine.state.current_actor_id]
    action = ActionDefinition(source_definition_id="action:typed.test", display_name="Typed test", owner_id=actor.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
                              parameters={"typed": typed})
    engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (*actor.action_ids, action.source_definition_id)
    return engine, actor.entity_id


def test_engine_run_of_one_option_applies_only_that_option():
    bundle = compile_character(SHEET, actor_id="actor:factory.engine_choice", typed_authority={"mechanics": {"TWIN_CHOICE": TWIN_CHOICE}})
    by_name = {row["display_name"]: row for row in bundle["action_catalog"]}

    engine, actor_id = _engine_with(by_name["Twin Choice: Shell"]["parameters"]["typed"], "TWIN-CHOICE-SHELL")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine.execute_intent(_intent(candidate))
    actor = engine.state.actors[actor_id]
    assert actor.temporary_hp == 10 and engine._ac_modifier(actor) == 0  # Guard's AC bonus never ran

    engine2, actor_id2 = _engine_with(by_name["Twin Choice: Guard"]["parameters"]["typed"], "TWIN-CHOICE-GUARD")
    candidate2 = next(c for c in engine2.legal_candidates() if c.source_definition_id == "action:typed.test")
    engine2.execute_intent(_intent(candidate2))
    actor2 = engine2.state.actors[actor_id2]
    assert actor2.temporary_hp == 0 and engine2._ac_modifier(actor2) == 3  # Shell's temp HP never ran


# ------------------------------------------------------------------ modifiers still attach to every option
def test_a_named_modifier_attaches_to_every_compiled_option():
    sheet = {**SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["TWIN_CHOICE", "BOOST"]}}
    bundle = compile_character(sheet, actor_id="actor:factory.modified_choice", typed_authority={"mechanics": {"TWIN_CHOICE": TWIN_CHOICE, "BOOST": STEADY_FOCUS}})
    by_name = {row["display_name"]: row for row in bundle["action_catalog"]}
    shell, guard = by_name["Twin Choice: Shell"], by_name["Twin Choice: Guard"]
    assert any(row["type"] == "advantage" for row in shell["parameters"]["typed"]["effects"])
    assert any(row["type"] == "advantage" for row in guard["parameters"]["typed"]["effects"])
    report = {row["name"]: row for row in bundle["modifiers"]}
    assert sorted(report["Steady Focus"]["applied"]) == ["Twin Choice: Guard", "Twin Choice: Shell"]


# ------------------------------------------------------------------ table: buttons group under the ability
def test_sheet_buttons_group_options_under_the_ability_with_hover_text():
    sheet = {**SHEET, "selected_record_sections": {"talents": [
        {"record_id": "TWIN_CHOICE", "display_name": "Twin Choice", "one_line_description": "Choose one.",
         "full_description": "**Action** -- choose one of the following.", "acquisition_cl": 1},
    ]}}
    bundle = compile_character(sheet, actor_id="actor:factory.sheet_choice", typed_authority={"mechanics": {"TWIN_CHOICE": TWIN_CHOICE}})
    buttons = auto_buttons(bundle, sheet_summary(sheet))
    options = [row for row in buttons if row["label"].startswith("Twin Choice:")]
    assert len(options) == 2
    for row in options:
        assert row["option_of"] == "TWIN_CHOICE" and row["option_label"] in {"Shell", "Guard"}
        assert row["description"].startswith(f"Option: {row['option_label']}")  # leads the hover text (owner 2026-09-26)
    library = sheet_library(sheet, buttons, set())
    other = next(sphere for group in library["groups"] if group["key"] == "spheres" for sphere in group["spheres"] if sphere["name"] == "Other talents")
    item = other["entries"][0]
    # A record's status/button come from whichever option button matched first (owner 2026-09-26): the
    # "#optN" suffix on the compiled action id must not stop the plain record id from matching at all.
    assert item["status"] == "action" and item["button_id"] is not None and "#opt" in item["button_id"]


def test_options_with_their_own_saves_keep_them():
    """Owner 2026-09-26 merge review (Explosive Pill): each pill is its own save -- Frost Pill a Constitution
    save, not inside Flame Pill's Dexterity one; Smoke Pill a cloud with no save; and a failed save deals the
    dice the model wrote on the "half damage" row."""
    from factory_authoring.typed_structure import build_options

    flame = [{"type": "save", "ability": "dex", "evidence": "Each creature in the area makes a Dexterity saving throw.",
              "on_success": [{"type": "half_damage", "dice": "6d6", "damage_types": ["fire"], "evidence": "Half damage."}]}]
    frost = [{"type": "save", "ability": "con", "evidence": "Each creature makes a Constitution saving throw.",
              "on_fail": [{"type": "damage", "dice": "4d6", "damage_types": ["cold"], "applies_to": "target", "evidence": "4d6 Cold damage."}],
              "on_success": [{"type": "half_damage", "evidence": "Half damage."}]}]
    smoke = [{"type": "zone", "evidence": "Create a 15-foot-radius smoke cloud for 1 minute."}]
    _common, options = build_options([], [{"label": "Flame Pill", "effects": flame}, {"label": "Frost Pill", "effects": frost},
                                          {"label": "Smoke Pill", "effects": smoke}], "Choose one formula.")
    trees = {option["label"]: option["effects"] for option in options}
    assert [(row["type"], row.get("ability")) for row in trees["Frost Pill"]] == [("save", "con")]
    assert [row["type"] for row in trees["Smoke Pill"]] == ["zone"]
    flame_save = trees["Flame Pill"][0]
    assert flame_save["ability"] == "dex" and flame_save["on_fail"][0]["type"] == "damage"
    assert flame_save["on_fail"][0]["dice"]["count"] == 6 and flame_save["on_fail"][0]["dice"]["sides"] == 6


def test_hover_text_is_the_full_printed_rules():
    """Owner 2026-09-25 asked for hover text that says what an action does; it showed the parser's untyped
    remainder (Wind Lash: only "When Wind Lash hits, choose one basic Vector:")."""
    from combat.tabletop import _authority_index

    text = _authority_index()["AIR_BASE_WIND_LASH"]["description"]
    assert "Make a ranged Cultivation Attack" in text and "Push:" in text and "Factory Combat Bucket" not in text


def test_a_modifier_menu_is_one_choice_per_option():
    """Owner 2026-09-26: Daemonic Augment's menu (add PB to one damage roll, or Disadvantage on one
    Concentration save, or 5 more feet of movement) rode Demon Mark with every option at once."""
    from combat.factory_compiler import apply_modifiers

    lash = [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
             "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["force"]}]}]
    augment = {"targets": ["Lash"], "scope": "named", "when": "hit", "optional": False, "limit": "once_per_turn", "effects": [],
               "options": [{"label": "Add PB", "effects": [{"type": "extra_damage", "formula": "pb", "applies_to": "target"}]},
                           {"label": "Knock Prone", "effects": [{"type": "condition", "condition": "prone", "applies_to": "target"}]}]}
    mechanics = {
        "LASH": {"mechanic_id": "LASH", "name": "Lash", "sphere_id": "s", "kind": "talent", "activation": {"economy": "action"},
                 "effects": lash, "riders": [], "cost": []},
        "AUG": {"mechanic_id": "AUG", "name": "Augment", "sphere_id": "s", "kind": "talent", "activation": {"economy": "special"},
                "effects": [], "riders": [], "cost": [], "modifier": augment},
    }
    built = {"LASH": {"action_id": "a:LASH", "name": "Lash", "economy": "action", "target_kind": "HOSTILE_ENTITY", "range_ft": 60,
                      "costs": [], "typed": {"effects": lash, "riders": [], "numbers": {"pb": 4}}, "mechanic": mechanics["LASH"], "modifiers": []}}
    apply_modifiers(built, ["LASH", "AUG"], mechanics, "qi", {"qi": 10})
    assert built["LASH"]["modifiers"] == []  # not merged in always-on
    variants = {row["name"]: row for row in built["LASH"]["variants"]}
    assert set(variants) == {"Lash + Augment: Add PB", "Lash + Augment: Knock Prone"}
    hit = variants["Lash + Augment: Knock Prone"]["typed"]["effects"][0]["on_hit"]
    assert [row["type"] for row in hit] == ["damage", "condition"]
    assert len({row["action_id"] for row in variants.values()}) == 2


def test_misread_resistance_and_added_damage_are_corrected():
    """Owner 2026-09-26 overnight: "ignore Resistance" was typed as granting it (Armor-Splitting Cut would have
    given its target resistance); a menu option's "add PB to one damage roll" was an inert damage_modifier."""
    from factory_authoring.typed_structure import fix_misread_effects

    ignore = {"type": "resistance", "applies_to": "target", "damage_types": ["slashing"],
              "evidence": "ignore Resistance to Slashing or Piercing damage on the triggering hit"}
    grant = {"type": "resistance", "applies_to": "self", "damage_types": ["fire"], "evidence": "you gain resistance to fire damage"}
    add = {"type": "damage_modifier", "applies_to": "self", "formula": "pb", "evidence": "add Proficiency Bonus to one damage roll"}
    replace = {"type": "damage_modifier", "formula": "none", "evidence": "increase Impact damage to 6d10 Force or Bludgeoning damage"}
    loses = {"type": "resistance", "applies_to": "target", "damage_types": ["slashing"],
             "evidence": "the target loses Resistance to Bludgeoning, Piercing, and Slashing damage"}
    # Owner 2026-09-26 (resistances now apply): ignoring is read when the damage lands, losing strips the target's.
    assert fix_misread_effects([ignore, grant, loses], adds_to_technique=False) == [
        {**ignore, "type": "ignore_resistance"}, grant, {**loses, "type": "suppress_resistance"}]
    fixed = fix_misread_effects([add, replace], adds_to_technique=True)
    assert fixed[0]["type"] == "extra_damage" and fixed[0]["applies_to"] == "target" and fixed[1]["type"] == "damage_modifier"
    assert fix_misread_effects([add], adds_to_technique=False)[0]["type"] == "damage_modifier"
