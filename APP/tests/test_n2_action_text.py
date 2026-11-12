"""Presentation regressions, including read-only owner roster service coverage."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService


def _assert_control_semantics(row, text):
    """Check maneuver, turn cost and delivery against the compiled control row."""
    if (row.get("parameters") or {}).get("description"):
        return  # Ability-owned explicit help takes precedence over shared controls.
    typed = (row.get("parameters") or {}).get("typed") or {}
    if text.startswith("Option:"):
        text = text.split("\n\n", 1)[1]
    effects = typed.get("effects") or []
    option = typed.get("unarmed_option")
    attack = next((e for e in effects if e.get("type") == "attack"), None)
    if option:
        assert "Strength or Dexterity save, DC" in text
        assert "at most one size larger" in text
        assert "on success it is unaffected" in text
        outcome = {"grapple": "Speed becomes 0 until it escapes", "shove_push": "pushed 5 feet away",
                   "shove_prone": "knocked Prone"}[option]
        assert outcome in text
        if option == "grapple":
            assert "free hand" in text
        if attack:
            # The follow-ups are the remaining attacks of the same Attack action, so the text names the delivery
            # the character has: the weapon in hand, or the unarmed strike when no melee weapon is held.
            armed = str(attack.get("attack_kind") or "") == "weapon"
            rest = "remaining attack" if armed else "remaining unarmed attack"
            assert f"{attack['count']} {rest}" in text
            assert "Armor Class" in text and "Each hit deals" in text
        return
    if not attack or not (typed.get("source") in {"improvised_weapon", "unarmed_strike"}
                          or str(typed.get("source") or "").startswith("tianxia.mortal.weapon.")):
        return
    assert text.startswith({"ACTION": "Action:", "BONUS_ACTION": "Bonus action:",
                            "NONE": "No additional action:", "REACTION": "Reaction when"}[row["economy"]])
    if row["economy"] == "NONE":
        assert "part of" in text
        assert "Attack action" in text
        if (row.get("parameters") or {}).get("following_strike"):
            assert "third creature" in text and "once per turn" in text
        elif typed.get("mastery") == "Nick":
            assert "Nick" in text
        else:
            assert "expend Martial Focus" in text and "once per turn" in text
    if typed.get("long_range_ft"):
        assert f"{typed['range_ft']} feet normally" in text
        assert f"{typed['long_range_ft']} feet with disadvantage" in text
        thrown = "thrown" in str((typed.get("weapon") or {}).get("properties") or "").lower()
        if thrown or typed.get("source") == "improvised_weapon":
            assert "Throw it" in text and "no longer hold it afterward" in text
        else:
            assert "Fire it" in text and "keep the weapon" in text
            assert "Throw it" not in text and "no longer hold it afterward" not in text


@pytest.fixture(scope="module")
def roster_table(tmp_path_factory):
    inputs = Path("/var/tmp/auto-audit/astra/lock3-inputs/portable_characters")
    archives = sorted(inputs.glob("*/current.zip"))
    if not archives:
        pytest.skip("Owner roster is not installed; portable service fixtures are private")
    user = tmp_path_factory.mktemp("n2-roster")
    for archive in archives:
        target = user / "portable_characters" / archive.parent.name / "current.zip"
        target.parent.mkdir(parents=True)
        shutil.copy2(archive, target)
    app = Path(__file__).resolve().parents[1]
    return TabletopService(CombatService(app, user), user), [p.parent.name for p in archives]


@pytest.mark.parametrize("project", sorted(p.name for p in
    Path("/var/tmp/auto-audit/astra/lock3-inputs/portable_characters").glob("*")
    if (p / "current.zip").is_file()) or [None])
def test_owner_roster_combat_buttons_have_rules_and_readable_dimensions(roster_table, project):
    """Keep full roster coverage as individually bounded character checks.

    The former single test compiled all 58 private roster characters twice;
    its 90-second diagnostic deadline fired during a finite deepcopy. Splitting
    the cases preserves every button and Node assertion and identifies the
    character responsible if a compilation actually stalls.
    """
    table, ids = roster_table
    failures = []
    entries = []
    count = 0
    assert project in ids
    sheet = table.sheet(project)
    _, bundle, _ = table._bundle_and_summary(project)
    rows = {r["source_definition_id"]: r for r in bundle["action_catalog"]}
    for group in sheet["library"]["groups"]:
        entries.extend(group.get("entries") or [])
        for sphere in group.get("spheres") or []:
            entries.append(sphere)
            entries.extend(sphere.get("entries") or [])
    for button in sheet["buttons"]:
        if button.get("kind") != "combat":
            continue
        count += 1
        if not button.get("description"):
            failures.append(button["label"])
        assert "None ft" not in str(button.get("detail"))
        assert "_OR_" not in str(button.get("detail", {}).get("save"))
        row = rows.get((button.get("combat") or {}).get("source_definition_id"))
        if row:
            _assert_control_semantics(row, button["description"])
    assert not failures, "\n".join(sorted(set(failures)))
    result = subprocess.run(["node", "tests/n2_rules.test.mjs", "--roster"],
                            input=json.dumps(entries), capture_output=True, text=True, check=False,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stdout + result.stderr
    print(f"Owner roster character: {count} combat buttons checked.\n{result.stdout}")


@pytest.mark.parametrize("case", ["grapple", "shove_push", "shove_prone", "bonus", "nick", "ambidexterity", "following", "bow", "thrown", "melee", "carnage", "draw", "stow"])
def test_compiled_control_text_on_service_sheet_and_menu(case, tmp_path):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ActionDefinition
    from tests.test_factory_combat_compiler import _weapons_of, SHEET

    bundle, weapons = _weapons_of(
        ["tianxia.mortal.weapon.duan_jian", "tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.gong_jian"],
        paths=("tianxia.path.body_refining",), features=["tianxia.path.body_refining.feature.extra_attack"],
        spheres=["tianxia.sphere.weapons"],
        extra_ids=["TAL_DUAL_WIELDING_AMBIDEXTERITY", "TAL_DUAL_WIELDING_FOLLOWING_STRIKE"])
    if case in {"draw", "stow"}:
        row = next(r for r in bundle["action_catalog"] if ".equipment_grip." in r["source_definition_id"] and r["source_definition_id"].endswith('.' + case))
        description = row['parameters']['description']
        assert 'hand' in description and 'Costs no Action or resource' in description
        assert ('ready it for weapon attacks' if case == 'draw' else 'cannot attack with it until you draw it again') in description
    elif case == "carnage":
        from combat.ext.bodya_berserker import ADVANCING_CARNAGE, FLAG

        # A single qualifying weapon still grants Carnage, but no paired strike.
        bundle, _ = _weapons_of(["tianxia.mortal.weapon.duan_jian"],
                                extra_ids=[ADVANCING_CARNAGE])
        row = next(r for r in bundle["action_catalog"] if r["source_definition_id"].endswith(".advancing_carnage"))
        assert row["parameters"]["requires_turn_flag"] == FLAG
        assert row["parameters"]["typed"].get("pair_role") != "answer"
        assert not any(r["parameters"].get("typed", {}).get("pair_role") == "answer" for r in bundle["action_catalog"])
    elif case in {"grapple", "shove_push", "shove_prone"}:
        row = next(r for r in bundle["action_catalog"] if (r["parameters"].get("typed") or {}).get("unarmed_option") == case)
        assert [e["type"] for e in row["parameters"]["typed"]["effects"]] == ["save", "attack"]
    else:
        key = {"bonus": "duan_jian#offhand", "nick": "bi_shou#offhand", "ambidexterity": "duan_jian#offhand_ambidexterity",
               "following": "duan_jian#following", "bow": "gong_jian", "thrown": "bi_shou#thrown", "melee": "bi_shou"}[case]
        row = weapons[key]

    class CompiledTable(TabletopService):
        def _bundle_and_summary(self, project_id):
            return SHEET, bundle, {"cultivation_level": 17}

    table = CompiledTable(CombatService(Path(__file__).resolve().parents[1], tmp_path), tmp_path)
    button = next(b for b in table.sheet("00000000-abcdef")["buttons"]
                  if (b.get("combat") or {}).get("source_definition_id") == row["source_definition_id"])
    _assert_control_semantics(row, button["description"])
    menu = {"actions": [{"source_definition_id": row["source_definition_id"]}]}
    # _menu_descriptions reads the acting creature from engine.state (the TabletopService menu path always has
    # one); a unit-level catalog stand-in has to provide the same shape or it is not a usable engine.
    engine = SimpleNamespace(action_catalog={row["source_definition_id"]: ActionDefinition.model_validate(row)},
                             state=SimpleNamespace(actors={}))
    TabletopService._menu_descriptions(menu, engine)
    _assert_control_semantics(row, menu["actions"][0]["description"])
    for text in (button["description"], menu["actions"][0]["description"]):
        if case == "bonus":
            assert "off-hand attack after attacking with your other qualifying weapon" in text
            assert "as part of the Attack action" in text
        if case == "carnage":
            assert text.startswith("Bonus action:")
            assert "Armor Class" in text and "Each hit deals" in text
            assert "off-hand" not in text
            assert "other qualifying weapon" not in text
            assert "Attack action" not in text
            assert "Nick:" not in text and "Ambidexterity:" not in text
    if case == "melee":
        assert "Throw it" not in button["description"]
    if case == "ambidexterity":
        assert "spent" in button["description"]


def test_contextual_help_at_table_menu_surface():
    from combat.ext import blossom, trap
    from combat.factory_compiler import compile_character
    from tests.test_formations import _sheet
    from combat.tabletop import auto_buttons
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ActionDefinition

    sheet = _sheet(cl=10)
    sheet["spheres_and_talents"]["sphere_record_ids"].extend([trap.SPHERE, blossom.SPHERE])
    bundle = compile_character(sheet, actor_id="actor:n2")
    labels = {"Disarm Trap": "thieves' tools", "Escape the net": "Cultivation Save DC", "Remove Blossom": "withers"}
    rows = {row["source_definition_id"]: ActionDefinition.model_validate(row) for row in bundle["action_catalog"]}
    menu = {"actions": [{"source_definition_id": key} for key, row in rows.items() if row.display_name in labels]}
    TabletopService._menu_descriptions(menu, SimpleNamespace(action_catalog=rows, state=SimpleNamespace(actors={})))
    assert len(menu["actions"]) == len(labels)
    for group in menu["actions"]:
        row = rows[group["source_definition_id"]]
        assert labels[row.display_name] in group["description"]
        assert "Action" in group["description"]
    buttons = {b["label"]: b for b in auto_buttons(bundle, {"cultivation_level": 10})}
    for name in labels:
        assert buttons[name]["description"]
    from combat.tabletop import engine_button_description
    assert engine_button_description({"parameters": {"typed": {"effects": []}}}) == ""


def test_printed_cone_lengths_and_special_footprint():
    from combat.tabletop import _area_text, saving_throw_text
    area = {"area": {"shape": "cone", "size_ft_by_cl": [[5, 10, 15], [11, 16, 30], [17, 20, 60]]}}
    assert [_area_text(area, cl) for cl in (5, 11, 17)] == [f"{n}-foot cone originating from you" for n in (15, 30, 60)]
    assert _area_text({"area": {"shape": "special", "size_ft": None}, "effects": [
        {"type": "zone", "evidence": "10-foot-radius circle centered on a visible point"}]}, 10).startswith("10-foot-radius")
    assert saving_throw_text({"ability": "STR_OR_DEX"}, {"save_dc": 14}) == "Strength or Dexterity save, DC 14"
    from combat.tabletop import damage_text
    assert damage_text({"weapon": {"fixed_damage": 4, "damage": {"count": 1, "sides": 2}, "damage_type": "BLUDGEONING"},
                        "effects": [{"type": "attack", "on_hit": [{"type": "damage", "weapon_damage": True}]}]}, 1) == "4 bludgeoning"


def test_damage_text_folds_a_pre_roll_modifiers_penalty_and_first_hit_damage():
    """Brutal Strike's row must read +4 / 1d10+15 from the same compiled numbers the executor rolls."""
    from combat.tabletop import attack_to_hit, damage_text

    typed = {"numbers": {"attack_bonus": 9, "cl": 5},
             "weapon": {"damage": {"count": 1, "sides": 10, "modifier": 5}, "damage_type": "SLASHING"},
             "effects": [{"type": "attack", "first_roll_bonus": -5, "first_hit_damage": 10,
                          "on_hit": [{"type": "damage", "weapon_damage": True}]}]}
    assert attack_to_hit(typed) == 4, "the printed -5 is part of the row's attack bonus"
    assert damage_text(typed, 5) == "1d10+15 slashing", "the +10 joins the weapon's own damage line, not a second packet"


