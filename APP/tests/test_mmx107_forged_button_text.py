"""A forged/constructed ability's table button prints ITS OWN printed rule.

Hunt109 / MMX107 confirmed 2: every forged action fell back to the SOURCE TALENT's printed
card, so pressing "Destruction Cone of Air" showed "Downburst Seal" -- a 10-foot-radius,
30-foot-high cylinder costing 1 CP, while the button resolves a 25-foot cone for 9 Qi. The
shape is exactly what a player needs to place an area, so the wrong text is a real defect.

These tests run at the TABLE level (real TabletopService menu), not a unit call, because the
bug was in what the player reads on the button. They also pin the inertness rule: a printed
talent's button keeps its own text.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_tabletop_hunt6 import LEFT, RIGHT, PROJECTS
from tests.test_lock2_persistence import act

PRIMARY = "TAL_AIR_DOWNBURST_SEAL"
# The same sheet written two other ways, both supported by the printed card format:
MARKDOWN_TALENT = "TAL_UNMAKING_BLACK_TRACE"   # "**Action Type:**", "**Range:**", "**Target:**", "**Cost:** None"
TARGET_TALENT = "AIR_BASE_WIND_LASH"           # a bare "Target:" line, then "Cost: None" after it


def _technique(name="Destruction Cone of Air", form="cone", cp=9, talent=PRIMARY, augments=(), drawbacks=()):
    """One forged technique: a Base Form carrying a talent the character knows."""
    return {
        "technique_id": f"tianxia.constructed.forged_technique.test.{name.replace(' ', '_')}",
        "name": name, "action_type": "bonus_action", "base_form": {"form_id": form},
        "primary_sphere_effect": {"talent_id": talent}, "secondary_sphere_effects": [],
        "augments": [{"augment_id": name_} for name_ in augments],
        "drawbacks": [{"drawback_id": name_} for name_ in drawbacks],
        "table_choices": {},
        "limits": [], "cp_cost": {"final": cp},
    }


def _fight(tmp_path, *, talents, forged, kit=None, starts=None):
    for name in PROJECTS:
        doc = sheet(talents if name == "left" else ["BEASTMASTERY_BASE_RIDER_PACKAGE"], cl=15,
                    kit=kit if name == "left" else None)
        doc["identity"]["display_name"] = name.title()
        if forged and name == "left":
            doc["forged_techniques"] = forged
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "MMX107 yard", "width_squares": 16, "height_squares": 12,
                               "walls": [], "starts": starts or {"team1": [[4, 4], [4, 7]], "team2": [[7, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]],
                                      opponent_actor_ids=[RIGHT],
                                      control_modes={LEFT: "MANUAL", PROJECTS["ally"]: "LOCAL_AUTO",
                                                    RIGHT: "LOCAL_AUTO"},
                                      arena_id="battlefield:map.mmx107-yard",
                                      match_seed="MMX107-TEXT")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == LEFT:
            return combat, table, mid
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("Left never got a turn")


def _button(table, mid, label):
    for group in table.state(mid)["menu"]["actions"]:
        if group["label"] == label:
            return group["description"]
    raise AssertionError(f"no button named {label!r}")


def test_option_only_primary_without_an_outcome_has_no_table_action(tmp_path):
    """A presentation fixture must not restore LIVE's rejected empty delivery."""
    label = "Trace without an outcome"
    combat, table, mid = _fight(tmp_path, talents=[MARKDOWN_TALENT], forged=[
        _technique(label, "burst", talent=MARKDOWN_TALENT)])
    assert not any(action.display_name == label
                   for action in combat._load_session(mid).engine.action_catalog.values())
    assert not any(group['label'] == label for group in table.state(mid)['menu']['actions'])


def _compiled_typed(combat, mid, label):
    """The compiled row the ENGINE will use for this button (the values the text must match)."""
    for action in combat._load_session(mid).engine.action_catalog.values():
        if action.display_name == label:
            return (action.parameters or {}).get("typed") or {}
    raise AssertionError(f"no compiled action named {label!r}")


def _compiled_area(combat, mid, label):
    return _compiled_typed(combat, mid, label).get("area") or {}


