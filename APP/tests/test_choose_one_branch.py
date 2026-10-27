""""Choose one" printed inside one save or attack outcome runs one option (fight audit 2026-09-28, hunt item 6a).

``has_choose_one_menu`` leaves a menu that follows a branch label ("Failed Save: Choose one: ...") to nobody, so none of the
top-level splits ever ran on it: Court of the Ninth Grave and 24 other abilities were typed with every bullet in the save's
on_fail, and one failed save applied all of them together (H1-11 timeline 442-445: Speed -10 and "cannot take Reactions" at once).
factory_authoring/typed_structure.py ``branch_menu`` + ``split_branch_menu`` now find such a menu and give each bullet its own
tree -- the whole ability, with only that bullet in the menu's place -- which tools/build_typed_mechanics_authority.py
``split_branch_menu_record`` writes as ``options``; combat/factory_compiler.py then compiles one action (or one reaction option)
per bullet, as for every other menu. Built like tests/test_choose_one.py and tests/test_reaction_options.py.
"""

import copy
import json
from functools import cache

import pytest

from combat import zones
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from factory_authoring.typed_structure import branch_menu, has_choose_one_menu, healing_reduction_amount
from tests.test_auto_support import _bundle, _do, _engine
from tests.test_zones import SHEET
from tools.typed_mechanics_helpers import split_branch_menu_record

NINTH_GRAVE = "TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"
HALF_WAKING_MOON = "TAL_DREAM_COURT_HALF_WAKING_MOON"
DREAM_MIRROR = "TAL_DREAM_DREAM_MIRROR"
THOUSAND_MONKEY = "TAL_MONKEY_STYLE_THOUSAND_MONKEY_UPRISING"
TEN_THOUSAND_MASKS = "tianxia.talent.jester.ten_thousand_masks_procession"
LAST_EMBER = "tianxia.talent.ash.court_of_the_last_ember"
LIVING_FLAME = "tianxia.talent.fire.court_of_the_living_flame"


@cache
def _authority() -> dict:
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _walk(rows):
    for effect in rows or []:
        if isinstance(effect, dict):
            yield effect
            for branch in ("on_hit", "on_miss", "on_fail", "on_success"):
                yield from _walk(effect.get(branch))


def _delivery(effects: list) -> dict:
    """The tree's own save or attack; an aura's is in its zone's trigger (Court of the Half-Waking Moon: "When an enemy starts its
    turn inside, it makes a Wisdom saving throw", rider lane C5)."""
    inner = [effect for zone in effects if zone.get("type") == "zone" for trigger in zone.get("triggers") or [] for effect in trigger.get("effects") or []]
    return next(effect for effect in [*effects, *inner] if effect["type"] in ("save", "attack"))


def _slot(effects: list, branch: str) -> list:
    """The types of the effects in one outcome of the tree's own save or attack."""
    return sorted(effect["type"] for effect in _delivery(effects).get(branch) or [])


def _denies_reactions(effect: dict) -> bool:
    return effect.get("type") == "reaction_denied" or effect.get("condition") == "reaction_denied"


# ------------------------------------------------------------------ finding the menu: branch_menu
_TEXT = """#### Court of Tests - Test Domain
Action Type: Action
Area: 30-foot-radius aura centered on you
Duration: Concentration, up to 1 minute
Cost: 7 CP
You gain Resistance to Necrotic damage.
When an enemy starts its turn inside, it makes a Constitution saving throw.
Failed Save: Choose one:
the enemy takes 2d8 Necrotic damage;
the enemy’s Speed is reduced by 10 feet until the start of its next turn;
the enemy cannot take Reactions until the start of its next turn;
the enemy cannot regain HP until the start of its next turn.
Successful Save: Healing the enemy receives is reduced by your Proficiency Bonus until the start of its next turn.
"""


def test_a_menu_printed_inside_one_outcome_is_found_and_the_top_level_splits_still_leave_it_alone():
    menu = branch_menu(_TEXT)
    assert menu["branch"] == "on_fail" and menu["head"] == "Failed Save"
    assert menu["text"].startswith("Failed Save: Choose one:") and "Successful Save" not in menu["text"]
    assert menu["after"]["branch"] == "on_success" and "Proficiency Bonus" in menu["after"]["text"]
    assert not has_choose_one_menu(_TEXT)  # build_options and split_reaction_menu never saw this menu; that is the bug
    hit = branch_menu("Make a melee attack. On a hit: choose one: push the target 5 feet; knock the target Prone.")
    assert hit["branch"] == "on_hit" and hit["after"] is None


