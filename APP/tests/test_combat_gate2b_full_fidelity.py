from __future__ import annotations

from pathlib import Path

from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import ACTIONS, AN, BAI, CUI, LEE, LING
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position, ReactionDecision
from combat.gate2_scripted import execute_script, load_script

ROOT = Path(__file__).resolve().parents[1]


def prepared(seed: str, actor_id: str) -> Gate2Engine:
    engine = Gate2Engine(ROOT, match_seed=seed)
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.active
    actor.bonus_action_available = actor.active
    actor.reaction_available = actor.active
    actor.movement_remaining_ft = actor.speed_ft
    return engine


def intent(candidate, *, name: str, options=(), reactions=()):
    return ActionIntent(
        intent_id=f"intent:{name}", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=tuple(options),
        reaction_decisions=tuple(reactions),
    )


def test_moon_sea_radiance_is_generated_once_per_round_and_sea_risen_is_manual():
    engine = prepared("MOON-SEA", BAI)
    bai = engine.state.actors[BAI]
    with engine._transaction("reaction:bai_meizhen.water_shield", "protect", BAI):
        assert engine._maybe_gain_moon_sea(bai, "PROTECTION_EVENT", "reaction:bai_meizhen.water_shield")
        assert not engine._maybe_gain_moon_sea(bai, "PROTECTION_EVENT", "reaction:bai_meizhen.water_shield")
    assert bai.resources["resource:bai_meizhen.moon_sea_radiance"] == 1
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:bai_meizhen.sea_risen_bearing")
    engine.execute_intent(intent(candidate, name="sea-risen"))
    assert bai.resources["resource:bai_meizhen.moon_sea_radiance"] == 0
    assert bai.temporary_hp == 7
    assert any(z.active and z.trigger_profile.get("kind") == "SEA_RISEN" for z in engine.state.zones.values())


def test_true_name_witness_spends_trace_after_roll_before_declared_result():
    engine = prepared("TRUE-NAME", AN)
    ling = engine.state.actors[LING]
    with engine._transaction("passive:ling_qi.mirror_trace", "seed-trace", LING):
        engine._gain_resource(ling, "resource:ling_qi.mirror_trace", 1, "passive:ling_qi.mirror_trace")
        engine._apply_condition(ling, "condition:ling_qi.mirror_trace_window", "passive:ling_qi.mirror_trace", LING, expires_on="END_OF_LING_NEXT_TURN")
    fake = ActionIntent(
        intent_id="intent:true-name", decision_id="private", candidate_id="private",
        state_version=engine.state.state_version, actor_id=AN,
        reaction_decisions=(ReactionDecision(
            checkpoint="SAVE_RESULT_BEFORE_DECLARED", reactor_id=LING,
            reaction_source_id="action:ling_qi.true_name_witness", selection="USE",
        ),),
    )
    with engine._transaction("system:test.save", fake.intent_id, AN):
        engine._active_intent = fake
        before_counter = engine.roller.counter
        roll = engine._roll_save(ling, "WIS", 99, "system:test.save")
        engine._active_intent = None
    assert roll.modifier == ling.saving_throws["WIS"] + 3
    assert engine.roller.counter > before_counter
    assert ling.resources["resource:ling_qi.mirror_trace"] == 0
    assert any(e.source_definition_id == "action:ling_qi.true_name_witness" for e in engine.events)


def test_bloodline_strike_is_a_separate_post_hit_candidate_and_spends_only_when_selected():
    # Locate a deterministic seed whose next Bai attack is a hit after initialization.
    chosen = None
    for index in range(3000):
        probe = prepared(f"BLOODLINE-{index}", BAI)
        probe.state.actors[BAI].position = Position(x=10, y=8)
        probe.state.actors[LEE].position = Position(x=11, y=8)
        attack = next(c for c in probe.legal_candidates() if c.source_definition_id == "action:bai_meizhen.numbing_venom_palm" and c.target_ids == (LEE,))
        probe.state.actors[BAI].resources["resource:bai_meizhen.ancestral_resonance"] = 1
        probe.execute_intent(intent(attack, name=f"probe-{index}"))
        if probe.state.pending_resolution and "action:bai_meizhen.bloodline_strike" in probe.state.pending_resolution.follow_up_candidates:
            chosen = probe
            break
    assert chosen is not None
    bai = chosen.state.actors[BAI]
    target = chosen.state.actors[LEE]
    hp_before = target.current_hp
    resonance_before_rider = bai.resources["resource:bai_meizhen.ancestral_resonance"]
    candidate = next(c for c in chosen.legal_candidates() if c.source_definition_id == "action:bai_meizhen.bloodline_strike")
    chosen.execute_intent(intent(candidate, name="bloodline"))
    assert bai.resources["resource:bai_meizhen.ancestral_resonance"] == resonance_before_rider - 1
    assert target.current_hp <= hp_before
    assert any(e.source_definition_id == "action:bai_meizhen.bloodline_strike" and e.event_type == "DAMAGE_COMMITTED" for e in chosen.events)


def test_reflection_cut_is_offered_only_from_preexisting_trace_and_is_source_authorized():
    engine = prepared("REFLECTION", LING)
    ling = engine.state.actors[LING]
    lee = engine.state.actors[LEE]
    ling.position = Position(x=10, y=4)
    lee.position = Position(x=11, y=4)
    with engine._transaction("passive:ling_qi.mirror_trace", "seed-trace", LING):
        engine._gain_resource(ling, "resource:ling_qi.mirror_trace", 1, "passive:ling_qi.mirror_trace")
        engine._apply_condition(ling, "condition:ling_qi.mirror_trace_window", "passive:ling_qi.mirror_trace", LING, expires_on="END_OF_LING_NEXT_TURN")
        engine._open_follow_up_window(ling, lee, "action:ling_qi.music_resonant_note", None, ["action:ling_qi.reflection_cut"])
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:ling_qi.reflection_cut")
    hp_before = lee.current_hp
    engine.execute_intent(intent(candidate, name="reflection"))
    assert ling.resources["resource:ling_qi.mirror_trace"] == 0
    assert lee.current_hp == hp_before - 3
    assert any(e.source_definition_id == "action:ling_qi.reflection_cut" and e.event_type == "DAMAGE_COMMITTED" for e in engine.events)


def test_retained_manual_script_is_terminal_and_byte_deterministic_with_cui_first_class():
    script = load_script(ROOT / "combat_gate2/scripted/Gate2_Scripted_Fight_Input.json")
    engine_a, decisions_a = execute_script(ROOT, script)
    engine_b, decisions_b = execute_script(ROOT, script)
    export_a = engine_a.export()
    export_b = engine_b.export()
    assert len(decisions_a) == len(script.steps) == len(decisions_b)
    assert export_a.model_dump(mode="json", by_alias=True) == export_b.model_dump(mode="json", by_alias=True)
    assert engine_a.state.terminal_result is not None
    assert engine_a.state.terminal_result.winning_team_id == "team:ling_qi_bai_meizhen"
    assert CUI in engine_a.state.actors
    assert engine_a.state.actors[CUI].owner_id == BAI
    assert all(event.source_definition_id for event in engine_a.events)
    assert [event.sequence for event in engine_a.events] == list(range(1, len(engine_a.events) + 1))
    assert engine_a.events[-1].event_type == "MATCH_ENDED"
    assert engine_a.state.terminal_result.event_sequence == engine_a.events[-1].sequence