@pytest.mark.parametrize("form,augments", [
    ("zone", ()), ("aura", ()), ("burst", ("persistent_zone",)),
])
def test_table_persistent_component_rule_is_verbatim_and_matches_compiled_timing(tmp_path, form, augments):
    from combat.forged import rules

    label = "Recurring Gale"
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[
        _technique(label, form, augments=augments)])
    typed = _compiled_typed(combat, mid, label)
    spec = typed["zone_spec"]
    assert spec["triggers"]
    assert all(trigger["on"] == ["enter", "start"] and trigger["who"] == "hostile"
               for trigger in spec["triggers"])
    assert spec["follows_owner"] is (form == "aura")
    component = (rules()["forms"][form]["text"].partition(". ")[2]
                 if form != "burst" else rules()["augments"]["persistent_zone"]["text"])
    text = _button(table, mid, label)
    assert "When you create the area: Each creature" in text
    assert "Persistent area — printed component rule: " + component in text
    assert "It moves with you." in text if form == "aura" else "It moves with you." not in text
    assert "A hostile creature that enters the area for the first time on a turn or starts its turn there" in component


@pytest.mark.parametrize("talent,direction,clause", [
    ("TAL_AIR_CYCLONE_PRISON", "toward_center", "A creature is pulled 10 feet toward the center"),
    ("TAL_AXES_LODGED_AXE_PULL", "toward", "If the target is no more than one size larger than you"),
    ("TAL_BRUTE_MOUNTAIN_MOVING_PALM", "away", "away from you"),
])
def test_table_actual_primary_movement_keeps_printed_direction_and_restrictions(tmp_path, talent, direction, clause):
    from combat.status_text import printed_rules

    label = "Carried Movement"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[_technique(label, "burst", talent=talent)])
    typed = _compiled_typed(combat, mid, label)
    def carried(effects):
        for effect in effects:
            yield effect
            yield from carried(effect.get("effects") or [])

    movement = next(effect for effect in carried(typed["effects"][0]["on_fail"])
                    if effect["type"] == "forced_movement")
    assert movement["direction"] == direction
    assert clause in movement["evidence"]
    assert movement["evidence"] in printed_rules()[talent]
    text = _button(table, mid, label)
    prefix = "Printed component rule: " if talent == "TAL_AXES_LODGED_AXE_PULL" else "Printed movement rule: "
    assert prefix + movement["evidence"] in text
    assert "it is pushed" not in text


@pytest.mark.parametrize("direction,verb,reference", [
    (None, "pushed", "away from you"), ("away", "pushed", "away from you"),
    ("toward", "pulled", "toward you"), ("toward_center", "pulled", "toward the area's center"),
    ("away_center", "pushed", "away from the area's center"),
])
def test_generated_movement_sentence_matches_executor_direction_or_quotes_printed_rule(direction, verb, reference):
    from combat.ext.forged_ability_text import _outcome

    effect = {"type": "forced_movement", "distance_ft": 10, "direction": direction}
    assert _outcome(effect, {}) == f"it is {verb} 10 feet {reference}"
    effect["evidence"] = "Move the target up to 10 feet in one legal direction other than directly upward."
    assert _outcome(effect, {}) == "Printed movement rule: " + effect["evidence"]
    effect.pop("evidence")
    effect["direction"] = "unrecognized"
    assert _outcome(effect, {}) == ""


def test_forged_button_prints_its_own_rule_not_the_source_talent(tmp_path):
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique(augments=("expanded_area",))])
    text = _button(table, mid, "Destruction Cone of Air")
    area = _compiled_area(combat, mid, "Destruction Cone of Air")

    # Its own rule: the technique's own name, its own shape, its own cost.
    assert "Destruction Cone of Air" in text
    assert f"{area['size_ft']}-foot cone" in text          # 25 ft: the Augment's own size
    assert "9 Qi" in text
    # Not the source talent's card: another ability's name, shape, cost and prerequisites.
    assert "10-foot-radius, 30-foot-high cylinder" not in text
    assert "1 CP" not in text
    assert "CL 5+" not in text
    # The Primary Sphere Effect is still credited, by name, so its effect is not lost.
    assert "Downburst Seal" in text


def test_forged_button_shows_the_augmented_size_not_the_base_form_size(tmp_path):
    """The Base Form template says 15 feet; Expanded Area makes it 25. The button must say 25."""
    plain_combat, plain_table, plain_mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique()])
    widened_combat, widened_table, widened_mid = _fight(
        tmp_path / "widened", talents=[PRIMARY], forged=[_technique(augments=("expanded_area",))])
    narrow = _compiled_area(plain_combat, plain_mid, "Destruction Cone of Air")["size_ft"]
    wide = _compiled_area(widened_combat, widened_mid, "Destruction Cone of Air")["size_ft"]
    assert wide > narrow, "the Expanded Area Augment did not widen the compiled area"
    assert f"{wide}-foot cone" in _button(widened_table, widened_mid, "Destruction Cone of Air")
    assert f"{narrow}-foot cone" in _button(plain_table, plain_mid, "Destruction Cone of Air")