@pytest.mark.parametrize("text", [
    "Choose one: gain 5 temporary Hit Points; or move 10 feet.",  # a top-level menu: has_choose_one_menu owns it
    _TEXT.replace("Choose one:", "Choose two:"),  # a menu of combinations: no option to pick
    "Failed Save: Choose one creature within 10 feet; it falls Prone. Successful Save: No effect.",  # a target pick
    "Failed Save: Choose one: fall Prone; drop an object. Successful Save: Choose one: gain 5 temporary HP; move 10 feet.",  # two menus
    "",
])
def test_anything_else_is_not_a_branch_menu(text):
    assert branch_menu(text) is None


# ------------------------------------------------------------------ splitting it: split_branch_menu_record
def _fx(kind: str, evidence: str, **rest) -> dict:
    return {"type": kind, "applies_to": "target", "flat": 0, "formula": "none", "damage_types": [], "ability": "none",
            "condition": "none", "distance_ft": 0, "on": "", "duration": "instant", "evidence": evidence, **rest}


_SLOW = _fx("speed", "the enemy’s Speed is reduced by 10 feet until the start of its next turn", flat=-10, duration="until_start_of_next_turn")
_DENY = _fx("reaction_denied", "the enemy cannot take Reactions until the start of its next turn", duration="until_start_of_next_turn")
_DICE = {"count": 2, "count_formula": None, "sides": 8, "bonus": None, "bonus_formula": None}
_DAMAGE = _fx("damage", "the enemy takes 2d8 Necrotic damage", dice=_DICE, damage_types=["necrotic"])
_PB_HEAL = _fx("healing_reduction", "Healing the enemy receives is reduced by your Proficiency Bonus until the start of its next turn",
               formula="pb", applies_to="enemies_in_area", duration="until_start_of_next_turn")


def _mechanic() -> dict:
    """The ability as the earlier typing left it: every bullet of the menu in the save's on_fail, applied together."""
    save = {"type": "save", "ability": "con", "dc": "technique_save_dc", "on_fail": [copy.deepcopy(_DAMAGE), copy.deepcopy(_SLOW), copy.deepcopy(_DENY)],
            "on_success": [copy.deepcopy(_PB_HEAL)]}
    resist = _fx("resistance", "You gain Resistance to Necrotic damage", applies_to="self", damage_types=["necrotic"], duration="one_minute")
    return {"mechanic_id": "TEST_COURT", "name": "Court of Tests", "activation": {"economy": "action"}, "effects": [save, resist], "riders": [],
            "cost": [], "options": [], "area": {"shape": "emanation", "size_ft": 30, "centered_on_self": True}}


def _proposals() -> dict:
    """tools/type_options.py's row for it: three typed bullets, and "cannot regain HP" rejected (a healing with no amount)."""
    return {"common_effects": [], "options": [
        {"label": "Necrotic Damage", "effects": [_fx("damage", "the enemy takes 2d8 Necrotic damage", dice="2d8", damage_types=["necrotic"])]},
        {"label": "Reduce Speed 10 Feet", "effects": [copy.deepcopy(_SLOW)]},
        {"label": "No Reactions", "effects": [copy.deepcopy(_DENY)]}],
        "rejected": [{**_fx("healing", "the enemy cannot regain HP until the start of its next turn", duration="until_start_of_next_turn"),
                      "rejected": "healing states none of its required values", "option": "No HP Regain"},
                     {"option": "No HP Regain", "rejected": "no grounded effect"}]}


def _split() -> dict:
    mechanic = _mechanic()
    split_branch_menu_record(mechanic, _proposals(), _TEXT)
    return mechanic


def test_each_bullet_of_the_menu_becomes_one_option_holding_only_itself():
    options = _split()["options"]
    assert [option["label"] for option in options] == ["Necrotic Damage", "Reduce Speed 10 Feet", "No Reactions", "No HP Regain"]
    assert [_slot(option["effects"], "on_fail") for option in options] == [["damage"], ["speed"], ["reaction_denied"], ["healing_reduction"]]
    # The bullet the proposals could not type is still a choice, read for what it says.
    fail = _delivery(options[3]["effects"])["on_fail"]
    assert healing_reduction_amount(fail[0]["evidence"]) == "none"


