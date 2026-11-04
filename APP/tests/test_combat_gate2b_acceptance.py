from __future__ import annotations

from pathlib import Path

import pytest

from combat.gate2_engine import Gate2Engine, SYSTEM_HAZARD, SYSTEM_OPPORTUNITY
from combat.gate2_runtime_content import ACTIONS, AN, BAI, CUI, LEE, LING
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position, ReactionDecision

ROOT = Path(__file__).resolve().parents[1]


def prepared(seed: str, actor_id: str) -> Gate2Engine:
    engine = Gate2Engine(ROOT, match_seed=seed)
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available = True
    actor.bonus_action_available = True
    actor.reaction_available = True
    actor.movement_remaining_ft = actor.speed_ft
    return engine


def intent(candidate, *, name="acceptance", options=(), reactions=()):
    return ActionIntent(
        intent_id=f"intent:{name}",
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
        destination=candidate.destination,
        option_ids=tuple(options),
        reaction_decisions=tuple(reactions),
    )


def test_action_and_bonus_action_economy_enforced_with_fallbacks():
    engine = prepared("ECONOMY", LING)
    engine.state.actors[LING].position = Position(x=10, y=4)
    engine.state.actors[LEE].position = Position(x=5, y=4)
    bonus = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:ling_qi.sound_resonant_note" and c.target_ids == (LEE,))
    engine.execute_intent(intent(bonus, name="bonus"))
    assert not engine.state.actors[LING].bonus_action_available
    assert not any(c.kind == CandidateKind.BONUS_ACTION for c in engine.legal_candidates())
    action = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:ling_qi.dissonant_note" and c.target_ids == (LEE,))
    engine.execute_intent(intent(action, name="action"))
    assert not engine.state.actors[LING].action_available
    remaining = engine.legal_candidates()
    assert not any(c.kind == CandidateKind.ACTION for c in remaining)
    assert any(c.kind == CandidateKind.END_TURN for c in remaining)
    assert any(c.kind == CandidateKind.HOLD_POSITION for c in remaining)


def test_first_arm_runs_all_exact_risk_checks_and_consumes_ruin_tempered_state():
    engine = prepared("FIRST-ARM", AN)
    an = engine.state.actors[AN]
    bai = engine.state.actors[BAI]
    an.position = Position(x=10, y=8)
    bai.position = Position(x=11, y=8)
    quick = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:an_eui.ruin_tempered_armament_quick")
    engine.execute_intent(intent(quick, name="quick", options=("PRIMARY_WEAPON",)))
    assert an.concentration is not None
    assert any(c.condition_id == "condition:an_eui.ruin_tempered" for c in an.conditions.values())
    first = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:an_eui.first_arm" and c.target_ids == (BAI,))
    engine.execute_intent(intent(first, name="first-arm", options=("AC_MINUS_1",)))
    assert an.concentration is None
    assert not any(c.condition_id == "condition:an_eui.ruin_tempered" for c in an.conditions.values())
    integrity = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.payload.get("integrity_check")]
    assert len(integrity) == 1
    self_checks = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == AN and e.source_definition_id == "action:an_eui.first_arm"]
    assert len(self_checks) >= 2


def test_paired_assault_enables_only_one_bonus_paired_strike_candidate():
    engine = prepared("PAIRED", AN)
    engine.state.actors[AN].position = Position(x=10, y=8)
    engine.state.actors[BAI].position = Position(x=11, y=8)
    assault = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:an_eui.paired_bi_shou_assault" and c.target_ids == (BAI,))
    engine.execute_intent(intent(assault, name="paired-assault"))
    bonus = [c for c in engine.legal_candidates() if c.source_definition_id == "action:an_eui.paired_strike" and c.target_ids == (BAI,)]
    assert len(bonus) == 1
    engine.execute_intent(intent(bonus[0], name="paired-strike"))
    assert not engine.state.actors[AN].bonus_action_available


def test_targeted_lightning_charges_self_weapon_willing_and_space_are_bounded():
    engine = prepared("CHARGES", LEE)
    lee = engine.state.actors[LEE]
    lee.position = Position(x=5, y=4)
    engine.state.actors[AN].position = Position(x=5, y=8)
    # Create four typed charges directly through the exact bounded helpers. The fourth evicts the oldest.
    with engine._transaction("action:lee_jia.gather_charge", "charge-set", LEE):
        engine._create_actor_lightning_charge(lee, lee, "SELF", "action:lee_jia.gather_charge")
        engine._create_actor_lightning_charge(lee, lee, "HELD_WEAPON", "action:lee_jia.gather_charge")
        engine._create_actor_lightning_charge(lee, engine.state.actors[AN], "WILLING_CREATURE", "action:lee_jia.gather_charge")
        engine._end_oldest_lightning_charge(lee)
        engine._create_space_lightning_charge(lee, Position(x=8, y=4), "action:lee_jia.gather_charge")
    assert lee.resources["resource:lee_jia.lightning_charge"] == 3
    typed = {c.condition_id for actor in engine.state.actors.values() for c in actor.conditions.values() if "lightning_charge" in c.condition_id}
    assert "condition:lee_jia.lightning_charge.held_weapon" in typed
    assert "condition:lee_jia.lightning_charge.willing_creature" in typed
    assert any(z.active and z.trigger_profile.get("kind") == "CHARGE_SPACE" for z in engine.state.zones.values())