def test_forged_zone_button_reports_its_own_area_range_and_duration(tmp_path):
    """A Zone, not a Burst: assert the compiled area, reach and one-minute Concentration."""
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique("Vaulted Gale", "zone", 4)])
    text = _button(table, mid, "Vaulted Gale")
    typed = _compiled_typed(combat, mid, "Vaulted Gale")
    area, duration = typed.get("area") or {}, typed.get("duration") or {}

    assert area.get("size_ft") == 20 and area.get("shape") == "sphere", "the Zone form did not compile its own area"
    assert f"{area['size_ft']}-foot radius" in text
    assert typed.get("range_ft") == 60, "the Zone's own placement limit is not 60 feet"
    assert f"Range: {typed['range_ft']} feet" in text
    assert (duration.get("kind"), duration.get("amount")) == ("minutes", 1), "the Zone did not compile a 1-minute duration"
    assert "1 minute" in text
    assert duration.get("concentration") is True
    assert "concentrate" in text.casefold()
    # And still not the source talent's own shape or casting header.
    assert "10-foot-radius, 30-foot-high cylinder" not in text
    assert "Cost: None" not in text
    assert "Downburst Seal" in text


def test_augmented_technique_reports_its_compiled_damage_not_the_talent_table(tmp_path):
    """Increased Damage is already inside the compiled dice; the button must print those."""
    from factory_authoring.typed_mechanics import dice_for_cl

    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique("Gale Fang", "projection", 6, augments=("increased_damage",))])
    text = _button(table, mid, "Gale Fang")
    typed = _compiled_typed(combat, mid, "Gale Fang")

    hit = typed["effects"][0]["on_hit"]
    damage = next(effect for effect in hit if effect.get("type") == "damage")
    dice = dice_for_cl(damage.get("dice_by_cl"), int((typed.get("numbers") or {}).get("cl") or 1))
    compiled = f"{dice['count']}d{dice['sides']}"
    unaugmented = f"{dice['count'] - 1}d{dice['sides']}"
    assert compiled in text, "the button does not print the compiled dice"
    assert unaugmented not in text, "the button still prints the talent's unaugmented damage"
    assert "6 Qi" in text


def test_drawbacks_are_priced_on_the_button(tmp_path):
    """A Self-Damage or Exhausting Drawback is in the compiled row; the button must say so."""
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[
        _technique("Wearied Gale", "ward", 3, drawbacks=("self_damage", "exhausting"))])
    text = _button(table, mid, "Wearied Gale")
    typed = _compiled_typed(combat, mid, "Wearied Gale")

    self_rows = [effect for effect in typed["effects"] if effect.get("applies_to") == "self"]
    assert {effect["type"] for effect in self_rows} == {"damage", "exhaustion"}
    assert "It also costs you" in text
    assert "Exhaustion" in text
    assert "damage equal to your Proficiency Bonus" in text


def test_ward_does_not_print_the_talent_offensive_rule(tmp_path):
    """A Ward's compiled delivery replaces the source's payload, so the printed body must go."""
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique("Gale Ward", "ward", 3)])
    text = _button(table, mid, "Gale Ward")

    assert "Temporary Hit Points" in text
    assert "Failed Save" not in text
    assert "pushed to the ground" not in text
    assert "takes Wind Lash damage" not in text
    assert "Downburst Seal" in text          # the source is still credited, by name


def test_markdown_printed_card_headers_are_removed(tmp_path):
    """Black Trace's card is written in bold Markdown: none of its header is the technique's."""
    combat, table, mid = _fight(tmp_path, talents=[MARKDOWN_TALENT], forged=[
        # LIVE omits outcome-free delivery rolls. Black Trace's unselected options
        # carry no payload, so use a real compiled augment to make this a button.
        _technique("Rending Mark", "cone", 9, talent=MARKDOWN_TALENT, augments=("major_condition",))])
    text = _button(table, mid, "Rending Mark")

    assert "**" not in text, "the source card's own emphasis survived"
    assert "Action Type:" not in text
    assert "Range: 30 feet" not in text
    assert "Target: One creature or object" not in text
    assert "Cost: None" not in text
    assert "Action type: Bonus Action" in text      # the technique's own
    assert "9 Qi" in text                          # the technique's own cost


