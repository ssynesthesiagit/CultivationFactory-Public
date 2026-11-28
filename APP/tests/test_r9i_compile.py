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


def test_armor_ease_preserves_choices_as_rider_without_mechanical_benefit():
    b = compile_character(sheet(["tianxia.talent.equipment.armor_ease"], kit={"starting_kit": KIT}), actor_id="actor:factory.compile")
    hide = next(a["parameters"]["typed"] for a in b["action_catalog"] if a["display_name"] == "Hide")
    assert hide["effects"][0]["mode"] == "DISADVANTAGE"
    text = " ".join(hide["riders"])
    assert "light, medium or heavy" in text and "proficiency" in text and "repeated choices must differ" in text