def test_space_charge_discharges_once_on_first_entry():
    engine = prepared("SPACE-CHARGE", LEE)
    lee = engine.state.actors[LEE]
    an = engine.state.actors[AN]
    lee.position = Position(x=5, y=4)
    an.position = Position(x=7, y=4)
    with engine._transaction("action:lee_jia.gather_charge", "space-charge", LEE):
        engine._create_space_lightning_charge(lee, Position(x=8, y=4), "action:lee_jia.gather_charge")
    hp = an.current_hp
    with engine._transaction("system:test.enter-charge", "enter-charge", AN):
        an.position = Position(x=8, y=4)
        engine._resolve_zone_entry_triggers(an)
        engine._resolve_zone_entry_triggers(an)
    assert an.current_hp == hp - 3
    assert not any(z.active and z.trigger_profile.get("kind") == "CHARGE_SPACE" for z in engine.state.zones.values())


def test_spark_step_is_separate_immediate_optional_movement_window():
    engine = prepared("SPARK-STEP", LEE)
    self_charge = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:lee_jia.gather_charge" and c.target_ids == (LEE,) and "SELF" in c.option_ids)
    engine.execute_intent(intent(self_charge, name="gather-self", options=("SELF",)))
    assert engine.state.pending_resolution is not None
    spark = [c for c in engine.legal_candidates() if c.source_definition_id == "talent:lee_jia.spark_step"]
    assert spark
    assert all(c.movement_cost_ft <= 10 for c in spark)
    decline = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.TAKE_NO_OPTIONAL_ACTION)
    engine.execute_intent(intent(decline, name="decline-spark"))
    assert engine.state.pending_resolution is None


def test_opportunity_attack_can_open_bounded_nested_stamina_guard():
    # Find a seed whose next Bai opportunity attack hits An.
    selected = None
    for i in range(1000):
        probe = prepared(f"OA-{i}", AN)
        roll = probe.roller.d20(modifier=5, actor_id=BAI, reason="probe")
        if roll.natural_result == 20 or (roll.natural_result != 1 and roll.total >= 17):
            selected = f"OA-{i}"
            break
    assert selected
    engine = prepared(selected, AN)
    an = engine.state.actors[AN]
    bai = engine.state.actors[BAI]
    an.position = Position(x=5, y=5)
    bai.position = Position(x=5, y=6)
    destination = Position(x=5, y=3)
    move = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE and c.destination == destination)
    stamina_before = an.resources["resource:an_eui.stamina"]
    decisions = (
        ReactionDecision(checkpoint="LEAVE_REACH", reactor_id=BAI, reaction_source_id=SYSTEM_OPPORTUNITY, selection="USE"),
        ReactionDecision(checkpoint="DAMAGE_APPLICATION", reactor_id=AN, reaction_source_id="reaction:core.stamina_guard", selection="USE", spend=1),
    )
    engine.execute_intent(intent(move, name="oa-move", reactions=decisions))
    assert an.resources["resource:an_eui.stamina"] == stamina_before - 1
    assert any(e.source_definition_id == SYSTEM_OPPORTUNITY and e.event_type == "REACTION_RESOLVED" for e in engine.events)
    assert any(e.source_definition_id == "reaction:core.stamina_guard" and e.event_type == "REACTION_RESOLVED" for e in engine.events)
    assert max(e.payload.get("reaction_depth", 0) for e in engine.events) <= 2


def test_qi_hazard_triggers_at_most_once_per_actor_turn():
    engine = prepared("HAZARD", AN)
    an = engine.state.actors[AN]
    an.position = Position(x=8, y=6)
    first = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE and c.destination == Position(x=9, y=6))
    engine.execute_intent(intent(first, name="hazard-one"))
    second = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE and c.destination == Position(x=10, y=6))
    engine.execute_intent(intent(second, name="hazard-two"))
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == SYSTEM_HAZARD]
    assert len(saves) == 1


