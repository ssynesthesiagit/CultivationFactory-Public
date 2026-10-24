"""w4-roster (owner 2026-09-28, "automate every aspect before another playtest"): GM-only-line pass over the five
fielded characters whose own workers finished earlier -- Tabik Damu, Gu Xiangze, Lingfeng Ironroot, Lingfeng Ironclad,
Shi Xunyun. Each test below exercises one real automation gap this worker closed; see the reviewed_final.d entries
and combat/ext modules named in each docstring for the corresponding typing/mechanism.
"""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_tabik import ME as TABIK, _do as _tabik_do, _ninja
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------ Tabik: Veil Escape
def test_veil_escape_offers_a_free_five_foot_move_once_per_turn_inside_the_smoke():
    """tianxia.subpath.qi.ninpo_adept.feature.smoke_veil's 'Veil Escape': once per turn after entering your Smoke
    Veil or using Shadow Step into it, move 5 feet without provoking. combat/ext/tabik_ninpo.py veil_escape_move."""
    engine, _bundle = _ninja()
    me = engine.state.actors[TABIK]
    names = lambda: {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None)  # noqa: E731
                     for c in engine.legal_candidates() if c.actor_id == TABIK}
    assert "Veil Escape" not in names()  # not inside any Smoke Veil yet
    _tabik_do(engine, "Smoke Veil", at=(3, 6))  # smoke over itself
    assert "Veil Escape" in names()
    before = me.movement_remaining_ft
    _tabik_do(engine, "Veil Escape")
    assert me.movement_remaining_ft == before + 5
    assert me.turn_flags.get("oa_free_ft") == 5
    assert "Veil Escape" not in names()  # once per turn


# ------------------------------------------------------------------------------------------------ Gu: Gravity Weight Shift
GU = "actor:factory.gu"


def _gu_engine(base_abilities=(), *, path_features=()):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.gravity"] if base_abilities else [],
                                     "automatic_sphere_component_record_ids": list(base_abilities)},
             "path_and_subpath": {"path_feature_record_ids": list(path_features)}}
    bundle = compile_character(sheet, actor_id=GU)
    engine = Gate4ControllerEngine(ROOT, match_seed="GRAVITY", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [GU, AN], "team_by_actor": {GU: "team:a", AN: "team:b"},
                                                 "starting_positions": {GU: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(GU)
    engine.state.current_actor_id = GU
    engine._system_start_turn()
    return engine, bundle


def _gu_do(engine, name, **kwargs):
    candidate = next(c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=GU, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_weight_shift_base_offers_the_three_modes_as_separate_actions_with_no_leftover_menu_text():
    """TAL_GRAVITY_WEIGHT_SHIFT_BASE: 'choose one mode' is three actions (Body Lightening/Heavying already had
    effects; the raw rider used to re-print all three modes' full text on every one of them -- authority/typed_
    mechanics/reviewed_final.d/gu.json trims that to the two bits the table cannot track (jump distance, carrying
    capacity))."""
    _engine_, bundle = _gu_engine(["TAL_GRAVITY_WEIGHT_SHIFT_BASE"])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Weight Shift: Body Lightening", "Weight Shift: Body Heavying"} <= names
    lightening = next(row for row in bundle["action_catalog"] if row["display_name"] == "Weight Shift: Body Lightening")
    riders = lightening["parameters"]["typed"].get("riders") or []
    assert not any(r.startswith("Choose one mode") for r in riders)


def test_external_weight_shift_offers_willing_and_unwilling_options_including_the_previously_missing_uplift():
    """TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT was typed as a single collapsed Burden effect (the model's 'choose-one
    applied all at once' bug); authority/typed_mechanics/reviewed_final.d/gu.json splits it into the four printed
    choices (Willing: Lightening/Heavying newly work on an external target; Unwilling: Burden/Uplift)."""
    _engine_, bundle = _gu_engine(["TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT"])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {f"External Weight Shift: {label}" for label in
            ("Willing: Body Lightening", "Willing: Body Heavying", "Unwilling: Burden", "Unwilling: Uplift")} <= names


# ------------------------------------------------------------------------------------------------ Gu: Dust to Dust
def test_dust_to_dust_reduce_structure_now_exists_and_scales_at_cl17():
    """tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust: the model dropped the third of three printed choices
    (Reduce Structure) entirely -- only Crumble Matter and Erode Defense compiled. reviewed_final.d/gu.json adds it
    back with its CL17 damage step; Crumble Matter and Reduce Structure act on placed objects only (sysv2_objects.json)."""
    _engine_, bundle = _gu_engine(path_features=["tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust"])
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert "Dust to Dust: Reduce Structure" in names
    reduce_structure = next(row for row in bundle["action_catalog"] if row["display_name"] == "Dust to Dust: Reduce Structure")
    # Fight audit 2026-09-29: typed as 6d8 in a 5-foot cube it hit creatures. Since sysv2 objects it is an object_damage
    # effect: it runs only against a placed object (combat/ext/objects.py, tests/test_sysv2_objects.py), 6d8 and 8d8 at CL17.
    typed = reduce_structure["parameters"]["typed"]
    assert [effect["type"] for effect in typed["effects"]] == ["object_damage"] and not reduce_structure["parameters"].get("inert")
    assert typed["effects"][0]["dice_by_cl"][-1] == [17, 20, 8, 8]
