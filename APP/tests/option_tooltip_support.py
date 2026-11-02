"""Real compiled selector fixtures for Python and Node SOL155 regressions."""
import json
from contextlib import contextmanager
from pathlib import Path
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import auto_buttons, engine_button_layout
from combat.tabletop_service import TabletopService
from tests.test_status_text import _install
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.sol155"
PROJECT = "15500000-0000-0000-0000-000000000000"
FOE = "actor:factory.sol155-foe"
LOCKED_EXPRESSION = "tianxia.path.body_refining.feature.core_tempering_expression"


def sheet():
    return {**SHEET, "spheres_and_talents": {
        "sphere_record_ids": ["tianxia.sphere.iron_fist", "tianxia.sphere.dark", "tianxia.sphere.void", "tianxia.sphere.unmaking"],
        "learned_talent_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING", "DARK_BASE_DARKNESS",
            "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_PERSISTENT_DARKNESS", "TAL_VOID_VOID_NEEDLE", "TAL_VOID_NULLIFYING_STRIKE"]}}


def bundle():
    return compile_character(sheet(), actor_id=OWNER)


def option_match(tmp_path, locked_expression=False):
    """Install the real selector character and seal one real Factory match.

    Returns the character sheet buttons and the persisted table state for the
    two option-listing files: presence, count, order and cost are checked in
    tests/test_option_tooltips.py, the printed wording of the same options in
    tests/test_option_tooltips_printed.py.

    locked_expression is the Core Tempering Expression case: False (not
    offered), True (the three Expressions are offered) or "legacy" (the same
    catalog sealed without the setting_lifetime field).
    """
    owner = sheet()
    if locked_expression:
        owner["identity"] = {**owner["identity"], "path": "Body Refining"}
        owner["path_and_subpath"] = {"path_feature_record_ids": [LOCKED_EXPRESSION]}
    _install(tmp_path, PROJECT, owner)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    buttons = table.sheet(PROJECT)["buttons"]
    if isinstance(buttons, dict):
        buttons = buttons["buttons"]
    own = compile_character(owner, actor_id=OWNER)
    if locked_expression == "legacy":
        for action in own["action_catalog"]:
            if action["parameters"].get("cte_choice"):
                action["parameters"].pop("setting_lifetime")
    mid = combat._finish_factory_match([own, compile_character(sheet(), actor_id=FOE)], [OWNER, FOE],
        {OWNER: "team:a", FOE: "team:b"}, {OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed="SOL155", display_name="SOL155",
        maximum_rounds=5)["match_id"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    if combat._load_session(mid).engine.state.current_actor_id != OWNER:
        turn = state["menu"]
        result = table.act(mid, turn["end_turn"], turn["decision_id"], turn["state_version"],
                           state["last_sequence"], [])
        # Both fighters are compiled from the same sheet, so a handover that did
        # not commit would leave the menu on the foe's seat and the caller would
        # check option listing for the wrong character.
        assert result["status"] == "COMMITTED"
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        state = table.state(mid)
    assert combat._load_session(mid).engine.state.current_actor_id == OWNER
    return {"combat": combat, "table": table, "mid": mid, "buttons": buttons, "state": state}


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
    from tests.record_display_support import install_display_rules
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
            "Synthetic reference prose for this fixture: a creature inside your Darkness "
            "is slowed by it, and its physical efforts falter while it remains there."),
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
    # The legacy Darkness row has no explicit zone effect: its description is
    # also compiler input. Public exports redact that prose independently.
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"]["DARK_BASE_DARKNESS"]["description"] = [
        "Create a sphere of supernatural Darkness centered anywhere within range."]
    # Modifier option labels are compiled from this evidence, not status_text.
    # Keep that prose consistent with the synthetic full rule above.
    failures = {
        "reaction_denied": "the target cannot take Reactions until the start of its next turn",
        "speed": "reduce the target's Speed by 10 feet until the start of your next turn",
        "condition": "the target becomes Hollowed until the start of your next turn",
        "void_suppress_benefit": "suppress one ordinary temporary Resistance until the start of your next turn",
    }
    for option in authority["mechanics"]["TAL_VOID_NULLIFYING_STRIKE"]["modifier"]["options"]:
        for effect in option["effects"]:
            if effect["type"] == "extra_damage":
                effect["evidence"] = "Deal extra Force, Necrotic, or Psychic damage."
            if effect["type"] == "save":
                effect["evidence"] = "The target makes a Constitution saving throw."
                for failure in effect["on_fail"]:
                    failure["evidence"] = failures[failure["type"]]
                for success in effect["on_success"]:
                    success["evidence"] = (
                        "Successful Save: The target cannot gain Temporary HP until the start of your next turn.")
    authority_path = tmp_path / "synthetic-option-authority.json"
    authority_path.write_text(json.dumps(authority))
    with monkeypatch.context() as patch:
        install_display_rules(tmp_path, patch, rules)
        patch.setattr(factory_compiler, "TYPED_AUTHORITY", authority_path)
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