def test_what_the_ability_does_whichever_bullet_is_picked_stays_on_every_option():
    mechanic = _split()
    for option in mechanic["options"]:
        assert _slot(option["effects"], "on_success") == ["healing_reduction"]  # the Successful Save's line, not one bullet's
        assert any(effect["type"] == "resistance" for effect in option["effects"])  # nor the top-level resistance
    assert _slot(mechanic["effects"], "on_fail") == []  # the shared tree keeps the menu's place empty


def test_a_bullet_that_cannot_be_typed_is_still_a_choice_carrying_its_printed_line():
    row = _proposals()
    row["rejected"] = [{"option": "Stumble", "rejected": "no grounded effect", "type": "condition", "applies_to": "target",
                        "evidence": "the enemy stumbles and loses its footing"}]
    text = _TEXT.replace("the enemy cannot regain HP until the start of its next turn", "the enemy stumbles and loses its footing")
    mechanic = _mechanic()
    split_branch_menu_record(mechanic, row, text)
    stumble = next(option for option in mechanic["options"] if option["label"] == "Stumble")
    assert _slot(stumble["effects"], "on_fail") == []
    assert any("stumbles and loses its footing" in rider for rider in stumble["riders"])


def test_a_record_the_earlier_typing_gives_no_delivery_to_is_left_as_typed():
    mechanic = _mechanic()
    mechanic["effects"] = [effect for effect in mechanic["effects"] if effect["type"] != "save"]
    before = copy.deepcopy(mechanic)
    split_branch_menu_record(mechanic, _proposals(), _TEXT)
    assert mechanic == before


# ------------------------------------------------------------------ the built authority
def test_court_of_the_ninth_grave_is_a_menu_of_four_not_all_four_at_once():
    options = _authority()[NINTH_GRAVE]["options"]
    fails = {option["label"]: _slot(option["effects"], "on_fail") for option in options}
    assert fails == {"Necrotic Damage": ["damage"], "No HP Regain": ["healing_reduction"], "Reduce Speed 10 Feet": ["speed"],
                     "No Reactions": ["reaction_denied"]}
    assert all(_slot(option["effects"], "on_success") == ["healing_reduction"] for option in options)  # the Successful Save's line


def test_it_compiles_to_one_action_per_bullet_and_each_zone_trigger_carries_only_its_bullet():
    expected = {"Necrotic Damage": ["damage"], "No HP Regain": ["healing_reduction"], "Reduce Speed 10 Feet": ["speed"], "No Reactions": ["reaction_denied"]}
    bundle = _bundle([NINTH_GRAVE], _authority()[NINTH_GRAVE]["sphere_id"])
    rows = {row["display_name"]: row for row in bundle["action_catalog"] if row["display_name"].startswith("Court of the Ninth Grave")}
    assert set(rows) == {f"Court of the Ninth Grave: {label}" for label in expected}  # and no all-at-once "Court of the Ninth Grave"
    for label, types in expected.items():
        typed = rows[f"Court of the Ninth Grave: {label}"]["parameters"]["typed"]
        assert _slot(typed["effects"], "on_fail") == types
        trigger = next(row for row in typed["zone_spec"]["triggers"] if "start" in row["on"])
        assert _slot(trigger["effects"], "on_fail") == types  # what the start-of-turn save runs, too


_FELT = {"Necrotic Damage": {"damage"}, "No HP Regain": {"healing"}, "Reduce Speed 10 Feet": {"speed"}, "No Reactions": {"reactions"}}


@pytest.mark.parametrize("label", sorted(_FELT))
def test_a_foe_that_fails_the_save_meets_only_the_picked_bullet(label):
    """H1-11: Speed -10 and "cannot take Reactions" landed together. The save is against DC 30, so the foe fails it."""
    engine = _engine(_bundle([NINTH_GRAVE], _authority()[NINTH_GRAVE]["sphere_id"]))
    foe = engine.state.actors[AN]
    hp = foe.current_hp
    _do(engine, f"Court of the Ninth Grave: {label}")
    zones.on_turn_start(engine, foe)
    felt = set()
    if foe.current_hp < hp:
        felt.add("damage")
    if any(modifier.target_field == "speed_ft" for modifier in foe.modifiers.values()):
        felt.add("speed")
    if any(modifier.target_field == "healing_reduction" for modifier in foe.modifiers.values()):
        felt.add("healing")
    if any(condition.condition_id.endswith("reaction_denied") for condition in foe.conditions.values()):
        felt.add("reactions")
    assert felt == _FELT[label]