def test_nocturne_and_blackwater_are_typed_concentration_zones_with_geometry():
    engine = prepared("ZONES", LING)
    ling = engine.state.actors[LING]
    with engine._transaction("action:ling_qi.forgotten_vale_nocturne", "nocturne", LING):
        fake = ActionIntent(intent_id="nocturne", decision_id="n", candidate_id="n", state_version=0, actor_id=LING)
        engine._resolve_zone_action(ling, ACTIONS["action:ling_qi.forgotten_vale_nocturne"], Position(x=10, y=6), fake, zone_kind="NOCTURNE")
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert zone.radius_cells == 4
    assert zone.concentration_link
    assert (10, 6) in {(p.x, p.y) for p in zone.affected_cells}
    assert engine.state.actors[LING].concentration.zone_id == zone.zone_id


def test_damage_concentration_failure_removes_linked_zone():
    found = False
    for index in range(500):
        engine = prepared(f"CONC-FAIL-{index}", LING)
        ling = engine.state.actors[LING]
        # Place zone away from actors to avoid creation saves/rolls.
        with engine._transaction("action:ling_qi.forgotten_vale_nocturne", "zone", LING):
            fake = ActionIntent(intent_id="zone", decision_id="z", candidate_id="z", state_version=0, actor_id=LING)
            engine._resolve_zone_action(ling, ACTIONS["action:ling_qi.forgotten_vale_nocturne"], Position(x=18, y=12), fake, zone_kind="NOCTURNE")
        with engine._transaction("system:test.concentration_damage", "damage", AN):
            engine._commit_damage(ling, 20, "TEST", "system:test.concentration_damage", AN, None, reaction_depth=0)
        if ling.concentration is None:
            found = True
            assert not any(z.active for z in engine.state.zones.values())
            assert any(e.event_type == "CONCENTRATION_ENDED" and e.payload["reason"] == "FAILED_DAMAGE_CHECK" for e in engine.events)
            break
    assert found


def test_temp_hp_keeps_greater_value_and_absorbs_before_hp():
    engine = prepared("TEMP-HP", LING)
    target = engine.state.actors[LEE]
    with engine._transaction("action:ling_qi.keep_the_measure", "temp", LING):
        engine._grant_temp_hp(target, 7, "action:ling_qi.keep_the_measure", LING)
        engine._grant_temp_hp(target, 4, "action:ling_qi.keep_the_measure", LING)
        engine._commit_damage(target, 5, "TEST", "system:test.damage", AN, None, reaction_depth=0)
    assert target.temporary_hp == 2
    assert target.current_hp == target.maximum_hp


def test_reaction_denied_suppresses_reaction_and_refreshes_on_turn_start():
    engine = prepared("REACTION-DENIED", LING)
    ling = engine.state.actors[LING]
    with engine._transaction("system:test.condition", "deny", AN):
        engine._apply_condition(ling, "condition:core.reaction_denied", "system:test.condition", AN, expires_on="START_OF_TARGET_NEXT_TURN")
    assert not engine._reaction_usable(LING, "reaction:ling_qi.qi_armor")
    with engine._transaction("system:test.start", "start", LING):
        engine._expire_for_checkpoint("START_OF_TURN", LING)
        ling.reaction_available = True
    assert engine._reaction_usable(LING, "reaction:ling_qi.qi_armor")


def test_bai_inactive_cui_guard_and_rescue_remains_first_class():
    engine = prepared("CUI-GUARD", BAI)
    bai = engine.state.actors[BAI]
    cui = engine.state.actors[CUI]
    bai.active = False
    bai.current_hp = 0
    bai.action_available = False
    bai.bonus_action_available = False
    bai.reaction_available = False
    bai.movement_remaining_ft = 0
    old = cui.position
    with engine._transaction("system:test.cui_guard", "guard", CUI):
        engine._cui_guard_and_rescue_default()
    assert cui.active
    assert CUI in engine.state.actors
    assert any(c.condition_id == "condition:core.dodge" for c in cui.conditions.values())
    assert any(e.event_type == "COMPANION_DEFAULT_APPLIED" and e.payload["behavior"] == "GUARD_AND_RESCUE" for e in engine.events)
    assert cui.position != old or any(a.active and a.team_id == cui.team_id for a in engine.state.actors.values())


def test_all_committed_events_are_source_authorized_and_state_versions_contiguous_by_transaction():
    engine = Gate2Engine(ROOT, match_seed="SOURCE-AUTH")
    hold = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.HOLD_POSITION)
    engine.execute_intent(intent(hold, name="hold"))
    assert all(e.source_definition_id and (e.source_definition_id.startswith(("action:", "reaction:", "passive:", "talent:", "creature:", "resource:", "system:"))) for e in engine.events)
    assert [e.sequence for e in engine.events] == list(range(1, len(engine.events)+1))
    assert engine.state.pending_resolution is None
