from __future__ import annotations

from pathlib import Path

import pytest

from combat.diagnostics import CombatGate1Error
from combat.gate2_engine import Gate2Engine
from combat.gate2_grid import SquareGrid
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate2_runtime_content import AN, BAI, CUI, LEE, LING
from combat.gate2_runtime_models import ActionIntent, CandidateKind, DiceSpec, Position, ReactionDecision

ROOT = Path(__file__).resolve().parents[1]


def intent_for(candidate, *, intent_id="test:intent", options=(), reactions=()):
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


def test_roll_authority_is_platform_stable_and_critical_doubles_dice_only():
    a = DeterministicRollAuthority("SAME-SEED")
    b = DeterministicRollAuthority("SAME-SEED")
    rows_a = [a.d20(modifier=4, actor_id=AN, reason="test").model_dump(mode="json") for _ in range(5)]
    rows_b = [b.d20(modifier=4, actor_id=AN, reason="test").model_dump(mode="json") for _ in range(5)]
    assert rows_a == rows_b
    roller = DeterministicRollAuthority("CRIT")
    normal = roller.roll(DiceSpec(count=2, sides=6, modifier=4), actor_id=AN, reason="normal")
    critical = roller.roll(DiceSpec(count=2, sides=6, modifier=4), actor_id=AN, reason="critical", critical=True)
    assert len(normal.dice) == 2
    assert len(critical.dice) == 4
    assert normal.modifier == critical.modifier == 4
    assert normal.counter_end < critical.counter_end


def test_square_grid_blocking_cost_corner_los_cover_and_compression():
    grid = SquareGrid.load(ROOT / "combat_gate1/generated/Battlefield.json")
    assert not grid.in_bounds((-1, 0))
    assert grid.shortest_path(Position(x=8, y=0), Position(x=9, y=0)) is None
    path, cost = grid.shortest_path(Position(x=8, y=6), Position(x=9, y=6))
    assert cost == 10  # Qi-hazard terrain cost 2.
    assert grid.distance_ft(Position(x=0, y=0), Position(x=2, y=2)) == 10
    assert grid.cover_bonus(Position(x=2, y=4), Position(x=8, y=4)) == 2
    assert grid.line_of_sight(Position(x=2, y=4), Position(x=8, y=4))
    compressed = grid.compress_path((Position(x=0, y=0), Position(x=1, y=0), Position(x=2, y=0), Position(x=2, y=1)))
    assert compressed == (Position(x=0, y=0), Position(x=2, y=0), Position(x=2, y=1))


def test_match_creation_has_four_primaries_and_first_class_cui():
    engine = Gate2Engine(ROOT, match_seed="KERNEL-CREATION")
    assert set(engine.state.actors) == {AN, LEE, LING, BAI, CUI}
    assert CUI not in engine.state.initiative_order
    assert engine.state.actors[CUI].owner_id == BAI
    assert not engine.state.actors[CUI].primary_combatant
    assert len(engine.state.initiative_order) == 4
    assert all(event.source_definition_id for event in engine.events)
    assert [event.sequence for event in engine.events] == list(range(1, len(engine.events) + 1))


def test_candidates_are_state_bound_and_stale_intent_rejects_without_mutation():
    engine = Gate2Engine(ROOT, match_seed="STALE")
    end = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
    stale = intent_for(end, intent_id="stale")
    # Commit a harmless hold, changing the state version.
    hold = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.HOLD_POSITION)
    engine.execute_intent(intent_for(hold, intent_id="hold"))
    before = engine.export().canonical_state_sha256
    with pytest.raises(CombatGate1Error) as caught:
        engine.execute_intent(stale)
    assert caught.value.diagnostic.code == "GATE2_STALE_OR_ILLEGAL_CANDIDATE"
    assert engine.export().canonical_state_sha256 == before


def test_move_candidate_commits_only_canonical_path_and_budget():
    engine = Gate2Engine(ROOT, match_seed="MOVE")
    actor = engine.state.actors[engine.state.current_actor_id]
    moves = [c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE]
    assert moves
    candidate = min(moves, key=lambda c: (c.movement_cost_ft, c.destination.y, c.destination.x))
    before = actor.movement_remaining_ft
    engine.execute_intent(intent_for(candidate, intent_id="move"))
    assert actor.position == candidate.destination
    assert actor.movement_remaining_ft == before - candidate.movement_cost_ft
    assert engine.events[-1].event_type == "MOVEMENT_COMMITTED"
    assert engine.events[-1].source_definition_id == "system:combat.movement"


def test_stamina_guard_integration_spends_once_and_reduces_pending_damage():
    engine = Gate2Engine(ROOT, match_seed="STAMINA-INTEGRATION")
    an = engine.state.actors[AN]
    before_hp = an.current_hp
    before_stamina = an.resources["resource:an_eui.stamina"]
    fake_intent = ActionIntent(
        intent_id="damage:test",
        decision_id="decision:test",
        candidate_id="candidate:test",
        state_version=engine.state.state_version,
        actor_id=engine.state.current_actor_id,
        reaction_decisions=(ReactionDecision(
            checkpoint="DAMAGE_APPLICATION",
            reactor_id=AN,
            reaction_source_id="reaction:core.stamina_guard",
            selection="USE",
            spend=2,
        ),),
    )
    with engine._transaction("system:test.damage", fake_intent.intent_id, engine.state.current_actor_id):
        engine._commit_damage(an, 20, "TEST", "system:test.damage", LING, fake_intent, reaction_depth=0)
    assert an.resources["resource:an_eui.stamina"] == before_stamina - 2
    assert 0 <= before_hp - an.current_hp <= 20
    spent = [e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == "reaction:core.stamina_guard"]
    assert len(spent) == 1
    reactions = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "reaction:core.stamina_guard"]
    assert len(reactions) == 1


def test_engine_exposes_no_generic_arbitrary_delta_api():
    engine = Gate2Engine(ROOT, match_seed="NO-DELTA")
    prohibited = {"apply_delta", "set_state", "mutate_state", "arbitrary_resource_gain", "arbitrary_condition"}
    assert prohibited.isdisjoint(set(dir(engine)))
