"""Real compiled selector fixtures for Python and Node SOL155 regressions."""
import json
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, engine_button_layout
from tests.test_zones import SHEET

OWNER = "actor:factory.sol155"


def synthetic_compiler_rules():
    """Give public-export runs the one printed category needed to compile the test choice."""
    from combat import factory_compiler

    return {
        **factory_compiler._rules_text(),
        "TAL_DARK_NUMBING_DARKNESS": (
            "### Numbing Darkness - Darkness\n"
            "Creatures inside your Darkness have Disadvantage on Strength, Dexterity, "
            "and Constitution ability checks and saving throws."
        ),
    }


def sheet():
    return {**SHEET, "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.iron_fist", "tianxia.sphere.dark", "tianxia.sphere.void", "tianxia.sphere.unmaking"],
        "learned_talent_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING", "DARK_BASE_DARKNESS",
            "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS", "TAL_VOID_VOID_NEEDLE", "TAL_VOID_NULLIFYING_STRIKE"]}}


def bundle():
    from combat import factory_compiler

    previous = factory_compiler._RULES_TEXT_CACHE
    factory_compiler._RULES_TEXT_CACHE = synthetic_compiler_rules()
    try:
        return compile_character(sheet(), actor_id=OWNER)
    finally:
        factory_compiler._RULES_TEXT_CACHE = previous


def rows():
    compiled = bundle()
    catalog = {r["source_definition_id"]: r for r in compiled["action_catalog"]}
    buttons = auto_buttons(compiled, {"cultivation_level": 10})
    # Attack-modifier detail settings are table rows; the sheet shows the grouped
    # modifier toggle. Cover both layouts from their real compiled definitions.
    selected = [r for r in buttons if r["label"].startswith(("Open the Gate:", "Shape Darkness:", "Augment Darkness:", "Overdraw:"))
                or r["label"] == "Nullifying Strike"]
    selected += [{"label": r["display_name"], "description": "", "combat": {"source_definition_id": r["source_definition_id"]}}
                 for r in catalog.values() if r["display_name"].startswith("Nullifying Strike:")]
    unique = {r["label"]: r for r in selected}
    return [{"label": r["label"], "description": r["description"],
             "hover": engine_button_layout(catalog[r["combat"]["source_definition_id"]])}
            for r in unique.values()]


if __name__ == "__main__":
    print(json.dumps(rows()))