def test_half_waking_moons_reaction_denial_is_the_successful_save_not_the_failed_one():
    options = _authority()[HALF_WAKING_MOON]["options"]
    assert len(options) == 5
    for option in options:
        assert not any(_denies_reactions(effect) for effect in _delivery(option["effects"])["on_fail"])  # it ran on a failed save too
        assert any(_denies_reactions(effect) for effect in _delivery(option["effects"])["on_success"])


def test_thousand_monkeys_aura_wide_reaction_denial_stays_out_of_the_failed_save_menu():
    # Rider lane 10: the four failed-save consequences are one standing choose-one menu, rolled at each triggering move or attack
    # (combat/ext/monkey.py _uprising_test), not four actions.
    mechanic = _authority()[THOUSAND_MONKEY]
    menu = next(effect for effect in mechanic["effects"] if effect["type"] == "menu")
    assert len(menu["options"]) == 4 and not any("reaction" in label.lower() for label in menu["options"])
    assert not any(_denies_reactions(effect) for effect in _walk(_delivery(mechanic["effects"]).get("on_fail")))
    assert any(_denies_reactions(effect) for effect in mechanic["effects"])  # "Inside the aura: enemies cannot take Reactions"


def test_no_bonus_actions_is_a_line_for_the_gm_not_a_reaction_denial():
    options = {option["label"]: option for option in _authority()[TEN_THOUSAND_MASKS]["options"]}
    bonus = options["No Bonus Actions"]
    assert _slot(bonus["effects"], "on_fail") == []
    assert any("Bonus Actions" in rider for rider in bonus["riders"])
    assert _slot(bonus["effects"], "on_success") == ["reaction_denied"]  # the printed Successful Save, on every option
    assert all(_slot(option["effects"], "on_success") == ["reaction_denied"] for option in options.values())


def test_halve_healing_received_reads_as_half_and_the_successful_save_still_reduces_it_by_pb():
    assert healing_reduction_amount("halve healing received until the start of its next turn.") == "half"
    option = next(option for option in _authority()[LAST_EMBER]["options"] if option["label"] == "Halve Healing")
    save = _delivery(option["effects"])
    assert [healing_reduction_amount(effect["evidence"]) for effect in save["on_fail"]] == ["half"]
    assert [healing_reduction_amount(effect["evidence"]) for effect in save["on_success"]] == ["pb"]


def test_resistance_ignored_on_a_target_suppresses_that_targets_resistance():
    option = next(option for option in _authority()[LIVING_FLAME]["options"] if option["label"] == "Ignore Fire Resistance")
    assert "suppress_resistance" in _slot(option["effects"], "on_fail")
    assert not any(effect["type"] == "ignore_resistance" for effect in _walk(option["effects"]))  # a no-op read at damage time


@pytest.mark.parametrize("key", ["tianxia.talent.blacksmith.hammer_rebuke", "TAL_DAEMONIC_CULTIVATION_PARASITE_MERIDIAN_NEEDLE"])
def test_a_reviewed_final_record_is_never_split_over_the_reviewers_typing(key):
    mechanic = _authority()[key]
    assert mechanic["typing_status"] == "reviewed_final" and not mechanic.get("options")


# ------------------------------------------------------------------ a reaction with the menu in its failed save
def test_a_reaction_menu_inside_a_failed_save_runs_only_the_picked_option():
    sheet = {**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [_authority()[DREAM_MIRROR]["sphere_id"]],
                                                               "learned_talent_record_ids": [DREAM_MIRROR]}}

    def row(plan=None) -> dict:
        bundle = compile_character(sheet, actor_id="actor:factory.mirror", reaction_plan=plan)
        return next(row for row in bundle["typed_reactions"] if row.get("feature_id") == DREAM_MIRROR)

    default = row()
    assert default["option_labels"] == ["Effect Fails", "Psychic Backlash", "Drowsy Attacker", "Attacker Misfortune"]
    assert _slot(default["effects"], "on_fail") == ["damage"]  # the default answers with the bullet that hurts, not all four
    assert _slot(default["effects"], "on_success") == ["half_damage"]  # the Successful Save's line rides every option
    assert _slot(row({"options": {DREAM_MIRROR: 3}})["effects"], "on_fail") == ["disadvantage"]
