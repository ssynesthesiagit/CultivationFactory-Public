"""Real compiled selector fixtures for Python and Node SOL155 regressions."""
import json
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


if __name__ == "__main__":
    print(json.dumps(rows()))
