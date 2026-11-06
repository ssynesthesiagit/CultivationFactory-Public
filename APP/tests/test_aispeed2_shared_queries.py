"""AISPEED2: one decision's shared facts must equal an uncached computation.

The built-in AI now shares pure, per-decision facts (zone membership and grants,
Speed, flight capability, support, terrain cover, perception, recalled rosters)
across every sampled square and option root. These regressions prove the caches
return what a cold query returns, and that the chosen action is identical when
the sharing is switched off.
"""
import pytest

from combat import read_queries, zones
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from tests.test_ai_flight_options import flyer_fight


def test_zone_grants_and_membership_match_a_cold_query(tmp_path):
    combat, _, mid, _ = flyer_fight(tmp_path)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    with read_queries.candidate_pass(engine):
        first = zones.current_inside_grants(engine, actor)
        second = zones.current_inside_grants(engine, actor)
        areas = zones.typed_zones(engine)
        inside = [zones._inside(engine, actor, zone) for zone in areas]
    assert second == first
    cold = zones._current_inside_grants(engine, actor)
    assert cold == first
    assert inside == [zones._inside(engine, actor, zone) for zone in areas]


def _context(combat, mid):
    session = combat._load_session(mid)
    engine = session.engine
    policy, _ = combat.policies.for_actor(engine.state.current_actor_id)
    candidates = combat._legal_candidates(session, knowledge_only=True)
    context = build_decision_context(engine, policy, for_ai=True, prepared_candidates=candidates)
    return context, LocalDeterministicController().choose_primary_action(context)


def test_sharing_off_changes_no_candidate_or_choice(tmp_path, monkeypatch):
    combat, _, mid, _ = flyer_fight(tmp_path)
    shared, shared_choice = _context(combat, mid)

    # Disable every sharing layer; each query recomputes as it did before.
    monkeypatch.setattr(read_queries, "enumeration_cache", lambda engine: None)
    monkeypatch.setattr(read_queries, "memo", lambda engine, key, compute: compute())
    monkeypatch.setattr(read_queries, "invariant_query",
                        lambda engine, key, compute, refs=(): compute())
    monkeypatch.setattr(read_queries, "shared_query",
                        lambda engine, key, compute, refs=(): compute())
    cold, cold_choice = _context(combat, mid)

    assert [c.candidate_id for c in cold.legal_candidates] == [c.candidate_id for c in shared.legal_candidates]
    assert [c.model_dump(mode="json") for c in cold.legal_candidates] == [
        c.model_dump(mode="json") for c in shared.legal_candidates]
    assert cold_choice.intent.candidate_id == shared_choice.intent.candidate_id
    assert cold_choice.intent.option_ids == shared_choice.intent.option_ids


def test_athletics_rows_follow_a_movement_selection_made_inside_the_frame():
    """bind() changes earned rows without a recorded state change; the key must see it."""
    from types import SimpleNamespace

    from combat import movement_sequences
    from combat.ext import athletics
    from combat.gate2_runtime_models import Position

    feature = "TAL_ATHLETICS_HEAVEN_TREADING_BODY"
    row = {"block": athletics.BLOCK, "kind": "heaven_treading", "feature_id": feature}
    actor = SimpleNamespace(entity_id="a", position=Position(x=0, y=0), conditions={})
    engine = SimpleNamespace(state=SimpleNamespace(state_version=0, event_sequence=0),
                             typed_passive_rows={"a": [row]})
    engine._movement_sequence = {"actor_id": "a"}
    with read_queries.read_frame(engine):
        assert "heaven_treading" in athletics.rows_of(engine, actor)
        movement_sequences.bind(engine, actor, "motion", [feature], [])
        assert "heaven_treading" not in athletics.rows_of(engine, actor)
