from __future__ import annotations

from pathlib import Path

import pytest

from combat.diagnostics import CombatGate1Error
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import ACTIONS, AN, BAI, CUI, LEE, LING
from combat.gate2_runtime_models import ActionIntent, CandidateKind, Position, ReactionDecision

ROOT = Path(__file__).resolve().parents[1]


def intent_for(candidate, *, intent_id="mechanic", options=(), reactions=()):
    return ActionIntent(
        intent_id=intent_id,
        decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,
        state_version=candidate.state_version,
        actor_id=candidate.actor_id,
        target_ids=candidate.target_ids,
        destination=candidate.destination,
        option_ids=tuple(options),
        reaction_decisions=tuple(reactions),
    )


def prepared_engine(seed: str, actor_id: str) -> Gate2Engine:
    engine = Gate2Engine(ROOT, match_seed=seed)
    engine.state.current_actor_id = actor_id
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    actor = engine.state.actors[actor_id]
    actor.action_available = True
    actor.bonus_action_available = True
    actor.reaction_available = True
    actor.movement_remaining_ft = actor.speed_ft
    return engine


def find_seed_for_next_attack(minimum_total: int, maximum_total: int, *, bonus: int = 6) -> str:
    for index in range(5000):
        seed = f"ATTACK-SEED-{index}"
        engine = Gate2Engine(ROOT, match_seed=seed)
        roll = engine.roller.d20(modifier=bonus, actor_id=LEE, reason="probe")
        if minimum_total <= roll.total <= maximum_total and roll.natural_result not in (1, 20):
            return seed
    raise AssertionError("no deterministic seed found")


def find_seed_for_hit(*, bonus: int, ac: int) -> str:
    for index in range(5000):
        seed = f"HIT-SEED-{index}"
        engine = Gate2Engine(ROOT, match_seed=seed)
        roll = engine.roller.d20(modifier=bonus, actor_id=BAI, reason="probe")
        if roll.natural_result == 20 or (roll.natural_result != 1 and roll.total >= ac):
            return seed
    raise AssertionError("no hit seed")


def test_qi_armor_rechecks_provisional_ranged_hit_into_miss():
    # Ling AC 13; Qi Armor raises it to 16. Force the next attack total into 13..15.
    seed = find_seed_for_next_attack(13, 15)
    engine = prepared_engine(seed, LEE)
    lee = engine.state.actors[LEE]
    ling = engine.state.actors[LING]
    lee.position = Position(x=10, y=4)
    ling.position = Position(x=17, y=4)
    qi_before = ling.resources["resource:ling_qi.qi"]
    hp_before = ling.current_hp
    action = ACTIONS["action:lee_jia.lightning_lash"]
    fake = ActionIntent(
        intent_id="qi-armor",
        decision_id="private-test",
        candidate_id="private-test",
        state_version=engine.state.state_version,
        actor_id=LEE,
        target_ids=(LING,),
        reaction_decisions=(ReactionDecision(
            checkpoint="ATTACK_HIT_BEFORE_DAMAGE",
            reactor_id=LING,
            reaction_source_id="reaction:ling_qi.qi_armor",
            selection="USE",
        ),),
    )
    with engine._transaction(action.source_definition_id, fake.intent_id, LEE):
        hit = engine._resolve_attack_action(lee, ling, action, fake)
    assert not hit
    assert ling.current_hp == hp_before
    assert ling.resources["resource:ling_qi.qi"] == qi_before - 2
    assert not ling.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "reaction:ling_qi.qi_armor" and e.event_type == "REACTION_RESOLVED"]
    assert resolved[-1].payload["hit_after_recheck"] is False


def test_water_whip_exists_only_after_hit_and_charges_on_selection():
    seed = find_seed_for_hit(bonus=7, ac=14)
    engine = prepared_engine(seed, BAI)
    bai = engine.state.actors[BAI]
    lee = engine.state.actors[LEE]
    bai.position = Position(x=8, y=8)
    lee.position = Position(x=13, y=8)
    lash = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:bai_meizhen.water_lash" and c.target_ids == (LEE,))
    qi_before = bai.resources["resource:bai_meizhen.qi"]
    engine.execute_intent(intent_for(lash, intent_id="lash"))
    assert engine.state.pending_resolution is not None
    pending = engine.legal_candidates()
    assert {c.kind for c in pending} == {CandidateKind.OPTIONAL_RIDER, CandidateKind.TAKE_NO_OPTIONAL_ACTION}
    rider = next(c for c in pending if c.kind == CandidateKind.OPTIONAL_RIDER)
    engine.execute_intent(intent_for(rider, intent_id="whip"))
    assert bai.resources["resource:bai_meizhen.qi"] == qi_before - 1
    assert engine.state.pending_resolution is None


