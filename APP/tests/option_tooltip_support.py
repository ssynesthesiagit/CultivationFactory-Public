"""Real compiled selector fixtures for Python and Node SOL155 regressions."""
import copy
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


def synthetic_authority_reader(original):
    """Supply the public-safe typed row needed to compile the Darkness choice."""
    mechanic_id = "TAL_DARK_NUMBING_DARKNESS"

    def read(path):
        authority, digest = original(path)
        authority = copy.deepcopy(authority)
        authority.setdefault("mechanics", {}).setdefault(mechanic_id, {
            "mechanic_id": mechanic_id,
            "name": "Numbing Darkness",
            "sphere_id": "tianxia.sphere.dark",
            "activation": {},
            "effects": [{"type": "disadvantage", "applies_to": "creatures_in_area"}],
            "cost": [],
        })
        return authority, digest

    return read


def sheet():
    return {**SHEET, "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.iron_fist", "tianxia.sphere.dark", "tianxia.sphere.void", "tianxia.sphere.unmaking"],
        "learned_talent_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING", "DARK_BASE_DARKNESS",
            "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS", "TAL_VOID_VOID_NEEDLE", "TAL_VOID_NULLIFYING_STRIKE"]}}


def bundle():
    from combat import factory_compiler

    previous = factory_compiler._RULES_TEXT_CACHE
    original_reader = factory_compiler._read_compilation_authority
    factory_compiler._RULES_TEXT_CACHE = synthetic_compiler_rules()
    factory_compiler._read_compilation_authority = synthetic_authority_reader(original_reader)
    try:
        return compile_character(sheet(), actor_id=OWNER)
    finally:
        factory_compiler._RULES_TEXT_CACHE = previous
        factory_compiler._read_compilation_authority = original_reader


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
