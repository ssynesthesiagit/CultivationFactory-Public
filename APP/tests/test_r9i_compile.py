"""General action compile seam leaves unrelated actors/actions unchanged."""
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_carry import KIT


def test_ridiculous_weapon_uses_higher_charisma_without_changing_other_attacks():
    base = sheet([], kit={"starting_kit": KIT})
    for row in base["ability_scores_and_statistics"]["abilities"]:
        if row["ability"] == "CHA":
            row.update(score=20, modifier=5)
    owner = sheet(["tianxia.talent.jester.ridiculous_weapon"], kit={"starting_kit": KIT})
    owner["ability_scores_and_statistics"] = base["ability_scores_and_statistics"]
    before = compile_character(base, actor_id="actor:factory.compile")
    after = compile_character(owner, actor_id="actor:factory.compile")
    catalog = {a["source_definition_id"]: a for a in after["action_catalog"]}
    for action in before["action_catalog"]:
        sid = action["source_definition_id"]
        if sid.endswith((".improvised.attack", ".improvised.thrown")):
            typed = catalog[sid]["parameters"]["typed"]
            assert typed["weapon"]["damage"]["modifier"] == 5
            assert typed["numbers"]["attack_bonus"] == 9
        elif ".weapon." in sid:
            assert action == catalog[sid]


def test_armor_ease_offers_proficient_choices_and_checks_worn_armor_live(tmp_path):
    b = compile_character(sheet(["tianxia.talent.equipment.armor_ease"], kit={"starting_kit": KIT}), actor_id="actor:factory.compile")
    hide = next(a["parameters"]["typed"] for a in b["action_catalog"] if a["display_name"] == "Hide")
    assert "mode" not in hide["effects"][0]  # Worn armor is checked live, not baked into Hide.
    from combat.ability_checks import hide_check_mode
    from combat.gate2_runtime_content import AN
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import ROOT
    actor_id = b["actor_id"]
    engine = Gate4ControllerEngine(ROOT, match_seed="R9I-armor", typed_bundles=(b,),
        roster_setup={"primary_actor_ids": [actor_id, AN], "team_by_actor": {actor_id: "team:a", AN: "team:b"},
                      "starting_positions": {actor_id: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    assert hide_check_mode(engine, engine.state.actors[actor_id]) == "DISADVANTAGE"
    from combat.gate5_service import CombatService
    from tests.test_mgr_t14_equipment_review import install
    from tests.test_mgr_t14_fitted_armor import PROJECT, sheet as equipment_sheet
    for talents, expected in ((["armor_ease"], {"light", "medium"}), ([], set())):
        install(tmp_path, equipment_sheet(talents))
        commands = CombatService(ROOT, tmp_path).character_preparation_options(PROJECT)["commands"]
        assert {c["parameters"]["category"] for c in commands if c["operation"] == "armor.ease.choose"} == expected