def test_declining_water_whip_spends_no_qi():
    seed = find_seed_for_hit(bonus=7, ac=14)
    engine = prepared_engine(seed, BAI)
    engine.state.actors[BAI].position = Position(x=8, y=8)
    engine.state.actors[LEE].position = Position(x=13, y=8)
    lash = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:bai_meizhen.water_lash" and c.target_ids == (LEE,))
    qi_before = engine.state.actors[BAI].resources["resource:bai_meizhen.qi"]
    engine.execute_intent(intent_for(lash, intent_id="lash-decline"))
    decline = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.TAKE_NO_OPTIONAL_ACTION)
    engine.execute_intent(intent_for(decline, intent_id="decline-whip"))
    assert engine.state.actors[BAI].resources["resource:bai_meizhen.qi"] == qi_before


def test_concentration_replacement_removes_prior_zone():
    engine = prepared_engine("CONCENTRATION", LING)
    ling = engine.state.actors[LING]
    fake = ActionIntent(intent_id="zone", decision_id="z", candidate_id="z", state_version=0, actor_id=LING)
    with engine._transaction("action:ling_qi.forgotten_vale_nocturne", "zone-one", LING):
        engine._resolve_zone_action(ling, ACTIONS["action:ling_qi.forgotten_vale_nocturne"], Position(x=12, y=6), fake, zone_kind="NOCTURNE")
    first_zone = next(iter(engine.state.zones.values()))
    assert first_zone.active
    # Use the same exact concentration action again at a new center; prior zone must end first.
    with engine._transaction("action:ling_qi.forgotten_vale_nocturne", "zone-two", LING):
        engine._resolve_zone_action(ling, ACTIONS["action:ling_qi.forgotten_vale_nocturne"], Position(x=14, y=6), fake, zone_kind="NOCTURNE")
    assert not first_zone.active
    active = [z for z in engine.state.zones.values() if z.active]
    assert len(active) == 1
    assert active[0].center == Position(x=14, y=6)
    assert any(e.event_type == "ZONE_REMOVED" and e.payload["reason"] == "REPLACED" for e in engine.events)


def test_cui_command_is_nested_first_class_activation_and_default_dodge_exists():
    engine = prepared_engine("CUI-COMMAND", BAI)
    bai = engine.state.actors[BAI]
    cui = engine.state.actors[CUI]
    target = engine.state.actors[AN]
    bai.position = Position(x=12, y=8)
    cui.position = Position(x=11, y=8)
    target.position = Position(x=8, y=8)
    command = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:bai_meizhen.command_cui" and c.target_ids == (AN,))
    engine.execute_intent(intent_for(command, intent_id="command-cui", options=("STRIKE",)))
    assert CUI in engine.state.actors
    assert CUI not in engine.state.initiative_order
    assert engine._commanded_cui_this_turn
    assert any(e.actor_id == CUI and e.event_type in {"MOVEMENT_COMMITTED", "ATTACK_ROLLED"} for e in engine.events)

    default_engine = prepared_engine("CUI-DEFAULT", BAI)
    default_engine.end_turn("bai-default")
    cui_default = default_engine.state.actors[CUI]
    assert any(c.condition_id == "condition:core.dodge" for c in cui_default.conditions.values())
    assert any(e.event_type == "COMPANION_DEFAULT_APPLIED" for e in default_engine.events)


def test_nonlethal_defeat_and_primary_only_victory_ignore_cui():
    engine = prepared_engine("VICTORY", AN)
    fake = ActionIntent(intent_id="victory", decision_id="v", candidate_id="v", state_version=0, actor_id=AN)
    with engine._transaction("system:test.victory", "victory", AN):
        engine._commit_damage(engine.state.actors[LING], 999, "TEST", "system:test.victory", AN, fake, reaction_depth=0)
        engine._commit_damage(engine.state.actors[BAI], 999, "TEST", "system:test.victory", AN, fake, reaction_depth=0)
    assert engine.state.actors[CUI].active
    assert engine.state.terminal_result is not None
    assert engine.state.terminal_result.winning_team_id == engine.state.actors[AN].team_id
    assert engine.state.actors[BAI].current_hp == 0
    assert not engine.state.actors[BAI].active
    assert all(e.source_definition_id for e in engine.events)


def test_resource_underflow_rolls_back_transaction():
    engine = prepared_engine("ROLLBACK", AN)
    an = engine.state.actors[AN]
    before = engine.export().canonical_state_sha256
    with pytest.raises(CombatGate1Error):
        with engine._transaction("system:test.underflow", "underflow", AN):
            engine._spend_resource(an, "resource:an_eui.stamina", 999, "system:test.underflow")
    assert engine.export().canonical_state_sha256 == before
