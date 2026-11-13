"""Cold service regressions for GROW3 findings and atomic multi-level acquisition.

Only synthetic installs and public authority; never models or owner data.
"""
from copy import deepcopy
import json
import zipfile

import pytest
from app.core import FoundryError
from combat import table_advance as ta
from combat import table_levelup as lu
from combat.tabletop import TabletopError
from tests.test_grow3_levelup import service, choices, baseline, PID, QI, TALENTS, SCORES

FEATURE = "tianxia.subpath.qi.five_elements_cultivator.feature.fivefold_attunement"
SUBPATH = "tianxia.subpath.qi.five_elements_cultivator"
INSIGHT = {"canonical_insight_id": "synthetic.insight", "display_name": "Careful Study",
           "selectable": True, "minimum_cl": 1, "ability_options": ["Intelligence", "Wisdom"],
           "full_description": "Gain a cultivation benefit and, when selected at a level, Intelligence or Wisdom +1.",
           "raw_source_record": {"repeatable": "No"}}


def install(root, sheet):
    path = root / "portable_characters" / PID / "current.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def at_three(root):
    s = service(root)
    s._insights_cache = [deepcopy(INSIGHT)]
    s.level_up(PID, choices(s.advancement(PID)))
    s.level_up(PID, choices(s.advancement(PID), 1))
    return s


@pytest.mark.parametrize("element,pair", [("wood", ["wood", "fire"]), ("water", ["water", "wood"])])
def test_subpath_required_build_choice_survives_level_commit_and_cold_reload(tmp_path, element, pair):
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    payload = choices(s.advancement(PID), 1)
    payload.update(subpaths={QI: SUBPATH}, feature_choices={})
    before = deepcopy(s.buttons.get(PID)["advancement"])
    with pytest.raises(FoundryError, match="required build"):
        s.level_up(PID, payload)
    assert s.buttons.get(PID)["advancement"] == before
    payload["feature_choices"] = {FEATURE: "not-an-element"}
    with pytest.raises(FoundryError, match="offered option"):
        s.level_up(PID, payload)
    payload["feature_choices"] = {FEATURE: element}
    s.level_up(PID, payload)
    cold = service(tmp_path)
    sheet = cold.combat._factory_owner_sheet(PID)
    assert sheet["path_and_subpath"]["feature_build_choices"][FEATURE] == {
        "choice": element, "starting_element": element, "known_attunements": pair}
    assert cold.buttons.get(PID)["advancement"]["levels"][-1]["feature_choices"] == {FEATURE: element}
    cold.undo_level(PID)
    assert FEATURE not in (service(tmp_path).combat._factory_owner_sheet(PID)["path_and_subpath"].get("feature_build_choices") or {})


def test_next_level_manual_talent_is_not_spent_as_free_pick(tmp_path):
    sheet = baseline(QI)
    manual_id = TALENTS[0]["canonical_talent_id"]
    sheet["training_sources"] = [{"name": "Next lesson", "contents": {
        "manual_collection": {"content_record_bindings": [{"record_id": manual_id}]},
        "recorded_art_details": [{"minimum_cl": 2}]}}]
    install(tmp_path, sheet)
    s = service(tmp_path)
    view = s.advancement(PID)
    assert manual_id not in ta.known(s.combat._factory_owner_sheet(PID))["talents"]
    assert manual_id not in {r["id"] for r in view["level_up"]["talents"]}
    with pytest.raises(FoundryError, match="unlearned"):
        s.level_up(PID, choices(view, 0))
    s.level_up(PID, choices(view, 1))
    learned = ta.known(service(tmp_path).combat._factory_owner_sheet(PID))["talents"]
    assert {manual_id, TALENTS[1]["canonical_talent_id"]} <= learned
    assert service(tmp_path).buttons.get(PID)["advancement"]["talents"][0]["id"] != manual_id


def test_unrelated_ac_bonus_survives_levels_ability_change_reload_and_undo(tmp_path):
    sheet = baseline(QI)
    sheet["ability_scores_and_statistics"]["armor_class"]["value"] += 1
    install(tmp_path, sheet)
    s = service(tmp_path)
    s.level_up(PID, choices(s.advancement(PID)))
    two = service(tmp_path).combat._factory_owner_sheet(PID)
    assert two["ability_scores_and_statistics"]["armor_class"]["value"] == 13
    s.level_up(PID, choices(s.advancement(PID), 1))
    s.level_up(PID, {**choices(s.advancement(PID), 2), "advancement": "ability", "changes": {"DEX": 2}})
    cold = service(tmp_path)
    armor = cold.combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]
    assert armor["base_value"] == 13 and armor["value"] == 14
    cold.undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]["value"] == 13


