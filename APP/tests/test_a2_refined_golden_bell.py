"""Refined Golden Bell through CombatService/session choices and cold reload.

Real Body Refining activation and compiled ownership; synthetic actions only
provide deterministic damage, check hazards, a second defense and unconsciousness.
No live model calls or browser launches.
"""
import pytest

from combat.ext.refined_golden_bell import FEATURE, CHOICE, CONDITION, STANCE, LABELS
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, resolve, turn

CTE = "tianxia.path.body_refining.feature.core_tempering_expression"


def fixture(tmp_path, *, owns=True, damage=20, damage_type="force", packets=1, ai=False):
    def sheet_edit(doc, aid):
        if aid == LEFT:
            doc["identity"]["path"] = "Body Refining"
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [FEATURE] if owns else []
            doc["path_and_subpath"] = {"path_feature_record_ids": [CTE],
                                       "core_tempering_expression": "golden_bell"}
    extras = [("Other temporary HP", {"effects": [{"type": "temp_hp", "flat": 20, "applies_to": "self"}]}),
        ("Unconscious", {"effects": [{"type": "condition", "condition": "unconscious",
        "applies_to": "self", "duration": {"kind": "until_removed"}}]}),
        ("Other resistance", {"effects": [{"type": "resistance", "damage_types": ["force"],
            "applies_to": "self", "duration": {"kind": "one_minute"}}]})]
    for hazard in ("forced_movement", "prone", "ordinary"):
        extras.append(("Check " + hazard, {"target_kind": "HOSTILE_ENTITY", "effects": [
            {"type": "contest_against", "actor_check": {"ability": "STR", "skill": "Athletics", "hazards": [hazard]},
             "target_check": {"kind": "dc", "basis": "save_dc"}}]}))
    combat, table, mid = fight(tmp_path, cl=12, left_resource="Stamina", sheet_edit=sheet_edit,
        reaction_ask=not ai, extra_actions=extras, maximum_rounds=30,
        cause=[{"type": "damage", "flat": damage, "applies_to": "target", "damage_types": [damage_type]}] * packets)
    return combat, table, mid


def fresh(combat, mid):
    engine = reload(combat, mid)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return engine


def send(combat, table, mid, label, *, ai=False, choice=None, target=None):
    controller = combat.controller
    try:
        return resolve(action_sender(combat, table, mid, label, ai=ai, target_id=target),
                       {CHOICE: [choice]} if choice else None)
    finally:
        if ai:
            combat.controller = controller
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")


def refine(combat, table, mid, choice="first_packet", *, ai=False):
    return send(combat, table, mid, "Golden Bell Circulation", ai=ai, choice=choice)


def damage(table, mid):
    return resolve(lambda answers: act(table, mid, "Cause", answers, target_id=LEFT))


def selection(engine):
    return next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == CONDITION)


@pytest.mark.parametrize("choice", list(LABELS))
def test_every_printed_refinement_is_reachable_and_persisted(tmp_path, choice):
    combat, table, mid = fixture(tmp_path)
    before = fresh(combat, mid).state.actors[LEFT].resources["resource:core.stamina"]
    _, prompts = refine(combat, table, mid, choice)
    engine = fresh(combat, mid)
    actor = engine.state.actors[LEFT]
    c = selection(engine)
    parent = next(c for c in actor.conditions.values() if c.condition_id == STANCE)
    assert c.data["choice"] == choice and c.data["pb"] == 4
    assert c.data["stance_instance"] == parent.instance_id and c.expires_on == parent.expires_on
    assert actor.resources["resource:core.stamina"] == before - 3
    assert actor.temporary_hp == (8 if choice == "temporary_hp" else 0)
    question = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert {o["id"] for o in question["choice"]["options"]} == set(LABELS)
    assert "Refined Golden Bell" in str(question) and "Keeper" in str(question)
    assert "No extra action or Stamina cost" in str(question)


def test_ai_selects_without_player_prompt_or_enemy_knowledge(tmp_path):
    combat, table, mid = fixture(tmp_path, ai=True)
    _, prompts = refine(combat, table, mid, ai=True)
    assert not prompts
    assert selection(fresh(combat, mid)).data["choice"] == "temporary_hp"
    assert fresh(combat, mid).state.actors[LEFT].temporary_hp == 8


def test_nonowner_activates_ordinary_bell_without_refinement(tmp_path):
    combat, table, mid = fixture(tmp_path, owns=False)
    _, prompts = refine(combat, table, mid)
    engine = fresh(combat, mid)
    assert not prompts
    assert any(c.condition_id == STANCE for c in engine.state.actors[LEFT].conditions.values())
    assert not any(c.condition_id == CONDITION for c in engine.state.actors[LEFT].conditions.values())
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 980


