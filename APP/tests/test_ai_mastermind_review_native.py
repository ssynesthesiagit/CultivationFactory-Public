"""Native decision/intent regressions for the review findings; all models fake."""
from combat import ai_lookahead, ai_mastermind, menu_rank
from combat.ai_tactics import make_plan
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import OWNER, context_for, fight
from tests.test_ai_mastermind import Offline


def offline(monkeypatch):
    client = Offline()
    monkeypatch.setattr(menu_rank, "default_client", lambda: client)
    monkeypatch.setattr(menu_rank, "_CLIENT", client)


def test_expired_optional_snapshot_still_uses_mastermind_and_every_native_option(tmp_path, monkeypatch):
    offline(monkeypatch)
    monkeypatch.setattr(ai_lookahead, "own_snapshot", lambda *a, **kw: None)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    assert "simulation" not in context.tactics
    assert isinstance(make_plan(context), ai_mastermind.MastermindPlan)
    choice = LocalDeterministicController().choose_primary_action(context)
    assert "Play: " in choice.record.explanation
    native_moves = {c.candidate_id for c in context.legal_candidates if c.kind == "MOVE"}
    assert native_moves <= {s.candidate_id for s in choice.record.scored_alternatives}
    session.engine.execute_intent(choice.intent)


def test_expired_flight_annotation_keeps_complete_native_menu(tmp_path, monkeypatch):
    from combat import flight_decision
    from combat.target_knowledge import actors_for
    offline(monkeypatch)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    engine = session.engine
    actor = engine.state.actors[OWNER]
    def forbidden(*args):
        raise AssertionError("No expensive geometry after the shared deadline")
    monkeypatch.setattr(flight_decision, "_geometric", forbidden)
    rows = flight_decision.annotate(engine, context.legal_candidates, OWNER,
                                   actors_for(engine, actor), deadline=0)
    assert [c.candidate_id for c in rows] == [c.candidate_id for c in context.legal_candidates]
    assert all(not c.metadata["flight_tactics"]["destination"]["evaluated"] for c in rows if c.kind == "MOVE")


def test_observation_squares_share_only_one_immutable_sense_frame(tmp_path, monkeypatch):
    from combat import senses, read_queries
    from combat.ext.ai_movement import observation_frame
    offline(monkeypatch)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               flight=True, foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    engine = session.engine
    actor = engine.state.actors[OWNER]
    before = engine.state.model_dump(mode="json")
    original = senses.perceives_cell
    computations = []
    def counted(engine, actor, position):
        read_queries.memo(engine, ("test:observation-sense", actor.entity_id),
                          lambda: computations.append(actor.position))
        return original(engine, actor, position)
    monkeypatch.setattr(senses, "perceives_cell", counted)
    first = observation_frame(engine, actor, context.legal_candidates, context.policy)
    assert len(first.squares) > 10
    assert len(computations) == 1
    assert observation_frame(engine, actor, context.legal_candidates, context.policy) == first
    assert len(computations) == 2
    assert engine.state.model_dump(mode="json") == before


def test_rollout_continues_our_play_policy_without_nested_search(tmp_path, monkeypatch):
    from combat.gate4_context import build_decision_context
    offline(monkeypatch)
    combat, _, session = fight(tmp_path, ["FIRE_TAL_FLAME_LASH"], band="rival/boss",
                               foe_at={"x": 3, "y": 7})
    context = context_for(combat, session)
    belief = ai_lookahead.projected_engine(context)
    assert belief is not None
    projected = build_decision_context(belief, context.policy, for_ai=True)
    assert isinstance(make_plan(projected), ai_mastermind.MastermindPlan)
    assert "simulation" not in projected.tactics
    def forbidden(*args, **kwargs):
        raise AssertionError("A speculative continuation may not recurse or call transports")
    monkeypatch.setattr(ai_lookahead, "verify", forbidden)
    monkeypatch.setattr(ai_mastermind.embedding_rank, "rank_options", forbidden)
    choice = LocalDeterministicController().choose_primary_action(projected)
    assert "Play: " in choice.record.explanation
    belief.execute_intent(choice.intent)
    # The other creature still uses its generic Tricky reply, never our Dao.
    belief.end_turn()
    reply = build_decision_context(belief, context.policy, for_ai=True)
    assert reply.tactics["tier"] == "TRICKY"
    assert not isinstance(make_plan(reply), ai_mastermind.MastermindPlan)


def test_spent_action_cannot_keep_a_burst_play_alive(tmp_path, monkeypatch):
    offline(monkeypatch)
    combat, _, session = fight(tmp_path, ["AIR_BASE_WIND_LASH"], band="rival/boss",
                               foe_at={"x": 3, "y": 7})
    engine = session.engine
    context = context_for(combat, session)
    strike = next(c for c in context.legal_candidates if c.kind == "ACTION"
                  and context.tactics["actions"].get(c.source_definition_id, {}).get("damage"))
    from combat.gate2_runtime_models import ActionIntent
    engine.execute_intent(ActionIntent(intent_id="review:spend-attack", actor_id=OWNER,
        decision_id=strike.decision_id, candidate_id=strike.candidate_id,
        state_version=strike.state_version, target_ids=strike.target_ids))
    assert not engine.state.actors[OWNER].action_available
    context = context_for(combat, session)
    plan = ai_mastermind.MastermindPlan(context)
    assert not plan.has_strike, [(c.display_name, c.metadata.get("expected_damage"),
        plan.actions.get(c.source_definition_id)) for c in context.legal_candidates
        if c.kind in {"ACTION", "BONUS_ACTION"}]
    assert all(p["id"] != "control_burst" for p in plan.plays)
    choice = LocalDeterministicController().choose_primary_action(context)
    assert "Bind, then burst" not in choice.record.explanation
    engine.execute_intent(choice.intent)
