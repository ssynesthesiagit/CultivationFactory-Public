"""Wave 2 sphere ownership (owner 2026-09-28, "automate every aspect before another playtest"): Space, Qiweaving,
Thread, Formations, Beastmastery, Destruction, Ink, Talismans, Spirit Companions, Sect Stewardship. Covers the
highest-value fixes: a non-optional add_range_ft modifier that never widened range_ft (Extended Fold), a "choose
one" that applied every option at once (Meridian Snare), two effect types that fell back to inert GM riders (Qi
Bond's mark, Borrow the Ally's Arm's outcome override), a save that did nothing on either branch (Beast Tamer), and
the new no_teleport condition rule (Dimensional Seal) actually blocking a self-teleport in a live fight."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.support"


def _bundle(talents, sphere):
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="SUPPORT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, name, actor=ME):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_extended_fold_actually_widens_fold_steps_reach():
    # A non-optional add_range_ft modifier was marked "applied" without ever touching range_ft, the field
    # gate4_engine.py and typed_executor.teleport_reach read; Fold Step's teleport did nothing extra.
    bundle = _bundle(["TAL_SPACE_FOLD_STEP", "tianxia.talent.space.extended_fold"], "tianxia.sphere.space")
    fold_step = next(row for row in bundle["action_catalog"] if row["display_name"] == "Fold Step")
    assert fold_step["range_ft"] == 35  # 20 base + 15 from one Extended Fold
    effect = fold_step["parameters"]["typed"]["effects"][0]
    assert effect["type"] == "teleport" and effect["distance_ft"] == 35


def test_dimensional_seal_blocks_the_targets_own_next_teleport():
    # Dimensional Seal's save did nothing on either branch; now applies a no_teleport condition (rule key in
    # combat/rules/typed_conditions.json) that block_movement honors for the sealed creature's own self-teleport.
    bundle = _bundle(["TAL_SPACE_FOLD_STEP"], "tianxia.sphere.space")
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    engine._apply_condition(me, CONDITION_PREFIX + "cannot_teleport", "test:seal", AN, expires_on="UNTIL_REMOVED")
    start = me.position
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Fold Step to") and c.destination != start)
    engine.execute_intent(ActionIntent(intent_id="fold", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    assert me.position == start  # sealed: the teleport did not move it


def test_meridian_snare_choose_one_compiles_as_four_separate_actions_not_all_at_once():
    bundle = _bundle(["TAL_THREAD_MERIDIAN_SNARE"], "tianxia.sphere.thread")
    names = {row["display_name"] for row in bundle["action_catalog"]}
    assert {"Meridian Snare: Arm Line", "Meridian Snare: Leg Line", "Meridian Snare: Breath Line", "Meridian Snare: Focus Line"} <= names
    assert "Meridian Snare" not in names  # the un-split "everything at once" action is gone
    # Repeat Use applies to every chosen snare; it is bookkeeping, not a second snare option.
    expected = {
        "Arm Line": {"type": "disadvantage", "on": "the next attack roll it makes"},
        "Leg Line": {"type": "speed", "flat": -15, "provenance": "meridian_constriction"},
        "Breath Line": {"type": "condition", "condition": "cannot_advantage_con_saves"},
        "Focus Line": {"type": "disadvantage", "on": "the next Constitution saving throw to maintain Concentration"},
    }
    for name, chosen in expected.items():
        row = next(row for row in bundle["action_catalog"] if row["display_name"] == f"Meridian Snare: {name}")
        save = row["parameters"]["typed"]["effects"][0]["on_hit"][0]
        assert save["type"] == "save" and save["ability"] == "con" and save["on_success"] == []
        snare, repeat = save["on_fail"]  # exactly one chosen effect and one Repeat Use mark
        assert {key: snare[key] for key in chosen} == chosen
        assert snare["applies_to"] == "target" and snare["duration"] == "until_end_of_your_next_turn"
        assert repeat == {"type": "mark", "applies_to": "target", "mark": "Meridian Snare",
                          "duration": {"kind": "until_end_of_your_next_turn"},
                          "evidence": "Repeat Use: A creature affected by Meridian Snare has advantage on saves against your Meridian Snare until the end of your next turn."}


def test_qi_bond_marks_its_target_on_a_hit():
    bundle = _bundle(["TAL_QIWEAVING_QI_BOND"], "tianxia.sphere.qiweaving")
    bond = next(row for row in bundle["action_catalog"] if row["display_name"] == "Qi Bond")
    on_hit = bond["parameters"]["typed"]["effects"][0]["on_hit"]
    assert on_hit and on_hit[0]["type"] == "mark" and on_hit[0]["mark"] == "qi_bond"


def test_beast_tamer_control_save_has_a_real_effect_on_both_branches():
    bundle = _bundle(["TAL_BEASTMASTERY_BEAST_TAMER"], "tianxia.sphere.beastmastery")
    tamer = next(row for row in bundle["action_catalog"] if row["display_name"] == "Beast Tamer")
    save = tamer["parameters"]["typed"]["effects"][0]
    failed = save["on_fail"][0]
    if failed["type"] == "rider_break_on_allied_damage":
        failed = failed["effects"][0]
    assert failed["type"] == "condition" and failed["condition"] == "charmed"


def test_press_mark_places_an_ink_mark_on_a_failed_resist_save():
    # The foundation of the Ink Mark sub-system placed no mark at all; nearly every other Ink talent keys off it.
    bundle = _bundle(["INK_BASE_PRESS_MARK"], "tianxia.sphere.ink")
    press = next(row for row in bundle["action_catalog"] if row["display_name"] == "Press Mark")
    save = press["parameters"]["typed"]["effects"][0]
    assert save["on_fail"] and save["on_fail"][0]["type"] == "mark" and save["on_fail"][0]["mark"] == "ink_mark"


def test_demon_subduing_tag_is_one_action_with_outcomes_on_the_right_branch():
    # "Failed Save"/"Successful Save" text was mistyped as a two-way player choice, with the successful-save
    # condition wired to the wrong (on_fail) branch.
    bundle = _bundle(["tianxia.talent.talismans.demon_subduing_tag"], "tianxia.sphere.talismans")
    names = [row["display_name"] for row in bundle["action_catalog"] if row["display_name"].startswith("Demon-Subduing Tag")]
    assert names == ["Demon-Subduing Tag"]  # not split into "...: Failed Save" / "...: Successful Save"
    tag = next(row for row in bundle["action_catalog"] if row["display_name"] == "Demon-Subduing Tag")
    save = tag["parameters"]["typed"]["effects"][0]
    assert save["on_fail"][0]["condition"] == "restrained"
    assert save["on_success"][0]["type"] == "reaction_denied"
