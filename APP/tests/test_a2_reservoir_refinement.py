"""Golden Core's second scene use through table/session commits and cold replay.

Synthetic free setup actions only drain Qi or exercise ordinary Exhaustion
cures; Golden Core and the Insight are compiled from printed authority.
"""
import pytest

from combat.ext import forged_exhaustion as exhaustion
from combat.ext import qi_path as qi
from combat.ext.reservoir_refinement import FEATURE
from tests.auto_worker1_support import LEFT, RIGHT, action_sender, fight, reload, resolve, turn


def fixture(tmp_path, *, cl=10, owns=True, initial_exhaustion=0, immune=False):
    def sheet_edit(doc, aid):
        if aid == LEFT:
            doc["identity"]["path"] = "Qi Cultivation"
            # The Golden Core Form is a fixed build choice recorded on the sheet,
            # so the character holds Reservoir from the first menu instead of switching it in the fight.
            doc["path_and_subpath"] = {"path_feature_record_ids": [qi.GOLDEN], "golden_core_forms": ["reservoir"]}
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [FEATURE] if owns else []

    def bundle_edit(bundle):
        if bundle["actor_id"] == LEFT:
            for resource in bundle["actor_template"]["resources"]:
                if resource["resource_id"] == qi.QI:
                    resource["initial"] = 20

    extras = [("Empty Qi", {"target_kind": "SELF", "effects": [
        {"type": "spend_resource", "applies_to": "self", "resource_id": qi.QI, "flat": 20}]}),
        ("Empty recovery", {"target_kind": "SELF", "effects": [
            {"type": "spend_resource", "applies_to": "self", "resource_id": qi.QI, "flat": 10}]}),
        ("Cure levels", {"target_kind": "SELF", "effects": [
            {"type": "exhaustion", "applies_to": "self", "amount": -5}]}),
        ("Remove Exhaustion", {"target_kind": "SELF", "effects": [
            {"type": "remove_condition", "applies_to": "self", "condition": "exhaustion"}]}),
        ("Ordinary Exhaustion", {"target_kind": "SELF", "effects": [
            {"type": "exhaustion", "applies_to": "self", "amount": 1}]}),
        ("End scene", {"target_kind": "HOSTILE_ENTITY", "effects": [
            {"type": "damage", "applies_to": "target", "flat": 2000, "damage_types": ["force"]}]})]
    setup = [{"type": "exhaustion", "applies_to": "self", "amount": initial_exhaustion}] if initial_exhaustion else []
    if immune:
        setup.append({"type": "condition", "condition": "exhaustion_ward", "applies_to": "self",
                      "duration": "until_removed", "condition_data": {"rule": {"condition_immunities": ["exhaustion"]}}})
    combat, table, mid = fight(tmp_path, cl=cl, left_resource="Qi", left_pb=4, ally=None,
        sheet_edit=sheet_edit, bundle_edit=bundle_edit, extra_actions=extras,
        prepare=setup, prepare_target="SELF")
    return combat, table, mid


def send(combat, table, mid, label, *, ai=False):
    controller = combat.controller
    try:
        return resolve(action_sender(combat, table, mid, label, ai=ai))
    finally:
        if ai:
            combat.controller = controller
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")


def fresh(combat, mid):
    engine = reload(combat, mid)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return engine.state.actors[LEFT]


def labels(table, mid):
    return [row["label"] for row in table.state(mid)["menu"]["actions"]]