def test_target_header_does_not_hide_the_techniques_own_cost(tmp_path):
    """Wind Lash's body opens with "Target:", so the Cost: line after it must still be removed."""
    combat, table, mid = _fight(tmp_path, talents=[TARGET_TALENT], forged=[
        _technique("Cutting Gale", "cone", 7, talent=TARGET_TALENT)])
    text = _button(table, mid, "Cutting Gale")

    assert "Cost: None" not in text, "the talent's free cost is printed on a paid technique"
    assert "Target: One creature or unattended object" not in text
    assert "7 Qi" in text
    assert "Wind Lash" in text  # attribution stays; only compiled effects are instructions
    assert "Make a ranged Cultivation Attack" not in text
    assert "choose one basic Vector" not in text


def test_projection_reports_its_own_extended_range(tmp_path):
    """Extended Range doubles the reach the technique actually uses; the button must say 120."""
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[
        _technique("Gale Lance", "projection", 5, augments=("extended_range",))])
    text = _button(table, mid, "Gale Lance")
    typed = _compiled_typed(combat, mid, "Gale Lance")

    assert typed.get("range_ft") == 120
    assert "Range: 120 feet" in text
    assert "Range: 60 feet" not in text


def test_printed_talent_button_is_unchanged(tmp_path):
    """Inertness, byte for byte: a character that forges nothing keeps the shared printed text."""
    from combat.status_text import printed_excerpt

    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=None)
    menu = table.state(mid)["menu"]
    printed = [group for group in menu["actions"] if "Downburst" in group["label"]]
    assert printed, "the printed Downburst Seal button is missing"
    label = printed[0]["label"]
    source = _compiled_typed(combat, mid, label).get("source")
    expected = printed_excerpt(str(source)).replace("Cost: 1 CP", "Cost: 1 Qi (your Path resource)")
    assert printed[0]["description"] == expected, "only LIVE's recorded cost wording may differ"
    assert "forged" not in printed[0]["description"].casefold()


def test_forged_button_text_survives_a_table_commit_and_reload(tmp_path):
    """Presentation only: reloading the saved fight must not change what the button says."""
    _combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[_technique()])
    before = _button(table, mid, "Destruction Cone of Air")
    act(table, mid, "end")
    # A fresh service reads the fight back off disk, exactly like a page reload.
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for _ in range(8):
        state = reloaded.state(mid)
        menu = state.get("menu") or {}
        if menu.get("actor_id") == LEFT and menu.get("actions"):
            break
        if (state.get("presentation") or {}).get("terminal"):
            break
        if menu.get("manual") and menu.get("end_turn"):
            act(reloaded, mid, "end")
        else:
            reloaded.auto_step(mid, after=state["last_sequence"])
    again = _button(reloaded, mid, "Destruction Cone of Air")
    assert again == before


def test_save_primary_projection_describes_nested_save_and_prone_release(tmp_path):
    combat, table, mid = _fight(tmp_path, talents=[PRIMARY], forged=[
        _technique("Downburst Lance", "projection")])
    typed = _compiled_typed(combat, mid, "Downburst Lance")
    nested = next(row for row in typed["effects"][0]["on_hit"] if row["type"] == "save")
    assert nested["ability"] == "str"
    assert nested["on_fail"][0]["condition"] == "prone"
    text = _button(table, mid, "Downburst Lance")
    assert "Make a ranged Cultivation Attack. On a hit" in text
    assert "it makes a Strength saving throw against your Cultivation Save DC" in text
    assert "On a failure, it becomes Prone until it stands up (standing up costs half its Speed)" in text
    assert "Each creature in" not in text


def test_attack_augments_describe_nested_saves_expiry_and_repeat_release(tmp_path):
    technique = _technique("Binding Gale", "projection", talent=TARGET_TALENT,
                           augments=("major_condition", "severe_hindrance", "forced_movement", "minor_hindrance"))
    technique["table_choices"]["minor_hindrance"] = "reaction_denied"
    combat, table, mid = _fight(tmp_path, talents=[TARGET_TALENT], forged=[
        technique])
    typed = _compiled_typed(combat, mid, "Binding Gale")
    saves = [row for row in typed["effects"][0]["on_hit"] if row["type"] == "save"]
    assert len(saves) == 4
    text = _button(table, mid, "Binding Gale")
    assert "it makes a Strength saving throw against your Cultivation Save DC. On a failure, it is pushed 10 feet" in text
    assert "it becomes Restrained until the end of its next turn" in text
    assert "repeats the Strength saving throw against your Cultivation Save DC at the end of each of its turns, ending Restrained on a success" in text
    assert "it makes a Constitution saving throw against your Cultivation Save DC. On a failure, it becomes Stunned until the end of its next turn" in text
    assert "ending Stunned on a success" in text
    assert "until the start of your next turn" in text
    assert "start of source next turn" not in text