def test_insight_milestone_uses_catalog_choice_plus_one_not_normal_asi(tmp_path):
    s = at_three(tmp_path)
    before = s.combat._factory_owner_sheet(PID)
    menu = s.advancement(PID)["level_up"]
    assert menu["available"] and menu["advancement_choice"]
    option = next(r for r in menu["insights"] if r["id"] == INSIGHT["canonical_insight_id"])
    assert option["ability_rule"]["allowed_abilities"] == ["INT", "WIS"]
    payload = {**choices(s.advancement(PID), 2), "advancement": "insight",
               "insight_id": INSIGHT["canonical_insight_id"], "insight_ability": "INT"}
    for ability in ["STR", ""]:
        with pytest.raises(FoundryError):
            s.level_up(PID, {**payload, "insight_ability": ability})
    s.level_up(PID, payload)
    cold = service(tmp_path)
    sheet = cold.combat._factory_owner_sheet(PID)
    assert ta.current_scores(sheet) == {**SCORES, "INT": SCORES["INT"] + 1}
    occurrence = sheet["spheres_and_talents"]["cultivation_insight_occurrences"][-1]
    assert occurrence["insight_id"] == INSIGHT["canonical_insight_id"]
    assert occurrence["ability_change_applied"] and occurrence["acquisition_source"] == "level"
    assert ta.recorded_ability_increase_cls(before, cold.buttons.get(PID)["advancement"]) == [4]
    for kind in ("insight", "ability"):
        with pytest.raises(TabletopError, match="Undo last level"):
            cold.remove_advancement(PID, kind, "0")
    cold.undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID) == before


def test_batch_levels_are_atomic_and_undo_one_cl_at_a_time(tmp_path):
    s = service(tmp_path)
    base = s.combat._factory_owner_sheet(PID)
    saved = ta.empty()
    first = choices(s.advancement(PID))
    interim = lu.prepare(base, saved, first, TALENTS)
    two = ta.memorized(ta.apply(base, interim))
    second = choices({"level_up": lu.menu(two, TALENTS, interim)}, 1)
    before = deepcopy(s.buttons.get(PID).get("advancement"))
    with pytest.raises(FoundryError, match="first level"):
        s.level_up(PID, {"cl": 3, "levels": [first]})
    assert s.buttons.get(PID).get("advancement") == before
    with pytest.raises(FoundryError):
        s.level_up(PID, {"cl": 2, "levels": [first, {**second, "feature_choices": {}}]})
    assert s.buttons.get(PID).get("advancement") == before
    s.level_up(PID, {"cl": 2, "levels": [first, second]})
    assert [r["cl"] for r in service(tmp_path).buttons.get(PID)["advancement"]["levels"]] == [2, 3]
    service(tmp_path).undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID) == two
    service(tmp_path).undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID) == base


def test_authenticated_path_bonus_is_not_stacked_with_itself(tmp_path):
    from tests.test_grow3_levelup import BODY
    sheet = baseline(BODY)
    sheet["ability_scores_and_statistics"]["armor_class"]["value"] += 1
    install(tmp_path, sheet)
    s = service(tmp_path, BODY)
    for index in range(4):
        payload = choices(s.advancement(PID), index)
        if payload["cl"] == 4:
            payload.update(advancement="ability", changes={"INT": 2})
        s.level_up(PID, payload)
    armor = service(tmp_path, BODY).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["armor_class"]
    folded = sum(r["bonus"] for r in armor["generation"]["always_on_bonuses"])
    assert armor["value"] == armor["base_value"] + folded + 1
    assert armor["base_value"] > sheet["ability_scores_and_statistics"]["armor_class"]["base_value"]


def test_insight_can_use_the_same_levels_free_talent_prerequisite(tmp_path):
    s = at_three(tmp_path)
    record = deepcopy(INSIGHT)
    record["prerequisites"] = [{"kind": "talent", "target_id": TALENTS[2]["canonical_talent_id"]}]
    s._insights_cache = [record]
    s.level_up(PID, {**choices(s.advancement(PID), 2), "advancement": "insight",
                     "insight_id": INSIGHT["canonical_insight_id"], "insight_ability": "WIS"})
    assert ta.current_scores(service(tmp_path).combat._factory_owner_sheet(PID))["WIS"] == SCORES["WIS"] + 1


def test_batch_choices_have_a_strict_http_input_shape():
    from app.models import TabletopLevelRequest
    value = TabletopLevelRequest.model_validate({"cl": 2, "levels": [
        {"cl": 2, "talent_ids": ["practice"]},
        {"cl": 3, "talent_ids": ["other"], "subpaths": {QI: SUBPATH}, "feature_choices": {FEATURE: "water"}}]})
    assert value.model_dump()["levels"][1]["feature_choices"] == {FEATURE: "water"}


def test_planning_database_uses_all_levels_and_plain_player_words(tmp_path):
    info = service(tmp_path).advancement(PID)["level_up"]
    assert [r["cl"] for r in info["planning"]] == list(range(2, 21))
    assert [r["cl"] for r in info["planning"] if r["advancement_choice"]] == [4, 8, 12, 16, 19]
    assert "campaign Insight growth update" not in json.dumps(info)
    assert info["subpath_progressions"][SUBPATH][0]["build_choices"][0]["feature_id"] == FEATURE
