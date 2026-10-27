from combat.ext import blossom, trap, vessel
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, engine_button_description
from combat.tabletop_service import TabletopService
from combat.player_text import explain_cp
from tests.test_formations import _sheet


def test_plugin_builders_supply_plain_hover_text_for_all_requested_choice_families():
    sheet = _sheet(cl=18)
    owned = sheet["spheres_and_talents"]
    owned["sphere_record_ids"].extend([trap.SPHERE, vessel.SPHERE, blossom.SPHERE])
    owned["learned_talent_record_ids"].extend([vessel.IRONWOOD, blossom.SEED])
    bundle = compile_character(sheet, actor_id="actor:c1")
    buttons = auto_buttons(bundle, {})
    prefixes = ["Trap aim:", "Trap form:", "Attack an object", "Vessel construction:", "Vessel form:", "Seed damage:",
                "Next Killing Line:", "Harmonized Pulse: strengthen Locking Gate", "Harmonized Pulse: strengthen Suppressing Vein",
                "Mountain-Sealing Great Array", "Next array: second layer"]
    for prefix in prefixes:
        matches = [button for button in buttons if button["label"].startswith(prefix)]
        assert matches, prefix
        for button in matches:
            assert button["description"], button["label"]
            row = next(row for row in bundle["action_catalog"] if row["source_definition_id"] == button["combat"]["source_definition_id"])
            assert explain_cp(row["parameters"]["description"]) in button["description"]
            assert "\n" not in row["parameters"]["description"]


def test_barrage_followup_keeps_its_specific_description_on_sheet():
    from tests.test_barrage_hits import FOLLOW, helpers

    bundle = helpers._bundle(helpers.BARRAGE, [], helpers.BOW_KIT)
    button = next(button for button in auto_buttons(bundle, {}) if button["label"] == FOLLOW)
    assert "Bonus Action" in button["description"]
    assert "positive ability modifier" in button["description"]


def test_summon_and_needles_generic_builders_use_the_owning_plugins_text():
    from tests.test_sys_menus_forms import _fight
    from tests.test_auto_lane3 import _needles_engine

    painting = _fight()
    needles = _needles_engine()
    for engine, effect, phrase in [(painting, "painted_passage", "willing creature"),
                                   (needles, "return_the_living", "half the touched creature's maximum HP")]:
        rows = [row.model_dump(mode="json") for row in engine.action_catalog.values()
                if any(eff.get("type") == effect for eff in (row.parameters.get("typed") or {}).get("effects") or [])]
        assert rows, effect
        for row in rows:
            text = engine_button_description(row)
            assert phrase in text
            button = next(button for button in auto_buttons({"action_catalog": [row]}, {}) if button["label"] == row["display_name"])
            assert text in button["description"]
            menu = {"actions": [{"source_definition_id": row["source_definition_id"]}]}
            TabletopService._menu_descriptions(menu, engine)
            assert menu["actions"][0]["description"] == text
    assert engine_button_description({"parameters": {"typed": {"effects": []}}}) == ""
    TabletopService._menu_descriptions(None, None)