@pytest.mark.parametrize("talent, label, forbidden", [
    (TARGET_TALENT, "Wind Cone", ("Vector", "Push:", "Pull:", "1d8", "CL 5")),
    (MARKDOWN_TALENT, "Ruin Cone", ("Unbound Trace", "Trace effect", "Overdraw", "Black Vein Strain", "| Realm |", "1d10")),
])
def test_area_buttons_only_instruct_compiled_save_damage_and_options(tmp_path, talent, label, forbidden):
    from combat.tabletop import damage_text

    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique(label, "cone", talent=talent,
                   augments=("major_condition",) if talent == MARKDOWN_TALENT else ())])
    typed = _compiled_typed(combat, mid, label)
    save = typed["effects"][0]
    assert save["type"] == "save"
    damage = next((row for row in save["on_fail"] if row["type"] == "damage"), None)
    text = _button(table, mid, label)
    assert "Each creature in a 15-foot cone" in text
    assert "saving throw against your Cultivation Save DC" in text
    if damage:
        assert damage_text({"effects": [damage], "numbers": typed["numbers"]}, 15) in text
        assert "On a success, it takes half that damage" in text
    else:
        # Black Trace's unselected options carry no damage. LIVE suppresses the
        # empty primary roll; the genuine restraint augment supplies this save.
        assert talent == MARKDOWN_TALENT
        assert any(row.get("condition") == "restrained" for row in save["on_fail"])
        assert "takes" not in text and "damage" not in text
    assert "Make a ranged Cultivation Attack" not in text
    assert all(fragment not in text for fragment in forbidden)


def test_augmented_numeric_source_does_not_advertise_original_damage_table(tmp_path):
    from factory_authoring.typed_mechanics import dice_for_cl

    talent = "TAL_MAGMA_LAVA_BURST"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Greater Lava Lance", "projection", talent=talent,
                   augments=("increased_damage",))])
    typed = _compiled_typed(combat, mid, "Greater Lava Lance")
    damage = next(row for row in typed["effects"][0]["on_hit"] if row["type"] == "damage")
    dice = dice_for_cl(damage["dice_by_cl"], 15)
    text = _button(table, mid, "Greater Lava Lance")
    assert f"{dice['count']}d{dice['sides']}" in text
    assert f"{dice['count'] - 1}d{dice['sides']}" not in text
    assert "6d6" not in text and "10d6" not in text
    assert "Molten Terrain" not in text
    assert text.count("Make a ranged Cultivation Attack") == 1


def test_healing_primary_projection_prints_dice_and_key_modifier(tmp_path):
    talent = "tianxia.talent.blood.blood_mending"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Mending Lance", "projection", talent=talent)])
    typed = _compiled_typed(combat, mid, "Mending Lance")
    healing = next(row for row in typed["effects"][0]["on_hit"] if row["type"] == "healing")
    assert healing["dice"]["count"] == 3 and healing["formula"] == "key_ability_modifier"
    assert typed["numbers"]["key_mod"] == 2
    assert "it regains 3d8+2 hit points" in _button(table, mid, "Mending Lance")


def test_strike_keeps_equipped_weapon_damage_with_healing_primary(tmp_path):
    from tests.test_auto_martial import SPEAR_KIT

    talent = "tianxia.talent.blood.blood_mending"
    combat, table, mid = _fight(tmp_path, talents=[talent], kit=SPEAR_KIT,
                              starts={"team1": [[4, 4], [4, 7]], "team2": [[5, 4]]}, forged=[
        _technique("Mending Strike", "strike", talent=talent)])
    typed = _compiled_typed(combat, mid, "Mending Strike")
    hits = typed["effects"][0]["on_hit"]
    assert any(row.get("weapon_damage") for row in hits)
    weapon = typed["weapon"]
    assert weapon["damage"]["count"] == 1 and weapon["damage"]["sides"] == 8
    assert weapon["damage"]["modifier"] == 2
    text = _button(table, mid, "Mending Strike")
    assert "Make a weapon attack" in text
    assert "it takes 1d8+2 piercing damage" in text
    assert "it regains 3d8+2 hit points" in text


def test_damaging_ward_prints_actual_resistance_types_and_expiry(tmp_path):
    combat, table, mid = _fight(tmp_path, talents=[TARGET_TALENT], forged=[
        _technique("Wind Shelter", "ward", talent=TARGET_TALENT)])
    typed = _compiled_typed(combat, mid, "Wind Shelter")
    resistance = next(row for row in typed["effects"] if row["type"] == "resistance")
    assert resistance["damage_types"] == ["bludgeoning", "slashing"]
    assert resistance["duration"] == "until_start_of_next_turn"
    text = _button(table, mid, "Wind Shelter")
    assert "You or an ally within 30 feet gains Temporary Hit Points equal to your Proficiency Bonus" in text
    assert "The protected creature gains Resistance to bludgeoning and slashing damage until the start of your next turn" in text
    assert "this technique's damage types" not in text