def next_turn(table, mid):
    from tests.auto_worker1_support import act
    resolve(lambda answers: act(table, mid, "end", answers))
    turn(table, mid, LEFT)


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("cl,amount", [(10, 6), (17, 10)])
def test_two_uses_restore_the_normal_or_perfected_amount_then_protect_exhaustion(tmp_path, ai, cl, amount):
    combat, table, mid = fixture(tmp_path, cl=cl)
    first, prompts = send(combat, table, mid, "Golden Core Reservoir", ai=ai)
    assert not prompts  # no optional benefit or cost choice in this printed rule
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 20 + amount
    assert exhaustion.level(me) == 0
    next_turn(table, mid)
    assert "Golden Core Reservoir" in labels(table, mid)
    second, _ = send(combat, table, mid, "Golden Core Reservoir", ai=ai)
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 20 + 2 * amount
    assert me.turn_flags["golden_core_reservoir_round_used"] == 2
    assert exhaustion.level(me) == 1
    condition = next(c for c in me.conditions.values() if c.condition_id == exhaustion.CONDITION_ID)
    assert condition.data["scene_locked_levels"] == 1
    events = reload(combat, mid).events
    restored = max(event.sequence for event in events if event.event_type == "RESOURCE_GAINED"
                   and event.payload.get("resource_id") == qi.QI)
    exhausted = max(event.sequence for event in events if event.event_type == "CONDITION_APPLIED"
                    and event.payload.get("condition_id") == exhaustion.CONDITION_ID)
    assert restored < exhausted
    send(combat, table, mid, "Cure levels", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 1
    send(combat, table, mid, "Remove Exhaustion", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 1
    next_turn(table, mid)
    assert "Golden Core Reservoir" not in labels(table, mid)
    assert fresh(combat, mid).turn_flags["golden_core_reservoir_round_used"] == 2


def test_nonowners_keep_one_use_and_ordinary_exhaustion_can_be_cured(tmp_path):
    combat, table, mid = fixture(tmp_path, owns=False, initial_exhaustion=2)
    send(combat, table, mid, "Prepare")
    assert exhaustion.level(fresh(combat, mid)) == 2
    send(combat, table, mid, "Remove Exhaustion")
    assert exhaustion.level(fresh(combat, mid)) == 0
    send(combat, table, mid, "Golden Core Reservoir")
    next_turn(table, mid)
    assert "Golden Core Reservoir" not in labels(table, mid)


def test_cures_remove_unprotected_levels_without_erasing_the_scene_cost(tmp_path):
    combat, table, mid = fixture(tmp_path, initial_exhaustion=2)
    send(combat, table, mid, "Prepare")
    send(combat, table, mid, "Golden Core Reservoir")
    next_turn(table, mid)
    send(combat, table, mid, "Golden Core Reservoir")
    assert exhaustion.level(fresh(combat, mid)) == 3
    send(combat, table, mid, "Cure levels")
    me = fresh(combat, mid)
    assert exhaustion.level(me) == 1
    assert next(c for c in me.conditions.values() if c.condition_id == exhaustion.CONDITION_ID).data["scene_locked_levels"] == 1


def test_perfected_unused_turn_recovery_counts_first_but_second_use_is_a_bonus_action(tmp_path):
    combat, table, mid = fixture(tmp_path, cl=17)
    send(combat, table, mid, "Empty Qi")
    assert fresh(combat, mid).resources[qi.QI] == 0
    next_turn(table, mid)
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 10
    assert me.bonus_action_available
    assert me.turn_flags["golden_core_reservoir_round_used"] == 1
    assert exhaustion.level(me) == 0
    send(combat, table, mid, "Empty recovery")
    next_turn(table, mid)
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 0  # already used: no second automatic activation
    assert me.bonus_action_available
    send(combat, table, mid, "Golden Core Reservoir")
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 10
    assert not me.bonus_action_available
    assert exhaustion.level(me) == 1


@pytest.mark.parametrize("ai", [False, True])
def test_the_second_use_cost_is_unavoidable_without_disabling_ordinary_immunity(tmp_path, ai):
    combat, table, mid = fixture(tmp_path, immune=True)
    send(combat, table, mid, "Prepare", ai=ai)
    send(combat, table, mid, "Ordinary Exhaustion", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 0
    send(combat, table, mid, "Golden Core Reservoir", ai=ai)
    next_turn(table, mid)
    send(combat, table, mid, "Golden Core Reservoir", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 1
    send(combat, table, mid, "Ordinary Exhaustion", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 1
    send(combat, table, mid, "Remove Exhaustion", ai=ai)
    assert exhaustion.level(fresh(combat, mid)) == 1


def test_the_cost_remains_exhaustion_but_its_removal_lock_ends_with_the_scene(tmp_path):
    combat, table, mid = fixture(tmp_path)
    send(combat, table, mid, "Golden Core Reservoir")
    next_turn(table, mid)
    send(combat, table, mid, "Golden Core Reservoir")
    engine = reload(combat, mid)
    assert exhaustion.locked_level(engine, engine.state.actors[LEFT]) == 1
    send(combat, table, mid, "End scene")
    me = fresh(combat, mid)
    engine = reload(combat, mid)
    assert engine.state.terminal_result is not None
    assert exhaustion.level(me) == 1  # the cost does not heal itself at scene end
    assert exhaustion.locked_level(engine, me) == 0


def test_a_second_use_at_five_exhaustion_still_restores_qi_then_defeats_the_owner(tmp_path):
    combat, table, mid = fixture(tmp_path, initial_exhaustion=5)
    send(combat, table, mid, "Prepare")
    send(combat, table, mid, "Golden Core Reservoir")
    next_turn(table, mid)
    send(combat, table, mid, "Golden Core Reservoir")
    me = fresh(combat, mid)
    assert me.resources[qi.QI] == 32
    assert exhaustion.level(me) == 6
    assert not me.active
    assert reload(combat, mid).state.terminal_result is not None


def test_whole_condition_cures_remove_ordinary_levels_without_protecting_them_as_well(tmp_path):
    combat, table, mid = fixture(tmp_path, initial_exhaustion=2)
    send(combat, table, mid, "Prepare")
    send(combat, table, mid, "Golden Core Reservoir")
    next_turn(table, mid)
    send(combat, table, mid, "Golden Core Reservoir")
    assert exhaustion.level(fresh(combat, mid)) == 3
    send(combat, table, mid, "Remove Exhaustion")
    assert exhaustion.level(fresh(combat, mid)) == 1
    send(combat, table, mid, "Remove Exhaustion")
    assert exhaustion.level(fresh(combat, mid)) == 1