@pytest.mark.parametrize("kind,expected", [("force", 990), ("fire", 980)])
def test_force_resistance_only_halves_force_and_does_not_stack(tmp_path, kind, expected):
    combat, table, mid = fixture(tmp_path, damage_type=kind)
    refine(combat, table, mid, "force_resistance")
    send(combat, table, mid, "Other resistance")
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == expected


def test_first_packet_is_post_percentage_and_only_once_per_round_across_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, damage=21)
    refine(combat, table, mid)
    send(combat, table, mid, "Other resistance")
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 994  # floor(21/2) - PB
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 984
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 978


def test_two_packets_in_one_activation_get_only_one_reduction(tmp_path):
    combat, table, mid = fixture(tmp_path, packets=2)
    refine(combat, table, mid)
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 964


def test_zero_packet_does_not_spend_round_use(tmp_path):
    combat, table, mid = fixture(tmp_path, damage=0)
    refine(combat, table, mid)
    turn(table, mid, RIGHT)
    damage(table, mid)
    engine = fresh(combat, mid)
    assert not any(e.source_definition_id == FEATURE and "reduction_round" in e.payload for e in engine.events)


@pytest.mark.parametrize("hazard,expected", [("forced_movement", "ADVANTAGE"), ("prone", "ADVANTAGE"), ("ordinary", "NORMAL")])
def test_anchoring_advantage_uses_actual_check_hazard(tmp_path, hazard, expected):
    combat, table, mid = fixture(tmp_path)
    refine(combat, table, mid, "anchoring")
    send(combat, table, mid, "Check " + hazard, target=RIGHT)
    engine = fresh(combat, mid)
    records = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == LEFT]
    assert records[-1].payload["actor"]["mode"] == expected
    assert selection(engine).data["choice"] == "anchoring"  # unrelated activation does not refresh it


def test_reactivation_replaces_old_choice_without_stacking(tmp_path):
    combat, table, mid = fixture(tmp_path)
    refine(combat, table, mid)
    turn(table, mid, RIGHT)
    damage(table, mid)
    first_round = fresh(combat, mid).state.round_number
    turn(table, mid, LEFT)
    refine(combat, table, mid, "force_resistance")
    engine = fresh(combat, mid)
    assert sum(c.condition_id == CONDITION for c in engine.state.actors[LEFT].conditions.values()) == 1
    assert selection(engine).data["choice"] == "force_resistance"
    turn(table, mid, RIGHT)
    damage(table, mid)
    assert fresh(combat, mid).state.actors[LEFT].current_hp == 974
    assert any(e.payload.get("reduction_round") == first_round for e in engine.events)


@pytest.mark.parametrize("choice", ["force_resistance", "temporary_hp"])
def test_ending_bell_ends_refinement_through_nested_condition_receipts(tmp_path, choice):
    combat, table, mid = fixture(tmp_path)
    refine(combat, table, mid, choice)
    send(combat, table, mid, "Unconscious")
    engine = fresh(combat, mid)
    assert not any(c.condition_id in {STANCE, CONDITION} for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].temporary_hp == 0


@pytest.mark.parametrize("before", [False, True])
def test_ending_refinement_preserves_an_unrelated_temporary_hp_pool(tmp_path, before):
    combat, table, mid = fixture(tmp_path)
    if before:
        send(combat, table, mid, "Other temporary HP")
    refine(combat, table, mid, "temporary_hp")
    if not before:
        send(combat, table, mid, "Other temporary HP")
    send(combat, table, mid, "Unconscious")
    assert fresh(combat, mid).state.actors[LEFT].temporary_hp == 20


@pytest.mark.parametrize("choice", ["force_resistance", "temporary_hp"])
def test_natural_bell_expiry_removes_refinement(tmp_path, choice):
    combat, table, mid = fixture(tmp_path)
    refine(combat, table, mid, choice)
    for _ in range(11):
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
    engine = fresh(combat, mid)
    assert not any(c.condition_id in {STANCE, CONDITION} for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].temporary_hp == 0


def test_reactivation_replaces_temporary_hp_refinement_without_leaving_its_pool(tmp_path):
    combat, table, mid = fixture(tmp_path)
    refine(combat, table, mid, "temporary_hp")
    assert fresh(combat, mid).state.actors[LEFT].temporary_hp == 8
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    refine(combat, table, mid, "force_resistance")
    engine = fresh(combat, mid)
    assert selection(engine).data["choice"] == "force_resistance"
    assert engine.state.actors[LEFT].temporary_hp == 0