def test_damage_text_expands_the_executor_formula_fields():
    from combat.tabletop import damage_text

    typed = {"numbers": {"pb": 3, "cl": 5, "key_mod": 3}, "effects": [{
        "type": "damage", "dice": {"count": 2, "sides": 8, "bonus_formula": "key_ability_modifier"},
        "formula": "pb", "damage_types": ["BLUDGEONING"],
    }]}
    assert damage_text(typed, 5) == "2d8+6 bludgeoning"


def test_damage_text_keeps_unknown_formula_local_and_formats_known_actor_numbers():
    from combat.tabletop import damage_text

    typed = {"numbers": {"pb": 3, "key_mod": 4}, "effects": [
        {"type": "damage", "dice": {"count": 1, "sides": 8}, "formula": "not_a_real_formula",
         "damage_types": ["SLASHING"]},
        {"type": "damage", "dice": {"count": 1, "sides": 6, "bonus_formula": "key_ability_modifier"},
         "damage_types": ["FIRE"]},
    ]}
    assert damage_text(typed, 5) == "1d8 + a bonus decided when it hits slashing + 1d6+4 fire"


@pytest.mark.parametrize("dice, numbers, expected", [
    ({"count": 2, "count_formula": "pb", "sides": 8}, {"pb": 3}, "2d8 fire"),
    ({"count": 0, "count_formula": "pb", "sides": 8, "bonus": 4}, {"pb": 3}, "4 fire"),
    ({"count_formula": "pb", "sides": 8, "bonus": 4}, {"pb": 0}, "4 fire"),
    ({"count_formula": "pb", "sides": 8}, {"pb": 3}, "3d8 fire"),
    ({"count": 2, "count_formula": "unknown", "sides": 8}, {}, "2d8 fire"),
    ({"count": 2, "sides": 1, "bonus": 4}, {}, "4 fire"),
])
def test_damage_display_matches_execution_count_and_flat_semantics(dice, numbers, expected):
    from combat.tabletop import damage_text
    from combat.typed_executor import Context

    typed = {"numbers": numbers, "effects": [{"type": "damage", "dice": dice, "damage_types": ["FIRE"]}]}
    resolved = Context(None, None, None, None, typed, []).dice(dice)
    if resolved.count:
        assert expected.startswith(f"{resolved.count}d{resolved.sides}")
    else:
        assert expected == f"{resolved.modifier} fire"
    assert damage_text(typed, 5) == expected


@pytest.mark.parametrize("formula", ["half_trigger_damage", "not_a_real_formula", "text:unresolved code"])
def test_damage_display_uses_plain_words_for_unresolved_formulas(formula):
    from combat.tabletop import damage_text

    typed = {"effects": [{"type": "damage", "dice": {"count": 1, "sides": 8},
                          "formula": formula, "damage_types": ["FIRE"]}]}
    assert damage_text(typed, 5) == "1d8 + a bonus decided when it hits fire"


def test_damage_display_uses_plain_words_for_unresolved_die_count():
    from combat.tabletop import damage_text

    typed = {"effects": [{"type": "damage", "dice": {"count_formula": "unknown_count", "sides": 8},
                          "damage_types": ["FIRE"]}]}
    assert damage_text(typed, 5) == "damage dice decided when it hits fire"