def test_self_benefit_ward_prints_healing_without_inventing_resistance(tmp_path):
    talent = "TAL_DAEMONIC_CULTIVATION_DEMON_BONE_REGENERATION"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Regenerating Shelter", "ward", talent=talent)])
    typed = _compiled_typed(combat, mid, "Regenerating Shelter")
    assert not any(row["type"] == "resistance" for row in typed["effects"])
    healing = next(row for row in typed["effects"] if row["type"] == "healing")
    assert healing["applies_to"] == "target"
    text = _button(table, mid, "Regenerating Shelter")
    assert "Temporary Hit Points equal to your Proficiency Bonus" in text
    assert "The protected creature regains 1d8+2 hit points" in text
    assert "Devoured Essence" not in text  # forging does not carry source resource spending
    assert "Resistance" not in text


def _carried_speed_fight(tmp_path, monkeypatch, label, effect):
    """Supply supported carried rows before compilation, so table reloads see them too."""
    from combat import forged

    original = forged.mechanic_for

    def compile_with_speed(*args, **kwargs):
        mechanic = original(*args, **kwargs)
        if mechanic and mechanic.get("name") == label:
            mechanic["effects"][0]["on_hit"].append({"type": "speed", "applies_to": "target", **effect})
        return mechanic

    monkeypatch.setattr(forged, "mechanic_for", compile_with_speed)
    return _fight(tmp_path, talents=[TARGET_TALENT], forged=[
        _technique(label, "projection", talent=TARGET_TALENT)])


@pytest.mark.parametrize("effect, expected", [
    ({"type": "healing", "flat": 5}, "it regains 5 hit points"),
    ({"type": "heal", "formula": "key_ability_modifier"}, "it regains 2 hit points"),
    ({"type": "healing", "flat": 5, "formula": "pb"}, "it regains 9 hit points"),
])
def test_healing_amounts_support_flat_and_formula_rows(effect, expected):
    from combat.ext.forged_ability_text import _outcome

    assert _outcome(effect, {"numbers": {"key_mod": 2, "pb": 4}}) == expected


def test_pill_devouring_ward_prints_carried_speed_bonus(tmp_path):
    talent = "tianxia.talent.alchemy.pill_devouring"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Swift Shelter", "ward", talent=talent)])
    typed = _compiled_typed(combat, mid, "Swift Shelter")
    speed = next(row for row in typed["effects"] if row["type"] == "speed")
    assert speed["applies_to"] == "target" and speed["flat"] == 10
    assert speed["duration"] == "one_minute"
    assert "The protected creature's Speed increases by 10 feet for one minute" in _button(table, mid, "Swift Shelter")


def test_burden_projection_prints_carried_speed_zero(tmp_path):
    talent = "TAL_EARTH_THE_BURDEN_OF_TEN_THOUSAND_STEPS"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Burden Lance", "projection", talent=talent)])
    save = next(row for row in _compiled_typed(combat, mid, "Burden Lance")["effects"][0]["on_hit"]
                if row["type"] == "save")
    speed = next(row for row in save["on_fail"] if row["type"] == "speed")
    assert speed["becomes"] == 0 and speed["duration"] == "until_end_of_next_turn"
    assert "its Speed becomes 0 feet until the end of its next turn" in _button(table, mid, "Burden Lance")


@pytest.mark.parametrize("effect, expected", [
    ({"halved": True, "becomes": 0, "amount": -10}, "its Speed is halved"),
    ({"amount": -15, "flat": 10}, "its Speed drops by 15 feet"),
    ({"amount": 10, "flat": -15}, "its Speed increases by 10 feet"),
    ({"becomes": 10, "amount": -15}, "its Speed becomes 10 feet"),
])
def test_table_button_renders_carried_speed_representations(tmp_path, monkeypatch, effect, expected):
    # Forging currently drops Burden's success branch (including halved Speed).
    combat, table, mid = _carried_speed_fight(tmp_path, monkeypatch, "Speed Lance",
                                             {"duration": "until_end_of_next_turn", **effect})
    typed = _compiled_typed(combat, mid, "Speed Lance")
    assert typed["effects"][0]["on_hit"][-1].items() >= effect.items()
    assert expected + " until the end of its next turn" in _button(table, mid, "Speed Lance")


