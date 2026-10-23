"""Real compiled selector fixtures for Python and Node SOL155 regressions."""
import json
from contextlib import contextmanager
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons, engine_button_layout
from tests.test_zones import SHEET

OWNER = "actor:factory.sol155"


def sheet():
    return {**SHEET, "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.iron_fist", "tianxia.sphere.dark", "tianxia.sphere.void", "tianxia.sphere.unmaking"],
        "learned_talent_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING", "DARK_BASE_DARKNESS",
            "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS", "TAL_VOID_VOID_NEEDLE", "TAL_VOID_NULLIFYING_STRIKE"]}}


def bundle():
    return compile_character(sheet(), actor_id=OWNER)


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


@contextmanager
def synthetic_option_rules(tmp_path, monkeypatch):
    """Supply stable prose to both shape compilation and tooltip projection.

    Public exports redact printed text, including category headings. Keep the
    real typed mechanics/compiler/menu builders; replace only reference prose.
    """
    from combat import factory_compiler, status_text, option_text
    rules = {**status_text.printed_rules(),
        "printed_option:Breath-Checking Strike": (
            "##### Open the Gate\nWhen you Open a creature, choose an effect.\n"
            "###### Breath-Checking Strike\nThe target cannot take Opportunity Attacks until the start of its next turn."),
        "printed_option:Centerline Impact": (
            "###### Centerline Impact\nWhen the triggering attack deals damage, add your Proficiency Bonus to that damage."),
        "printed_option:Hooking Step": (
            "###### Hooking Step\nMove yourself 5 feet without provoking Opportunity Attacks."),
        "TAL_DARK_NUMBING_DARKNESS": (
            "### Numbing Darkness - Darkness\n"
            "Creatures inside your Darkness have Disadvantage on Strength, Dexterity, "
            "and Constitution ability checks and saving throws."),
        "printed_option:Numbing Darkness": (
            "###### Numbing Darkness\nApply Numbing Darkness to the selected area."),
        "printed_option:Persistent Darkness": (
            "###### Persistent Darkness\nThe selected area lasts without Concentration."),
        "printed_option:unmaking.overdraw": (
            "###### Overdraw\nOn the next qualifying hit, add bonus Ruin damage."),
        "TAL_VOID_NULLIFYING_STRIKE": (
            "#### Nullifying Strike\nCost: 2 cultivation points or 2 Stamina\n"
            "The target makes a Constitution saving throw.\nFailed Save: Choose one:\n"
            "the target becomes Hollowed until the start of your next turn;\n"
            "the target cannot take Reactions until the start of its next turn;\n"
            "suppress one ordinary temporary Resistance until the start of your next turn;\n"
            "reduce the target’s Speed by 10 feet until the start of your next turn.\n"
            "Successful Save: The target cannot gain Temporary HP until the start of your next turn."),
        "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke": (
            "#### Saint-Body Rebuke\nCost: 1 Golden Sea Pulse\n"
            "After a qualifying hit, choose one rider: "
            "push the target 5 feet if it is no more than one size larger than you; "
            "the target cannot take Reactions against you until the start of your next turn; or "
            "you gain Advantage on the next eligible Saint-Body Frame resistance roll "
            "against that target before the start of your next turn."),
    }
    path = tmp_path / "synthetic-option-rules.json"
    path.write_text(json.dumps(rules))
    with monkeypatch.context() as patch:
        patch.setattr(status_text, "RULES_TEXT_PATH", path)
        # Shape selectors use this separate reader to find the talent category.
        # Tooltip-only synthetic prose cannot restore a redacted category.
        patch.setattr(factory_compiler, "_RULES_TEXT_CACHE", {
            **factory_compiler._rules_text(),
            "TAL_DARK_NUMBING_DARKNESS": rules["TAL_DARK_NUMBING_DARKNESS"],
        })
        option_text._names.cache_clear()
        try:
            yield
        finally:
            option_text._names.cache_clear()


if __name__ == "__main__":
    print(json.dumps(rows()))
