"""The Piercing Needle's base kit (owner 2026-09-28, "automate every aspect"): Feint, Exploits and Disarming Technique.
combat/factory_compiler.py, combat/typed_executor.py apply_exploit."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.needle"
TALENTS = ["TAL_FENCING_FEINT", "TAL_FENCING_CHEST_STRIKE"]


def _bundle():
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.the_piercing_needle"], "learned_talent_record_ids": TALENTS}}
    return compile_character(sheet, actor_id=ME)


def test_the_kit_compiles_without_a_free_advantage_on_every_attack():
    bundle = _bundle()
    names = [row["display_name"] for row in bundle["action_catalog"]]
    assert "Feint" in names and "Exploit: Chest Strike" in names
    assert not [name for name in names if name.endswith("+ Feint")]
    assert any(name.endswith("attack: Disarm") for name in names)  # Disarming Technique on a melee weapon
    assert "Chest Strike" not in bundle["diagnostics"]["skipped"]["passive"]


def test_feint_then_attack_with_advantage_applies_the_exploit_once_a_round():
    engine = Gate4ControllerEngine(ROOT, match_seed="NEEDLE", typed_bundles=(_bundle(),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[AN]
    feint = next(c for c in engine.legal_candidates() if c.display_name == "Feint")
    engine.execute_intent(ActionIntent(intent_id="feint", decision_id=feint.decision_id, candidate_id=feint.candidate_id,
                                       state_version=feint.state_version, actor_id=ME, target_ids=feint.target_ids))
    # Feint (task F, 2026-09-29) is the Help rule's Advantage: the fencer's next attack roll against that enemy (combat/ext/needle_feint.py)
    me = engine.state.actors[ME]
    assert [m for m in me.modifiers.values() if m.target_field == "attack_mode_vs" and m.value == f"ADVANTAGE:{foe.entity_id}"]