@pytest.mark.parametrize("form", ["projection", "cone"])
def test_void_field_table_text_prioritizes_explicit_target_expiry(tmp_path, form):
    talent = "TAL_VOID_VOID_FIELD"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Hollow Gale", form, talent=talent)])
    session = combat._load_session(mid)
    assert session.engine.state.current_actor_id == LEFT
    assert LEFT != RIGHT and RIGHT in session.engine.state.actors
    typed = _compiled_typed(combat, mid, "Hollow Gale")
    delivery = typed["effects"][0]
    save = (next(row for row in delivery["on_hit"] if row["type"] == "save")
            if form == "projection" else delivery)
    hollowed = next(row for row in save["on_fail"] if row.get("condition") == "hollowed")
    assert hollowed["duration"] == "until_start_of_next_turn"
    assert hollowed["expires_on"] == "START_OF_TARGET_NEXT_TURN"
    # On the caster's table turn, the engine schedules the affected enemy's own
    # next turn, rather than the caster's. Pin the wording to that real deadline.
    from combat import typed_executor
    from combat.ext.effect_durations import token

    engine = session.engine
    caster, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    action = next(action for action in engine.action_catalog.values() if action.display_name == "Hollow Gale")
    ctx = typed_executor.Context(engine, caster, action, None, typed, [target], target, {})
    assert typed_executor.effect_expiry(ctx, hollowed, target, condition=True) == token(
        "start", RIGHT, target.turns_started + 1)
    text = _button(table, mid, "Hollow Gale")
    assert "it becomes Hollowed until the start of its next turn" in text
    assert "Hollowed until the start of your next turn" not in text


@pytest.mark.parametrize("expiry, expected", [
    ("START_OF_SOURCE_NEXT_TURN", "until the start of your next turn"),
    ("END_OF_HOLDER_NEXT_TURN", "until the end of its next turn"),
    ("END_OF_CURRENT_TURN", "until the end of the current turn"),
])
def test_table_button_explicit_expiry_overrides_generic_duration(tmp_path, monkeypatch, expiry, expected):
    combat, table, mid = _carried_speed_fight(tmp_path, monkeypatch, "Timed Lance",
                                             {"amount": -10, "duration": "one_minute", "expires_on": expiry})
    typed = _compiled_typed(combat, mid, "Timed Lance")
    assert typed["effects"][0]["on_hit"][-1]["expires_on"] == expiry
    assert "its Speed drops by 10 feet " + expected in _button(table, mid, "Timed Lance")


@pytest.mark.parametrize("form", ["projection", "cone"])
@pytest.mark.parametrize("talent, owner", [
    ("TAL_ICE_FROZEN_MERIDIAN_BIND", "its"),
    ("tianxia.talent.thread.meridian_lock", "your"),
])
def test_table_condition_deadline_uses_actual_primary_evidence(tmp_path, form, talent, owner):
    from combat import typed_executor
    from combat.ext.effect_durations import token

    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Meridian Gale", form, talent=talent)])
    typed = _compiled_typed(combat, mid, "Meridian Gale")
    delivery = typed["effects"][0]
    save = (next(row for row in delivery["on_hit"] if row["type"] == "save")
            if form == "projection" else delivery)
    restrained = next(row for row in save["on_fail"] if row.get("condition") == "restrained")
    assert restrained["duration"] == "until_end_of_turn"
    assert not restrained.get("expires_on")
    assert f"until the end of {owner} next turn" in restrained["evidence"]
    session = combat._load_session(mid)
    engine = session.engine
    caster, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert engine.state.current_actor_id == LEFT and LEFT != RIGHT
    action = next(action for action in engine.action_catalog.values() if action.display_name == "Meridian Gale")
    ctx = typed_executor.Context(engine, caster, action, None, typed, [target], target, {})
    expected = (f"END_OF_SOURCE_TURN_AT:{caster.turns_started + 1}" if owner == "your"
                else token("end", RIGHT, target.turns_started + 1))
    assert typed_executor.effect_expiry(ctx, restrained, target, condition=True) == expected
    text = _button(table, mid, "Meridian Gale")
    assert f"it becomes Restrained until the end of {owner} next turn" in text
    assert "Restrained until the end of the current turn" not in text


@pytest.mark.parametrize("form", ["projection", "cone"])
def test_table_slag_grasp_primary_names_both_save_alternatives(tmp_path, form):
    talent = "TAL_MAGMA_SLAG_GRASP"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Slag Gale", form, talent=talent)])
    delivery = _compiled_typed(combat, mid, "Slag Gale")["effects"][0]
    save = (next(row for row in delivery["on_hit"] if row["type"] == "save")
            if form == "projection" else delivery)
    assert save["ability"] == "str_or_dex"
    assert "a Strength or Dexterity saving throw against your Cultivation Save DC" in _button(
        table, mid, "Slag Gale")


@pytest.mark.parametrize("fields, expected", [
    ({"on": "until the start of its following turn"}, "until the start of its next turn"),
    ({"on": "before the end of your next turn"}, "until the end of your next turn"),
    ({"evidence": "until the end of its next turn", "on": "until the start of your next turn"},
     "until the end of its next turn"),
    ({"evidence": "until the start of its next turn", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
     "until the start of your next turn"),
    ({"on": "for the rest of this turn"}, "until the end of the current turn"),
])
def test_table_carried_turn_words_and_explicit_expiry_precedence(tmp_path, monkeypatch, fields, expected):
    combat, table, mid = _carried_speed_fight(tmp_path, monkeypatch, "Worded Lance",
                                             {"amount": -10, "duration": "one_minute", **fields})
    assert _compiled_typed(combat, mid, "Worded Lance")["effects"][0]["on_hit"][-1].items() >= fields.items()
    assert "its Speed drops by 10 feet " + expected in _button(table, mid, "Worded Lance")


@pytest.mark.parametrize("form", ["cone", "projection"])
def test_table_impossible_premise_describes_carried_conditional_mark(tmp_path, form):
    talent = "tianxia.talent.illusion.impossible_premise"
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique("Premise Gale", form, talent=talent)])
    typed = _compiled_typed(combat, mid, "Premise Gale")
    delivery = typed["effects"][0]
    save = (next(row for row in delivery["on_hit"] if row["type"] == "save")
            if form == "projection" else delivery)
    guard = save["on_fail"][0]
    assert guard["type"] == "if_not_marked" and guard["mark"] == "Impossible Premise immunity"
    mark = guard["effects"][0]
    assert mark["type"] == "mark" and mark["mark"] == "False Premise"
    assert mark["duration"] == {"kind": "target_next_turn"}
    assert not save["on_success"]  # Forging does not carry the source's success immunity.
    text = _button(table, mid, "Premise Gale")
    assert "On a failure, if it does not already bear your Impossible Premise immunity mark" in text
    assert "it gains your False Premise mark until the end of its next turn" in text
    assert "the creature acted on the illusion as if it were real" in text
    assert "at the start of their next turn" not in text
    assert "two different responses" not in text  # Not a carried effect of this forged action.
    assert "until you finish a Long Rest" not in text


@pytest.mark.parametrize("talent, label, deadline", [
    ("tianxia.talent.space.folded_reach", "Folded Gale", "Until the end of your current turn"),
    ("tianxia.talent.illusion.impossible_premise", "Premise Gale", "Until the end of the target's next turn"),
])
@pytest.mark.parametrize("concentration", [False, True])
def test_table_actual_primary_special_duration_uses_its_text(tmp_path, talent, label, deadline, concentration):
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique(label, "cone", talent=talent,
                   drawbacks=("concentration",) if concentration else ())])
    duration = _compiled_typed(combat, mid, label)["duration"]
    assert duration["kind"] == "special"
    assert duration["amount"] == (1 if concentration else None)
    assert duration["text"].rstrip(".") == deadline
    assert duration["concentration"] is concentration
    text = _button(table, mid, label)
    assert f"Duration: {deadline}." in text
    assert "None special" not in text and "null" not in text and "for special" not in text
    assert ("You must concentrate on it for as long as it lasts" in text) is concentration


@pytest.mark.parametrize("kind, subject, expected", [
    ("if_marked", "target", "if it bears your Charged mark or your Conductive mark"),
    ("if_marked", "self", "if you bear your Charged mark or your Conductive mark"),
    ("if_not_marked", "self", "if you do not already bear your Charged mark or your Conductive mark"),
])
def test_conditional_description_supports_mark_lists_and_self(kind, subject, expected):
    from combat.ext.forged_ability_text import _outcome

    effect = {"type": kind, "mark": ["Charged", "Conductive"], "applies_to": subject,
              "effects": [{"type": "healing", "flat": 5},
                          {"type": "mark", "mark": "Charged", "duration": {"kind": "target_next_turn"}}]}
    text = _outcome(effect, {})
    assert text.startswith(expected + ", ")
    assert ("you regain 5 hit points" if subject == "self" else "it regains 5 hit points") in text
    assert "Charged mark until the end of " + ("your" if subject == "self" else "its") + " next turn" in text
